---
name: gumloop-sdk
description: Call MCP integration tools (Slack, Gmail, Google Sheets, etc.) from the sandbox for CUSTOM PROCESSING — batch several at once, chain calls with custom logic, transform/branch on results, or read server resources and prompts. For discovery and simple one-off calls, use the top-level tools (tool_discovery / tool_executor), not the sandbox.
---

# MCP Tools (Gumloop CLI & SDK)

The `gumloop` CLI and SDK are **already installed** in the sandbox — never pip
install them. Credentials are already in the env (`GUMLOOP_ACCESS_TOKEN`,
`GUMLOOP_BASE_URL`), so both work with no setup.

**Use the sandbox only for custom processing. Simple one-off calls and discovery go through the top-level tools (tool_discovery / tool_executor), NOT the sandbox.** The user sees top-level tool calls as discrete, captioned steps they can follow and verify; integration calls buried in sandbox code are opaque and hard for them to understand, so default to the observable path.
- **SDK** (in `sandbox_python`) — write + run a script. Use to transform, branch on, chain, batch, or combine results in code.
- **CLI** — same backend, no code to write; for use inside a script. Narrow discovery fallback only: if a server in <servers> returns no tools from tool_discovery (e.g. a newly deployed gumstack/custom server still indexing), `gumloop mcp tools <server_id>` can introspect that one server.

## CLI

```bash
gumloop mcp tools <server_id>    # tools on a server
gumloop mcp call <server_id> <tool> --args-json '{"max_results": 5}'
gumloop mcp call <server_id> <tool> --args-file ./args.json
gumloop mcp call <server_id> <tool> --json   # JSON output (text content decoded)
```

## SDK

```python
from gumloop import Gumloop

client = Gumloop()   # base URL + token from env; project resolved from the token

resp = client.mcp.execute("<server_id>", "<tool>", {"max_results": 5})
result = resp.results[0]
if result.status != "success":
    raise RuntimeError(result.error)
data = result.decoded_content   # JSON content already parsed (list of dicts)

client.mcp.list_tools("<server_id>")   # tools on a server
```

## Chain & batch

Chain calls with logic in between — the main reason to reach for the SDK over the CLI:
```python
items = client.mcp.execute("<server_id>", "<tool>", {"max_limit": 50}).results[0].decoded_content
flagged = [i for i in items if i.get("priority") == 1]
for item in flagged:
    client.mcp.execute("<other_server_id>", "<tool>", {"text": item["title"]})
```

Batch independent calls into one request — run concurrently server-side, max 5:
```python
resp = client.mcp.execute_many([
    {"server_id": "<server_id>", "tool_name": "<tool>", "arguments": {"max_results": 5}},
    {"server_id": "<other_server_id>", "tool_name": "<tool>", "arguments": {}},
])
first = resp.results[0].decoded_content
second = resp.results[1].decoded_content
```

## Resources & prompts

Some servers expose readable resources and prompt templates — both per-server, and empty if the server doesn't support them.
```bash
gumloop mcp resources <server_id>                # list resources
gumloop mcp resource <server_id> <resource_uri>  # read one by URI
gumloop mcp prompts <server_id>                  # list prompt templates
gumloop mcp prompt <server_id> <prompt> --args-json '{"key": "value"}'
```
```python
resources = client.mcp.list_resources("<server_id>").resources
contents = client.mcp.get_resource("<server_id>", "<resource_uri>").contents
prompts = client.mcp.list_prompts("<server_id>").prompts
prompt = client.mcp.get_prompt("<server_id>", "<prompt>", {"key": "value"})
```

## Notes

- Call servers by their `server_id` (listed in your `<gumcp_servers>` context), passed separately from `tool_name` (not a `server__tool` slug).
- Tool responses vary in shape — inspect one result before writing batch logic.
