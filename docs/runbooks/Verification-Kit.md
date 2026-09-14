# Issue #8 검증 배포 키트

지원 대상은 Linux x86_64, glibc 2.28 이상, CPython 3.12다. 새 가상환경을 만들려면
Python의 venv/ensurepip와 Git이 미리 설치돼 있어야 한다. OS 패키지·시스템 Python·
시스템 Ansible은 이 도구가 설치하거나 교체하지 않는다. Windows에서는 수집·패키지 생성·
압축 검증이 가능하며 실제 Ansible 실행은 Linux에서 한다.

기본 실행은 localhost fixture 시험뿐이다. 실제 노드 inventory, 운영 SSH 키나 known_hosts,
외부 가상환경 경로를 받는 옵션은 없다. Git 소스에 기존 playbook이 포함돼 있어도 apply를
실행하지 않는다. #7의 실제 6대 읽기 결과와 이 키트의 새 환경 fixture 결과는 별도 증적이다.

## 고정되는 것

- 선택한 전체 40자리 commit, tree, Git blob·파일 mode·원본 SHA256 목록.
- 지정 commit의 파일 전체를 `source/`에 저장한다. 과거 '28개'라는 숫자에 의존하지 않고
  SOURCE_MANIFEST.json의 실제 목록·개수를 검사한다. #7 병합본은 44개이며 키트 변경 파일이 추가된다.
- 두 엔진 2.16.19 / 2.21.3의 기존 9개 의존성 버전 및 설치기 pip 25.2.
- `tools/verification-wheels.lock.json`: PyPI 버전별 metadata URL, 정확한 Linux wheel 이름·크기·SHA256·다운로드 URL.
- `requirements-<engine>.lock` / `installer.lock`: `--require-hashes` 설치용 고정 요구사항.
- SOURCE.pack: 해당 commit와 해당 tree/blob만 포함. 부모 commit·이력·원격 URL·Git 설정·hooks·자격증명은 복사하지 않는다.
- 내부 SHA256SUMS와 외부 압축 SHA256. 검증기는 별도 verify-kit.py와 sidecar로 제공한다.

SHA256은 받은 파일의 일치 여부를 검사한다. 리뷰어가 확인한 commit·압축 해시·검증기 해시를
독립 전달 기록과 대조한다. 같은 전송 폴더 안의 sidecar만 신뢰 출처로 삼지 않는다.
모든 byte가 같아도 실행 결과나 담당자의 승인을 대신하지 않는다.

## 1. 네트워크가 가능한 준비 환경

승인/시험 대상 commit을 checkout한 깨끗한 저장소에서 실행한다. 아래 값은 실제 PR/인계의
40자리 SHA와 기존 checkout 절대 경로로 바꾼다. 새 파일은 checkout 밖에 생성한다.

```bash
set -euo pipefail
REPO=/absolute/infra-ansible
COMMIT=<검토할-40자리-commit>
ROOT=$(mktemp -d /tmp/issue-8-kit-XXXXXXXX)
python3.12 -I "$REPO/tools/verification-kit.py" collect \
  --repo "$REPO" --commit "$COMMIT" --output "$ROOT/wheels"
python3.12 -I "$REPO/tools/verification-kit.py" build \
  --repo "$REPO" --commit "$COMMIT" --wheels "$ROOT/wheels" --output "$ROOT/distribution"
```

`collect`만 인터넷에 접근한다. 고정된 files.pythonhosted.org URL에서 받은 wheel의 해시가
lock과 다르면 실패한다. 임의 최신 버전을 해석하거나 sdist를 실행·빌드하지 않는다.
실패 폴더를 수정해서 재사용하지 말고 새 ROOT에서 다시 시작한다.

build는 현재 실행 중인 생성기와 commit 안의 생성기가 같은지도 확인한다. 수정 중인
checkout으로 정식 키트를 만들 수 없다. 출력된 commit·원본 개수·archive SHA256을 기록한다.
같은 commit·wheel·Python/Git/zlib 도구 환경의 반복 빌드는 같은 압축 바이트를 생성한다.
다른 Git/zlib 버전 간 동일 압축 해시는 보장하지 않는다. 각 산출물의 해시를 새로 기록하고
source manifest/원본 파일 일치로 재현성을 비교한다.

## 2. 반입과 독립 검증

`distribution/`의 tar.gz, .sha256, verify-kit.py, verify-kit.py.sha256을 원래 바이트 그대로
폐쇄망에 복사한다. 원본 압축본을 재압축하지 않는다. wheel 폴더를 별도로 반입할 필요는 없다.
압축 파일에는 내부 주소가 있는 소스 inventory가 포함되므로 기존 팀 접근 범위에서 보관한다.

```bash
cd /absolute/received-distribution
sha256sum -c verify-kit.py.sha256
sha256sum -c verification-kit-<commit>.tar.gz.sha256
# HASH는 독립 인계 기록과 대조한 실제 archive SHA256이다.
HASH=<확인한-64자리-SHA256>
ARCHIVE=/absolute/received-distribution/verification-kit-<commit>.tar.gz
python3.12 -I verify-kit.py verify --archive "$ARCHIVE" --sha256 "$HASH"
```

