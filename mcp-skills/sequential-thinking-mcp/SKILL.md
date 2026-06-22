---
name: sequential-thinking-mcp
description: Use the Sequential Thinking MCP integration to structured step-by-step reasoning helper. Activate when the user wants to structured step-by-step reasoning helper via Sequential Thinking, including discovering the right tool, building parameters, and handling results.
icon: plug
color: Blue
---

# Sequential Thinking MCP Integration

## Overview
This skill covers working with the **Sequential Thinking** integration over the Model Context Protocol (MCP) to structured step-by-step reasoning helper.

## When to use this skill
Activate when the user wants to structured step-by-step reasoning helper using Sequential Thinking, or asks to connect, automate, or query Sequential Thinking.

## Workflow
1. **Discover** the available Sequential Thinking tools via tool discovery before calling anything — never assume a tool exists.
2. **Resolve identifiers** (IDs, names, URLs) the target tool requires; fetch current state before mutating.
3. **Build parameters** strictly from the tool's input schema (include all required fields).
4. **Execute** the tool and validate the result `status` before using the data.
5. **Handle errors** by reading the message and adjusting inputs — do not blindly retry.

## Usage pattern (sandbox)
```python
from gumloop import Gumloop
client = Gumloop()
res = client.mcp.execute("sequential-thinking", "<tool_name>", { }).results[0]
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
