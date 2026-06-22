---
name: script-connected-html-output
description: Rules for HTML files that fetch live data from integrations via data scripts. Activate when building dashboards, monitors, forms, or any HTML output where the data comes from integrations.
icon: activity
color: Blue
---

# Script-Connected HTML Output

When an HTML file displays data from integrations, use data scripts so the data refreshes every time the file is opened. Only hardcode data when the source is truly static (user-provided CSV, pasted text).

Refer to the `gumloop-sdk` skill for the client and tool-calling patterns.

## How It Works

For new script-connected HTML artifacts, start with:

```bash
python3 /home/user/skills/.tools/html_scaffold.py /home/user/myproject --script-connected
```

Then replace the generated `data.py` sample payload with the real Gumloop SDK call.

1. Write Python data scripts that fetch data via the Gumloop SDK and print JSON to stdout
2. Write the HTML to `fetch('/gumloop/data/{key}')` instead of hardcoding data
3. Export with `sandbox_download(..., scripts={"key": "/home/user/script.py"}, server_ids=["server_id"])`

The platform intercepts `/gumloop/` fetches and runs the matching script server-side.

## Example

**Data script** (`/home/user/get_issues.py`):

```python
import json
from gumloop import Gumloop

client = Gumloop()  # base URL + token from env; project resolved from the token
resp = client.mcp.execute("linear", "list_issues", {"max_limit": 50})
print(json.dumps(resp.results[0].decoded_content))
```

**HTML** uses `fetch` to load that data and render it:

```html
<script>
fetch('/gumloop/data/issues')
  .then(function(r) { return r.json(); })
  .then(function(data) {
    var container = document.getElementById('content');
    data.forEach(function(issue) {
      var div = document.createElement('div');
      div.textContent = issue.title;
      container.appendChild(div);
    });
  });
</script>
```

**Export** bundles both together:

```
sandbox_download(
  sandbox_path="/home/user/dashboard.html",
  scripts={"issues": "/home/user/get_issues.py"},
  server_ids=["linear"]
)
```

Keys in `scripts` and the fetch URLs must match. The tools each script may call are parsed from its source to scope the execute token — you don't list them. `server_ids` lists every server_id used by any script (enables connection checks when the artifact is shared).

## Write Actions

For forms that write back to integrations, use `/gumloop/action/{key}` with POST. The request body is forwarded to the script as `os.getenv("GUMLOOP_PAYLOAD")`.

```python
import os, json
from gumloop import Gumloop

client = Gumloop()  # base URL + token from env; project resolved from the token
payload = json.loads(os.getenv("GUMLOOP_PAYLOAD", "{}"))
resp = client.mcp.execute("linear", "create_issue", payload)
print(json.dumps(resp.results[0].decoded_content))
```

## Script Constraints

- Output JSON to stdout via `print(json.dumps(...))` — stdout is the response body
- Instantiate `Gumloop()` directly (runs in a one-off sandbox)
- Scripts can only call tools from `gumcp_server` type servers (see server-discovery catalog). Do not use `gumstack_server` or `mcp_server` tools in data scripts — they will fail at execute time
- For read-only scripts, run them once in the sandbox before exporting to verify they return valid JSON
- Omit `scripts` from `sandbox_download` entirely for static HTML
