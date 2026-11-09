"""This app leaves nothing in ComfyUI's input and output folders, and never touches anything else there."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import comfy_files  # noqa: E402


def touch(*parts):
    path = os.path.join(*parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    return path


class ComfyFilesTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        patch = mock.patch.object(comfy_files, "comfyui_folders", return_value=[self.root])
        patch.start()
        self.addCleanup(patch.stop)

    def test_its_uploads_go_and_yours_stay(self):
        ours = [touch(self.root, "input", name) for name in ("autocomfyui_image_1.png", "autogen_run_1_audio.wav",
                                                             "pipeline_no_image.png", "aishorts_avatar_ref.png")]
        yours = [touch(self.root, "input", "holiday.jpg"), touch(self.root, "input", "prompts", "autocomfyui_kept.png")]
        self.assertEqual(comfy_files.clean_inputs(), 4)
        self.assertFalse(any(os.path.exists(path) for path in ours))
        self.assertTrue(all(os.path.exists(path) for path in yours), "your files, and anything in a folder of yours, stay")

    def test_a_downloaded_output_goes_and_only_from_output(self):
        made = touch(self.root, "output", "NVIDIA_RTX_VSR_Long_Video", "film_00001.mp4")
        self.assertTrue(comfy_files.forget_output("film_00001.mp4", "NVIDIA_RTX_VSR_Long_Video", "output"))
        self.assertFalse(os.path.exists(made))
        temp = touch(self.root, "temp", "ComfyUI_temp_00001.png")
        self.assertFalse(comfy_files.forget_output("ComfyUI_temp_00001.png", "", "temp"), "ComfyUI empties its temp itself")
        self.assertTrue(os.path.exists(temp))
        outside = touch(self.root, "elsewhere.png")
        self.assertFalse(comfy_files.forget_output("../elsewhere.png", "", "output"), "never outside its output folder")
        self.assertTrue(os.path.exists(outside))

    def test_idle_clears_h3_memory_and_clips_of_runs_gone(self):
        kept = touch(self.root, "output", "autogen_h3_infinite", "run_kept", "clip_00001.safetensors")
        gone = touch(self.root, "output", "autogen_h3_infinite", "run_gone", "clip_00001.safetensors")
        cache = touch(self.root, "output", "minimax_motion_context_cache", "17", "seg_0000.pt")
        yours = touch(self.root, "output", "CivitAI", "mine.png")
        comfy_files.clean_idle({"run_kept"})
        self.assertTrue(os.path.exists(kept), "a run still saved keeps its clips: it continues from them")
        self.assertFalse(os.path.exists(gone) or os.path.exists(cache))
        self.assertTrue(os.path.exists(yours))
        self.assertTrue(comfy_files.forget_h3_run("run_kept"))
        self.assertFalse(os.path.exists(kept), "and they go with the run")

    def test_without_comfyui_found_nothing_is_done(self):
        with mock.patch.object(comfy_files, "comfyui_folders", return_value=[]):
            self.assertEqual(comfy_files.clean_inputs(), 0)
            self.assertEqual(comfy_files.clean_idle(set()), 0)


if __name__ == "__main__":
    unittest.main()
