#!/usr/bin/env python3
"""
Call a tool via the guMCP client.

Usage:
    python3 call_tool.py <server__tool_name> '<json_arguments>'

Examples:
    python3 call_tool.py slack__send_message '{"channel": "#general", "text": "Hello!"}'
    python3 call_tool.py gmail__read_emails '{"max_results": 5}'
    python3 call_tool.py gsheets__read_spreadsheet '{"spreadsheet_id": "...", "range": "Sheet1!A1:D10"}'
"""

import json
import sys

from gumcp_client import ToolError

from _config import get_allowed_servers, get_client, validate_server_access


def main():
    if len(sys.argv) < 2:
        print("Usage: call_tool.py <server__tool_name> '<json_arguments>'")
        print("\nExamples:")
        print('  call_tool.py slack__send_message \'{"channel": "#general", "text": "Hello!"}\'')
        print('  call_tool.py gmail__read_emails \'{"max_results": 5}\'')
        sys.exit(1)

    tool_name = sys.argv[1]
    arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    # Validate server is in the agent's configured tool set
    if '__' in tool_name:
        validate_server_access(tool_name.split('__', 1)[0], get_allowed_servers())

    try:
        with get_client() as client:
            result = client.call_tool(tool_name, arguments)

            # Pretty-print the result
            for item in result:
                try:
                    parsed = json.loads(item)
                    print(json.dumps(parsed, indent=2))
                except (json.JSONDecodeError, TypeError):
                    print(item)
    except ToolError as e:
        print(f"Tool error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
