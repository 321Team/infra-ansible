# Issue9 — worker02 canary의 다음 실행 준비

2026-10-09 KST · CODEX_ASSISTED · 이권욱. **설계 및 범위 수정 검증 / 운영 실행 NOT_RUN.** 책임 [Issue9](https://github.com/321Team/infra-ansible/issues/9). 이 문서는 다음 회차의 구체적 검토안이며 DNS role 채택·현장 GO·기존 AC 변경을 확정하지 않는다.

## 확보한 입력과 재사용

- [일반 CI Issue5 종결](https://github.com/321Team/infra-ansible/issues/5#issuecomment-5845142603): 2026-09-26 인수. 이를 후보 엔진 운영 전환으로 확대하지 않는다.
- [증적184](https://github.com/321Team/fds-project-evidence/tree/0ff20e904502ebee58f14c5303f1d44ffb50d144/evidence/P1-ANS-01/controller-canary-preparation-20261009T092827): 10/9 09:28 조회. 운영 checkout `/home/server01_ansible/p1-ans-01`은 `e1c4458cf95dacca76870d7b9b012f8615f6974a`, 별도 DNS 시험 checkout `/home/server01_ansible/worker02-dns-stage.yJfHG0vS/source`는 `5111c66f233fe0f84e2d63cef3837fe091a2a268`. 조회 뒤 변동은 실행 직전 확인한다.
- 운영 checkout에는 명시적 엔진 helper가 없고 별도 checkout에는 있다. 이 PR의 로컬 수정은 두 서버 경로에 설치되지 않았다.
- 후보 bin은 `/home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-2.21.3/bin`. system RPM/전역 PATH는 유지한다. 파일·설치 선언 관측과 실제 CLI 실행 결과를 구분한다.
- worker02 SSH hardening 적용2회/changed0·신규 SSH는 [증적113](https://github.com/321Team/fds-project-evidence/pull/113), DNS verify 성공은 [증적167](https://github.com/321Team/fds-project-evidence/pull/167). 같은 분기 반복을 위해 정상 키나 DNS를 고의로 변경하지 않는다.

## 다음 후보와 현재 코드의 한계

권장 검토 후보는 **worker02 한 대의 DNS resolver role**이다. 단일 대상 verify·명시적 후보 엔진과 기존 role을 재사용할 수 있다. SSH 키 복구는 현재 복원이 필요한 drift가 확인되지 않았고, 정상 키를 고의 손상시켜 시험하지 않는다. MON/NTP/Harbor는 이번 후보에 섞지 않는다. 실제 role 채택은 실행안과 함께 Lead가 확정한다.

| 구간 | 현재 구현 | 다음 회차에 필요한 것 |
|---|---|---|
| DNS verify | `verify-worker02`에 controller scope guard, worker02만 접속 | 증적167 재사용. 실제 변경 뒤 사후 확인이 필요할 때만 새 회차 실행 |
| DNS apply | `workers`는 worker01·02·03 전체, serial1 | worker02 전용 apply/reapply 진입점과 controller guard 구현·독립 리뷰. 현재 workers 또는 직접 `--limit`로 대체하지 않음 |
| 명시적 rollback | 기존 playbook은 전체 k8s_nodes facts 수집 뒤 대상 외 end_host | 이 변경에서 승인·정확한 host 검사를 controller에서 먼저 수행하고, 지정 host만 facts/복구 대상으로 선택 |
| 복구 원본 | role은 고정 `cr_dns_state_dir/original-resolver.json`을 `force: false`로 최초 보존 | 과거 baseline 원본과 이번 회차 직전 상태를 분리. 후속 코드에서 새 회차의 보호된 백업 경로·hash와 apply/reapply/rollback 결합 필요 |

범위 수정은 다른 노드에 대한 불필요한 facts 접속을 막는다. **오래된 백업의 적합성은 해결하지 않는다.** 기존 파일을 삭제하거나 덮어써 신선한 백업처럼 만들지 않는다. 현재 원본의 값이 이번 회차 직전 상태와 같다는 확인 없이 수동 rollback을 시험 명령으로 실행하지 않는다. 자동 rescue는 같은 apply에서 읽은 메모리의 사전값을 사용하고, 수동 rollback은 보존 파일을 사용하므로 두 경로를 구분한다.

## rollback 범위 수정 계약

`scripts/cr-p1-ans-01-01-run.sh rollback HOST` 인터페이스는 유지한다. controller의 첫 play는 become/facts 없이 target 정의·문자열·비어 있지 않음·기존 CR 승인 token, k8s_nodes 멤버십, 동명 group 부재, inventory pattern의 정확한 단일 host 일치를 확인한다. 두 번째 play의 host는 그 고정 target이다. 기존 원본 소유 검증과 실제 복구 태스크는 그대로다.

잘못된 대상·그룹·패턴·승인 누락은 managed-host facts 전에 nonzero로 종료한다. 기존 허용 노드를 worker02로 강제 축소하지 않으며 worker02 단독 창에서는 worker02만 선택한다. 검토된 inventory/config/변수와 정상 wrapper 호출이 전제다. 직접 `--limit`·tags·임의 변수를 통해 guard를 생략하는 호출, 악의적인 inventory plugin, endpoint 진위나 동시 변경까지 이 guard가 방어한다고 주장하지 않는다.

## 실제 실행안에 확정할 입력

| 입력 | 회차에 넣을 내용 | 현재 상태 |
|---|---|---|
| 대상·계정 | ansible01/server01_ansible → k8s-worker02/10.1.93.107/svc_ansible, 기존 strict host-key/키 | 기존 경로; fresh 인증·endpoint 확인 필요 |
| 코드 | 새 apply guard 및 이 rollback 수정이 독립 검토된 full SHA, inventory/vars/config hash | apply guard 미구현, 새 source 미확정 |
| 예상 변경 | NM 활성 connection/interface, DNS/search/ignore-auto 사전·목표값, resolver·kubelet 사전 상태 | 이번 회차 값 미수집. 기존 승인 목표를 임의 변경하지 않음 |
| 백업 | 기존 CR 최초 백업 유지, 이번 회차 사전값을 별도 보호 경로에 보존·hash·소유권 확인 | 새 백업 설계/구현·검증 필요 |
| 복구 | 회차 사전값과 현재 상태 drift 대조, 같은 단일 host·검토된 복구 경로, 콘솔 인수자 | 실제 인수 및 회차 범위 확정 필요 |
| 실행창 | 사용자13:20~15:00 KST 단독 창, Harbor 제외 | 창 확보만으로 미확정 코드·복구·GO를 대신하지 않음 |

실제 순서는 fresh 입력/접속 확인 → 단일 대상 check와 승인된 apply → 동일 입력 실제 재적용 → 신규 SSH·role 사후 확인 → 승인된 회차 rollback 및 복귀 확인 → 결과 회수다. 서비스·네트워크 변경과 복구를 창 안에 마칠 수 없으면 시작하지 않는다. 현재 이 문서에는 복사해 실행할 운영 apply/rollback 명령을 제공하지 않는다.

정상 기준은 실패0/unreachable0, 대상 외 접속0, 예상 변경만 존재, 재적용의 관리 설정 변화0, 신규 SSH 성공, 회차 사전 상태 복귀다. 기록/백업 태스크 changed와 설정 changed는 분리한다. drift가 없으면 해당 apply가 무변경 성공한 사실까지만 기록하고 실제 변경·실패 복구 분기 PASS로 확대하지 않는다.

대상 확대·입력 drift·연결 손실·실패·시간 초과 시 다음 단계/호스트 확대를 중단하고 원 로그를 보존한다. timeout 자체를 롤백으로 보지 않으며 살아 있는 프로세스·최종 상태와 콘솔 인수를 확인한다. 운영 키 복원, 엔진 전역 전환, DNS 최초 백업 삭제, 보안 통제 해제로 대응하지 않는다.

## 검증

`tests/test_dns_rollback_scope.py`는 실제 Ansible engine으로 production play의 controller guard와 remote play header, 선두 assert/end_host 검사를 사용한다. 이후 원본 읽기/복구 태스크를 marker 또는 의도한 실패로 바꾸고 모든 inventory 연결을 local로 고정한다. nmcli·운영 SSH·sudo·서비스 변경은 실행하지 않는다.

고정 engine2.16.19/2.21.3 각각에서 단일 대상 정상 경로, 누락/빈값/잘못된 타입, 승인 누락, 미등록/그룹/패턴/동명 group/잘못된 멤버십, empty inventory, remote 실패 전파를 검증한다. 수정 전 playbook으로 같은 단일 대상 회귀 검사를 실행하면 대상 외 facts 접속 때문에 실패해야 한다. 이것은 scope fixture이며 실제 백업·DNS 복구 성공 증적이 아니다.

실행 결과·시각·명령·원 로그·소스 해시는 [검증 기록](../change/validation/issue9-rollback-scope/VALIDATION.json)에 보존한다. GitHub CI·독립 리뷰·병합·운영 적용은 각 단계가 끝난 뒤 별도로 기록한다.
