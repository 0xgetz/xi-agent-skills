---
name: gumcp-client
description: Deprecated — use the gumloop-sdk skill for new code. Covers existing gumcp_client/get_client() integration scripts in the sandbox; see MIGRATION.md to port them.
---

# guMCP Client

> ⚠️ **Deprecated — will be removed soon.** For new code use the **gumloop-sdk** skill.
> `gumcp_client` still works, so existing/saved scripts keep running; see `MIGRATION.md` to port one.

## When to Use This Skill

Only when you hit existing `get_client()` / `gumcp_client` code in a saved script or
trigger you must read or maintain. Never write new `gumcp_client` — use the
**gumloop-sdk** skill for all new work; see `MIGRATION.md` to port an old script.

## Import and Setup

The `gumcp_client` package is pre-installed and `get_client()` is **automatically available** in every sandbox Python execution — you do not need to import or define it.

```python
import json

# get_client() is pre-defined — just use it directly
with get_client() as client:
    raw = client.call_tool("slack__list_channels", {})
    channels = [json.loads(item) for item in raw]
```

**State persistence:** Imports, data variables, and function/class definitions all persist between sandbox executions. You can define a helper in one call and use it in the next.

## Calling Tools

`call_tool()` returns `list[str]` where each string is a JSON-encoded result item. Some tools return one item, others return multiple (e.g. Gmail returns one per email). Always parse every item:

```python
with get_client() as client:
    raw = client.call_tool("gmail__read_emails", {"max_results": 5})
    results = [json.loads(item) for item in raw]
    # results is now a list of parsed dicts -- one per email
    for email in results:
        print(email["subject"])
```

For single-result tools, the list has one item:

```python
with get_client() as client:
    raw = client.call_tool("slack__send_message", {
        "channel": "#general",
        "text": "Hello from the sandbox!"
    })
    result = json.loads(raw[0])  # single result
    print(result)
```

Tool slugs use the `server__tool_name` format (double underscore): `slack__send_message`, `gmail__read_emails`, `gsheets__read_spreadsheet`.

## Listing Available Tools

Prefer the top-level `tool_discovery` tool for discovery. Use `list_tools()` only inside a script that is already running for custom processing.

`list_tools()` returns a **dict** with a `"tools"` key containing a list of tool definitions:

```python
with get_client() as client:
    result = client.list_tools()
    for tool in result["tools"]:
        print(tool["name"], "-", tool["description"])
```

## Listing From Inside A Running Script (legacy)

Discovery is done with the top-level `tool_discovery` tool, NOT the sandbox. Do not enter the sandbox to list tools or find servers. These helper scripts remain only as a legacy live fallback, usable when `tool_discovery` returns nothing for a server visible in `<servers>` (e.g. a still-indexing gumstack/custom server):

```bash
# List all available tools across connected integrations
python3 /home/user/skills/gumcp-client/scripts/list_tools.py

# Call a tool directly from the command line
python3 /home/user/skills/gumcp-client/scripts/call_tool.py slack__send_message '{"channel": "#general", "text": "Hello!"}'

# List resources on a server
python3 /home/user/skills/gumcp-client/scripts/list_resources.py
```

## Server IDs

Server IDs in `call_tool()` must match the actual server ID, not the display name.
Use the top-level `tool_discovery` tool to discover the exact server IDs.
Some common non-obvious mappings: Google BigQuery = `gbigquery`, Google Calendar = `gcalendar`,
Google Sheets = `gsheets`, Google Docs = `gdocs`, Google Drive = `gdrive`.

Only use server IDs that are listed as connected in your environment.

## Approach: Inspect First, Then Process

Never write processing logic against a response you haven't seen. Tool responses vary wildly in structure -- nested objects, lists of dicts, unexpected field names. Writing a batch script blind leads to key errors and wasted executions.

**Step 1: Explore the response shape with a single call.**

```python
with get_client() as client:
    raw = client.call_tool("apollo__enrich_person", {"email": "test@example.com"})
    sample = json.loads(raw[0])
    print(json.dumps(sample, indent=2))
```

**Step 2: Now that you know the field paths, write targeted extraction.**

```python
with get_client() as client:
    contacts = ["alice@co.com", "bob@co.com", "carol@co.com"]
    for email in contacts:
        raw = client.call_tool("apollo__enrich_person", {"email": email})
        data = json.loads(raw[0])
        # You know these paths exist because you inspected the response
        print(f"{email}: {data['person']['title']} at {data['person']['organization']['name']}")
```

