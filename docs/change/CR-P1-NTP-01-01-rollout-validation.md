# NTP 통합 실행 검증 기록

기준: PR #27 병합 commit `e5446288c1c646f41c9ec9c890bf85e7509503ec`,
tree `eeb9ce9f9493ae900b6d0258a4e1ccae6aaff1e1`.
통합 실행과 receipt producer, 공통 잠금 및 wrapper 변경을 검증한다.
기존 paired migration 모듈·역할·source/client apply playbook의 구현은 변경하지 않았다.
아래 결과는 LOCAL/MOCK 범위이며 CI와 실제 서버 RUNTIME 결과가 아니다.

## 결과

**128/128 PASS**, 추가로 신규 gate playbook syntax **2/2 PASS**.

| 범위 | 결과 |
|---|---:|
| Rollout 단계·receipt·소스/입력·잠금·중단 처리 | 62/62 |
| 기존 shell wrapper 및 실패 전파 | 19/19 |
| 실제 Ansible 5-host 직렬 실패·복구 | 1/1 |
| Probe 관측 모의 시험 | 43/43 |
| 실제 chrony 4.8 loopback 시험 | 3/3 |

[기계 판독 결과와 시험 대상 SHA256](CR-P1-NTP-01-01-rollout-validation.json)에
각 case 이름·판정, 최종 소스 hash, 원본 report hash를 보존했다. 실행기·wrapper·probe의
시험 대상 hash와 제출 파일의 hash가 일치함을 확인했다. 기존 migration 68개 시험과
이전 probe 연구 8+11개를 이번 합계에 중복 산입하지 않았다.

## 검증 범위

- 실제 통합 실행 제어 흐름, Git 소스 확인, subprocess 처리와 증적 포장에
  controller/Ansible 응답 fixture를 연결한다. 정상 순서, 진단 전용, 입력 오류,
  소스·입력 변경, 각 단계 실패, 잘못된 receipt, 중단·시간초과와 잠금 해제를 확인한다.
- 기존 shell wrapper는 check/diff → apply → idempotency 순서와 각 실패 시 다음
  명령 미실행을 확인한다. 실제 서비스·SSH 호출은 fixture다.
- 실제 Ansible client playbook의 serial/any_errors_fatal 제어와 paired 파일 처리를
  사용하는 다섯 호스트 fixture에서 세 번째 host의 서비스 실패를 주입한다.
  첫 두 host는 적용 상태를 유지하고 세 번째는 invocation pair로 복구하며,
  네 번째·다섯 번째는 시작하지 않아야 한다. 서비스·chronyc는 모의 응답이다.
- Probe의 host/IP/서비스/확장 argv/재시작 OPTIONS/설정 parser/ACL/listener/offset
  판정은 모의 관측으로 검증한다. 정상·250ms offset·unsynchronised 응답 3건은
  실제 chrony 4.8과 loopback NTP fixture를 사용한다. 공인 주소에는 접속하지 않는다.
- 진단·pathcheck 두 playbook을 기존 core 2.16.19에서 syntax-check한다.

## 감사에서 수정한 사항

1. `GIT_DIR`/`GIT_WORK_TREE` 때문에 dirty 실행 checkout 대신 다른 clean 저장소를
   검사할 수 있었다. 통합 실행과 wrapper에서 `GIT_*` 환경을 제거하고 wrapper의
   저장소 위치를 script 자체 경로로 고정했다. 동일 재현에서 차단됨을 확인했다.
2. 통합 실행과 wrapper의 runtime 변수 허용 목록을 동일한 6개 키로 맞췄다.
   run/source/input binding과 허용된 NTP 값 외 임의 변수를 전달하지 않는다.
3. finalize 종료 뒤 입력을 다시 검사하고, outer manifest가 nested manifest도
   포함하도록 했다. archive 생성 실패 시에도 공통 잠금을 해제한다.
4. `source_applied`를 삼상태로 기록하여 source 도중 실패를 미적용으로 단정하지 않는다.
5. 현재 `/proc` argv와 다음 재시작의 표준 `OPTIONS`를 대조한다. 대체 config,
   clock-control 옵션, competing service 또는 해석할 수 없는 override는 중단한다.
6. rc0만으로 NTP 응답을 통과시키지 않는다. 유효 표본과 유한 offset ≤100ms를
   요구하고, 잘못된 수치는 원문 로그와 `null`로 보존한다.

## 재현

Ansible 2.16.19의 Python/CLI 환경을 사용한다. `chronyd`는 loopback 시험용
로컬 4.8 바이너리이며 운영 daemon을 시작하지 않는다. fixture가 소유하는
임시 디렉터리를 사용하고 운영 `/etc`나 `/var/lib`를 테스트 경로로 지정하지 않는다.

```bash
python3 -B tests/ntp_source/test_rollout.py --output /tmp/ntp-rollout-tests
python3 -B tests/ntp_source/test_wrapper.py
python3 -B tests/ntp_source/test_probe.py \
  --output /tmp/ntp-probe-tests --chronyd /path/to/test/chronyd
python3 -B tests/ntp_source/test_rollout_serial.py \
  --output /tmp/ntp-serial-tests \
  --ansible-playbook /path/to/venv/bin/ansible-playbook \
  --chronyd /path/to/test/chronyd
```

각 시험 출력에는 fixture 사용 범위와 개별 판정이 포함된다. 운영 주소를 예제
fixture 값으로 채우지 않는다. 3개 공인 주소, 서비스 사용·윤초 정책, 실제 내부·외부
UDP/123 정책은 현장 입력과 증적으로 확정해야 한다.

## 남은 현장 인수

새 통합 실행 코드의 독립 리뷰와 병합, 실제 controller/SELinux/service/방화벽
동작, 여섯 노드의 적용·복구 및 원본 증적은 이 로컬 검증으로 대체되지 않는다.
60초 간격 6회 측정, 5분 sync-loss 기준, 재부팅 후 5분 이내 재동기화와
장애·회복 시험은 별도 AC다. 실제 방화벽 변경·호스트 적용·재부팅은 수행하지 않았다.

공식 동작 근거: [chronyd 4.8의 -Q 및 명령행 설정](https://chrony-project.org/doc/4.8/chronyd.html),
[chrony 4.8 설정](https://chrony-project.org/doc/4.8/chrony.conf.html).
