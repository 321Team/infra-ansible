# 321Team infra-ansible

`infra-ansible`은 321Team 온프레미스 인프라의 반복 가능한 구성과 사전 검증을 관리하는 Ansible 소스 저장소입니다. 호스트별 자격증명, 로컬 실행 증적, 편집기 설정 및 생성 결과는 저장소에서 제외합니다.

## 현재 범위

- Kubernetes 노드 공통 사전 구성 및 검증
- 공통 OS 설정과 Kubernetes prerequisite 역할
- Inventory와 그룹 변수 관리
- SSH known-hosts 및 서비스 계정 authorized_keys 경로 관리
- Kubernetes API Load Balancer Stage A 연결 검증
- `CR-P1-ANS-01-01` Kubernetes 전체 Node DNS Resolver 전환
- `CR-P1-MON-01-01` Alertmanager egress용 Squid 프록시 서버 구성 (대상 노드 미정, `inventory/hosts.yml`의 `egress_proxy` 그룹에 확정 후 반영)

## 저장소 구조

| 경로 | 용도 |
|---|---|
| `ansible.cfg` | 저장소 공통 Ansible 설정 |
| `inventory/hosts.yml` | 관리 대상 호스트와 그룹 |
| `inventory/group_vars/all.yml` | 공통 변수, SSH 옵션 및 승인된 Resolver 목표값 |
| `playbooks/precheck.yml` | 구축 전 사전 점검 |
| `playbooks/site.yml` | 공통 구성 진입점 |
| `playbooks/harden_svc_ansible_key.yml` | 서비스 계정 authorized_keys 관리 |
| `playbooks/p1-lb-01-stage-a-nodes.yml` | API LB Stage A 노드 연결 검증 |
| `playbooks/cr-p1-ans-01-01-*.yml` | DNS Resolver 사전점검·Batch 적용·검증·Rollback |
| `playbooks/cr-p1-mon-01-01-*.yml` | Egress 프록시 사전점검·적용·검증·Rollback |
| `roles/common/` | 공통 운영체제 설정 |
| `roles/k8s_prereq/` | Kubernetes 사전 요구사항 설정 |
| `roles/dns_resolver/` | NetworkManager 기반 Resolver 상태·검증·자동 실패복구 |
| `roles/egress_proxy/` | Squid 기반 discord.com allowlist 프록시 구성·검증·Rollback |
| `scripts/cr-p1-ans-01-01-run.sh` | 승인 Gate와 Evidence 수집 실행기 |
| `scripts/cr-p1-mon-01-01-run.sh` | CR-P1-MON-01-01 승인 Gate와 Evidence 수집 실행기 |
| `docs/runbooks/CR-P1-ANS-01-01.md` | CR 실행 및 증적 Runbook |
| `docs/runbooks/CR-P1-MON-01-01.md` | CR-P1-MON-01-01 실행 및 증적 Runbook |

## 검증 기준 환경

- Ansible Core 2.16 계열
- 검증 기준 버전: `ansible-core 2.16.19`
- 제어 노드: `ansible01`
- 실행 계정: `server01_ansible`

## 로컬 인증 설정

Private Key 파일과 절대 경로는 저장소에 커밋하지 않습니다. 제어 노드에서 다음 로컬 환경 파일을 먼저 적용합니다.

```bash
source ~/.config/ansible/p1-ans-01.env
```

로컬 환경 파일은 저장소 외부에 보관하고 권한을 `600`으로 유지합니다. `ANSIBLE_PRIVATE_KEY_FILE`을 통해 키 경로를 제공합니다.

## 변경 전 검증

```bash
source ~/.config/ansible/p1-ans-01.env
ansible-config dump --only-changed
ansible-inventory -i inventory/hosts.yml --graph
ansible-playbook -i inventory/hosts.yml --syntax-check playbooks/precheck.yml
ansible-playbook -i inventory/hosts.yml --syntax-check playbooks/site.yml
ansible-playbook -i inventory/hosts.yml --check --diff playbooks/site.yml
```

`CR-P1-ANS-01-01`은 다음 Runbook을 먼저 검토합니다.

```bash
less docs/runbooks/CR-P1-ANS-01-01.md
```

Check Mode를 지원하지 않는 모듈은 별도 검토하며, 실제 적용은 승인된 변경 범위와 대상 호스트를 다시 확인한 뒤 수행합니다.

## 보안 및 제외 정책

다음 항목은 Git 추적 대상에서 제외합니다.

- `.vscode/`: 개인 편집기 설정
- `stage-a-output/`: 로컬 생성 결과
- `docs/evidence/`: 원본 실행 증적과 환경별 기록
- `*.retry`: Ansible 재시도 파일
- Private Key, Token, Password 및 로컬 환경 파일

`inventory/group_vars/all.yml`의 known-hosts 경로는 `%d/.ssh/known_hosts` 형식을 사용합니다. `/home/svc_ansible/.ssh/authorized_keys`는 관리 대상 서비스 계정의 authorized_keys 경로이며 Private Key 경로가 아닙니다.

## 변경 관리 절차

1. 티켓 번호를 포함한 작업 브랜치를 생성합니다.
2. 변경 전후에 Inventory, Syntax Check 및 Check Mode를 수행합니다.
3. 민감정보와 환경 종속 절대경로 포함 여부를 검사합니다.
4. `infra-reviewers` 검토 후 `infra-maintainers`가 병합합니다.
5. 직접 `main` 변경은 피하고 Pull Request 이력을 남깁니다.

## 팀 접근 모델

| 팀 | 저장소 역할 | 책임 |
|---|---|---|
| `infra-maintainers` | Maintain | 저장소 운영, 변경관리, 릴리스 및 접근권한 검토 |
| `infra-reviewers` | Triage | Issue, Pull Request, 보안 및 변경 영향 검토 |
| `infra-contributors` | Write | 승인된 자동화 구현과 Pull Request 제출 |

증적 원본은 저장소 외부의 통제된 경로에 보관하며, 저장소에는 검토 완료된 소스와 운영 문서만 반영합니다.
