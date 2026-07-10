# Obsidian LLM Wiki 默认 Vault 配置设计

## 目标

让 Skill 能将用户已确认的 Vault 路径保存为该用户的默认 Obsidian LLM Wiki 目标。之后的 Skill 调用可自动解析此默认目标，既不扫描文件系统，也不会悄悄选择另一个 Vault。

这是 Shared Root Resolver 的一个小型 v0.2 增量，基于已有的用户配置兜底能力实现；不涉及注册表、摄入事务或全盘发现机制。

## 产品决策

用户交互固定为两步：

```text
用户提供候选 Vault 路径
-> 只读解析该路径
-> Skill 展示 vault_root、control_center、wiki_root
-> 人工确认该候选
-> configure 命令将其保存为默认 Vault
```

`root resolve` 始终只读。任何持久化命令都必须显式提供确认标记，因此 Skill 不能仅因探测过一个路径就改变用户默认 Vault。

新确认的 Vault 会成为默认 Vault；原有 Vault 记录仍保留在用户配置中，但将被标记为非激活。用户配置在任意时刻最多只有一个激活 Vault。

## 范围

### 本次包含

- 显式保存用户默认 Vault 的 `root configure` 命令。
- 复用现有 Vault、控制中心与 wiki 根目录分类器。
- 用户级配置的读取、预览、原子更新和校验。
- 所有写入都要求 `--confirm` 安全门。
- Skill 指令：解析候选路径、向用户展示、得到确认后才保存。
- 首次配置、切换默认、无效路径、缺少确认不写入等测试。

### 本次不包含

- 扫描整块磁盘、用户主目录或任意驱动器来寻找 Vault。
- 读取 Obsidian 应用状态或最近打开的 Vault 元数据。
- 自动写入项目级 `.obsidian-llm-wiki.json`。
- 项目级默认目标选择；项目配置仍是更高优先级的显式覆盖。
- 跨机器或云端同步。
- 除单文件原子替换外的多进程锁机制。

## 用户体验

### 用户提供路径后的首次配置

例如用户提供：

```text
C:\Users\admin\Documents\Obsidian Vault
```

Skill 先执行等价的只读命令：

```text
python scripts/llm_wiki.py root resolve --root "C:\Users\admin\Documents\Obsidian Vault" --format json
```

解析器可接受 Vault 根目录、控制中心目录或直接的 `wiki/` 根目录，并将候选规范化为 `vault_root`、`control_center`、`wiki_root`。Skill 展示这三个值并等待用户确认。

确认后，Skill 执行：

```text
python scripts/llm_wiki.py root configure --root "C:\Users\admin\Documents\Obsidian Vault" --activate --confirm --format json
```

命令将规范化后的 Vault 写入用户默认配置。之后只有在显式路径、项目配置和环境变量都未命中时，根目录解析才使用该默认 Vault。

### 不写入的预览

未提供 `--confirm` 时调用 `root configure`，命令只输出 JSON 或文本预览：包括已解析的候选、计划发生的激活状态变化和用户配置文件路径；返回 `confirmation-required`，且绝不写入。

这样用户或 Skill 可以在明确提供 `--confirm` 前检查将要保存的内容。

### 切换默认 Vault

当另一个 Vault 通过 `--activate --confirm` 被确认时：

1. 若它尚未存在则新增；若已存在则按规范化路径更新该记录。
2. 其 `active` 设为 `true`。
3. 所有其他 Vault 记录的 `active` 设为 `false`。
4. 旧记录保留，未来只能通过再次明确确认来切换回去。

命令不会自行在多个 Vault 之间做选择；默认 Vault 只能由用户确认的一条路径建立。

## CLI 契约

### 新命令

```text
python scripts/llm_wiki.py root configure \
  --root <vault-or-control-center-or-wiki> \
  --activate \
  --confirm \
  [--user-config <path>] \
  [--format json|text]
```

参数说明：

- `--root` 必填，并复用 Shared Root Resolver 的显式路径分类器。
- `--activate` 在本增量中必填，避免出现语义不明确的“新增但不激活”记录。
- 任何用户配置写入前都必须有 `--confirm`。
- `--user-config` 可覆盖平台默认路径，主要用于测试或用户自管配置位置。
- `--format` 默认为 `json`，也支持终端用户使用 `text`。

