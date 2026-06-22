#!/usr/bin/env python3
"""
List available resources via the guMCP client.

Usage:
    python3 list_resources.py

Examples:
    python3 list_resources.py
"""

import sys

from _config import get_allowed_servers, get_client


def main():
    allowed_servers = get_allowed_servers()

    try:
        with get_client() as client:
            all_resources = {}

            if allowed_servers is not None:
                for sid in allowed_servers:
                    try:
                        result = client.get_resources(server_id=sid)
                        all_resources.update(result.get('resources', {}))
                    except Exception as e:
                        print(f"  Warning: could not list resources for {sid}: {e}", file=sys.stderr)
            else:
                result = client.get_resources()
                all_resources = result.get('resources', {})

            if not all_resources:
                print("No resources found.")
                return

            print(f"Available resources ({len(all_resources)} total):\n")
            for uri, name in all_resources.items():
                print(f"  {name}")
                print(f"    uri: {uri}")
                print()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
