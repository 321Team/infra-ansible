# Token input permission guard: pre-change deep review

Status: review completed before implementation; self-review, not independent approval.
Base: infra-ansible 9cb8d6c702f750b9276daec859b1c237109daed1.

## Incident and evidence boundary

The operator reported a wrong absolute-path entry, an inaccessible/empty-looking login home, and subsequent recovery.
Earlier shell guidance applied `chmod 600 -- "$TASK_TOKEN_PATH"` before checking the object type. A home-directory input could remove its search permission. The actual incident's directory mode/deletion was not independently observed.
The local synthetic reproduction recorded in this session demonstrated inaccessible contents after directory mode 0700 -> 0600 and accessibility after 0700 restoration; this does not establish a server-wide reset or data deletion.

The deployed launch.py already requires a bounded, singly linked regular token file owned by the original login user with mode 0600. It does not perform chmod on that input. Its later validation cannot protect an earlier shell chmod. The new guard belongs before that shell step.

## Decisions made before coding

1. Add an independent helper under tools/ansible-runner-input. Do not modify the 24 deployed Runner v1.2 files or the 11 admin-token files; retain the verified image and PREPARED binding.
2. The production CLI runs only as the original non-root login on cicd-runner01. Do not accept HOME from the environment as authority; use the passwd record and the expected account/home.
3. Only accept a direct child of that home with the generated token-packet filename. Reject relative, parent, noncanonical, directory and out-of-home paths.
4. Open each home component with O_DIRECTORY|O_NOFOLLOW; check ownership/write permissions. Open the token relative to the pinned home descriptor with O_NOFOLLOW|O_NONBLOCK.
5. Before any permission mutation: require a bounded regular file, single hard link, expected owner, no special mode bits; read and verify stable metadata, reject duplicate JSON keys, validate the exact repository, token field shape and 10–120 minute expiry window.
6. Change mode using fchmod on that same verified descriptor, never chmod on the supplied pathname. Recheck the directory entry identity and final metadata. A name swap cannot make a directory the chmod target.
7. Do not recursively chmod, delete, copy to the dedicated account, start a Runner, or call an external service. The launcher remains a separate step and must revalidate its own input.
8. Write only fixed error codes and boolean/state fields to a new private evidence directory in the original login home. Never emit token contents, raw exceptions or user-supplied path strings on failure. Disable memory dumps before reading credentials.
9. Test home/directory rejection, links, FIFO nonblocking rejection, path bounds, owner/content/expiry validation, unchanged rejected inputs, valid 0644->0600 behavior, idempotence and a name-swap regression. Use synthetic tokens only.
10. If the home itself cannot be trusted/opened, fail without attempting to repair it or choose another evidence directory.

## Validation/release gate

The workspace execution service is currently unavailable (environment_offline). New helper tests must be executed before this helper is packaged, distributed or used on the server. This change is a Draft review candidate, not a tested deployment artifact. Do not reuse Runner v1.2's 49 prior tests as this helper's test result.

Latest submitted actual Runner archive: SHA256 7b8906a94ad5a4b23ae8a1d32cc307160311ea90cf17cad70623898384d1a0b7, 6206 bytes.
PASS_REGISTRATION_CHECK; ID 3; ansible-ci-f9e3ef4d85e44573891eaebcaffd5b1d; configure/remove rc0; BOM decoding and identity checks passed; cleanup passed.
That run predates and does not exercise this new input guard. Management API absence for the new ID/name remains pending; Actions was NOT_RUN.

## Reference semantics

- Python descriptor-relative operations and fchmod: https://docs.python.org/3/library/os.html
- Directory search permission: https://man7.org/linux/man-pages/man7/path_resolution.7.html

## Superseded operator step

The earlier unconditional `chmod 600` on an operator-supplied token path is withdrawn.
Keep the historical runtime bundles byte-for-byte; use the new operations note for current instructions after its validation gate is satisfied.
