"""Each task's verifier must reject plausible-but-wrong solutions, not just no-ops.

A scripted "agent" runs a near-miss solution for each task's trap, and the
trial must FAIL. Needs Docker; skipped without it.

    python3 -m unittest tests.test_task_traps -v
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from invigilator.llm import LLMConfig
from invigilator.runner import run_trial
from invigilator.task import Task

TASKS = Path(__file__).resolve().parent.parent / "tasks"


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def scripted(*commands):
    def call(name, args):
        return {"content": "", "tool_calls": [{"id": "1", "type": "function",
                                               "function": {"name": name, "arguments": json.dumps(args)}}]}
    replies = [call("run_shell", {"command": c}) for c in commands] + [call("finish", {})]
    return lambda config, messages, tools: (replies.pop(0), {})


def attempt(task: str, *commands):
    return run_trial(Task.load(TASKS / task), "agent", llm=LLMConfig(), chat_fn=scripted(*commands))


@unittest.skipUnless(docker_available(), "Docker is not running")
class NearMissTest(unittest.TestCase):
    def assertRejected(self, result, reason):
        self.assertEqual(result.status, "FAIL", result.test_output)
        self.assertIn(reason, result.test_output)

    def test_json_shallow_merge(self):
        shallow = ("python3 -c \"import json; b=json.load(open('/app/base.json')); "
                   "b.update(json.load(open('/app/override.json'))); json.dump(b, open('/app/config.json','w'))\"")
        self.assertRejected(attempt("json-config-merge", shallow), "wrong merge result")

    def test_sqlite_counting_refunds(self):
        self.assertRejected(attempt("sqlite-top-customer", "echo Ravi > /app/answer.txt"), "expected Meera")

    def test_permissions_blanket_chmod(self):
        blanket = ("groupadd web && useradd -r -g web deploy && chown -R deploy:web /srv/app "
                   "&& chmod -R 750 /srv/app")
        self.assertRejected(attempt("user-permissions", blanket), "expected 'deploy:web 640'")

    def test_backup_quoted_but_unguarded_glob(self):
        fixed_quotes = ("printf '#!/bin/sh\\nmkdir -p \"$2\"\\nn=0\\nfor f in \"$1\"/*.txt; do cp \"$f\" \"$2\"/; "
                        "n=$((n+1)); done\\necho \"copied $n files\"\\n' > /app/backup.sh")
        self.assertRejected(attempt("fix-backup-script", fixed_quotes), "copied 0 files")

    def test_git_revert_undoes_readme_too(self):
        revert = "cd /app/repo && git revert --no-edit HEAD~1"
        self.assertRejected(attempt("git-restore-file", revert), "README.md was changed")

    def test_git_squash_rewrites_history(self):
        # Right files, but every commit squashed into one.
        squash = ("cd /app/repo && git checkout HEAD~2 -- pricing.csv "
                  "&& git reset -q --soft $(git rev-list --max-parents=0 HEAD) && git commit -q --amend -m restore")
        self.assertRejected(attempt("git-restore-file", squash), "no longer in history")

    def test_log_flood_killing_only_the_child(self):
        self.assertRejected(attempt("stop-log-flood", "pkill -f collector.py; rm -f /var/log/app/collector.log"),
                            "collector")


if __name__ == "__main__":
    unittest.main()
