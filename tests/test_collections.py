"""Collections: images and films moved in one at a time, shown only there, each keeping all that made it."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: E402,F401  Set isolated paths before importing the application.
from PIL import Image  # noqa: E402

from panel import app as _sides  # noqa: E402,F401
from panel import collections, server  # noqa: E402
from pipelines.image.run_state import RunState  # noqa: E402


class CollectionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        for patch in (mock.patch.object(collections, "PATH", os.path.join(self.temp, "collections.json")),
                      mock.patch.dict(collections.FOLDERS, {"video": os.path.join(self.temp, "video")})):
            patch.start()
            self.addCleanup(patch.stop)
        os.makedirs(collections.FOLDERS["video"])
        self.client = server.app.test_client()
        with self.client.session_transaction() as session:
            session["authed"] = True

    def make_set(self, count=2):
        state = RunState.new("a cat", count, True, 64, 64)
        state.update(output_name=f"cats_{state.id}", title="Cats",
                     shots=[{"number": n, "title": f"Version {n}", "prompt": "a cat", "file": f"cat_{n}.png"} for n in range(1, count + 1)])
        os.makedirs(state.output_dir, exist_ok=True)
        for shot in state.shots:
            Image.new("RGB", (8, 8)).save(state.image_path(shot))
        self.addCleanup(state.remove)
        return state

    def payload(self, state, films=()):
        return {"image_sets": [{"id": state.id, "nsfw": False, "images": [{"position": i, "file": s["file"]} for i, s in enumerate(state.shots, 1)]}],
                "videos": {"video": [{"name": name, "nsfw": True} for name in films]}}

    def move(self, **body):
        return self.client.post("/api/collections/move", json=body)

    def test_an_image_moved_is_only_in_its_collection(self):
        state = self.make_set()
        reply = self.move(kind="image", run=state.id, file="cat_2.png", new="Favourites").get_json()
        self.assertTrue(reply["ok"])
        payload = self.payload(state)
        collections.apply(payload)
        images = payload["image_sets"][0]["images"]
        self.assertEqual([image.get("collection") for image in images], [None, reply["collection"]["id"]], "marked, so Output leaves it out")
        self.assertEqual(payload["collections"], [{"id": reply["collection"]["id"], "name": "Favourites", "nsfw": False,
                                                    "items": [{"kind": "image", "set": state.id, "file": "cat_2.png"}], "folded": False}])
        self.assertEqual(self.move(kind="image", run=state.id, file="cat_2.png").status_code, 404, "into a collection only")
        self.assertEqual(self.move(kind="image", run=state.id, file="gone.png", new="X").status_code, 404)

    def test_a_list_short_for_a_moment_drops_nothing_and_a_deleted_file_goes(self):
        state = self.make_set()
        self.move(kind="image", run=state.id, file="cat_1.png", new="Keep")
        # The sets not read yet (just after a restart): the image is still on disk, so it stays.
        collections.apply({"image_sets": [], "videos": {"video": []}})
        self.assertEqual([i["file"] for i in collections._read()[0]["items"]], ["cat_1.png"])
        os.remove(os.path.join(state.output_dir, "cat_1.png"))
        collections.apply({"image_sets": [], "videos": {"video": []}})
        self.assertEqual(collections._read()[0]["items"], [], "its file deleted: it goes")

    def test_one_collection_to_another_and_a_film_too(self):
        state = self.make_set()
        first = self.move(kind="image", run=state.id, file="cat_1.png", new="A").get_json()["collection"]["id"]
        second = self.client.post("/api/collections", json={"name": "B"}).get_json()["collection"]["id"]
        self.assertTrue(self.move(kind="image", run=state.id, file="cat_1.png", to=second).get_json()["ok"])
        open(os.path.join(collections.FOLDERS["video"], "Film.mp4"), "wb").close()
        with mock.patch.object(collections.server, "run_of_film", return_value=None):
            self.assertTrue(self.move(kind="film", name="Film.mp4", to=second).get_json()["ok"])
        payload = self.payload(state, films=["Film.mp4"])
        collections.apply(payload)
        shown = {c["id"]: c for c in payload["collections"]}
        self.assertEqual(shown[first]["items"], [], "it left the first")
        self.assertEqual([item["kind"] for item in shown[second]["items"]], ["image", "film"], "in the order they came")
        self.assertTrue(shown[second]["nsfw"], "an NSFW film makes the collection NSFW")
        self.assertEqual(payload["videos"]["video"][0]["collection"], second)

    def test_folded_or_open_is_kept_with_it(self):
        made = self.client.post("/api/collections", json={"name": "F"}).get_json()["collection"]
        url = f"/api/collections/{made['id']}/fold"
        self.assertEqual(self.client.post(url, json={"folded": "yes"}).status_code, 400)
        self.assertTrue(self.client.post(url, json={"folded": True}).get_json()["ok"])
        self.assertTrue(collections._read()[0]["folded"])

    def test_rename_needs_a_name(self):
        made = self.client.post("/api/collections", json={"name": "  Old  "}).get_json()["collection"]
        self.assertEqual(made["name"], "Old")
        self.assertEqual(self.client.post(f"/api/collections/{made['id']}/rename", json={"name": " "}).status_code, 400)
        self.assertTrue(self.client.post(f"/api/collections/{made['id']}/rename", json={"name": "New"}).get_json()["ok"])
        self.assertEqual(collections._read()[0]["name"], "New")

    def test_deleting_its_set_spares_what_moved_and_deleting_the_collection_deletes_it(self):
        state = self.make_set()
        home = self.move(kind="image", run=state.id, file="cat_2.png", new="Keep").get_json()["collection"]["id"]
        self.assertTrue(self.client.post(f"/image-runs/{state.id}/delete").get_json()["ok"])
        left = RunState.load(state.id)
        self.assertEqual([shot["file"] for shot in left.shots], ["cat_2.png"], "the set keeps only what moved")
        self.assertFalse(os.path.exists(os.path.join(state.output_dir, "cat_1.png")))
        self.assertTrue(os.path.exists(os.path.join(state.output_dir, "cat_2.png")))
        self.assertTrue(self.client.post(f"/api/collections/{home}/delete").get_json()["ok"])
        self.assertIsNone(RunState.load(state.id), "its last image deleted, the set goes with it")
        self.assertEqual(collections._read(), [])

    def test_arranging_a_collection_and_a_set(self):
        state = self.make_set(3)
        home = self.move(kind="image", run=state.id, file="cat_1.png", new="Mine").get_json()["collection"]["id"]
        self.move(kind="image", run=state.id, file="cat_2.png", to=home)
        open(os.path.join(collections.FOLDERS["video"], "F.mp4"), "wb").close()
        with mock.patch.object(collections.server, "run_of_film", return_value=None):
            self.move(kind="film", name="F.mp4", to=home)
        url = f"/api/collections/{home}/order"
        images = [{"kind": "image", "run": state.id, "file": f} for f in ("cat_2.png", "cat_1.png")]
        self.assertTrue(self.client.post(url, json={"items": images}).get_json()["ok"])
        self.assertEqual([i.get("file") or i.get("name") for i in collections._read()[0]["items"]], ["cat_2.png", "cat_1.png", "F.mp4"],
                         "its images in the new order, its videos kept as they were")
        self.assertEqual(self.client.post(url, json={"items": images[:1]}).status_code, 409, "all of an album, or nothing")
        # A set: its images by their files, in the order asked.
        set_url = f"/image-runs/{state.id}/order"
        self.assertEqual(self.client.post(set_url, json={"files": ["cat_3.png"]}).status_code, 409)
        self.assertTrue(self.client.post(set_url, json={"files": ["cat_3.png", "cat_1.png", "cat_2.png"]}).get_json()["ok"])
        self.assertEqual([shot["file"] for shot in RunState.load(state.id).shots], ["cat_3.png", "cat_1.png", "cat_2.png"])

    def test_an_upscale_of_one_in_a_collection_joins_it(self):
        state = self.make_set()
        home = self.move(kind="image", run=state.id, file="cat_1.png", new="Up").get_json()["collection"]["id"]
        state.shots.insert(1, {"number": 1, "title": "Version 1 · upscaled", "prompt": "a cat", "file": "cat_1_upscaled.png", "upscaled_from": 1})
        state.save()
        item = {"argv": ["python", "-m", "pipelines.image.upscale", "--resume", state.id, "--image", "1", "--file", "cat_1.png"]}
        collections.follow_upscale(item, "done", state, 2, None)
        self.assertEqual([i["file"] for i in collections._find(collections._read(), home)["items"]], ["cat_1.png", "cat_1_upscaled.png"])


if __name__ == "__main__":
    unittest.main()
