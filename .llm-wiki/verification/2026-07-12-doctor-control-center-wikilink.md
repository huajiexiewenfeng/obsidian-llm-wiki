# Verification: 2026-07-12-doctor-control-center-wikilink

- executor: agent-local
- authority: local worktree plus installed project-level runtime
- trust_level: agent-local
- regression RED: control-center-relative Wikilink produced `broken-index-link`
- focused GREEN: 4 resolver tests passed
- full command: `python -m unittest discover -s tests`
- full result: 230 passed, 2 conditional skips, 0 failures
- diff_check: passed
- pushed_commit: `cd31cc3`

## Installed Runtime Trial

- project-level runtime file hash matched the pushed repository file.
- prior successful archive target: `raw/src-562cc684d7b7a410/archive-trial.bin`
- source/archive SHA-256 bytes: equal
- `doctor validate --fail-on error`: exit 0
- Doctor ERROR findings: 0
- remaining findings: sample Vault missing roadmap and knowledge map only

## Test Integrity Gate

- production and tests changed together: yes
- regression uses real temporary files and subprocess Doctor, not mocked resolver output
- assertion checks the externally visible broken-link finding
- existing vault-root, wiki-root, and explicit-relative resolver tests remained green
- no expectations were weakened or deleted

## Residual Risk

- evidence remains agent-local rather than independent CI/reviewer authority.
- the two full-suite skips remain Windows symlink privilege and opt-in Skills CLI install integration.
