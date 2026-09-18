# v1.2 수정 후 자체 코드 검토

- 선행 검토: REGISTRATION_FAILURE_REVIEW.md (수정 전 작성).
- container.py: .NET UTF-8 BOM 파일을 지원하는 bounded read와 엄격한 UTF-8/JSON 해석. URL·새 UUID 이름·양의 정수 ID 검사 유지. 추가 필드 및 틀린 원문 값은 내보내지 않음.
- runner.py: 고정 실패 단계/예외 열거값, identity boolean만 보존. 오류 메시지·토큰·원본 native 로그·.runner 전체를 수집하지 않음.
- 실패 시 remove 회복 뒤에도 FAIL 유지. 실제 제거 실패는 정확한 ID/name을 남기며 PASS 차단. 계정·권한·proxy·cgroup·SELinux 및 cleanup 경계 변경 없음.
- 새 등록 회귀12건, 기존37건 총49건 PASS. 모의 configure/remove는 실제 등록이 아님. Python AST9파일, bash 구문 PASS.
- 실서버 관측은 이전 v1.1 configure/remove rc0 및 전체 FAIL. 직접 예외는 증적 미보존으로 UNKNOWN. BOM 결함 수정의 서버 효과는 새 prepare와 재등록 검사에서 확인해야 함.
- launcher/common/Containerfile/admin-token/proxy/account 검사 코드는 이전본과 동일. container.py는 이미지 포함 파일이므로 이전 PREPARED/이미지 결합 재사용 금지.
- 독립 리뷰 승인, 실제 새 이미지 검증, Actions 성공, 병합/운영 적용을 이 자체 검토로 주장하지 않음.

이전 설계 검토와 prepare 실패 분석은 DEEP_REVIEW.md/PREPARE_FAILURE_REVIEW.md에 이력으로 보존한다.
