# AC04 Docker 체인 순서 차이 — 읽기 원본의 오프라인 분석 준비

CODEX_ASSISTED. infra-ansible#62 지원, baseline#13의 6032702451/6032930550/6032992856을 근거로 한다.
이 도구는 원본과 fresh 관측의 Docker 체인 5개를 별도로 대조한다. 기존 verifier/iptables/nft/봉인 원본/AC/승인 경계를 변경하지 않는다. SSH·sudo·subprocess·설치·토큰·서버 쓰기는 없다.

## 현재 판정과 지원 범위

16:16:37 현장 보고에서 DOCKER-FORWARD 마지막 ACCEPT2줄 외에 DOCKER filter 마지막 DROP2줄의 교환이 추가로 발견됐다. 기존 A′ 승인6032930550은 DROP 교환을 허용하지 않으므로 **현재 NO-GO 유지**다. 이 준비 코드를 실행해도 새 승인이나 영구 정규화가 되지 않는다.
도구는 6줄의 고정 체인에서 마지막 정확한 두 literal 규칙의 자리 교환만 후보로 분류한다. 전체 chain sort/set는 하지 않는다. 앞4줄의 순서/내용, 추가·삭제·중복·인터페이스/target/option 변화, FORWARD/DOCKER-USER/NAT drift는 범위 밖이다.
DOCKER-FORWARD 접두는 선언+DOCKER-CT/INTERNAL/BRIDGE의 정확한4줄, DOCKER filter 접두는 선언+동일 순서의 ACCEPT3줄이다. 인터페이스는 이번 보고의 docker0와 br-835092bfcbbc로 고정하므로 다른 호스트/bridge에 보편적으로 적용하지 않는다.
동등성은 input/output 인터페이스 조건과 최종 target에 대한 정적 검토 후보다. Netfilter 공식 HOWTO §7.3을 참조한다. 부팅이 순서 변화 원인이라는 추정이나 실제 Runtime 동작을 이 코드로 입증하지 않는다.

## 입력·실행·증적

실행 위치는 기존 ansible01 로그인 또는 원본을 받은 검토 PC이며 Python3 표준 라이브러리만 필요하다. root/sudo로 분석할 필요가 없다.
원본은 기존 harbor01 /var/lib/fds-change/P1-HBR-01-AC04/original-state.json의 실제 수신 바이트다. 기존 PRESTATE_SHA256SUMS 5개 검증(rc0)과 원본 hash는 별도 원본 증적에 남긴다. 현장 보고의 원본 SHA는1090de081eb5969f2fc5e1d890f6f022494cf652356a6b8d541be70d6b62d83f이며 도구는 입력값과 실제 바이트를 대조할 뿐 보고 hash의 독립 진위를 인증하지 않는다.
current-state.json은 fresh 읽기 결과의 forward_rules/docker_user_rules/docker_forward_rules/docker_filter_rules/docker_nat_rules 5개 문자열 배열을 그대로 담는다. 각 배열은 승인 observe source의 다음 명령 stdout_lines와 일치해야 한다:

```bash
iptables -w 5 -t filter -S FORWARD
iptables -w 5 -t filter -S DOCKER-USER
iptables -w 5 -t filter -S DOCKER-FORWARD
iptables -w 5 -t filter -S DOCKER
iptables -w 5 -t nat -S DOCKER
```

이 명령은 harbor01의 기존 svc_ansible/become 읽기 범위에서만 사용한다. 명령별 실제 argv/rc/stdout/stderr/시각/host·source SHA를 보존하고 rc가 실패하면 분석 입력으로 성공 배열을 합성하지 않는다. 민감한 원본 전달은 기존 승인 경로를 사용한다. 이 준비에는 새 현장 수집이나 전달 성공 증적이 없다.
원본이 이미 있으면 재수집하지 않는다. 신규 빈 디렉터리에 결과를 저장하고 기존 파일을 덮어쓰지 않는다.

```bash
python3 -I -B tools/p1-hbr-ac04-docker-chain-analysis.py \
  --original-state '<수신한_original-state.json>' \
  --original-sha256 1090de081eb5969f2fc5e1d890f6f022494cf652356a6b8d541be70d6b62d83f \
  --current-state '<fresh_current-state.json>' > '<신규_경로>/analysis.json'
rc=$?
printf '%s\n' "$rc" > '<신규_경로>/analysis.rc'
sha256sum '<신규_경로>/analysis.json' '<신규_경로>/analysis.rc'
```

## 결과·중단·다음 단계

- RC0/EXACT_DOCKER_CHAINS_ONLY: 이5체인만 원본과 정확히 일치. full verifier·신선도·guard/TLS·Runtime·AC PASS가 아니다.
- RC2/FIXED_TAIL_SWAP_REVIEW_REQUIRED: 정확한 마지막 pair 교환 후보만 있다. 현행 exact 비교 미충족이며 NO-GO를 유지한다. 새로운 승인/영구 변경은 별도 검토 대상이다.
- RC2/UNSUPPORTED_DRIFT 또는 INCOMPLETE: 범위 밖 차이/형식·읽기·hash 실패. 원본을 보존하고 중단한다.
- 모든 출력에서 full_verifier_pass/runtime_go/ac04_accepted/runtime_changed=false. 원문 규칙이나 입력의 기타 필드/비밀을 출력하지 않는다.

원래17:00 T0 상한, 당일1회/30분, APP 종료+10분/비중첩, 공지, S3 fresh .20 TLS200, S4 .26 source/deny/counter, guard 계약과 복구/원복 경계는 유지한다. 분석 도구는 이 조건을 검증하지 않는다.
영구 verifier 수정은 별도 코드 PR에서 필요성·좁은 허용 범위·독립 리뷰·필수 Linux CI를 충족한 뒤 판단한다. PR66 필수 CI가 queued인 동안 이 준비는 source branch에만 보관해 새 regression queue를 만들지 않는다.
복구: 운영 변경이 없다. 후보 source는 필요 시 검토된 revert로 회수하며 원본 상태/규칙을 재정렬·재봉인하지 않는다.

## 근거

- https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-6032992856
- https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-6032930550
- https://github.com/321Team/infra-ansible/blob/61a77ad2f984cbf9e74a95f779691e2831a5a2a6/playbooks/p1-hbr-01-ac04-verify.yml
- https://www.netfilter.org/documentation/HOWTO/packet-filtering-HOWTO-7.html
