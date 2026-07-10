# 默认 Vault 发现与保存：人工验收手册

适用版本：包含 \`root discover\` 与 \`root configure\` 的当前 main。

## 准备

1. 打开仓库根目录。
2. 使用 Python 3.10 或更高版本。
3. 测试过程中请使用临时目录保存用户配置，避免修改你真实的默认配置。

PowerShell 示例：

~~~powershell
$python = 'C:\tmp\python-3.12.10-embed-amd64\python.exe'
$repo = 'C:\Users\admin\Documents\New project 2\obsidian-llm-wiki'
Set-Location $repo
~~~

## 0. 回归测试

运行：

~~~powershell
& $python -m unittest discover tests -v
~~~

预期：所有测试通过。

## 1. 发现最近使用的 Obsidian Vault

运行：

~~~powershell
& $python scripts/llm_wiki.py root discover --format json
~~~

预期：

- 命令退出码为 0。
- 输出包含 \`candidates\`、\`source\`、\`status\`。
- 候选项是绝对路径，不包含笔记正文。
- 没有可访问的 Obsidian 元数据时，允许返回空数组；不应扫描整块磁盘。

如果返回候选路径，请记下一个真实 Vault 根目录，例如：

~~~text
C:\Users\<user>\Documents\Obsidian Vault
~~~

## 2. 用真实路径验证根目录解析

将下方路径替换为你在第 1 步看到的 Vault 根目录：

~~~powershell
$vault = 'C:\Users\<user>\Documents\Obsidian Vault'
& $python scripts/llm_wiki.py root resolve --root $vault --format json
~~~

预期：

- \`source\` 为 \`argument\`。
- \`vault_root\` 是你提供的 Vault。
- \`control_center\` 指向 \`00-知识库中控\`。
- \`wiki_root\` 指向 \`00-知识库中控\wiki\`。
- 此命令只读，不写文件。

如果该 Vault 尚未初始化，没有控制中心时会返回 \`invalid-root\`；请先用 Init Skill 初始化，或选择一个已有 LLM Wiki 控制中心的 Vault。

## 3. 预览默认 Vault 设置：确认不会写入

使用临时配置路径：

~~~powershell
$tempConfig = Join-Path $env:TEMP 'obsidian-llm-wiki-manual-test\config.json'
Remove-Item -LiteralPath $tempConfig -Force -ErrorAction SilentlyContinue
& $python scripts/llm_wiki.py root configure --root $vault --activate --user-config $tempConfig --format json
Test-Path -LiteralPath $tempConfig
~~~

预期：

- 命令退出码为 1。
- JSON 中 \`confirmation_required\` 为 \`true\`。
- JSON 中 \`configured\` 为 \`false\`。
- 最后一行输出 \`False\`，说明未写入配置。

## 4. 确认后保存默认 Vault

运行：

~~~powershell
& $python scripts/llm_wiki.py root configure --root $vault --activate --confirm --user-config $tempConfig --format json
Get-Content -LiteralPath $tempConfig -Raw -Encoding UTF8
~~~

预期：

- 命令退出码为 0。
- JSON 中 \`configured\` 为 \`true\`。
- 临时配置含有一个 \`active: true\` 的 Vault。
- 配置中的 \`vault_root\`、\`control_center\` 与第 2 步解析结果一致。

## 5. 验证默认 Vault 自动生效

运行：

~~~powershell
& $python scripts/llm_wiki.py root resolve --cwd $PWD --user-config $tempConfig --format json
~~~

预期：

- \`source\` 为 \`user-config\`。
- 返回的 \`vault_root\` 与第 4 步保存的 Vault 一致。
- 不需要再次传入 \`--root\`。

## 6. 验证优先级：显式路径永远优先

准备另一个已初始化的 LLM Wiki Vault，填入 \`$otherVault\`：

~~~powershell
$otherVault = 'D:\another\Obsidian Vault'
& $python scripts/llm_wiki.py root resolve --root $otherVault --user-config $tempConfig --format json
~~~

预期：

- \`source\` 为 \`argument\`。
- 返回 \`$otherVault\`，而不是第 4 步的默认 Vault。
- 这证明默认 Vault 不会覆盖用户当次明确指定的路径。

## 7. 切换默认 Vault

确认 \`$otherVault\` 是一个有效 LLM Wiki Vault 后运行：

~~~powershell
& $python scripts/llm_wiki.py root configure --root $otherVault --activate --confirm --user-config $tempConfig --format json
Get-Content -LiteralPath $tempConfig -Raw -Encoding UTF8
~~~

预期：

- 新 Vault 的 \`active\` 为 \`true\`。
- 原 Vault 记录仍保留，但 \`active\` 为 \`false\`。
- 配置中不会同时有两个 \`active: true\`。

## 8. 异常场景

### 无效路径

~~~powershell
& $python scripts/llm_wiki.py root configure --root 'C:\does-not-exist' --activate --confirm --user-config $tempConfig --format json
~~~

预期：退出码为 2；原有配置不被修改。

### 损坏配置

手工把 \`$tempConfig\` 改为无效 JSON 后再次运行第 4 步命令。

预期：退出码为 2；工具返回 \`invalid-config\`，不会覆盖损坏文件。

## 清理

完成测试后删除临时配置：

~~~powershell
Remove-Item -LiteralPath (Split-Path -Parent $tempConfig) -Recurse -Force -ErrorAction SilentlyContinue
~~~

不要删除真实 Obsidian Vault、真实用户配置或笔记内容。

