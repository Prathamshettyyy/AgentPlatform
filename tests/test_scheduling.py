from app.scheduling import WorkflowScheduler


def test_scheduler_replaces_duplicate_interval_jobs():
    scheduler = WorkflowScheduler()
    scheduler.add_interval("demo", 60, lambda: None)
    scheduler.add_interval("demo", 60, lambda: None)
    assert len(scheduler.scheduler.get_jobs()) == 1
    scheduler.shutdown()