외부 해시 확인 후 내부 Manifest·파일 목록·크기·mode·Git blob·wheel lock을 검사한다.
절대/상위 경로·링크·장치·중복·대소문자 충돌·미등록 파일·credential 이름과 일반적인
비밀키/token 형식을 거부한다. 형식 검사는 모든 종류의 비밀정보 부재를 증명하지 않으므로
선택 commit의 diff를 별도로 검토한다. 로컬의 미추적 파일은 패키지에 들어가지 않는다.

추출된 텍스트를 별도 확인하려면 새 경로를 지정한다. 원본 파일은 이동하지 않는다.

```bash
INSPECT=/absolute/new-inspection-directory
python3.12 -I verify-kit.py verify --archive "$ARCHIVE" --sha256 "$HASH" --output "$INSPECT"
(cd "$INSPECT" && sha256sum -c SHA256SUMS)
```

## 3. 빈 디렉터리에 오프라인 환경 생성

`prepare`는 검증 후 새 runtime 아래에 두 개의 venv를 만든다. 호스트 설정을 수정하지 않는다.
초기 venv의 ensurepip는 로컬 Python에 포함된 것을 사용한 뒤 동봉한 pip 25.2로 고정한다.
패키지 설치에는 `--no-index --only-binary=:all: --require-hashes`를 사용하고 pip check를 실행한다.
부모 환경의 pip 설정·proxy index·Ansible 변수·Python import 경로·SSH agent는 전달하지 않는다.

```bash
RUNTIME=/absolute/new-issue-8-runtime
python3.12 -I verify-kit.py prepare --archive "$ARCHIVE" --sha256 "$HASH" --output "$RUNTIME"
```

runtime/repo에는 source-only pack으로 동일 commit의 shallow Git 메타데이터를 복구한다.
Git tree/blob와 텍스트 일치를 대조하고 기존 #7의 clean-source 계약을 유지한다. 원래 저장소의
Git 설정·remote·hooks는 복사하지 않는다. source/ 원본은 수정하지 않는다.
실패하면 로그를 보존한다. 해당 runtime을 덮어쓰거나 부분 성공으로 판정하지 않는다.

## 4. 새 환경 fixture 시험

```bash
RESULTS=/absolute/new-issue-8-results
python3.12 -I verify-kit.py run --runtime "$RUNTIME" --sha256 "$HASH" --output "$RESULTS"
```

실행 순서는 단위시험 → #6 공개 CLI/결함 재주입 → #7 callback/음성시험 → 두 엔진 DNS
정규화 fixture다. rc/완료/실행 commit과 원본 해시를 연결한다. 기존 운영 inventory나
verify-ssh-main.py를 실행하지 않는다. 새 venv의 고정 패키지는 #7 matrix에서 다시 검사한다.

성공 조건은 exit 0 및 KIT_RUN.json의 `PASS_FRESH_OFFLINE_FIXTURES`다. 설치 로그와
단계별 명령·stdout/stderr·exit code 및 내부 SHA256SUMS를 함께 보존한다. 어느 단계든
실패하면 FAIL로 기록하고 후속 단계를 중단한다. 설치 단계 자체의 실패도 install-* 로그로
보존하며 RUNTIME.json의 PREPARED가 없으면 실행할 수 없다.

같은 RESULTS로 두 번 실행하면 기존 결과를 덮어쓰지 않고 즉시 실패한다. 새 실행에는
다른 결과 경로를 사용한다. 실패 원본을 지우거나 성공 원본으로 바꾸지 않는다.

## 증적 제출과 종결

실행자가 `KIT_RUN.json`, 전체 결과 폴더, 내부 Manifest, distribution 압축 해시 및
runtime 설치 로그를 제출한다. 콘솔 붙여넣기는 파일 원본과 구분한다. 보관용 tar와
sidecar는 새 이름으로 만들고 원본 결과 폴더를 유지한다. 키트 압축본은 그대로 보관한다.

```bash
PARENT=$(dirname "$RESULTS")
NAME=$(basename "$RESULTS")
test ! -e "$PARENT/issue-8-evidence.tar.gz"
tar -C "$PARENT" -czf "$PARENT/issue-8-evidence.tar.gz" "$NAME"
(cd "$PARENT" && sha256sum issue-8-evidence.tar.gz > issue-8-evidence.tar.gz.sha256)
```

#7은 [코드 PR #15](https://github.com/321Team/infra-ansible/pull/15)와
[증적 PR #11](https://github.com/321Team/fds-project-evidence/pull/11)의 독립 승인·병합으로
Done이다. Structured-SSH-Verification.md의 실행 전 대기 문구는 당시 이력이며 이번 키트의
새 환경 결과를 뜻하지 않는다. #8 새 환경 시험·무결성 대조·독립 리뷰·키트 PR 병합을 확인한
뒤 종결한다. #5 CI와 #9 운영 전환, 기존 서버 main 반영 및 별도 Runtime Gate는 별도다.

설치/배포 계약 참고: [pip 해시 고정 설치](https://pip.pypa.io/en/stable/topics/secure-installs/),
[Git object pack](https://git-scm.com/docs/git-pack-objects).
