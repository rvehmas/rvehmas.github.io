#!/usr/bin/env python3
"""
run_notebook.py

Usage:
    python run_notebook.py path/to/notebook.ipynb

What it does:
  - Creates (or reuses) a virtual environment in ".venv" next to this script.
  - Ensures pip exists inside the venv (bootstraps with ensurepip if needed).
  - Installs packages from "requirements.txt" next to this script (and ensures voila is installed).
  - Starts Voilà to serve the given notebook, hides code cells, and opens it in a browser.
  - Runs Voilà in detached mode so your terminal remains free.

Works on Windows and Linux/macOS.
"""

import argparse
import os
import sys
import subprocess
import venv
import shutil
import socket
import time
import webbrowser
from pathlib import Path


# -----------------------
# Paths and venv helpers
# -----------------------

def script_dir() -> Path:
    return Path(__file__).resolve().parent

def venv_dir() -> Path:
    return script_dir() / ".venv"

def venv_python_executable(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    else:
        return venv_path / "bin" / "python"

def ensure_venv(venv_path: Path) -> None:
    """
    Create the venv if missing. (We repair pip later if needed.)
    """
    if not venv_path.exists():
        print(f"[info] Creating virtual environment at {venv_path} ...")
        builder = venv.EnvBuilder(with_pip=True, upgrade_deps=False)
        builder.create(venv_path)
    else:
        print(f"[info] Reusing existing virtual environment at {venv_path}")

def recreate_venv(venv_path: Path) -> None:
    print(f"[info] Recreating virtual environment at {venv_path} ...")
    shutil.rmtree(venv_path, ignore_errors=True)
    builder = venv.EnvBuilder(with_pip=True, upgrade_deps=False, clear=True)
    builder.create(venv_path)


# -----------------------
# Subprocess utilities
# -----------------------

def run(cmd, cwd=None, env=None) -> int:
    print(f"[cmd] {' '.join(map(str, cmd))}")
    try:
        return subprocess.call(cmd, cwd=cwd, env=env)
    except FileNotFoundError:
        print(f"[error] Command not found: {cmd[0]}")
        return 127

def has_pip(python: Path) -> bool:
    return run([str(python), "-m", "pip", "--version"]) == 0

def bootstrap_pip(python: Path) -> bool:
    """
    Try to install/repair pip inside the given interpreter using ensurepip.
    Returns True on success, False otherwise.
    """
    print("[info] Bootstrapping pip with ensurepip ...")
    code = run([str(python), "-m", "ensurepip", "--upgrade"])
    if code == 0:
        # sanity check and small upgrade of pip
        if has_pip(python):
            run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
            return True
    else:
        print("[warn] 'ensurepip' failed or is unavailable for this Python.")
    return False


# -----------------------
# PIP install logic
# -----------------------

def pip_install(python: Path, requirements_file: Path) -> None:
    # Make sure pip itself is up to date enough
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])

    # Install from requirements.txt if present
    if requirements_file.exists():
        print(f"[info] Installing dependencies from {requirements_file} ...")
        code = run([str(python), "-m", "pip", "install", "-r", str(requirements_file)])
        if code != 0:
            print("[warn] Failed installing from requirements.txt (continuing).")
    else:
        print(f"[info] No requirements.txt found at {requirements_file} (skipping).")

    # Ensure voila is installed
    print("[info] Ensuring 'voila' is installed ...")
    code = run([str(python), "-m", "pip", "install", "voila"])
    if code != 0:
        sys.exit("[error] Failed to install Voilà.")


# -----------------------
# Networking helpers
# -----------------------

def find_free_port(host="127.0.0.1", start=8866, max_tries=50) -> int:
    # Try start..start+max_tries, else ask OS for any free port
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    # Fallback: let OS pick
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]

def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.3)
    return False


# -----------------------
# Main
# -----------------------

def main():
    parser = argparse.ArgumentParser(description="Run a notebook with Voilà using a local virtual environment.")
    parser.add_argument("notebook", help="Path to the .ipynb notebook to serve with Voilà")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: auto-find)")
    args = parser.parse_args()

    nb_path = Path(args.notebook).resolve()
    if not nb_path.exists() or nb_path.suffix.lower() != ".ipynb":
        sys.exit(f"[error] Notebook not found or not a .ipynb file: {nb_path}")

    vpath = venv_dir()
    ensure_venv(vpath)

    py = venv_python_executable(vpath)
    if not py.exists():
        sys.exit("[error] Could not find Python inside the virtual environment.")

    # Ensure pip exists in this venv (handle Debian/Ubuntu corner cases)
    if not has_pip(py):
        if not bootstrap_pip(py):
            print(
                "[error] Could not bootstrap pip inside the venv.\n"
                "On Debian/Ubuntu, make sure 'python3-venv' is installed:\n"
                "    sudo apt-get update && sudo apt-get install -y python3-venv\n"
                "Attempting to recreate the venv automatically ..."
            )
            recreate_venv(vpath)
            py = venv_python_executable(vpath)
            if not has_pip(py) and not bootstrap_pip(py):
                sys.exit("[error] Still no pip after recreating the venv. Aborting.")

    requirements = script_dir() / "requirements.txt"
    pip_install(py, requirements)

    port = args.port or find_free_port(args.host)
    url = f"http://{args.host}:{port}/"

    voila_cmd = [
        str(py), "-m", "voila", str(nb_path),
        "--no-browser",
        "--port", str(port),
        "--Voila.ip", args.host,
        "--Voila.strip_sources=True",   # hide code cells
    ]

    print(f"[info] Starting Voilà at {url}")
    # Start Voilà server in detached mode
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            voila_cmd,
            creationflags=DETACHED_PROCESS,
            close_fds=True
        )
    else:
        subprocess.Popen(
            voila_cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True
        )

    if wait_for_port(args.host, port, timeout=30.0):
        print("[info] Voilà is up — opening your browser ...")
        webbrowser.open_new(url)
    else:
        print("[warn] Timed out waiting for Voilà. You can try opening the URL manually:")
        print(f"       {url}")

    print("[info] Voilà is running in the background. Use Task Manager/`ps` + `kill` to stop it if needed.")


if __name__ == "__main__":
    main()
