---
name: xero-mcp
description: Use the Xero MCP integration to manage accounting records and invoices. Activate when the user wants to manage accounting records and invoices via Xero, including discovering the right tool, building parameters, and handling results.
icon: plug
color: Blue
---
# Xero MCP Integration

## Overview
This skill covers working with the **Xero** integration via the MCPClient from `lib.gumloop_mcp`. The MCPClient wraps the Gumloop MCP transport layer with automatic retries, error handling, and typed responses. Use it for all Xero accounting software operations.

## When to use this skill
Activate when the user wants to query, create, update, or manage Xero accounting software using the Gumloop MCP connection to `xero`.

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
current = safe_call(client, 'xero', 'get_invoices', 'get_invoices', {'status': 'AUTHORISED', 'page': 1})
print('Current state:', current)
```

## Read Operations
```python
from lib.gumloop_mcp import MCPClient

client = MCPClient()

# Fetch data with retry
result = safe_call(client, 'xero', 'get_invoices', 'get_invoices', {'status': 'AUTHORISED', 'page': 1})
print('Result:', result)
```

## Write Operations
Always read the current state first (GET-first) before modifying. For destructive operations, call `confirm_destructive()` or `await_confirm()` first.
```python
from lib.gumloop_mcp import MCPClient

client = MCPClient()

# Read current state first
current = safe_call(client, 'xero', 'get_invoices', 'get_invoices', {'status': 'AUTHORISED', 'page': 1})
print('Current state:', current)

# Now create/update
result = safe_call(client, 'xero', 'create_invoice', 'create_invoice', {'type': 'ACCREC', 'contact': {'name': 'Client Ltd'}, 'line_items': [{'description': 'Service', 'quantity': 1, 'unit_amount': 1000.00, 'account_code': '200'}]})
print('Write completed:', result)
```

## Update Operations
```python
# Read first, then update
current = safe_call(client, 'xero', 'get_invoices', 'get_invoices', {'status': 'AUTHORISED', 'page': 1})
print('Current state:', current)

result = safe_call(client, 'xero', 'update_invoice', 'update_invoice', {'invoice_id': 'inv_abc', 'status': 'PAID'})
print('Updated:', result)
```

## Delete Operations (Destructive - Requires Confirmation)
```python
from lib.gumloop_mcp import MCPClient

client = MCPClient()

# ALWAYS confirm with the user first
user_confirmed = await_confirm()
if not user_confirmed:
    print('Operation cancelled by user')
    return

# Read current state before deleting
current = safe_call(client, 'xero', 'get_invoices', 'get_invoices', {'status': 'AUTHORISED', 'page': 1})
print('About to delete:', current)

result = safe_call(client, 'xero', 'delete_invoice', 'delete_invoice', {'invoice_id': 'inv_xyz'})
print('Delete completed:', result)
```

## Artificial API / REST Fallback
If the native Gumloop `xero` connection is unavailable, fall back to the raw REST API:
```python
import os
import requests

# Get API key from bound secrets
api_key = os.environ.get('FALLBACK_API_KEY')
if not api_key:
    raise RuntimeError('Missing FALLBACK_API_KEY - use bind_env_vars first')

# Call the native REST API directly
response = requests.get(
    'https://developer.xero.com/documentation/api/accounting/overview',
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
- Service: `xero`
- MCPClient docs: [Gumloop MCP SDK](https://docs.gumloop.com/mcp)
- Native API reference: https://developer.xero.com/documentation/api/accounting/overview
- Tool discovery: Use `safe_call(client, 'xero', 'tool_discovery', {})` to list available tools at runtime.

---
*This skill is part of the Gumloop MCP integration suite. Tool names and schemas vary by deployment. Always rely on live discovery, not assumptions.*
