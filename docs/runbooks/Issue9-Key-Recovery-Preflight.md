# Issue9 — worker02 키 복원 사전검증 v1.0

책임: [infra-ansible#9](https://github.com/321Team/infra-ansible/issues/9).
근거: PR70 병합 설계 blob `fb0a91c1111b36dd7cd3d667bb8ddd031d0f6fec`, evidence#113 병합 `a9837ea2e3531a5754f728c646b69e51d6568bfd`의 `backup-RECEIPT.txt` blob `6db514343b1d9908729a9644fe727deff2bf6cea`.
단계: **SOURCE_PREPARED / MOCK ONLY / FIELD NOT_RUN / 독립 검토 대기**.
AI usage: CODEX_ASSISTED.

## 목적과 경계

`tools/inspect-worker02-key-recovery.py`는 복원 판단에 필요한 현재 백업·목적지 메타데이터를 수집하는 **읽기 전용** 도구다. 운영 키 쓰기/복사/stage/교체, chown/chmod/chcon/restorecon, SSH·Ansible·엔진 전환, 토큰 발급은 구현하지 않는다. stdout JSON 외 산출물을 자체 생성하지 않는다. 키 내용과 OS 예외 원문을 출력하지 않는다.

기존 receipt의 METADATA는 **SOURCE인 목적지**에 대한 기록이다. 백업 파일 자체의 owner/mode/SELinux label까지 실제 확인한 증거로 재사용하지 않는다. 도구는 양쪽을 따로 관측하며 복원 후 목적지의 기대값 `1001:1001 / 0600 / unconfined_u:object_r:ssh_home_t:s0`을 별도로 유지한다. 백업의 다른 문맥을 목적지로 자동 전파하지 않는다.

현재 정상 상태면 복원이 필요 없다고 보고한다. drift는 별도 원인·정상 변경 이력 검토로 연결하며 오래된 백업을 자동 적용하지 않는다. 실제 쓰기 도구·독립 리뷰·실행창 승인은 후속 작업이며 이 사전검증으로 대체하지 않는다.

## 입력·검증

외부 경로/host/hash 인수를 받지 않는다. 고정 대상은 `k8s-worker02`만이며 worker01은 포함하지 않는다. 고정 backup은 기존 `NXrcqAmF`이며 합성 fixture `lWTROYLy`, `.pre-p1-restrict`, 개인키는 열지 않는다.

- Linux root와 SELinux Enforcing을 요구한다. root부터 부모 경로를 FD 상대 `O_DIRECTORY|O_NOFOLLOW`로 열고 소유자·그룹/other 쓰기 부재를 확인한다. 백업 디렉터리는 root/private, svc home·.ssh는 UID1001, .ssh는 private가 필수다. 현장 값이 다르면 권한을 바꾸지 않고 INCOMPLETE로 중단한다.
- 정규 단일 링크 파일만 읽는다. backup은 owner0 또는1001과 mode0600이 필수다. 대상 owner도 이 집합을 벗어나면 중단한다. 크기 한도는 1~262144바이트이며 초과 파일은 미확인으로 남긴다.
- 열린 파일 FD의 hash/uid/gid/mode/SELinux xattr와 inode/시각을 관측한다. 읽기 전후 파일 fingerprint, 파일 이름→FD 대응, 부모 경로 대응과 label을 재확인한다. FIFO 등 특수파일은 읽지 않고 링크는 따라가지 않는다.
- 두 파일의 관측을 두 차례 비교해 변경을 감지한다. 같은 inode를 원본/목적지로 쓰거나 backup hash가 기존 기대값과 다르면 중단한다.

**한계:** FD 검사와 두 snapshot은 검사 시점의 변경 감지다. 두 검사 사이에 원상 복귀한 변경이나 최종 검사 이후 변경, 비협조적인 동일 UID/root writer를 차단하는 lock/원자 compare-and-swap가 아니다. `restore_ready=false`, `concurrent_writer_exclusion=NOT_ESTABLISHED`를 항상 남긴다. 읽기로 atime이 갱신될 수 있고 내용/권한/보안 정책을 변경하지 않는다. 실효 ACL·mount provenance·SELinux 정책의 적합성 전체를 인증하지 않는다. root 자체를 공격자로 방어하는 도구가 아니다.

## 현장 수집 명령 — 아직 실행하지 않음

대상 **worker02의 기존 VMware 콘솔 / root**에서만 사용한다. 새 SSH 경로를 만들지 않는다. 코드의 독립 검토와 아래 source manifest 대조 뒤 기존 접근·권한으로 수행할 읽기 전용 수집안이다. source 준비를 실제 배포 완료로 표시하지 않는다.

선행조건: 검토된 source/manifest를 새 작업 폴더에 전달, 기존 NXrcqAmF 백업 보존, SELinux Enforcing, worker02 확인, 다른 키 변경 세션과 겹치지 않는 수집 시각 기록. 파일 전달은 기존 VM 제약에 맞춘 번들로 하며 실제 키를 PC·채팅으로 보내지 않는다.

```bash
# worker02 / root; 전달된 새 폴더의 절대 경로로 이동한 뒤 실행한다.
umask 077
sha256sum -c SHA256SUMS
python3.12 -I -B tools/inspect-worker02-key-recovery.py --read-only
```

stdout을 파일로 남길 때는 `set -o noclobber`와 회차별 새 파일명을 사용하고 별도로 실행 시각·종료코드·명령·source SHA256·호스트를 기록한다. 예상 폴더/파일을 덮어쓰지 않는다. 명령 결과의 `inspector_sha256`은 manifest와 대조한다.

| 결과 | 의미 / 다음 조치 |
|---|---|
| rc0 / UNCHANGED_NO_RESTORE_NEEDED | backup hash와 현재 목적지 내용·기대 메타데이터가 수집 시점에 일치. 키 유지. 복원/새 wrapper Runtime/엔진 전환 PASS가 아님 |
| rc2 / DRIFT_REVIEW_REQUIRED | drift 목록 검토, 백업 이후 정상 변경 확인, 콘솔 접근 유지. 쓰기 없이 중단하고 원본 결과를 #9에 보고 |
| rc2 / INCOMPLETE | 링크·권한·읽기·SELinux·snapshot 변경 등으로 판단 불가. 출력 error_code를 보고. root/SELinux/경로 예외나 자동 재시도 없음 |

명령 자체는 설정 복구 대상이 없다. 드러난 drift를 이 도구로 복구하지 않는다. 복원이 필요하면 검토된 실행안을 새로 고정한다: 복원 원본 hash, 목적지 현재 snapshot, 동시 writer 배제, 같은 FS 보호 stage, root에 의한 UID/GID1001·0600 및 **목적지 기대 label 명시 검증**, 검사~교체 경쟁 처리, 원본/현재 파일 보존, fsync와 실패 단계별 상태, 최종검사 및 기존 접근을 통한 신규 SSH. 보안 통제 해제와 시험을 위한 운영 키 훼손은 포함하지 않는다.

## 검증과 제출

Windows Python에서 14개 unittest를 수행한다. POSIX FD·xattr는 모의 kernel이며 실제 Linux syscall/UID1001/SELinux 검증이 아니다. 정상 관측, 백업 label·소유권 분리, 목적지 다섯 drift, host/계정/Enforcing 거부, 원본 hash 실패, snapshot/파일/부모/label 변경, symlink/hardlink·FIFO·권한·크기 거부, 비밀 예외 미출력, FD 정리를 검증한다. 실제 field 수집은 NOT_RUN.

기존 PR66의 필수 Ansible regression queue가 해소되기 전에는 새 PR로 같은 queue를 추가하지 않는다. 준비 branch에 소스와 시험을 보존하고 #9에 링크·hash·한계를 기록한다. queue 해소 후 main 재정합→일반 코드 PR→독립 검토→검토된 source의 현장 읽기 수집 순서다. 런타임 쓰기/복원·wrapper 적용·운영 엔진 전환은 각각 별도 판단한다.
