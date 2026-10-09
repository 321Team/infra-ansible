# Issue9 — worker02 DNS 회차 적용·복구 계약

2026-10-09 KST · CODEX_ASSISTED · 이권욱. 코드 및 격리 시험 범위. **운영 실행·후보 엔진 전환·AC 인수는 NOT_RUN.** [Issue9](https://github.com/321Team/infra-ansible/issues/9), [선행 PR75](https://github.com/321Team/infra-ansible/pull/75), [앞선 준비안](Issue9-Worker02-Canary-Next.md).

## 변경과 적용 범위

기존 `workers`는 전체 worker를 대상으로 하고 최초 CR 백업은 재사용한다. 새 `worker02-session` 경로는 worker02 한 대와 새 회차 백업만 사용한다. 기존 `workers`, 일반 `rollback HOST`, 최초 `original-resolver.json`의 인터페이스·내용은 유지한다. 이 문서는 기존 AC나 Lead의 role 선택·Runtime GO를 대신하지 않는다.

- controller guard가 facts 전에 inventory의 worker02 단독 해석, k8s_workers/k8s_nodes 소속, IP `10.1.93.107`, 계정 `svc_ansible`, 회차·행위별 승인 토큰을 검사한다.
- 새 root 소유 경로 `/var/lib/fds-change/CR-P1-ANS-01-01/worker02-sessions/<ID>/original-resolver.json`에 0700 디렉터리·0600 파일을 독점 생성한다. 기존 ID·심볼릭 링크·부적절한 소유권/권한·추가 ACL/xattr는 중단한다. 기존 파일 권한을 고쳐 통과시키지 않는다.
- 백업에 회차 ID, 전체 코드 SHA, 고정 host/IP/account, 활성 interface/connection, 원래 DNS/search/ignore-auto 및 목표값을 저장한다. hash는 원본 바이트의 식별값이며 성공/GO를 뜻하지 않는다.
- 준비 결과의 SHA256을 컨트롤러 실행 로그와 회차 기록에 별도 보존한 후 이후 호출에 명시한다. 재적용·복구에서 파일을 다시 해시해 자동 채택하거나 다른 회차 파일을 찾아 대체하지 않는다.
- 최초 적용은 백업 생성 15분 이내이며 현재 사전값이 원본과 정확히 같아야 한다. 만료·중간 변경 시 승인된 새 회차를 준비하며 기존 백업은 남긴다.
- 재적용은 같은 바인딩과 목표값 유지가 전제다. 다른 변경이 있으면 자동으로 덮어써 멱등 성공처럼 만들지 않는다.
- 수동 복구는 현재값이 회차 원본 또는 목표값일 때만 허용한다. 다른 drift·활성 연결 변경이면 콘솔 인수로 넘긴다. 복구 자체에는 15분 만료를 적용하지 않는다.
- 자동 rescue는 기존 role과 같이 해당 호출의 메모리 사전값을 사용한다. 수동 복구는 검증된 회차 파일을 사용한다. 두 복구를 혼동하지 않는다.

## 실행 전 확정할 사항

독립 코드 리뷰·해당 HEAD의 CI, Lead의 DNS role 선택과 실제 회차 GO, 단독 창·동시 NetworkManager 작성자 배제, worker02 콘솔 복구 인수자, 정상 SSH·endpoint/host-key, 실행 checkout·inventory·변수·설정 hash 및 예상 DNS 값이 필요하다. 기존 증적113·167을 재사용하되 실행 직전 상태를 대신하지 않는다. 현재 사용자 창은 10/9 17:00 KST까지 연장됐지만, 창 확보가 이 실행의 GO는 아니다.

새 wrapper는 ansible01/server01_ansible에서 검토된 clean checkout을 요구한다. managed-host에서는 기존 become 경로로 root 권한이 필요하다. 후보 CLI 경로만 명시하고 전역 PATH/RPM은 바꾸지 않는다. untracked 실행 코드도 거부한다. 로그는 별도의 비공개 evidence 경로에 보관한다.

아래는 **승인 후 사용할 인터페이스 설명**이다. ID·SHA·승인 토큰의 실제 값은 아직 확정하지 않았다. 환경변수 토큰은 운영자의 확인 표식이며 접근통제나 독립 승인의 증명이 아니다.

```text
FDS_ANSIBLE_ENGINE_DIR=<검토된 2.16.19 또는 2.21.3 bin 절대경로>
FDS_ANSIBLE_ENGINE_VERSION=<그 경로의 고정 버전>
ANSIBLE_PRIVATE_KEY_FILE=<기존 정상 키 경로>
CR_CHANGE_APPROVED=CR-P1-ANS-01-01
CR_DNS_SOURCE_SHA=<검토된 checkout HEAD 전체 SHA>
CR_EVIDENCE_DIR=<별도 비공개 회차 로그 절대경로>
CR_DNS_SESSION_APPROVED=<회차ID>:<행위>
scripts/cr-p1-ans-01-01-run.sh worker02-session <행위> <회차ID> [백업SHA256]
```

회차 ID 형식은 `w02-YYYYMMDDTHHMMSS-8자리소문자16진수`이며 유일한 새 ID를 사용한다. 일자는 운영 기록용이고 신선도 판정은 module이 기록한 UTC 시각을 사용한다.

| 순서 | 행위 | 입력·정상 판정 |
|---|---|---|
| 1 | `prepare` | 승인된 사전 점검과 새 백업 생성. hash 인자를 넣지 않는다. `snapshot_written=true`와 hash·경로를 외부 기록에 보존한다. DNS 변경 없음 |
| 2 | `apply`, `CR_DNS_CHECK_ONLY=1` | 보존한 hash 전달. 백업·현재 상태 검증, 예상 drift 확인. 서비스·DNS 변경 없음 |
| 3 | `apply`, `CR_DNS_CHECK_ONLY=0` | 같은 hash, 15분 이내. 예상 변경만, failed/unreachable 0, role 사후 검증 |
| 4 | `reapply` | 같은 ID/source/목표/hash. 관리 설정 변경 0, 실패 0. 신규 SSH는 별도 연결로 수집 |
| 5 | `rollback` | 회차 GO에 복구가 포함된 경우만. 같은 백업을 검증한 뒤 원래 DNS/search/ignore-auto 복구·재적용, 값 일치·외부 해석·API 확인 |
| 6 | 사후 확인·회수 | 신규 SSH, live resolver·kubelet/containerd 및 범위 밖 변화 확인, 명령/rc/시각/원 로그/hash 보존. 자동 AC 종결 없음 |

prepare의 check-mode는 백업을 쓰지 않으며 사용 가능한 hash도 반환하지 않는다. rollback check-mode는 바인딩 검사까지만 하고 복구 PASS를 출력하지 않는다. 정상 DNS를 고의 손상시켜 변경·복구 증적을 만들지 않는다. 원래 목표값과 같으면 무변경 성공까지만 판정한다.

## 중단·복구 한계

실패, 대상 확대, 입력/소스 drift, 연결 손실, 백업 해시/메타데이터 불일치, 시간 부족 시 다음 행위를 중단하고 기록을 보존한다. `down/up`, 키 제한 해제, SELinux/방화벽 해제, 백업 삭제·덮어쓰기를 복구 수단으로 쓰지 않는다. timeout은 원복 완료를 의미하지 않는다. 자동 rescue도 실패하거나 연결이 끊기면 콘솔 인수자가 같은 회차 원본과 현장 상태를 대조해 복구한다.

이 경로는 회차 파일의 독점 생성과 읽기 무결성을 검사하지만 **NM 상태의 읽기→쓰기 전체를 잠그지 않는다**. 다른 root/operator·NetworkManager 작성자와의 배제는 실제 실행창에서 별도로 확보해야 한다. 직접 playbook의 `--limit`/tags/임의 extra-vars로 guard를 건너뛰는 호출, 악의적인 inventory/plugin 및 privileged 동시 변경은 지원하지 않는다. wrapper의 정상 호출과 검토된 config가 전제다.

복구의 자동 검증은 persistent DNS 필드·외부 해석·API이며, 실서버 live resolver와 서비스·신규 SSH까지 자동 인수했다고 주장하지 않는다. 실제 회차 후 외부 사후 증적이 필요하다. SSH 키 복원·엔진 영구 전환·Harbor·Push/Deploy는 포함하지 않는다.

## 검증 구분

- 파일 시험: 실제 임시파일에 prepare/apply/reapply/rollback 바인딩, 변조·중복·만료·권한·링크·drift 실패 경로를 실행한다. controller UID1000 파일이며 운영 root/SELinux 검증은 아니다.
- 범위 시험: production play의 controller guard를 실제 두 Ansible engine으로 실행한다. 모든 연결은 local, DNS role은 marker/failure로 대체한다.
- 흐름 시험: production role의 태스크 순서/조건/구조를 유지하고 외부 I/O만 임시 action plugin으로 바꾼다. NM은 합성 상태, snapshot 함수는 실제 임시파일을 사용한다. 정상 적용/무변경 재적용/복구, 잘못된 hash·drift 차단, 적용 실패·사후 검증 실패의 rescue 후 nonzero를 검사한다.
- shell 시험: 가짜 CLI로 행위별 token·clean source·pinned engine·check flag·오류 전파를 검사한다.

원 로그와 명령·시각·rc·source hash는 [검증 기록](../change/validation/issue9-dns-session/VALIDATION.json)에 보존한다. 이 결과를 실제 worker02 적용 또는 GitHub CI 완료로 전용하지 않는다.
