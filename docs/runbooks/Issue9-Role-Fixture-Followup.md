# Issue9 역할별 기존 증적 재사용·격리 시험 후속 — 2026-10-15

CODEX_ASSISTED · 이권욱. 책임 [#9](https://github.com/321Team/infra-ansible/issues/9).
기준 main `bd5a6bc219e5d471a4bfbce799cdb73b5f4b1976`.
[PR85](https://github.com/321Team/infra-ansible/pull/85)의 운영 경로 준비 다음 단계다.
이 변경은 **시험 코드와 문서**이며 운영 role·wrapper·engine helper·AC를 바꾸지 않는다.

## 1. 기존 성공을 재사용할 범위

### MON

[9/16 격리 원본](https://github.com/321Team/fds-project-evidence/tree/f3b5ea69f5119fc89e15f128c086f1c8eba97fea/evidence/infra-ansible-followup/cicd-runner01-podman-20260916T110635Z)은
source `d5147ebff0febbb8ab2afca28fe64d68301e033c`에서 엔진별 **45/45** 기대결과를 충족했다.
원본 archive SHA256 `194e0fc6c79dc81800fe9d2495340639c7e7ff8043153251dd82218af98adfbd`와
내부 두 엔진 RESULTS의 source/clean/case/rc, 엔진별 manifest78파일을 다시 대조했다.
중첩 archive와 펼친 사본은 같은 실행이며 네 번의 실행으로 합산하지 않는다.

기존 결과를 새 main의 전체 PASS로 복제하지 않는다. 당시 source 이후 차이는
MON apply/rollback의 injected fact 참조 정비와 wrapper의 명시 엔진 helper 연결이다.
백업·baseline guard·marker 중단 모델은 기존 근거를 재사용하고,
새 엔진 연결과 fact 입력은 현재 코드에 맞춘 검증으로 구분한다.
[증적150](https://github.com/321Team/fds-project-evidence/pull/150)은 실제 후보2.21.3
verify/changed0·허용200/차단403이며 실제 apply/rollback 전체 인수는 아니다.

### NTP

[기존 two-source 검증](../change/CR-P1-NTP-01-01-two-source-validation.md)의
LOCAL/MOCK **301/301**과 syntax7은 **2.16.19** 기준이다.
기록은 당시 uncommitted 변경의 파일별 SHA256을 고정한 것으로,
SUMMARY의 source_head만을 실제 실행 코드 전체의 커밋으로 사용하지 않는다.
해당 source 해시37개와 현재 main을 대조하면33개 동일,
차이는 `fds_ntp_probe.py`, `_legacy.yml`, NTP wrapper, `test_probe.py`의4개다.

기존 [후보 엔진 차단 기록](../change/CR-P1-NTP-01-01-review-fix-validation.md)은
LocalRPC 시작 실패이며 2.21.3 역할 동작 PASS가 아니다.
이번에 조회한 기록에서는 후보의 migration/legacy-role/serial/transport 성공을
입증하지 못했다. 다른 미조회 자료의 부재까지 단정하지 않는다.

## 2. 이번에 바로잡은 시험 준비물

| 결함 | 실제 영향 | 보완 |
|---|---|---|
| MON recap 함수만 추출, engine helper 미로딩 | 정상 recap도 `fds_engine_exec`를 찾지 못해 inventory 전에 실패 | 실제 sibling helper를 로딩·초기화. `--ansible-bin`에 연결된 PATH를 사용하고 호출자의 engine opt-in 변수는 시험 환경에서 제거 |
| NTP wrapper 사본에 `scripts/lib/ansible-engine.sh` 누락 | 실제 wrapper가 action 전에 source 실패 | wrapper와 실제 helper를 함께 복사. 시험의 fake playbook 경로를 외부 engine opt-in으로 우회하지 않도록 제거 |
| NTP fixture의 `ansible_date_time` | 현행 `_legacy.yml`의 `ansible_facts['date_time']`가 없어서 baseline 생성 실패 | legacy/migration/serial fixture 입력과 재적용 timestamp를 현행 namespace로 맞춤 |

운영 역할의 보호 조건을 완화하지 않았다. MON 운영 wrapper 자체를 source하지 않고
순수 recap 함수만 호출한다. NTP 실제 실행창·승인값·host·credentials는 소비하지 않는다.

## 3. 검증 상태

- **MOCK 7/7**: Windows Git Bash, 실제 MON recap/helper와 fake inventory.
  과거 추출의 양성 실패 재현, 수정 후 정상·changed·localhost-only·wrong/extra target 거절,
  inventory 실패의 비정상 종료 및 상속된 engine 변수 차단.
- **MOCK 4/4**: NTP fixture가 생성한 YAML의 실제 production timestamp 표현식 렌더링,
  재적용 timestamp, 옛 namespace 거절, wrapper/helper 사본 바이트 확인.
  Ansible 호출 직전 중단하며 이를 role PASS로 사용하지 않는다.
- **STATIC**: 변경 Python AST, diff whitespace, 아래 기존 명령·CLI 옵션 대조.
- **Linux 양 엔진 전체 MON 및 NTP 후보 역할 동작**: 이번 변경에서는 **미실행**.
- **CI/독립 REVIEW/MERGE**: 이 PR의 실제 상태를 따른다. PR85 CI는 이 새 변경의 CI가 아니다.

## 4. 남은 격리 실행의 고정 범위

기존 [MON 복구 시험](CR-P1-MON-01-01.md#6-roll-back-when-required)과
[NTP migration fixture](../../tests/ntp_source/README-migration.md)를 재사용한다.
새 일반 CI나 O02 재실습으로 대체하지 않는다.

필요 환경은 운영 키/토큰·호스트 소켓·운영 `/etc` 마운트가 없는 Linux 격리 공간이다.
네트워크가 차단된 상태에서 Python3.12, 저장소 lock의 두 engine venv,
PyYAML/Jinja2, 기존 chronyd parser가 있어야 한다. NTP migration/serial은
**격리 공간 내부 uid0**과 root 소유의 보호된 임시 경로가 필요하며
운영 호스트 root로 실행하거나 기존 Runner의 uid1000 제약을 임의 변경하지 않는다.
현재 Windows에서는 이 Linux 조건을 확인하지 못했다.

실제 공급 전 실행자는 아래 값을 한 번에 고정한다. 이번 PR은 환경 생성/서버 배치 허용이 아니다.

- 검토된 source SHA와 clean checkout, source와 별도인 새 결과 부모.
- 두 engine의 CLI 경로·버전·lock, parser 경로·버전·SHA.
- 격리 backend/uid/mount/network/CPU·메모리·PID 제한, 종료와 정리 책임.
- 실행창·해당 호스트 다른 업무와 비중첩. Harbor 및 운영 Ansible 전환은 별도다.

다음은 그 **격리 공간 안에서만** 사용할 카드다. `REPO`, `BIN216`, `BIN221`,
`CHRONYD`, `OUT`은 위에서 고정한 절대 경로이고 `OUT`은 새 보호 경로다.
미확정 상태에서 placeholder를 운영 경로로 치환하여 실행하지 않는다.

```bash
set -euo pipefail
cd "$REPO"
unset FDS_ANSIBLE_ENGINE_DIR FDS_ANSIBLE_ENGINE_VERSION

# 새 helper 연결의 Linux/엔진 결합: 기존 task/body 전체를 다시 고치는 작업 아님.
"$BIN216/python" -B tests/run-egress-recovery.py --ansible-bin "$BIN216" --output "$OUT/mon-216"
"$BIN221/python" -B tests/run-egress-recovery.py --ansible-bin "$BIN221" --output "$OUT/mon-221"

# 엔진과 무관한 module 거래 전체는 기존 결과의 파일 동일성을 우선 재사용.
# 후보 Ansible flow와 실제 module transport에 집중한다.
export PATH="$BIN221:/usr/bin:/bin"
"$BIN221/python" -B tests/ntp_source/test_ntp_source.py --ansible-playbook "$BIN221/ansible-playbook" --output "$OUT/ntp-legacy-221" --jobs 2
"$BIN221/python" -B tests/ntp_source/test_migration.py --suite flow --ansible-playbook "$BIN221/ansible-playbook" --chronyd "$CHRONYD" --output "$OUT/ntp-flow-221" --jobs 2
"$BIN221/python" -B tests/ntp_source/test_rollout_serial.py --ansible-playbook "$BIN221/ansible-playbook" --chronyd "$CHRONYD" --output "$OUT/ntp-serial-221"
"$BIN221/python" -B tests/ntp_source/test_module_transport.py --ansible-playbook "$BIN221/ansible-playbook" --output "$OUT/ntp-transport-221"
"$BIN221/python" -B tests/ntp_source/test_wrapper.py "$OUT/ntp-wrapper"
```

이 카드는 실행 명령 본체이며 실행자는 각 명령의 argv/cwd/source/시각/rc와 stdout/stderr를
별도로 보존해야 한다. 실패하면 다음 suite를 시작하지 않고 결과 디렉터리를 남긴다.
보안 통제를 풀거나 실패 사례를 빼서 PASS로 바꾸지 않는다. 정리는 소유한 격리 객체만
대상으로 하고 원본/해시 회수 후 수행한다. `RESULTS.json`의 실제 사례 집합과
예상 거절 rc를 대조하며 rc0 한 값만으로 전체 범위 완료를 선언하지 않는다.

이후에만 실제 운영 caller/source/config/engine·복귀와 전환 시점6노드 비교를
[기존 준비서](Issue9-Operating-Transition-Readiness.md)에 결합한다.
정상 MON/NTP 서비스를 과거 backup으로 돌리거나 신규 장애를 주입하지 않는다.
DNS 증적208·helper 버전 출력·기존 CI를 같은 결과를 얻기 위해 반복하지 않는다.
