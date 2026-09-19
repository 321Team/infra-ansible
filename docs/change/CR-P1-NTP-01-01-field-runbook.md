# CR-P1-NTP-01-01 실제 서버 반영 절차

상태: **2–3개 지원 수정안의 현장 실행 절차 / 실제 서버 적용 NOT RUN**.
새 수정안의 정확한 HEAD 독립 리뷰와 Lead 병합 판단을 마친 뒤 사용한다.
이 문서의 명령을 작성한 사실은 코드 승인, 방화벽 반영 또는 NTP 인수 완료가 아니다.

## 기존 기록 정정과 이번 수정 범위

- **PR28은 승인·병합 완료다.** hayeounglee가 HEAD
  `f7940d7fd29850e45f4197ea7ab97d74b35021aa`를 2026-09-19 01:20:28 KST에
  [APPROVED](https://github.com/321Team/infra-ansible/pull/28#pullrequestreview-5250065110)했고,
  01:22:03 KST에 PR24 작업 브랜치로 병합됐다. merge는
  `a51a7de0e7e7cebaa46bef318ab46808ceb2b835`다. 과거 “PR28 승인 대기”는 현행 상태가 아니다.
- 기존 권고 댓글의 “기존 실행기에 2개만 넣어도 된다”는 당시 코드와 맞지 않는다.
  승인된 f794의 [입력 검사](https://github.com/321Team/infra-ansible/blob/f7940d7fd29850e45f4197ea7ab97d74b35021aa/tools/render-ntp-egress.py)는
  정확히 3개를 요구한다. 이번 수정은 지원 개수를 **2–3개**로 맞추고 생성·진단·검증에 같은 계약을 적용한다.
- f794의 마지막 변경이 문서 중심이라는 이유로 “실행 코드가 없는 커밋”이라고
  해석하면 안 된다. 해당 tree에는 기존 [통합 실행기](https://github.com/321Team/infra-ansible/blob/f7940d7fd29850e45f4197ea7ab97d74b35021aa/tools/ntp-rollout.py)가
  포함돼 있다. 다만 그 실행기는 이번 2–3개 지원 수정안과 다른 버전이다.

기술 지원 목록은 Cloudflare `162.159.200.1`, `162.159.200.123`과
Netnod `194.58.200.20`이다. 서로 다른 literal IPv4 2–3개를 사용하며,
현재 기본값 `[]`는 유지한다. Cloudflare 두 주소를 독립된 두 운영기관으로
세지 않는다. NIST·NICT 및 지원 목록 밖 주소는 이번 실행 코드의 입력으로
사용하지 않는다. 구체적인 서비스 정책과 한계는
[시간원 선정 문서](CR-P1-NTP-01-01-upstream-selection.md)를 따른다.

공식 주소·서비스 설정·비smear 근거를 확보한 Cloudflare `162.159.200.1`과
`162.159.200.123`을 1차 권장안으로 제시한다. 동일 운영기관 의존과 두 source 간
상충 시 판별 한계를 기존 CR에 기록하여 수용한 경우에 사용한다. 이 선택에는
사용하지 않는 Netnod 확인을 선행조건으로 추가하지 않는다. Netnod의 현재
주소·서비스·윤초 적합성을 확인한 뒤 기관 분산 대안을 선택할 수 있다.
독립 운영기관 분산은 권고이고 기존 정본 의무로 소급하지 않는다.

## 실행 위치·대상·명령의 용도

| 항목 | 값 | 용도 |
|---|---|---|
| Controller 로그인 | `server01_ansible@ansible01`, 관리 IP `10.250.10.10` | 아래 명령은 이 일반 계정에서 실행 |
| Ansible 환경 | 기존 core **2.16.19** | `ansible`, `ansible-playbook`, `ansible-inventory` 모두 같은 기존 환경 사용 |
| SSH 개인키 | `/home/server01_ansible/.ssh/p1_ansible_ed25519` | 기존 검증 키의 **파일 경로**; 내용·`.pub` 파일 입력 아님 |
| 내부 NTP source | `k8s-control01`, `10.1.93.102` | 선정 공인 2–3개로만 NTP 요청, 내부 5대에 시간 제공 |
| Client | `k8s-control02` `.103`, `k8s-control03` `.104` | 전체 IP는 `10.1.93.103`, `10.1.93.104`; control01만 사용 |
| Client | `k8s-worker01` `.105`, `k8s-worker02` `.107`, `k8s-worker03` `.108` | 전체 IP는 `10.1.93.105`, `10.1.93.107`, `10.1.93.108`; control01만 사용 |
| 관리 대상 계정 | 기존 inventory의 `svc_ansible` | playbook이 필요한 become 사용; controller 전체를 root로 시작하지 않음 |
| `ntp-rollout.py --apply` | 진단 후 조건부 적용·검증·증적 포장 | source→내부 path 검사→clients 순서 자동 진행 |
| `ntp-rollout.py` | `--apply` 없이 실행 | controller 준비→precheck→diagnose→finalize/포장; 구성 적용 안 함 |

## 실행 전에 완료할 기존 입력

1. **이번 새 수정 코드**의 정확한 HEAD를 독립 검토하고 병합한다.
   PR28의 기존 승인은 보존하지만 새 변경에 소급하지 않는다. 실행 소스는 새
   수정이 포함된 검토·병합된 commit의 clean checkout으로 고정한다. 새 PR/merge
   번호를 임의로 채우거나 구 f794에 2개 입력을 넣어 실행하지 않는다.
2. 사용할 2–3개 endpoint와 서비스·윤초 처리 적합성을 기존 CR에 연결한다.
   Netnod를 선택한다면 현재 주소/서비스와 윤초 정책의 적합성 확인을 마친다.
   코드의 지원 목록 통과만으로 이 확인이 완료된 것은 아니다. 기존 control01
   내부 구조·수치 AC·역할은 유지하고, control01 외부 접근 범위 변경을 기록한다.
3. `10.1.93.102/32`에서 선택 endpoint 각각 `/32`의 **UDP destination 123**과
   stateful reply, 5개 client→control01 내부 UDP123의 실제 정책·경로를 연결한다.
   client source port를 123으로 고정하지 않는다. 실제 firewalld/nftables,
   HEP/GNP, 상위망·NAT 중 적용되는 통제 지점과 기존 정책을 확인한다.
4. 변경 전 chrony pair와 네트워크 정책 원문·해시, 이번 변경 증분과 복구 경로를
   확보한다. 실패 host의 원래 pool/DHCP 설정 복구 시 필요한 경로까지 맞춘다.
   이미 성공한 host와 공유 규칙을 일괄 되돌리지 않도록 범위를 고정한다.

현재 자료에는 전체 유효 방화벽 정책과 해당 변경·복구 원문이 없다. 따라서
이 문서에서 구체적인 `firewall-cmd`/Calico/상위 장비 변경 명령을 확정하지 않는다.
통합 실행기는 방화벽을 자동 배포하지 않는다. 실제 확인한 backend의 검토된
증분으로 준비하며 “규칙 한 줄이면 완료”나 문서상 allowlist만으로 경로 PASS를
선언하지 않는다. 세부 확인·복구는
[네트워크·복구 계약](CR-P1-NTP-01-01-network-recovery.md)을 따른다.

위 내용은 새로운 사람이나 승인 단계를 추가하는 절차가 아니다. 기존 책임 범위의
Lead가 같은 CR 기록에 입력·영향·복구를 연결하며, 같은 확정 실행의 각 단계마다
별도 승인 질문이나 Support 서명을 반복하지 않는다.

## 입력 파일을 한 번 작성

새 수정이 포함된 **검토·병합된 전용 checkout의 저장소 루트**로 이동한다.
`tools/ntp-rollout.py`와 `inventory/hosts.yml`이 그 checkout에 있어야 한다.
기존 Ansible 환경을 활성화하고, 아래 빈 양식을 checkout 밖의
`/home/server01_ansible/ntp-runtime-input.json`에 작성한 뒤 실제 값으로 채운다.
기존 실행에 사용한 파일이 있다면 덮어쓰지 말고 원본을 보존하여 새 파일명을 사용한다.

```json
{
  "reviewed_source_sha": "",
  "public_upstreams": [],
  "source_policy_ref": "",
  "network_policy_ref": "",
  "recovery_ref": ""
}
```

| 키 | 작성할 실제 값 |
|---|---|
| `reviewed_source_sha` | 이번 수정이 포함된 검토·병합된 실행 checkout의 전체 HEAD SHA |
| `public_upstreams` | 위 지원 목록에서 확정한 서로 다른 IPv4 2–3개; hostname이나 설명문을 넣지 않음 |
| `source_policy_ref` | 해당 endpoint·서비스 사용·윤초 적합성과 선택을 기록한 기존 CR/결정의 실제 참조 |
| `network_policy_ref` | 동일 endpoint의 control01 외부 경로와 5개 내부 경로, 실제 정책·반영 결과를 연결한 참조 |
| `recovery_ref` | host별 pair와 기존 네트워크 정책·변경 증분·복구 순서·성공 host 보존을 연결한 참조 |

세 참조는 한 CR 기록의 서로 다른 절을 가리켜도 된다. 빈 값, `PENDING`,
예시 URL이나 `approved:true`를 명령으로 만들어 대신하지 않는다. 문자열을
입력했다는 사실은 결정의 진위나 방화벽 반영을 기계적으로 증명하지 않는다.
키 내용·PAT·토큰·GitHub 인증 파일은 이 JSON에 넣지 않는다.

작성한 파일은 본인 소유의 일반 파일로 보관하고 group/other 쓰기를 허용하지 않는다.

```bash
chmod 600 "$HOME/ntp-runtime-input.json"
```

`git rev-parse HEAD`는 현재 SHA를 확인하는 용도이며 독립 승인 증명이 아니다.
실제 검토/병합 기록의 실행 소스와 JSON의 SHA를 맞춘다. 실행기는 HEAD/tree,
clean 상태, 원문 입력 해시 및 inventory의 실제 host/upstream을 다시 검사한다.

## 진단부터 적용까지 한 번에 실행

위 준비와 입력을 마친 동일 checkout 루트, `server01_ansible@ansible01`에서 실행한다.
이 명령은 진단 통과 뒤 **실제 chrony 구성 적용과 서비스 재시작**까지 이어간다.

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

`CR_CHANGE_APPROVED`는 기존 CR 범위의 실행 선택값이다. export 명령 자체로
미결정 주소·정책·코드가 승인되거나 실제 네트워크 조건이 충족되는 것은 아니다.
controller의 sudo/root 실행이나 SSH 키 재발급·권한 일괄 변경은 필요하지 않다.

순서: controller·소스·입력 검사 → precheck → control01에서 선택한 공인
endpoint 각각 진단 → source check/apply/idempotency → source 상태/ACL/listener와
5개 client의 실제 내부 NTP 응답 검사 → clients check/apply/idempotency →
전체 verify → finalize/archive. clients 적용은 한 대씩 진행하며 실패하면
이후 host를 시작하지 않는다. 임의 extra-vars를 추가하여 이 순서를 우회하지 않는다.

진단만 필요할 때는 같은 유효 입력을 사용하고 `--apply`를 생략한다.

```bash
(
set -euo pipefail
umask 077
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export ANSIBLE_PRIVATE_KEY_FILE=/home/server01_ansible/.ssh/p1_ansible_ed25519
python3 -I -B tools/ntp-rollout.py \
  --runtime-input "$HOME/ntp-runtime-input.json"
)
```

진단 모드는 **precheck와 diagnose까지만** 수행하고 `DIAGNOSED_NOT_APPLIED`로
마무리한다. source 적용 후에 수행하는 pathcheck, clients 적용, 전체 verify는
포함하지 않는다. 진단에도 동일한 소스·정책 입력 검사가 필요하며 입력 미완성을
우회하지 않는다. `--apply` 실행은 이 진단을 포함하므로 별도 진단을 필수로
한 번 더 실행할 필요는 없다. chronyd `-Q` 표본은 기존 daemon/시계를 직접
수정하지 않지만 실제 적용의 재시작은 다르다. 기존 `makestep 1.0 3`이 유지되어
재시작 뒤 조건을 만족하면 시계가 step될 수 있다.

## 종료·중단·복구 판단

| 출력 상태 | 의미와 처리 |
|---|---|
| `DIAGNOSED_NOT_APPLIED` | 진단 완료. source/client 구성 적용 미실행 |
| `ROLLOUT_COMPLETED_REVIEW_REQUIRED` | 적용 흐름·snapshot 검증 완료. 아래 지속성 AC와 원문 인수는 별도 |
| `INCOMPLETE_APPLY_NOT_STARTED` | controller/사전 진단 단계 중단. 이 실행의 Ansible 적용 미시작; 별도로 준비한 네트워크 변경 유무는 확인 |
| `SOURCE_PHASE_FAILED_REVIEW_REQUIRED` | source 단계 실패. `source_applied:null`이면 적용·복구 여부를 원문과 해당 host 상태로 확인 |
| `SOURCE_APPLIED_CLIENTS_NOT_STARTED` | source 완료 후 path gate 등 중단. clients 미시작, 성공 source를 자동으로 되돌리지 않음 |
| `CLIENTS_STARTED_REVIEW_REQUIRED` | client 단계가 시작됨. host별 적용·복구·미실행을 구분하여 후속 판단 |
| `INCOMPLETE_FINALIZATION` | 증적 마무리 실패. 실행 결과와 남은 원문을 보존하고 완료 PASS로 표시하지 않음 |

SIGINT/TERM·timeout 때 controller가 자식 그룹을 종료해도 이미 시작한 원격
작업의 종료·복구까지 입증되는 것은 아니다. 강제 종료 뒤 무조건 재실행하지 말고
현재 host 상태, `RESULT.json`, 로그와 baseline을 먼저 대조한다.

자동 rescue는 실패 host의 해당 호출 직전 pair 복원을 시도한다. 복원 자체의
실패도 원문으로 확인하며 성공을 가정하지 않는다. 명시적 rollback은
최초 baseline을 사용하므로 두 기준점을 혼동하지 않는다. 앞서 성공한 host를
자동으로 일괄 되돌리지 않는다. 예를 들어 **실제 복구 대상이 worker02로
확정된 경우에만**, 동일 검토 소스와 기존 SSH 환경에서 다음을 사용한다.

```bash
CR_NTP_MIGRATE_MAIN=1 CR_CHANGE_APPROVED=CR-P1-NTP-01-01 \
  ./scripts/cr-p1-ntp-01-01-run.sh rollback k8s-worker02
```

다른 대상이면 실제 확인한 inventory host로 지정한다. 혼합 HEAD 증적을
만들지 않도록 기존 wrapper 증적의 소스 결합을 유지하고, 별도 복구 기록이
필요하면 새 `CR_EVIDENCE_DIR`를 사용한다. baseline 삭제·수기 수정이나 전체
방화벽 flush로 검사를 우회하지 않는다.

원래 pool/DHCP pair로 복구하면 새 고정 IP allowlist와 목적지가 다를 수 있다.
`recovery_ref`에 연결된 **이번 네트워크 증분의 복구**와 조정하고 성공 host의
경로·공유 정책을 보존한다. pair 복원 또는 chronyd active만으로 시간 동기화
복구를 PASS 처리하지 않는다.

## 증적 전달과 최종 AC

종료 시 출력된 `HOME_EVIDENCE=`의 archive와 `SHA256_SIDECAR=`의 sidecar를
함께 보존·전달한다. 파일 이름을 임의로 바꾸지 않는다. 같은 디렉터리에서
해당 sidecar에 `sha256sum -c`를 실행하여 무결성을 확인한다. 실행이 실패했어도
생성된 원본을 보존하며, archive 생성이 실패하면 남은 증적 디렉터리를 보존한다.
SSH 개인키·토큰·인증 파일은 첨부하지 않는다.

원문 `RESULT.json`, `COMMANDS.json`, `SOURCE.json`, 입력·해시, 6대 gate receipt,
wrapper 로그·내부 manifest를 함께 대조한다. 서버 접속/입력 검사 전에 중단되면
일부 항목은 없을 수 있으므로 누락을 정상 수집으로 취급하지 않는다.

기존 최종 AC는 **offset≤100ms, 60초 간격 6회, sync loss가 5분 이상 지속되면
FAIL, 재부팅 후 5분 이내 재동기화**다. 6대 실제 시각·source/tracking과 원문으로
판정하며 장애/복구·재부팅 및 최소 권한 Positive/Negative/Regression 증적을
연결한다. 통합 실행의 단일 시점 진단으로 이 지속성 결과를 대신하지 않는다.

기존 PR28 로컬 시험 128/128, 이번 수정안의 별도 시험, GitHub CI 및 현장
Runtime은 구분한다. CI 실행 기록이 0건이면 **CI NOT RUN**이며 PASS가 아니다.
이 문서 작성으로 실제 source/client 적용, 방화벽 변경 또는 운영 AC 완료를
주장하지 않는다. 상세 범위는 [통합 실행 지침](CR-P1-NTP-01-01-rollout.md)과
[네트워크·복구 계약](CR-P1-NTP-01-01-network-recovery.md)을 따른다.
