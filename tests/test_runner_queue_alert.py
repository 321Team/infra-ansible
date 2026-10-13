import copy
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('queue_alert',ROOT/'tools/ansible-ci-queue-alert.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)
NOW=dt.datetime(2026,10,13,0,0,tzinfo=dt.timezone.utc)
SHA='a'*40
ENV={'ANSIBLE_QUEUE_ALERT_ENABLED':'true','ANSIBLE_QUEUE_ALERT_RECIPIENTS':'reviewer,operator',
     'GITHUB_REPOSITORY':m.REPO,'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'schedule',
     'GITHUB_WORKFLOW_REF':m.NOTICE_WORKFLOW,'GITHUB_SHA':SHA,'GITHUB_WORKFLOW_SHA':SHA,
     'GITHUB_RUN_ID':'99','GITHUB_RUN_ATTEMPT':'1'}


def run():
    return {'id':10,'run_attempt':1,'head_sha':SHA,'repository':{'full_name':m.REPO},'path':m.WORKFLOW}


def job():
    return {'id':20,'run_id':10,'run_attempt':1,'labels':sorted(m.watch.EXPECTED_LABELS),
            'status':'queued','created_at':'2026-10-12T23:40:00Z'}


class API:
    def __init__(self,*,runs=None,jobs=None,comments=None,fail=False,run_status='queued'):
        self.runs=[run()] if runs is None else runs
        self.jobs=[job()] if jobs is None else jobs
        self.comments=[] if comments is None else comments
        self.calls=[];self.fail=fail;self.main_sha=SHA;self.run_status=run_status

    def call(self,path,*,body=None):
        self.calls.append((path,copy.deepcopy(body)))
        if '/actions/workflows/' in path:
            if self.fail:raise m.AlertError('API_READ_FAILED')
            rows=self.runs if f'status={self.run_status}&' in path else []
            return {'total_count':len(rows),'workflow_runs':copy.deepcopy(rows)}
        if '/attempts/' in path:return {'total_count':len(self.jobs),'jobs':copy.deepcopy(self.jobs)}
        if path.endswith('/commits/main'):return {'sha':self.main_sha}
        if path==m.ISSUE:return {'number':61,'state':'open','comments':len(self.comments)}
        if '/comments?' in path:return copy.deepcopy(self.comments)
        if body is not None:
            assert path==m.ISSUE+'/comments'
            return {'id':80,'body':body['body'],'user':{'login':'github-actions[bot]','type':'Bot'},
                    'html_url':f'https://github.com/{m.REPO}/issues/61#issuecomment-80'}
        raise AssertionError(path)


def observation(api=None):
    value=m.collect(api or API(),threshold_minutes=10,now=NOW)
    value['observed_at_utc']=NOW.isoformat()
    return value


def comment(digest,*,bot=True):
    return {'body':f'<!-- p1-ansible-queue-alert:v1:{digest} -->\noriginal',
            'user':{'login':'github-actions[bot]' if bot else 'human','type':'Bot' if bot else 'User'}}


class QueueCollectionTests(unittest.TestCase):
    def test_overdue_job_is_attention_not_runner_absence_or_go(self):
        api=API();value=observation(api)
        self.assertEqual(value['alerts'][0]['reason'],'QUEUED_THRESHOLD_EXCEEDED')
        self.assertEqual(value['state'],'ATTENTION')
        self.assertFalse(any('/runners' in p or b for p,b in api.calls))

    def test_empty_queue_is_no_alert_without_claiming_ci_success(self):
        self.assertEqual(observation(API(runs=[]))['state'],'NO_ALERT')

    def test_active_workflow_other_status_does_not_hide_queued_job(self):
        for status in m.ACTIVE_STATUSES:
            self.assertEqual(observation(API(run_status=status))['state'],'ATTENTION')

    def test_run_transition_deduplicates_only_unchanged_identity(self):
        api=API();original=api.call
        def moved(path,*,body=None):
            if 'status=in_progress&' in path:
                return {'total_count':1,'workflow_runs':[run()]}
            return original(path,body=body)
        api.call=moved
        self.assertEqual(observation(api)['active_runs_read'],1)
        def replaced(path,*,body=None):
            if 'status=in_progress&' in path:
                r=run();r['run_attempt']=2
                return {'total_count':1,'workflow_runs':[r]}
            return original(path,body=body)
        api.call=replaced
        with self.assertRaisesRegex(m.AlertError,'RUN_CHANGED_DURING_READ'):observation(api)

    def test_young_job_suppressed(self):
        j=job();j['created_at']='2026-10-12T23:59:00Z'
        self.assertEqual(observation(API(jobs=[j]))['alerts'],[])

    def test_threshold_boundary_included(self):
        j=job();j['created_at']='2026-10-12T23:50:00Z'
        self.assertEqual(observation(API(jobs=[j]))['state'],'ATTENTION')

    def test_missing_or_malformed_timestamp_is_attention(self):
        for value in (None,'bad',123,'2026-10-12T23:40:00'):
            with self.subTest(value=value):
                j=job();j['created_at']=value
                self.assertEqual(observation(API(jobs=[j]))['alerts'][0]['reason'],'QUEUED_AGE_UNKNOWN')

    def test_future_timestamp_not_treated_as_young(self):
        j=job();j['created_at']='2026-10-13T01:00:00Z'
        self.assertEqual(observation(API(jobs=[j]))['alerts'][0]['reason'],'QUEUED_TIMESTAMP_IN_FUTURE')

    def test_other_labels_not_included(self):
        j=job();j['labels']=['ubuntu-latest']
        self.assertEqual(observation(API(jobs=[j]))['alerts'],[])

    def test_job_that_started_during_collection_not_alerted(self):
        for status in ('in_progress','completed','waiting'):
            j=job();j['status']=status
            self.assertEqual(observation(API(jobs=[j]))['alerts'],[])

    def test_attempt_mismatch_bool_and_duplicate_rejected(self):
        for mutate in (lambda j:j.update(run_attempt=2),lambda j:j.update(run_attempt=True),
                       lambda j:j.update(run_id=11),lambda j:j.update(id=True)):
            j=job();mutate(j)
            with self.assertRaises(m.AlertError):observation(API(jobs=[j]))
        with self.assertRaises(m.AlertError):observation(API(jobs=[job(),job()]))

    def test_wrong_repo_workflow_head_and_duplicate_run_rejected(self):
        for key,value in [('repository',{}),('repository','bad'),('head_sha','bad'),('path','other.yml')]:
            r=run();r[key]=value
            with self.assertRaises(m.AlertError):observation(API(runs=[r]))
        with self.assertRaises(m.AlertError):observation(API(runs=[run(),run()]))

    def test_pagination_limit_and_incomplete_lists_fail_closed(self):
        for data in ({'total_count':101,'jobs':[]},{'total_count':1,'jobs':[]},
                     {'total_count':True,'jobs':[job()]},{'jobs':[]}):
            with self.assertRaises(m.AlertError):m.page(data,'jobs',100)

    def test_threshold_bounds_fail(self):
        for value in (0,1441,True,1.5):
            with self.assertRaises(m.AlertError):m.collect(API(),threshold_minutes=value,now=NOW)


class NotificationTests(unittest.TestCase):
    def test_changed_attention_posts_only_to_fixed_issue_once(self):
        api=API();result=m.notify(api,observation(),env=ENV,threshold=10)
        writes=[(p,b) for p,b in api.calls if b]
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0][0],m.ISSUE+'/comments')
        self.assertIn('@operator @reviewer',writes[0][1]['body'])
        self.assertEqual(result['human_receipt'],'NOT_CONFIRMED')

    def test_unchanged_state_no_repeated_comment(self):
        obs=observation();digest=m.state_hash(obs,['operator','reviewer'],10)
        api=API(comments=[comment(digest)])
        self.assertEqual(m.notify(api,obs,env=ENV,threshold=10)['status'],'UNCHANGED_NO_COMMENT')
        self.assertFalse(any(b for _,b in api.calls))

    def test_initial_no_alert_is_silent(self):
        api=API();result=m.notify(api,observation(API(runs=[])),env=ENV,threshold=10)
        self.assertEqual(result['status'],'NO_ALERT_NO_COMMENT')

    def test_recovery_is_reported_once_without_claiming_job_success(self):
        api=API(comments=[comment('b'*64)])
        result=m.notify(api,observation(API(runs=[])),env=ENV,threshold=10)
        body=[b['body'] for _,b in api.calls if b][0]
        self.assertEqual(result['status'],'COMMENT_POSTED')
        self.assertIn('CI PASS·공급/정리 성공·O02 인수 완료 판정은 아닙니다',body)

    def test_human_marker_cannot_suppress_notification(self):
        obs=observation();digest=m.state_hash(obs,['operator','reviewer'],10)
        api=API(comments=[comment(digest,bot=False)])
        self.assertEqual(m.notify(api,obs,env=ENV,threshold=10)['status'],'COMMENT_POSTED')

    def test_read_failure_is_not_normal_clear(self):
        obs={'state':'READ_ERROR','alerts':[],'error':'API_READ_FAILED','observed_at_utc':NOW.isoformat()}
        api=API(comments=[comment('b'*64)])
        m.notify(api,obs,env=ENV,threshold=10)
        body=[b['body'] for _,b in api.calls if b][0]
        self.assertIn('정상 해소로 처리하지 않습니다',body)

    def test_main_changed_never_posts(self):
        api=API();api.main_sha='b'*40
        with self.assertRaisesRegex(m.AlertError,'NOTIFICATION_MAIN_CHANGED'):
            m.notify(api,observation(),env=ENV,threshold=10)
        self.assertFalse(any(b for _,b in api.calls))

    def test_incomplete_or_excessive_comment_history_never_posts(self):
        for total in (1,1001):
            api=API();original=api.call
            def incomplete(path,*,body=None):
                if path==m.ISSUE:return {'number':61,'state':'open','comments':total}
                return original(path,body=body)
            api.call=incomplete
            with self.assertRaises(m.AlertError):m.notify(api,observation(),env=ENV,threshold=10)
            self.assertFalse(any(b for _,b in api.calls))

    def test_malformed_write_response_is_unconfirmed_without_second_post(self):
        api=API();original=api.call
        def broken(path,*,body=None):
            result=original(path,body=body)
            if body is not None:result['user']=None
            return result
        api.call=broken
        with self.assertRaisesRegex(m.AlertError,'COMMENT_WRITE_UNCONFIRMED'):
            m.notify(api,observation(),env=ENV,threshold=10)
        self.assertEqual(sum(b is not None for _,b in api.calls),1)

    def test_disabled_branch_other_repo_workflow_and_retry_rejected_before_api(self):
        for key,value in [('ANSIBLE_QUEUE_ALERT_ENABLED','false'),('GITHUB_REF','refs/heads/topic'),
                          ('GITHUB_REPOSITORY','other/repo'),('GITHUB_WORKFLOW_REF','bad'),
                          ('GITHUB_EVENT_NAME','pull_request'),('GITHUB_RUN_ATTEMPT','2')]:
            env=dict(ENV);env[key]=value;api=API()
            with self.assertRaises(m.AlertError):m.notify(api,observation(),env=env,threshold=10)
            self.assertEqual(api.calls,[])

    def test_recipients_are_explicit_bounded_and_no_markdown(self):
        for value in ('','user,user','@user','team/member','user\n@everyone',','.join('user'+str(n) for n in range(6))):
            with self.assertRaises(m.AlertError):m.recipients(value)

    def test_state_digest_ignores_observation_clock_but_binds_recipient_and_threshold(self):
        a=observation();b=copy.deepcopy(a);b['observed_at_utc']='later'
        self.assertEqual(m.state_hash(a,['user'],10),m.state_hash(b,['user'],10))
        self.assertNotEqual(m.state_hash(a,['user'],10),m.state_hash(b,['other'],10))
        self.assertNotEqual(m.state_hash(a,['user'],10),m.state_hash(b,['user'],11))


