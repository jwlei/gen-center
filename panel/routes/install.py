"""
The panel as an app on a phone's home screen: its manifest (name, icons, colours, where it opens) and its service
worker. Both open without signing in: the browser fetches them without the login cookie, and neither says anything
private. Installing needs the HTTPS address (app_link.py).
"""
import json

from flask import Blueprint, send_from_directory, url_for

from panel import server, settings

bp = Blueprint("install", __name__)
APP_NAME = "gen-center"
# Long-press the icon: straight to a side.
SHORTCUTS = (("Shorts", "/shorts"), ("Video", "/video"), ("Image", "/image"))


def theme_colours():
    """(background, panel) of the theme in use: the splash screen and the system bars match the page."""
    theme = settings.THEMES.get(settings.load().get("theme")) or settings.THEMES["standard"]
    return theme[1], theme[2]


@bp.route("/manifest.webmanifest")
def manifest():
    background, _panel = theme_colours()
    icon = lambda name, size, purpose: {"src": url_for("static", filename=f"icons/{name}"), "sizes": f"{size}x{size}",
                                        "type": "image/png", "purpose": purpose}
    body = {
        "id": "/",
        "name": APP_NAME,
        "short_name": APP_NAME,
        "description": "AI video and image generation on your own GPU.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": background,
        "theme_color": background,
        "icons": [icon("icon-192.png", 192, "any"), icon("icon-512.png", 512, "any"),
                  icon("maskable-512.png", 512, "maskable")],
        "shortcuts": [{"name": name, "url": path, "icons": [icon("icon-192.png", 192, "any")]} for name, path in SHORTCUTS],
    }
    response = server.app.response_class(json.dumps(body), mimetype="application/manifest+json")
    response.headers["Cache-Control"] = "no-cache"  # A new theme's colours on the next install or update
    return response


@bp.route("/sw.js")
def service_worker():
    """From the site's root, so it looks after every page (a worker only reaches pages under its own path)."""
    response = send_from_directory(server.app.static_folder, "sw.js", mimetype="text/javascript", max_age=0)
    response.headers["Cache-Control"] = "no-cache"  # The browser checks it on each visit: a changed one takes over
    return response


@bp.route("/offline")
def offline():
    """What the app shows when the panel can't be reached: kept by the service worker, never fetched when it's needed."""
    return send_from_directory(server.app.static_folder, "offline.html", mimetype="text/html", max_age=0)


server.app.register_blueprint(bp)
