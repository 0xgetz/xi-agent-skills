"""
Base class for MCP polling triggers.

AI subclasses BaseTrigger and implements:
  - check(**inputs) -> (fired: bool, data: list[dict] | None)
  - run_trigger_test() -> dict

BaseTrigger.run() handles validation, error classification, and output contract enforcement.

Triggers always fire the agent they're attached to. Never ask the user which agent to call.
"""

import json
import os
from typing import Any, Optional

from gumloop import Gumloop


class TriggerError(Exception):
    """Raise from check() or run_trigger_test() for clean, surfaceable errors."""
    pass


class TriggerState:
    """Checkpoint storage for deduplication across poll cycles.

    Available as self.state on BaseTrigger subclasses.

    Methods:
        get()                -> list[dict]  all checkpoints (committed + staged)
        push(entry: dict)    -> None        stage a new checkpoint
        latest(key=None)     -> dict | value | None   last checkpoint or field from it
        has_seen(key, value) -> bool        True if any checkpoint has key == value
    """

    MAX_ENTRIES = 5000  # Oldest entries are trimmed when state exceeds this limit

    def __init__(self, initial: list) -> None:
        self._current: list[dict] = list(initial)
        self._staged: list[dict] = []

    def get(self) -> list[dict]:
        """All checkpoints (committed + staged this cycle)."""
        return self._current + self._staged

    def push(self, entry: dict) -> None:
        """Stage a new checkpoint entry. Committed after successful poll.
        Trimming happens in _commit_state(), not here."""
        if not isinstance(entry, dict):
            raise TriggerError(f"state.push() expects dict, got {type(entry).__name__}")
        self._staged.append(entry)

    def latest(self, key: Optional[str] = None) -> Any:
        """Last checkpoint entry, or a specific field from it.

        state.latest()          -> last dict or None
        state.latest("last_id") -> value of "last_id" in last dict, or None
        """
        entries = self.get()
        if not entries:
            return None
        last = entries[-1]
        return last.get(key) if key else last

    def has_seen(self, key: str, value: Any) -> bool:
        """Check if any checkpoint has key == value. Useful for dedup."""
        return any(e.get(key) == value for e in self.get())

    def get_staged(self) -> list[dict]:
        """Entries staged this cycle (not yet committed)."""
        return self._staged


class _Client:
    """Gumloop SDK with a gumcp-compatible call_tool, so one client serves both:
    new triggers call self.client.mcp.execute(...); existing triggers call
    self.client.call_tool("server__tool", args). Project/team comes from the token.
    """

    def __init__(self) -> None:
        self._sdk = Gumloop()
        self.mcp = self._sdk.mcp

    def call_tool(self, slug: str, arguments: Optional[dict] = None) -> list:
        server_id, _, tool_name = slug.partition("__")
        response = self.mcp.execute(server_id, tool_name, arguments or {})
        if not response.results:
            raise TriggerError(f"{slug} returned no results")
        result = response.results[0]
        if result.status != "success":
            raise TriggerError((result.error or {}).get("message") or f"{slug} failed")
        return result.content or []


class BaseTrigger:
    """Abstract base for MCP polling triggers.

    Subclass this and implement:
        check(**inputs)        -> (fired: bool, data: list[dict] | None)
        run_trigger_test()     -> dict with test results

    Available on self:
        self.client  -- MCP client: self.client.mcp.execute("gmail", "read_emails", args)
                        (existing triggers' self.client.call_tool("gmail__read_emails", args) also works)
        self.state   -- TriggerState with get/push/latest/has_seen
    """

    def __init__(
        self,
        state_data: list,
        input_args: dict[str, Any],
        expected_outputs: set[str],
    ) -> None:
        self.state = TriggerState(state_data)
        self._client = None
        self._input_args = input_args
        self._expected_outputs = expected_outputs

    @property
    def client(self):
        if self._client is None:
            self._client = _Client()
        return self._client

    def check(self, **inputs: Any) -> tuple[bool, Optional[list[dict]]]:
        """Override this. Return (fired, data).

        fired: True if the trigger should fire, False otherwise
        data:  list of dicts matching trigger_outputs when fired, None otherwise
        """
        raise NotImplementedError("Subclass must implement check()")

    def run_trigger_test(self) -> dict:
        """Override this. Make real calls to verify the trigger works.

        Return a dict, e.g.:
            {"status": "success", "baseline_state": [{"last_id": "..."}]}
            {"status": "no_data", "message": "No items found"}
        """
        raise NotImplementedError("Subclass must implement run_trigger_test()")

    def run(self, mode: str = "check") -> dict:
        """System entry point. Wraps check/test with validation and error handling."""
        try:
            if mode == "test":
                return self.run_trigger_test()

            result = self.check(**self._input_args)

            if not isinstance(result, tuple) or len(result) != 2:
                return _error("contract", "check() must return (fired: bool, data)")

            fired, data = result

            if fired and data:
                if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
                    return _error("contract", "data must be list[dict]")
                if self._expected_outputs:
                    for item in data:
                        missing = self._expected_outputs - set(item.keys())
                        if missing:
                            return _error(
                                "contract",
                                f"data missing keys {missing} from trigger_outputs",
                            )
                return {
                    "status": "fired",
                    "data": data,
                    "staged_state": self.state.get_staged(),
                }

            return {"status": "empty", "staged_state": self.state.get_staged()}

        except TriggerError as e:
            return _error("trigger", str(e))
        except Exception as e:
            return _error(_classify_error(e), str(e))


def _error(error_type: str, message: str) -> dict:
    return {"status": "error", "error_type": error_type, "message": message}


def _classify_error(e: Exception) -> str:
    try:
        err = json.loads(str(e))
        code = err.get("error_status", 0)
        if code == 429:
            return "rate_limit"
        if code in (401, 403):
            return "auth"
    except Exception:
        if "timeout" in str(e).lower():
            return "timeout"
    return "unknown"
