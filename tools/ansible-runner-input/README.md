# Token input guard — Draft / NOT_RUN

This helper replaces the earlier shell instruction that unconditionally applied
chmod 600 to an operator-entered path. Do not run that withdrawn chmod step.

**This candidate has not been executed or packaged.** The development workspace
became unavailable before implementation. The tests below are source code, not
PASS evidence. Do not distribute or use this helper on the server until they pass
and the review gate is completed.

## Scope

- Run as server01_cicd-runner on cicd-runner01, without sudo.
- Token input must be a direct child of /home/server01_cicd-runner named
  ansible-runner-token-<generated-name>.json.
- The home comes from the passwd record and is checked against the expected
  account path; an environment HOME override is not accepted.
- Reject directories (including the home), links, special files, owner mismatch,
  oversized/invalid/expired packets and a different repository before chmod.
- Read and validate the same descriptor that receives fchmod(0600). A pathname
  replacement cannot redirect that operation to a directory.
- Refuse an unsafe home rather than changing it.
- Write RESULT.json and RESULT.json.sha256 inside a new 0700
  ansible-token-input-evidence-* directory in the original login home. Files are
  0600. If the home itself cannot be trusted/opened, report failure on the terminal
  without writing elsewhere.
- Errors are fixed codes. Evidence contains no tokens, original input path,
  packet content hashes or raw exception text.
- No deletion, recursive chmod, registration, container execution, service or
  account change. A valid token file may change from its original mode to 0600.
- A failure after permission application may leave that verified file at 0600;
  the result explicitly records permission_changed. It never widens permissions
  or attempts rollback onto an operator-supplied path.
- Concurrent modification by the same account is not treated as a security
  boundary. Metadata/identity changes are rejected, and the Runner launcher must
  independently re-read and validate the packet after this helper succeeds.

The packet schema and 10–120 minute expiry contract match the deployed
tools/ansible-runner/common.py. Duplicate JSON keys are additionally rejected.
The helper imports only the Python standard library and makes no network calls.

## Review and test gate

DEEP_REVIEW.md was committed before code was written.
CODE_REVIEW.md records the subsequent static review and remaining execution gap.

From a checkout of this Draft PR, on a suitable Linux development environment:

    python3 -I -B tools/ansible-runner-input/test_safe_input.py

The 20 test methods use synthetic tokens and new temporary directories in the
test account's passwd home. They do not use an actual token, Podman or GitHub API.
Do not count these tests as passed until an actual log and return code exist.

After the gate has passed, the operator flow is:

1. Transfer the freshly issued token packet privately into the login home.
2. Run safe_input.py --token-file with its exact path, as the normal login user.
3. Continue to the existing Runner launcher only if exit code is 0 and status is
   PASS_TOKEN_INPUT. A shell integration must enforce this with an explicit
   conditional or a correctly scoped set -e; never run the launcher regardless
   of guard failure.
4. Submit only the evidence JSON and its sidecar. Never upload the token packet.

No executable deployment instructions or ZIP are issued with this untested
candidate.

## Current Runner result

The submitted runtime archive with SHA256
7b8906a94ad5a4b23ae8a1d32cc307160311ea90cf17cad70623898384d1a0b7 passed
registration-check on 2026-09-16 17:25:32–17:25:58 UTC.
Runner ID 3 / ansible-ci-f9e3ef4d85e44573891eaebcaffd5b1d configured and removed with
rc0. The UTF-8 BOM identity parsing and isolation/cleanup checks passed.
This earlier run did not use this new guard.

The 24-file Runner v1.2 bundle, 11-file admin-token bundle, PREPARED receipt and
verified image remain unchanged. Adding this separate helper does not require a
new image build or repeating the already successful registration check merely
to test the helper.

Next: confirm the new ID/name is absent through the management host's read-only
GitHub API query. Workflow activation, actual Actions runs, independent approval
and merging remain separate outstanding steps.
