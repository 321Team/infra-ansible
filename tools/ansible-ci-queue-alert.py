#!/usr/bin/env python3
"""Bounded queued-job notice; never supplies a Runner or infers Runner absence.

Default: GitHub reads + local observation only. --notify can append one changed
state notice to the fixed operations Issue #82 from the enabled main workflow.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

SPEC = importlib.util.spec_from_file_location('queue_watch', Path(__file__).with_name('ansible-ci-queue-watch.py'))
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)
REPO = watch.REPO
WORKFLOW = '.github/workflows/ansible-regression.yml'
ACTIVE_STATUSES = ('queued', 'in_progress', 'requested', 'waiting', 'pending')
NOTICE_WORKFLOW = f'{REPO}/.github/workflows/ansible-queue-alert.yml@refs/heads/main'
ISSUE_NUMBER = 82
ISSUE = f'repos/{REPO}/issues/{ISSUE_NUMBER}'
MARKER = re.compile(r'^<!-- p1-ansible-queue-alert:v1:([0-9a-f]{64}) -->\n')
LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?')


class AlertError(RuntimeError):
    pass


def need(ok, code):
    if not ok:
        raise AlertError(code)


def positive(value):
    return type(value) is int and value > 0


class GitHub:
    """Fixed caller-generated REST paths; no retries or raw errors in receipts."""
    def __init__(self):
        self.deadline = time.monotonic() + 120

    def call(self, path, *, body=None):
        left = self.deadline - time.monotonic()
        need(left > 0, 'API_BUDGET_EXHAUSTED')
        gh = shutil.which('gh')
        need(gh is not None, 'GH_CLI_NOT_FOUND')
        cmd = [gh, 'api', '--hostname', 'github.com', '-X', 'POST' if body is not None else 'GET', path]
        data = None
        if body is not None:
            need(path == ISSUE + '/comments' and set(body) == {'body'}, 'WRITE_SCOPE_REJECTED')
            cmd += ['--input', '-']
            data = json.dumps(body, ensure_ascii=True).encode()
        try:
            r = subprocess.run(cmd, input=data, capture_output=True,
                               timeout=min(10, left), env=watch.clean_env())
        except (OSError, subprocess.TimeoutExpired):
            raise AlertError('COMMENT_WRITE_UNCONFIRMED' if body is not None else 'API_READ_FAILED') from None
        need(r.returncode == 0, 'COMMENT_WRITE_UNCONFIRMED' if body is not None else 'API_READ_FAILED')
        need(len(r.stdout) <= 2 * 1024 * 1024, 'API_RESPONSE_TOO_LARGE')
        try:
            return json.loads(r.stdout.decode('utf-8'))
        except (UnicodeError, ValueError):
            raise AlertError('API_RESPONSE_INVALID') from None


def page(value, key, limit):
    need(type(value) is dict and type(value.get('total_count')) is int and
         0 <= value['total_count'] <= limit, 'API_LIST_LIMIT_OR_SHAPE')
    rows = value.get(key)
    need(type(rows) is list and len(rows) == value['total_count'] and
         all(type(x) is dict for x in rows), 'API_LIST_INCOMPLETE')
    return rows


def collect(api, *, threshold_minutes, now):
    need(type(threshold_minutes) is int and 1 <= threshold_minutes <= 1440, 'THRESHOLD_INVALID')
    # A workflow can be in_progress while one of its jobs remains queued.
    # Reads are not an atomic snapshot; identical runs moving between lists
    # are deduplicated, while a changed identity aborts this observation.
    run_map = {}
    for status in ACTIVE_STATUSES:
        rows = page(api.call(f'repos/{REPO}/actions/workflows/ansible-regression.yml/runs?status={status}&per_page=100'),
                    'workflow_runs', 20)
        page_ids = set()
        for run in rows:
            rid = run.get('id')
            need(positive(rid) and rid not in page_ids, 'RUN_IDENTITY_INVALID')
            page_ids.add(rid)
            if rid in run_map:
                need(all(run.get(k) == run_map[rid].get(k)
                         for k in ('run_attempt','head_sha','path','repository')), 'RUN_CHANGED_DURING_READ')
            else:
                run_map[rid] = run
            need(len(run_map) <= 20, 'ACTIVE_RUN_LIMIT_EXCEEDED')
    runs = list(run_map.values())
    alerts, seen_runs, seen_jobs = [], set(), set()
    for run in runs:
        rid, attempt, sha = run.get('id'), run.get('run_attempt'), run.get('head_sha')
        need(positive(rid) and positive(attempt) and isinstance(sha, str) and watch.SHA40.fullmatch(sha),
             'RUN_IDENTITY_INVALID')
        need(rid not in seen_runs and run.get('path') == WORKFLOW and
             type(run.get('repository')) is dict and
             run['repository'].get('full_name') == REPO, 'RUN_SCOPE_INVALID')
        seen_runs.add(rid)
        # A listed run may start while being read. Jobs are re-read for its exact attempt.
        jobs = page(api.call(f'repos/{REPO}/actions/runs/{rid}/attempts/{attempt}/jobs?per_page=100'), 'jobs', 100)
        for job in jobs:
            jid = job.get('id')
            need(positive(jid) and jid not in seen_jobs and type(job.get('run_id')) is int and
                 job['run_id'] == rid and type(job.get('run_attempt')) is int and
                 job['run_attempt'] == attempt and type(job.get('labels')) is list,
                 'JOB_IDENTITY_INVALID')
            seen_jobs.add(jid)
            need(len(seen_jobs) <= 100, 'TOTAL_JOB_LIMIT_EXCEEDED')
            labels = job['labels']
            need(all(isinstance(x, str) for x in labels), 'JOB_LABELS_INVALID')
            need(job.get('status') in ('queued','in_progress','completed','waiting','pending','requested'),
                 'JOB_STATUS_INVALID')
            if not watch.EXPECTED_LABELS <= set(labels) or job['status'] != 'queued':
                continue
            try:
                created = watch.parse_time(job.get('created_at'))
            except (watch.WatchError, TypeError, AttributeError):
                created = None
            if created is None:
                reason = 'QUEUED_AGE_UNKNOWN'
            elif created > now:
                reason = 'QUEUED_TIMESTAMP_IN_FUTURE'
            elif (now-created).total_seconds() < threshold_minutes*60:
                continue
            else:
                reason = 'QUEUED_THRESHOLD_EXCEEDED'
            alerts.append({'run_id':rid, 'attempt':attempt, 'job_id':jid,
                           'observed_run_head_sha':sha, 'reason':reason})
    return {'state':'ATTENTION' if alerts else 'NO_ALERT',
            'alerts':sorted(alerts, key=lambda x:(x['run_id'],x['job_id'])),
            'active_runs_read':len(runs), 'jobs_read':len(seen_jobs)}


def recipients(value):
    names = value.split(',') if isinstance(value, str) else []
    need(1 <= len(names) <= 5 and len(names) == len(set(names)) and
         all(LOGIN.fullmatch(x) for x in names), 'RECIPIENTS_REQUIRED')
    return sorted(names)


def notification_context(env):
    need(env.get('ANSIBLE_QUEUE_ALERT_ENABLED') == 'true', 'NOTIFICATION_NOT_ENABLED')
    need(env.get('GITHUB_REPOSITORY') == REPO and env.get('GITHUB_REF') == 'refs/heads/main' and
         env.get('GITHUB_EVENT_NAME') in ('schedule','workflow_dispatch') and
         env.get('GITHUB_WORKFLOW_REF') == NOTICE_WORKFLOW and
         isinstance(env.get('GITHUB_SHA'),str) and watch.SHA40.fullmatch(env['GITHUB_SHA']) and
         env.get('GITHUB_WORKFLOW_SHA') == env['GITHUB_SHA'], 'NOTIFICATION_MAIN_CONTEXT_REQUIRED')
    need(positive(int(env.get('GITHUB_RUN_ID','0'))) and env.get('GITHUB_RUN_ATTEMPT') == '1',
         'NOTIFICATION_FIRST_ATTEMPT_REQUIRED')
    return recipients(env.get('ANSIBLE_QUEUE_ALERT_RECIPIENTS'))


def state_hash(observation, names, threshold):
    state = {k:observation[k] for k in ('state','alerts')}
    state.update(recipients=names, threshold_minutes=threshold, error=observation.get('error'))
    return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def previous_notice(api):
    issue = api.call(ISSUE)
    need(type(issue) is dict and issue.get('number') == ISSUE_NUMBER and issue.get('state') == 'open' and
         'pull_request' not in issue and type(issue.get('comments')) is int and
         0 <= issue['comments'] <= 1000, 'OWNER_ISSUE_UNAVAILABLE')
    for n in range(max(1,math.ceil(issue['comments']/100)),0,-1):
        rows = api.call(ISSUE+f'/comments?per_page=100&page={n}')
        need(type(rows) is list and all(type(x) is dict for x in rows), 'COMMENT_LIST_INVALID')
        need(min(100, max(0, issue['comments']-(n-1)*100)) <= len(rows) <= 100,
             'COMMENT_LIST_INCOMPLETE')
        for row in reversed(rows):
            author=row.get('user')
            need(type(author) is dict, 'COMMENT_AUTHOR_INVALID')
            body=row.get('body')
            if author.get('login')=='github-actions[bot]' and author.get('type')=='Bot' and isinstance(body,str):
                m=MARKER.match(body)
                if m:return m.group(1)
    return None


def render(observation, names, digest, run_id):
    lines=[f'<!-- p1-ansible-queue-alert:v1:{digest} -->',
           '### Ansible 격리 Job 대기 관측', '', ' '.join('@'+x for x in names), '',
           f"관측: `{observation['observed_at_utc']}` · 상태 `{observation['state']}`."]
    if observation['state']=='READ_ERROR':
        lines += ['조회 실패로 현재 대기를 판정하지 못했습니다. 기존 경고를 정상 해소로 처리하지 않습니다.',
                  '오류 분류: `'+observation['error']+'`.']
    elif observation['alerts']:
        for a in observation['alerts']:
            lines += [f"- [Run {a['run_id']} / Job {a['job_id']}](https://github.com/{REPO}/actions/runs/{a['run_id']}/job/{a['job_id']}) · Attempt {a['attempt']} · `{a['reason']}` · 관측 SHA `{a['observed_run_head_sha']}`"]
        lines += ['', 'Runner 등록/online/busy는 이 감시가 조회하지 않았습니다. 미공급 확정이나 공급 GO가 아닙니다.',
                  '기존 운영자 카드의 exact HEAD/Job/labels/중복·창 확인과 1회 queue-watch 분류 뒤 판단하세요.']
    else:
        lines += ['현재 조회에서 알림 조건이 해소됐습니다. CI PASS·공급/정리 성공·O02 인수 완료 판정은 아닙니다.']
    lines += ['', f'[감시 Run](https://github.com/{REPO}/actions/runs/{run_id}) · [운영자 카드](https://github.com/{REPO}/blob/main/docs/runbooks/Ansible-CI-Operator-Card.md)',
              '이 감시는 token 발급·Runner 공급/삭제·Job 재실행/취소·설정 변경을 하지 않습니다.']
    return '\n'.join(lines)+'\n'


def notify(api, observation, *, env, threshold):
    names=notification_context(env)
    main=api.call(f'repos/{REPO}/commits/main')
    need(type(main) is dict and main.get('sha')==env['GITHUB_SHA'], 'NOTIFICATION_MAIN_CHANGED')
    digest=state_hash(observation,names,threshold)
    previous=previous_notice(api)
    if previous==digest:return {'status':'UNCHANGED_NO_COMMENT','state_sha256':digest}
    if previous is None and observation['state']=='NO_ALERT':
        return {'status':'NO_ALERT_NO_COMMENT','state_sha256':digest}
    body=render(observation,names,digest,int(env['GITHUB_RUN_ID']))
    result=api.call(ISSUE+'/comments',body={'body':body})
    need(type(result) is dict and positive(result.get('id')) and result.get('body')==body and
         type(result.get('user')) is dict and result['user'].get('login')=='github-actions[bot]' and
         result['user'].get('type')=='Bot' and
         result.get('html_url')==f"https://github.com/{REPO}/issues/{ISSUE_NUMBER}#issuecomment-{result['id']}",
         'COMMENT_WRITE_UNCONFIRMED')
    return {'status':'COMMENT_POSTED','comment_url':result['html_url'],'state_sha256':digest,
            'human_receipt':'NOT_CONFIRMED'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--threshold-minutes',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--notify',action='store_true')
    args=p.parse_args()
    try:
        need(1 <= args.threshold_minutes <= 1440,'THRESHOLD_INVALID')
        need(not args.output.exists() and not Path(str(args.output)+'.sha256').exists(),'OUTPUT_ALREADY_EXISTS')
        if args.notify:notification_context(os.environ)
        api=GitHub();now=watch.utc_now()
        try:
            observation=collect(api,threshold_minutes=args.threshold_minutes,now=now)
        except AlertError as exc:
            observation={'state':'READ_ERROR','alerts':[],'error':str(exc)}
        observation.update(schema='infra-ansible.queue-notice.v1',repository=REPO,
            observed_at_utc=now.isoformat(),threshold_minutes=args.threshold_minutes,
            runner_presence='NOT_QUERIED',supply_authorized=False)
        observation['notification']={'status':'DRY_RUN_NO_COMMENT'}
        if args.notify:
            try:observation['notification']=notify(api,observation,env=os.environ,threshold=args.threshold_minutes)
            except AlertError as exc:observation['notification']={'status':'UNCONFIRMED','error':str(exc)}
        watch.write_observation(args.output,observation)
        print(json.dumps(observation,ensure_ascii=True,sort_keys=True))
        return 1 if observation['state']=='READ_ERROR' or observation['notification']['status']=='UNCONFIRMED' else 0
    except (AlertError,watch.WatchError,ValueError,OSError):
        print('{"status":"STOP","notification":"NOT_CONFIRMED","supply_authorized":false}')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
