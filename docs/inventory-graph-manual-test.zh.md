# Inventory 主图可达性与孤岛测试

本手册验证四件事：首次基线不制造历史积压、基线后新增文件能被发现、历史孤岛与真正新增不会混淆、Wiki 脱离组件会影响 Doctor 导航分。

## 1. 首次基线预览

先初始化状态层，再预览 Inventory；两步均使用真实 Vault 或测试 Vault 的绝对路径：

```powershell
$python = '<python.exe>'
$runtime = '<skills-root>\obsidian-wiki-runtime\scripts\llm_wiki.py'
$vault = '<vault-root>'

& $python $runtime state init --root $vault --confirm --format json
& $python $runtime inventory initialize --root $vault --format json
```

预期：当前历史文件不会计入 `candidate_count`。`disposition_counts` 会分别展示 `known-existing` 与 `unverified` 数量，供确认前审核。

## 2. 确认基线

复制预览返回的 `plan_checksum`：

```powershell
& $python $runtime inventory initialize --root $vault --confirm --plan-checksum '<sha256>' --format json
```

该命令会创建 `.meta/inventory.json`，因此只应在测试 Vault 或用户明确确认的真实 Vault 中运行。

## 3. 新文件发现

基线确认后新增一个普通 Markdown 文件，再运行：

```powershell
& $python $runtime inventory inspect --root $vault --format json
```

预期：新路径报告 `uningested-source`。原有 `unverified` 历史文件报告 `source-island`，不会被误报成新增文件。

## 4. Wiki 孤岛

在 `wiki/` 下建立两个互相链接、但没有被 `wiki/index.md` 引用的测试页面，然后运行：

```powershell
& $python $runtime doctor validate --root $vault --format json --fail-on none
& $python $runtime doctor score --root $vault --format json
```

预期：两个页面分别产生 `orphan-wiki-page`，并共同产生一个 `detached-wiki-component`；“Navigation and discoverability”降为警告档。删除测试页或把代表页连接到 `wiki/index.md` 后，相关 finding 消失。

Doctor 与 `inventory inspect` 全程只读。图分析不会打开 Inventory 排除范围或敏感范围。
