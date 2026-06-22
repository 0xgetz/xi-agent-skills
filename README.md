# Gumloop Agent — Skills & MCP

This repository is an export of the **skills** and connected **MCP server** documentation from my Gumloop agent.

## Contents

- **`skills/`** — All agent skills. Each skill is a directory with a `SKILL.md` (instructions + YAML frontmatter) and optional `scripts/`, `references/`, and `assets/`.
- **`MCP_SERVERS.md`** — The MCP integrations connected to the agent and the tools each exposes.

## Skills included

| Skill | Purpose |
|-------|---------|
| `skill-creator` | Create and improve agent skills. |
| `gumloop-sdk` | Call integration (MCP) tools from sandbox Python or CLI. |
| `gumcp-client` | Legacy gumcp client (deprecated; see MIGRATION.md). |
| `trigger-builder` | Build custom polling triggers for integrations. |
| `spreadsheet-output` | Formatting rules for clean CSV/XLSX output. |
| `script-connected-html-output` | HTML outputs that fetch live integration data. |
| `server-discovery` | Discover and add new MCP servers/integrations. |

The `skills/.tools/` directory contains shared helper scripts (skill init, validation, HTML scaffold).

---
_Exported automatically from the Gumloop agent._