class ApiAndCliTests(unittest.TestCase):
    def test_no_arbitrary_write_endpoint(self):
        with mock.patch.object(m.shutil,'which',return_value='gh'):
            with self.assertRaisesRegex(m.AlertError,'WRITE_SCOPE_REJECTED'):
                m.GitHub().call('repos/other/repo/issues/1/comments',body={'body':'x'})

    def test_write_timeout_not_retried_and_raw_error_not_disclosed(self):
        with mock.patch.object(m.shutil,'which',return_value='gh'), \
             mock.patch.object(m.subprocess,'run',side_effect=subprocess.TimeoutExpired('gh',10)) as child:
            with self.assertRaisesRegex(m.AlertError,'^COMMENT_WRITE_UNCONFIRMED$'):
                m.GitHub().call(m.ISSUE+'/comments',body={'body':'x'})
            self.assertEqual(child.call_count,1)

    def test_cli_default_does_not_post_or_read_runner_inventory(self):
        api=API()
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'observation.json'
            with mock.patch.object(m,'GitHub',return_value=api),mock.patch.object(m.watch,'utc_now',return_value=NOW), \
                 mock.patch.object(sys,'argv',['alert','--threshold-minutes','10','--output',str(output)]), \
                 mock.patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(m.main(),0)
            value=json.loads(output.read_text())
            self.assertEqual(value['notification']['status'],'DRY_RUN_NO_COMMENT')
            self.assertEqual(value['runner_presence'],'NOT_QUERIED')
            self.assertFalse(value['supply_authorized'])
            self.assertTrue(Path(str(output)+'.sha256').exists())
            self.assertFalse(any('/runners' in p or b for p,b in api.calls))

    def test_cli_api_failure_is_saved_as_error_not_empty_success(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'observation.json'
            with mock.patch.object(m,'GitHub',return_value=API(fail=True)), \
                 mock.patch.object(sys,'argv',['alert','--threshold-minutes','10','--output',str(output)]), \
                 mock.patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(m.main(),1)
            self.assertEqual(json.loads(output.read_text())['state'],'READ_ERROR')

    def test_cli_existing_output_stops_before_api(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'observation.json';output.write_text('original')
            with mock.patch.object(m,'GitHub') as api, \
                 mock.patch.object(sys,'argv',['alert','--threshold-minutes','10','--output',str(output)]), \
                 mock.patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(m.main(),1)
                api.assert_not_called()
            self.assertEqual(output.read_text(),'original')


if __name__=='__main__':unittest.main()
