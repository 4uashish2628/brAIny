"""The agent loop: an LLM solves a task by running shell commands in a sandbox.

    model thinks -> calls run_shell(command) -> sees output -> ... -> calls finish

Every step is recorded in a Trajectory so runs can be inspected and replayed.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from .llm import LLMConfig, LLMError, chat

MAX_OUTPUT_CHARS = 4000

# Small models often retry the same failing command forever, sometimes alternating
# between two (edit, cat, edit, cat...). Count repeats within a recent window.
REPEAT_WINDOW = 10  # look at the last this-many commands
REPEAT_WARN = 3     # same command + exit code this often in the window -> warn the model
REPEAT_STOP = 5     # ... this often -> end the trial as "stuck"

SYSTEM_PROMPT = """You are an expert Linux engineer working inside a Docker container. \
Complete the user's task by running shell commands with the run_shell tool.

Rules:
- Each command runs in a fresh `sh` shell as root. The working directory and \
environment variables do not persist between commands, so use absolute paths \
or `cd /dir && ...`.
- Commands time out after {timeout} seconds. Start long-running programs such as \
servers in the background, e.g. `nohup cmd > /tmp/out.log 2>&1 &`.
- There is no internet access.
- Verify your work before finishing.
- When the task is complete, call the finish tool."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command in the container and return its exit code and output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The command to run."}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Call this once the task is fully complete.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string", "description": "What you did."}},
            },
        },
    },
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


@dataclass
class Step:
    index: int
    thought: str
    command: str
    exit_code: Optional[int]
    output: str
    duration: float


@dataclass
class Trajectory:
    steps: list[Step] = field(default_factory=list)
    finished: bool = False
    stop_reason: str = ""
    summary: str = ""
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: Optional[str] = None
    # The full conversation, including replies that contained no tool call.
    messages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep the head and tail of long output; the middle is usually least useful."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n...[{len(text) - limit} characters truncated]...\n{text[-half:]}"


def parse_tool_calls(message: dict) -> tuple[list[tuple[str, str, dict]], bool]:
    """Extract (call_id, name, arguments) from an assistant message.

    Returns (calls, native). native is False when the model wrote the call as
    JSON text instead of using the tool-calling API, which small local models
    often do. Those calls are still honoured, but their results have to be
    sent back as plain user messages.
    """
    calls = []
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        calls.append((call.get("id") or f"call_{i}", fn.get("name") or "", args if isinstance(args, dict) else {}))
    if calls:
        return calls, True
    return _parse_text_tool_call(message.get("content") or ""), False


def _parse_text_tool_call(content: str) -> list[tuple[str, str, dict]]:
    """Find tool-call JSON objects anywhere in the text, e.g. after a paragraph of
    planning or inside a ```json fence. Every '{' is tried as the start of an object."""
    decoder = json.JSONDecoder()
    calls = []
    pos = content.find("{")
    while pos != -1:
        try:
            obj, end = decoder.raw_decode(content, pos)
        except json.JSONDecodeError:
            pos = content.find("{", pos + 1)
            continue
        if isinstance(obj, dict) and obj.get("name") in TOOL_NAMES:
            args = obj.get("arguments") or obj.get("parameters") or {}
            calls.append((f"text_call_{len(calls)}", obj["name"], args if isinstance(args, dict) else {}))
        pos = content.find("{", end)
    return calls


ChatFn = Callable[[LLMConfig, list, list], tuple]


def run_agent(
    sandbox,
    instruction: str,
    llm: LLMConfig,
    max_steps: int = 30,
    command_timeout: int = 60,
    chat_fn: ChatFn = chat,
) -> Trajectory:
    """Let the model work on the task until it finishes, gives up, or runs out of steps.

    sandbox only needs an exec(command, timeout) -> (exit_code, output) method.
    chat_fn is injectable so the loop can be tested without a real model.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(timeout=command_timeout)},
        {"role": "user", "content": instruction},
    ]
    traj = Trajectory(messages=messages)
    nudged = False
    recent: list[tuple[str, Optional[int]]] = []

    for _ in range(max_steps):
        try:
            message, usage = chat_fn(llm, messages, TOOLS)
        except LLMError as e:
            traj.stop_reason, traj.error = "llm_error", str(e)
            return traj
        traj.llm_calls += 1
        traj.prompt_tokens += usage.get("prompt_tokens", 0)
        traj.completion_tokens += usage.get("completion_tokens", 0)

        thought = (message.get("content") or "").strip()
        calls, native = parse_tool_calls(message)

        assistant = {"role": "assistant", "content": message.get("content") or ""}
        if native:
            assistant["tool_calls"] = message["tool_calls"]
        messages.append(assistant)

        if not calls:
            # Models sometimes reply in prose. Remind once, then give up.
            if nudged:
                traj.stop_reason = "no_tool_call"
                return traj
            nudged = True
            messages.append({
                "role": "user",
                "content": "Use the run_shell tool to run commands, or call finish if the task is complete.",
            })
            continue

        for call_id, name, args in calls:
            # max_steps limits commands, not model replies: one reply can hold several calls.
            if len(traj.steps) >= max_steps:
                traj.stop_reason = "max_steps"
                return traj
            if name == "finish":
                traj.finished, traj.stop_reason = True, "finished"
                traj.summary = str(args.get("summary", ""))
                return traj

            command = args.get("command")
            if name != "run_shell" or not isinstance(command, str) or not command.strip():
                result = "error: call run_shell with a non-empty 'command' string, or call finish."
            else:
                start = time.monotonic()
                exit_code, output = sandbox.exec(["sh", "-c", command], timeout=command_timeout)
                output = truncate(output)
                traj.steps.append(Step(
                    index=len(traj.steps) + 1,
                    thought=thought,
                    command=command,
                    exit_code=exit_code,
                    output=output,
                    duration=round(time.monotonic() - start, 2),
                ))
                thought = ""  # attach the reasoning to the first command only
                result = f"exit code: {exit_code}\n{output or '(no output)'}"

                attempt = (command.strip(), exit_code)
                recent = (recent + [attempt])[-REPEAT_WINDOW:]
                repeats = recent.count(attempt)
                if repeats >= REPEAT_STOP:
                    traj.stop_reason = "stuck"
                    return traj
                if repeats >= REPEAT_WARN:
                    result += (f"\n\nNote: you have run this exact command {repeats} times recently "
                               "with the same result. It is not working; try a different approach.")

            if native:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            else:
                messages.append({"role": "user", "content": f"run_shell result:\n{result}"})

    traj.stop_reason = "max_steps"
    return traj
