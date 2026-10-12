# Queue alert 검증 — 2026-10-13

- `runner-alert-tests.stderr.log`: Windows Python3.12 로컬 MOCK49/49, SKIP0. 기존 queue-watch와 새 alert의 상태·실패·권한·증적 경로를 포함한다. stdout은 빈 원본으로 보존한다.
- `runner-alert-validation.json`: 위 로그 SHA, YAML 파싱·Job 권한 분리·Bash2블록 구문과 검증한 소스5파일의 SHA. Git blob과 대조한다.
- `runner-alert-api-observation-final.json`: 04:51:57 KST 검증 소스의 실제 GitHub 읽기. 활성Run0, `NO_ALERT`, `DRY_RUN_NO_COMMENT`, rc0. `--notify`를 사용하지 않았으며 댓글·설정·Runner 변경은 없다. sidecar는 원문 SHA다.

테스트는 fake API이며 댓글 POST도 합성이다. Linux CI·scheduled 감시·실제 알림/수신·O02 운영 인수는 미실행이다. 원문 로그의 CRLF를 포함해 이 디렉터리 파일은 `.gitattributes`로 Git 개행 변환을 막는다. 이후 결과는 별도 회차 경로에 추가한다.
