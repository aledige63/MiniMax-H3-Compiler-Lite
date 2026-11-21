"""Un worker per l'inferenza; le richieste HTTP non aspettano il modello."""
import queue
import threading
import time

from app.domain import CompileResult


class JobWorker:
    def __init__(self, repository, client, *, clock=time.perf_counter, assistance=None, connections=None):
        self.repository, self.client = repository, client
        self.clock = clock
        self.assistance = assistance
        self.connections = connections
        self.pending = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="h3-inference", daemon=True)
        self.thread.start()

    def submit(self, job_id):
        self.pending.put(('text', str(job_id), self.clock()))

    def submit_assistance(self, job_id):
        self.pending.put(('assistance', str(job_id), self.clock()))

    def submit_trial(self, job_id):
        self.pending.put(('trial', str(job_id), self.clock()))

    def _run(self):
        while (pending := self.pending.get()) is not None:
            kind, job_id, submitted_at = pending
            queue_s = max(0.0, self.clock() - submitted_at)
            try:
                if kind == 'trial':
                    self.connections.run_trial(job_id, queue_s)
                    continue
                if kind == 'assistance':
                    self.assistance.run(job_id, queue_s)
                    continue
                work = self.repository.start_job(job_id)
                if work is None:
                    continue
                data, model = work
                try:
                    result = self.client.compile(data, model)
                except Exception:
                    # Nessun traceback/payload nel log o nella risposta pubblica.
                    result = CompileResult(status="error", input_hash=self.repository.job(job_id).input_hash,
                        error_code="internal_error", issues=["Compilazione non riuscita. Il lavoro è conservato; riprovare esplicitamente."])
                if result.metrics is not None:
                    metrics = result.metrics.model_copy(update={
                        "queue_s": result.metrics.queue_s + queue_s,
                        "wall_s": result.metrics.wall_s + queue_s,
                    })
                    result = result.model_copy(update={"metrics": metrics})
                self.repository.finish_job(job_id, result)
            finally:
                self.pending.task_done()

    def close(self):
        self.pending.put(None)
        self.thread.join(timeout=1)
