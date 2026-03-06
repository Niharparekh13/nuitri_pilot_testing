import os
import platform
import subprocess
import sys
import json
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values  # pip install python-dotenv

# Force UTF-8 on Windows so logs don't get mangled
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(os.getenv("NUTRIPILOT_WORKSPACE_ROOT", SCRIPT_DIR.parent)).resolve()
BACKEND_DIR = WORKSPACE_ROOT / "nuitri_pilot_backend"
FRONTEND_DIR = WORKSPACE_ROOT / "nuitri_pilot_frontend"

LOG_DIR = SCRIPT_DIR / "test_logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Track pass/fail for summary
RESULTS = {
    "backend": "NOT RUN",
    "backend_ai_batch_100": "NOT RUN",
    "frontend_unit": "NOT RUN",
    "frontend_integration": "NOT RUN",
}
REPORTS_OPENED = False


def log(msg: str) -> None:
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _try_get_git_commit(repo_dir: Path) -> str:
    """
    Best-effort git commit hash for audit logs.
    If git isn't available (or repo isn't a git repo), returns "unknown".
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode == 0:
            return (r.stdout or "").strip() or "unknown"
        return "unknown"
    except Exception:
        return "unknown"


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
        for m in missing:
            log(f"- missing: {m}")
        log(
            "Fix: run this from nuitri_pilot_testing or set "
            "NUTRIPILOT_WORKSPACE_ROOT to a folder containing both repos."
        )
        sys.exit(2)


def _find_latest_ai_presentation_html() -> Path | None:
    runs_dir = BACKEND_DIR / "tests" / "ai_eval" / "runs"
    if not runs_dir.exists():
        return None
    htmls = sorted(runs_dir.glob("*_image_batch_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    return htmls[0] if htmls else None


def _auto_open_ai_reports_once() -> None:
    """
    Opens AI HTML reports once per run for quick review/presentation.
    Disable with AUTO_OPEN_AI_REPORTS=0.
    """
    global REPORTS_OPENED
    if REPORTS_OPENED:
        return
    if os.getenv("AUTO_OPEN_AI_REPORTS", "1") != "1":
        return
    if os.name != "nt":
        return

    report_paths: list[Path] = []

    pytest_html = BACKEND_DIR / "test_reports" / "ai_batch" / "ai-batch-pytest-report.html"
    if pytest_html.exists():
        report_paths.append(pytest_html)

    latest_presentation = _find_latest_ai_presentation_html()
    if latest_presentation and latest_presentation.exists():
        report_paths.append(latest_presentation)

    if not report_paths:
        return

    for p in report_paths:
        try:
            os.startfile(str(p))
            log(f"Opened report: {p}")
        except Exception as e:
            log(f"Could not auto-open report {p}: {e}")

    REPORTS_OPENED = True


def _log_latest_ai_image_batch_summary() -> None:
    """
    Reads the newest image batch run artifact and logs key counts + sample feedback.
    """
    runs_dir = BACKEND_DIR / "tests" / "ai_eval" / "runs"
    if not runs_dir.exists():
        log(f"AI batch summary: runs folder not found at {runs_dir}")
        return

    candidates = sorted(runs_dir.glob("*image_batch_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        log(f"AI batch summary: no image batch artifact found in {runs_dir}")
        return

    latest = candidates[0]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"AI batch summary: failed reading {latest}: {e}")
        return

    summary = payload.get("summary") if isinstance(payload, dict) else {}
    metrics = payload.get("metrics") if isinstance(payload, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(metrics, dict):
        metrics = {}

    scored_count = summary.get("scored_with_feedback_count", metrics.get("scored_with_feedback_count", "unknown"))
    unreadable_count = summary.get("unreadable_feedback_count", metrics.get("unreadable_feedback_count", "unknown"))
    success_calls = metrics.get("success_calls", "unknown")
    expected_fail_calls = metrics.get("expected_fail_calls", "unknown")
    total_returned = metrics.get("total_returned", "unknown")
    success_rate = metrics.get("success_rate", None)
    success_rate_txt = f"{(float(success_rate) * 100):.2f}%" if isinstance(success_rate, (int, float)) else "unknown"

    log("\nAI IMAGE BATCH SUMMARY (latest artifact)")
    log(f"Artifact: {latest}")
    csv_artifact = latest.with_suffix(".csv")
    html_artifact = latest.with_suffix(".html")
    if csv_artifact.exists():
        log(f"Case CSV: {csv_artifact}")
    if html_artifact.exists():
        log(f"Presentation HTML: {html_artifact}")
    log(f"- Scored with feedback (code=0, mark>0): {scored_count}")
    log(f"- 'Could not read ingredient list clearly' feedback count: {unreadable_count}")
    log(f"- Success calls: {success_calls}")
    log(f"- Expected-failure calls: {expected_fail_calls}")
    log(f"- Total returned: {total_returned}")
    log(f"- Success rate: {success_rate_txt}")

    scored_samples = summary.get("scored_with_feedback_samples", [])
    unreadable_samples = summary.get("unreadable_feedback_samples", [])
    if isinstance(scored_samples, list) and scored_samples:
        log("\nSample scored feedbacks:")
        for s in scored_samples[:3]:
            if not isinstance(s, dict):
                continue
            log(f"  {s.get('id')} | mark={s.get('mark')} | feedback={s.get('feedback')}")

    if isinstance(unreadable_samples, list) and unreadable_samples:
        log("\nSample unreadable feedbacks:")
        for s in unreadable_samples[:3]:
            if not isinstance(s, dict):
                continue
            log(
                f"  {s.get('id')} | code={s.get('code')} | mark={s.get('mark')} | "
                f"feedback={s.get('feedback')}"
            )


def run_command(cmd: list[str], cwd: Path, env: dict, title: str) -> int:
    log("\n" + "=" * 60)
    log(title)
    log("=" * 60)
    log(f"CMD: {' '.join(cmd)}")
    log(f"CWD: {cwd}")

    p = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )

    assert p.stdout is not None
    for line in p.stdout:
        # stream to console
        print(line, end="")
        # stream to file
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)

    p.wait()
    log(f"\n[DEBUG] Return code: {p.returncode}\n")
    return int(p.returncode or 0)


def build_backend_env() -> dict:
    env = dict(os.environ)

    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        log(f"ERROR: Backend .env not found at: {env_path}")
        sys.exit(2)

    values = dotenv_values(env_path)
    for k, v in values.items():
        if v is not None and k not in env:
            env[k] = v

    # Map names used across code
    if "OPENAI_API_KEY" not in env and "OPEN_AI_API_KEY" in env:
        env["OPENAI_API_KEY"] = env["OPEN_AI_API_KEY"]
    if "OPEN_AI_API_KEY" not in env and "OPENAI_API_KEY" in env:
        env["OPEN_AI_API_KEY"] = env["OPENAI_API_KEY"]

    if "AI_MODEL" not in env and "OPEN_AI_MODEL" in env:
        env["AI_MODEL"] = env["OPEN_AI_MODEL"]
    if "OPEN_AI_MODEL" not in env and "AI_MODEL" in env:
        env["OPEN_AI_MODEL"] = env["AI_MODEL"]

    # Ensure src imports work
    env["PYTHONPATH"] = str(BACKEND_DIR)

    # Test mode
    env["ENV"] = "test"

    return env


def run_backend_tests() -> None:
    log("\nRUNNING BACKEND TESTS\n")

    env = build_backend_env()

    # ------------------------------
    # Corporate artifacts (JUnit + HTML + Coverage)
    # ------------------------------
    report_dir = BACKEND_DIR / "test_reports"
    report_dir.mkdir(exist_ok=True)

    args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"--junitxml={report_dir / 'pytest-junit.xml'}",
        f"--html={report_dir / 'pytest-report.html'}",
        "--self-contained-html",
        "--cov=src",
        f"--cov-report=xml:{report_dir / 'coverage.xml'}",
        f"--cov-report=html:{report_dir / 'html'}",
        "--cov-report=term-missing",
    ]

    # Skip live AI tests unless explicitly enabled
    if os.getenv("RUN_AI_LIVE") != "1":
        args += ["-m", "not ai_live"]
    else:
        # Keep live AI quality gates aligned with fail-closed unreadable behavior.
        env.setdefault("AI_MIN_MARK", "0")
        env.setdefault("AI_MIN_SUCCESS_RATE", "0.3")
        log("RUN_AI_LIVE=1 -> INCLUDING live AI tests (paid / slower / can be flaky)\n")
        log(
            "Live AI gates: "
            f"AI_MIN_MARK={env.get('AI_MIN_MARK')} | "
            f"AI_MIN_SUCCESS_RATE={env.get('AI_MIN_SUCCESS_RATE')}\n"
        )
        if not env.get("OPENAI_API_KEY"):
            log("ERROR: OPENAI_API_KEY not set after reading backend .env.")
            log("Fix: Ensure .env has OPEN_AI_API_KEY (or OPENAI_API_KEY).")
            RESULTS["backend"] = "FAILED"
            sys.exit(2)
        if os.getenv("RUN_AI_LEGACY_EVAL") != "1":
            args += ["--ignore=tests/ai_eval/test_ai_batch_live.py"]
            log(
                "RUN_AI_LEGACY_EVAL!=1 -> excluding legacy tests/ai_eval/test_ai_batch_live.py "
                "(set RUN_AI_LEGACY_EVAL=1 to include)\n"
            )
        else:
            log("RUN_AI_LEGACY_EVAL=1 -> INCLUDING legacy tests/ai_eval/test_ai_batch_live.py\n")

    rc = run_command(args, cwd=BACKEND_DIR, env=env, title="RUNNING BACKEND PYTEST")

    if rc != 0:
        if os.getenv("RUN_AI_LIVE") == "1":
            _log_latest_ai_image_batch_summary()
            _auto_open_ai_reports_once()
        RESULTS["backend"] = "FAILED"
        log("\nBackend tests FAILED")
        sys.exit(rc)

    RESULTS["backend"] = "PASSED"
    log("\nBackend tests PASSED\n")
    log(f"Backend reports: {report_dir}\n")
    if os.getenv("RUN_AI_LIVE") == "1":
        _log_latest_ai_image_batch_summary()
        _auto_open_ai_reports_once()


def run_backend_ai_batch_100_test() -> None:
    """
    Runs the dedicated 100-case live AI image batch suite.
    Enable with RUN_AI_BATCH_100=1.
    """
    if os.getenv("RUN_AI_BATCH_100") != "1":
        RESULTS["backend_ai_batch_100"] = "SKIPPED (RUN_AI_BATCH_100!=1)"
        log("\nSkipping backend AI batch 100 test (set RUN_AI_BATCH_100=1 to enable).\n")
        return

    # Avoid duplicate paid runs if full live backend suite is already enabled.
    if os.getenv("RUN_AI_LIVE") == "1":
        RESULTS["backend_ai_batch_100"] = "SKIPPED (already covered by RUN_AI_LIVE=1)"
        log("\nSkipping dedicated AI batch 100 test (RUN_AI_LIVE=1 already includes it).\n")
        return

    log("\nRUNNING BACKEND AI IMAGE BATCH (100 LIVE CASES)\n")
    env = build_backend_env()
    report_dir = BACKEND_DIR / "test_reports" / "ai_batch"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not env.get("OPENAI_API_KEY"):
        log("ERROR: OPENAI_API_KEY not set after reading backend .env.")
        log("Fix: Ensure .env has OPEN_AI_API_KEY (or OPENAI_API_KEY).")
        RESULTS["backend_ai_batch_100"] = "FAILED"
        sys.exit(2)

    # Keep this step explicit at 100 unless caller overrides AI_BATCH_N.
    env.setdefault("AI_BATCH_N", "100")
    # Image batch contract allows mark in 0..100; keep default gate aligned.
    env.setdefault("AI_MIN_MARK", "0")
    env.setdefault("AI_MIN_SUCCESS_RATE", "0.3")
    log(
        "Dedicated AI batch gates: "
        f"AI_MIN_MARK={env.get('AI_MIN_MARK')} | "
        f"AI_MIN_SUCCESS_RATE={env.get('AI_MIN_SUCCESS_RATE')}\n"
    )

    args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"--junitxml={report_dir / 'ai-batch-junit.xml'}",
        f"--html={report_dir / 'ai-batch-pytest-report.html'}",
        "--self-contained-html",
        "tests/ai_eval/test_ai_batch_image_live.py::test_ai_image_batch_100_live",
    ]

    rc = run_command(args, cwd=BACKEND_DIR, env=env, title="RUNNING BACKEND AI BATCH 100 (LIVE)")
    _log_latest_ai_image_batch_summary()
    _auto_open_ai_reports_once()
    if rc != 0:
        RESULTS["backend_ai_batch_100"] = "FAILED"
        log("\nBackend AI batch 100 test FAILED")
        sys.exit(rc)

    RESULTS["backend_ai_batch_100"] = "PASSED"
    log("\nBackend AI batch 100 test PASSED\n")
    log(f"AI batch pytest artifacts: {report_dir}\n")


def run_frontend_tests() -> None:
    log("\nRUNNING FRONTEND TESTS\n")

    env = dict(os.environ)
    flutter_cmd = "flutter.bat" if os.name == "nt" else "flutter"

    # Where Flutter will drop artifacts (coverage/ + our logs)
    fe_reports = FRONTEND_DIR / "test_reports"
    fe_reports.mkdir(exist_ok=True)

    # flutter pub get
    rc = run_command([flutter_cmd, "pub", "get"], cwd=FRONTEND_DIR, env=env, title="FRONTEND: flutter pub get")
    if rc != 0:
        RESULTS["frontend_unit"] = "FAILED"
        log("\nFrontend dependency install FAILED")
        sys.exit(rc)

    # unit/widget (+ coverage + machine output)
    rc = run_command(
        [flutter_cmd, "test", "--coverage", "--machine"],
        cwd=FRONTEND_DIR,
        env=env,
        title="FRONTEND: flutter test --coverage --machine",
    )
    if rc != 0:
        RESULTS["frontend_unit"] = "FAILED"
        log("\nFrontend unit/widget tests FAILED")
        sys.exit(rc)

    RESULTS["frontend_unit"] = "PASSED"
    log("\nFrontend unit/widget tests PASSED\n")
    log(f"Frontend coverage: {FRONTEND_DIR / 'coverage' / 'lcov.info'}\n")

    # integration tests if folder exists
    it_dir = FRONTEND_DIR / "integration_test"
    if it_dir.exists():
        log("\nRUNNING FRONTEND INTEGRATION TESTS (Windows)\n")
        rc = run_command(
            [flutter_cmd, "test", "integration_test", "-d", "windows"],
            cwd=FRONTEND_DIR,
            env=env,
            title="FRONTEND: flutter test integration_test -d windows",
        )
        if rc != 0:
            RESULTS["frontend_integration"] = "FAILED"
            log("\nFrontend integration tests FAILED")
            log("If you see a symlink error, enable Developer Mode:")
            log("  start ms-settings:developers")
            sys.exit(rc)

        RESULTS["frontend_integration"] = "PASSED"
        log("\nFrontend integration tests PASSED\n")
    else:
        RESULTS["frontend_integration"] = "SKIPPED (no integration_test/ folder)"
        log("\nNo integration_test/ folder found -> skipping frontend integration tests.\n")


def main() -> None:
    started = datetime.now()
    validate_workspace_layout()

    log("\n===============================")
    log("   NutriPilot Full Test Run")
    log("===============================")
    log(f"Start Time: {started}")
    log(f"Log File: {LOG_FILE}")

    # Audit header
    log("\n--- RUN CONTEXT ---")
    log(f"Python: {sys.version.replace(os.linesep, ' ')}")
    log(f"Python Executable: {sys.executable}")
    log(f"OS: {platform.platform()}")
    log(f"SCRIPT_DIR: {SCRIPT_DIR}")
    log(f"WORKSPACE_ROOT: {WORKSPACE_ROOT}")
    log(f"Testing repo commit: {_try_get_git_commit(SCRIPT_DIR)}")
    log(f"Backend repo commit: {_try_get_git_commit(BACKEND_DIR)}")
    log(f"Frontend repo commit: {_try_get_git_commit(FRONTEND_DIR)}")
    log(f"RUN_AI_LIVE: {os.getenv('RUN_AI_LIVE', '0')}")
    log(f"RUN_AI_BATCH_100: {os.getenv('RUN_AI_BATCH_100', '0')}")
    log(f"RUN_AI_LEGACY_EVAL: {os.getenv('RUN_AI_LEGACY_EVAL', '0')}")
    log(f"RUN_AI_JUDGE: {os.getenv('RUN_AI_JUDGE', '0')}")
    log(f"AI_BATCH_N: {os.getenv('AI_BATCH_N', '100')}")
    log(f"AI_MIN_MARK: {os.getenv('AI_MIN_MARK', '0')}")
    log(f"AI_MIN_SUCCESS_RATE: {os.getenv('AI_MIN_SUCCESS_RATE', '0.3')}")
    log(f"AUTO_OPEN_AI_REPORTS: {os.getenv('AUTO_OPEN_AI_REPORTS', '1')}")
    log("-------------------\n")

    # Run tests (these sys.exit on failure)
    run_backend_tests()
    run_backend_ai_batch_100_test()
    run_frontend_tests()

    ended = datetime.now()
    duration = ended - started

    log("\n===============================")
    log(" RUN SUMMARY")
    log("===============================")
    log(f"- Backend: {RESULTS['backend']}")
    log(f"- Backend AI Batch 100 (Live): {RESULTS['backend_ai_batch_100']}")
    log(f"- Frontend unit/widget: {RESULTS['frontend_unit']}")
    log(f"- Frontend integration: {RESULTS['frontend_integration']}")
    log(f"- AI Live Enabled: {os.getenv('RUN_AI_LIVE') == '1'}")
    log(f"- AI Batch 100 Enabled: {os.getenv('RUN_AI_BATCH_100') == '1'}")
    log(f"- AI Legacy Eval Enabled: {os.getenv('RUN_AI_LEGACY_EVAL') == '1'}")
    log(f"- AI Judge Enabled: {os.getenv('RUN_AI_JUDGE') == '1'}")
    log(f"End Time: {ended}")
    log(f"Duration: {duration}")
    log("===============================\n")

    # Only print success if everything actually passed
    all_ok = (
        RESULTS["backend"] == "PASSED"
        and RESULTS["frontend_unit"] == "PASSED"
        and (RESULTS["backend_ai_batch_100"] == "PASSED" or str(RESULTS["backend_ai_batch_100"]).startswith("SKIPPED"))
        and (RESULTS["frontend_integration"] == "PASSED" or str(RESULTS["frontend_integration"]).startswith("SKIPPED"))
    )

    if all_ok:
        log("ALL TESTS COMPLETED SUCCESSFULLY\n")
        return

    log("TEST RUN COMPLETED WITH FAILURES\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
