# P1-HBR-01 AC04 — edge01 .50 예외 회수

CODEX_ASSISTED. **소스 변경·전환 준비 문서**이며 실행 package/request, Runtime
완료 또는 AC 인수가 아니다. 연결: [baseline #13](https://github.com/321Team/fds-project-baseline/issues/13).

## 범위와 근거

기존 제거 조건은 edge01 이관과 구 `robot$fds-ci` 정리다. 2026-10-14
edge01 직접 읽기에서 k3s inactive/disabled·관련 수신 0을 확인했고,
이재환이 22:53:24 KST ID 1 삭제를 보고했다. 22:58 직접 조회에서 ID 1 부재,
목록 [2,3], worker/push 불변과 API 원본 body를 대조했다. HTTP 코드와 삭제
요청 횟수는 실행자 보고와 구분한다. 해당 근거는 #13에 연결해 보존한다.

23:08:25 KST 읽기에서는 실제 guard가 여전히 6개 주소를 허용했고, Harbor
10개 healthy·관리자 active/running이었다. 이 PR은 desired source만 5개로
정리한다. 병합해도 서버는 자동 변경되지 않는다.

| 구분 | 다음 desired set / 보존 범위 |
|---|---|
| 회수 | 10.1.93.50 한 주소의 Harbor DNAT TCP/443 허용 |
| 유지 | 10.250.10.20, 10.1.93.105/.107/.108, 임시 관리 예외 10.1.93.102 |
| 유지 | ens160, 원래 목적지 10.1.93.54:443, forward priority -1, 규칙 3개, IPv6 거부 |
| 제외 | worker/push 계정, K8s Secret, k3s 데이터, edge nginx/Worker30080, Docker/firewalld 소유 규칙 |

기존 `.26` same-L2 negative와 `10.250.10.10` negative 기준은 유지한다.
`.50`의 차단 검증을 추가하며 기존 검증을 대신하지 않는다. 원본 six-source
nftables 1.1.5 fixture와 sealed prestate는 그대로 보존한다.

## 결합 전환이 필요한 이유

Harbor PR64의 host policy는 전용 nft table의 정규화 지문을 고정한다.
`handle`, counter 값, metainfo만 제외하고 source element는 포함한다.
따라서 `.50`만 먼저 삭제하면 기존 관리자는 `HOST_AC04_DRIFT`로 중단한다.
새 지문은 host/execution binding을 바꾸므로 기존 bundle/Store/claim을
수정·재사용하거나 관측값을 자동 학습시키지 않는다.

관리자 코드 변경은 필요하지 않다. 같은 병합 코드로 새 입력·새 Store를
준비하고, 정확한 방화벽 변경과 함께 전환한다. 기존 app ID/PID/StartedAt,
이미지·마운트·정책의 허용된 변화, 현재 boot/daemon, SELinux·CA 검증은 유지한다.

기존 파일 installer는 15개 설치 대상 모두에 `INSTALL_EXISTING_TARGET`
검사를 한다. 같은 PR64 코드를 유지하는 이번 전환에 그대로 실행하면 기존
module/bootstrap 경로에서 중단된다. 이를 피하려고 코드 revision을 바꾸거나
기존 코드 파일을 이동·삭제하지 않는다. 권장 전환은 기존 12개 코드 파일과
manager unit을 hash/metadata로 **읽기 검증하고 보존**, 새 bundle 1개 생성과
기존 launch 보존 후 새 launch 1개 생성만 수행하는 입력 전용 경로다.
이 경로의 실제 adapter·실패 모의시험·정확 입력 검토는 **별도 잔여**이며,
이 문서만으로 기존 installer를 우회 실행하지 않는다.

## 실행 전 확정할 실제 입력

- 대상 harbor01/10.1.93.54, UUID `1e864d56-61f9-c443-d8f4-0ece2755a850`.
  기존 strict SSH 경로와 root 권한을 사용하고 비밀값을 수집하지 않는다.
- 같은 회차에서 source 파일 bytes/SHA/소유/권한/SELinux context, 실제 nft
  전체 table·기존 bundle/launch/unit·Store 목록/hash·앱 상태·manager PID/Job을
  읽어 결속한다. 이전 관측 시각/boot를 현재 입력으로 복사하지 않는다.
- 병합 source로 렌더한 정확 5개 candidate, 검토된 이전 6개 source 원본,
  managed table 밖의 Docker/firewalld 정규화 비교 자료를 보존한다.
- 새 Store/보존 경로는 실제 부재와 부모 권한/context를 조회한 뒤 결정한다.
  실제 서비스 writer probe로 라벨을 검증한다. boot·경로 label·작업창·예산을
  예시로 채운 실행 request를 만들지 않는다.
- 기존 관리자 startup 60초/종료 유예160초, 초기 HOLD60초/정책300초/arm60초,
  활성화600초, 파일 설치60초/유효기간600초는 확정 범위를 유지한다.
  신규 guard 교체 단계·결합 전체 상한과 현재 비중첩은 실행 전에 확정한다.
- 정확 입력·변경 diff·실패 경로를 독립 검토한 뒤 진행한다. 승인된 기존
  H3/H4 결과는 보존하며 이 회수 때문에 재부팅 시험을 자동 반복하지 않는다.

## 적용 순서 — 아직 실행 명령이 아님

1. 현행 정상·동일 신원/boot/daemon·현재 작업 비중첩을 확인한다. 기존
   6개 지문과 관리자 bundle 일치, 10healthy, 새 source delta가 `.50` 하나뿐인지
   대조한다. 읽기 범위에서 `nft -c -f`로 candidate를 검증한다.
2. 기존 관리자를 검토 CLI로 HOLD하고 정상 종료·disable한다. PID/ControlPID0,
   Job 없음·lease 해제를 확인하고 **그 이후** 기존 Store 전체를 봉인한다.
   HOLD 자체의 정상 기록 변화와 종료 이후 불변 검증을 구분한다.
   guard/Docker는 계속 active로 유지한다. manager가 정상 정지하지 않으면
   다음 방화벽/정책 쓰기 없음. 강제 종료는 없다.
3. 검토한 입력 전용 경로로 새 Store와 새 5개 입력의 공급 준비를 완료한다.
   source/bootstrap/unit의 bytes·경로·metadata는 그대로 유지한다. 기존
   launch의 별도 보존과 새 bundle/launch 생성 대상만 고정한다. old bundle,
   Store, claim을 보존한다. 새 입력의 actual nft 지문 검증은 **5개 table이
   적용된 이후** 실행한다. 이 전에는 설치 성공으로 기록하지 않는다.
4. 현재 6개 source 파일·table·metadata를 재대조하고, 검토된 5개 영구 source를
   동일 디렉터리의 배타적 신규 파일에서 원자 교체한다. mode/owner/context를
   보존하고 파일/부모 fsync·readback을 완료한다. 이후 전용 table만
   `nft -f`의 단일 transaction으로 교체한다. firewalld reload, guard
   stop/restart, Docker restart, flush ruleset, generic443 개방은 없다.
   파일 교체와 kernel 적용은 서로 다른 단계라 실패 시 혼합 상태를 보존한다.
5. nft 실제 table을 조회해 정확 5개/규칙3개/순서·scope·IPv6 거부를 검증한다.
   새 입력의 미리 검토한 지문과 실제 지문의 동일성을 확인한다. 실제 지문이
   예상과 다르면 자동 갱신하지 않고 중단한다. managed 외 표면, guard/Docker
   상태, 앱 ID/PID/StartedAt/health·원본 Store 불변도 대조한다.
6. 입력 전용 adapter로 새 bundle 생성→기존 launch의 배타적 보존→새 launch
   마지막 생성·readback을 수행한다. code/bootstrap/unit 재설치는 없다.
   새 입력으로 실제 host 검증·서비스 writer 시험을 통과한 뒤 기존 검토된
   정책 절차(no→always, 새 Store HOLD 초기화, policy-install always→no,
   arm, manager enable/start)를 따른다. 기존 healthy 앱에 start 요청을
   보내지 않는다. 새 RUN/HEALTHY/lease 단독/claim·pending과 현재 상태를
   별도 프로세스에서 확인한다.
7. 보존된 CA로 `.102` 관리 경로와 Worker3/Runner 허용 경로, `.50` 차단,
   기존 `.26`/관리 negative를 같은 회차 증적으로 수집한다. 출발 IP와
   nft counter 변화를 함께 기록해 timeout/인증 실패를 방화벽 차단으로
   오판하지 않는다. 새 Pull/Push 인증 시험과 단순 TLS/HTTP 도달성은 분리한다.
   실행 불가한 probe는 미실행으로 남긴다. 전체 AC 완료로 확대하지 않는다.

## 실패·복구

불일치, 실패, timeout, 응답 불명, 원본/receipt 보존 실패 시 다음 변경을
중단한다. 실제 파일과 kernel table이 각각 6/5 중 어느 상태인지, manager
상태·혼합 정책·앱 상태·새/옛 Store를 읽고 보존한다. 원격 timeout은 명령
미실행이나 종료의 증명이 아니다. 같은 명령을 자동 재시도하지 않는다.

복구가 필요하면 **당시 실제 부분 상태**를 기준으로 최소 범위를 결정한다.
검토된 이전 6개 guard를 복구하는 경우에도 manager를 정지 상태로 유지하고
영구 파일과 kernel table을 모두 맞춘 뒤, 그 값에 결속된 이전 입력으로
정상 복귀할 수 있는지 검증한다. 삭제한 Robot은 복구하지 않는다. 새/옛
Store를 합치거나 claim을 지우지 않는다. 관리자 복귀/정책 원복을 실패 후
자동으로 수행하지 않고 기존 중단 규칙을 따른다.

최초 설치 `p1-hbr-01-ac04-apply.yml`은 새 대상용이다. 최초 설치
`rollback.yml`은 guard를 제거하고 generic443을 복원하므로 **이번 회수의
복구 경로로 사용하지 않는다**. 보안 통제 완화, 앱 재생성·정지·시작,
Docker/VM 재시작·snapshot 복원은 이 전환에 포함하지 않는다.

## 검증과 완료 경계

로컬 Static/Mock: exact 5개·`.102` 보존·`.50` 재유입/나머지 누락 거부,
렌더 delta가 주소 한 항목뿐인지, 기존 drop/scope와 역사 fixture 불변을 검증한다.
CI: exact HEAD의 Linux regression 결과를 별도로 연결한다. queued/skipped는
PASS가 아니다. 리뷰·병합·Runtime 회수·관리자 복귀·traffic 증적·AC는 별도다.
회수 결과는 #13에 source/head·실제 시각·before/after hash·영향·미실행 probe를
기록하며 `.102`, Robot 회전, 전체 인수 잔여를 임의 종결하지 않는다.
