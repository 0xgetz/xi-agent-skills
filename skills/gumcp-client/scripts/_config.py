"""Shared configuration helpers for gumcp-client skill scripts."""

import json
import os
import sys

from gumcp_client import Client


def get_allowed_servers():
    """Read allowed_servers from GUMCP_CONFIG env var.

    Returns None when no config is set (no restriction), or a list
    of server IDs the agent is permitted to use.
    """
    raw = os.getenv('GUMCP_CONFIG')
    if not raw:
        return None
    try:
        return json.loads(raw).get('allowed_servers')
    except (json.JSONDecodeError, TypeError):
        return None


def validate_server_access(server_id, allowed_servers):
    """Exit with a clear error if server_id is not in the allowed list."""
    if allowed_servers is not None and server_id not in allowed_servers:
        print(
            f"Error: server '{server_id}' is not configured for this agent.\n"
            f"Available servers: {', '.join(sorted(allowed_servers))}",
            file=sys.stderr,
        )
        sys.exit(1)


def get_client():
    """Create a gumcp Client from environment variables, or exit on missing creds."""
    access_token = os.getenv('GUMCP_ACCESS_TOKEN')
    user_id = os.getenv('GUMCP_USER_ID')
    api_key = os.getenv('GUMCP_API_KEY')
    base_url = os.getenv('GUMCP_BASE_URL')

    if not base_url:
        print("Error: GUMCP_BASE_URL must be set.")
        sys.exit(1)

    if access_token:
        return Client(access_token=access_token, base_url=base_url)

    if not api_key or not user_id:
        print("Error: GUMCP_ACCESS_TOKEN (or GUMCP_API_KEY + GUMCP_USER_ID) must be set.")
        sys.exit(1)

    return Client(user_id=user_id, gumcp_api_key=api_key, base_url=base_url)
