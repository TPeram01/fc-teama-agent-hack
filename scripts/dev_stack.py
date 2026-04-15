from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


def _resolve_command(command: str) -> str:
    candidates = [command]
    if os.name == "nt" and Path(command).suffix == "":
        candidates = [f"{command}.cmd", f"{command}.exe", f"{command}.bat", command]

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved

    if command == "npm":
        raise SystemExit(
            "npm was not found on PATH. Install Node.js and npm, then restart your shell."
        )

    raise SystemExit(f"{command} was not found on PATH.")


def _prepare_command(command: list[str]) -> list[str]:
    if not command:
        raise ValueError("Command cannot be empty.")

    return [_resolve_command(command[0]), *command[1:]]


def _stream_output(prefix: str, pipe) -> None:
    for line in iter(pipe.readline, ""):
        print(f"[{prefix}] {line}", end="")


def _spawn_process(
    name: str,
    command: list[str],
    cwd: Path,
) -> subprocess.Popen[str]:
    prepared_command = _prepare_command(command)
    process = subprocess.Popen(
        prepared_command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    if process.stdout is None:
        raise RuntimeError(f"{name} process did not expose stdout.")

    thread = threading.Thread(
        target=_stream_output,
        args=(name, process.stdout),
        daemon=True,
    )
    thread.start()
    return process


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the FastAPI control plane and the Next.js frontend together."
    )
    parser.add_argument(
        "--api-port",
        default="8000",
        help="Port used by the FastAPI server.",
    )
    parser.add_argument(
        "--frontend-port",
        default="3000",
        help="Port used by the Next.js frontend.",
    )
    parser.add_argument(
        "--install-frontend",
        action="store_true",
        help="Run npm install in frontend/ before starting the stack.",
    )
    args = parser.parse_args()

    if args.install_frontend:
        subprocess.run(
            _prepare_command(["npm", "install"]),
            cwd=FRONTEND_DIR,
            check=True,
        )
    elif not (FRONTEND_DIR / "node_modules").exists():
        print(
            "frontend/node_modules is missing. Run "
            "`uv run scripts/dev_stack.py --install-frontend` first."
        )
        raise SystemExit(1)

    processes = [
        _spawn_process(
            "api",
            [
                "uv",
                "run",
                "uvicorn",
                "api:app",
                "--reload",
                "--host",
                "0.0.0.0",
                "--port",
                args.api_port,
            ],
            ROOT_DIR,
        ),
        _spawn_process(
            "frontend",
            [
                "npm",
                "run",
                "dev",
                "--",
                "--hostname",
                "0.0.0.0",
                "--port",
                args.frontend_port,
            ],
            FRONTEND_DIR,
        ),
    ]

    print(f"FastAPI:   http://127.0.0.1:{args.api_port}")
    print(f"Frontend:  http://127.0.0.1:{args.frontend_port}")
    print("Press Ctrl+C to stop both processes.")

    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is None:
                    continue

                print(f"Process exited with code {return_code}. Shutting down stack.")
                for sibling in processes:
                    if sibling is process:
                        continue
                    _terminate_process(sibling)
                raise SystemExit(return_code)

            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping stack...")
    finally:
        for process in processes:
            _terminate_process(process)


if __name__ == "__main__":
    main()
