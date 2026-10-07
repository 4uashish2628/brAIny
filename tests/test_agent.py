"""Agent-loop tests with a scripted fake model and a fake sandbox (no Docker, no LLM).

    python3 -m unittest discover tests
"""

import json
import unittest

from invigilator.agent import parse_tool_calls, run_agent, truncate
from invigilator.llm import LLMConfig, LLMError


def tool_call(name, **args):
    return {"content": "", "tool_calls": [
        {"id": f"id_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    ]}


def scripted(*replies):
    """A fake chat_fn that returns the given replies in order and records what it was sent."""
    replies = list(replies)
    sent = []

    def chat_fn(config, messages, tools):
        sent.append([dict(m) for m in messages])
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"prompt_tokens": 10, "completion_tokens": 5}

    chat_fn.sent = sent
    return chat_fn


class FakeSandbox:
    def __init__(self, outputs=None):
        self.commands = []
        self.outputs = outputs or {}

    def exec(self, command, timeout):
        self.commands.append(command[-1])
        return self.outputs.get(command[-1], (0, "ok"))


class AgentLoopTest(unittest.TestCase):
    def test_runs_commands_then_finishes(self):
        sandbox = FakeSandbox({"ls /app": (0, "report.py")})
        chat_fn = scripted(tool_call("run_shell", command="ls /app"), tool_call("finish", summary="done"))

        traj = run_agent(sandbox, "do it", LLMConfig(), chat_fn=chat_fn)

        self.assertTrue(traj.finished)
        self.assertEqual(traj.stop_reason, "finished")
        self.assertEqual(traj.summary, "done")
        self.assertEqual(sandbox.commands, ["ls /app"])
        self.assertEqual(traj.steps[0].output, "report.py")
        self.assertEqual((traj.llm_calls, traj.prompt_tokens, traj.completion_tokens), (2, 20, 10))
        # The command's result went back to the model as a tool message.
        self.assertEqual(chat_fn.sent[1][-1]["role"], "tool")
        self.assertIn("report.py", chat_fn.sent[1][-1]["content"])

    def test_stops_at_max_steps(self):
        chat_fn = scripted(*[tool_call("run_shell", command="true")] * 3)
        traj = run_agent(FakeSandbox(), "loop", LLMConfig(), max_steps=3, chat_fn=chat_fn)
        self.assertFalse(traj.finished)
        self.assertEqual(traj.stop_reason, "max_steps")
        self.assertEqual(len(traj.steps), 3)

    def test_max_steps_counts_commands_not_replies(self):
        # One reply with five commands must still respect max_steps=3.
        many = {"content": "\n".join(f'{{"name": "run_shell", "arguments": {{"command": "echo {i}"}}}}' for i in range(5))}
        traj = run_agent(FakeSandbox(), "task", LLMConfig(), max_steps=3, chat_fn=scripted(many))
        self.assertEqual(traj.stop_reason, "max_steps")
        self.assertEqual(len(traj.steps), 3)

    def test_warns_then_stops_when_stuck(self):
        # Seen with qwen2.5-coder:7b: `apk add nginx` retried 28 times with no network.
        failing = {"apk add nginx": (1, "ERROR: unable to fetch")}
        chat_fn = scripted(*[tool_call("run_shell", command="apk add nginx")] * 10)

        traj = run_agent(FakeSandbox(failing), "task", LLMConfig(), chat_fn=chat_fn)

        self.assertEqual(traj.stop_reason, "stuck")
        self.assertEqual(len(traj.steps), 5)
        self.assertIn("try a different approach", chat_fn.sent[3][-1]["content"])  # after the 3rd run

    def test_detects_alternating_loop(self):
        # Seen with qwen2.5-coder:7b: sed, cat, sed, cat... for 30 steps.
        loop = [tool_call("run_shell", command="sed -i s/a/b/ f"), tool_call("run_shell", command="cat f")] * 10
        traj = run_agent(FakeSandbox(), "task", LLMConfig(), chat_fn=scripted(*loop))
        self.assertEqual(traj.stop_reason, "stuck")
        self.assertEqual(len(traj.steps), 9)  # 5th sed, interleaved with 4 cats

    def test_nudges_once_then_gives_up_on_prose(self):
        chat_fn = scripted({"content": "I think you should..."}, {"content": "Still just talking."})
        traj = run_agent(FakeSandbox(), "task", LLMConfig(), chat_fn=chat_fn)
        self.assertEqual(traj.stop_reason, "no_tool_call")
        self.assertIn("run_shell", chat_fn.sent[1][-1]["content"])

    def test_text_tool_call_fallback(self):
        # Small local models often write the call as JSON in the message text.
        text_call = {"content": '```json\n{"name": "run_shell", "arguments": {"command": "whoami"}}\n```'}
        sandbox = FakeSandbox()
        chat_fn = scripted(text_call, tool_call("finish"))

        traj = run_agent(sandbox, "task", LLMConfig(), chat_fn=chat_fn)

        self.assertEqual(sandbox.commands, ["whoami"])
        self.assertTrue(traj.finished)
        # No native tool call to reply to, so the result goes back as a user message.
        self.assertEqual(chat_fn.sent[1][-1]["role"], "user")

    def test_bad_arguments_are_reported_not_run(self):
        sandbox = FakeSandbox()
        chat_fn = scripted(tool_call("run_shell"), tool_call("finish"))
        run_agent(sandbox, "task", LLMConfig(), chat_fn=chat_fn)
        self.assertEqual(sandbox.commands, [])
        self.assertIn("error", chat_fn.sent[1][-1]["content"])

    def test_llm_error_is_recorded(self):
        chat_fn = scripted(LLMError("cannot reach model"))
        traj = run_agent(FakeSandbox(), "task", LLMConfig(), chat_fn=chat_fn)
        self.assertEqual(traj.stop_reason, "llm_error")
        self.assertIn("cannot reach", traj.error)


class HelpersTest(unittest.TestCase):
    def test_truncate_keeps_head_and_tail(self):
        text = "A" * 3000 + "B" * 3000
        out = truncate(text, limit=100)
        self.assertTrue(out.startswith("A" * 50))
        self.assertTrue(out.endswith("B" * 50))
        self.assertIn("5900 characters truncated", out)

    def test_parse_finds_call_after_prose(self):
        # Real qwen2.5-coder:7b reply: a plan, then the call in a ```json fence.
        content = (
            "Let's start by examining the script.\n\n1. **Examine**: run it.\n\n"
            '```json\n{"name": "run_shell", "arguments": {"command": "python3 /app/report.py /app/sales.csv"}}\n```'
        )
        calls, native = parse_tool_calls({"content": content})
        self.assertFalse(native)
        self.assertEqual(calls, [("text_call_0", "run_shell", {"command": "python3 /app/report.py /app/sales.csv"})])

    def test_parse_finds_multiple_calls(self):
        content = ('{"name": "run_shell", "arguments": {"command": "ls"}}\n'
                   '{"name": "run_shell", "arguments": {"command": "pwd"}}')
        calls, _ = parse_tool_calls({"content": content})
        self.assertEqual([c[2]["command"] for c in calls], ["ls", "pwd"])

    def test_parse_ignores_unrelated_json(self):
        calls, native = parse_tool_calls({"content": '{"hello": "world"}'})
        self.assertEqual(calls, [])
        self.assertFalse(native)


class ChangesTest(unittest.TestCase):
    def test_leaf_changes_hides_parents_and_harness_markers(self):
        from invigilator.runner import leaf_changes
        changes = [("C", "/app"), ("A", "/app/answer.txt"), ("C", "/tmp"), ("A", "/tmp/.invig_pg_1a2b"),
                   ("C", "/etc/motd")]
        self.assertEqual(leaf_changes(changes), [("A", "/app/answer.txt"), ("C", "/etc/motd")])

    def test_tampering_only_flags_protected_files(self):
        from invigilator.runner import find_tampering
        changes = [("C", "/usr"), ("C", "/usr/bin"), ("C", "/usr/bin/wget"), ("A", "/app/out.txt"),
                   ("A", "/usr/local/lib/python3.12/__pycache__/x.pyc")]
        self.assertEqual(find_tampering(changes), ["C /usr/bin/wget"])
        self.assertEqual(find_tampering(changes, allowed=("/usr/bin",)), [])


if __name__ == "__main__":
    unittest.main()
