# CR-P1-NTP-01-01 통합 실행 지침

상태: 통합 실행 코드의 리뷰 후보. [로컬 검증 128/128 PASS](CR-P1-NTP-01-01-rollout-validation.md). 실제 서버 적용과 AC 인수는 미실행.

2026-09-19 KST 권장안 착수: [공인 시간원 후보와 서비스 정책 수정 계약](CR-P1-NTP-01-01-upstream-selection.md),
[네트워크·복구 실행 계약](CR-P1-NTP-01-01-network-recovery.md)을 추가했다.
NIST 후보는 현재 iburst 진단/설정과 호환되지 않으므로 실제 입력에 추가하지 않는다.
후보 선정 문서는 실행 설정이 아니며 기존 128/128 결과에 신규 provider 적합성 시험을 소급 포함하지 않는다.

## 승인과 소스

PR #27은 `hayeounglee`가 2026-09-18 22:12:28 KST에 정확한 HEAD
`52e9a7450aca411e44be221b99840aeb372bacb3`를 승인했다.
[승인 원문](https://github.com/321Team/infra-ansible/pull/27#pullrequestreview-5248146019).
22:28:45 KST에 PR #24 작업 브랜치 `cr-p1-ntp-01-01`로 병합했으며,
병합 commit은 `e5446288c1c646f41c9ec9c890bf85e7509503ec`이다.
승인 HEAD와 병합 commit의 tree는 모두
`eeb9ce9f9493ae900b6d0258a4e1ccae6aaff1e1`이다.
이는 main 병합이나 운영 적용 완료를 뜻하지 않는다. 당시 Checks, Status,
Actions 실행 기록은 0건이므로 CI는 NOT RUN이다.

이 문서와 함께 추가한 통합 실행기는 새 코드다. [리뷰 정책](../REVIEW_POLICY.md)에
따라 해당 최종 HEAD의 독립 리뷰와 Lead 병합 판단을 거쳐 사용한다.
기존 PR #27 승인을 새 실행 코드의 승인으로 소급하지 않는다.
동일한 승인 범위의 진단·적용·검증 단계마다 추가 승인 질문을 요구하지 않는다.

## 계속 유지할 지침

- 실행은 검토·병합된 소스와 깨끗한 checkout에 고정한다. 실행 도중 HEAD,
  tree 또는 실행 입력이 달라지면 후속 적용을 중단하고 증적을 보존한다.
- controller는 `server01_ansible@ansible01`이다. 기존 SSH 개인키의 **경로**만
  사용하며 키 내용, 토큰, 인증 파일은 입력 JSON·로그·증적에 넣지 않는다.
- control01만 확정된 공인 IPv4 NTP 3개를 사용한다. 다섯 클라이언트는
  control01 `10.1.93.102`만 사용한다. 기본 주소 목록은 비워 두며 현재 pool의
  응답 IP를 임의로 운영 입력으로 채택하지 않는다.
- 공인 서비스 사용 조건, 장애 도메인, 윤초 처리 방식과 실제 network/host
  정책을 확정한다. 정책 참조 문자열은 판단 근거를 연결하는 값이며 승인이나
  방화벽 적용 사실을 기계적으로 증명하는 인증 토큰이 아니다.
- 전체 실행 동안 controller 공통 잠금을 유지한다. 다른 checkout이나 증적
  디렉터리에서 시작한 동일 CR 실행도 동시에 진행하지 않는다.
  이 보호는 새 잠금을 사용하는 동일 controller 계정의 실행기 사이에 적용된다.
  구버전 실행기, 다른 controller 또는 직접 실행한 Ansible까지 차단하지는 않는다.
- check/diff → apply → zero-change check 순서를 유지한다. control01 검증 및
  다섯 클라이언트의 실제 내부 NTP 응답 검사가 통과해야 clients 적용을 시작한다.
- 클라이언트 적용은 한 대씩 진행하고 실패하면 다음 호스트를 실행하지 않는다.
  현재 호스트의 변경 실패는 기존 paired 복구 계약을 사용한다. 앞서 성공한
  호스트까지 자동으로 원래 설정으로 되돌리지는 않는다.
- 실패·중단·부분 적용을 PASS로 표시하지 않는다. 종료 때 finalize와 증적
  압축을 시도하며, finalize 실패로 최초 실패 원인을 덮지 않는다.
- 기존 복구 baseline을 삭제하거나 수기로 변경하여 검사를 우회하지 않는다.
  대상 서버 전체 삭제, firewall flush, 임의 권한 변경을 복구 수단으로 쓰지 않는다.
- STATIC/MOCK/CI/RUNTIME/REVIEW/MERGE와 최종 AC 인수는 별개로 기록한다.
  후속 변경도 이 지침을 버전 관리하고 기존 실행 이력은 소급 수정하지 않는다.

## 입력을 한 번 준비

[입력 예제](CR-P1-NTP-01-01-runtime-input.example.json)를 checkout **밖**에 복사하고
소유자만 읽고 쓸 수 있도록 보관한다. 아래 다섯 값만 입력한다.

| 키 | 실제 값 |
|---|---|
| `reviewed_source_sha` | 통합 실행기를 포함한 검토·병합된 실행 checkout의 전체 HEAD SHA |
| `public_upstreams` | 확정된 서로 다른 공인 IPv4 주소 3개 |
| `source_policy_ref` | 위 주소 및 호환되는 윤초·서비스 사용 조건을 결정한 기존 기록 |
| `network_policy_ref` | control01 외부 UDP/123 및 5개 client → control01 내부 UDP/123 정책 기록 |
| `recovery_ref` | 기존 chrony pair와 네트워크 정책 복구에 대한 기존 기록 |

별도 `approved: true` 서류를 만들지 않는다. 원문 입력과 SHA256을 실행 증적에
보존하고, 실행기가 허용된 Ansible 변수만 새로 만들어 모든 단계에 동일하게
전달한다. 임의 extra-vars나 서버 주소를 입력 JSON에 추가하지 않는다.

## 진단부터 적용까지 한 번에 실행

검토·병합된 clean checkout에서, 기존 Ansible 실행 환경을 활성화한 뒤 실행한다.
`--apply`가 없으면 진단만 수행한다. 아래 명령은 진단에 통과하면 자동 적용한다.

```bash
(
set -euo pipefail
umask 077
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export ANSIBLE_PRIVATE_KEY_FILE=/home/server01_ansible/.ssh/p1_ansible_ed25519
export CR_CHANGE_APPROVED=CR-P1-NTP-01-01
python3 -I -B tools/ntp-rollout.py \
  --runtime-input "$HOME/ntp-runtime-input.json" \
  --apply
)
```

실행 순서는 사전검사 → control01에서 공인 NTP 3개 응답 진단 → source
check/apply/idempotency → 다섯 client에서 control01 NTP 응답 진단 → clients
check/apply/idempotency → 전체 검증 → finalize/압축이다. 단계 사이에 수동 명령이나
승인 답변을 추가하지 않는다. 주소 미확정, 입력 불일치, 구성 충돌, 응답 실패는
해당 단계에서 멈춘다. control01 적용 후 내부 통신이 실패하면 source 적용 사실과
clients 미시작 상태를 증적에 남긴다.

`source_applied`는 source 단계 미시작이면 `false`, 단계 완료·검증 시 `true`,
도중 실패해 적용 여부를 확정할 수 없으면 `null`로 남긴다. source 단계에서
실패했다고 해서 이미 수행한 변경이 없었다고 해석하지 않는다.

NTP 응답 진단은 설치된 chronyd의 `-Q`를 별도 설정으로 실행한다. 기존 daemon과
시계를 수정하지 않고, 응답 offset의 유한값 및 100ms 한도를 별도 검사한다.
응답 성공은 네트워크 경로에서 유효한 표본을 받았다는 뜻이며 전체 방화벽의
최소 권한, 세 upstream의 합의, 지속 동기화까지 증명하지 않는다. 실제 서비스의
Leap Normal 및 선택 source 검증은 기존 apply/verify에 유지한다.

## 종료와 복구

종료 결과와 증적 경로를 함께 확인하고 생성된 archive와 SHA256 sidecar를 전달한다.
nonzero 종료, 중단, 일부 host 적용, finalize 실패는 인수 PASS가 아니다.
강제 종료나 host 장애로 프로세스가 사라지면 자동 마무리는 보장되지 않으므로
남은 증적과 paired baseline을 보존한다.
SIGINT/TERM 시 controller의 자식 프로세스 그룹을 종료하더라도, 이미 원격에서
시작한 작업의 종료·복구까지 증명되는 것은 아니다. 해당 호스트 상태를 증적으로
확인한 뒤 복구하며 중단 결과를 적용 미실행으로 단정하지 않는다.

명시적 복구는 동일 검토 소스에서 대상 한 대를 지정한다. 원래 pool/DHCP 설정을
복원하므로 네트워크 정책도 원래 경로를 허용하도록 기존 복구 계획과 조정한다.

```bash
CR_NTP_MIGRATE_MAIN=1 CR_CHANGE_APPROVED=CR-P1-NTP-01-01 \
  ./scripts/cr-p1-ntp-01-01-run.sh rollback k8s-worker02
```

기존 `makestep 1.0 3`은 보존된다. 재시작 후 조건을 만족하면 시계가 step될 수 있다.
본 통합 실행을 step-free로 설명하지 않는다. 방화벽·HEP·Calico 규칙은 이 실행기가
변경하지 않는다. 원본 pair 복원만으로 동기화 성공을 선언하지 않는다.

최종 AC인 60초 간격 6회 측정, 5분 이상 sync loss 실패, 재부팅 후 5분 이내
재동기화와 장애·회복 시험은 별도 현장 증적이 필요하다. 통합 실행의 snapshot
검증이나 코드 승인을 이 인수 결과로 대체하지 않는다.
