#!/usr/bin/env python3
"""
List available tools via the guMCP client.

Usage:
    python3 list_tools.py

Examples:
    python3 list_tools.py
"""

import sys

from _config import get_allowed_servers, get_client


def main():
    allowed_servers = get_allowed_servers()

    try:
        with get_client() as client:
            all_tools = []

            if allowed_servers is not None:
                for sid in allowed_servers:
                    try:
                        result = client.list_tools(server_id=sid)
                        all_tools.extend(result.get('tools', []))
                    except Exception as e:
                        print(f"  Warning: could not list tools for {sid}: {e}", file=sys.stderr)
            else:
                result = client.list_tools()
                all_tools = result.get('tools', [])

            if not all_tools:
                print("No tools found.")
                return

            print(f"Available tools ({len(all_tools)} total):\n")
            for tool in all_tools:
                print(f"  {tool['name']}")
                if tool.get('description'):
                    print(f"    {tool['description']}")
                if tool.get('input_schema', {}).get('properties'):
                    params = list(tool['input_schema']['properties'].keys())
                    required = tool['input_schema'].get('required', [])
                    param_strs = []
                    for p in params:
                        param_strs.append(f"{p}*" if p in required else p)
                    print(f"    params: {', '.join(param_strs)}")
                print()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
