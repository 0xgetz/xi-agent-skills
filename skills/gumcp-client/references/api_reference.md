# guMCP Client API Reference

## Available Exports

The `gumcp_client` package exports the following:

```python
from gumcp_client import Client          # Synchronous client
from gumcp_client import AsyncClient     # Async client
from gumcp_client import Client, ToolError  # Client + exception for tool call failures
from gumcp_client import encode_cursor   # Cursor utility for paginated resource listing
```

## Client Class

The synchronous client for interacting with guMCP servers. A single client handles routing to all connected integrations via the `server__tool_name` convention.

### Constructor

```python
import os
from gumcp_client import Client

client = Client(
    user_id=os.getenv('GUMCP_USER_ID'),
    gumcp_api_key=os.getenv('GUMCP_ACCESS_TOKEN') or os.getenv('GUMCP_API_KEY'),
    base_url=os.getenv('GUMCP_BASE_URL'),
)
```

### call_tool(tool_name, arguments) -> list[str]

Call a tool and get results as a list of strings. Each string is a JSON-encoded response.
Tools use the `server__tool_name` format. Always parse with `json.loads(raw[0])`:

```python
import json

# server__tool_name format (double underscore)
raw = client.call_tool("slack__send_message", {
    "channel": "#general",
    "text": "Hello!"
})
result = json.loads(raw[0])
# result is now a parsed dict, e.g. {"ok": True}

raw = client.call_tool("gcalendar__create_event", {
    "summary": "Team standup",
    "start_datetime": "2026-02-12 09:00",
    "end_datetime": "2026-02-12 09:30"
})
event = json.loads(raw[0])
```

### list_tools() -> dict

List all available tools across connected integrations. Takes no arguments. Returns a dict with a `"tools"` key:

```python
result = client.list_tools()
# result is a dict:
# {
#     "tools": [
#         {
#             "name": "slack__send_message",
#             "description": "Send a message to a channel",
#             "input_schema": {"properties": {...}, "required": [...]}
#         },
#         ...
#     ]
# }
for tool in result["tools"]:
    print(tool["name"])
```

### get_resources(cursor=None) -> dict

List available resources. Supports pagination via cursor.

```python
result = client.get_resources()
# result = {
#     "resources": {"resource://uri": "Resource Name", ...},
#     "nextCursor": "..." or None
# }
```

### read_resource(uri) -> Any

Read a specific resource by URI.

```python
content = client.read_resource("resource://some-uri")
```

### list_prompts() -> dict

List available prompts.

```python
result = client.list_prompts()
# result = {"prompts": [{"name": "...", "description": "...", "arguments": [...]}]}
```

### get_prompt(name, arguments=None) -> dict

Get a specific prompt by name.

```python
result = client.get_prompt("my-prompt", {"arg1": "value"})
# result = {"description": "...", "messages": [...]}
```

### close()

Close the client connection. Always call when done, or use the context manager.

```python
client.close()
```

### Context Manager

```python
with Client(
    user_id=os.getenv('GUMCP_USER_ID'),
    gumcp_api_key=os.getenv('GUMCP_ACCESS_TOKEN') or os.getenv('GUMCP_API_KEY'),
    base_url=os.getenv('GUMCP_BASE_URL')
) as client:
    result = client.call_tool("slack__send_message", {"channel": "#general", "text": "Hello!"})
    # client.close() called automatically
```

## AsyncClient

For async code, use `AsyncClient` with `async/await`:

```python
from gumcp_client import AsyncClient

async with AsyncClient(
    user_id=os.getenv('GUMCP_USER_ID'),
    gumcp_api_key=os.getenv('GUMCP_ACCESS_TOKEN') or os.getenv('GUMCP_API_KEY'),
    base_url=os.getenv('GUMCP_BASE_URL')
) as client:
    result = await client.call_tool("slack__send_message", {"channel": "#general", "text": "Hi!"})
```

## Error Handling

```python
from gumcp_client import Client, ToolError, ConnectionError, ResourceError

try:
    result = client.call_tool("slack__send_message", {"channel": "#general", "text": "Hello!"})
except ToolError as e:
    print(f"Tool call failed: {e}")
except ConnectionError as e:
    print(f"Connection failed: {e}")
except ResourceError as e:
    print(f"Resource error: {e}")
```

### Exception Hierarchy

- `GumCPError` -- base exception
  - `AuthenticationError` -- auth failures
  - `ConnectionError` -- connection issues
  - `SessionError` -- invalid session
  - `ToolError` -- tool call failures
  - `ResourceError` -- resource access failures
  - `PromptError` -- prompt errors

## Common Patterns

### Multi-integration Workflow

```python
import json
import os
from gumcp_client import Client

with Client(
    user_id=os.getenv('GUMCP_USER_ID'),
    gumcp_api_key=os.getenv('GUMCP_ACCESS_TOKEN') or os.getenv('GUMCP_API_KEY'),
    base_url=os.getenv('GUMCP_BASE_URL')
) as client:
    # Read from Sheets
    raw = client.call_tool("gsheets__read_spreadsheet", {
        "spreadsheet_id": "...",
        "range": "Sheet1!A1:D100"
    })
    data = json.loads(raw[0])

    # Process with Python
    processed = transform(data)

    # Send via Slack
    client.call_tool("slack__send_message", {
        "channel": "#reports",
        "text": str(processed)
    })
```

### Paginated Resource Listing

```python
from gumcp_client import Client, encode_cursor

with Client(
    user_id=os.getenv('GUMCP_USER_ID'),
    gumcp_api_key=os.getenv('GUMCP_ACCESS_TOKEN') or os.getenv('GUMCP_API_KEY'),
    base_url=os.getenv('GUMCP_BASE_URL')
) as client:
    all_resources = {}
    cursor = encode_cursor("channel", None)

    while True:
        response = client.get_resources(cursor=cursor)
        all_resources.update(response.get("resources", {}))
        cursor = response.get("nextCursor")
        if not cursor:
            break

    print(f"Found {len(all_resources)} resources")
```
