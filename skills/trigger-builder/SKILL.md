---
name: trigger-builder
description: Build custom polling triggers that monitor MCP tools and fire the agent when something new is detected. Subclass BaseTrigger, implement check() and run_trigger_test(). Use when existing operator triggers don't cover the use case.
---

# Trigger Builder

## When to Use

Use `create_mcp_trigger` when the user wants monitoring that existing integration triggers can't handle (cross-service conditions, services without operator triggers, custom filtering, value monitoring).

## Workflow

Follow these steps in order:

1. **Ensure servers are connected.** Identify ALL servers the task needs upfront. Call `add_server_awaiter` for every missing server in parallel (one call per server, all in the same step) so the user adds them all at once.
2. **Discover tools.** Run the list_tools script to get exact tool names and parameter schemas. Never guess.
3. **Build the trigger.** Subclass `BaseTrigger`, implement `check()` and `run_trigger_test()`.
4. **Test in sandbox.** Run the trigger class with `run("test")` in a single `sandbox_python` call.
5. **Create the trigger.** Call `create_mcp_trigger` only after the test succeeds.
6. **Report issues.** If something fails due to user-side configuration (wrong email, missing permissions), report clearly and ask the user to correct it.

## Discovering Tools

Discover all available tools BEFORE writing any code:

```bash
gumloop mcp list            # connected servers
gumloop mcp tools <server>  # tools + parameter schemas on a server
```

Never guess tool names. Never make API calls before discovering the correct tool names and parameters from this output.

## What You Write

Read `/home/user/skills/gumloop-sdk/SKILL.md` for the client API and `/home/user/skills/trigger-builder/scripts/trigger_base.py` for the BaseTrigger class.

You write a `class Trigger(BaseTrigger)` with two methods:
- `check(**inputs)` -- poll for changes, return `(fired: bool, data: list[dict] | None)`
- `run_trigger_test()` -- make real calls to verify the trigger works

The system provides: imports, client setup, state management, validation, and the runner. When passing `trigger_code` to `create_mcp_trigger`, do NOT include `from trigger_base import BaseTrigger` -- the system provides it. Only include it when testing in sandbox.

### Available on `self`:
- `self.client` -- MCP client (see the gumloop-sdk skill)
- `self.client.mcp.execute("server", "tool", {args})` -- parsed results in `resp.results[0].decoded_content`
- `self.state.latest("key")` -- last checkpoint value, or None
- `self.state.push({"key": "value"})` -- stage a checkpoint (committed after successful poll)
- `self.state.has_seen("key", value)` -- True if any checkpoint has key == value

### Example

```python
class Trigger(BaseTrigger):
    def _read(self, query, max_results):
        resp = self.client.mcp.execute("gmail", "read_emails",
            {"query": query, "max_results": max_results})
        return resp.results[0].decoded_content

    def check(self, sender_email):
        last_id = self.state.latest("last_id")
        emails = self._read(f"from:{sender_email}", 10)
        if not emails:
            return False, None
        latest_id = emails[0]["id"]
        if latest_id == last_id:
            return False, None
        self.state.push({"last_id": latest_id})
        if last_id is None:
            return False, None
        return True, [{"email_id": e["id"], "subject": e["subject"]}
                      for e in emails if e["id"] != last_id]

    def run_trigger_test(self):
        emails = self._read(f"from:{self._input_args['sender_email']}", 5)
        if not emails:
            return {"status": "no_data"}
        return {"status": "success",
                "baseline_state": [{"last_id": emails[0]["id"]}]}
```

## Contracts

**`check()` is read-only detection. The agent handles all actions.** The trigger detects the condition; the prompt tells the agent what to do with the data.

**Inputs**: `check()` receives `trigger_inputs` values as kwargs.
**Outputs**: `check()` returns `(fired: bool, data: list[dict] | None)`. Dict keys must match `trigger_outputs`.
**Class name**: Always `Trigger`.
**Trigger name**: Short descriptive name like "Email from {sender}" or "New message in {channel}".

**Data selectivity is critical.** `data` must contain ONLY items that are new since the last poll -- not everything the API returned. Use state to filter down to the delta.

**`poll_frequency`**: Choose based on the user's intent, not the default. "Notify me immediately" → 300s. "Send a daily report" → 86400. "Check every hour" → 3600. Match the cadence to what makes sense for the use case -- don't waste credits polling every 5 min when hourly is fine.

## State Management

State is a **sliding window of 5000 entries** persisted across poll cycles. It exists solely for dedup -- do NOT store raw API responses.

**One push per poll cycle.** Push a single checkpoint dict at the end of `check()` with the minimum needed for dedup.

**`latest()` is O(1)** -- primary dedup pattern. `has_seen()` scans all entries -- use only when needed. `get()` returns all entries -- if you need it, your dedup strategy is probably wrong.

Choose the right checkpoint for the use case -- don't default to `last_id` if the data doesn't have stable IDs. Think about what actually changes and what uniquely identifies "new" data. The sandbox has standard libraries (hashlib, collections, etc.) if needed. Never compromise on trigger accuracy to save a few bytes of state.

## Testing

Write the class AND test in a **single `sandbox_python` call** (sandbox state does not persist between calls):

```python
import sys, json
sys.path.insert(0, "/home/user/skills/trigger-builder/scripts")
from trigger_base import BaseTrigger

class Trigger(BaseTrigger):
    # ... your code ...

trigger = Trigger(
    state_data=[],
    input_args={"sender_email": "user@example.com"},
    expected_outputs={"email_id", "subject"}
)
result = trigger.run("test")
print(json.dumps(result, indent=2))
```

Only call `create_mcp_trigger` after the test succeeds.

## Testing an Existing Trigger

When the user wants to test a trigger after creation, use `manage_integration_trigger` with `action: "test_now"` and the `trigger_id`. This runs the trigger's `check()` live against the current state and returns the result directly.

Interpret the result: `status: "fired"` + `data` = new data detected (show the items). `status: "empty"` = no new data since the last poll. `status: "error"` = report the error.

## Gotchas

- **Tool call failures are not your problem to fix.** If `mcp.execute()` returns auth/credential/connection errors, surface the error to the user -- don't mock data or invent workarounds. Fix logic bugs in your code, not infrastructure issues.
- **Triggers ALWAYS fire THIS agent** -- NEVER ask "which agent" or "do you mean this agent". Just build it.
- Confirm user-provided INPUT VALUES (email addresses, URLs, etc.) before creating -- but don't ask about design decisions. Just build it.
- Extract shared logic between `check()` and `run_trigger_test()` into private helper methods -- don't copy-paste
- `mcp.execute(...).results[0].decoded_content` gives the JSON content already parsed (`.content` is the raw strings)
- Read-only tools only -- never use tools that create, update, delete, or send
- Push ONE checkpoint per cycle AFTER all API calls succeed -- not before, not per item
- First run = baseline -- when `state.latest()` returns `None`, push a checkpoint but return `(False, None)`
