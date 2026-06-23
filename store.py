"""Persistent storage for doit: conversation history, long-term memory, and shell history."""

import json
import os
import re
from pathlib import Path

HISTORY_DIR = Path.home() / ".doit"
HISTORY_FILE = HISTORY_DIR / "history.json"
MEMORY_FILE = HISTORY_DIR / "memory.json"
MAX_HISTORY = 10


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_turn(entry: dict):
    HISTORY_DIR.mkdir(exist_ok=True)
    history = load_history()
    history.append(entry)
    history = history[-MAX_HISTORY:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def format_history_for_prompt(history: list) -> str:
    if not history:
        return "(no previous turns)"
    lines = []
    for i, turn in enumerate(history, start=1):
        lines.append(f"Turn {i}:")
        lines.append(f'  User instruction: "{turn.get("instruction", "")}"')
        lines.append(f'  Response type: {turn.get("type", "")}')
        if turn.get("type") == "command":
            lines.append(f'  Command run: {turn.get("command", "")}')
            stdout = (turn.get("stdout") or "").strip()
            stderr = (turn.get("stderr") or "").strip()
            if stdout:
                lines.append(f'  Output: {stdout[:500]}')
            if stderr:
                lines.append(f'  Error output: {stderr[:300]}')
        elif turn.get("content"):
            lines.append(f'  Content: {turn.get("content", "")[:300]}')
            if turn.get("suggested_command"):
                lines.append(f'  Suggested command (not executed): {turn.get("suggested_command")}')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def load_memory() -> dict:
    if not MEMORY_FILE.exists():
        return {}
    try:
        with open(MEMORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_memory(memory: dict):
    HISTORY_DIR.mkdir(exist_ok=True)
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)


def apply_memory_action(memory: dict, memory_action: dict) -> dict:
    if not memory_action:
        return memory
    action = memory_action.get("action")
    key = memory_action.get("key")
    value = memory_action.get("value")
    if not key:
        return memory
    if action in ("store", "update"):
        memory[key] = value
    elif action == "delete":
        memory.pop(key, None)
    save_memory(memory)
    return memory


def format_memory_for_prompt(memory: dict) -> str:
    if not memory:
        return "(no stored memories)"
    return "\n".join(f"- {k}: {v}" for k, v in memory.items())


# ---------------------------------------------------------------------------
# Shell history (user awareness)
# ---------------------------------------------------------------------------

SHELL_HISTORY_LINES = 20


def load_shell_history() -> list[str]:
    """Read the last N commands from the user's shell history file.

    Supports bash (~/.bash_history) and zsh (~/.zsh_history).
    Each returned string is a plain command, already stripped of zsh metadata.
    """
    shell = os.environ.get("SHELL", "/bin/bash")
    is_zsh = "zsh" in shell

    history_file = Path.home() / (".zsh_history" if is_zsh else ".bash_history")
    if not history_file.exists():
        return []

    try:
        text = history_file.read_text(errors="replace")
    except OSError:
        return []

    commands = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if is_zsh:
            # zsh extended history format: ": <timestamp>:<elapsed>;<command>"
            m = re.match(r"^:\s*\d+:\d+;(.+)$", line)
            if m:
                line = m.group(1)
            elif line.startswith(":"):
                continue

        # Skip noise that adds nothing useful to the context
        if line.startswith("#") or line in ("clear", "history"):
            continue

        commands.append(line)

    # Collapse consecutive duplicate commands (re-running the same thing,
    # or noise from multiple test rounds) so the window holds more signal.
    deduped = []
    for cmd in commands:
        if not deduped or deduped[-1] != cmd:
            deduped.append(cmd)

    return deduped[-SHELL_HISTORY_LINES:]


def format_shell_history_for_prompt(commands: list[str], cwd: str) -> str:
    """Render shell history + CWD for the system prompt.

    Lines are tagged [doit] if they are doit invocations, [user] otherwise,
    so the LLM can distinguish between what the user did manually and what
    doit executed on their behalf.
    """
    lines = [f"Current working directory: {cwd}"]
    if not commands:
        lines.append("(no recent shell history available)")
    else:
        lines.append("Recent shell commands (oldest first, most recent last):")
        for cmd in commands:
            tag = "[doit]" if re.match(r"^doit(\s|$)", cmd) else "[user]"
            lines.append(f"  {tag} {cmd}")
    return "\n".join(lines)
