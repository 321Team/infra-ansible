# Runner(cicd-runner01)·Harbor(harbor01) `svc_ansible` 프로비저닝 (P1-HBR-01 #59)

## 배경

`playbooks/p1-hbr-01-discover.yml`(P1-HBR-01 설정값 자동 수집)을 ansible01에서
실행하기 위해 `runner_host=10.250.10.20`(cicd-runner01), `harbor_host=10.1.93.54`
(harbor01)를 대상으로 지정했으나, 두 호스트 모두 다른 6대(k8s_nodes)와 달리
`svc_ansible` 계정이 없어 접속이 실패했다. [edge01 사례](P1-SEC-01-edge01-svc_ansible-provisioning.md)와
같은 패턴이며, 계정 생성 이후에도 호스트별로 서로 다른 추가 장애가 있었다.

## 조치 (2026-09-28~29, ansible01에서 각 호스트의 기존 관리자 계정으로 수행)

### 1. 계정·키 생성 (두 호스트 공통)

cicd-runner01은 `server01_cicd-runner`(비밀번호 인증, keyboard-interactive),
harbor01은 `server08`(비밀번호 인증) 계정으로 접속해 동일하게 수행:

```bash
sudo useradd -m -d /home/svc_ansible -s /bin/bash svc_ansible
sudo mkdir -p /home/svc_ansible/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIM7tgJlin911gQLk591EuPfjOJUudgn/wmYx1HiGDXtG P1-ANS-01 svc_ansible' \
  | sudo tee /home/svc_ansible/.ssh/authorized_keys
sudo chown -R svc_ansible:svc_ansible /home/svc_ansible/.ssh
sudo chmod 700 /home/svc_ansible/.ssh
sudo chmod 600 /home/svc_ansible/.ssh/authorized_keys
```

결과: cicd-runner01 `uid=1002(svc_ansible) gid=1003`, harbor01
`uid=1002(svc_ansible) gid=1002`(다른 호스트의 `uid=1001`과 다름 — SSH 인증에는
영향 없음).

cicd-runner01의 `/home/svc_ansible`에는 `.bash_logout`(2024-10-29),
`.mozilla`(2026-08-24) 등 계정 생성 이전부터 남아있던 파일이 있었다(과거 다른
용도로 쓰이던 홈 디렉터리로 추정). `useradd -m`은 기존 파일을 지우지 않고
스켈레톤만 보충하므로 문제는 없었으나, SELinux 컨텍스트(`ls -Z`로 확인한
`ssh_home_t`)는 정상이었다.

### 2. cicd-runner01 전용 장애: `AllowGroups`

계정·키가 정상인데도 키 인증이 계속 거부돼 `journalctl -u sshd`로 확인한 결과:

```
User svc_ansible from ... not allowed because none of user's groups are listed in AllowGroups
```

`/etc/ssh/sshd_config.d/20-p1-security.conf`에 `AllowGroups linux-admins`가
설정돼 있었다(harbor01에는 이 제한이 없음). 해결:

```bash
sudo usermod -aG linux-admins svc_ansible
```

### 3. 두 호스트 공통 장애: `become`(sudo) 시 비밀번호 요구

`p1-hbr-01-discover.yml`의 Runner/harbor01 태스크는 `become: true`를 쓰는데,
k8s-control01의 `svc_ansible`과 달리 두 호스트엔 NOPASSWD sudo 권한이 없었다.
각 호스트에서 기존 관리자 계정으로 다음을 수행:

```bash
echo 'svc_ansible ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/90-svc_ansible
sudo chmod 440 /etc/sudoers.d/90-svc_ansible
sudo visudo -c
```

두 호스트 모두 `visudo -c` PASS 확인.

## 결과

`ansible-playbook -i inventory/hosts.yml -i "10.250.10.20,10.1.93.54," -e ansible_ssh_private_key_file=~/.ssh/p1_ansible_ed25519 -e runner_host=10.250.10.20 -e cp_host=k8s-control01 -e harbor_host=10.1.93.54 -e runner_runtime_user=server01_cicd-runner playbooks/p1-hbr-01-discover.yml`
실행 성공(`failed=0`). Harbor 인증서 IP SAN에 `10.1.93.54` 포함 확인
(`IP_SAN_MATCH=True`, AC-01), `hbr01-values.env` 생성 확인.

## 후속 조치 필요 (미완료)

- **키 제한 미적용**: [edge01 사례](P1-SEC-01-edge01-svc_ansible-provisioning.md)와
  동일하게, `playbooks/harden_svc_ansible_key.yml`은 `hosts: k8s_nodes`에만
  `from="10.250.10.10",restrict`를 적용한다. cicd-runner01·harbor01도 그 그룹
  밖이라 이번에 등록한 키 역시 **현재 제한 옵션 없이** 등록돼 있다. 다른
  비-k8s_nodes 호스트(edge01 포함)와 함께 일괄 하드닝하는 후속 작업이 필요하다.
- `inventory/hosts.yml`에 Runner/Harbor 그룹이 정식으로 없어 이번 실행은
  `-i "10.250.10.20,10.1.93.54,"` 인라인 인벤토리로 처리했다. 반복 실행이
  필요하면 정식 그룹 추가를 검토한다.
- cicd-runner01의 `AllowGroups linux-admins` 제한은 harbor01에는 없어 두
  호스트 간 sshd 정책이 일관되지 않다. 의도된 것인지 확인이 필요하다.
