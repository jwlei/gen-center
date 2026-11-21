"""The settings box's own requests: its settings, the local models, how much room the disks have."""
import os
import shutil
import threading

from flask import Blueprint, request

from panel import server

bp = Blueprint("settings", __name__)


@bp.route("/api/settings", methods=["GET", "POST"])
@server.password_required
def api_settings():
    if request.method == "POST":
        changes = request.get_json(silent=True)
        if not isinstance(changes, dict):
            return {"ok": False, "error": "Settings are a JSON object."}, 400
        try:
            saved = server.settings.update(changes)
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        except OSError as e:
            return {"ok": False, "error": f"Could not save it: {e}"}, 500
        if "low_priority" in changes:
            threading.Thread(target=server.apply_comfyui_priority, daemon=True).start()
        return {"ok": True, "settings": saved}
    return {"ok": True, "settings": server.settings.load(), "local_models": server.settings.local_models(), "disk": disk_usage()}


@bp.route("/api/local-models")
@server.password_required
def api_local_models():
    return {"ok": True, "models": server.settings.local_models()}


_disk_cache = {"at": 0.0, "value": None}


def disk_usage():
    """The disk the videos and images go to: what's free, and what the three output folders take."""
    if _disk_cache["value"] and server.time.time() - _disk_cache["at"] < 30:
        return _disk_cache["value"]
    folder = server.FOLDERS["output"]
    while folder and not os.path.exists(folder) and os.path.dirname(folder) != folder:
        folder = os.path.dirname(folder)
    try:
        usage = shutil.disk_usage(folder)
    except OSError:
        return None
    used = 0
    for root in {os.path.abspath(path) for path in server.FOLDERS.values()}:
        for where, _, names in os.walk(root):
            for name in names:
                try:
                    used += os.path.getsize(os.path.join(where, name))
                except OSError:
                    pass
    value = {"free": usage.free, "total": usage.total, "outputs": used,
             "drive": os.path.splitdrive(os.path.abspath(folder))[0] or "/"}
    _disk_cache.update(at=server.time.time(), value=value)
    return value


server.app.register_blueprint(bp)
