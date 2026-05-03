---
name: using-split-file-python
description: When user asks to split a python module in Python, use split_file
type: skill
---

# Scalpel - split_file (Python)

Split a Python module

## When to use

Invoke `split_file` (language: **python**) when the user says any of:

- "split module"

> v2.0 wire-name cleanup: the legacy alias `scalpel_split_file` continues to
> work through v2.x and is removed in v2.1. Prefer the unprefixed name in
> new prompts.

## How it works

The facade composes the following LSP primitives in order:

1. `textDocument/codeAction`

## Tool call

```json
{"tool": "split_file", "arguments": {"path": "<file>", "language": "python"}}
```
