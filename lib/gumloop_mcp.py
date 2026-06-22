"""
gumloop_mcp — Shared MCP integration library for Gumloop agent skills.
"""
import json, time, os
from typing import Any, Dict, List, Optional

class MCPClient:
    """Wrapper around the Gumloop MCP client with error handling."""

    def __init__(self, retries: int = 2, retry_delay: float = 1.0):
        from gumloop import Gumloop
        self.client = Gumloop()
        self.retries = retries
        self.retry_delay = retry_delay

    def call(self, server: str, tool_name: str, args: dict) -> Any:
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                result = self.client.mcp.execute(server, tool_name, args).results[0]
                if result.status != "success":
                    raise RuntimeError(f"Tool {server}/{tool_name} failed: {result.error}")
                return result.decoded_content if hasattr(result, 'decoded_content') else result.content[0]
            except Exception as e:
                last_error = e
                if attempt < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise RuntimeError(f"All {self.retries+1} attempts failed: {last_error}")

    def mutate(self, server: str, tool_name: str, args: dict, confirm: bool = True) -> Any:
        if confirm:
            print(f"⚠️ Preview: would call {server}/{tool_name} — set confirm=False to execute")
            return None
        return self.call(server, tool_name, args)

def json_or_text(result) -> Any:
    if hasattr(result, "decoded_content"):
        return result.decoded_content
    if hasattr(result, "content"):
        raw = result.content
        if isinstance(raw, list): raw = raw[0]
        try: return json.loads(raw) if isinstance(raw, str) else raw
        except: return raw
    return result