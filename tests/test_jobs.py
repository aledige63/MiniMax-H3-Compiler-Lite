import threading
import unittest

from app.domain import CompileResult, Metrics
from app.jobs import JobWorker


class WorkerQueueTests(unittest.TestCase):
    def test_queue_time_includes_wait_behind_previous_job(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        state = {"now": 10.0, "calls": [], "results": {}}

        class Repository:
            def start_job(self, job_id):
                return job_id, "fixture-model"

            def finish_job(self, job_id, result):
                state["results"][job_id] = result
                if job_id == "second":
                    finished.set()

        class Client:
            def compile(self, data, model):
                state["calls"].append(data)
                if data == "first":
                    entered.set()
                    release.wait(timeout=3)
                return CompileResult(status="proposal", input_hash=data,
                    metrics=Metrics(model=model, digest="fixture-digest", inference_calls=1,
                        input_hash=data, input_chars=10, queue_s=.25, wall_s=5.0))

        worker = JobWorker(Repository(), Client(), clock=lambda: state["now"])
        try:
            worker.submit("first")
            self.assertTrue(entered.wait(timeout=3))
            state["now"] = 20.0
            worker.submit("second")
            self.assertEqual(state["calls"], ["first"])
            state["now"] = 35.0
            release.set()
            self.assertTrue(finished.wait(timeout=3))
            self.assertEqual(state["calls"], ["first", "second"])
            first = state["results"]["first"].metrics
            second = state["results"]["second"].metrics
            self.assertEqual(first.queue_s, .25)
            self.assertEqual(first.wall_s, 5.0)
            self.assertEqual(second.queue_s, 15.25)
            self.assertEqual(second.wall_s, 20.0)
            self.assertEqual(second.inference_calls, 1)
        finally:
            release.set()
            worker.close()


if __name__ == "__main__":
    unittest.main()
