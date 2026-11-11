import io
import json
import os
import runpy
import sys
import unittest
from unittest import mock


LAUNCHER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "start_webapp.pyw")


class LauncherTest(unittest.TestCase):
    def test_browser_only_opens_for_the_normal_shortcut(self):
        for args, opens_browser in (([], True), (["--headless"], False)):
            with self.subTest(args=args), mock.patch.object(sys, "argv", [LAUNCHER, *args]), \
                    mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(json.dumps({"restarting": False}).encode())), \
                    mock.patch("webbrowser.open") as browser, mock.patch("subprocess.Popen") as process:
                runpy.run_path(LAUNCHER, run_name="__main__")
                self.assertEqual(browser.called, opens_browser)
                process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
