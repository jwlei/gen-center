"""
Starting Tailscale with the panel, against a fake CLI: signing in to a real tailnet
isn't something a test can do. The panel's side uses the real routes.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: F401  (keeps the real .env out of the tests)

from panel import app as _both_pipelines  # noqa: F401
from panel import server as webapp
from panel import app_link, tailscale

RUNNING = {"BackendState": "Running", "TailscaleIPs": ["100.64.0.7", "fd7a:115c:a1e0::7"]}


class FakeCli:
    """Answers `status --json` with the current state; a bare `up` moves Stopped to Running."""

    def __init__(self, state, tray_open=True):
        self.state = state
        self.tray_open = tray_open
        self.ups = []

    def run(self, argv, **kwargs):
        if argv[0] == "tasklist":
            return subprocess.CompletedProcess(argv, 0, "tailscale-ipn.exe  14188 Console" if self.tray_open else "INFO: No tasks")
        if argv[1:] == ["status", "--json"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.state))
        self.ups.append(argv[1:])
        self.state = RUNNING
        return subprocess.CompletedProcess(argv, 0, "")


class TailscaleTest(unittest.TestCase):
    def use(self, cli, installed=True):
        for patcher in (mock.patch.object(tailscale, "program", lambda name: f"C:/ts/{name}.exe" if installed else None),
                        mock.patch.object(tailscale.subprocess, "run", cli.run),
                        mock.patch.object(tailscale.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)
        popen = mock.patch.object(tailscale.subprocess, "Popen").start()
        self.addCleanup(mock.patch.stopall)
        return popen

    def test_not_installed_does_nothing(self):
        cli = FakeCli(RUNNING)
        popen = self.use(cli, installed=False)
        self.assertEqual(tailscale.connect(8800), (None, None))
        self.assertEqual(tailscale.reach(8800), (None, None))
        popen.assert_not_called()

    def test_connected_gives_the_ipv4_address(self):
        cli = FakeCli(RUNNING)
        self.use(cli)
        self.assertEqual(tailscale.connect(8800), ("http://100.64.0.7:8800", None))
        self.assertEqual(cli.ups, [], "already connected, so nothing to ask for")

    def test_disconnected_reconnects_with_a_bare_up(self):
        cli = FakeCli({"BackendState": "Stopped", "TailscaleIPs": []})
        self.use(cli)
        self.assertEqual(tailscale.connect(8800), ("http://100.64.0.7:8800", None))
        self.assertEqual(cli.ups, [["up"]])

    def test_signed_out_says_so_without_hanging_on_up(self):
        cli = FakeCli({"BackendState": "NeedsLogin", "TailscaleIPs": []})
        self.use(cli)
        with mock.patch.object(tailscale, "CONNECT_WAIT", 0):
            self.assertEqual(tailscale.connect(8800), (None, tailscale.SIGN_IN))
        self.assertEqual(cli.ups, [], "`up` would block on signing in")

    def test_service_down_says_not_connected(self):
        cli = FakeCli(RUNNING)
        self.use(cli)
        with mock.patch.object(tailscale, "status", return_value=None):
            self.assertEqual(tailscale.reach(8800), (None, tailscale.NOT_CONNECTED))

    @unittest.skipUnless(os.name == "nt", "the tray app is Windows-only")
    def test_tray_starts_only_when_closed(self):
        popen = self.use(FakeCli(RUNNING, tray_open=True))
        tailscale.start_tray()
        popen.assert_not_called()
        popen = self.use(FakeCli(RUNNING, tray_open=False))
        tailscale.start_tray()
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["C:/ts/tailscale-ipn.exe"])


class PanelOverTailscaleTest(unittest.TestCase):
    TAILNET_PHONE = {"REMOTE_ADDR": "100.64.0.9"}

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"APP_PASSWORD": "open sesame", "COMFYUI_URL": "http://127.0.0.1:9"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = webapp.app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["authed"] = True

    def test_panel_shows_the_address(self):
        self.sign_in()
        with mock.patch.object(webapp.tailscale, "reach", return_value=("http://100.64.0.7:8800", None)) as reach:
            page = self.client.get("/", base_url="http://localhost:8800").data.decode()
        reach.assert_called_once_with("8800")
        self.assertIn("<code>http://100.64.0.7:8800</code>", page)

    def test_panel_says_whats_in_the_way(self):
        self.sign_in()
        with mock.patch.object(webapp.tailscale, "reach", return_value=(None, tailscale.SIGN_IN)):
            self.assertIn(tailscale.SIGN_IN, self.client.get("/").data.decode())

    def test_panel_says_nothing_without_tailscale(self):
        self.sign_in()
        with mock.patch.object(webapp.tailscale, "reach", return_value=(None, None)):
            self.assertNotIn("Phone (anywhere", self.client.get("/").data.decode())

    def test_no_password_means_no_phone_so_it_isnt_asked(self):
        with mock.patch.dict(os.environ, {"APP_PASSWORD": ""}), mock.patch.object(webapp.tailscale, "reach") as reach:
            self.client.get("/")
        reach.assert_not_called()

    def test_a_phone_on_the_tailnet_isnt_this_pc(self):
        self.assertEqual(self.client.get("/", environ_base=self.TAILNET_PHONE).status_code, 302, "it still signs in")
        self.assertEqual(self.client.post("/launcher/refresh", data={"code_changed_at": "1"},
                                          environ_base=self.TAILNET_PHONE).status_code, 403)


class StartupTest(unittest.TestCase):
    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["webapp.py", *args]), \
                mock.patch.dict(os.environ, {"APP_PASSWORD": "open sesame"}), \
                mock.patch.object(webapp.app, "run"), \
                mock.patch.object(webapp, "ComfyMonitor"), \
                mock.patch("panel.heat.monitor_gpu_heat"), \
                mock.patch.object(webapp.tailscale, "connect", return_value=(None, None)) as connect, \
                mock.patch.object(webapp.threading, "Thread", side_effect=lambda target, args=(), daemon=None: mock.Mock(start=lambda: target(*args))):
            webapp.main()
        return connect

    def test_listening_to_other_devices_starts_tailscale(self):
        self.run_main("--host", "0.0.0.0", "--port", "8800").assert_called_once_with(8800)

    def test_connected_it_also_serves_https_for_the_app(self):
        with mock.patch.object(webapp.tailscale, "connect", return_value=("http://100.64.0.7:8800", None)),                 mock.patch.object(webapp.app_link, "start", return_value="https://pc.tail.ts.net:9443") as start:
            webapp.connect_tailscale(8800, 9443)
            start.assert_called_once_with(webapp.app, 9443)
            start.reset_mock()
            webapp.connect_tailscale(8800, 0)
            start.assert_not_called()

    def test_this_pc_only_leaves_it_alone(self):
        self.run_main().assert_not_called()


class CertificateTest(unittest.TestCase):
    """The tailnet's HTTPS certificate, against a fake `tailscale cert`."""

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        for patcher in (mock.patch.object(tailscale, "program", lambda name: f"C:/ts/{name}.exe"),
                        mock.patch.object(app_link, "CERT_DIR", self.temp)):
            patcher.start()
            self.addCleanup(patcher.stop)
        app_link.state.update(url=None, problem=None)

    def cli(self, said="", works=True, name="pc.tail.ts.net."):
        def run(argv, **kwargs):
            if argv[1:] == ["status", "--json"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps({**RUNNING, "Self": {"DNSName": name}}))
            if works:
                for flag in ("--cert-file", "--key-file"):
                    with open(argv[argv.index(flag) + 1], "w") as f:
                        f.write("pem")
            return subprocess.CompletedProcess(argv, 0 if works else 1, "", said)
        patcher = mock.patch.object(tailscale.subprocess, "run", side_effect=run)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_its_name_has_no_trailing_dot(self):
        self.cli()
        self.assertEqual(tailscale.dns_name(), "pc.tail.ts.net")

    def test_made_into_the_files_asked_for(self):
        run = self.cli()
        cert, key = os.path.join(self.temp, "a.crt"), os.path.join(self.temp, "a.key")
        self.assertIsNone(tailscale.cert("pc.tail.ts.net", cert, key))
        self.assertEqual(run.call_args[0][0][1:], ["cert", "--cert-file", cert, "--key-file", key, "pc.tail.ts.net"])

    def test_https_off_in_the_tailnet_says_where_to_turn_it_on(self):
        self.cli(said="500 Internal Server Error: your Tailscale account does not support getting TLS certs", works=False)
        self.assertEqual(tailscale.cert("pc.tail.ts.net", "a", "b"), tailscale.HTTPS_OFF)

    def test_another_failure_says_what_tailscale_said(self):
        self.cli(said="Access denied: cert access denied", works=False)
        self.assertIn("Access denied", tailscale.cert("pc.tail.ts.net", "a", "b"))

    def test_started_on_every_address_with_the_certificate(self):
        self.cli()
        context = mock.Mock()
        with mock.patch.object(app_link.ssl, "SSLContext", return_value=context),                 mock.patch("werkzeug.serving.make_server") as make_server,                 mock.patch.object(app_link.threading, "Thread") as thread:
            self.assertEqual(app_link.start(webapp.app, 9443), "https://pc.tail.ts.net:9443")
        context.load_cert_chain.assert_called_once_with(os.path.join(self.temp, "pc.tail.ts.net.crt"),
                                                        os.path.join(self.temp, "pc.tail.ts.net.key"))
        make_server.assert_called_once_with("0.0.0.0", 9443, webapp.app, threaded=True, ssl_context=context)  # The home network too
        self.assertEqual(thread.call_count, 2, "the server, and its daily renewal")
        self.assertEqual((app_link.url(), app_link.problem()), ("https://pc.tail.ts.net:9443", None))

    def test_without_magicdns_there_is_no_name_to_certify(self):
        self.cli(name="")
        self.assertIsNone(app_link.start(webapp.app, 9443))
        self.assertEqual(app_link.problem(), app_link.NO_NAME)

    def test_a_refused_certificate_is_the_problem_shown(self):
        self.cli(said="does not support getting TLS certs", works=False)
        self.assertIsNone(app_link.start(webapp.app, 9443))
        self.assertEqual(app_link.problem(), tailscale.HTTPS_OFF)


if __name__ == "__main__":
    unittest.main()
