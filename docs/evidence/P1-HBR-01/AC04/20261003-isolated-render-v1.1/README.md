# PR63 current-template isolated render evidence

Source commit: badbe29440916ec3ec79da8fc81722c2e6c4e75b (not this evidence commit).
Execution: ansible01, 2026-10-03 21:07:56–21:08:03 KST; ansible-core2.16.19; nftables1.1.5.
Original uploaded archive SHA256: bc9c4a7f5a601a8247887587bdd383a375e54ae1d3cd16876dba614f1569c252.
Rechecked archive digest and all 40 SHA256SUMS entries on 2026-10-03. The 41 original archive files, including SHA256SUMS, are preserved without text modification. README is added documentation outside the original manifest.

Read isolated-probe.stdout.log for namespace identity, empty initial ruleset, exact nft command flags, numeric table/chain output, complete unchanged repository verifier run (ok13 changed0 failed0 unreachable0 rc0), and isolated table destruction. RENDERED.nft preserves explicit IPv4 nfproto input; actual numeric output elides it. RESULT.json and PR_IDENTITY.json bind the source and execution scope. HARNESS.json and render/isolated-probe command records preserve how template rendering and verifier execution were invoked.

Verdict: ISOLATED_RENDER_VERIFIER_PASS only. No production apply, engine transition, real traffic/persistence acceptance, independent approval, or merge is established. This successful v1.1 run is distinct from the earlier v1.0 harness-path failure. Review finding withdrawal remains the reviewer's decision.

The source PR63 branch is not moved by this evidence publication. This branch is an evidence carrier, not an approved deployment source.
