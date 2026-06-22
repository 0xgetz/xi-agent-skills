# Migrating gumcp_client → Gumloop SDK / CLI

`gumcp_client` is deprecated. For new code use the **gumloop-sdk** skill. This maps the
old calls to the SDK and the equivalent CLI so you can port existing/saved scripts.

| Deprecated (`gumcp_client`) | Gumloop SDK | Gumloop CLI |
|---|---|---|
| `c = get_client()` | `from gumloop import Gumloop`<br>`c = Gumloop()` | (env-configured, nothing to set up) |
| `c.call_tool("gmail__read_emails", args)` | `c.mcp.execute("gmail", "read_emails", args)` | `gumloop mcp call gmail read_emails --args-json '{...}'` |
| `c.list_tools()` | `c.mcp.list_tools("gmail")` | `gumloop mcp tools gmail` |
| `c.get_resources()` | `c.mcp.list_resources("gmail")` | `gumloop mcp resources gmail` |
| `c.read_resource(uri)` | `c.mcp.get_resource("gmail", uri)` | `gumloop mcp resource gmail "<uri>"` |
| `c.list_prompts()` | `c.mcp.list_prompts("gmail")` | `gumloop mcp prompts gmail` |
| `c.get_prompt(name, args)` | `c.mcp.get_prompt("gmail", name, args)` | `gumloop mcp prompt gmail <name> --args-json '{...}'` |

Notes:
- Pass `server_id` and `tool_name` separately (`"gmail"`, `"read_emails"`), not a `server__tool` slug. SDK calls are per-server.
- `team_id` comes from the token, don't pass it.
- `execute(...)` returns an `McpExecuteResponse`: use `.results[0]`, check `.status == "success"`, then read `.decoded_content` (JSON already parsed; `.content` is the raw strings).

See the **gumloop-sdk** skill for full usage.
