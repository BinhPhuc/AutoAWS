"""Remediation: the ONLY place AutoAWS writes to a user's account (AGENTS.md hard constraint #1).

- ``catalog``: the fixed, generic list of actions (by resource and operation), each with
  snapshot, pre-check, preview, execute, verify and undo written by hand (``actions/``). The
  LLM only names an action and its parameters; it never writes commands.
- ``sessions``: the write session, locked to exactly the API calls of one action.
"""
