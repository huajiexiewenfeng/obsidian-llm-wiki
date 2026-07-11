# Installable Skill Runtime Packaging Design

## Bug Brief

- **Symptom:** after `npx skills add huajiexiewenfeng/obsidian-llm-wiki`, installed Obsidian skills contain `SKILL.md` and `references/`, but not the repository-root `scripts/` directory. Commands such as `python scripts/llm_wiki.py doctor report ...` therefore fail.
- **Expected behavior:** installing the repository with Skills CLI installs every file required to run root resolution and Doctor commands, independent of the source checkout.
- **Evidence:** Skills CLI treats each directory containing `SKILL.md` as the installable unit. The current Python runtime lives at repository root while all five consumer skills invoke it. The installed `obsidian-wiki-doctor` directory has no `scripts/` child.
- **Reproduction status:** reproduced against the installed skill layout. A repository-level integration test will reproduce it automatically before implementation.
- **Active scope:** skill packaging, runtime location, consumer skill command documentation, compatibility entry points, installation tests, CI, and installation documentation.
- **Read-only scope:** Doctor behavior and Vault root-resolution behavior.
- **Excluded scope:** changes to user Vaults, new Doctor checks, publishing a release, and unrelated skill text.
- **Flow ID:** `skill-runtime-packaging-2026-07-11`.

## Goals

1. Make the deterministic Python runtime part of an installable skill directory.
2. Keep one canonical runtime implementation.
3. Preserve repository-root script entry points for developers and existing automation.
4. Make every consumer skill resolve the installed runtime explicitly rather than assuming the current working directory is the repository root.
5. Prove the public installation command installs and runs the runtime.

## Non-Goals

- Converting the project exclusively to a Codex or Claude plugin.
- Duplicating the runtime into all five consumer skills.
- Changing command semantics, report formats, scores, or root-selection precedence.
- Automatically modifying global user skill installations during tests.

## Reference Pattern

`obra/superpowers` keeps files needed by a skill under that skill directory, for example `skills/brainstorming/scripts/`. Its Codex plugin manifest exposes `./skills/` as the skill tree. The important packaging rule is that an installed skill must not depend on repository-root files that the skill installer does not copy.

This project will apply that rule through one internal shared skill rather than duplicating the same Python runtime in five user-facing skills.

## Proposed Layout

```text
skills/
  obsidian-wiki-runtime/
    SKILL.md
    scripts/
      llm_wiki.py
      obsidian_wiki_doctor.py
      llm_wiki_core/
        __init__.py
        root.py

  obsidian-wiki-doctor/
    SKILL.md
  obsidian-wiki-ingest/
    SKILL.md
  obsidian-wiki-init/
    SKILL.md
  obsidian-wiki-maintain/
    SKILL.md
  obsidian-wiki-query/
    SKILL.md

scripts/
  llm_wiki.py                 # compatibility launcher
  obsidian_wiki_doctor.py     # compatibility launcher
```

`skills/obsidian-wiki-runtime/scripts/` is the canonical implementation. Repository-root launchers delegate to it so existing commands and tests remain compatible without maintaining two implementations.

## Runtime Skill Contract

`obsidian-wiki-runtime/SKILL.md` describes an internal dependency. It is not a user workflow and must not replace the five intent-specific skills.

The skill must remain discoverable by Skills CLI and therefore must **not** set
`metadata.internal: true`; the CLI skips internal skills during a normal
repository installation unless `INSTALL_INTERNAL_SKILLS` is explicitly enabled.

It exposes one executable entry point:

```text
<skills-root>/obsidian-wiki-runtime/scripts/llm_wiki.py
```

The entry point owns both command groups:

```text
root discover|resolve|configure
doctor report|validate|score
```

The runtime has no third-party Python dependencies.

## Consumer Runtime Resolution

Each consumer `SKILL.md` will contain the same runtime-resolution contract:

1. Resolve the current skill directory from the selected `SKILL.md` resource.
2. Resolve its parent as `<skills-root>`.
3. Build `<skills-root>/obsidian-wiki-runtime/scripts/llm_wiki.py`.
4. Verify that the file exists before accessing the Vault.
5. Invoke Python with the absolute runtime path.
6. If missing, stop with `missing-runtime` and recommend reinstalling the complete repository.

