from apscheduler.schedulers.background import BackgroundScheduler

class WorkflowScheduler:
    def __init__(self): self.scheduler = BackgroundScheduler()
    def add_interval(self, job_id, seconds, callback):
        if self.scheduler.get_job(job_id) is not None:
            self.scheduler.remove_job(job_id)
        self.scheduler.add_job(callback, "interval", seconds=seconds, id=job_id, replace_existing=True)
    def start(self): self.scheduler.start()
    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

