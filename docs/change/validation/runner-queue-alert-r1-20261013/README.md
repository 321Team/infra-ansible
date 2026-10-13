# PR81 R1/N1 변경분 검증 — 2026-10-13

검토 기준 HEAD `bd1e7876382eab9c0df322a8a4d44546d2d8fd94`. [이재환 R1/N1](https://github.com/321Team/infra-ansible/pull/81#pullrequestreview-5497322141)과 [이하영 보안 의견](https://github.com/321Team/infra-ansible/pull/81#pullrequestreview-5497587075)에 대한 변경분이다.

- STATIC: workflow Bash 블록2개 구문, 권한·main/트리거/Action SHA·기존 알림 명령·기본 비활성 조건 보존 대조 PASS. cron만 바뀌고 설정 검사만 추가됐다.
- LOCAL BASH MOCK: Windows Git Bash에서 workflow 원문 두 블록을 추출해 정상5종·거부15종, 합계40사례 PASS. threshold 누락/공백/0/상한 초과/비숫자/명령 형태/개행/Unicode 입력은 rc2·변수값 비출력·관측 도구 호출0. 정상 경계와 앞0 허용은 기존 CLI 인수를 보존한다. python3 함수를 stub으로 대체했으며 실제 alert 실행/API 호출0이다.
- STATIC: UTC cron을 KST로 대조해09:07~23:37/30회·야간 공백570분 확인. Job당1분 가정으로30일900분·14일420분이며 실제 잔여 Billing 사용량은 NOT_VERIFIED다.
- REUSED: 기존 alert/watch 소스와 시험, 운영자 카드 바이트는 기준 HEAD와 동일. 기존 MOCK49/0SKIP 원본은 [이전 회차](../runner-queue-alert-20261013/README.md)를 그대로 사용했다. 이49건을 다시 돌리지 않았으며 이번40사례와 합쳐 새로운 전체 회귀 통과 숫자로 표시하지 않는다. 독립 리뷰의 Linux49 OK는 해당 리뷰 원문 범위이고 GitHub CI가 아니다.
- 이전 검증 디렉터리는 바이트 단위로 보존했다. `verification-delta.json`은 이번 검사 결과/소스 해시이며 실제 서버·scheduled/발송·사람의 수신·O02 증적이 아니다.

재현 환경: Python3, PyYAML6.0.3, Git, Bash, 위 기준 HEAD Git 객체가 있는 checkout. 저장소 루트에서 새 출력 경로를 사용한다:

```text
python -B docs/change/validation/runner-queue-alert-r1-20261013/verify_delta.py --repo . --output <존재하지_않는_JSON> --bash <bash_실행파일>
```

PyYAML이 별도 디렉터리에 있으면 `--yaml-path <디렉터리>`를 추가한다. 실제 검증은 Windows 번들 Python과 `C:/Program Files/Git/bin/bash.exe`를 사용했다. 도구는 GitHub를 호출하지 않고 검사 결과 JSON 하나를 배타 생성한다. 새 HEAD의 GitHub CI 결과는 PR에서 별도 확인한다. 알림 활성화·새 Runner/token 공급·서버 실행·O02 인수는 미실행이다.
