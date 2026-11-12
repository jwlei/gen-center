"""Finished: what ended is kept over a restart, until Clear."""
import json
import os
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  Set isolated paths before importing the application.

from panel import server


class FinishedTest(unittest.TestCase):
    def queue(self, folder):
        job = mock.Mock(closed=False, progress={}, returncode=0)
        return server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))

    def test_finished_outlasts_a_restart_until_cleared(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.queue(folder)
            first._record({"label": "A film", "pipeline": "shorts", "id": 7}, "failed", "exit 1")
            saved = os.path.join(folder, "queue_runs_finished.json")
            self.assertTrue(os.path.exists(saved), "saved beside the queue")

            again = self.queue(folder)
            self.assertEqual([(r["label"], r["outcome"], r["job_id"]) for r in again.results], [("A film", "failed", 7)])
            self.assertEqual(again.next_id, 8, "a new job never takes a kept result's number")

            again.clear_results()
            with open(saved, encoding="utf-8") as f:
                self.assertEqual(json.load(f), [])
            self.assertEqual(self.queue(folder).results, [], "cleared stays cleared")

    def test_only_the_last_twenty_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            for number in range(25):
                queue._record({"label": f"job {number}", "pipeline": "shorts", "id": number}, "done")
            self.assertEqual([r["label"] for r in self.queue(folder).results], [f"job {n}" for n in range(5, 25)])

    def test_a_broken_file_starts_it_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "queue_runs_finished.json"), "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual(self.queue(folder).results, [])

    def test_what_is_deleted_from_output_leaves_finished(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            queue.results = [{"label": "Film", "run_id": "run_1", "film": "Film.mp4"},
                             {"label": "Set", "run_id": "image_1", "film": None},
                             {"label": "Short", "run_id": None, "film": "short.mp4"},
                             {"label": "Other", "run_id": "run_2", "film": "Other.mp4"}]
            queue.forget(run_id="image_1")
            queue.forget(film="short.mp4")
            queue.forget(run_id="run_1", film="Film.mp4")
            self.assertEqual([r["label"] for r in queue.results], ["Other"])
            self.assertEqual([r["label"] for r in self.queue(folder).results], ["Other"], "and stays gone after a restart")

    def test_deleting_a_film_forgets_it_in_both_lists(self):
        client = server.app.test_client()
        with client.session_transaction() as session:
            session["authed"] = True
        with mock.patch.object(server, "safe_video_path", return_value=os.path.join("x", "Film.mp4")), \
                mock.patch.object(server, "run_of_film", return_value="run_1"), \
                mock.patch.dict(server.PIPELINES, {"video": mock.Mock(delete_video=mock.Mock(return_value={"ok": True}))}), \
                mock.patch.object(server.run_queue, "forget") as runs, mock.patch.object(server.upload_queue, "forget") as uploads:
            self.assertTrue(client.post("/delete/video/Film.mp4").get_json()["ok"])
        runs.assert_called_once_with(run_id="run_1", film="Film.mp4")
        uploads.assert_called_once_with(run_id="run_1", film="Film.mp4")

    def test_a_swipe_forgets_one_result_and_it_stays_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = self.queue(folder)
            for number in (1, 2, 3):
                queue._record({"label": f"job {number}", "pipeline": "shorts", "id": number}, "done")
            self.assertTrue(queue.forget_result(2))
            self.assertFalse(queue.forget_result(2), "already gone")
            self.assertEqual([r["label"] for r in self.queue(folder).results], ["job 1", "job 3"], "and after a restart")

    def test_forget_route_takes_the_lane(self):
        client = server.app.test_client()
        with client.session_transaction() as session:
            session["authed"] = True
        with mock.patch.object(server.upload_queue, "forget_result", return_value=True) as uploads:
            self.assertEqual(client.post("/queue/upload/finished/5/forget").get_json(), {"ok": True})
        uploads.assert_called_once_with(5)
        self.assertEqual(client.post("/queue/nope/finished/5/forget").status_code, 404)

    def test_clear_route_only_removes_the_results_the_page_saw(self):
        client = server.app.test_client()
        with client.session_transaction() as session:
            session["authed"] = True
        with tempfile.TemporaryDirectory() as folder:
            runs = self.queue(folder)
            runs.results = [{"label": "Shown", "job_id": 1}, {"label": "Hidden NSFW", "job_id": 2},
                            {"label": "Just finished", "job_id": 3}]
            with mock.patch.dict(server.QUEUES, {"run": runs, "upload": mock.Mock()}):
                reply = client.post("/queue/finished/clear", json={"run": [1], "upload": []})
                self.assertEqual(reply.get_json(), {"ok": True})
                server.QUEUES["upload"].clear_results.assert_called_once_with(set())
            self.assertEqual([r["job_id"] for r in self.queue(folder).results], [2, 3])
        for invalid in (None, {}, {"run": [], "upload": [True]}, {"run": "all", "upload": []}):
            self.assertEqual(client.post("/queue/finished/clear", json=invalid).status_code, 400)


if __name__ == "__main__":
    unittest.main()


class AimdoRetryTest(unittest.TestCase):
    """ComfyUI's aimdo memory compile error: restart ComfyUI and try once more, then Failed and restart again."""

    def test_fatal_log_stops_a_still_running_generation_before_retrying(self):
        for error in ("ComfyUI failed in SamplerCustomAdvanced: aimdo memory compile error",
                      "ComfyUI exited with code 1", "Command returned non-zero exit status 1."):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as folder:
                job = mock.Mock(closed=False, running=True, idle=False, stopped=False, progress={}, returncode=1,
                                batches=0, first_line=8, lines=[{"n": 9, "text": error}])
                queue = server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))
                queue.current = {"id": 3, "label": "Clip", "pipeline": "video", "argv": []}

                def stop(failed=False):
                    self.assertTrue(failed, "a fatal crash is not a user cancellation")
                    job.running = False
                    job.idle = True
                    return True

                job.stop.side_effect = stop
                with mock.patch.object(server, "run_queue", queue), \
                        mock.patch.object(server, "restart_comfyui_in_background", return_value=True) as restart:
                    queue.held = True
                    queue._advance()
                    job.stop.assert_called_once_with(failed=True)
                    restart.assert_called_once()
                    self.assertTrue(queue.items[0]["aimdo_retried"])

    def test_old_fatal_lines_do_not_stop_the_next_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            job = mock.Mock(closed=False, running=True, idle=False, first_line=9,
                            lines=[{"n": 9, "text": "aimdo memory compile error"}])
            queue = server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))
            queue.current = {"id": 3}
            with mock.patch.object(server, "run_queue", queue):
                queue._advance()
            job.stop.assert_not_called()
        for text in ("exited with code 10", "exit 12", "Rendering clip 1"):
            self.assertIsNone(server.live_crash_reason(mock.Mock(first_line=0, lines=[{"n": 1, "text": text}])))

    def test_retried_once_after_a_restart_then_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            job = mock.Mock(closed=False, progress={}, returncode=1, stopped=False, batches=0, first_line=0,
                            lines=[{"n": 1, "text": "❌ MiniMaxH3Sampler: aimdo memory compile error"}])
            queue = server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))
            item = {"id": 3, "label": "A clip", "pipeline": "video", "argv": ["python", "-m", "pipelines.video.main"]}
            with mock.patch.object(server, "run_queue", queue), \
                    mock.patch.object(server, "restart_comfyui_in_background", return_value=True) as restart:
                queue.current = item
                queue._finish_current()
                self.assertEqual(restart.call_count, 1, "restarted before the retry")
                self.assertEqual(queue.results, [], "not Failed yet")
                retry = queue.items[0]
                self.assertTrue(retry["aimdo_retried"])
                self.assertNotIn("later", retry, "goes again on its own")

                queue.items.remove(retry)
                queue.current = retry
                queue._finish_current()
                self.assertEqual(restart.call_count, 2, "restarted again after the second failure")
                self.assertEqual([r["outcome"] for r in queue.results], ["failed"])
                self.assertEqual(queue.items, [], "not retried a second time")
                self.assertNotIn("aimdo_retried", queue.results[0]["job"], "back in Pending, it gets its retry again")

    def test_exit_code_1_restarts_comfyui_and_retries_too(self):
        with tempfile.TemporaryDirectory() as folder:
            job = mock.Mock(closed=False, progress={}, returncode=1, stopped=False, batches=0, first_line=0,
                            lines=[{"n": 1, "text": "❌ CUDA error: out of memory"}])
            queue = server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))
            with mock.patch.object(server, "run_queue", queue), \
                    mock.patch.object(server, "restart_comfyui_in_background", return_value=True) as restart:
                queue.current = {"id": 4, "label": "B", "pipeline": "video", "argv": []}
                queue._finish_current()
                restart.assert_called_once()
                self.assertEqual(queue.results, [], "not Failed yet")
                self.assertTrue(queue.items[0]["aimdo_retried"])
                retry = queue.items.pop(0)
                queue.current = retry
                queue._finish_current()
                self.assertEqual(restart.call_count, 2)
                self.assertEqual([r["outcome"] for r in queue.results], ["failed"])

    def test_other_failures_are_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            job = mock.Mock(closed=False, progress={}, returncode=2, stopped=False, batches=0, first_line=0,
                            lines=[{"n": 1, "text": "❌ CUDA error: out of memory"}])
            queue = server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))
            with mock.patch.object(server, "run_queue", queue), \
                    mock.patch.object(server, "restart_comfyui_in_background") as restart:
                queue.current = {"id": 4, "label": "B", "pipeline": "video", "argv": []}
                queue._finish_current()
                restart.assert_not_called()
                self.assertEqual([r["outcome"] for r in queue.results], ["failed"])
