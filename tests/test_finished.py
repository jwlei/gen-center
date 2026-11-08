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

    def test_clear_route_empties_runs_and_uploads(self):
        client = server.app.test_client()
        with client.session_transaction() as session:
            session["authed"] = True
        with mock.patch.object(server.run_queue, "clear_results") as runs, \
                mock.patch.object(server.upload_queue, "clear_results") as uploads:
            self.assertEqual(client.post("/queue/finished/clear").get_json(), {"ok": True})
        runs.assert_called_once()
        uploads.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class AimdoRetryTest(unittest.TestCase):
    """ComfyUI's aimdo memory compile error: restart ComfyUI and try once more, then Failed and restart again."""

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

    def test_other_failures_are_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            job = mock.Mock(closed=False, progress={}, returncode=1, stopped=False, batches=0, first_line=0,
                            lines=[{"n": 1, "text": "❌ CUDA error: out of memory"}])
            queue = server.JobQueue(job, lambda item: None, path=os.path.join(folder, "queue_runs.json"))
            with mock.patch.object(server, "run_queue", queue), \
                    mock.patch.object(server, "restart_comfyui_in_background") as restart:
                queue.current = {"id": 4, "label": "B", "pipeline": "video", "argv": []}
                queue._finish_current()
                restart.assert_not_called()
                self.assertEqual([r["outcome"] for r in queue.results], ["failed"])
