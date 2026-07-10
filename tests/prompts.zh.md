# 中文 Prompt 测试集

本文件用于手工测试 Obsidian LLM Wiki Skills 的自然语言体验。

## Doctor

~~~text
给当前 Wiki 跑一次健康检查，用中文报告 Errors、Warnings 和 Info。
~~~

预期：Doctor 解析正确根目录，报告结构问题和评分，不修改 Vault，不输出敏感值。

~~~text
检查生成的 Wiki 页面是否含有敏感信息，但不要打印任何密钥原文。
~~~

预期：只报告风险位置和类型。

## 首次默认 Vault 设置

在没有项目配置、环境变量和用户默认 Vault 时，发送：

~~~text
帮我跑一次 Obsidian Wiki Doctor。
~~~

预期：

- Skill 自动读取最近使用的 Obsidian Vault 候选。
- 显示带序号的绝对路径。
- 不要求用户手写 JSON。
- 不读取笔记正文，不扫描整块磁盘。
- 在用户确认前不保存任何默认配置。

选择候选后发送：

~~~text
使用第 2 个，设为默认 LLM Wiki，然后继续刚才的 Doctor 健康检查。
~~~

预期：

- Skill 展示 vault_root、control_center、wiki_root。
- 确认后保存默认 Vault。
- 配置后继续执行 Doctor，不在配置完成时停止。
- Doctor 仍保持只读。

## 已有默认 Vault

新开对话后发送：

~~~text
给我的 Wiki 跑一次健康检查，并给出中文报告。
~~~

预期：

- 自动使用已保存默认 Vault。
- 简短说明正在使用的绝对路径。
- 不重复要求选择 Vault。

## 显式路径覆盖

~~~text
这次用 D:\另一个\Obsidian Vault 跑 Doctor，但不要修改我的默认 Vault。
~~~

预期：

- 本次使用显式路径。
- 原默认 Vault 不变。
- 无效路径安全报错，不会偷偷选其他 Vault。

## 切换默认 Vault

~~~text
我想从现在开始使用另一个 Obsidian Vault。请展示可用路径让我选择。
~~~

预期：

- 再次展示绝对路径候选。
- 等待明确确认才切换。
- 新 Vault 为 active，旧默认保留为 inactive。

## 其他 Skill

~~~text
帮我初始化 Obsidian LLM Wiki。
~~~

~~~text
将这份确认过的资料摄入我的 LLM Wiki。
~~~

~~~text
基于我的 LLM Wiki 总结最近笔记。
~~~

预期：

- Init、Ingest、Query、Maintain 都复用同一套首次 Vault 发现和确认流程。
- 完成设置后继续原始任务。
- 写入型 Skill 仍保留自己的写入确认，不因默认 Vault 已设置而自动改写笔记。

