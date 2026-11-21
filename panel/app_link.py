"""
The panel over HTTPS on the tailnet, beside its plain address: https://pc.tailnet-name.ts.net:8443.

A phone only installs a site as an app (its own icon, full screen, no browser bar) from HTTPS, and the panel's
Tailscale address is plain http://100.x.y.z. So the tailnet's own certificate for this PC (tailscale cert, Let's
Encrypt) is served on a second port by the same app: the phone still signs in, and still counts as another device.
(Not `tailscale serve`: it proxies from localhost, which the panel takes for this PC.)

On every address of the PC, the home network's too: with the router's DNS answering the tailnet name with the PC's
home address, the same installed app works at home with Tailscale off (README, "As an app on your phone").

Started once Tailscale is up (server.connect_tailscale). Renewed each day: `tailscale cert` only makes a new
certificate near the old one's end, and the server takes it for the next connection without a restart.
"""
import logging
import os
import ssl
import threading
import time

from core.paths import PROJECT_ROOT
from panel import tailscale

# The certificate and its key: private, kept out of git (.gitignore).
CERT_DIR = os.path.join(PROJECT_ROOT, "certs")
DEFAULT_PORT = 8443
RENEW_EVERY = 24 * 3600
NO_NAME = ("Tailscale gave this PC no name: turn on MagicDNS in Tailscale's admin console (DNS page), "
           "then restart the panel.")

# What Settings, Connection shows: the address to open on a phone, or why there's none.
state = {"url": None, "problem": None}


def url():
    return state["url"]


def problem():
    return state["problem"]


def _files(name):
    return os.path.join(CERT_DIR, f"{name}.crt"), os.path.join(CERT_DIR, f"{name}.key")


def _certify(name):
    """The certificate made or renewed: (cert file, key file), or raises RuntimeError with what went wrong."""
    os.makedirs(CERT_DIR, exist_ok=True)
    cert_file, key_file = _files(name)
    wrong = tailscale.cert(name, cert_file, key_file)
    if wrong:
        raise RuntimeError(wrong)
    return cert_file, key_file


def _renew(context, name):
    """Each day: a renewed certificate loaded into the server's context, which each new connection reads."""
    while True:
        time.sleep(RENEW_EVERY)
        try:
            context.load_cert_chain(*_certify(name))
        except (RuntimeError, OSError, ssl.SSLError) as error:
            logging.getLogger(__name__).warning("The HTTPS certificate wasn't renewed: %s", error)


def start(app, port=DEFAULT_PORT, host="0.0.0.0"):
    """
    Serves app over HTTPS under the PC's tailnet name, on host (every address of the PC). Returns the address, or
    None with state["problem"] saying why. Its server runs in a thread of its own until the panel stops.
    """
    from werkzeug.serving import make_server

    state.update(url=None, problem=None)
    name = tailscale.dns_name()
    if not name:
        state["problem"] = NO_NAME
        return None
    try:
        cert_file, key_file = _certify(name)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        server = make_server(host, port, app, threaded=True, ssl_context=context)
    except (RuntimeError, OSError, ssl.SSLError) as error:
        state["problem"] = str(error) if isinstance(error, RuntimeError) else f"HTTPS couldn't start on port {port}: {error}"
        return None
    threading.Thread(target=server.serve_forever, name="https", daemon=True).start()
    threading.Thread(target=_renew, args=(context, name), name="https-renew", daemon=True).start()
    state["url"] = f"https://{name}:{port}"
    return state["url"]
