# Obsidian LLM Wiki Default Vault Configuration Design

## Goal

Let a Skill turn a user-confirmed Vault path into the user's default Obsidian
LLM Wiki target. Later Skill invocations can resolve that default automatically
without scanning the filesystem or silently selecting a different Vault.

This is a small v0.2 increment to the shared Root Resolver. It builds on the
existing user-configuration fallback; it does not introduce registries, ingest
transactions, or broad filesystem discovery.

## Product Decision

The user interaction is intentionally two-step:

```text
User provides a candidate Vault path
-> resolve it without writing
-> Skill displays vault_root, control_center, and wiki_root
-> human confirms this candidate
-> configure command persists it as the default Vault
```

When no configured root or explicit path is available, the Skill first reads
Obsidian's local recent-Vault metadata and presents its existing absolute paths
for the human to select. This is candidate discovery, not root resolution: a
recent Vault is never selected or persisted without human confirmation.

`root resolve` stays read-only. A persistence command requires an explicit
confirmation flag, so a Skill cannot change the user's default merely by
probing a path.

When a newly confirmed Vault becomes the default, prior Vault records remain in
the user configuration but are marked inactive. There is always at most one
active user Vault.

## Scope

### In scope

- `root configure` as an explicit user-default persistence command.
- Read-only `root discover` for Obsidian recent-Vault metadata.
- Reuse of the existing Vault/control-center/wiki-root classifier.
- User-level configuration read, preview, atomic update, and validation.
- A `--confirm` safety gate for any write.
- Skill instructions for resolving a candidate, showing it to the human, and
  persisting it only after confirmation.
- Tests for first-time setup, default switching, invalid paths, and no-write
  behavior without confirmation.

### Out of scope

- Scanning the whole disk, home directory, or arbitrary drives for Vaults.
- Reading note bodies, attachments, or any Vault content during discovery.
- Writing project `.obsidian-llm-wiki.json` automatically.
- Per-project default selection; project configuration remains an explicit
  higher-priority override.
- Synchronization between machines or cloud storage.
- Concurrent multi-process locking beyond atomic single-file replacement.

## User Experience

### Candidate discovery when no root is configured

If explicit root, project configuration, environment, and user default are all
absent, the Skill calls a read-only discovery command. The command reads only
the local Obsidian application metadata that lists recently opened Vaults. It
deduplicates existing absolute paths and never walks parent directories or
drives looking for more.

The Skill shows the paths directly, without inventing display names:

```text
Detected recently used Obsidian Vaults:

1. D:\knowledge\Work Wiki
2. C:\Users\admin\Documents\Obsidian Vault
3. E:\Notes\Learning

Choose the default LLM Wiki by number, or provide another absolute path.
```

With exactly one candidate, the Skill shows that absolute path and asks whether
to use it as the default. With no usable candidate or unreadable application
metadata, the Skill asks the user to provide an absolute Vault path. Discovery
does not read any note, inspect `.obsidian/`, or write any configuration.

### First-time setup from a supplied path

For a user-provided path such as:

```text
C:\Users\admin\Documents\Obsidian Vault
```

the Skill runs the equivalent of:

```text
python scripts/llm_wiki.py root resolve --root "C:\Users\admin\Documents\Obsidian Vault" --format json
```

The resolver accepts a Vault root, control center, or direct `wiki/` root. It
normalizes the candidate to `vault_root`, `control_center`, and `wiki_root`.
The Skill displays those three values and asks the user to confirm.

After confirmation, the Skill runs:

```text
python scripts/llm_wiki.py root configure --root "C:\Users\admin\Documents\Obsidian Vault" --activate --confirm --format json
```

The command records the normalized Vault as the user default. Subsequent root
resolution uses it only after explicit root, project configuration, and the
environment variable have had priority.

### Preview without a write

Calling `root configure` without `--confirm` produces a JSON or text preview
of the resolved candidate and the planned active-Vault change. It returns a
`confirmation-required` result and writes nothing.

This lets a human or a Skill inspect exactly what will be persisted before
providing `--confirm`.

### Changing the default

When a different Vault is confirmed with `--activate --confirm`:

1. The configured Vault is added if it is new, or its existing record is
   updated with the normalized paths.
2. Its `active` flag becomes `true`.
3. Every other Vault record becomes `active: false`.
4. Historical inactive records remain available for a future explicit switch.

The command never chooses between multiple Vaults by itself. A new default is
created only from the one path the user confirmed.

## CLI Contract

### Candidate-discovery command

```text
python scripts/llm_wiki.py root discover [--format json|text]
```

`root discover` is read-only. It returns only existing absolute Vault paths
listed in supported Obsidian recent-Vault metadata. JSON results include a
`candidates` array and a metadata-source status. An unavailable, malformed, or
unsupported metadata file produces an empty candidate list with an explanatory
status; it does not cause a filesystem scan.

Exit codes:

| Result | Exit code |
|---|---:|
| Discovery ran, including an empty candidate result | 0 |
| Unsupported command arguments | 2 |

