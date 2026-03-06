import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(os.getenv("NUTRIPILOT_WORKSPACE_ROOT", SCRIPT_DIR.parent)).resolve()
BACKEND_DIR = WORKSPACE_ROOT / "nuitri_pilot_backend"
FRONTEND_DIR = WORKSPACE_ROOT / "nuitri_pilot_frontend"


def log(msg: str) -> None:
    print(msg, flush=True)


def _bool_env(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def validate_workspace_layout() -> None:
    missing = []
    if not BACKEND_DIR.exists():
        missing.append(str(BACKEND_DIR))
    if not FRONTEND_DIR.exists():
        missing.append(str(FRONTEND_DIR))
    if missing:
        log("ERROR: Could not find expected NutriPilot workspace folders.")
        log(f"SCRIPT_DIR: {SCRIPT_DIR}")
        log(f"WORKSPACE_ROOT: {WORKSPACE_ROOT}")
        for path in missing:
            log(f"- missing: {path}")
        log(
            "Fix: run this from nuitri_pilot_testing or set "
            "NUTRIPILOT_WORKSPACE_ROOT to a folder containing both repos."
        )
        sys.exit(2)


def wait_for_backend(url: str, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as resp:
                if 200 <= int(resp.status) < 500:
                    return True
        except HTTPError as e:
            if 200 <= int(getattr(e, "code", 500)) < 500:
                return True
        except URLError:
            pass
        except Exception:
            pass
        time.sleep(1)
    return False


def kill_process_tree(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    log(f"Stopped {name}.")


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run NutriPilot backend + frontend together.")
    p.add_argument("--backend-host", default=os.getenv("BACKEND_HOST", "0.0.0.0"))
    p.add_argument("--backend-port", type=int, default=int(os.getenv("BACKEND_PORT", "8000")))
    p.add_argument(
        "--api-base-url",
        default=os.getenv("FRONTEND_API_BASE_URL", "http://10.0.2.2:8000"),
        help="Frontend API URL passed to emulator run script.",
    )
    p.add_argument("--emulator-id", default=os.getenv("ANDROID_EMULATOR_ID", "Medium_Phone_API_36.0"))
    p.add_argument("--device-id", default=os.getenv("ANDROID_DEVICE_ID", "emulator-5554"))
    p.add_argument("--backend-warmup-timeout", type=int, default=int(os.getenv("BACKEND_WARMUP_TIMEOUT_S", "30")))
    p.add_argument("--backend-only", action="store_true", help="Start only backend.")
    p.add_argument("--no-reload", action="store_true", help="Disable uvicorn reload.")
    p.add_argument("--no-preload-images", action="store_true", help="Disable emulator image preload.")
    return p.parse_args()


def start_backend(args: argparse.Namespace) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "src.main:app",
        "--host",
        args.backend_host,
        "--port",
        str(args.backend_port),
    ]
    if not args.no_reload:
        cmd.append("--reload")

    log("\nStarting backend...")
    log(f"CMD: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(BACKEND_DIR), env=dict(os.environ), shell=False)
    return proc


def start_frontend(args: argparse.Namespace) -> subprocess.Popen:
    preload = "0" if args.no_preload_images else "1"
    if os.name == "nt":
        script = FRONTEND_DIR / "scripts" / "run_android_emulator.ps1"
        if not script.exists():
            raise FileNotFoundError(f"Missing frontend script: {script}")
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ApiBaseUrl",
            args.api_base_url,
            "-EmulatorId",
            args.emulator_id,
            "-DeviceId",
            args.device_id,
            "-PreloadBackendImages",
            preload,
        ]
    else:
        cmd = [
            "flutter",
            "run",
            "-d",
            args.device_id,
            f"--dart-define=API_BASE_URL={args.api_base_url}",
        ]

    log("\nStarting frontend...")
    log(f"CMD: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(FRONTEND_DIR), env=dict(os.environ), shell=False)
    return proc


def main() -> None:
    args = build_args()
    validate_workspace_layout()

    backend_proc: subprocess.Popen | None = None
    frontend_proc: subprocess.Popen | None = None

    try:
        backend_proc = start_backend(args)
        time.sleep(1.5)
        if backend_proc.poll() is not None:
            raise RuntimeError(f"Backend exited immediately with code {backend_proc.returncode}")

        health_url = f"http://127.0.0.1:{args.backend_port}/"
        if wait_for_backend(health_url, args.backend_warmup_timeout):
            log(f"Backend is reachable at {health_url}")
        else:
            log(f"WARNING: backend did not become reachable within {args.backend_warmup_timeout}s at {health_url}")

        if not args.backend_only:
            frontend_proc = start_frontend(args)
            time.sleep(1.5)
            if frontend_proc.poll() is not None:
                raise RuntimeError(f"Frontend exited immediately with code {frontend_proc.returncode}")

        log("\nNutriPilot app runner is active. Press Ctrl+C to stop both processes.")

        while True:
            if backend_proc.poll() is not None:
                raise RuntimeError(f"Backend process exited with code {backend_proc.returncode}")
            if frontend_proc and frontend_proc.poll() is not None:
                raise RuntimeError(f"Frontend process exited with code {frontend_proc.returncode}")
            time.sleep(1)

    except KeyboardInterrupt:
        log("\nCtrl+C received. Shutting down...")
    except Exception as e:
        log(f"\nRunner error: {e}")
        raise
    finally:
        if frontend_proc is not None:
            kill_process_tree(frontend_proc, "frontend")
        if backend_proc is not None:
            kill_process_tree(backend_proc, "backend")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
