"""PR34 R2 failure simulations. No remote process or packet is permitted."""
import copy
import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_post_egress as E


WINDOW_VALIDATOR = E.REMOTE.validate_window


def wall_clock(value):
    class FixedClock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return value if tz is None else value.astimezone(tz)
    return types.SimpleNamespace(datetime=FixedClock, timezone=datetime.timezone,
                                 timedelta=datetime.timedelta)


class RemoteClockLeaseTests(E.NoLiveActions):
    def test_request_and_packet_guard_never_read_remote_wall_clock(self):
        fixture = E.ObservationFixture(self)
        expected = fixture.preflight()
        verifier = fixture.verifier('verify', expected)
        class ForbiddenWallClock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                raise AssertionError('Remote UTC must not authorize the work window')
        with patch.object(E.REMOTE, 'datetime', types.SimpleNamespace(
                datetime=ForbiddenWallClock, timezone=datetime.timezone)):
            E.REMOTE.validate_request(verifier.req)
            result = verifier.execute()
        self.assertTrue(result['observation']['negative_ipv4_probe']['pass'])
        self.assertEqual(fixture.sent, ['k8s-control01'])

    def test_remote_wall_clock_offset_and_steps_do_not_authorize_or_block_packet(self):
        for hours in (-12, 12, 0, -24, 24):
            with self.subTest(remote_wall_offset_hours=hours):
                fixture = E.ObservationFixture(self)
                with patch.object(E.REMOTE, 'validate_window', side_effect=WINDOW_VALIDATOR), \
                        patch.object(E.REMOTE, 'datetime', wall_clock(E.NOW + datetime.timedelta(hours=hours))):
                    expected = fixture.preflight()
                    verifier = fixture.verifier('verify', expected)
                    E.REMOTE.validate_request(verifier.req)
                    result = verifier.execute()
                self.assertTrue(result['observation']['negative_ipv4_probe']['pass'])
                self.assertEqual(fixture.sent, ['k8s-control01'])

    def test_late_arrival_cannot_reset_fixed_expiry_even_with_new_verifier(self):
        fixture = E.ObservationFixture(self)
        expected = fixture.preflight()
        deadline = E.clock_binding()['deadline_boottime_ns']
        for arrival in (deadline, deadline + 1, deadline + 3_600_000_000_000):
            for attempt in range(2):
                with self.subTest(arrival=arrival, attempt=attempt), patch.object(
                        E.REMOTE, 'clock_snapshot', return_value={
                            'boot_id': E.BOOT_ID, 'boottime_ns': arrival}):
                    with self.assertRaises(ValueError):
                        fixture.verifier('verify', expected).execute()
                self.assertEqual(fixture.sent, [])

    def test_boot_switch_or_counter_before_calibration_blocks_packet(self):
        fixture = E.ObservationFixture(self)
        expected = fixture.preflight()
        for snapshot in (
                {'boot_id': 'ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee',
                 'boottime_ns': E.SAMPLED_BOOTTIME_NS + 1},
                {'boot_id': E.BOOT_ID, 'boottime_ns': E.SAMPLED_BOOTTIME_NS - 1}):
            with self.subTest(snapshot=snapshot), patch.object(
                    E.REMOTE, 'clock_snapshot', return_value=snapshot):
                with self.assertRaises(ValueError):
                    fixture.verifier('verify', expected).execute()
            self.assertEqual(fixture.sent, [])

    def test_fixed_lease_rejects_malformed_or_unbound_time_values(self):
        cases = [('boot_id', 'bad'), ('sampled_boottime_ns', True),
                 ('sampled_boottime_ns', -1), ('deadline_boottime_ns', True),
                 ('deadline_boottime_ns', E.SAMPLED_BOOTTIME_NS),
                 ('controller_received_at', '2026-09-21T13:05:00'),
                 ('controller_received_at', E.END),
                 ('controller_received_at', '2026-09-21T12:59:59+09:00'),
                 ('deadline_boottime_ns', E.clock_binding()['deadline_boottime_ns'] + 1), ('extra', 1)]
        for key, value in cases:
            request = E.remote_request()
            request['clock_binding'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                E.REMOTE.validate_request(request)
        for missing in E.clock_binding():
            request = E.remote_request()
            request['clock_binding'].pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                E.REMOTE.validate_request(request)

    def test_clock_binding_missing_from_legacy_request_is_rejected(self):
        request = E.remote_request()
        request.pop('clock_binding')
        with self.assertRaises(ValueError):
            E.REMOTE.validate_request(request)

    def test_remote_command_timeout_cannot_outlast_remaining_lease(self):
        fixture = E.ObservationFixture(self)
        verifier = fixture.verifier()
        deadline = verifier.req['clock_binding']['deadline_boottime_ns']
        observed = []
        verifier.runner = lambda argv, timeout: observed.append(timeout) or {
            'argv': argv, 'rc': 0, 'stdout': '', 'stderr': ''}
        with patch.object(E.REMOTE, 'clock_snapshot', return_value={
                'boot_id': E.BOOT_ID, 'boottime_ns': deadline - 4_000_000_000}):
            verifier.read_command(['/usr/sbin/iptables-save'], timeout=20)
        self.assertEqual(len(observed), 1)
        self.assertLessEqual(observed[0], 3)
        with patch.object(E.REMOTE, 'clock_snapshot', return_value={
                'boot_id': E.BOOT_ID, 'boottime_ns': deadline - 1_000_000_000}):
            with self.assertRaises(ValueError):
                verifier.read_command(['/usr/sbin/iptables-save'], timeout=20)
        self.assertEqual(len(observed), 1)

    def test_counter_moving_backwards_within_an_observation_blocks_packet(self):
        fixture = E.ObservationFixture(self)
        expected = fixture.preflight()
        verifier = fixture.verifier('verify', expected)
        with patch.object(E.REMOTE, 'clock_snapshot', side_effect=[
                {'boot_id': E.BOOT_ID, 'boottime_ns': E.SAMPLED_BOOTTIME_NS + 3_000_000_000},
                {'boot_id': E.BOOT_ID, 'boottime_ns': E.SAMPLED_BOOTTIME_NS + 2_000_000_000}]), \
                patch.object(verifier, 'preservation', return_value=expected):
            with self.assertRaisesRegex(ValueError, 'backwards'):
                verifier.send()
        self.assertEqual(fixture.sent, [])


class ControllerClockCalibrationTests(E.NoLiveActions):
    def test_generated_clock_payload_reads_only_boot_id_and_boot_clock(self):
        fixture = E.PipelineFixture(self)
        controller = fixture.controller
        reads = []
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if str(path) == '/proc/sys/kernel/random/boot_id':
                reads.append(str(path))
                return E.BOOT_ID + '\n'
            return read_text(path, *args, **kwargs)

        def command(phase, argv, timeout=60, env=None):
            command_value = json.loads(argv[argv.index('-a') + 1])
            output = io.StringIO()
            with patch.object(Path, 'read_text', read), \
                    patch.object(E.REMOTE.time, 'clock_gettime_ns', return_value=E.SAMPLED_BOOTTIME_NS) as clock, \
                    E.contextlib.redirect_stdout(output):
                exec(compile(command_value['stdin'], 'LOCAL_MOCK_CLOCK_PAYLOAD', 'exec'), {})
            clock.assert_called_once_with(E.REMOTE.time.CLOCK_BOOTTIME)
            destination = Path(argv[argv.index('--tree') + 1])
            (destination / 'k8s-control01').write_text(json.dumps({'rc': 0, 'stdout': output.getvalue()}))
            return {'returncode': 0, 'timed_out': False, 'interrupted': False, 'output_limit': False}

        with patch.object(controller, 'mutation_guard'), patch.object(controller, 'run_command', side_effect=command), \
                patch.object(E.CONTROLLER, 'datetime', wall_clock(E.NOW)):
            binding = controller.clock_binding('k8s-control01')
        self.assertEqual(reads, ['/proc/sys/kernel/random/boot_id'])
        self.assertEqual(binding['sampled_boottime_ns'], E.SAMPLED_BOOTTIME_NS)

    def exchange(self, transform=None, result_update=None, received=E.NOW):
        fixture = E.PipelineFixture(self)
        controller = fixture.controller
        host = 'k8s-control01'
        calls = []

        def command(phase, argv, timeout=60, env=None):
            calls.append((phase, timeout))
            destination = Path(argv[argv.index('--tree') + 1])
            request = json.loads((destination.parent / 'REQUEST.json').read_text())
            response = dict(request, status='OK', changed=False, clock={
                'boot_id': E.BOOT_ID, 'boottime_ns': E.SAMPLED_BOOTTIME_NS})
            if transform:
                transform(response)
            (destination / host).write_text(json.dumps({'rc': 0, 'stdout': json.dumps(response)}))
            result = {'returncode': 0, 'timed_out': False, 'interrupted': False, 'output_limit': False}
            result.update(result_update or {})
            return result

        with patch.object(controller, 'mutation_guard'), patch.object(controller, 'run_command', side_effect=command), \
                patch.object(E.CONTROLLER, 'datetime', wall_clock(received)):
            binding = controller.clock_binding(host)
        return binding, fixture, calls

    def test_controller_receipt_maps_to_fixed_deadline_with_full_transport_margin(self):
        binding, fixture, calls = self.exchange()
        self.assertEqual(binding, dict(E.clock_binding(),
                                       controller_received_at=E.NOW.astimezone(datetime.timezone.utc).isoformat()))
        self.assertEqual(calls, [('clock-k8s-control01', 30)])
        saved = json.loads((fixture.controller.root / 'CLOCK_BINDINGS.json').read_text())
        self.assertEqual(saved, {'k8s-control01': binding})
        with patch.object(fixture.controller, 'mutation_guard'), \
                patch.object(fixture.controller, 'run_command') as run, \
                patch.object(E.CONTROLLER, 'datetime', wall_clock(E.NOW + datetime.timedelta(minutes=20))):
            reused = fixture.controller.clock_binding('k8s-control01')
        self.assertEqual(reused, binding)
        run.assert_not_called()
        reused['deadline_boottime_ns'] += 1
        self.assertEqual(fixture.controller.clock_bindings['k8s-control01'], binding)

    def test_delayed_calibration_receipt_shortens_instead_of_renewing_budget(self):
        for delay in (1, 10, 30, 600):
            with self.subTest(delay_seconds=delay):
                binding, fixture, calls = self.exchange(received=E.NOW + datetime.timedelta(seconds=delay))
                self.assertEqual(binding['deadline_boottime_ns'],
                                 E.clock_binding()['deadline_boottime_ns'] - delay * 1_000_000_000)

    def test_wrong_or_malformed_calibration_binding_never_caches(self):
        cases = [('host', 'k8s-worker01'), ('followup_run_id', 'ntp-post-egress-' + 'c' * 32),
                 ('request_id', 'c' * 32), ('window_end', E.START), ('schema_version', True),
                 ('status', 'STOP'), ('changed', True), ('unexpected', 'field')]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(E.CONTROLLER.W.StateUncertain):
                self.exchange(transform=lambda response: response.update({key: value}))
        for value in ({}, {'boot_id': 'invalid', 'boottime_ns': 1},
                      {'boot_id': E.BOOT_ID, 'boottime_ns': True},
                      {'boot_id': E.BOOT_ID, 'boottime_ns': 0},
                      {'boot_id': E.BOOT_ID, 'boottime_ns': 10, 'utc': E.NOW.isoformat()}):
            with self.subTest(clock=value), self.assertRaises(E.CONTROLLER.W.StateUncertain):
                self.exchange(transform=lambda response: response.update(clock=value))

    def test_failed_or_interrupted_transport_cannot_establish_clock_binding(self):
        for update in ({'returncode': 2}, {'timed_out': True}, {'interrupted': True}, {'output_limit': True}):
            with self.subTest(update=update), self.assertRaises(E.CONTROLLER.W.StateUncertain):
                self.exchange(result_update=update)

    def test_expired_or_margin_only_calibration_receipt_is_refused(self):
        end = datetime.datetime.fromisoformat(E.END)
        for received in (end, end + datetime.timedelta(hours=1), end - datetime.timedelta(seconds=9)):
            with self.subTest(received=received), self.assertRaises(ValueError):
                self.exchange(received=received)

    def test_calibration_requires_full_thirty_second_command_and_ten_second_margin(self):
        fixture = E.PipelineFixture(self)
        with patch.object(fixture.controller, 'mutation_guard'), \
                patch.object(E.CONTROLLER, 'datetime', wall_clock(E.NOW)), \
                patch.object(E.CONTROLLER.R, 'validate_window', return_value=(E.NOW, E.NOW + datetime.timedelta(seconds=39))), \
                patch.object(E.CONTROLLER.W.OnePass, 'run_command') as run:
            with self.assertRaisesRegex(ValueError, 'cleanup margin'):
                fixture.controller.clock_binding('k8s-control01')
            run.assert_not_called()
        self.assertEqual(fixture.controller.clock_bindings, {})


class FailureEvidenceTests(E.NoLiveActions):
    def test_primary_failure_survives_simultaneous_preservation_failure(self):
        fixture = E.ObservationFixture(self)
        expected = fixture.preflight()
        verifier = fixture.verifier('verify', expected)
        fixture.journal.close = lambda: None
        output = io.StringIO()
        with patch.object(E.REMOTE, 'ReadOnlyJournal', return_value=fixture.journal), \
                patch.object(E.REMOTE, 'Verifier', return_value=verifier), \
                patch.object(E.REMOTE, 'load_base', return_value=E.BASE), \
                patch.object(E.BASE.Engine, 'identity'), \
                patch.object(verifier, 'preservation', side_effect=[expected, OSError('preservation reread failed')]), \
                patch.object(verifier.engine, 'verify', side_effect=ValueError('negative counter failed')), \
                E.contextlib.redirect_stdout(output):
            code = E.REMOTE.main(verifier.req, E.BASE_SOURCE, E.KERNEL_SOURCE)
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'STOP')
        self.assertIn('negative counter failed', result['error'])
        self.assertEqual(result['operation_error'], {'type': 'ValueError', 'message': 'negative counter failed'})
        self.assertEqual(result['preservation_error'], {'type': 'OSError', 'message': 'preservation reread failed'})
        self.assertTrue(result['preservation_uncertain'])
        self.assertEqual(result['details']['preservation_before'], expected)
        self.assertIsNone(result['details']['preservation_after'])


