# Issue9 복원 file fixture — Pre-check / local only

책임: https://github.com/321Team/infra-ansible/issues/9
연관 증적: https://github.com/321Team/fds-project-evidence/pull/113

## 목적과 경계

worker02는 이미 제한된 키 상태에서 실제 apply2회 및 fresh SSH가 성공했다. 같은 내용의 백업을 덮어쓰는 것으로 실제 내용 복원 분기까지 검증했다고 할 수 없어, 운영 키를 훼손하지 않는 임시 파일 실험을 추가한다.

`tests/run-ssh-key-restore-file-fixture.py`는 인수/외부 경로를 받지 않고 TemporaryDirectory 안의 합성 파일만 다룬다. SSH·sudo·Ansible·실제 키·운영 서비스는 사용하지 않는다. 사용자 실행용 복원 도구가 아니며 fixture의 exercise 함수를 운영 파일에 전용하지 않는다.

## 실제 로컬 시험

2026-10-05 KST Codex 실행 환경에서 `python3 -I -B tests/run-ssh-key-restore-file-fixture.py` 실행: rc0, 7/7 PASS.

| 사례 | 실제 확인 |
|---|---|
| 내용·mode 차이 | cp --preserve=all로 stage 후 hash/메타데이터 확인, os.replace 후 baseline 복원 |
| 동일 내용 재적용 | 성공 및 baseline 유지 (inode 불변 검증 아님) |
| 잘못된 백업 hash | 거부, target bytes/metadata 유지 |
| backup symlink | 거부, target 유지 |
| target symlink | 거부, 참조 대상 내용/metadata와 링크 유지 |
| backup hardlink | 거부, target 유지 |
| 교체 직전 예외 주입 | target 보존 및 stage 정리 |

스크립트 SHA256: 905683463d2320f2cd05e6c0112ae8985c8e9c796e03dd57b29bb74d04625ded

uid/gid는 실행자 소유 합성 파일 간 동일성만 확인했다. SELinux context, 다른 UID/GID로의 복구, 2.16/2.21 Ansible 실행, 원격 복원, 전원 손실 내구성, 적대적 동시 경로 교체는 검증하지 않았다. cp 파일 부분 실패 전체를 시험한 것으로도 확대하지 않는다. 로컬 결과를 Issue9 rollback AC 또는 운영 전환 PASS로 표시하지 않는다.

## 후속

- evidence PR113 독립 리뷰는 별도 대기. 이번 변경은 기존 source5454b77d로 실행한 canary 증적을 소급 변경하지 않는다.
- 실제 복원 자료는 NXrcqAmF 백업과 현재 drift 검사를 고정하고 worker02만 대상으로 하며, 소유권·mode·SELinux·fresh SSH를 별도로 검증해야 한다.
- 운영 Runtime 코드/실행 설정으로 편입하려면 해당 SHA의 독립 리뷰와 Lead 실행 판단이 필요하다. Pre-check 병합 가능성을 Runtime 승인으로 쓰지 않는다.
- 실행 가능한 서버 복원 명령은 이 PR에 포함하지 않음. 시스템 RPM/PATH/wrapper도 변경하지 않음.

AI usage: CODEX_ASSISTED. 작성자 자체 점검이며 독립 리뷰 미수행.
