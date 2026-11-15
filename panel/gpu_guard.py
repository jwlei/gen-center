"""Recover Afterburner's fan control once per GPU heat event, as Settings' GPU heat guard says."""
import os
import subprocess
import threading

import psutil


# The defaults, as it ran before it was a setting (panel/settings.py keeps the chosen ones).
RESTART_ABOVE = 78
REARM_AT = 75
PROFILE = 3
ELEVATION_REQUIRED = 740
# One restart at a time: Settings' Restart Afterburner and a heat event could otherwise start two.
_restarting = threading.Lock()


class Busy(RuntimeError):
    """MSI Afterburner is already being restarted."""


def profile_argument(profile):
    """Afterburner's command line switch that applies one of its five saved profiles."""
    return f"-Profile{int(profile)}"


def restart_afterburner(profile=PROFILE):
    """Closes this user's MSI Afterburner and starts it again with that profile (1-5). Raises Busy, RuntimeError, OSError."""
    if not _restarting.acquire(blocking=False):
        raise Busy("MSI Afterburner is already restarting.")
    try:
        _restart(profile_argument(profile))
    finally:
        _restarting.release()


def _restart(argument):
    owner = psutil.Process().username()
    processes = [process for process in psutil.process_iter(["name", "username", "exe"])
                 if (process.info["name"] or "").lower() == "msiafterburner.exe"
                 and process.info["username"] == owner]
    executable = next((process.info["exe"] for process in processes if process.info["exe"]), None)
    if not executable:
        executable = next((os.path.join(root, "MSI Afterburner", "MSIAfterburner.exe")
                           for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"))
                           if root and os.path.isfile(os.path.join(root, "MSI Afterburner", "MSIAfterburner.exe"))), None)
    if not executable:
        raise RuntimeError("MSI Afterburner was not found. Start it once or install it in Program Files.")
    for process in processes:
        process.terminate()
    _, alive = psutil.wait_procs(processes, timeout=5)
    if alive:
        raise RuntimeError("MSI Afterburner did not exit; another instance was not started.")
    try:
        process = subprocess.Popen([executable, argument], cwd=os.path.dirname(executable),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as error:
        if getattr(error, "winerror", None) != ELEVATION_REQUIRED:
            raise
        # Afterburner asks for administrator rights and this process has none: ShellExecute can ask for them.
        import ctypes
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, argument,
                                                     os.path.dirname(executable), 1)
        if result <= 32:
            raise RuntimeError(f"MSI Afterburner needs administrator rights and they were not given (code {result}).") from error
        return
    try:
        code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        return
    raise RuntimeError(f"MSI Afterburner exited immediately (exit {code}). Check its permissions.")


def default_config():
    return {"gpu_guard": True, "gpu_restart_above": RESTART_ABOVE, "gpu_rearm_at": REARM_AT, "gpu_profile": PROFILE}


class GPUHeatGuard:
    """
    Restarts Afterburner once the GPU is above the restart temperature, then not again until it has cooled down to the
    cool-down temperature. config: the settings, read at every check, so a change in Settings counts at once.
    """
    def __init__(self, note, config=default_config):
        self.armed = True
        self.note = note
        self.config = config

    def check(self, temperature):
        if temperature is None:
            return
        config = self.config()
        if temperature <= config["gpu_rearm_at"]:
            self.armed = True
        elif temperature > config["gpu_restart_above"] and self.armed and config["gpu_guard"]:
            self.armed = False
            profile = config["gpu_profile"]
            self.note(f"GPU is {temperature} C: restarting MSI Afterburner with profile {profile}.")
            try:
                restart_afterburner(profile)
            except (OSError, RuntimeError, psutil.Error) as error:
                self.note(f"Could not restart MSI Afterburner: {error}")
            else:
                self.note("MSI Afterburner restarted.")