class ControllerPinnedDependencyTests(E.NoLiveActions):
    def test_remote_module_hash_is_checked_before_any_module_body_executes(self):
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        tools = directory / 'tools'
        tools.mkdir()
        for filename in ('ntp-post-egress.py', 'ntp-onepass.py', 'ntp-post-egress-remote.py',
                         'ntp-kernel-contract.py'):
            (tools / filename).write_bytes((E.ROOT / 'tools' / filename).read_bytes())
        remote = tools / 'ntp-post-egress-remote.py'
        marker = directory / 'UNREVIEWED_MODULE_EXECUTED'
        remote.write_text('from pathlib import Path\nPath(%r).write_text("executed")\n' % str(marker) +
                          remote.read_text())
        controller = tools / 'ntp-post-egress.py'
        with self.assertRaisesRegex(ValueError, 'dependency bytes differ'):
            E.load_module('tampered_post_followup_local_fixture', controller)
        self.assertFalse(marker.exists())

    def test_embedded_remote_pin_matches_exact_file_bytes(self):
        self.assertEqual(E.CONTROLLER.REMOTE_SHA256,
                         hashlib.sha256((E.ROOT / 'tools/ntp-post-egress-remote.py').read_bytes()).hexdigest())

    def test_kernel_module_hash_is_checked_before_any_module_body_executes(self):
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        tools = directory / 'tools'
        tools.mkdir()
        for filename in ('ntp-post-egress.py', 'ntp-onepass.py', 'ntp-post-egress-remote.py',
                         'ntp-kernel-contract.py'):
            (tools / filename).write_bytes((E.ROOT / 'tools' / filename).read_bytes())
        kernel = tools / 'ntp-kernel-contract.py'
        marker = directory / 'UNREVIEWED_KERNEL_EXECUTED'
        kernel.write_text('from pathlib import Path\nPath(%r).write_text("executed")\n' % str(marker) +
                          kernel.read_text())
        with self.assertRaisesRegex(ValueError, 'dependency bytes differ'):
            E.load_module('tampered_kernel_contract_local_fixture', tools / 'ntp-post-egress.py')
        self.assertFalse(marker.exists())

    def test_only_the_exact_pinned_kernel_source_loads(self):
        self.assertEqual(E.REMOTE.KERNEL_SHA256,
                         hashlib.sha256(E.KERNEL_SOURCE.encode()).hexdigest())
        for source in (None, E.KERNEL_SOURCE + '\n', '# unreviewed kernel contract\n'):
            with self.subTest(source_type=type(source).__name__), self.assertRaises(ValueError):
                E.REMOTE.load_kernel(source)

    def test_expired_controller_window_refuses_before_clock_or_probe_submission(self):
        fixture = E.PipelineFixture(self)
        controller = fixture.controller
        with patch.object(controller, 'assert_sources'), patch.object(controller, 'verify_input'), \
                patch.dict(E.os.environ, {'CR_NTP_FOLLOWUP_APPROVED': E.CONTROLLER.W.CHANGE_ID}, clear=True), \
                patch.object(E.CONTROLLER.R, 'datetime', wall_clock(datetime.datetime.fromisoformat(E.END))), \
                patch.object(controller, 'run_command') as run:
            with self.assertRaisesRegex(ValueError, 'Outside'):
                controller.remote('preflight', 'k8s-control01')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
