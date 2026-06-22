#!/usr/bin/env python3
"""Scaffold a responsive HTML project with Tailwind CSS v4.

Optimized for the Gumloop artifact viewer (400px through wider artifact panels).
Includes class-based dark mode with auto OS preference detection.
"""

import os
import sys

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project</title>
  <script
    src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.0/dist/index.global.js"
    integrity="sha384-nWTzRTCY/9V4Bo352ehygr1c4cnst4XN6lMR3fipakEQrhVpc0hEM5Dii3Amz0sT"
    crossorigin="anonymous"
  ></script>
  <style type="text/tailwindcss">
    @custom-variant dark (&:where(.dark, .dark *));
  </style>
  <script>
    document.documentElement.classList.toggle(
      'dark',
      window.matchMedia('(prefers-color-scheme: dark)').matches
    );
  </script>
  <link rel="stylesheet" href="styles.css">
</head>
<body class="min-h-dvh text-sm antialiased">
  <div id="app"></div>
  <script src="app.js"></script>
</body>
</html>
"""

STYLES_CSS = """\
/* Critical layout -- works even if the pinned Tailwind runtime is slow to load */
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, sans-serif; }
img, video, svg { max-width: 100%; height: auto; }

/* Responsive card grid: stacks at 400px, fills as the panel widens */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr));
  gap: 0.75rem;
}

/* Table wrapper for horizontal scroll when needed */
.table-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
"""

STATIC_APP_JS = """\
document.addEventListener('DOMContentLoaded', function () {
  // Entry point
});
"""

LIVE_APP_JS = """\
document.addEventListener('DOMContentLoaded', function () {
  var app = document.getElementById('app');
  app.innerHTML = '<main class="w-full p-4 md:p-6"><p id="status" class="text-gray-600 dark:text-gray-300">Loading live data...</p><div id="content" class="card-grid mt-4"></div></main>';

  fetch('/gumloop/data/main')
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Failed to load live data');
      }
      return response.json();
    })
    .then(function (data) {
      renderData(data);
    })
    .catch(function (error) {
      document.getElementById('status').textContent = error.message;
    });
});

function renderData(data) {
  var status = document.getElementById('status');
  var content = document.getElementById('content');
  status.textContent = 'Live data loaded';
  content.textContent = JSON.stringify(data, null, 2);
}
"""

LIVE_DATA_PY = """\
import json

# Replace this sample payload with a real GumCP tool call after choosing
# the integration server and tool.
#
# client = get_client()
# result = client.call_tool("server__tool_name", {"argument": "value"})

result = {
    "message": "Replace data.py with a real GumCP tool call.",
    "items": [],
}

print(json.dumps(result))
"""

LIVE_EXPORT_MD = """\
# Exporting This Live Artifact

After replacing `data.py` with the real GumCP tool call, export with:

sandbox_download(
  sandbox_path="{project_dir}/index.html",
  bundle_dir="{project_dir}/",
  filename="{project_name}.html",
  scripts={{"main": "{project_dir}/data.py"}},
  server_ids=["server_id"]
)

The `filename` names the saved artifact and its version history — use a descriptive
one and keep it the SAME on re-exports so versions chain together.

The `main` key must match `fetch('/gumloop/data/main')` in `app.js`.
Replace `server_id` with the GumCP servers `data.py` uses. The tools each script may
call are parsed from its source to scope the execute token — no need to list them.
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 html_scaffold.py <project_dir> [--script-connected]")
        sys.exit(1)

    project_dir = sys.argv[1]
    script_connected_enabled = any(
        flag in sys.argv[2:] for flag in ("--script-connected", "--live-data")
    )
    os.makedirs(project_dir, exist_ok=True)

    files = {
        "index.html": INDEX_HTML,
        "styles.css": STYLES_CSS,
        "app.js": LIVE_APP_JS if script_connected_enabled else STATIC_APP_JS,
    }

    if script_connected_enabled:
        files["data.py"] = LIVE_DATA_PY
        files["EXPORT.md"] = LIVE_EXPORT_MD.format(
            project_dir=project_dir,
            project_name=os.path.basename(project_dir.rstrip("/")) or "artifact",
        )

    for filename, content in files.items():
        path = os.path.join(project_dir, filename)
        if os.path.exists(path):
            print(f"Skipped (exists): {path}")
            continue
        with open(path, "w") as f:
            f.write(content)
        print(f"Created: {path}")

    print(f"Scaffold ready: {project_dir}")


if __name__ == "__main__":
    main()
