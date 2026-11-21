"""The machine: shutting it down when the queue empties, restarting the panel or ComfyUI, starting ComfyUI."""
import subprocess
import threading

from flask import Blueprint, abort, request

from panel import server

bp = Blueprint("system", __name__)


@bp.route("/api/poweroff", methods=["GET", "POST"])
@server.password_required
def api_poweroff():
    """Shut the PC down once the queue is empty: for this session only, so it is never saved."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        arm = bool(body.get("armed"))
        with server._poweroff_lock:
            was_counting = server._poweroff["at"] is not None
            server._poweroff.update(armed=arm, idle_since=None, at=None if not arm else server._poweroff["at"])
            if arm and not server._poweroff.get("watching"):
                server._poweroff["watching"] = True
                threading.Thread(target=server._poweroff_loop, daemon=True).start()
            if not arm:
                server._poweroff["at"] = None
        if not arm and was_counting:
            server._run_shutdown(cancel=True)
    return {"ok": True, **server.poweroff_state()}


@bp.route("/restart/panel", methods=["POST"])
@server.password_required
def restart_panel():
    """
    Starts the panel again, to load new code. Only when nothing is running that it would cut short, unless the body
    says force: then the run and upload going are stopped first (as Stop does: the run waits in the queue, which comes
    back on hold), for when one is stuck.
    """
    force = bool((request.get_json(silent=True) or {}).get("force"))
    if force:
        if server.job.running:
            server.job.log("⚠️ The panel was force-restarted from Settings while this was running.")
        server.stop_run()
        server.uploads.stop()
        if server.job.running or server.uploads.running:
            return {"ok": False, "error": f"{server.STOP_FAILED} Then restart again."}, 500
    with server.run_queue.lock:
        if not force and server.restart_blocked():
            return {"ok": False, "error": "A run, upload or prompt writer is going, or a queue is about to start one. Wait for it first."}, 409
        command, flags = server.respawn_command()
        subprocess.Popen(command, cwd=server.PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
        server._panel_closing = True
        server.exit_soon()
    return {"ok": True}


@bp.route("/restart/comfyui", methods=["POST"])
@server.password_required
def restart_comfyui():
    """
    Closes ComfyUI and starts it again. Not while a run or prompt writer is going, unless the body says force: then at
    once, whatever the panel believes is going (that run fails, and is tried once more: restart_reason).
    """
    force = bool((request.get_json(silent=True) or {}).get("force"))
    with server.run_queue.lock:
        if not force and (server.job.running or server._writing_prompt or server._comfy_restarting or server._comfy_freeing):
            return {"ok": False, "error": "A run or prompt writer is going, or ComfyUI is restarting. Wait for it first."}, 409
        if not server.comfyui_launcher():
            return {"ok": False, "error": "COMFYUI_LAUNCHER isn't set in .env, so the panel can't start ComfyUI again."}, 400
        if force and server.job.running:
            server.job.log("⚠️ ComfyUI was force-restarted from Settings while this was running.")
        server.restart_comfyui_in_background(force=force)
    return {"ok": True}


@bp.route("/shutdown", methods=["POST"])
@server.password_required
def shutdown():
    """
    Force-stops everything the panel is doing, then the server itself: started
    from start_webapp.pyw it has no window to close.
    """
    with server.run_queue.lock:
        if server._writing_prompt:
            return {"ok": False, "error": "Wait for the prompt writer to finish before shutting down."}, 409
        for queue in server.QUEUES.values():
            queue.close()
        server._panel_closing = True
    server.stop_run()
    server.uploads.stop()
    # Exiting now would leave it running with nothing in the panel to stop it.
    if server.job.running or server.uploads.running:
        return {"ok": False, "error": f"{server.STOP_FAILED} Then shut down again."}, 500
    server.close_comfyui()
    # Reply first, then exit, so the browser gets its answer.
    server.exit_soon()
    return {"ok": True}


@bp.route("/launcher/refresh", methods=["POST"])
def launcher_refresh():
    """
    Exits if the code changed after this server started, so start_webapp.pyw can
    start a fresh one. Only answers this PC, and never stops a run or a queue that's going.
    """
    if not server.on_this_pc():
        abort(403)
    try:
        code_changed_at = float(request.form.get("code_changed_at", 0))
    except ValueError:
        abort(400)
    with server.run_queue.lock:
        if code_changed_at <= server.STARTED_AT or server.restart_blocked():
            return {"restarting": False}
        server._panel_closing = True
        server.exit_soon()
    return {"restarting": True}


@bp.route("/comfyui/start", methods=["POST"])
@server.password_required
def comfyui_start():
    """A manual start replaces any local ComfyUI instance; automatic starts don't."""
    with server.run_queue.lock:
        if server.restart_blocked():
            return {"ok": False, "error": "A run or upload is going, or a queue is about to start one. Stop it or let it finish first."}, 409
        try:
            server.start_fresh_comfyui()
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}, 500
    return {"ok": True}


server.app.register_blueprint(bp)
