"""Recover Afterburner's fan control once per GPU heat event, as Settings' GPU heat guard says."""
import os
import subprocess
import threading
import time

import psutil


# The defaults, as it ran before it was a setting (panel/settings.py keeps the chosen ones).
RESTART_ABOVE = 78
REARM_AT = 75
PROFILE = 3
ELEVATION_REQUIRED = 740
# One restart at a time: Settings' Restart Afterburner and a heat event could otherwise start two.
_restarting = threading.Lock()
# Found not running with the guard on, it's started, but tried at most once a minute: one that won't start isn't
# tried every few seconds.
START_EVERY = 60
# Whether it was running at the guard's last check, for Settings (None: not looked yet, or not on Windows).
state = {"running": None}


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


def _gone(process):
    """Whether this Afterburner has exited, asked in ways it allows."""
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        return not psutil.pid_exists(process.pid)


def _afterburners():
    """This user's running MSI Afterburners."""
    owner = psutil.Process().username()
    return [process for process in psutil.process_iter(["name", "username", "exe"])
            if (process.info["name"] or "").lower() == "msiafterburner.exe" and process.info["username"] == owner]


def afterburner_running():
    return any(not _gone(process) for process in _afterburners())


def start_afterburner(profile=PROFILE):
    """Starts MSI Afterburner with that profile if it isn't running, never asking for administrator rights. Returns
    whether it started it. Raises Busy (a restart going), RuntimeError, OSError."""
    if not _restarting.acquire(blocking=False):
        raise Busy("MSI Afterburner is already restarting.")
    try:
        if afterburner_running():
            return False
        _restart(profile_argument(profile), ask=False)
        return True
    finally:
        _restarting.release()


def _start_task():
    """Afterburner's own start-at-logon task, which runs it with administrator rights without asking. Whether it ran."""
    try:
        done = subprocess.run(["schtasks", "/run", "/tn", "MSIAfterburner"], capture_output=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _restart(argument, ask=True):
    """
    Closes this user's Afterburner, if running, and starts it with argument. Needing administrator rights, ask: Windows
    asks for them; else its start-at-logon task starts it (with its start-up profile rather than this one).
    """
    processes = _afterburners()
    executable = next((process.info["exe"] for process in processes if process.info["exe"]), None)
    if not executable:
        executable = next((os.path.join(root, "MSI Afterburner", "MSIAfterburner.exe")
                           for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"))
                           if root and os.path.isfile(os.path.join(root, "MSI Afterburner", "MSIAfterburner.exe"))), None)
    if not executable:
        raise RuntimeError("MSI Afterburner was not found. Start it once or install it in Program Files.")
    for process in processes:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    # Not psutil.wait_procs: Afterburner lets this process close it but not wait on it (AccessDenied), which left it
    # closed and never started again. Whether it's still there can be asked, so that is asked until it's gone.
    deadline = time.monotonic() + 5
    while not all(_gone(process) for process in processes) and time.monotonic() < deadline:
        time.sleep(0.1)
    if not all(_gone(process) for process in processes):
        raise RuntimeError("MSI Afterburner did not exit; another instance was not started.")
    try:
        process = subprocess.Popen([executable, argument], cwd=os.path.dirname(executable),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as error:
        if getattr(error, "winerror", None) != ELEVATION_REQUIRED:
            raise
        if not ask:
            if _start_task():
                return
            raise RuntimeError("MSI Afterburner needs administrator rights: start it, or tap Restart Afterburner to be asked for them.") from error
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
    def __init__(self, note, config=default_config, keep=False):
        self.armed = True
        self.note = note
        self.config = config
        # keep: also see that Afterburner is running (keep_running), as the panel's monitor does.
        self.keep = keep
        self.tried_start = None

    def keep_running(self, config):
        """Afterburner looked for, for Settings, and with the guard on, started if it isn't running."""
        try:
            running = afterburner_running()
        except psutil.Error:
            return
        state["running"] = running
        if running or not config["gpu_guard"] or _restarting.locked():
            return
        now = time.monotonic()
        if self.tried_start is not None and now - self.tried_start < START_EVERY:
            return
        self.tried_start = now
        profile = config["gpu_profile"]
        try:
            if start_afterburner(profile):
                self.note(f"MSI Afterburner wasn't running: started it with profile {profile}.")
                state["running"] = True
        except Busy:
            pass
        except (OSError, RuntimeError, psutil.Error) as error:
            self.note(f"MSI Afterburner isn't running, and could not be started: {error}")

    def check(self, temperature):
        config = self.config()
        if self.keep:
            self.keep_running(config)
        if temperature is None:
            return
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