Command examples will use `<runtime-script>` instead of the ambiguous repository-relative `scripts/llm_wiki.py`:

```text
python <runtime-script> root resolve --cwd <working-directory> --format json
python <runtime-script> doctor report --root <control-center-or-vault> --format text
```

This contract is stable for global, project-local, and custom Skills CLI destinations because it depends only on sibling skill directories.

## Compatibility Launchers

The two repository-root scripts remain supported:

- `scripts/llm_wiki.py`
- `scripts/obsidian_wiki_doctor.py`

They will delegate with `runpy.run_path` to canonical files below `skills/obsidian-wiki-runtime/scripts/`, preserving arguments, standard streams, and exit codes. They will emit a clear error if the canonical runtime is missing.

Direct execution of the installed runtime does not pass through these launchers.

## Installation Verification

Regression coverage will have two layers.

### Repository Contract Test

A Python test will verify:

- the runtime skill contains `SKILL.md` and the complete required Python file set;
- all five consumers document the shared runtime resolver;
- consumer command examples do not invoke repository-root-relative `python scripts/llm_wiki.py`;
- compatibility launchers exist and delegate to the canonical runtime.

This test is deterministic and runs in the normal unit-test suite.

### Skills CLI Integration Test

An isolated smoke test will:

1. create a temporary HOME and project installation target;
2. run Skills CLI 1.5.16 non-interactively against the local checkout with
   `--skill '*' --agent codex --copy --yes` and project-local scope;
3. assert that `obsidian-wiki-runtime/scripts/` is present in the installed skills tree;
4. execute the installed `llm_wiki.py root resolve` against a temporary Vault;
5. execute the installed `llm_wiki.py doctor report` against the same Vault;
6. avoid reading or modifying any real user Vault or global skill installation.

The cross-platform test selects `npx.cmd` on Windows and `npx` elsewhere, then
executes the equivalent of:

```text
npx --yes skills@1.5.16 add <repository-path> --skill '*' --agent codex --copy --yes
```

It sets `HOME`, `USERPROFILE`, `DISABLE_TELEMETRY`, and `DO_NOT_TRACK` to
temporary/test values. CI runs this pinned integration test in addition to the
Python suite. Final release verification also runs the public unpinned command
against the repository checkout so version drift in the public installation
path is visible before publishing.

## Documentation

README installation sections will state that a complete install includes `obsidian-wiki-runtime` and provide a post-install verification command. Developer documentation will identify the runtime skill directory as canonical and the repository-root scripts as compatibility launchers.

## Error Handling

- Missing installed runtime: consumers report `missing-runtime`, show the expected path, and recommend reinstalling the whole repository.
- Incomplete runtime file set: the entry point fails before Vault access with a concise missing-module error.
- Skills CLI failure: the integration test reports command output and the isolated destination; it never falls back to copying files manually.
- Compatibility launcher mismatch: repository contract tests fail before release.

## Security and Safety

- Installation tests use temporary directories and synthetic Vaults only.
- No test reads existing Obsidian metadata unless a test-specific path is supplied.
- No test writes to global `~/.agents`, `~/.claude`, or Codex skill directories.
- Existing secret-redaction and safe-root behavior remain unchanged and covered by the current suite.

## Acceptance Criteria

1. A clean `npx skills add huajiexiewenfeng/obsidian-llm-wiki` installs `obsidian-wiki-runtime/scripts/llm_wiki.py` and all imported modules.
2. The installed runtime successfully runs `root resolve` and `doctor report` without a repository checkout.
3. All five consumer skills resolve the shared runtime from the installed skills root.
4. Repository-root script commands remain compatible.
5. Existing tests and new packaging tests pass on Windows-compatible paths.
6. The test process does not mutate the user's actual skill directories or Vaults.
7. A normal installation includes the runtime without requiring
   `INSTALL_INTERNAL_SKILLS`.

## Verification Plan

1. Run the new repository contract test and observe it fail before implementation.
2. Run the isolated Skills CLI integration test and observe the missing runtime failure before implementation.
3. Move the canonical implementation into the runtime skill and add compatibility launchers.
4. Update consumer skills and documentation.
5. Run the focused packaging tests until green.
6. Run all Python tests.
7. Run the isolated `npx skills add .` smoke test and execute installed CLI commands.
8. Inspect `git diff --check` and the final changed-file list.
