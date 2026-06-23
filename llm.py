"""LLM interaction layer for doit."""

import json
import re
import configparser
import subprocess
from pathlib import Path

import litellm

litellm.suppress_debug_info = True

DEFAULT_MODEL = "ollama_chat/qwen3:4b"


def get_active_model() -> str:
    config_path = Path.home() / "doit.cfg"
    if config_path.exists():
        cfg = configparser.ConfigParser()
        cfg.read(config_path)
        if "Model" in cfg and "name" in cfg["Model"]:
            return cfg["Model"]["name"]
    return DEFAULT_MODEL


def _strip_response(text: str) -> str:
    """Remove markdown fences and <think>...</think> blocks from model output."""
    # Strip thinking blocks (qwen3 and similar models)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


def call_llm(model: str, system_prompt: str, user_message: str) -> dict:
    """Call the LLM and return the parsed JSON response dict."""
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    # request JSON mode; fall back silently if the provider rejects it
    try:
        response = litellm.completion(**kwargs, response_format={"type": "json_object"})
    except Exception:
        response = litellm.completion(**kwargs)

    raw = _strip_response(response.choices[0].message.content or "")
    return json.loads(raw)


def is_dangerous(command: str, model: str) -> tuple[bool, str]:
    """Return (is_dangerous, explanation) for the given shell command."""
    system_prompt = (
        "You are a safety classifier for shell commands.\n"
        "Given a shell command, decide if it is SAFE (read-only: ls, grep, cat, find, ps, df, echo) "
        "or DANGEROUS (modifies filesystem or system state: creates, deletes, moves, renames, "
        "overwrites files/dirs, changes permissions, installs/removes packages, kills processes, "
        "modifies git history, etc.).\n\n"
        "Respond ONLY with raw JSON — no markdown:\n"
        '{"dangerous": true or false, "explanation": "short plain-English explanation"}'
    )
    result = call_llm(model, system_prompt, command)
    return result.get("dangerous", True), result.get("explanation", "")


def run_shell(command: str, shell: str = "/bin/bash") -> dict:
    """Execute command in the given shell; return stdout, stderr, returncode."""
    import re as _re
    if _re.match(r"^\s*doit(\s|$)", command):
        return {
            "stdout": "",
            "stderr": "doit: refusing to run a recursive doit call.\n",
            "returncode": 1,
        }
    try:
        result = subprocess.run(
            [shell, "-c", command],
            text=True,
            capture_output=True,
            timeout=60,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "doit: command timed out after 20s.\n", "returncode": 1}
    except FileNotFoundError:
        return {"stdout": "", "stderr": f"doit: shell not found: {shell}\n", "returncode": 1}
