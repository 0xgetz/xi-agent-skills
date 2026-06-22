---
name: microsoft-word-mcp
description: Use the Microsoft Word MCP integration to create and edit Word documents. Activate when the user wants to create and edit Word documents via Microsoft Word, including discovering the right tool, building parameters, and handling results.
icon: plug
color: Blue
---

# Microsoft Word MCP Integration

## Overview
This skill covers working with the **Microsoft Word** integration over the Model Context Protocol (MCP) to create and edit Word documents.

## When to use this skill
Activate when the user wants to create and edit Word documents using Microsoft Word, or asks to connect, automate, or query Microsoft Word.

## Workflow
1. **Discover** the available Microsoft Word tools via tool discovery before calling anything — never assume a tool exists.
2. **Resolve identifiers** (IDs, names, URLs) the target tool requires; fetch current state before mutating.
3. **Build parameters** strictly from the tool's input schema (include all required fields).
4. **Execute** the tool and validate the result `status` before using the data.
5. **Handle errors** by reading the message and adjusting inputs — do not blindly retry.

## Usage pattern (sandbox)
```python
from gumloop import Gumloop
client = Gumloop()
res = client.mcp.execute("microsoft-word", "<tool_name>", { }).results[0]
if res.status != "success":
    raise RuntimeError(res.error)
data = res.decoded_content
```

## Safety
- Confirm before destructive or externally visible actions (sends, deletes, posts).
- Never log credentials or secrets.
- Respect rate limits and paginate large result sets.

## Notes
Tool names and schemas vary by deployment. Always rely on live discovery, not assumptions.
