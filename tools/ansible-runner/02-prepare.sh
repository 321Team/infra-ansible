#!/bin/bash
set -euo pipefail
umask 077
TASK_KIT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$TASK_KIT_ROOT/common-start.sh"
check_login server01_cicd-runner cicd-runner01 /home/server01_cicd-runner
cd -- "$TASK_KIT_ROOT"
sha256sum -c SHA256SUMS
sudo bash run.sh prepare
