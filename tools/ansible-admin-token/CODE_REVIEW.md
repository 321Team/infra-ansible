# 작성 후 자체 딥리뷰

구현 전 검토는 DEEP_REVIEW.md에 있다. 이 문서는 독립 승인이나 실제 서버 발급 성공 기록이 아니다.

- 기존 실패 화면의 원인은 UNKNOWN으로 유지했다. 로그인/호스트/메모리 보호/gh/저장소 GET/두 POST/packet/파일 저장 단계를 분리했고 실패 코드·HTTP·rc·시간차만 기록한다.
- API 목적지는 github.com/321Team/infra-ansible에 고정했다. 저장소 GET의 admin 필드를 발급 성공으로 사용하지 않는다. POST는 HTTP201/rc0/JSON 계약, packet은 기존 common.py 정책을 모두 만족해야 통과한다.
- gh의 디버그 강제 출력 변수를 제거하고 stdin을 닫았다. API stdout/stderr·예외 원문·토큰·인증 환경값은 결과/출력에 넣지 않는다. hint는 고정 분류이며 원인을 확정하지 않는다.
- 원본 예외가 민감한 문자열을 포함하는 모형, timeout의 output/stderr, 오류 JSON·임의 stderr에도 비밀값이 최종 출력/압축 증적에 나타나지 않음을 확인했다.
- packet은 홈0600의 별도 파일이다. fsync/write 실패 시 부분 파일을 제거하고, 증적 저장 실패 시 새 packet을 제거한다. archive는 생성한 RESULT/SHA256SUMS 바이트만 포함하므로 홈 packet을 파일 순회로 포함할 경로가 없다.
- 홈0700 디렉터리/0600 packet·archive, 외부 checksum 및 내부 manifest를 시험에서 대조했다. 일반 사용자/ansible01 제약은 유지한다. 호스트/홈 검사 불가, 저장장치 쓰기 실패, 강제 종료 시 증적 생성은 보장하지 않는다.
- 기존 v1.1 Runner 전체 manifest와 ZIP 해시를 다시 대조했다. byte가 같고 common.py도 동일하다. 이 보완 도구를 기존 Runner 폴더에 덮어쓰지 않도록 별도 ZIP/새 경로로 제공한다.
- 단위·모형 및 실제 로컬 자식 프로세스22건 PASS, Python AST3 PASS. 테스트의 HTTP 응답은 모형이며 실제 GitHub 토큰 발급 성공으로 사용하지 않는다.

실제 재실행 전 남은 확인은 ansible01 인증/권한/clock/prctl/API 응답이다. API401/403/404·TLS/DNS 힌트는 후속 확인에 쓰며 자동 로그인·권한 확대·인증서 또는 시스템 시각 변경을 수행하지 않는다. 부분 발급 실패 시 이미 발급된 단기 token의 원격 취소를 수행한 것은 아니다. Runner 등록/해제·실제 Actions·독립 활성화 리뷰는 별도다.
