# PR #24 수정안 검증 기록 — 2026-09-18 UTC

기준은 `321Team/infra-ansible` PR #24의 HEAD
`e9b628af2923d2dc1346923295fa8361f752b8f9`이다. 기존 7건의
[CHANGES_REQUESTED 리뷰](https://github.com/321Team/infra-ansible/pull/24#pullrequestreview-5245582560)에
대한 코드 수정 제안이며, 작성자의 독립 승인이나 실제 운영 인수를 뜻하지 않는다.

| 범위 | 결과 | 한계 |
|---|---|---|
| Ansible 2.16.19 역할 회귀시험 | 48/48 PASS | LOCAL/MOCK |
| 실행 wrapper 회귀시험 | 8/8 PASS | 호스트 식별·playbook 명령은 모의 처리 |
| NTP playbook 5개 문법 검사 | 2.16.19, 2.21.3 각 5/5 PASS | 실제 대상 실행 아님 |
| Ansible 2.21.3 동작 시험 | BLOCKED / NOT VALIDATED | 기존 동일 환경에서 LocalRPC server 시작 실패(rc250); 문법 검사로 동작 PASS를 대신하지 않음 |
| GitHub CI / 실 서버 RUNTIME | NOT RUN | 이 기록은 로컬 후보 검증만 다룸 |

역할 시험은 임시 디렉터리와 localhost만 사용한다. 원본 역할의
`when`, `block/rescue`, `include_tasks`, `assert` 및 실제
`template/copy/slurp/stat/file` 모듈을 실행한다. 운영 명령인
`rpm/systemctl/chronyc/systemd`는 외부 호출이 없는 fixture action으로
교체한다. `/etc/chrony.conf` 경로와 관리 파일 목적지는 임시 경로로
변경하고, chronyd parser의 성공/실패는 모의 처리한다. 실제 NTP 응답,
SELinux, 운영 uid/gid 권한, 시간 수렴 지연이나 UDP/123 도달성 검증은 아니다.

48개 사례는 다음을 포함한다.

- 없는/기존 drop-in의 백업 JSON, 내용 및 mode 보존, source/client 적용.
- 잘못된 현재 소스가 있는 dry-run의 diff와 무변경, 두 번째 실제 적용
  `changed=0` 및 재시작 없음. 두 번째 호출의 facts 시각은 다르게 설정.
- 명시적 멱등성 검사에서 drift 거부, 템플릿 검증 실패 시 원본 보존.
- 지연 수렴 성공 모형, 대기 소진, 재시작 실패, 검증 실패, 복구 재시작 실패.
- 변경 없는 적용의 검증 실패가 이전 적용을 취소하지 않음.
- 수동 rollback의 기존/미존재 baseline 복구 및 오래된 schema 거부.
- 유효 confdir/include, 대소문자/공백, 주석 4종, pool/peer/sourcedir 차단.
- 현재 보정값 100ms 경계, 500ms, 음수, 누락/중복, NaN/Inf/overflow,
  잘못된 Last offset, Leap, 잘못된/복수/미해석 source, IP 정규식 오인 방지.

음성 사례는 rc만 보지 않고 **의도한 실패 task 도달**, 실제 파일/메타데이터
보존, 재시작 횟수 및 대기 호출을 검사한다. 동기화 모형은 waitsync 호출
전에는 미동기 상태를 제공하고 호출 후에만 정상 상태로 바뀐다. 이는
대기 순서·인수·실패 복구 검증이며 실제 300초 시간 측정은 아니다.

8개 wrapper 검사는 shell 문법/실행 비트, source/client의
check→apply→멱등성 check 순서, 각 단계 실패 전파와 승인 토큰 미설정
차단을 확인한다. 가짜 키 파일은 시험용 평문이며 실제 인증 정보가 아니다.

해석 근거는 [chrony tracking/waitsync/sources 공식 문서](https://chrony-project.org/doc/4.6/chronyc.html)와
[confdir/include 공식 문서](https://chrony-project.org/doc/4.6/chrony.conf.html#confdir)이다.
`waitsync`는 횟수·허용 보정값·간격을 지정하고, 추가 task timeout 300초로
무응답도 제한한다. 강제 시간 변경(makestep)은 추가하지 않는다.

다음 단계는 수정 후보의 정확한 HEAD를 작성자 외 적격 검토자가 검토하고
Lead가 반영을 판단하는 것이다. 기존 main-config pool/DHCP 확인·정리와
control01 자체 upstream 결정은 별도 선행조건으로 유지된다. 승인된
운영 단계에서 설치된 chrony parser/`sources -a` 지원, 실제 복구·수렴,
60초×6 측정, 5분 sync loss 및 reboot resync AC를 확인해야 한다.

기존 승인·증적은 소급 수정하지 않는다. 이 후보를 작성한 검토자의
자체 점검은 독립 APPROVE가 아니며, PR #24의 기존 HEAD에 대한
CHANGES_REQUESTED를 자동 해소하지 않는다.
