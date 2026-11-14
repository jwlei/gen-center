"""Install the cleanup acknowledgement route; restart idle ComfyUI afterwards."""
import argparse
import os
from pathlib import Path
import shutil

from dotenv import load_dotenv


def main():
    project = Path(__file__).resolve().parent.parent
    load_dotenv(project / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-root", type=Path, help="ComfyUI directory containing server.py")
    args = parser.parse_args()
    root = args.comfy_root
    if root is None:
        configured = os.getenv("H3IR_COMFY_ROOT")
        launcher = os.getenv("COMFYUI_LAUNCHER")
        if not configured and not launcher:
            parser.error("Set COMFYUI_LAUNCHER or supply --comfy-root.")
        root = Path(configured) if configured else Path(launcher).parent / "ComfyUI"
    if not (root / "server.py").is_file() or not (root / "execution.py").is_file():
        parser.error(f"Not a ComfyUI directory: {root}")
    target = root / "custom_nodes" / "gen_center_cleanup"
    installed = target / "__init__.py"
    if installed.exists() and not installed.read_text(encoding="utf-8").startswith('"""Acknowledged cleanup on ComfyUI'):
        parser.error(f"An unrelated integration already uses {target}; refusing to overwrite it.")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project / "comfyui" / "gen_center_cleanup" / "__init__.py", installed)
    print(f"Installed verified cleanup integration into {target}. Restart ComfyUI when idle.")


if __name__ == "__main__":
    main()
