# 구현 전 딥리뷰 — 관리 호스트 토큰 도구 보완

검토 입력: 사용자 ansible01 화면의 ZIP/manifest 성공 및 `STOP: RuntimeError`, 검증된 Runner v1.1 admin-token.py/common.py/launch.py.

## 확정 사실과 미확정 원인

- admin-token.py의 마지막 예외 처리기는 예외 종류만 출력한다. host/UID, prctl, gh 존재, 두 POST 실패, packet 형식/만료, 홈 검사 중 어느 조건이 실패했는지 화면으로 식별할 수 없다. UID/호스트나 GitHub 권한 문제를 확정하지 않는다.
- 동일 화면만으로 등록 토큰 POST가 한 번도 호출되지 않았다고 단정할 수 없다. 일부 발급 후 다음 단계에서 실패할 수 있다. 이 도구 자체는 Runner 등록·Job 실행을 하지 않는다.
- 먼저 발급한 뒤 홈을 검사하는 순서 및 유효시간·단계 미기록이 진단을 어렵게 한다.
- common.packet은 문자열 형식과 두 토큰의 남은 시간10~120분을 검사한다. 이 정책을 완화하지 않는다.
- PREPARED는 Runner bundle manifest/image에 묶인다. 기존 tools/ansible-runner 및 v1.1 ZIP은 바꾸지 않고 별도 관리 호스트 보완 도구를 제공한다.

## 구현할 수정

1. 일반 ansible01 계정, 검증된 로그인 홈, memory dump 차단, gh 존재, 저장소 읽기, registration POST, removal POST, packet 검증,0600 저장을 단계로 구분. 홈/도구/호스트 검사는 API 전에 수행.
2. 사용자에게 예외 원문/traceback/API 원문/gh debug/token을 출력하지 않는다. 자체 고정 오류코드·returncode·HTTP 숫자·시간차·진단 분류만 기록한다. 분류는 원인 확정이 아닌 단서다.
3. 고정 repository/hostname과 API 버전, gh 비대화식 실행, GH_DEBUG/GH_FORCE_TTY 제거. timeout과 nonzero는 FAIL. 발급된 packet은 모두 검증한 뒤에만 저장. 중간 실패에는 packet을 남기지 않는다.
4. 발급 packet은 홈0600 별도 파일; 진단 증적은 홈0700 신규 디렉터리에 고정 JSON/manifest만 압축한다. 폴더 전체나 원문 로그를 압축하지 않는다. 실패도 증적과 nonzero를 보존한다.
5. 기존 common.py를 바이트 그대로 사용하여 packet 계약 유지. tokens/PAT는 명령 인자에 넣지 않는다. 패킷 저장 후 증적 보존 실패 시 이번 packet을 제거하고 실패한다.

## 검증할 위험

API401/403/404·DNS/TLS·timeout·permission/spawn·gh미설치·prctl실패·만료/형식 불일치·부분 발급·write 실패·출력/증적의 비밀 누출·0600/0700·기존 도구 바이트 보존. 실제 사용자 API 원인은 다음 실행 증적 전까지 UNKNOWN.

공식 근거: https://cli.github.com/manual/gh_api , https://docs.github.com/en/rest/actions/self-hosted-runners#create-a-registration-token-for-a-repository
