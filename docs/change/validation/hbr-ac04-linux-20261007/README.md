# HBR AC04 오프라인 분석 — Linux MOCK 수신 기록

CODEX_ASSISTED. infra-ansible#62 [검토 의견6036319385](https://github.com/321Team/infra-ansible/issues/62#issuecomment-6036319385)의 해시·로그 보존 후속이다.

## 출처와 검증 범위

- 시험 소스: 준비 커밋 `b067a21f8ecce0c79052b0ac2ba9f2df54fab882`의 4파일. 도구·시험 코드는 이 PR에서도 동일 바이트다.
- 실제 실행 위치: ansible01 / server01_ansible / Python3.12.14, `/home/server01_ansible/p1-offline-validation.bHRqcUbI/`.
- 명령: `python3.12 -B hbr/tests/test_p1_hbr_ac04_docker_chain_analysis.py > hbr-test.stdout.log 2> hbr-test.stderr.log`.
- 결과: 합성 입력 18개 OK. 실행 도구 응답에 `HBR_TEST_RC=0`을 관측했다. 별도 서버 rc 파일은 생성하지 않았으므로 이 기록을 당시 서버 rc 원본 파일로 표시하지 않는다.
- 시간: 두 서버 로그 mtime은 2026-10-07 19:37:31 KST다. 독립적인 실행 시작/종료 로그는 없으며 mtime을 정확한 실행 구간으로 확대하지 않는다.
- 원 stdout(0바이트)·stderr(2259바이트)를 재작성하지 않고 보존했다. 후속 서버 읽기 재대조의 stdout/stderr도 원 바이트이며 명령·시각·종료코드는 RECEIPT.json에서 추적한다.
- `RECEIPT.json`의 source_files는 **시험 당시 원본 4파일**의 hash다. 현재 정정한 runbook hash와 혼동하지 않는다.

도구·시험·runbook 3개 hash는 이미 준비 커밋의 SOURCE.json에 있었다. 이번 후속은 Linux 로그와 SOURCE.json 자체를 포함한 4파일 수신/서버 재대조 기록을 추가한다. 기존 SOURCE.json의 Windows 시험 결과와 당시 Linux 미실행 기록은 그대로 보존한다.

## 현재 편입 바이트 확인

저장소 루트에서 `sha256sum -c docs/change/validation/hbr-ac04-linux-20261007/CURRENT_SHA256SUMS`로 이번 편입 파일을 확인한다. manifest는 자기 자신을 제외한다. 검증 결과는 바이트 일치이며 현장 시험 성공이나 AC 승인 증거가 아니다.

현재 runbook에는 A″ 및 10/7 동일 1회 GO의 실행자·창·조건을 연결했다. 과거 17:00/NO-GO와 PR66 queued 문구는 현재 계약으로 사용하지 않는다. 이 문서 정정은 새 회차·시간 연장·자동 재시도 승인이나 verifier 변경이 아니다.

## 상태와 남은 조건

STATIC=기존 도구/시험 바이트 동일, MOCK=Linux18 OK. 이 PR의 CI/독립 리뷰/병합은 GitHub의 해당 HEAD 상태를 따르며 Linux MOCK으로 대신하지 않는다. 실제 harbor01 원본 분석·Docker Runtime·AC04 인수는 이 회차에서 수행하지 않았다. unsupported drift/누락/hash 불일치는 중단하고 원본을 보존한다. 현장 원본 수신 후 기존 승인 조건과 별도로 대조한다.

복구: 이번 PR은 운영 verifier·서버 설정을 변경하지 않는다. 문서 보완이 필요하면 새 수정 커밋으로 남기며 원본 로그와 과거 기록을 덮어쓰지 않는다.
