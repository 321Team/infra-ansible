# Controller-local validation

2026-10-09 KST · CODEX_ASSISTED · ansible01/server01_ansible, UID1000.

- ansible-core 2.16.19: 전체 단위시험 208건 PASS(DNS 관련 51건 포함).
- ansible-core 2.21.3: DNS 관련 51건 PASS.
- 전체 syntax 38개 × 두 엔진 = 76건 PASS, shell syntax PASS.
- 기존 일반 wrapper/rollback 및 role의 비옵트인 동작 정적 대조 PASS.
- worker02/다른 managed host 접속, sudo, 실제 DNS/서비스 변경, 운영 엔진 전환: NOT_RUN.

`VALIDATION.json`은 명령·시각·rc·격리 경로·검사 대상 source hash를 보존한다.
`run-validation.py`는 당시 runner 복사본이다. source root에 배치하여 정상 controller
계정으로 실행한 프로그램이며 이 문서 경로에서 바로 실행하는 런북이 아니다.
단위시험 및 버전 출력은 원본 바이트 그대로이고, syntax와 shell의 stdout/stderr 원본
154개는 `syntax-logs.tar.gz`에 보관했다. `SYNTAX_ARCHIVE_CONTENTS.json`에서 각 원본
길이/hash를 확인할 수 있다. 압축 파일은 source/credential/운영 payload를 포함하지 않는다.

파일 시험은 UID1000 임시 파일에 대한 실제 I/O다. 범위 fixture는 local 연결과
대체 role을 사용하며, 흐름 fixture는 NM/서비스/네트워크 I/O만 합성하고 production
태스크 조건·rescue와 snapshot 함수를 실행한다. 운영 root·SELinux·SSH·live resolver
및 동시 작성자 배제 검증, GitHub CI, 독립 리뷰, Runtime GO와 구분한다.
