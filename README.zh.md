# Obsidian LLM Wiki

[![test](https://github.com/huajiexiewenfeng/obsidian-llm-wiki/actions/workflows/test.yml/badge.svg)](https://github.com/huajiexiewenfeng/obsidian-llm-wiki/actions/workflows/test.yml)

用于 Obsidian 的 AI 辅助 LLM Wiki skills：整理已有 vault、摄入外部资料、诊断知识库结构、执行已确认修复，并基于个人知识库回答问题。

[English](./README.md) | 简体中文

## 这是什么？

Obsidian LLM Wiki 是一套工作流和 skills，用来把已有的 Obsidian Vault 逐步整理成更安全、更结构化、更适合 AI 读取的知识库。

它不是 Obsidian 插件，而是一组 Codex/agent skills 和流程文档。目标是让 AI 助手以可控方式处理你的 vault：

```text
初始化 -> 摄入 -> Doctor 诊断 -> Maintain 修复 -> 查询
```

这个项目的目标不是把所有文件都倒进 Obsidian，而是在真实笔记、项目资料和外部目录之上，建立一层稳定、可见、可查询的知识结构。

## 为什么需要它？

真实的个人知识库通常并不干净：

- 60% 以上的有用资料可能已经在 Obsidian 里。
- 其余资料可能散落在 Downloads、项目目录、会议导出、PDF、Word、Excel 和代码仓库中。
- 有些文件适合保留外部路径引用，不适合复制进 vault。
- 有些文件包含密钥、内网地址、凭据、客户信息或生产日志。

Obsidian LLM Wiki 就是为这种现实情况设计的。

它先做盘点和确认，再把选定资料沉淀成 topic、source、project、entity、SOP、checklist 等 wiki 页面。

## 核心架构

第一版包含 5 个 skills：

| Skill | 使用场景 |
|---|---|
| `obsidian-wiki-init` | 初始化或接管 Obsidian Vault，创建知识库中控、盘点 vault、建立规则，并生成建设路线图 |
| `obsidian-wiki-ingest` | 整理已有 vault 目录，或将外部文件/目录摄入成 wiki 页面 |
| `obsidian-wiki-doctor` | 只读诊断、校验、评分并生成报告，判断 wiki 结构和成熟度 |
| `obsidian-wiki-maintain` | 根据 doctor 报告执行已确认的窄范围修复，例如 index、链接、log 或 source proxy 更新 |
| `obsidian-wiki-query` | 基于 wiki 回答问题、总结资料、生成大纲，并建议保存长期有价值的页面 |

5 个 skill 按用户意图拆分：

```text
init      = 准备 vault
ingest    = 把资料变成 wiki 页面
doctor    = 诊断、校验、评分和报告
maintain  = 执行已确认的结构修复
query     = 基于 wiki 回答和沉淀
```

## 外部资料摄入

外部目录默认谨慎处理。

默认模式是路径索引：

```text
扫描外部路径
-> 按主题、类型、风险和价值分类
-> 生成摄入计划
-> 等待用户确认
-> 只处理确认过的资料
```

支持 3 种模式：

| 模式 | 行为 | 是否复制文件进 vault |
|---|---|---|
| 路径索引 | 记录文件在哪里，并创建可进入图谱的 source 代理节点和链接关系 | 否 |
| 摘要摄入 | 读取确认过的内容，生成 source/topic/project 页面 | 可选 |
| 归档导入 | 将确认过的文件复制到 `raw/`，再处理 | 是 |

外部文件默认不会复制进 `raw/`。

路径索引仍然是 Obsidian 图谱操作：

- 写入前必须先定位当前激活的 Obsidian 知识库中控，不能只写到当前 shell / 项目工作区。
- `ingest/index.md` 记录摄入批次、原始路径、wiki 入口、处理状态和缺口。
- `sources/<name>.md` 是外部文档或文档组在 Obsidian 里的 source 代理节点。
- `index.md`、topic、project、entity、SOP 页面要链接到这些代理节点，使其能出现在关系图谱里，并能被 query workflow 找到。

## 安全模型

所有 skills 都遵守同一套安全策略：

- 不删除或移动用户文件。
- 未明确要求时，不改写原始笔记。
- 默认不把外部文件复制进 vault。
- 不把 API Key、Token、密码、AK/SK、Cookie、私钥、证书、RTSP 凭据、内网地址、客户数据或生产日志复制到生成的 wiki 页面。
- 可疑文件先作为路径级引用处理。
- 深度读取 PDF、Word、Excel、压缩包或疑似敏感目录前，必须先确认。

生成的 wiki 页面应该保存知识结构，而不是保存秘密原值。

## 安装

使用 Skills CLI 安装：

```bash
npx skills add huajiexiewenfeng/obsidian-llm-wiki
```

本地开发时，在仓库根目录运行：

```bash
npx skills add .
```

安装后，重启 Codex 或你的 agent runtime，让 skills 重新被发现。

### 根目录配置

运行环境要求 Python 3.10 或更新版本。当没有显式传入 Vault 时，在工作项目中创建
`.obsidian-llm-wiki.json`：

```json
{
  "schema_version": 1,
  "vault_root": "D:/notes/My Vault",
  "control_center": "00-知识库中控",
  "active": true
}
```

只解析、不写入：

```text
python scripts/llm_wiki.py root resolve --cwd . --format json
```

解析顺序为显式路径、最近的项目配置、环境变量、再到唯一激活的用户配置 Vault；工具不会扫描整块磁盘。

## 使用示例

### 首次设置 Vault

不需要先手工创建 JSON 配置。未配置 Wiki 时，Skill 会读取 Obsidian 最近使用的 Vault 元数据，展示已有的绝对路径并请你选择；确认后在后台保存为默认 Vault，再继续原请求。发现过程不读取笔记，也不扫描整块磁盘。

自然表达即可：

```text
初始化当前 Obsidian Vault，创建 LLM Wiki 中控结构。
```

```text
我的 Obsidian vault 已经有很多目录，初始化后请一步一步引导我，并推荐第一批整理范围。
```

```text
只扫描目录结构和文件类型，不读取正文。
```

```text
扫描 D:\资料 和 D:\Downloads，生成摄入计划，先不要复制文件。
```

```text
把这个确认过的 PDF 摘要摄入知识库，并更新相关主题页或项目页。
```

```text
对当前 wiki 运行 Obsidian Wiki Doctor，输出 Errors、Warnings、not-applicable 维度和评分。
```

```text
基于当前 wiki，总结视频流低延迟问题的排查路径。
```

也可以指定 skill：

```text
使用 obsidian-wiki-ingest，以路径索引模式扫描这些外部目录。
```

```text
使用 obsidian-wiki-query，基于我的 Obsidian wiki 回答这个问题。
```

## 如何判断它在正常工作？

Obsidian LLM Wiki 正常工作时，应该表现为：

- 已有笔记不会在未确认时被移动或改写。
- 外部目录会先扫描和规划，再决定是否复制或摘要。
- 生成的 wiki 页面不会泄露敏感原值。
- `index.md` 成为 wiki 的主导航入口。
- `ingest/index.md` 成为摄入控制台索引。
- source 代理页面能说明资料来自哪里、如何被处理。
- topic、project、entity、SOP 页面比散落原始笔记更容易查询。
- Doctor 报告能输出明确的 Errors、Warnings、not-applicable 维度和评分。
- Maintain 只执行来自确认 findings 的已批准修复。
- query 回答会引用 wiki 页面，并说明证据不足的地方。

## 项目结构

```text
skills/
  obsidian-wiki-init/
  obsidian-wiki-ingest/
  obsidian-wiki-maintain/
  obsidian-wiki-doctor/
  obsidian-wiki-query/

docs/
  architecture.md
  workflow.md
  safety.md
  development-plan.md

scripts/
  obsidian_wiki_doctor.py

tests/
  prompts.md
```

## 文档

- [Architecture](docs/architecture.md)
- [Workflow](docs/workflow.md)
- [Safety](docs/safety.md)
- [Development Plan](docs/development-plan.md)
- [Test Prompts](tests/prompts.md)

## 当前状态

项目目前处于早期文档型 MVP 阶段。

当前重点是先把 skill 边界、工作流、输出格式和安全规则写清楚。Doctor 脚本是第一批确定性的校验与评分能力；更多确定性辅助脚本会在手工流程稳定后再加入。

## License

MIT
