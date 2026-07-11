# Obsidian WikiLink 解析修复实施计划

> **面向智能体执行者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 修复 Doctor 对 Vault 根路径、带点文件名和 Vault 全局纯文件名 WikiLink 的误报，同时保留相对路径、真实缺失和重名歧义的安全行为。

**架构：** 保持 Markdown 链接解析器不变，为 WikiLink 增加独立的候选路径生成和 Vault 全局文件名索引。`check_links` 每次检查只构建一次文件名索引，并把 `vault_root`、`wiki_root` 和索引传给 `resolve_wikilink`，避免对每条链接重复扫描 Vault。

**技术栈：** Python 3 标准库、`pathlib`、`unittest`、现有 Doctor CLI。

---

## 文件结构与职责

- 修改 `tests/test_obsidian_wiki_doctor.py`：新增 WikiLink 语义回归用例，不引入测试专用生产接口。
- 修改 `scripts/obsidian_wiki_doctor.py`：实现 WikiLink 候选生成、Vault 文件名索引和解析顺序；不修改 Markdown 链接、脱敏、评分或根目录发现。
- 修改 `.llm-wiki/bugs/2026-07-11-obsidian-wikilink-resolution.md`：记录计划、实现和验证证据。
- 不新增第三方依赖，不拆分现有 Doctor 脚本。

## 已确认基线

- 分支：`codex/fix-wikilink-resolution`
- worktree：`C:\tmp\codex-worktrees\obsidian-llm-wiki\fix-wikilink-resolution`
- 基线命令：

