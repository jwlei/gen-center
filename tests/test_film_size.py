"""A film is joined at its clips' own size: a latent upscale's bigger clips aren't shrunk back to the run's size."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ffmpeg  # noqa: E402
from fakes import make_clip  # noqa: E402
from pipelines.video import media  # noqa: E402


class FilmSizeTest(unittest.TestCase):
    def test_upscaled_clips_keep_their_size_in_the_film(self):
        with tempfile.TemporaryDirectory() as temp:
            clips = [os.path.join(temp, f"shot_{n}.mp4") for n in (1, 2)]
            for clip in clips:
                make_clip(clip, 1)
            # The run was set up at 32x32; the clips came out at 64x64, as a latent upscale makes them.
            size = media.film_size(clips, 32, 32)
            self.assertEqual(size, (64, 64))
            output = os.path.join(temp, "film.mp4")
            media.stitch(clips, os.path.join(temp, "parts"), output, *size, chained=False)
            stream = next(s for s in ffmpeg.probe(output)["streams"] if s["codec_type"] == "video")
            self.assertEqual((stream["width"], stream["height"]), (64, 64))

    def test_unreadable_clips_fall_back_to_the_run_size(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(media.film_size([os.path.join(temp, "missing.mp4")], 352, 704), (352, 704))


if __name__ == "__main__":
    unittest.main()
