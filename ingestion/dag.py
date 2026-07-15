"""
hormuz_watch/ingestion/dag.py

A minimal in-process DAG orchestrator: declare tasks with dependencies,
and the scheduler runs each task as soon as its own dependencies finish
(not gated on unrelated tasks) using a thread pool, since ingestion tasks
are I/O-bound network calls. Each task gets its own retry-with-
exponential-backoff policy, independent of any retry logic inside
individual collectors (that's per-HTTP-call; this is for the task as a
whole raising).

This is deliberately NOT Airflow/Prefect/Dagster — those are the natural
next step for a real deployment, but a small dependency-graph scheduler
demonstrates (and gets real value from) DAG semantics for a single-
machine daily pipeline without adding a scheduler service to run and
maintain.

Usage:
    dag = DAG()
    dag.add_task("eia", eia.run)
    dag.add_task("gdelt", gdelt.run)
    dag.add_task("risk_index", build_index, depends_on=["eia", "gdelt"])
    results, errors, task_states = dag.run()
"""

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class Task:
    name: str
    func: callable
    depends_on: list = field(default_factory=list)
    max_retries: int = 2
    retry_backoff_base: float = 2.0  # seconds; delay = base * 2**attempt


class TaskResult:
    def __init__(self, name: str):
        self.name = name
        self.status = "pending"  # pending -> running -> success | failed | skipped
        self.value = None
        self.error = None
        self.attempts = 0


class DAG:
    """
    Register tasks with add_task(), then call run(). A task whose
    dependencies all succeeded starts as soon as those specific
    dependencies finish. A task with a failed dependency is marked
    "skipped", not attempted. Independent tasks run concurrently via a
    thread pool.
    """

    def __init__(self, max_workers: int = 4):
        self.tasks: dict = {}
        self.max_workers = max_workers

    def add_task(self, name: str, func, depends_on: list = None,
                 max_retries: int = 2, retry_backoff_base: float = 2.0):
        self.tasks[name] = Task(
            name=name, func=func, depends_on=depends_on or [],
            max_retries=max_retries, retry_backoff_base=retry_backoff_base,
        )

    def _run_one(self, task: Task) -> TaskResult:
        result = TaskResult(task.name)
        result.status = "running"

        for attempt in range(task.max_retries + 1):
            result.attempts = attempt + 1
            try:
                result.value = task.func()
                result.status = "success"
                return result
            except Exception as e:
                logger.warning(f"[DAG] '{task.name}' attempt {attempt + 1}/{task.max_retries + 1} "
                               f"failed: {e}")
                if attempt < task.max_retries:
                    delay = task.retry_backoff_base * (2 ** attempt)
                    logger.info(f"[DAG] '{task.name}' retrying in {delay:.0f}s...")
                    time.sleep(delay)
                else:
                    result.status = "failed"
                    result.error = f"{e}\n{traceback.format_exc()}"

        return result

    def run(self):
        """
        Execute the DAG. Returns (results, errors, task_states):
          results: dict[name -> return value] for successful tasks
          errors:  list[(name, error_str)] for failed/skipped tasks
          task_states: dict[name -> TaskResult] for everything
        """
        pending = dict(self.tasks)
        done = {}
        in_flight = {}

        logger.info(f"[DAG] Executing {len(pending)} tasks: {list(pending)}")

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            while pending or in_flight:
                ready = [t for t in pending.values() if all(dep in done for dep in t.depends_on)]

                for task in ready:
                    del pending[task.name]
                    failed_deps = [d for d in task.depends_on if done[d].status != "success"]
                    if failed_deps:
                        skipped = TaskResult(task.name)
                        skipped.status = "skipped"
                        skipped.error = f"upstream dependency failed: {failed_deps}"
                        logger.warning(f"[DAG] '{task.name}' skipped — {skipped.error}")
                        done[task.name] = skipped
                        continue
                    logger.info(f"[DAG] '{task.name}' starting (deps satisfied: {task.depends_on})")
                    future = pool.submit(self._run_one, task)
                    in_flight[future] = task.name

                if not in_flight:
                    if pending:
                        stuck = list(pending)
                        logger.error(f"[DAG] Stuck — unresolved dependencies for: {stuck} "
                                     "(cycle or unknown task name)")
                        for name in stuck:
                            r = TaskResult(name)
                            r.status = "failed"
                            r.error = "unresolved dependency (cycle or unknown task name)"
                            done[name] = r
                    break

                # Block for at least one completion, then re-check readiness so
                # newly-unblocked tasks start immediately rather than waiting
                # for the whole in-flight batch.
                for future in as_completed(list(in_flight)):
                    name = in_flight.pop(future)
                    task_result = future.result()
                    done[name] = task_result
                    level = logger.success if task_result.status == "success" else logger.warning
                    level(f"[DAG] '{name}' finished: {task_result.status} "
                          f"({task_result.attempts} attempt(s))")
                    break

        results = {name: r.value for name, r in done.items() if r.status == "success"}
        errors = [(name, r.error) for name, r in done.items() if r.status in ("failed", "skipped")]

        succeeded = sum(1 for r in done.values() if r.status == "success")
        logger.info(f"[DAG] Done: {succeeded}/{len(done)} tasks succeeded")

        return results, errors, done
