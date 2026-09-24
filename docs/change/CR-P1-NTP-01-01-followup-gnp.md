# CR-P1-NTP-01-01 — Calico GNP 기준 후속 검증 (A안)

상태: **코드 리뷰 대상 / LOCAL·MOCK 시험만 수행 / 운영 실행 NOT RUN / 새 작업창 필요**.

## 배경과 결정

- 2026-09-22 Gate 2([fds-project-baseline#10](https://github.com/321Team/fds-project-baseline/issues/10))에서
  노드 보호 수단이 firewalld에서 Calico HostEndpoint(HEP) + GlobalNetworkPolicy(GNP)로 바뀌었다.
  수신 증적(`fds-project-evidence` 브랜치 `evidence/P1-K8S-01-gate2-readme-ntp-count`,
  `evidence/P1-K8S-01/gate2-final-20260922/`, **편입 PR 미병합**)에는 다음이 기록돼 있다.
  - 6대 firewalld가 `inactive`다.
  - HEP `fds-k8s-*`가 6개 있다.
  - GNP `fds-k8s-host-*`가 6개 있고 UDP/123 egress·ingress 규칙을 포함한다.
- 기존 후속 검증기(`tools/ntp-post-egress*.py`)와 PR #44 후보(9/21 커널 해시 계약)는
  firewalld direct의 `FDS_NTP_0101` 체인을 집행 수단으로 전제한다. 이 전제는 Gate 2 이후
  운영 구조와 맞지 않는다.
- **A안(2026-09-24 요청): NTP 집행 수단을 Calico GNP로 인정하고 후속 검증을 GNP 기준으로 재설계한다.**
  검증 전체는 ansible01에서 플레이북으로 제어한다. Lead 결정 기록의 링크는 결정 후 여기에 연결한다.

## 구성

| 파일 | 역할 |
|---|---|
| `playbooks/cr-p1-ntp-01-01-followup-gnp.yml` | ansible01에서 실행하는 전체 흐름. checkout·입력 바인딩 → 시작 검사 → (선택) 패킷 → 종료 재검사 |
| `roles/ntp_source/tasks/_followup_gate.yml` | 단일 게이트 실행, 결과 파일(receipt)의 controller 보존(실패 포함), 통과 여부 판정 |
| `library/fds_ntp_gnp_followup.py` | 노드 측 게이트: `contract`, `kernel`, `negative`, `sample` |
| `module_utils/fds_ntp_gnp_contract.py` | HEP/GNP/FelixConfiguration 선언적 UDP/123 계약 평가 |
| `module_utils/fds_ntp_hep_kernel.py` | Felix가 만든 ens160 HEP egress 체인의 구조 검사와 DROP 카운터 |
| `tests/ntp_source/test_gnp_followup.py` | LOCAL/MOCK 시험 |
| `tests/ntp_source/fixtures/calico_gate2_20260922.json` | Gate 2 수신 증적 HEP/GNP 원문. SHA-256과 출처 포함 |

양의 경로 검사에는 기존에 리뷰된 `fds_ntp_probe`의 `pathcheck` 게이트를 그대로 쓴다.
기존 onepass/post-egress 도구, 적용 엔진, journal은 변경하지 않는다.

## 판정 계층

1. **정책 계약** (`contract`, control01에서 `kubectl get`만 실행)
   - HEP: 노드마다 정확히 1개이고, `interfaceName: ens160`이며, `expectedIPs`에 인벤토리 IP가 있어야 한다.
   - egress UDP/123
     - 클라이언트 5대: `10.1.93.102/32`만 Allow
     - control01: 입력으로 받은 승인 upstream /32만 Allow
     - 그 밖의 목적지: 명시 Deny 또는 end-of-tier Deny로만 도달해야 한다.
   - ingress UDP/123 (control01): 클라이언트 5개 /32만 Allow
   - 정책 순서: `(order, name)` 순으로 평가하며, `order`가 없는 정책은 마지막에 평가한다.
   - 보수적 판정: 앞선 Deny에 가려진 넓은 Allow 규칙도 FAIL로 본다.
   - FelixConfiguration
     - `failsafe*HostPorts`에 UDP/123이 있으면 FAIL
     - 설정되지 않았으면 Calico 기본값으로 기록만 한다.
     - eBPF 또는 nftables dataplane이면 STOP
   - 모델링하지 않은 문법은 STOP(fail closed)한다: `has()` 등 selector 함수, `Pass`, `doNotTrack`,
     기본 외 tier, named port, `notNets`/selector 매치, preDNAT UDP/123 ingress.
     단, UDP를 매치할 수 없는 규칙(TCP 등)은 해석하지 않고 건너뛴다.
   - 기대값은 리뷰된 입력(토폴로지·승인 upstream)에서 온다. live 객체로 기준을 학습하지 않는다.
2. **커널 구조** (`kernel`, 각 노드에서 읽기 전용)
   - firewalld가 `inactive`여야 한다.
   - `iptables-save -c`에서 다음 경로가 있어야 한다:
     filter `OUTPUT` 첫 규칙 → `cali-OUTPUT` → `cali-to-host-endpoint` → `-o ens160` dispatch →
     `cali-th-*` 체인 정확히 1개 → 그 안의 DROP(end-of-tier)
   - raw 테이블 `cali-to-host-endpoint`에 ens160 규칙(untracked)이 있으면 STOP한다.
   - 규칙 의미는 해석하지 않는다. 의미 판정은 1번(정책 계약)과 3번(패킷 시험)이 맡는다.
3. **패킷 시험** (`cr_ntp_followup_packets=true`일 때만)
   - 양의 경로: 기존 `pathcheck`로 클라이언트 → CP1 응답을 확인한다. CP1은 승인 upstream 선택·ACL·listener를 확인한다.
   - 음성
     - 대상: 모든 노드는 TEST-NET `192.0.2.123`, 클라이언트는 추가로 승인 upstream(직접 공인 NTP 차단 확인).
     - 판정: `chronyd -Q` 응답이 없어야 한다. 또한 같은 길이의 idle 구간과 비교해
       HEP 체인 트리의 DROP 카운터가 `probe_delta ≥ idle_delta + 1`만큼 늘어야 한다.
       timeout만으로는 PASS하지 않는다.
   - 관측: 60초 간격으로 6회 `chronyc tracking/sources`를 수집한다.
     - 판정 기준: 승인 source 1개가 선택되고, Leap Normal이며, offset이 `cr_ntp_offset_max_ms`(100ms) 이내여야 한다.
4. **실행 중 drift**: 종료 시 계약과 커널을 다시 검사한다.
   - Calico 객체의 labels/spec digest가 시작 시점과 다르면 STOP한다.
   - 카운터를 제외한 HEP 체인 구조 digest가 시작 시점과 다르면 STOP한다.

## 실행 (ansible01)

전제:
- 리뷰·병합된 정확한 commit에 clean checkout 상태여야 한다.
- 기존 승인 계정(`svc_ansible`, 비대화형 sudo)을 사용한다.
- 새 작업창이 필요하다.

```bash
cd /home/server01_ansible/p1-ans-01 && git fetch origin && git checkout --detach <reviewed-commit>
cp docs/change/CR-P1-NTP-01-01-followup-gnp-input.example.json ~/ntp-followup-input.json
# run_id, source_head(=<reviewed-commit>), evidence_dir, packets, upstreams 기입
ansible-playbook playbooks/cr-p1-ntp-01-01-followup-gnp.yml -e @~/ntp-followup-input.json
```

- 1단계로 `packets=false`를 실행한다. 계약과 커널 구조만 확인하며, NTP 패킷은 0이다.
- 결과를 검토한 뒤 작업창 안에서 `packets=true`를 실행한다.
  샘플링에만 최소 5분이 걸리고, 음성 시험은 대상마다 idle 구간과 probe 구간이 추가로 걸린다.
- 결과는 `<evidence_dir>/<run_id>/`에 게이트·단계·호스트별 JSON으로 남는다. 실패 결과도 보존한다.
  이 디렉터리를 `fds-project-evidence` 절차로 편입한다.

정상 판정은 플레이북이 실패 없이 끝나고 모든 결과의 `gate_pass: true`인 것이다.
중단·복구:
- 각 게이트는 실패하면 즉시 멈춘다.
- 서버 변경이 없으므로 복구할 대상이 없다.
- 정책이나 커널이 바뀌었으면 원인을 확인한 뒤 새 `run_id`로 다시 실행한다.
  이미 쓴 run 디렉터리는 재사용하지 않는다.

## 리뷰 포인트와 한계

- **kubeconfig**: 기본값은 control01의 `/etc/kubernetes/admin.conf`(cluster-admin)이며 `get`만 호출한다.
  권장안은 3개 CRD에 get/list 권한만 가진 전용 read-only kubeconfig를 만들어
  `cr_ntp_followup_kubeconfig`로 지정하는 것이다.
- **커널 fixture는 합성본이다.** HEP 적용 이후의 `iptables-save -c` 원문은 아직 수집되지 않았다.
  Felix 체인 이름·dispatch 형태(`cali-th-*`, `-g`, `ens+`)는 새 읽기 전용 수집본으로 확인하고,
  확인 후 합성 fixture를 교체해야 한다.
  9/21 실제 원문(HEP 적용 전)으로는 `OUTPUT → cali-OUTPUT → cali-to-host-endpoint`까지 확인했다.
  cali-th 체인이 없는 상태에서는 STOP하는 것도 확인했다.
- **카운터 귀속의 한계**: 같은 시간대의 다른 차단 트래픽이 idle 구간보다 probe 구간에 몰리면 오귀속될 수 있다.
  응답 부재와 계약 PASS를 함께 요구하는 것으로 보완하지만, 단독 증명은 아니다.
- **적용 범위**
  - IPv4만 다룬다. IPv6, 비허용 ingress 실측, 장애·회복, 재부팅 지속성, 최종 AC 인수는 이 도구의 범위 밖이다.
    이 항목들은 [네트워크·복구 인수 계약](CR-P1-NTP-01-01-network-recovery.md)에 따라 별도로 수행한다.
  - Gate 2 이후 추가된 GNP(예: `nodeport-30080-allow`, TCP preDNAT)는 UDP/123과 무관해 PASS에 영향이 없다.
    Gate 2 증적 이후의 실제 객체는 새 실행에서 읽는다.
  - control01의 Cloudflare egress 규칙과 중복된 ingress 규칙은 v4 render 입력에 없는 수동 patch다
    ([infra-kubernetes PR #26](https://github.com/321Team/infra-kubernetes/pull/26)).
    이 도구는 규칙이 중복돼도 판정이 같다. 다만 그 규칙의 승인 여부는 판정하지 않는다.
