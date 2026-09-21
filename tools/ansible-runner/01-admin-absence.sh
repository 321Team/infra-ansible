#!/bin/bash
set -euo pipefail
umask 077
TASK_KIT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$TASK_KIT_ROOT/common-start.sh"
check_login server01_ansible ansible01 /home/server01_ansible
cd -- "$TASK_KIT_ROOT"
sha256sum -c SHA256SUMS
TASK_EVIDENCE=$(mktemp -d "$TASK_LOGIN_HOME/ansible-runner-id4-absence.XXXXXXXX")
mkdir -- "$TASK_EVIDENCE/evidence"
finish() {
  local rc=$?
  trap - EXIT
  printf '%s\n' "$rc" > "$TASK_EVIDENCE/evidence/execution.rc"
  (cd -- "$TASK_EVIDENCE/evidence" && sha256sum -- ./*.json ./*.log execution.rc > SHA256SUMS)
  tar -czf "$TASK_EVIDENCE/ansible-runner-absence.tar.gz" -C "$TASK_EVIDENCE" evidence
  (cd -- "$TASK_EVIDENCE" && sha256sum ansible-runner-absence.tar.gz > ansible-runner-absence.tar.gz.sha256)
  printf 'HOME_EVIDENCE=%s\n' "$TASK_EVIDENCE/ansible-runner-absence.tar.gz"
  exit "$rc"
}
printf '{"repository":"321Team/infra-ansible","runner_id":4,"runner_name":"ansible-ci-cffaab5978b74334828fc94e91fc9de7"}\n' > "$TASK_EVIDENCE/evidence/EXPECTED.json"
: > "$TASK_EVIDENCE/evidence/query.stderr.log"
trap finish EXIT
gh api --hostname github.com --method GET --paginate --slurp \
  'repos/321Team/infra-ansible/actions/runners?per_page=100' \
  > "$TASK_EVIDENCE/evidence/pages.json" 2> "$TASK_EVIDENCE/evidence/query.stderr.log"
python3 -I -B - "$TASK_EVIDENCE/evidence" <<'PY'
import datetime, json, sys
from pathlib import Path
d = Path(sys.argv[1])
pages = json.loads((d/'pages.json').read_text())
valid = (isinstance(pages,list) and bool(pages) and
         all(isinstance(p,dict) and type(p.get('total_count')) is int and
             p['total_count'] >= 0 and isinstance(p.get('runners'),list) for p in pages))
rows = [r for p in pages for r in p['runners']] if valid else []
valid = valid and all(isinstance(r,dict) and type(r.get('id')) is int and
                      isinstance(r.get('name'),str) for r in rows)
valid = valid and len({r['id'] for r in rows}) == len(rows) and all(p['total_count']==len(rows) for p in pages)
matches = [r for r in rows if r.get('id')==4 or r.get('name')=='ansible-ci-cffaab5978b74334828fc94e91fc9de7'] if valid else []
result = {'status':'PASS_ABSENT' if valid and not matches else 'FAIL_REVIEW_REQUIRED',
          'queried_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'repository':'321Team/infra-ansible','runner_id':4,
          'runner_name':'ansible-ci-cffaab5978b74334828fc94e91fc9de7',
          'complete_query':valid,'matching_count':len(matches) if valid else None,
          'deletion_performed':False}
(d/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print('STATUS='+result['status'])
raise SystemExit(0 if valid and not matches else 1)
PY
