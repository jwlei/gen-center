import copy
import unittest
from contextlib import ExitStack
from unittest import mock

import fakes  # noqa: F401
from panel import app as _routes  # noqa: F401
from panel import server
from panel.catalogue import CatalogueCache


class CatalogueTest(unittest.TestCase):
    def test_scans_are_cached_but_active_work_refreshes_and_mutations_invalidate(self):
        cache = CatalogueCache()
        build = mock.Mock(return_value=({"videos": []}, {}))
        with mock.patch("panel.catalogue.time.monotonic", return_value=100) as clock:
            first = cache.get(build, active=True)
            clock.return_value = 101
            self.assertEqual(cache.get(build, active=True), first)
            self.assertEqual(build.call_count, 1)
            clock.return_value = 102
            self.assertEqual(cache.get(build, active=True)[2], first[2], "unchanged content retains its revision")
            self.assertEqual(build.call_count, 2)
            cache.invalidate()
            build.return_value = ({"videos": ["new.mp4"]}, {})
            self.assertNotEqual(cache.get(build)[2], first[2])

    def test_compact_status_omits_unchanged_catalogue_and_keeps_legacy_response(self):
        data = {"videos": {"output": [{"name": f"film-{i}.mp4", "topic": "x" * 100} for i in range(1000)],
                           "uploaded": [], "video": [], "image": []}, "image_sets": []}
        cache = CatalogueCache()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(server, "_catalogue_cache", cache))
            scan = stack.enter_context(mock.patch.object(server, "_scan_output_catalogue", return_value=(data, {})))
            stack.enter_context(mock.patch.object(server.run_queue, "snapshot_with_job", side_effect=lambda: (
                {"running": False, "pipeline": "image", "progress": {}},
                {"items": [], "results": [], "current": None, "held": True},
            )))
            for name, value in {
                "stopped_runs": [], "made_in_this_run": [], "films_of_runs": {},
                "comfyui_online": False, "comfyui_listening": False, "comfyui_launcher": "",
                "ram_stats": {}, "gpu_stats": {}, "cached_quota": {}, "poweroff_state": {},
                "private_mode": False,
            }.items():
                stack.enter_context(mock.patch.object(server, name, return_value=value))
            stack.enter_context(mock.patch.object(server, "STATUS_HOOKS", []))
            client = server.app.test_client()
            first = client.get("/api/status?catalogue_revision=")
            self.assertEqual(first.status_code, 200)
            revision = first.json["catalogue_revision"]
            second = client.get("/api/status", query_string={"catalogue_revision": revision})
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json["catalogue_revision"], revision)
            self.assertNotIn("videos", second.json)
            self.assertNotIn("image_sets", second.json)
            self.assertIn("queue", second.json)
            self.assertLess(len(second.data), len(first.data) // 10)
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(data["image_sets"], [], "per-request markings never mutate cached data")
            with mock.patch.object(server, "list_videos", return_value=[]), mock.patch.object(server, "saved_runs", return_value=[]):
                legacy = client.get("/api/status")
            self.assertIn("videos", legacy.json)
            self.assertIn("image_sets", legacy.json)
            changed = copy.deepcopy(data)
            changed["videos"]["output"].append({"name": "new.mp4"})
            scan.return_value = changed, {}
            cache.invalidate()
            self.assertNotEqual(client.get("/api/status?catalogue_revision=" + revision).json["catalogue_revision"], revision)
