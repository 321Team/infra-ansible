# Issue9 운영 호출 경로 전환·복귀 준비 — 2026-10-15

CODEX_ASSISTED · 이권욱 · 책임 [infra-ansible#9](https://github.com/321Team/infra-ansible/issues/9).
상태: **순수 읽기·native helper 버전 확인 완료 / 운영 호출 경로 전환·전체 AC 인수 미완료**.
대조 기준 main `ac013f61df2502534f36a2ca77686f17fd4e5669`. 기존 AC·역할·승인 엔진 2.16.19→2.21.3을 유지한다.

## 1. 완료된 작업과 남은 작업

10/13 worker02 DNS prepare/apply/reapply/동일 원본 복구는 [증적208](https://github.com/321Team/fds-project-evidence/pull/208)에 병합됐다. [실행 결과](https://github.com/321Team/infra-ansible/issues/9#issuecomment-6129831803)의 failed/unreachable/rescued/ignored0·새 SSH·동일값 복구 범위는 재사용한다. 과거 문서의 이 회차 NOT_RUN은 당시 이력이다. 정상 DNS/키를 손상하거나 같은 회차를 다시 실행하지 않는다.

Runner CI와 O02 인수·[#61 종결](https://github.com/321Team/infra-ansible/issues/61#issuecomment-6166830041)은 완료했고 운영은 [#82](https://github.com/321Team/infra-ansible/issues/82)에 분리됐다. 이것은 #9 운영 엔진 전환이 아니다. 일반 CI나 O02를 새 선행 승인으로 요구하지 않는다.

현재 남은 것은 **각 실제 운영 호출자가 사용할 source·엔진·config·대상 범위를 고정하고, 역할별 실제 적용/복구 증거와 결합하여 전환·복귀를 인수하는 것**이다. 원래 #9의 다른 role·6대 SSH/OS/DNS 비교 및 전체 분기 조건을 삭제하지 않는다. 엔진 선택만을 이유로 정상 MON/NTP/Harbor 설정을 과거 backup으로 되돌리지 않는다.

## 2. 00:38~00:39 KST의 실제 읽기 결과

기존 `fds-ansible01` SSH 경로, `ansible01/server01_ansible` 비관리자 권한, strict host-key/BatchMode를 사용했다. sudo·패키지 설치·새 credential·대상 호스트 SSH·playbook·wrapper action·서비스/설정 변경은 없었다. 수집기는 stdin으로 한 번 실행하고 결과는 로컬 수신 경로에만 보존했다.

| 대상 | 직접 확인한 사실 | 한계 |
|---|---|---|
| 운영 `/home/server01_ansible/p1-ans-01` | HEAD `e1c4458cf95dacca76870d7b9b012f8615f6974a`, tracked 변경0·실행 경로 untracked0. 엔진 helper **없음** | 최신 main이나 opt-in wrapper가 배치된 경로가 아니다 |
| 기존 검증 `/home/server01_ansible/worker02-session-plan-3hetha3t/source` | HEAD `0d58598d8a3ce77ccd7eaa9e1dfba820b0a436ea`, tracked 변경0·실행 경로 untracked0, helper 존재 | 10/13 DNS 회차의 검증 경로. 자동으로 운영 기본이 된 것이 아니다 |
| `/usr/bin`의 CLI4종 | 모두 core2.16.19 | 지정된 환경·cwd의 관측이며 모든 로그인 shell/alias를 대표하지 않는다 |
| 기존 후보 venv CLI4종 | 모두 core2.21.3 | 버전·파일 SHA와 실행 위치 확인. 설치 provenance 전체 재검증은 아님 |
| 기존 복귀 venv CLI4종 | 모두 core2.16.19 | 실제 변경된 원격 상태의 복구 시험은 아님 |

CLI4종은 `ansible`, `ansible-playbook`, `ansible-inventory`, `ansible-config`다. 후보·복귀 경로는 다음과 같다.

```text
/home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-2.21.3/bin
/home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-2.16.19/bin
```

기존 검증 checkout의 helper를 SHA `aedf6cd8d2fa656784e5f93e4d507582efb39755655d2e2ad0696e6353f316dd`로 대조한 뒤, 별도 비로그인 Bash 프로세스 안에서 다음 순서로 각 CLI의 `--version`만 호출했다.

1. 후보 경로+2.21.3 명시 → 4종 모두2.21.3.
2. 복귀 경로+2.16.19 명시 → 4종 모두2.16.19.
3. 두 opt-in 변수 unset → 고정 `PATH=/usr/bin:/bin`에서 4종 모두2.16.19.

12개 출력·rc0·helper 사후 해시 동일을 확인했다. `fds_engine_init`의 내부 버전 조회는 이12개와 별도이며 독립 시험 수로 합산하지 않는다. 이 결과는 **native helper의 선택·복귀 진단**이지 네 운영 wrapper의 action 실행, 전역 엔진 전환, 원격 role 복구가 아니다. 로그인 프로파일·기존 셸·cron·systemd 환경은 바꾸지 않았다. 3번은 명시된 PATH의 결과이며 모든 기본 엔진 경로를 보장하지 않는다.

원본·명령·시각·수신 해시는 [읽기 기록](../change/validation/issue9-operating-readiness-20261015/README.md)에서 확인한다. JSON/수집기 보존 사본을 배포 입력으로 소비하지 않는다.

## 3. source 차이와 전환 범위

- 운영 HEAD→현재 main의 `ansible.cfg/inventory/scripts/roles/library/module_utils/playbooks`에는 **17개 파일 차이**가 있다. helper만 추가하는 변경이 아니므로 운영 checkout을 무조건 `git pull`하거나 실행 중 branch를 바꾸지 않는다.
- 기존 DNS 검증 HEAD→main에서 같은 범위를 대조하면 차이는 shutdown 관련4파일뿐이다. `ansible.cfg`, inventory, 네 wrapper, helper, DNS/MON/NTP/Gate0 기존 경로는 동일하다. 이번 준비는 shutdown을 실행하거나 새 shutdown 인수를 요구하지 않는다.
- 실제 운영 전환 후보는 **기존 검증 source를 별도 경로에서 명시적으로 호출하는 범위부터** 정한다. 기존 RPM·PATH·운영 checkout은 복귀 경로로 보존한다. 이 후보를 현재 운영 채택 결정으로 표시하지 않는다.
- 운영 source 고정 SHA를 새 main으로 바꿔야 하는 경우에는 새 diff와 영향을 검토한다. 원본 검증 checkout의 Git HEAD/파일을 수정해 새 source인 것처럼 만들지 않는다.

## 4. 호출 경로별 인수표

| 경로 | 재사용할 실제 근거 | 아직 필요한 조건 |
|---|---|---|
| worker02 DNS 전용 action | PR76 코드·증적208 실제 단일 회차·이번 helper 선택 진단 | 운영 호출자가 사용할 source/cwd·엔진을 채택하고 다음 **실제 필요한 작업**에 사용/복귀를 연결. 기존 canary를 다시 미실행 처리하지 않음 |
| MON wrapper | [증적150](https://github.com/321Team/fds-project-evidence/pull/150)의 후보 엔진 실제 verify·changed0 | apply/멱등성/rollback 기존 증거를 엔진별로 대조. 부족 분기는 격리 또는 별도 구체 변경 범위로 확인. 정상 서비스에 임의 적용·옛 baseline 복원 금지 |
| NTP wrapper | 기존 source/clients/verify/rollback·잠금 및 source/runtime-vars 계약 | 후보 엔진의 실제 해당 분기 호환성. source와 clients의 대상·lock/FD를 보존하고 현재 조건을 대조. 엔진 전환을 위해 NTP Gate를 생략하지 않음 |
| Gate0 wrapper | 기존 native syntax·공개 CLI/고정 엔진 결과 | check/run은 k8s_nodes6대·교차노드 범위이므로 과거 worker02 단일 허용을 확대하지 않음. finalize는 해당 실행 source/rc를 소비 |
| 수동/예약 호출 | 10/5 RPM 공급원·Collection·cron/timer 조사, [10/8 운영 경로](https://github.com/321Team/infra-ansible/issues/9#issuecomment-6042409863), 이번 고정 경로 조회 | 실제 전환 대상 호출자/작업 시점·환경을 명시. 다른 사용자·동적 간접 호출 전체 부재를 주장하지 않음 |
| Runner | PR83 실제 CI·회수 및 #61 완료, #82 운영 | 격리 Ansible CI와 장기 CICD Runner를 별개로 유지. CI core2.21.3 성공을 운영 Ansible 배포 호출로 전용하지 않음 |

## 5. 다음 실행 카드에 고정할 항목

이 문서에서 승인 문자열이나 가상의 새 작업창을 만들어 기존 wrapper에 넣지 않는다. 기존 역할별 실행 카드를 재사용하여 한 번에 다음을 채운다.

1. 선택한 **실제 목적의 role/action**, source SHA, 기존/선택 checkout, config/inventory/vars 해시, 실제 대상 집합, 엔진4종 절대 경로·core 버전.
2. 해당 회차의 동시 작성/호출 배제, fresh backup·외부 SHA, 현재 콘솔 복구 인수와 유한 실행창. 10/13 worker02 콘솔·동시 변경 확인은 그 회차만의 기록이다.
3. 실제 적용/멱등성·새 SSH·role별 결과·실패 복귀 또는 유효한 기존 증적의 적용 범위. 완료된 일반 CI·동일 helper 시험은 새 변경 근거 없이 반복하지 않는다.
4. 전환 전후 실제 호출 경로·config/collections·버전과 이전 engine 복귀 결과, source/로그/rc/회수 증적을 같은 회차에 묶는다.

### 중단·복귀

- source/엔진/대상 불일치, 실행 경로 untracked·동시 변경, 미확인 backup, 기존 창 만료 시 새 action을 호출하지 않는다.
- helper가 없는 운영 checkout에서는 환경변수를 주어도 선택 효과가 없으므로 그 경로를 후보 엔진 경로로 사용하지 않는다.
- 엔진 선택 복귀는 명시한 이전 경로 사용 또는 두 opt-in 변수 해제다. 실제 PATH/버전을 다시 확인한다. RPM·venv 삭제나 전역 shell 수정은 기본 복귀가 아니다.
- 이미 적용한 원격 DNS/MON/NTP 상태는 엔진 복귀로 복원되지 않는다. 해당 role의 검토된 fresh backup/rollback과 사후 새 연결 확인이 별도로 필요하다.
- 실패 회차는 원본을 보존하고 대상/다음 role 확대를 중단한다. 정상 서비스를 고의로 손상하여 복구 실적을 만들지 않는다.

## 단계와 판정

STATIC: source 파일/경로 정합 대조. RUNTIME_READ: 기존 계정의 고정 조회 및 native helper `--version` 진단 완료. 새로운 운영 wrapper action/엔진 전환/role 적용·복구: **미실행**. 독립 검토·병합: 이 PR 상태를 따름. AC·Status·일정·담당·최종 인수: 기존 #9 유지.

Harbor `.50` 예외 회수는 PR84/Harbor 전담 세션, CICD AC08은 별도 CICD 세션, D-03는 별도 APP/E2E 세션이 수행한다. 이 준비는 해당 업무의 실행 권한·창을 대신하지 않는다. Phase2와 신규 엔진 버전 선정은 범위 밖이다.
