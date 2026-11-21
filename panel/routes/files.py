"""What Output serves and changes on disk: films, posters, downloads, opening a folder, deleting."""
import os

from flask import Blueprint, abort, send_file

from panel import server

bp = Blueprint("files", __name__)


@bp.route("/videos/<folder>/<path:name>")
@server.password_required
def video_file(folder, name):
    return send_file(server.safe_video_path(folder, name), mimetype="video/mp4", conditional=True)


@bp.route("/posters/<folder>/<path:name>")
@server.password_required
def poster(folder, name):
    """The picture a Short shows before it plays, as videos only load once you press play."""
    stem = os.path.splitext(server.safe_video_path(folder, name))[0]
    for candidate in (f"{stem}.jpg", f"{stem}.still.jpg"):
        if os.path.exists(candidate):
            return send_file(candidate, mimetype="image/jpeg", max_age=3600)
    abort(404)


@bp.route("/download/<folder>/<path:name>")
@server.password_required
def download(folder, name):
    return send_file(server.safe_video_path(folder, name), as_attachment=True, download_name=name)


@bp.route("/folders/<folder>/open", methods=["POST"])
@server.password_required
def open_folder(folder):
    """Shows a tab's folder in File Explorer. Made here if need be: nothing has been uploaded at first."""
    if not server.can_open_folders():
        abort(403)
    if folder not in server.FOLDERS:
        abort(404)
    try:
        os.makedirs(server.FOLDERS[folder], exist_ok=True)
        os.startfile(server.FOLDERS[folder])
    except OSError as e:
        return {"ok": False, "error": f"Could not open the folder: {e}"}, 500
    return {"ok": True}


@bp.route("/delete/<folder>/<path:name>", methods=["POST"])
@server.password_required
def delete(folder, name):
    path = server.safe_video_path(folder, name)
    film = os.path.basename(path)
    # Which run made it, asked before the run goes with it; an upscaled copy is only itself.
    run_id = None
    if server.FOLDER_PIPELINES.get(folder) == "video":
        run_id = None if server.UPSCALED.search(film) else server.run_of_film(film)
    reply = server.PIPELINES[server.FOLDER_PIPELINES.get(folder, "shorts")].delete_video(folder, path)
    body = reply[0] if isinstance(reply, tuple) else reply
    if isinstance(body, dict) and body.get("ok"):
        # Deleted from Output, it is gone from Finished too.
        for queue in server.QUEUES.values():
            queue.forget(run_id=run_id, film=film)
    return reply


server.app.register_blueprint(bp)
