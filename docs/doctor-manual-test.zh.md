# Obsidian Wiki Doctor：中文人工验收手册

适用版本：当前 main。目标是验证 Doctor 的根目录解析、只读性、新旧入口兼容和错误诊断。

## 准备

~~~powershell
$python = 'C:\tmp\python-3.12.10-embed-amd64\python.exe'
$repo = 'C:\Users\admin\Documents\New project 2\obsidian-llm-wiki'
Set-Location $repo
$tempRoot = Join-Path $env:TEMP 'obsidian-llm-wiki-doctor-manual-test'
Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
$vault = Join-Path $tempRoot 'Sample Vault'
$control = Join-Path $vault '00-知识库中控'
$wiki = Join-Path $control 'wiki'
New-Item -ItemType Directory -Force -Path $wiki | Out-Null
Set-Content -Encoding utf8 -Path (Join-Path $wiki 'index.md') -Value "# Index"
Set-Content -Encoding utf8 -Path (Join-Path $wiki 'log.md') -Value "# Log"
~~~

## 1. 显式根目录与报告

~~~powershell
& $python scripts/llm_wiki.py root resolve --root $vault --format json
& $python scripts/llm_wiki.py doctor report --root $vault --format json
~~~

预期：Root Resolver 的 source 为 argument；报告包含 root、state、findings、score。

## 2. Doctor 只读

~~~powershell
$before = Get-ChildItem -LiteralPath $vault -Recurse -File | ForEach-Object {
  [pscustomobject]@{
    FullName = $_.FullName
    Length = $_.Length
    LastWriteTimeUtc = $_.LastWriteTimeUtc
    SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
  }
} | ConvertTo-Json
& $python scripts/llm_wiki.py doctor validate --root $vault --format json --fail-on error
& $python scripts/llm_wiki.py doctor score --root $vault --format json
& $python scripts/llm_wiki.py doctor report --root $vault --format text
$after = Get-ChildItem -LiteralPath $vault -Recurse -File | ForEach-Object {
  [pscustomobject]@{
    FullName = $_.FullName
    Length = $_.Length
    LastWriteTimeUtc = $_.LastWriteTimeUtc
    SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
  }
} | ConvertTo-Json
$before -eq $after
~~~

预期：最后一行是 True。若 `.meta/lock.json` 存在，它也必须出现在前后快照中且完全不变。Doctor 不新增、不删除、不修改 Vault 文件，也不获取写锁。

## 3. 新旧入口等价

~~~powershell
$new = & $python scripts/llm_wiki.py doctor report --root $vault --format json
$old = & $python scripts/obsidian_wiki_doctor.py report --root $vault --format json
$new -eq $old
~~~

预期：最后一行是 True。

## 4. 项目配置自动解析

~~~powershell
$project = Join-Path $tempRoot 'sample-project'
New-Item -ItemType Directory -Force -Path $project | Out-Null
@"
{
  "schema_version": 1,
  "vault_root": "$($vault.Replace('\', '\\'))",
  "control_center": "00-知识库中控",
  "active": true
}
"@ | Set-Content -Encoding utf8 -Path (Join-Path $project '.obsidian-llm-wiki.json')
Push-Location $project
& $python "$repo\scripts\llm_wiki.py" doctor score --format json
Pop-Location
~~~

预期：root.source 为 project-config。

## 5. 环境变量兜底

~~~powershell
$env:OBSIDIAN_LLM_WIKI_ROOT = $vault
& $python scripts/llm_wiki.py doctor report --format json
Remove-Item Env:OBSIDIAN_LLM_WIKI_ROOT
~~~

预期：root.source 为 environment。

## 6. 无效路径安全失败

~~~powershell
$invalid = Join-Path $tempRoot 'does-not-exist'
& $python scripts/llm_wiki.py doctor validate --root $invalid --format json --fail-on error
$LASTEXITCODE
~~~

预期：出现 invalid-root Error，退出码为 1；不扫描磁盘、不写文件。

## 7. 断链诊断

~~~powershell
Set-Content -Encoding utf8 -Path (Join-Path $wiki 'index.md') -Value ("# Index" + [Environment]::NewLine + [Environment]::NewLine + "- [Missing](topics/missing.md)")
& $python scripts/llm_wiki.py doctor validate --root $vault --format json --fail-on error
Set-Content -Encoding utf8 -Path (Join-Path $wiki 'index.md') -Value "# Index"
~~~

预期：出现 broken-index-link Error，退出码为 1；Doctor 只报告，不自动修复。

## 8. Phase 4 状态一致性故障注入

在临时 Vault 先通过 `state init` 和一次测试 ingest 生成 Phase 3 状态，再分别复制一份 fixture 验证：

1. 在 `change-log.jsonl` 末尾追加无换行的半条 JSON：预期 `torn-change-log-tail` WARN，合法前缀生成的 `wiki/log.md` 仍可比较。
2. 在中间插入非法 JSON 行：预期 `invalid-state-file` ERROR，跳过 event-dependent checks。
3. 修改 `wiki/index.md` projection marker 内正文：预期 `projection-drift` WARN；Doctor 不自动 rebuild。
4. 写入其他 host 的合法 `.meta/lock.json` 并保留匹配的 running operation：预期仅 `cross-host-lock` WARN，不误报 orphan。
5. 留下 `.pages.json.<random>.tmp`：预期 `orphan-temp-file` WARN，Doctor 不读取正文、不删除文件。

每次运行后重复第 2 节快照比较，确认包括 `.meta/lock.json` 在内的所有文件未变化。

## 9. 真实 Vault 只读试跑

~~~powershell
$realVault = 'C:\Users\<user>\Documents\Obsidian Vault'
& $python scripts/llm_wiki.py root resolve --root $realVault --format json
& $python scripts/llm_wiki.py doctor report --root $realVault --format text
~~~

先核对根目录正确，再决定是否让 Maintain Skill 修复。Doctor 本身不会修改真实 Vault。

## 清理

~~~powershell
Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
~~~

