---
name: google-maps-mcp
description: Use the Google Maps MCP integration to geocode, search places, and get directions. Activate when the user wants to geocode, search places, and get directions via Google Maps, including discovering the right tool, building parameters, and handling results.
icon: plug
color: Blue
---
# Gmaps MCP Integration

## Overview
This skill covers working with the **Gmaps** integration via the MCPClient from `lib.gumloop_mcp`. The MCPClient wraps the Gumloop MCP transport layer with automatic retries, error handling, and typed responses. Use it for all Google Maps and geolocation operations.

## When to use this skill
Activate when the user wants to query, create, update, or manage Google Maps and geolocation using the Gumloop MCP connection to `gmaps`.

## Client Setup
```python
from lib.gumloop_mcp import MCPClient

client = MCPClient()
# The client auto-resolves credentials from the agent's connected integrations.
# No API keys or tokens to configure manually.
```

## Error Handling & Retries
All MCP calls should use this pattern:
```python
def safe_call(client, server, tool, params, max_retries=3):
    """Call an MCP tool with retry and error handling."""
    import time
    for attempt in range(max_retries):
        try:
            result = client.call(server, tool, params)
            error = getattr(result, 'error', None)
            if error:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError('MCP call failed: ' + str(error))
            return result
        except Exception as exc:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
```

## GET-First Pattern
Always read the current state before modifying:
```python
# Fetch current state first with retry
current = safe_call(client, 'gmaps', 'geocode', 'geocode', {'address': '1600 Amphitheatre Parkway, Mountain View, CA'})
print('Current state:', current)
```

## Read Operations
```python
from lib.gumloop_mcp import MCPClient

client = MCPClient()

# Fetch data with retry
result = safe_call(client, 'gmaps', 'geocode', 'geocode', {'address': '1600 Amphitheatre Parkway, Mountain View, CA'})
print('Result:', result)
```

## Write Operations
This service is **read-only** via the Gumloop MCP connector. Data cannot be created or modified through native tools. For write-capable alternatives, see the Artificial API / REST Fallback section below.

## Artificial API / REST Fallback
`gmaps` does not have a native Gumloop MCP connector. Use raw `requests` + `os.environ` with a bound secret for write operations:
```python
import os
import requests

# Get API key from bound secrets
api_key = os.environ.get('FALLBACK_API_KEY')
if not api_key:
    raise RuntimeError('Missing FALLBACK_API_KEY - use bind_env_vars first')

# Call the native REST API directly
response = requests.get(
    'https://developers.google.com/maps/documentation',
    headers={'Authorization': 'Bearer ' + api_key, 'Accept': 'application/json'}
)
response.raise_for_status()
data = response.json()
```

## Safety Notes
- **Always read first** before modifying any resource (GET-first pattern).
- **Confirm destructive operations**: deletes, destroys, removals, and any irreversible actions must be confirmed with the user.
- **Never log credentials**: MCPClient handles auth transparently. Do not print or log secrets.
- **Respect rate limits**: Use the retry pattern above. Back off exponentially on 429 responses.
- **Paginate large sets**: Use `limit`, `page`, or cursor parameters where available.
- **Idempotency**: Write/create calls should be idempotent when possible to avoid duplicates on retry.

## API Documentation
- Service: `gmaps`
- MCPClient docs: [Gumloop MCP SDK](https://docs.gumloop.com/mcp)
- Native API reference: https://developers.google.com/maps/documentation
- Tool discovery: Use `safe_call(client, 'gmaps', 'tool_discovery', {})` to list available tools at runtime.

---
*This skill is part of the Gumloop MCP integration suite. Tool names and schemas vary by deployment. Always rely on live discovery, not assumptions.*