### 结果与退出码

| 结果 | 退出码 | 是否写入 |
|---|---:|---|
| 有效且确认后的激活 | 0 | 是 |
| 未提供 `--confirm` 的有效预览 | 1 | 否 |
| 无效根目录或已有用户配置无效 | 2 | 否 |
| 保存时发生文件系统或权限错误 | 2 | 否，且无完成更新 |

预览结果含有 `confirmation_required: true`、规范化候选、用户配置文件路径和计划激活的 Vault。成功结果除同样的根目录信息外，还包含 `configured: true`。

## 配置模型

沿用已有用户配置格式：

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

保存时写入规范化后的 Vault 根目录，以及相对于 Vault 的控制中心路径。若已有配置不是 schema version 1 对象，或不含 `vaults` 数组，写入器返回错误且不覆盖这份无法识别或已损坏的配置。

记录以规范化 `vault_root` 与 `control_center` 的组合去重。对其他有效字段的更新保留未知顶层字段和未知记录字段，避免覆盖未来版本添加的数据。

## 持久化规则

1. 读取或修改配置前，先解析并校验 `--root`。
2. 若用户配置存在则读取；不存在则从 schema version 1 与空 `vaults` 数组开始。
3. 在内存中完整构造下一份配置。
4. 将 UTF-8 JSON 写入同目录临时文件。
5. 临时文件成功写完后才用 `os.replace` 替换目标文件。
6. 替换前任一步失败时，原始配置保持不变。

这提供了可恢复的单文件更新能力，但不提前引入 v0.2 操作日志和锁系统。

## 配置后的解析优先级

优先级保持不变：

```text
显式 --root
-> 当前目录向上最近的项目 .obsidian-llm-wiki.json
-> OBSIDIAN_LLM_WIKI_ROOT
-> 唯一激活的用户配置 Vault
-> 安全的 missing-config 或 multiple-roots 结果
```

`root configure` 只改变第四级来源，永远不会覆盖项目配置或显式用户请求。

## Skill 规则

五个 Obsidian Wiki Skill 都遵循相同行为：

1. 先只读解析显式路径或已有配置的根目录。
2. 若尚未配置根目录，向用户索取 Vault 路径，而不是扫描磁盘。
3. 展示候选规范化后的 `vault_root`、`control_center`、`wiki_root`。
4. 仅在用户明确确认“设为默认”后持久化。
5. 读取或写入 wiki 内容前说明正在使用的根目录。

`obsidian-wiki-init` 可以接收尚未包含控制中心的新 Vault 路径，但创建控制中心结构前仍须另行确认。其余 Skill 必须要求已有可解析的控制中心或 wiki 根目录。

## 错误处理

- 用户提供的路径无效时返回 `invalid-root`，不写配置。
- 已有用户配置格式错误时返回 `invalid-config`，不尝试修复或覆盖。
- 只有在 `--confirm` 后、原子写入前，才创建缺少的用户配置父目录。
- 权限错误返回目标用户配置文件路径，且目标文件不会处于部分写入状态。
- 配置失败后，命令不会悄悄切换到无关 Vault。

## 验证

单元与 CLI 测试覆盖：

- 提供 Vault 后预览但不写入配置；
- 首次确认激活时创建有效用户配置；
- 切换默认时保留原 Vault 但将其设为非激活；
- 无显式根目录时解析新激活的默认 Vault；
- 无效路径和已有损坏配置不发生写入；
- 更新时保留未知但有效的 JSON 字段；
- 通过可注入文件系统接口验证原子写入失败行为；
- Windows 与 Linux 用户配置路径；
- Skill 和 README 都说明人工确认与禁止全盘扫描。

## 验收标准

- 用户可以提供一个 Vault 路径，并且只确认一次。
- 后续命令在没有更高优先级来源时自动解析该 Vault。
- 切换默认 Vault 时绝不悄悄删除原 Vault 记录。
- 没有命令会扫描任意磁盘来发现 Vault。
- `root resolve` 始终保持只读。
- 未提供 `--confirm` 时绝不写入配置。