### New command

```text
python scripts/llm_wiki.py root configure \
  --root <vault-or-control-center-or-wiki> \
  --activate \
  --confirm \
  [--user-config <path>] \
  [--format json|text]
```

Arguments:

- `--root` is required and is passed through the shared explicit-root
  classifier.
- `--activate` is required in this increment; it prevents accidental creation
  of an inactive record with unclear semantics.
- `--confirm` is required before any user-configuration write.
- `--user-config` optionally overrides the platform default and is primarily
  for tests or a user-controlled configuration location.
- `--format` defaults to `json` and supports `text` for terminal users.

### Results and exit codes

| Result | Exit code | Write performed |
|---|---:|---|
| Valid confirmed activation | 0 | Yes |
| Valid preview without `--confirm` | 1 | No |
| Invalid root or invalid existing user configuration | 2 | No |
| Filesystem/permission failure while saving | 2 | No completed update |

The preview payload includes `confirmation_required: true`, the normalized
candidate, the user configuration path, and the planned active Vault. A success
payload includes the same resolved values plus `configured: true`.

## Configuration Model

The existing user configuration remains the storage format:

```json
{
  "schema_version": 1,
  "vaults": [
    {
      "vault_root": "C:/Users/admin/Documents/Obsidian Vault",
      "control_center": "00-知识库中控",
      "active": true
    }
  ]
}
```

The saved record uses the normalized Vault root and the control-center path
relative to that Vault. The writer rejects an existing configuration that is
not a schema-version-1 object with a `vaults` array; it must not overwrite an
unrecognized or corrupt configuration.

Records are deduplicated by normalized `vault_root` plus `control_center`.
Unknown top-level keys and unknown per-record keys are preserved when updating
an otherwise valid configuration, so later schema additions are not discarded.

## Persistence Rules

1. Resolve and validate `--root` before reading or modifying configuration.
2. Load the user configuration if it exists; otherwise begin with a new
   schema-version-1 object and an empty `vaults` array.
3. Build the next configuration entirely in memory.
4. Write UTF-8 JSON to a temporary sibling file in the same directory.
5. Replace the target with `os.replace` only after the temporary write
   succeeds.
6. On any failure before replacement, retain the original configuration.

This design provides a recoverable single-file update without expanding into
the v0.2 operation-log and lock system.

## Resolution Priority After Configuration

The priority order is unchanged:

```text
explicit --root
-> nearest project .obsidian-llm-wiki.json
-> OBSIDIAN_LLM_WIKI_ROOT
-> exactly one active user-configured Vault
-> safe missing-config or multiple-roots result
```

`root configure` only changes the fourth source. It never overrides a project
configuration or an explicit user request.

Candidate discovery is deliberately outside this priority chain. It is used
only to help a human select a path when the chain cannot resolve a root.

## Skill Rules

The five Obsidian Wiki Skills use the same behavior:

1. Resolve an explicit path or existing configured root without writing.
2. If no root is configured, run `root discover` and show its absolute-path
   candidates. If it returns none, ask the user for a Vault path.
3. Display the selected candidate's normalized `vault_root`, `control_center`, and
   `wiki_root`.
4. Persist it only after the user explicitly confirms it should become the
   default.
5. State which root is used before reading or writing wiki content.

`obsidian-wiki-init` may accept a new Vault path that does not yet contain a
control center; it must obtain separate confirmation before creating the
control-center structure. Other Skills require a resolvable existing control
center or wiki root.

## Error Handling

- An invalid supplied path returns `invalid-root`; no configuration is written.
- A malformed existing user configuration returns `invalid-config`; no attempt
  is made to repair or overwrite it.
- A missing parent directory for the user configuration is created only after
  `--confirm` and immediately before the atomic write.
- Permission errors are returned with the target user-config path and no
  partial target file.
- The command does not fall through to an unrelated Vault when setup fails.

## Verification

Unit and CLI tests cover:

- previewing a supplied Vault without writing configuration;
- first confirmed activation creating a valid user configuration;
- switching defaults while retaining the former Vault as inactive;
- resolving the newly active default without an explicit root;
- rejecting invalid paths and malformed existing configurations without writes;
- preserving unknown valid JSON keys through an update;
- atomic-write failure behavior through an injected filesystem seam;
- Windows and Linux user-configuration paths;
- recent-Vault discovery returning existing absolute paths without reading Vault
  contents or scanning directories;
- empty, malformed, and unsupported recent-Vault metadata returning safe empty
  candidate results;
- Skill and README instructions documenting human confirmation and no broad
  filesystem search.

## Acceptance Criteria

- A user can provide one Vault path and confirm it once.
- Later commands resolve that Vault automatically when no higher-priority root
  source exists.
- Switching defaults never silently deletes the previous Vault record.
- No command scans arbitrary disks to discover a Vault.
- `root resolve` remains read-only.
- No configuration write occurs without `--confirm`.
