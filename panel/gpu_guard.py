"""Recover Afterburner's fan control once per GPU heat event."""
import os
import subprocess

import psutil


RESTART_ABOVE = 78
REARM_AT = 75


def restart_afterburner():
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
    process = subprocess.Popen([executable], cwd=os.path.dirname(executable),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        return
    raise RuntimeError(f"MSI Afterburner exited immediately (exit {code}). Check its permissions.")


class GPUHeatGuard:
    def __init__(self, note):
        self.armed = True
        self.note = note

    def check(self, temperature):
        if temperature is None:
            return
        if temperature <= REARM_AT:
            self.armed = True
        elif temperature > RESTART_ABOVE and self.armed:
            self.armed = False
            self.note(f"GPU is {temperature} C: restarting MSI Afterburner.")
            try:
                restart_afterburner()
            except (OSError, RuntimeError, psutil.Error) as error:
                self.note(f"Could not restart MSI Afterburner: {error}")
            else:
                self.note("MSI Afterburner restarted.")
