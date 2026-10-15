# Issue9 역할 fixture 보완 검증

2026-10-15 KST · CODEX_ASSISTED. [변경·기존 증거·남은 실행안](../../../runbooks/Issue9-Role-Fixture-Followup.md).

- MON 7/7, NTP 입력4/4: 새 회귀의 실제 로컬 결과. Windows Git Bash/가짜 inventory 및 YAML/Jinja 입력 시험이며 Ansible·서비스·서버 실행이 아니다.
- `VALIDATION.json`은 정확한 변경 파일 SHA, argv, 환경, 수행·미수행 상태를 보존한다. stdout/stderr 원문은 빈 출력도 포함한다.
- `MON_VALIDATION.json`은 앞서 완료한7건의 원본 기록. 변경 없는 시험을 재실행하지 않고 SHA 일치를 확인하여 재사용했다.
- `EVIDENCE_BINDING.json`의 MON4행/manifest4행은 같은 두 엔진 실행의 중첩 archive와 펼친 사본이다. 시험4회 또는180건으로 합산하지 않는다.
- NTP37파일 대조는 당시 uncommitted source의 파일별 SHA를 기준으로 한다. 예전 source_head를 실행 코드 전체로 오인하지 않는다.
- `SHA256SUMS`는 이 편입 파일 바이트 검사용이며 Linux/Runtime/독립 인수 PASS가 아니다. 새 PR의 CI·리뷰·병합은 GitHub 실제 상태를 따른다.
