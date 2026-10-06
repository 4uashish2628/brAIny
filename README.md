# Invigilator

A sandboxed evaluation harness for AI coding agents. It runs agents on real
terminal tasks inside isolated Docker containers, grades them with automated
verifiers, and checks that the tasks themselves are well-made.

Benchmarks are only as good as their verifiers. A verifier that rejects the
correct fix, passes an untouched environment, or can be edited by the agent
produces misleading scores. Invigilator checks for these problems automatically.

## Quick start

Requires Python 3.9+ and Docker.

```bash
python3 -m invigilator check tasks/
```

```
TASK              ORACLE   NO-OP    TIME    VERDICT
fix-csv-report    PASS     FAIL     3.4s    OK
free-port-9000    PASS     FAIL     5.2s    OK
nginx-serve-8080  PASS     FAIL     5.8s    OK
```

Add `-v` to see the test output for every trial.

## Task format

```
my-task/
├── instruction.md      what the agent is told to do
├── solution.sh         reference ("oracle") solution
├── environment/        Docker build context: the agent's world
│   └── Dockerfile      its CMD must keep the container running
└── tests/
    └── run_tests.sh    exit 0 = solved
```

Only `environment/` is built into the image. `solution.sh` and `tests/` are
copied in at run time, and the tests only after the solution has finished, so
an agent never sees them while it works.

## Sandbox

Each trial runs in a fresh container with no network, a 512 MB memory limit,
1 CPU, a process limit, and a per-step timeout. The container is always
removed afterwards.

## Verifier checks

| Check | Expectation | Catches |
|---|---|---|
| Oracle | reference solution passes | tests that reject a correct fix |
| No-op | untouched environment fails | tests that are too weak |
| Tamper *(planned)* | test files unchanged after the run | agents that edit the tests |
| Flakiness *(planned)* | oracle passes on every repeat | non-deterministic verifiers |

## Roadmap

- [x] Task format, Docker sandbox, oracle and no-op checks
- [ ] LLM agent loop with a shell tool and trajectory logging
- [ ] Parallel trials, pass rate and pass@k per task
- [ ] Tamper and flakiness checks
- [ ] API, job queue and dashboard with trajectory replay