This matters most for batch operations -- if you're processing 50 items and your field path is wrong, you waste the entire run. Inspect one, then process many.

## Task Decomposition

Before writing a script, decompose the user's request into ordered steps with dependencies:

- **GET before UPDATE/DELETE.** Mutating a resource requires its ID. If the user says "update the Jira ticket," you need to fetch the ticket first to get its ID, then update it.
- **Resolve names to IDs.** Platforms use internal IDs, not display names. "Post to #general" requires looking up the channel ID for "general" before sending. Same for user mentions, project names, labels, etc.
- **Skip lookups when identifiers are already known.** If the user provides a direct email address, URL, or ID, use it directly.
- **Identify parallel vs sequential steps.** Steps that don't depend on each other's output can run in parallel (see Parallel Execution pattern below). Steps that feed into each other must be sequential.

Example: "Fetch open PRs from GitHub and post a summary to Slack #engineering"
1. Fetch open PRs from GitHub (no dependency)
2. Look up Slack channel ID for "engineering" (no dependency -- parallel with step 1)
3. Format PR data into a message (depends on step 1)
4. Send message to Slack channel (depends on steps 2 and 3)

## Execution Patterns

All patterns below use `get_client()` which is automatically available (see Import and Setup above).

### Pagination

Use when a tool returns paged results (look for `next_cursor`, `next_page_token`, or `offset` in responses).

```python
with get_client() as client:
    all_items = []
    cursor = None

    while True:
        args = {"per_page": 100}
        if cursor:
            args["cursor"] = cursor

        raw = client.call_tool("github__list_issues", args)
        data = json.loads(raw[0])
        items = data.get("issues", [])
        all_items.extend(items)

        cursor = data.get("next_cursor")
        if not cursor or not items:
            break

    print(f"Fetched {len(all_items)} total items")
```

### Bulk Operations with Checkpoints

Use when processing many items (50+) where partial failure shouldn't lose progress.

```python
CHECKPOINT = "/home/user/processed.json"

def load_checkpoint():
    try:
        with open(CHECKPOINT) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_checkpoint(done):
    with open(CHECKPOINT, "w") as f:
        json.dump(list(done), f)

with get_client() as client:
    done = load_checkpoint()
    contacts = [...]  # your full list

    for email in contacts:
        if email in done:
            continue
        try:
            client.call_tool("gmail__send_email", {"to": email, "subject": "Update", "body": "..."})
            done.add(email)
            save_checkpoint(done)
        except Exception as e:
            print(f"Failed {email}: {e}")

    print(f"Completed {len(done)}/{len(contacts)}")
```

### Error Recovery with Retry

Use when calling tools that may intermittently fail (rate limits, transient errors).

```python
import time

def call_with_retry(client, tool, args, max_retries=3):
    for attempt in range(max_retries):
        try:
            raw = client.call_tool(tool, args)
            return json.loads(raw[0])
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            print(f"Retry {attempt + 1}/{max_retries} after {wait}s: {e}")
            time.sleep(wait)

with get_client() as client:
    data = call_with_retry(client, "apollo__enrich_person", {"email": "user@co.com"})
```

### Parallel Execution

Use when making many independent calls (e.g., enriching a list of contacts) where order doesn't matter.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with get_client() as client:
    emails = ["alice@co.com", "bob@co.com", "carol@co.com"]

    def enrich(email):
        raw = client.call_tool("apollo__enrich_person", {"email": email})
        return email, json.loads(raw[0])

    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(enrich, e): e for e in emails}
        for future in as_completed(futures):
            try:
                email, data = future.result()
                results[email] = data
            except Exception as e:
                print(f"Failed {futures[future]}: {e}")

    print(f"Enriched {len(results)}/{len(emails)}")
```

## Sandbox Limitations

- Playwright and browser automation are not available in this sandbox environment. Use HTTP requests or integration tools instead.
- System packages cannot be installed (no root access). Use `pip install` for Python packages.
- Python execution has a 120-second timeout. Break long-running operations into smaller steps.

## Resources

### scripts/

Runnable helper scripts for quick tool discovery and execution from the shell.

### references/

Full API reference for the `Client` class, including all methods, error handling, and advanced patterns.

## Important Notes

- Credentials are pre-configured via environment variables.
- The `gumcp_client` package is pip-installed and available globally.
- Tools use the `server__tool_name` format (double underscore) for routing.
- Use `tool_discovery` first to find available tool names and their required arguments.
- Always use the `with` statement or call `client.close()` to clean up connections.
