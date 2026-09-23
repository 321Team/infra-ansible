# 리뷰·병합과 Lead 판단

적용 기준: 2026-09-18 KST [병합된 중앙 리뷰 권한 정책](https://github.com/321Team/fds-project-baseline/blob/b2e4612cf2e417b10e7f145c5b1e5f58dbe1b948/governance/REVIEW_AUTHORITY_POLICY.md). 사람 간 승인 절차를 정렬하며 요구사항·AC·업무 담당·보안 통제를 바꾸지 않는다. 과거 실행·승인·불변 소스 기록은 작성 당시 이력으로 보존한다.

## 변경 분류

| 변경 | 검토와 병합 |
|---|---|
| 코드·실행 설정·혼합 PR | 작성자 외 적격 검토자 최소 1인의 정확한 HEAD 독립 리뷰 후 Lead가 병합 판단 |
| 사전 검증(Pre-check) 코드 | 별도 코드 리뷰 없이 담당 Lead가 즉시 병합 가능. 운영 서버 Runtime 적용 전 해당 SHA 독립 리뷰 필수 (아래 Pre-check 절) |
| 이 저장소의 문서·증적만 변경 | 책임 Lead의 검토·병합 판단. 작성자와 Lead가 같아도 자기 GitHub APPROVE는 요구하지 않음 |
| fds-project-evidence의 모든 PR | 코드 포함 여부와 무관하게 독립 리뷰 유지. 이 저장소 문서 절차를 적용해 생략하지 않음 |

코드에는 앱·테스트·스크립트·IaC/Ansible·manifest·Workflow·의존성·인증서 profile·실행 시 소비되는 정책/설정이 포함된다. 제목이나 확장자 대신 실제 diff와 사용처로 판단한다. 실행 결과와 당시 사용 소스의 보존 사본은 새 실행 코드 변경과 구분한다. 기록 경로를 새 실행 입력으로 소비하도록 바꾸면 코드 변경이다.

## 사전 검증(Pre-check) 코드 예외 — 2026-09-23

적용 기준: 프로젝트 중간 결과 회고에 따른 2026-09-23 KST 사용자 정책 변경 안내. 상세 기준은 [중앙 리뷰 권한 정책 §3.2](https://github.com/321Team/fds-project-baseline/blob/ea2488b33a870d35c16bd303af568c5fe48c2e44/governance/REVIEW_AUTHORITY_POLICY.md)([PR #93](https://github.com/321Team/fds-project-baseline/pull/93))를 따른다. 중앙 PR 병합 전까지 이 절은 제안 상태다.

| 단계 | 검토와 병합 |
|---|---|
| Pre-check 코드 병합 | 사전 검증 단계의 점검·수집·판정용 스크립트·검증기와 그 시험 코드는 별도 코드 리뷰 없이 책임 티켓의 담당 Lead 권한으로 즉시 병합할 수 있다. |
| 운영(Production) 서버 Runtime 적용 | 운영 서버에서 실행·설치·배포·영구 반영하거나 운영 배포 경로에 편입하는 시점부터 코드 리뷰가 필수다. 읽기 전용 실행도 포함한다. |

- **Pre-check 병합 기록.**
  - PR은 계속 사용한다. main 직접 push·force push·자동 병합은 금지다.
  - PR에 `Pre-check` 분류, 책임 티켓, 병합 SHA, 담당 Lead, KST 시각을 남긴다.
  - 리뷰 상태는 `REVIEW=NOT PERFORMED (Pre-check)`로 표기한다. 이 병합을 리뷰 완료, Runtime PASS, AC 인수로 표시하지 않는다.
- **운영 적용 전 절차.**
  - 적용할 SHA를 고정한다.
  - 직전 독립 리뷰 SHA 이후 전체 diff를 작성자 외 적격 검토자가 리뷰한다. 리뷰 이력이 없으면 적용 대상 코드 전체가 범위다.
  - Lead는 리뷰 완료 SHA와 적용 SHA의 일치를 실행 기록에 남긴다.
  - 리뷰 후 수정 PR은 일반 코드 PR 절차를 따른다.
- **대상 외(기존 독립 리뷰 유지).**
  - Pre-check 코드와 운영 Runtime 코드·manifest·IaC·배포 설정이 섞인 혼합 PR
  - 병합·Release 게이트 CI workflow
  - 시크릿·무결성 등 보안 통제 코드
  - fds-project-evidence의 모든 PR
- **유지 통제.** 비밀정보 커밋 금지, 필수 AC·시험·보안 기준, 운영 적용 시 선행조건·중단·복구 기준은 완화하지 않는다.

## PR와 확인

1. 작업 브랜치에서 PR을 만들고 관련 티켓/AC, 변경·영향·복구, 전체 HEAD SHA, 검증 결과와 제한을 기록한다. main 직접 push·force push·자동 병합을 하지 않는다.
2. 코드/혼합 PR은 작성자가 아닌 기존 역할 범위의 적격 검토자가 검토한다. Reviewer 지정, 기술 의견, 실제 GitHub APPROVED를 구분한다. AI 자체 점검이나 작성자의 자체 검토는 독립 승인이 아니다.
3. 새 commit의 변경 부분과 영향 범위만 재검토한다. 병합 담당자는 최종 HEAD, 필요한 독립 검토 근거, 해당 단계 필수 검사와 미해결 차단사항을 확인하여 수동 병합한다. 여러 단계 판단은 한 PR/티켓 기록에 함께 남길 수 있다.
4. 역할은 책임 티켓의 기존 Lead·Support 및 저장소 병합 담당을 유지한다. 이 문서는 GitHub 계정·팀·서버 권한이나 branch protection/ruleset을 변경하지 않는다.

## 실행·인수·종결

해당 책임 Lead가 문서·계획, 운영 실행·배포·영구 반영·복구, 결과 수용·AC 인수·티켓 종결을 판단한다. 본인이 수행한 업무도 필수 AC와 실제 증적으로 인수할 수 있다. 동일 코드의 각 단계에서 Support/독립 Reviewer의 반복 승인을 일률적 필수 조건으로 두지 않는다. 새 코드/실행 설정 변경은 다시 코드 PR 절차를 따른다.

운영 실행은 검토·병합된 SHA/Digest, 대상·계정·작업 경로·선행조건, 성공/중단 기준과 복구안을 고정한다. 후보 SHA의 정적·모의·CI·격리 시험은 범위와 격리/복구 조건을 기록해 Lead 판단으로 진행할 수 있다. 후보 시험이나 코드 병합을 운영 반영 완료로 표시하지 않는다.

Lead는 기존 기록에 대상/단계·Lead·KST 시각·해당 SHA/Digest·검증/원본 증적·판정/잔여·해당 복구 방법을 남긴다. 비해당 항목의 별도 서류를 만들 필요는 없다. STATIC/MOCK/CI/RUNTIME/REVIEW/MERGE/PUBLICATION은 구분한다. 해시 일치는 무결성이고 CI 0건은 NOT RUN이다.

필수 AC·시험·보안·실패 시 중단·회수 조건은 유지한다. 비밀키·Token·Password·Secret은 커밋하지 않는다. 원본 증적·과거 승인 이력과 진행 중인 실행의 기존 계약을 소급 수정하지 않는다. 증적 저장소 편입 PR은 독립 리뷰를 거치며, 그 병합만으로 업무 티켓을 자동 종결하지 않는다.
