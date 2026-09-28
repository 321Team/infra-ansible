# edge01 `svc_ansible` 계정 신설 (P1-SEC-01 #58)

## 배경

`inventory/hosts.yml`에 `edge01`(10.1.93.50, 물리 호스트 server08)을 새 `edge`
그룹으로 추가하면서(P1-SEC-01 #58), 정본 inventory의 전역 `ansible_user: svc_ansible`로
접속을 시도했으나 실패했다. 확인 결과 edge01에는 다른 6대(k8s-control01~03,
k8s-worker01~03)와 달리 `svc_ansible` 계정 자체가 존재하지 않았다.

## 조치 (2026-09-28, ansible01에서 `server08` 계정으로 직접 수행)

```bash
sudo useradd -m -d /home/svc_ansible -s /bin/bash svc_ansible
sudo mkdir -p /home/svc_ansible/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIM7tgJlin911gQLk591EuPfjOJUudgn/wmYx1HiGDXtG P1-ANS-01 svc_ansible' \
  | sudo tee /home/svc_ansible/.ssh/authorized_keys
sudo chown -R svc_ansible:svc_ansible /home/svc_ansible/.ssh
sudo chmod 700 /home/svc_ansible/.ssh
sudo chmod 600 /home/svc_ansible/.ssh/authorized_keys
```

결과: `uid=1003(svc_ansible) gid=1003(svc_ansible)` (다른 호스트의 `uid=1001`과
다름 — SSH 인증에는 영향 없음, uid 1001/1002가 edge01에서 이미 다른 계정에
할당돼 있어 시스템이 자동 배정한 값). 홈 디렉터리/셸은 다른 호스트와 동일하게
`/home/svc_ansible`, `/bin/bash`.

`ssh -v -i ~/.ssh/p1_ansible_ed25519 svc_ansible@10.1.93.50`로 키 인증 성공을
확인했고, 같은 키로 `ansible-playbook -i inventory/hosts.yml
playbooks/p1-sec-01-b2-collect-58.yml`을 실행해 `edge01 → k8s-worker01/02/03`
curl 위임 태스크가 3/3 PASS로 끝나는 것까지 확인했다.

## 후속 조치 필요 (미완료)

- **키 제한 미적용**: `playbooks/harden_svc_ansible_key.yml`은 `hosts: k8s_nodes`
  (control-plane/worker)에만 `from="10.250.10.10",restrict` 옵션을 적용한다.
  edge01은 `k8s_nodes` 그룹 밖이라 이 하드닝 대상에 포함되지 않고, 위에서
  추가한 `authorized_keys` 항목은 **현재 제한 옵션 없이 등록돼 있다**
  (`docs/runbooks/SSH-Key-Guard-Verification.md` 참고). ansible01
  (10.250.10.10) 외 출발지에서도 이 키로 edge01 접속이 가능한 상태이므로,
  다른 6대와 동일하게 `from="10.250.10.10",restrict`를 적용하는 후속 작업이
  필요하다 (`harden_svc_ansible_key.yml`의 `hosts:`에 `edge` 그룹을 추가하거나
  별도 태스크로 분리).
- 이 계정 신설 사실을 베이스라인 문서(VM/서비스 계정 목록)에도 반영할지는
  별도 결정 필요.
