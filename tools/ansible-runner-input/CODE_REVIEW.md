# Static code review of the input guard

Status: static self-review completed; 20 local regression methods subsequently PASS. No independent approval claimed.

- Input validation is upstream of the only production permission mutation.
- The CLI rejects root/sudo invocation, wrong host/account and an unexpected
  passwd home; it disables process dumping before reading credentials.
- Every home component is opened without following symlinks. Ancestors must be
  root/current-user owned and not writable by group/others; the final home must
  belong to the caller and retain owner search permission.
- The strict basename gate precedes the token open. No user input becomes a
  subprocess command, path for chmod, recursive filesystem operation or
  arbitrary evidence filename.
- The token open uses O_NONBLOCK so a FIFO cannot wait for a writer. fstat checks
  the type before any read. Reads are bounded to 8193 bytes.
- Full metadata is compared before/after reading and before applying mode.
  Directory-entry identity is checked both before and after descriptor fchmod.
  fchmod cannot change a substituted directory; a substitution is reported FAIL.
- JSON field sets, repository, token format and aware expiry are validated.
  Duplicate keys are rejected. Raw parse errors are not emitted.
- Evidence is written using O_EXCL into a new private home directory and uses
  only allowlisted fields. Evidence write failure changes the process verdict to
  FAIL. No fallback into /tmp or the dedicated account home is used.
- A check after chmod can fail; the verified file may then remain 0600. This is
  intentionally not rolled back, because rollback is unnecessary and a pathname
  rollback would reintroduce the incident's class of bug.
- The helper does not promise atomic protection from another process using the
  same UID. The existing launcher independently revalidates its input.
- Test source includes 20 methods covering the incident path, other filesystem
  objects, contract failures, redaction and a pathname replacement at fchmod.
  The test fixture cleanup is confined to its freshly created temporary
  directory; it is not part of the production helper.
- Existing Runner/admin-token source and manifest files are not modified.

Execution update: the workspace connection recovered. All 20 regression methods
passed in the actual local Python run saved as validation/unit.log and unit.rc.
This closes the temporary local execution gap; server execution of this guard
and independent approval remain pending. The actual PASS_REGISTRATION_CHECK
receipt belongs to the unchanged Runner v1.2 and is not a server guard test.

The only code change after that first successful local run removes the obsolete
candidate-only module docstring; the packaged source is tested again with its log
captured. No filesystem behavior is changed for packaging.
