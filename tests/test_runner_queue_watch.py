import datetime as dt
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "queued_watch",
    ROOT / "tools" / "ansible-ci-queue-watch.py",
)
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)

NOW = dt.datetime(2026, 10, 1, 6, 0, tzinfo=dt.timezone.utc)
EXPECTED = ["self-hosted", "Linux", "X64", "fds-ci", "ansible-isolated"]


def job(status="queued", created_at="2026-10-01T05:50:00Z", labels=None):
    return {
        "id": 110000000001,
        "run_id": 36800000001,
        "run_attempt": 4,
        "name": "regression",
        "status": status,
        "conclusion": None,
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "labels": EXPECTED if labels is None else labels,
    }


def run():
    return {
        "id": 36800000001,
        "run_attempt": 4,
        "event": "pull_request",
        "head_sha": "b" * 40,
        "html_url": "https://github.com/321Team/infra-ansible/actions/runs/36800000001",
        "created_at": "2026-10-01T05:49:00Z",
    }


def runner(name="ansible-ci-test", status="online", busy=False, labels=None):
    labels = EXPECTED if labels is None else labels
    return {
        "id": 7,
        "name": name,
        "status": status,
        "busy": busy,
        "labels": [{"name": value} for value in labels],
    }


class QueueWatchTests(unittest.TestCase):
    def classify(self, current_job, runners, threshold=5):
        return watch.classify(
            current_job,
            run(),
            runners,
            threshold_minutes=threshold,
            now=NOW,
            expected_source_sha="a" * 40,
        )

    def test_old_queued_job_without_matching_runner_requires_action(self):
        result = self.classify(job(), [])
        self.assertEqual(result["classification"], "EPHEMERAL_RUNNER_NOT_SUPPLIED")
        self.assertTrue(result["action_required"])
        self.assertEqual(result["runner_observation"]["matching_count"], 0)
        self.assertEqual(result["run"]["expected_source_sha"], "a" * 40)

    def test_matching_online_runner_prevents_missing_runner_classification(self):
        result = self.classify(job(), [runner()])
        self.assertEqual(result["classification"], "QUEUED_WITH_MATCHING_RUNNER_ONLINE")
        self.assertFalse(result["action_required"])
        self.assertEqual(result["runner_observation"]["matching_online_count"], 1)

    def test_matching_offline_runner_does_not_count_as_online_supply(self):
        result = self.classify(job(), [runner(status="offline")])
        self.assertEqual(result["classification"], "EPHEMERAL_RUNNER_NOT_SUPPLIED")
        self.assertEqual(result["runner_observation"]["matching_count"], 1)
        self.assertEqual(result["runner_observation"]["matching_online_count"], 0)

    def test_young_queued_job_stays_in_grace(self):
        current = job(created_at="2026-10-01T05:58:00Z")
        result = self.classify(current, [])
        self.assertEqual(result["classification"], "QUEUED_WITHIN_GRACE")
        self.assertFalse(result["action_required"])

    def test_in_progress_and_completed_are_not_supply_alerts(self):
        for status, expected in (
            ("in_progress", "JOB_IN_PROGRESS"),
            ("completed", "JOB_COMPLETED"),
        ):
            with self.subTest(status=status):
                result = self.classify(job(status=status), [])
                self.assertEqual(result["classification"], expected)
                self.assertFalse(result["action_required"])

    def test_non_isolated_job_is_not_classified_as_missing_runner(self):
        result = self.classify(job(labels=["self-hosted", "Linux", "X64"]), [])
        self.assertEqual(result["classification"], "NOT_ANSIBLE_ISOLATED_JOB")
        self.assertFalse(result["action_required"])

    def test_invalid_expected_source_sha_is_rejected(self):
        with self.assertRaisesRegex(watch.WatchError, "EXPECTED_SOURCE_SHA_INVALID"):
            watch.classify(
                job(),
                run(),
                [],
                threshold_minutes=5,
                now=NOW,
                expected_source_sha="not-a-sha",
            )

    def test_runner_extra_labels_are_allowed_but_required_labels_are_not_optional(self):
        extra = runner(labels=EXPECTED + ["extra"])
        result = self.classify(job(), [extra])
        self.assertEqual(result["classification"], "QUEUED_WITH_MATCHING_RUNNER_ONLINE")

        missing = runner(labels=EXPECTED[:-1])
        result = self.classify(job(), [missing])
        self.assertEqual(result["classification"], "EPHEMERAL_RUNNER_NOT_SUPPLIED")

    def test_clean_env_removes_debug_controls_without_touching_auth(self):
        original = watch.os.environ.copy()
        try:
            watch.os.environ["GH_DEBUG"] = "api"
            watch.os.environ["GH_FORCE_TTY"] = "1"
            watch.os.environ["ACTIONS_STEP_DEBUG"] = "true"
            watch.os.environ["ACTIONS_RUNNER_DEBUG"] = "true"
            watch.os.environ["GH_TOKEN"] = "test-placeholder"
            env = watch.clean_env()
        finally:
            watch.os.environ.clear()
            watch.os.environ.update(original)

        self.assertNotIn("GH_DEBUG", env)
        self.assertNotIn("GH_FORCE_TTY", env)
        self.assertNotIn("ACTIONS_STEP_DEBUG", env)
        self.assertNotIn("ACTIONS_RUNNER_DEBUG", env)
        self.assertEqual(env.get("GH_TOKEN"), "test-placeholder")


if __name__ == "__main__":
    unittest.main()
