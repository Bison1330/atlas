# atlas-worker

Redis-Queue (RQ) worker for Atlas.

Listens on the `default` queue and executes enqueued jobs. In Milestone 0 no jobs are defined yet — the worker just starts cleanly, registers itself with Redis, and waits.

Later milestones will enqueue drawing-ingest and analysis jobs here.

## Run

```bash
python -m worker.main
```
