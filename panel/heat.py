"""
Settings' GPU heat guard and temperature graph: a background check every few seconds that restarts MSI Afterburner
when the GPU runs hot (gpu_guard.py), the minute-by-minute temperature log it keeps (temperatures.py), and the two
routes the page uses. Added to the panel by panel/app.py; the monitor starts with the panel (server.STARTUP_HOOKS).
"""
import os
import threading
import time

from flask import request

from panel import settings, temperatures
from panel.server import STARTUP_HOOKS, STATUS_HOOKS, app, gpu_stats, job, password_required


def monitor_gpu_heat():
    from panel.gpu_guard import GPUHeatGuard

    guard = GPUHeatGuard(job.log, settings.load, keep=True)
    while not job.closed:
        reading = gpu_stats()
        gpu = reading["temp"] if reading else None
        guard.check(gpu)
        # Settings' temperature graph: logged every reading, kept a minute at a time.
        try:
            temperature_log().add(gpu=gpu, cpu=temperatures.cpu_temperature())
        except Exception as e:  # The graph must never stop the heat guard
            app.logger.warning("Could not log temperatures: %s", e)
        time.sleep(3)


_temperature_log = None


def temperature_log():
    global _temperature_log
    if _temperature_log is None:
        _temperature_log = temperatures.TemperatureLog()
    return _temperature_log


@app.route("/api/temperatures")
@password_required
def api_temperatures():
    try:
        hours = int(request.args.get("hours", 6))
    except ValueError:
        hours = 0
    if hours not in temperatures.RANGES_HOURS:
        return {"ok": False, "error": f"hours is one of {', '.join(map(str, temperatures.RANGES_HOURS))}."}, 400
    guard = settings.load()
    return {"ok": True, **temperature_log().query(hours),
            "guard": {"on": guard["gpu_guard"], "restart_above": guard["gpu_restart_above"], "rearm_at": guard["gpu_rearm_at"]}}


def start_monitor():
    """Windows only: the guard restarts MSI Afterburner, and the CPU temperature comes from it."""
    if os.name == "nt":
        threading.Thread(target=lambda: monitor_gpu_heat(), daemon=True).start()


STARTUP_HOOKS.append(start_monitor)


def afterburner_status(payload):
    """Whether MSI Afterburner was running at the heat guard's last check, for Settings (None: not known)."""
    from panel import gpu_guard

    payload["afterburner"] = gpu_guard.state["running"]


STATUS_HOOKS.append(afterburner_status)


@app.route("/restart/afterburner", methods=["POST"])
@password_required
def restart_afterburner():
    """Settings' GPU heat guard: MSI Afterburner closed and started again now, with the chosen profile, whatever the heat."""
    from panel import gpu_guard

    profile = settings.load()["gpu_profile"]
    try:
        gpu_guard.restart_afterburner(profile)
    except gpu_guard.Busy as e:
        return {"ok": False, "error": str(e)}, 409
    except (OSError, RuntimeError, gpu_guard.psutil.Error) as e:
        job.log(f"Could not restart MSI Afterburner: {e}")
        return {"ok": False, "error": f"Could not restart MSI Afterburner: {e}"}, 500
    gpu_guard.state["running"] = True
    job.log(f"MSI Afterburner restarted from Settings with profile {profile}.")
    return {"ok": True, "profile": profile}


@app.route("/start/afterburner", methods=["POST"])
@password_required
def start_afterburner():
    """Settings' Start Afterburner: started with the chosen profile if it isn't running, never asking on the PC for
    administrator rights (its start-at-logon task has them), so it works from a phone."""
    from panel import gpu_guard

    profile = settings.load()["gpu_profile"]
    try:
        started = gpu_guard.start_afterburner(profile)
    except gpu_guard.Busy as e:
        return {"ok": False, "error": str(e)}, 409
    except (OSError, RuntimeError, gpu_guard.psutil.Error) as e:
        job.log(f"Could not start MSI Afterburner: {e}")
        return {"ok": False, "error": f"Could not start MSI Afterburner: {e}"}, 500
    gpu_guard.state["running"] = True
    if started:
        job.log(f"MSI Afterburner started from Settings with profile {profile}.")
    return {"ok": True, "started": started, "profile": profile}
