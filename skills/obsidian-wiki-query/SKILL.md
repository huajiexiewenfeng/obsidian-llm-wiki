---
name: obsidian-wiki-query
description: Use this whenever the user asks questions that should be answered from an Obsidian LLM Wiki or personal knowledge base. Trigger on requests like "基于当前 wiki 回答", "according to my knowledge base", "从 Obsidian 里找", "summarize from my wiki", "generate an outline from my knowledge base", or "what do my notes say about...". This skill reads wiki pages first and only falls back to raw/source material when needed.
---

# Obsidian Wiki Query

Answer questions from the Obsidian LLM Wiki.

## When To Use

Use this skill when the user wants to:

- answer a question from the knowledge base
- summarize a topic or project from wiki pages
- generate a plan, outline, checklist, or explanation from existing wiki knowledge
- locate relevant pages in the wiki
- save a durable synthesis after answering

Do not use this skill for health checks. Use `obsidian-wiki-maintain`.

## Reading Order

Follow `references/query-workflow.md`.

Default order:

```text
index.md
  -> relevant topic/project/entity/SOP/source pages
  -> original source material only when necessary
```

## Answer Rules

Use `references/answer-format.md`.

- Cite or name the wiki pages used.
- State when evidence is insufficient.
- Do not expose sensitive information.
- Separate sourced knowledge from inference.
- Suggest durable page creation when the answer has long-term value.

## Optional Save-Back

Use `references/synthesis-rules.md` when saving durable answers.

Ask before creating or updating wiki pages unless the user explicitly requested saving.

## Examples

Input:

```text
Based on the current wiki, summarize the video stream low-latency troubleshooting path.
```

Expected behavior:

```text
Read index and related topic/SOP/entity pages, then answer with page references and clear gaps.
```

Input:

```text
Use my knowledge base to generate a team AI productivity talk outline.
```

Expected behavior:

```text
Use relevant AI learning and productivity pages to generate an outline and suggest saving it as a project or article-outline page.
```
