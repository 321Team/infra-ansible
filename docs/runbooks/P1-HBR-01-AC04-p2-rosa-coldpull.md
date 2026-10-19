# P1-HBR-01 AC04 — P2 ROSA cold-pull 출발지 임시 허용 (P2 overlay)

CLAUDE_ASSISTED. **소스 변경·전환 준비 문서**이며 실행 request, Runtime 완료, 변경 GO 또는
AC 인수가 아니다. 연결: [fds-project-baseline#13 요청 6258868341](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-6258868341),
[검토 6261120111](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-6261120111),
[infra-rosa#12 S1 확인 6258748604](https://github.com/321Team/infra-rosa/issues/12#issuecomment-6258748604).
병합해도 서버는 자동 변경되지 않는다. 기본값(overlay 미사용)의 렌더 결과는 현재 검토된 P1 guard와 바이트가 같다.

## 범위

| 구분 | 내용 |
|---|---|
| 추가 | `inet p1_hbr_ac04`에 interval set `p2_rosa_v4` = `10.20.10.0/24`(ROSA worker `private_a`) 1개, `forward_guard`의 P1 accept 다음·미승인 IPv4 drop 앞에 accept 1줄 |
| 범위 | 기존 규칙과 같음: `iifname "ens160"`, DNAT된 연결 중 원래 목적지 `10.1.93.54:443`/tcp만 |
| 유지 | P1 `approved_v4` 5개(`10.250.10.20`, `10.1.93.105/.107/.108`, 임시 관리 예외 `10.1.93.102`), 미승인 IPv4 drop, IPv6 drop, hook/priority -1, Docker·firewalld 소유 규칙 |
| 제외 | NAT EIP, VPC 전체 `10.20.0.0/16`, 포괄 허용, host INPUT/firewalld 한 줄 추가, Harbor→ROSA 신규 연결, Relay/VPN/AWS route·SG(fds-project-baseline#35·#37 소관), harbor01 호스트 반환 경로 |

- harbor01 호스트 반환 경로(`10.20.0.0/16 via 10.1.93.51`, runtime·NM 영구 아님)는 [S1 6074999671](https://github.com/321Team/fds-project-baseline/issues/37#issuecomment-6074999671) 3번대로 **fds-project-baseline#13 소관**이다. #37은 값과 시험 조건만 제공한다. route 명령 자체는 이 PR 범위 밖이며 창 B 카드와 #13 승인에서 다룬다.
- **단, 적용 시점은 guard와 묶는다.** Harbor host policy는 nft table 지문(`nft_sha256`)과 함께 host route 전체 지문(`routes_sha256`, `ip -j route show table all`)도 고정한다(infra-harbor-trivy `harbor_address_host.py` `HOST_ROUTE_CHANGED`). 그래서 manager 전환 밖에서 route만 넣거나 빼면 manager가 중단된다. P2 guard 줄과 반환 경로는 **같은 manager 전환 1회**(HOLD·정상 정지 → 봉인 → route·guard 변경 → 두 지문을 담은 새 입력·bundle/launch/Store → 복귀)에 함께 넣고, 회수도 같은 방식으로 함께 뺀다.

- accept는 **worker가 시작한 Harbor 443 연결**을 허용한다. 역방향(Harbor→ROSA) 신규 개시는 이 규칙으로 열리지 않는다. 최초 pull은 worker의 신규 TCP 연결이므로 established 전용으로 제한하지 않는다.
- 같은 chain에 두는 이유: nftables에서 다른 table·chain의 accept는 이 chain의 drop을 무효로 하지 않는다.
- P1 set과 분리하는 이유: 회수 시 P2 줄만 빠지고 P1 승인 출발지 목록은 그대로 남는다.

## 소스 구성

| 파일 | 내용 |
|---|---|
| `inventory/group_vars/hbr.yml` | `hbr_ac04_p2_sources: []` — 기본 비활성 |
| `inventory/overlays/hbr-p2-rosa-coldpull.yml` | 승인 창에서만 `-e`로 공급. `10.20.10.0/24`, `P2_TEMP_ROSA_COLDPULL`, `hard_expiry_kst: 2026-10-23T23:59:00+09:00` |
| `templates/p1-hbr-01-ac04.nft.j2` | overlay가 있을 때만 set·규칙 렌더 |
| `playbooks/tasks/p1-hbr-01-ac04-nft-verify.yml` | 기본은 기존과 같이 set 1·규칙 3. overlay가 있으면 set 2·규칙 4, P2 규칙 위치·set 내용·`flags interval` 정확 대조. overlay 범위가 `10.20.10.0/24` 1개를 넘으면 STOP. overlay 없이 live에 P2가 남아 있어도 STOP |
| `tools/p1-hbr-01-ac04-contract.py` | 기본 비활성·overlay 정확 값·P2 규칙 위치 정적 검사 |

렌더 결과(작성 PC, 저장소 시험과 같은 Jinja 설정):

| 입력 | 크기 | SHA256 |
|---|---|---|
| `group_vars/hbr.yml`만 | 1293 B | `6bef425bfb72e2f64e938c913028c29b2033b4c13633db27ac4e24e729aaa5b0` (현재 검토된 P1 guard와 같음) |
| + `overlays/hbr-p2-rosa-coldpull.yml` | 1735 B | `ced77208d60412c4b50ce78f5cb17a57c9b8d2df6c8bdc2d3c9c264a1203d08a` |

```bash
ansible localhost -c local -m ansible.builtin.template \
  -a "src=templates/p1-hbr-01-ac04.nft.j2 dest=$TMP/p1-hbr-ac04-p2.nft mode=0600" \
  -e @inventory/group_vars/hbr.yml -e @inventory/overlays/hbr-p2-rosa-coldpull.yml
```

`nft -c -f`는 작성 PC에서 실행하지 못했다(nftables 없음). 실제 nftables 1.1.5의 list 형식은 기존 fixture의 P1 규칙과 같은 표현식으로 예상했을 뿐 캡처하지 않았다. 아래 적용 1단계의 읽기 범위 `nft -c`와 5단계 live 대조가 실제 확인이며, 다르면 STOP한다.

## 적용 — 아직 실행 명령이 아님

fds-project-baseline#13의 별도 Runtime 승인과 작업창 배정 뒤에만 한다. 경로는 [`.50` 회수](P1-HBR-01-AC04-edge-retirement.md)와 같은 manager 결합 전환이며, 관리자 코드 변경은 없다(Harbor host policy는 전용 table의 정규화 지문만 고정하므로 새 지문은 새 입력으로 공급).

1. 현행 정상·비중첩 확인. 실제 guard source가 `6bef425b…` bytes이고 live `approved_v4` 5개·규칙 3개인지 대조한다. 다르면(그 사이 다른 승인 변경 포함) STOP하고 원본 보존. 읽기 범위에서 overlay candidate(`ced77208…`)를 `nft -c -f`로 검증한다.
2. ~6. edge-retirement 문서 2~6단계와 같다(HOLD·정상 정지 → 옛 Store 봉인 → 새 입력·Store 준비 → source 원자 교체·전용 table 단일 transaction 교체 → live 검증(이 문서 기준 set 2·규칙 4) → 새 bundle/launch·정책 절차·관리자 복귀). guard stop/restart, Docker restart, firewalld reload, flush ruleset, generic 443 개방은 없다.
7. P1 회귀: 기존 승인 출발지(Runner·Worker 1곳 이상)의 CA 검증 443과 allow 카운터, 미승인 출발지 deny 카운터. P2 경로 자체의 도달·pull은 cold-pull(infra-rosa#12)에서 별도로 본다.

전체 소요 상한(manager HOLD·복귀 포함)과 중단 조건은 실행 request에서 확정한다. P1 회귀 실패나 manager 복귀 실패 시 중단하고 기존 경로로 복구한다.

## 회수

- **렌더 기준:** overlay 없이 다시 렌더하면 `6bef425b…`가 나온다. 적용 이후 다른 승인 변경이 guard에 들어갔다면 옛 전체 guard로 덮어쓰지 않는다. STOP하고 대조한 뒤, 그 시점 source에서 P2 set·규칙만 뺀 candidate를 만든다.
- **순서:** P2 Robot 비활성화·삭제 → 목록·인증 거부 확인 → guard에서 P2 set·규칙 제거(같은 관리 경로) → live readback(set 1·규칙 3, `p2_rosa_v4` 부재) → ROSA P2 pull Secret 삭제 기록. 기존 P1 Robot(Worker23·Push ID3·구 ID2)과 `.102` 예외는 대상이 아니다.
- **기간:** cold-pull 창 B 당일 준비 구간에 적용한다. 검증·결함 재시험·반출·재해시·내용 검토가 끝나면 회수한다. **`2026-10-23 23:59 KST`는 독립 상한**이며 ROSA 삭제가 늦어져도 자동 연장하지 않는다. 계속 필요하면 만료 전에 남은 목적·기간만 다시 판단한다. Robot 만료는 인증 제한일 뿐 Robot 삭제·guard 제거를 대신하지 않는다.

## 자격증명 (P2 Robot)

- Harbor project Robot의 실제 로그인 이름은 prefix + project + account 형식이다([Harbor 문서](https://goharbor.io/docs/2.14.0/working-with-projects/project-configuration/create-robot-accounts/)). 이름을 미리 정하지 않고, 발급 화면의 이름·ID·project scope를 읽어 기록한다.
- 권한은 `fds` project의 pull이다. 승인 digest 2개로 기술적으로 제한된 권한이 아니다. 승인 이미지 2개만 쓰는 것은 cold-pull 절차의 범위다.
- Pod/SA의 `imagePullSecrets`에는 Secret **이름**만 들어간다. `kubernetes.io/dockerconfigjson` Secret에는 인증 가능한 credential이 저장된다. 원문은 GitHub·공유 원본·증적·로그·shell history·명령 argv에 넣지 않는다. 승인된 보호 입력으로 P2 Secret 하나에만 공급한다. 증적에는 Secret 이름·UID·권한·만료 등 비밀이 아닌 인벤토리만 남긴다.

## 검증과 완료 경계

로컬: `tests/test_p1_hbr_ac04_p2_overlay.py`(렌더 SHA·delta, verifier 판정식 평가: 정상 P1·정상 P2·회수 잔존·overlay만 있고 live 없음·drop 뒤 배치·다른 subnet·범위 확대), `tests/test_p1_hbr_ac04_contract.py`(overlay 확대·만료 연장·기본 활성 거부). verifier 평가는 Jinja로 판정식을 계산한 것이며 Ansible 실행이 아니다. CI는 exact HEAD의 Linux regression을 별도로 연결한다. queued/skipped는 PASS가 아니다. 리뷰·병합·Runtime 적용·회수·traffic 증적·AC는 별도다.