```powershell
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

- 基线结果：`Ran 50 tests`，`OK`。

### 任务 1：添加 WikiLink 语义回归测试

**文件：**

- 修改：`tests/test_obsidian_wiki_doctor.py`，放在 `ValidationCheckTests` 的现有 WikiLink 测试附近。
- 测试：`tests/test_obsidian_wiki_doctor.py`

- [ ] **步骤 1：添加四个必须先失败的回归测试**

在 `ValidationCheckTests` 中加入以下代码：

```python
    def test_vault_root_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(
                control / "wiki" / "index.md",
                "# Index\n\n- [[00-知识库中控/wiki/topics/topic|Topic]]\n",
            )

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_dotted_extensionless_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(control / "00.知识库地图.md", "# Map\n")
            write(control / "wiki" / "index.md", "# Index\n\n- [[00.知识库地图]]\n")

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_unique_vault_basename_wikilink_outside_wiki_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(vault / "00.整理范围确认.md", "# Scope\n")
            write(control / "wiki" / "index.md", "# Index\n\n- [[00.整理范围确认]]\n")

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_ambiguous_vault_basename_wikilink_remains_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(control / "wiki" / "topics" / "Topic.md", "# Topic\n")
            write(vault / "archive" / "Topic.md", "# Archived Topic\n")
            write(control / "wiki" / "index.md", "# Index\n\n- [[Topic]]\n")

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertIn("broken-index-link", {item["check"] for item in findings})
```

- [ ] **步骤 2：添加两个保护性测试**

继续在同一测试类加入以下代码，锁定已存在的相对路径行为和真实缺失行为：

```python
    def test_explicit_relative_wikilink_resolves_from_source_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(
                control / "wiki" / "projects" / "project.md",
                "# Project\n\n- [[../topics/topic|Topic]]\n",
            )

            result = run_doctor("validate", "--root", str(control), "--format", "json")

            findings = json.loads(result.stdout)
            project_findings = [item for item in findings if item["path"] == "projects/project.md"]
            self.assertNotIn("broken-internal-link", {item["check"] for item in project_findings})

    def test_genuinely_missing_wikilink_remains_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "index.md", "# Index\n\n- [[Missing Topic]]\n")

            result = run_doctor("validate", "--root", str(control), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertIn("broken-index-link", {item["check"] for item in findings})
```

- [ ] **步骤 3：运行新增测试并确认 RED/保护性结果**

运行：

```powershell
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest `
  tests.test_obsidian_wiki_doctor.ValidationCheckTests.test_vault_root_wikilink_is_not_broken `
  tests.test_obsidian_wiki_doctor.ValidationCheckTests.test_dotted_extensionless_wikilink_is_not_broken `
  tests.test_obsidian_wiki_doctor.ValidationCheckTests.test_unique_vault_basename_wikilink_outside_wiki_is_not_broken `
  tests.test_obsidian_wiki_doctor.ValidationCheckTests.test_ambiguous_vault_basename_wikilink_remains_broken `
  tests.test_obsidian_wiki_doctor.ValidationCheckTests.test_explicit_relative_wikilink_resolves_from_source_page `
  tests.test_obsidian_wiki_doctor.ValidationCheckTests.test_genuinely_missing_wikilink_remains_broken -v
```

预期：

- 前四个测试失败，原因分别是 Vault 根路径误判、带点文件名未补 `.md`、Vault 外 basename 未扫描、重复 basename 被错误地按 Wiki 内唯一目标接受。
- 后两个保护性测试通过。
- 不允许因拼写、导入或夹具错误而进入 ERROR；若出现 ERROR，先修正测试并重新运行，直到得到上述 RED 结果。

### 任务 2：实现最小 WikiLink 解析修复

**文件：**

- 修改：`scripts/obsidian_wiki_doctor.py:165-199`
- 修改：`scripts/obsidian_wiki_doctor.py:251-271`
- 测试：`tests/test_obsidian_wiki_doctor.py`

- [ ] **步骤 1：增加 WikiLink 专用候选路径和文件名索引**

在 `resolve_markdown_link` 后、`resolve_wikilink` 前加入：

```python
def wikilink_candidate_paths(base: Path) -> list[Path]:
    candidates = [base]
    if not base.name.lower().endswith(".md"):
        candidates.append(Path(f"{base}.md"))
    candidates.append(base / "index.md")
    return candidates


def resolve_wikilink_base(base: Path) -> Path:
    candidates = wikilink_candidate_paths(base.resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def build_markdown_name_index(root: Path | None) -> dict[str, tuple[Path, ...]]:
    if root is None or not root.is_dir():
        return {}
    grouped: dict[str, list[Path]] = {}
    for path in iter_markdown_files(root):
        grouped.setdefault(path.name.casefold(), []).append(path.resolve())
    return {name: tuple(sorted(paths)) for name, paths in grouped.items()}
```

该辅助逻辑只服务 WikiLink；`resolve_link_candidate` 和 `resolve_markdown_link` 保持不变。

- [ ] **步骤 2：替换 `resolve_wikilink` 实现**

用以下实现替换现有函数：

```python
def resolve_wikilink(
    source: Path,
    target: str,
    vault_root: Path | None = None,
    wiki_root: Path | None = None,
    basename_index: dict[str, tuple[Path, ...]] | None = None,
) -> Path | None:
    link_target = obsidian_link_target(target)
    if not link_target or link_target.startswith("#"):
        return None
    if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", link_target) or link_target.startswith("//"):
        return None

    normalized_target = link_target.replace("\\", "/")
    target_path = Path(normalized_target)
    explicit_relative = normalized_target.startswith("./") or normalized_target.startswith("../")
    has_directory = "/" in normalized_target

    if explicit_relative:
        return resolve_wikilink_base(source.parent / target_path)

    if has_directory:
        roots: list[Path] = []
        for root in (vault_root, wiki_root):
            if root is not None and root not in roots:
                roots.append(root)
        unresolved: Path | None = None
        for root in roots:
            candidate = resolve_wikilink_base(root / target_path)
            if candidate.exists():
                return candidate
            if unresolved is None:
                unresolved = candidate
        return unresolved or resolve_wikilink_base(source.parent / target_path)

    source_candidate = resolve_wikilink_base(source.parent / target_path)
    if source_candidate.exists():
        return source_candidate

    expected_name = target_path.name
    if not expected_name.lower().endswith(".md"):
        expected_name = f"{expected_name}.md"
    lookup = basename_index if basename_index is not None else build_markdown_name_index(vault_root or wiki_root)
    matches = lookup.get(expected_name.casefold(), ())
    if len(matches) == 1:
        return matches[0]
    return source_candidate
```

- [ ] **步骤 3：在 `check_links` 中每次检查只构建一次索引**

把 `check_links` 的开头和 WikiLink 解析调用调整为：

```python
def check_links(root: ResolvedRoot) -> list[Finding]:
    if root.wiki_root is None:
        return []

    basename_index = build_markdown_name_index(root.vault_root or root.wiki_root)
    findings: list[Finding] = []
    for markdown_file in iter_markdown_files(root.wiki_root):
        text = read_text(markdown_file)
        link_targets = [(match.group(1), resolve_markdown_link(markdown_file, match.group(1))) for match in MARKDOWN_LINK_RE.finditer(text)]
        link_targets.extend(
            (
                match.group(1),
                resolve_wikilink(
                    markdown_file,
                    match.group(1),
                    vault_root=root.vault_root,
                    wiki_root=root.wiki_root,
                    basename_index=basename_index,
                ),
            )
            for match in WIKILINK_RE.finditer(text)
        )
```

保留现有 `for target, resolved in link_targets:` 及后续 finding 生成代码不变。

- [ ] **步骤 4：运行六个定向测试并确认 GREEN**

重复任务 1 步骤 3 的命令。

预期：`Ran 6 tests`，`OK`。

- [ ] **步骤 5：运行全部 Doctor 测试**

运行：

```powershell
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_obsidian_wiki_doctor -v
```

预期：Doctor 测试全部通过，无失败和错误。

- [ ] **步骤 6：提交解析器和回归测试**

```powershell
git add -- tests/test_obsidian_wiki_doctor.py scripts/obsidian_wiki_doctor.py
git commit -m "fix: resolve Obsidian WikiLinks with Vault semantics"
```

### 任务 3：完整验证并同步 Bug Brief

**文件：**

- 修改：`.llm-wiki/bugs/2026-07-11-obsidian-wikilink-resolution.md`
- 验证：`tests/`、当前真实 Vault

- [ ] **步骤 1：运行完整测试套件**

```powershell
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

预期：`Ran 56 tests`，`OK`。

- [ ] **步骤 2：使用源码 Runtime 验证当前真实 Vault**

```powershell
$env:PYTHONUTF8='1'
if (-not $env:OBSIDIAN_LLM_WIKI_ROOT) {
  throw 'Set OBSIDIAN_LLM_WIKI_ROOT to the absolute Vault path before verification.'
}
$raw = & 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  'scripts\llm_wiki.py' doctor validate `
  --root $env:OBSIDIAN_LLM_WIKI_ROOT `
  --format json --fail-on error | Out-String
$doctorExit = $LASTEXITCODE
$items = $raw | ConvertFrom-Json
[ordered]@{
  doctor_exit = $doctorExit
  checks = @(
    $items | Group-Object check | Sort-Object Count -Descending | ForEach-Object {
      [ordered]@{ name = $_.Name; count = $_.Count }
    }
  )
} | ConvertTo-Json -Depth 4
```

预期：

- 不出现 `broken-index-link` 或 `broken-internal-link`。
- `doctor_exit` 仍可为 `1`，但只能由当前明确排除的 `sensitive-pattern` ERROR 导致。
- 不在聊天或 Bug Brief 中复制任何敏感匹配值。

- [ ] **步骤 3：验证评分和非目标行为未漂移**

```powershell
$env:PYTHONUTF8='1'
if (-not $env:OBSIDIAN_LLM_WIKI_ROOT) {
  throw 'Set OBSIDIAN_LLM_WIKI_ROOT to the absolute Vault path before verification.'
}
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  'scripts\llm_wiki.py' doctor score `
  --root $env:OBSIDIAN_LLM_WIKI_ROOT `
  --format json
```

预期：当前 Vault 评分仍为 `80`、级别仍为 `usable`；导航维度保持 `25/25`，敏感卫生维度保持 `0/20`。

- [ ] **步骤 4：更新 Bug Brief 的状态与验证证据**

在 `.llm-wiki/bugs/2026-07-11-obsidian-wikilink-resolution.md` 中进行以下精确更新：

```markdown
- status: verified
- next_gate: project-finish sync and review

## Verification

- status: passed
- commands_or_checks: six targeted WikiLink tests; full unittest discovery; source-tree Doctor validation and score against the current Vault
- result_summary: All 56 tests passed. Covered WikiLink structural findings are absent from the real Vault report; remaining Doctor failure is limited to the explicitly excluded sensitive-pattern findings.
- limitation: The installed skill cache is not updated by this source commit; deployment or reinstall is a separate action.
- residual_risk: Obsidian syntax outside the approved scope remains unchanged; ambiguous duplicate basenames intentionally remain unresolved.
```

把 Flow Record 更新为：

```markdown
| source | done | User report and real Vault Doctor output | 2026-07-11 |
| design | done | Approved Chinese resolver design | 2026-07-11 |
| plan | done | `docs/superpowers/plans/2026-07-11-obsidian-wikilink-resolution-implementation-plan.md` | 2026-07-11 |
| development | done | Resolver and regression-test commit | 2026-07-11 |
| testing | done | 56 tests and real Vault source-runtime verification | 2026-07-11 |
| archive | pending | Awaiting project-finish |  |
```

- [ ] **步骤 5：提交 Bug Brief 验证同步**

```powershell
git add -- '.llm-wiki/bugs/2026-07-11-obsidian-wikilink-resolution.md'
git commit -m "docs: record WikiLink resolver verification"
```

## 计划完成检查

- [ ] 设计中的 Vault 根路径、显式相对路径、带点文件名、Vault 全局 basename、重名歧义和真实缺失均有对应测试。
- [ ] Markdown 链接解析器没有修改。
- [ ] Vault 文件名索引每次 Doctor 检查只构建一次。
- [ ] 不涉及 Vault 自动发现、敏感脱敏、评分权重或 Maintain 写入逻辑。
- [ ] 没有新增依赖。
- [ ] 完整测试与真实 Vault 验证均有明确命令和预期结果。
