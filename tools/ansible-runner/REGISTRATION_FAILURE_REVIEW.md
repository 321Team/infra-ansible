# 코드 수정 전 딥리뷰 — Runner v1.1 등록 검사 실패

## 실서버 사실

2026-09-16 15:55:40–15:56:05 UTC, cicd-runner01 registration-check는 FAIL이다. 원본 6093 bytes의 SHA256은 `5cf140fc17fb452c2c681502aa61e2eede0cc6992bdb13c55269c42c06c2351a`. 외부 sidecar, 외부17파일/내부10파일 manifest·집합·중첩 원본 checksum과 HOST 결과 복제 바이트가 모두 일치한다. bundle/image는 검증된 v1.1 준비본과 같다.

configure_rc=0, remove_rc=0, 컨테이너 rc=1/OOM=false, 정리 runner/proxy/workspace=REMOVED. 선별 결과에는 runner identity가 없다. 전용 계정/비sudo와 격리14개는 PASS, Actions NOT_RUN. 회복 제거 성공만으로 원래 FAIL을 PASS로 바꾸지 않는다.

## 차단 결함과 근거

1. P1: `json.loads((RUNNER / '.runner').read_text())`는 UTF-8 BOM이 있는 정상 Runner 설정 파일을 거절한다. 공식 v2.337.0 `ConfigurationStore.SaveSettings`는 `IOUtil.SaveObject`를 호출하고, 이는 `File.WriteAllText(path, StringUtil.ConvertToJson(obj), Encoding.UTF8)`을 사용한다. Python 문자열 JSON 파서는 초기 BOM을 자동 제거하지 않는다. 이 호환성 결함은 로컬 BOM fixture로 재현할 수 있다.
2. P2: `clean_result`가 error_type과 실패 단계를 버려 진단에 필요한 고정 필드도 남지 않는다. .runner 원문/private log는 정리되어 실서버의 실제 예외와 BOM 바이트 자체를 소급 확인할 수 없다. 따라서 이 실행의 직접 예외가 JSONDecodeError였다는 단정은 금지한다. 관찰 패턴과 코드 경로는 BOM 실패와 일치한다.
3. 테스트가 이미 정규화된 identity dict를 주입하므로 .NET 파일 → JSON 파서 → 일치 검사 → 제거 → 선별 증적 경계를 검증하지 못했다.

## 수정 설계

- .runner를 symlink/하드링크/크기 제한이 적용되는 bounded regular read로 읽고 `utf-8-sig`로 엄격하게 decode한다. BOM 없는 UTF-8도 지원한다. 다른 문자 인코딩/깨진 JSON은 실패로 둔다.
- 저장소 URL·새 고유 이름·양의 정수 ID 일치를 그대로 요구한다. 잘못된 identity를 예상값으로 대체하지 않는다. 원문 값/추가 임의 필드는 수집하지 않는다.
- 고정 실패 단계, 허용된 예외 분류, BOM 존재/파싱 성공/identity 비교 boolean만 선별 보존한다. private log·토큰·설정 원문은 계속 제외한다.
- 등록 실패 시 회복 제거와 전체 FAIL 유지, 기존 컨테이너 정리 동작을 보존한다.
- 파일 기반 BOM/무BOM 성공, 깨진 JSON/URL·이름·ID 오류 거절, main 전체 모형에서 등록→파싱→제거 및 실패 회복, 임의 필드/문자열 유출 차단을 검사한다. 실제 Podman/등록 성공으로 표기하지 않는다.
- container.py가 이미지에 포함되므로 v1.2는 새 prepare가 필요하다. 기존 PREPARED.json의 manifest나 이미지 결합을 우회하지 않는다. 새 prepare PASS 후 새 단기 토큰으로 재검증한다.
- 현재 GitHub 등록 잔존 여부는 관리 API에서 정확한 `ansible-ci-e64364fe3bab45fabcc43aea675c9693` 이름으로 별도 확인해야 한다. 제거 rc0는 API 목록 부재의 대체 증거가 아니다.

## 공식 근거

- https://github.com/actions/runner/blob/v2.337.0/src/Runner.Common/ConfigurationStore.cs
- https://github.com/actions/runner/blob/v2.337.0/src/Runner.Sdk/Util/IOUtil.cs
- https://learn.microsoft.com/en-us/dotnet/api/system.text.encoding.utf8?view=net-8.0
- https://docs.python.org/3/library/json.html#character-encodings
- https://docs.python.org/3/library/codecs.html#encodings.utf_8_sig

이 문서는 수정 전 자체 검토이며 독립 승인/서버 재검증/병합을 뜻하지 않는다.
