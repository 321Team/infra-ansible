# Issue9 2026-10-15 읽기·native helper 버전 원본

CODEX_ASSISTED · 이권욱. 00:38~00:39 KST, 기존 ansible01/server01_ansible SSH 계정에서 수행한 고정 Git/파일 메타데이터/CLI --version 조회와 helper 선택 진단이다. 운영 전환·관리 대상 시험·역할별 인수 증적이 아니다.

- `controller.stdout.json`: 운영/기존 검증 checkout·파일 metadata 및 세 엔진 CLI4종의 원 출력/rc.
- `helper.stdout.json`: 기존 검증 source helper의 후보→이전→unset-fixed-PATH, CLI4종 --version 원 출력/rc. init 내부 조회와 출력12개를 구분한다.
- `*.receipt.json`: 데스크톱 SSH 요청·시각·종료코드·실행한 수집기 SHA·수신 stdout/stderr SHA. 서버 서명/독립 봉인은 아니다.
- `*.py.txt`: 실제 stdin으로 보낸 수집 코드 보존 사본. 이 경로의 파일을 실행/배포 입력으로 사용하지 않는다.
- `VERIFICATION.json`: 수신 원본 해시·16경로(Git 일치15/예상 부재1)와 12출력 순서·source 차이 재계산 결과. Runtime 성공·AC 전체 충족으로 확대하지 않는다.

기존 운영 checkout/RPM/PATH·서비스·설정·credential·타 호스트는 변경하지 않았다. helper 프로세스 내부 환경변수만 바뀌고 종료됐다. 원본은 수정하지 않았으며 과거9/25·10/5·10/8·10/13 자료를 소급 갱신하지 않는다. full env/history/credential 값은 수집하지 않았다. 설치된 CLI 파일 SHA/버전은 package 공급·모든 실행 경로의 증명이 아니다.

무결성: 이 디렉터리에서 `sha256sum -c SHA256SUMS`. 전체 실행/인수 범위는 [준비 문서](../../../runbooks/Issue9-Operating-Transition-Readiness.md)를 참조한다. 별도 CI/운영 전환 승인·티켓 종결은 이 읽기 결과로 생성되지 않는다.
