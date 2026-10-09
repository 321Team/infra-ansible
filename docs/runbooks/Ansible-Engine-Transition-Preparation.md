# Issue #9 엔진 전환 준비 — v1.0

작성일: 2026-09-24 KST. 책임 티켓: [infra-ansible #9](https://github.com/321Team/infra-ansible/issues/9).
단계: **PREPARATION / 운영 전환 PENDING**. 현재 승인 대상 엔진은 기존 #9의 2.16.19 → 2.21.3이며, 최신 버전 선정 작업으로 범위를 넓히지 않는다.

2026-10-09 후속: 아래 9/24 조사 시점은 이력으로 보존한다. 일반 CI 종결·별도 시험 checkout·기존 worker02 성공과 현재 남은 단일 대상/복구 원본 조건은 [worker02 다음 canary 준비](Issue9-Worker02-Canary-Next.md)에 연결했다. 운영 전환 완료나 새 Runtime GO는 아니다.

## 1. 이번 결과와 재사용 범위

| 구분 | 확인한 범위 | 아직 확인하지 않은 범위 |
|---|---|---|
| 코드 조사 | main `fa12a35578ba33e6b7fb4e0e037c0a11631f41d1`의 wrapper 4개가 PATH의 `ansible-playbook` 호출 | 운영 checkout·로그인 shell·cron·systemd가 실제 선택하는 엔진 |
| 기존 운영 자료 | 9/8 자료에는 `/usr/bin/ansible-playbook`, core 2.16.19, CentOS RPM `2.16.19-2.el10`, Python 3.12.13 기록 | 현재 설치/공급원·배포사 backport·예약/Runner 호출 경로 |
| 기존 영향 분석 | #9에 9/23 기준 injected facts 12파일·50참조 목록 확보 | 이번에 참조 수 재계산 또는 facts 코드 정비를 수행한 것은 아님 |
| 최근 구문 검사 | PR47 `c6ba5f87711acc3eeeba12c13c72cedd09d178f8`에서 두 엔진 합계 46/46 | 구문 PASS가 실제 apply·멱등성·rollback을 입증하지 않음 |
| 신규 수집기 | 로컬 단위·모의 시험, 비밀 값/원문 미출력, 수집 대상 미실행, 누락 상태 구분 | ansible01·cicd-runner01 실제 수집 NOT RUN |

이번 PR은 읽기 전용 수집기·시험·계획만 추가한다. 운영 wrapper, 엔진, 패키지, CI 설정, 티켓의 AC·담당·일정은 변경하지 않는다.

## 2. 호출 경로별 조사 결과와 후속

아래 소스 경로는 위 main에 고정한 정적 관찰이다. 실행 여부·운영 배치 여부는 현장에서 확인한다.

| 진입점 | 현재 코드가 선택하는 엔진 | 수집·전환 계획 |
|---|---|---|
| `scripts/cr-p1-ans-01-01-run.sh` | PATH의 `ansible-playbook` | DNS apply/verify/rollback 모두 같은 고정 엔진인지 확인 |
| `scripts/cr-p1-mon-01-01-run.sh` | PATH의 `ansible-playbook` | MON apply/멱등성/rollback의 엔진·대상 일치 확인 |
| `scripts/cr-p1-ntp-01-01-run.sh` | PATH의 `ansible-playbook`; 잠금 도구도 PATH의 `python3` | NTP 개별 선행조건·잠금·source binding 유지, 엔진 전환으로 네트워크 STOP을 우회하지 않음 |
| `scripts/p1-k8s-01-gate0-run.sh` | PATH의 `ansible-playbook` | Gate0 읽기 전용 검사와 향후 운영 적용 범위 구분 |
| `scripts/verify-ssh-main.py` | 명시한 `--python216`, `--python221`; 구버전 기본값 `/usr/bin/python3` | 향후 비교 시 두 엔진 모두 절대 경로로 명시하고 기존 결과 계약 재사용 |
| 수동 shell / cron / systemd | 현장 미확인 | alias·function·환경파일·작업 디렉터리·동시 실행·예약 대상 확인 |
| Runner | 현장 미확인 | infra-cicd 영구 Runner와 infra-ansible 격리 Runner를 별도 행으로 기록. workflow SHA·image digest·실제 명령 확인 |

권고안: 운영 시스템 RPM과 전역 PATH를 먼저 바꾸지 않고, 호출 경로별로 검토된 wrapper가 고정 venv의 절대 실행 경로를 선택하도록 후속 코드 변경을 준비한다. 기존 wrapper에 임의 인수나 환경변수를 주입해 canary 제한을 우회하지 않는다. 현재 wrapper는 범용 canary `--limit` 전달 인터페이스가 아니다. 실제 수집 후 필요한 최소 변경 diff를 별도 검토한다.

## 3. 지금 실행 가능한 순수 수집

실행 위치: **ansible01 / server01_ansible**, 기존 checkout `/home/server01_ansible/p1-ans-01`.
필요 환경: Linux, Python 3.9 이상(현장 Python 3.12 사용), 기존 비관리자 계정. Python 표준 라이브러리만 사용한다. 도구 설치·sudo·dnf/pip·SSH·Ansible 실행은 없다. 고정된 로컬 조회는 `/usr/bin/git rev-parse`, `/usr/bin/rpm -q`, 현재 사용자의 `/usr/bin/crontab -l` 세 가지다.

실행 전 담당 Lead는 `tools/collect-ansible-callpaths.py`가 중앙 정책 §3.2의 순수 검증기 조건에 해당함을 확인한다. 기존 권한으로 한 번 실행하며 지정 결과 경로 외 설정 변경·상주·서비스 조작이 없다. 이 확인을 독립 코드 리뷰나 운영 전환 승인으로 기록하지 않는다.

배포 ZIP을 홈 아래 새 폴더에 풀고, 해당 폴더로 이동한 다음 실행한다. 기존 checkout을 갱신하거나 운영 branch를 바꿀 필요가 없다.

```bash
cd /home/server01_ansible/FDS_Ansible_Issue9_Preparation_v1.0
sha256sum -c SHA256SUMS
python3.12 -I -B tools/collect-ansible-callpaths.py \
  --expected-host ansible01 \
  --expected-user server01_ansible \
  --repo /home/server01_ansible/p1-ans-01 \
  --output-parent /home/server01_ansible
```

출력 JSON의 `output`은 새 `/home/server01_ansible/ansible-callpaths-...` 경로다. 0700 디렉터리, 0600 결과 파일을 만든다. 매 실행에 새 경로를 생성하며 이전 자료를 덮어쓰지 않는다.

**수집 정상 종료:** exit 0, `REPORT.json`의 `completed=true`, `status=COLLECTED_REVIEW_REQUIRED`, 내부 `sha256sum -c SHA256SUMS` 성공. 이는 수집기 종료이며 #9의 첫 수집 AC 완료나 운영 PASS가 아니다. `coverage_gaps`, `manual_followup`, 각 query rc를 검토해야 한다. `crontab -l` 비정상 종료를 예약 작업 없음으로 판정하지 않는다.

**중단:** host/account 불일치, root 실행, 잘못된 출력 경로는 exit 64로 수집을 시작하지 않는다. 예상 밖 오류는 `INCOMPLETE_COLLECTION`/exit 2이며 생성된 결과를 보존한다. 권한 부족·링크·대용량/파일 수 제한은 파일별 미확인으로 남긴다. 권한을 늘리거나 보안 통제를 끄지 말고 기존 담당자에게 해당 경로의 읽기 결과를 받는다. Ctrl+C 시 부분 결과 디렉터리는 보존한다. 설정을 변경하지 않으므로 엔진/서비스 복구 작업은 없다.

수집 파일 범위는 repo의 알려진 진입점, 현재 PATH 후보, 사용자 shell 시작 파일, cron 표준 경로, system/user unit와 drop-in, `/etc/yum.repos.d/*.repo`다. 파일 최대 256 KiB, 전체 본문 8 MiB, 디렉터리당 1,200 항목 제한이다. 원문·명령 인수·환경 변수 값·repository URL·시크릿은 출력하지 않고 파일 메타데이터와 Ansible/Python 참조 위치만 기록한다. Ansible 설정/Collection의 유효 값과 동적 shell 해석은 자동 확정하지 않는다.

알려진 사용자 wrapper/Runner workflow가 기본 범위 밖에 있으면 동일 명령에 `--file /절대/경로`를 추가한다. 지정 파일은 읽기만 하며 실행하지 않는다. 비밀 파일·전체 홈/로그를 추가하지 않는다. 파일 링크는 자동 본문 수집하지 않으며 운영자가 확인한 정규 파일을 별도 지정한다. `/bin` 등 PATH CLI 후보의 canonical 파일은 메타데이터를 위해 별도 읽을 수 있다.

## 4. 수신 뒤 보완할 항목

`docs/change/issue-9-callpath-inventory.tsv`에 확인한 경로마다 행을 추가한다. 비밀 값이나 전체 명령줄 대신 실행 파일·스크립트/설정 경로와 source SHA/hash를 적는다.

1. `REPORT.json` host/user/time/collector hash와 세 query 결과 확인. 과거 9/8 값과 현재 값을 분리한다.
2. 실제 shell에서 alias/function 유무 및 실행 파일·config·collection 경로를 기존 권한으로 확인한다. 전체 `env`, history, shell 초기화 파일을 공유하지 않는다.
3. cron·systemd의 간접 호출, `EnvironmentFile`, root/다른 계정 예약 작업, 활성 timer/일시 생성 unit은 해당 계정/담당자 확인으로 보완한다. 수집기의 파일 목록만으로 활성 실행 경로 전체를 확인했다고 하지 않는다.
4. `.repo` 정의는 현재 설정된 저장소 목록이다. 설치된 RPM의 실제 originating repo와 vendor backport 증거는 별도 읽기 자료가 필요하다. 이번 키트는 dnf metadata 갱신이나 package cache 생성을 하지 않는다.
5. Runner는 관리 기록의 등록 저장소/labels와 해당 job의 workflow SHA·image digest·실제 venv 명령을 결합한다. CI 격리 Runner를 운영 배포 경로로 자동 전용하지 않는다.
6. 누락 항목이 남으면 #9 첫 수집 AC는 미완료로 유지한다. 자료가 확인된 경로에 대해서만 후속 변경 설계를 확정한다.

## 5. canary 실행 계획 — 준비용, 이번 키트에서 실행하지 않음

현재 계획의 실제 운영 canary와 전환은 #5 일반 CI 인수 후 진행한다. #5의 상세 실행/리뷰 조건은 [#5](https://github.com/321Team/infra-ansible/issues/5)를 따른다. 증적 PR24 병합 자체를 별도 서버 준비/실행 선행조건으로 추가하지 않는다. 병합 전 로컬·모의·격리 후보 시험은 기존 Lead 권한으로 가능하다.

| 순서 | 고정할 입력·수행 | 정상 판정 / 중단 기준 |
|---|---|---|
| 실행 전 | 정확한 source SHA·inventory hash·변수 hash, 기존/후보 Python와 ansible-playbook 절대 경로·버전·lock, 대상 1대와 변경 role, 백업과 콘솔/SSH 복구 경로 | 하나라도 미확정이면 apply 중단. inventory 전체나 그룹을 canary 1대로 간주하지 않음 |
| 사전 비교 | 동일 코드와 대상에 기존 #6/#7 검증 계약 사용, 현재 SSH·OS·DNS와 target Python 확인 | 엔진/호스트/완료 표식 불일치, ERROR·unreachable·예상 외 변화 시 중단 |
| 후보 1차 적용 | 승인된 canary 1대·role만 2.21.3로 실제 apply, 구조화 결과/rc/백업/변경 목록 보존 | 예상 변경만 허용. 실패·연결 손실·범위 확대·source 변동 시 즉시 중단 |
| 실제 재적용 | 같은 코드·inventory·변수·엔진으로 같은 canary에 두 번째 실제 apply | 실패0·unreachable0, 관리 설정 변화0. 백업/기록 태스크의 changed는 개별 분류하며 check-mode만으로 멱등성 완료 판정하지 않음 |
| fresh SSH | 기존 연결을 재사용하지 않는 신규 SSH로 대상·계정·키·OS/DNS와 role별 결과 재확인 | 새로운 연결 실패 시 다음 대상 확대 중단 |
| 복구 검증 | 해당 role의 기존 rollback/백업 절차와 엔진 호출 경로 복구를 각각 시험 | 파일/서비스/권한/연결의 사전값 복원, 이전 엔진 절대 경로·버전 재조회로 확인 |
| 범위 확대·전환 | role별 apply/rollback 분기 검증 후 Lead가 범위 확대. 수동·예약·Runner 호출 경로별 명시적 전환 | 미확인 경로 남음·이중 실행 위험·rollback 실패 시 전환 중단 |
| 전환 후 | 각 실제 진입점에서 executable/realpath/core/config/collections 재조회 및 기존 회귀 계약 확인 | 일부 CLI 성공만으로 전체 전환 완료 처리하지 않음 |

첫 canary 대상·role은 아직 선정하지 않았다. 기존 SSH hardening 검증 계약을 재사용하는 방향으로 검토하되, 현재 상태·복구 가능성·영향을 확인한 후 확정한다. DNS/MON/NTP 등 다른 role의 미완료 apply/rollback AC는 별도로 남는다. NTP 네트워크 관련 개별 STOP은 해당 작업에서 해소해야 한다.

## 6. 실패 시 복구 원칙

- **엔진 선택 복귀:** 변경했던 각 호출 경로만 이전의 확인된 절대 실행 경로로 되돌리고 버전·realpath를 재조회한다. 운영 RPM 제거/교체, 전역 PATH 수정, 기존 venv 삭제를 기본 복구로 사용하지 않는다.
- **대상 상태 복구:** 엔진을 되돌려도 이미 적용한 DNS·SSH·MON·NTP 설정은 복원되지 않는다. 해당 role의 검토된 rollback 또는 백업 복구를 사용하고 사전 hash·권한·서비스 상태·fresh SSH를 비교한다.
- **동시 실행:** 예약/Runner 작업과 충돌할 경우 추가 실행을 중단한다. 작업 중지/재개는 실제 수집한 경로와 기존 운영 절차에 따라 Lead가 결정하며 이번 수집기는 이를 조작하지 않는다.
- 실패 원문·대상·source/engine·최종 상태를 보존한다. 임의 `rm -rf`, `podman prune`, 홈 초기화, 보안 옵션 완화는 복구 절차에 포함하지 않는다.

## 7. 검증·리뷰·추적

로컬 검증 원문: `docs/change/validation/issue-9-callpaths/`.
신규 코드는 Pre-check 수집기이며 `REVIEW=NOT PERFORMED (Pre-check)`다. 작성·단위/모의 시험과 실서버 실행·독립 리뷰·병합·운영 전환은 별개다. 이번 작업은 main 직접 push나 자동 병합을 수행하지 않는다.

근거:

- [현행 #9 요구사항과 잔여 AC](https://github.com/321Team/infra-ansible/issues/9)
- [기준 main](https://github.com/321Team/infra-ansible/tree/fa12a35578ba33e6b7fb4e0e037c0a11631f41d1)
- [기존 운영 엔진 기록](https://github.com/321Team/fds-project-evidence/blob/9a3d03341d8878f43e97d5ab9fc040b0037c9250/evidence/P1-ANS-01/pr4-runtime-apply-20260908/results/operational_engine_version.txt)
- [기존 controller 패키지 기록](https://github.com/321Team/fds-project-evidence/blob/9a3d03341d8878f43e97d5ab9fc040b0037c9250/evidence/P1-ANS-01/pr4-runtime-apply-20260908/results/controller_engine_context.txt)
- [Pre-check/Lead 권한 정책](https://github.com/321Team/infra-ansible/blob/fa12a35578ba33e6b7fb4e0e037c0a11631f41d1/docs/REVIEW_POLICY.md)
