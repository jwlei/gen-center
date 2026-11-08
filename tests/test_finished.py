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
