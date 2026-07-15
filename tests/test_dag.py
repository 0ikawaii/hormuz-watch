import time

from dag import DAG


def _sleepy(seconds=0.3, value="done"):
    def f():
        time.sleep(seconds)
        return value
    return f


def test_independent_tasks_run_concurrently():
    dag = DAG(max_workers=4)
    for name in ("a", "b", "c"):
        dag.add_task(name, _sleepy())

    start = time.time()
    results, errors, states = dag.run()
    elapsed = time.time() - start

    assert elapsed < 0.6, f"tasks did not run concurrently, took {elapsed:.2f}s"
    assert set(results) == {"a", "b", "c"}
    assert not errors


def test_dependency_ordering():
    order = []
    dag = DAG(max_workers=4)

    def mk(name):
        def f():
            order.append(name)
            return name
        return f

    dag.add_task("a", mk("a"))
    dag.add_task("b", mk("b"))
    dag.add_task("d", mk("d"), depends_on=["a", "b"])
    dag.run()

    assert order.index("d") > order.index("a")
    assert order.index("d") > order.index("b")


def test_failed_task_retries_then_skips_downstream():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        raise ValueError("boom")

    dag = DAG(max_workers=2)
    dag.add_task("bad", flaky, max_retries=2, retry_backoff_base=0.01)
    dag.add_task("downstream", lambda: "ok", depends_on=["bad"])
    results, errors, states = dag.run()

    assert attempts["count"] == 3
    assert states["bad"].status == "failed"
    assert states["downstream"].status == "skipped"
    assert "downstream" not in results
