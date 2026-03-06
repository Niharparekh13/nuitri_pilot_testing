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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
    "backend_ai_batch": "NOT RUN",
    "frontend_unit": "NOT RUN",
    "frontend_integration": "NOT RUN",
}
REPORTS_OPENED = False


def log(msg: str) -> None:
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _dedicated_ai_batch_requested() -> bool:
    return _env_truthy("RUN_AI_BATCH_ALWAYS", "1") or _env_truthy("RUN_AI_BATCH_100", "0")


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
    audit_passed_calls = metrics.get("audit_passed_calls", "unknown")
    audit_failed_calls = metrics.get("audit_failed_calls", "unknown")
    fact_issue_total = metrics.get("fact_issue_total", "unknown")
    diagnostic_mode = metrics.get("diagnostic_mode", "unknown")
    gate_failures = summary.get("gate_failures", [])
    issue_counts = summary.get("audit_issue_counts", {})
    next_actions = summary.get("next_actions", [])

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
    log(f"- Audit passed calls: {audit_passed_calls}")
    log(f"- Audit failed calls: {audit_failed_calls}")
    log(f"- FACT issue total: {fact_issue_total}")
    log(f"- Diagnostic mode: {diagnostic_mode}")

    if isinstance(issue_counts, dict) and issue_counts:
        log("- Audit issue counts:")
        for k, v in sorted(issue_counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            log(f"  {k}: {v}")

    if isinstance(gate_failures, list) and gate_failures:
        log("- Gate failures (recorded):")
        for g in gate_failures[:5]:
            log(f"  {g}")

    if isinstance(next_actions, list) and next_actions:
        log("- Next actions:")
        for a in next_actions[:5]:
            log(f"  {a}")

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
        # stream to console (encoding-safe)
        safe_line = line
        out_encoding = getattr(sys.stdout, "encoding", None)
        if out_encoding:
            safe_line = line.encode(out_encoding, errors="replace").decode(out_encoding, errors="replace")
        print(safe_line, end="")
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
    run_batch_separately = _dedicated_ai_batch_requested()

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
        if run_batch_separately:
            args += ["--ignore=tests/ai_eval/test_ai_batch_image_live.py"]
            log(
                "RUN_AI_BATCH_ALWAYS=1 or RUN_AI_BATCH_100=1 -> excluding "
                "tests/ai_eval/test_ai_batch_image_live.py from main backend suite; "
                "it will run in the dedicated AI batch step.\n"
            )
        if os.getenv("RUN_AI_REGRESSION") != "1":
            args += ["--ignore=tests/live/test_ai_regression_live.py"]
            log(
                "RUN_AI_REGRESSION!=1 -> excluding tests/live/test_ai_regression_live.py "
                "(set RUN_AI_REGRESSION=1 to include snapshot drift checks).\n"
            )
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
        if run_batch_separately:
            log("Deferring report auto-open until dedicated AI batch step completes.\n")
        else:
            _auto_open_ai_reports_once()


def run_backend_ai_batch_test() -> None:
    """
    Runs the dedicated live AI image batch suite and generates JSON/CSV/HTML reports.

    Behavior:
    - RUN_AI_BATCH_ALWAYS=1 (default): diagnostic batch on every run.
    - RUN_AI_BATCH_100=1: strict 100-case mode.
    """
    run_always = _env_truthy("RUN_AI_BATCH_ALWAYS", "1")
    strict_100 = _env_truthy("RUN_AI_BATCH_100", "0")

    if not run_always and not strict_100:
        RESULTS["backend_ai_batch"] = "SKIPPED (RUN_AI_BATCH_ALWAYS!=1 and RUN_AI_BATCH_100!=1)"
        log(
            "\nSkipping dedicated AI image batch step "
            "(set RUN_AI_BATCH_ALWAYS=1 or RUN_AI_BATCH_100=1).\n"
        )
        return

    mode = "STRICT_100" if strict_100 else "DIAGNOSTIC"
    log(f"\nRUNNING BACKEND AI IMAGE BATCH ({mode})\n")
    env = build_backend_env()
    report_dir = BACKEND_DIR / "test_reports" / "ai_batch"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not env.get("OPENAI_API_KEY"):
        log("ERROR: OPENAI_API_KEY not set after reading backend .env.")
        log("Fix: Ensure .env has OPEN_AI_API_KEY (or OPENAI_API_KEY).")
        RESULTS["backend_ai_batch"] = "FAILED"
        sys.exit(2)

    if strict_100:
        # Strict mode must force 100 cases regardless of prior shell env values.
        env["AI_BATCH_N"] = "100"
        env["AI_DIAGNOSTIC_MODE"] = "0"
        env.setdefault("AI_MIN_MARK", "0")
        env.setdefault("AI_MIN_SUCCESS_RATE", "0.3")
        env.setdefault("AI_MAX_FAILED_AUDIT", "-1")
    else:
        if "AI_BATCH_N" not in env:
            env["AI_BATCH_N"] = os.getenv("AI_BATCH_DEFAULT_N", "20")
        env.setdefault("AI_DIAGNOSTIC_MODE", "1")
        env.setdefault("AI_MIN_MARK", "0")
        env.setdefault("AI_MIN_SUCCESS_RATE", "0.6")
        env.setdefault("AI_MAX_FAILED_AUDIT", "-1")
        env.setdefault("RUN_AI_JUDGE", "0")

    log(
        "Dedicated AI batch settings: "
        f"AI_BATCH_N={env.get('AI_BATCH_N')} | "
        f"AI_DIAGNOSTIC_MODE={env.get('AI_DIAGNOSTIC_MODE')} | "
        f"AI_MIN_MARK={env.get('AI_MIN_MARK')} | "
        f"AI_MIN_SUCCESS_RATE={env.get('AI_MIN_SUCCESS_RATE')} | "
        f"AI_MAX_FAILED_AUDIT={env.get('AI_MAX_FAILED_AUDIT')} | "
        f"RUN_AI_JUDGE={env.get('RUN_AI_JUDGE', os.getenv('RUN_AI_JUDGE', '0'))}\n"
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

    rc = run_command(args, cwd=BACKEND_DIR, env=env, title=f"RUNNING BACKEND AI BATCH ({mode})")
    _log_latest_ai_image_batch_summary()
    _auto_open_ai_reports_once()
    if rc != 0:
        RESULTS["backend_ai_batch"] = "FAILED"
        log("\nBackend AI batch test FAILED")
        sys.exit(rc)

    RESULTS["backend_ai_batch"] = f"PASSED ({mode}, N={env.get('AI_BATCH_N')}, DIAG={env.get('AI_DIAGNOSTIC_MODE')})"
    log("\nBackend AI batch test PASSED\n")
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
        log("\nRUNNING FRONTEND INTEGRATION TESTS (Android emulator)\n")

        api_base_url = os.getenv("FRONTEND_API_BASE_URL", "http://10.0.2.2:8000")
        emulator_id = os.getenv("ANDROID_EMULATOR_ID", "Medium_Phone_API_36.0")
        device_id = os.getenv("ANDROID_DEVICE_ID", "emulator-5554")
        preload_images = _env_truthy("PRELOAD_BACKEND_IMAGES", "1")

        if device_id.strip().lower() == "windows":
            RESULTS["frontend_integration"] = "FAILED"
            log("ERROR: ANDROID_DEVICE_ID is set to 'windows'.")
            log("This test runner is mobile/emulator-first. Use an Android emulator device id (e.g. emulator-5554).")
            sys.exit(2)

        emulator_test_script = FRONTEND_DIR / "scripts" / "test_android_emulator.ps1"
        if os.name == "nt" and emulator_test_script.exists():
            preload_flag = "1" if preload_images else "0"
            rc = run_command(
                [
                    "powershell",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(emulator_test_script),
                    "-ApiBaseUrl",
                    api_base_url,
                    "-EmulatorId",
                    emulator_id,
                    "-DeviceId",
                    device_id,
                    "-PreloadBackendImages",
                    preload_flag,
                    "-RunUnitTests",
                    "0",
                    "-RunIntegrationTests",
                    "1",
                ],
                cwd=FRONTEND_DIR,
                env=env,
                title="FRONTEND: Android emulator integration via scripts/test_android_emulator.ps1",
            )
        else:
            # Fallback path if script is missing or on non-Windows host.
            rc = run_command(
                [
                    flutter_cmd,
                    "test",
                    "integration_test",
                    "-d",
                    device_id,
                    f"--dart-define=API_BASE_URL={api_base_url}",
                ],
                cwd=FRONTEND_DIR,
                env=env,
                title=f"FRONTEND: flutter test integration_test -d {device_id}",
            )

        if rc != 0:
            RESULTS["frontend_integration"] = "FAILED"
            log("\nFrontend integration tests FAILED")
            log("Expected target: Android emulator (not Windows desktop).")
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
    log(f"RUN_AI_BATCH_ALWAYS: {os.getenv('RUN_AI_BATCH_ALWAYS', '1')}")
    log(f"RUN_AI_BATCH_100: {os.getenv('RUN_AI_BATCH_100', '0')}")
    log(f"RUN_AI_REGRESSION: {os.getenv('RUN_AI_REGRESSION', '0')}")
    log(f"RUN_AI_LEGACY_EVAL: {os.getenv('RUN_AI_LEGACY_EVAL', '0')}")
    log(f"RUN_AI_JUDGE: {os.getenv('RUN_AI_JUDGE', '0')}")
    log(f"AI_BATCH_N: {os.getenv('AI_BATCH_N', '100')}")
    log(f"AI_BATCH_DEFAULT_N: {os.getenv('AI_BATCH_DEFAULT_N', '20')}")
    log(f"AI_MIN_MARK: {os.getenv('AI_MIN_MARK', '0')}")
    log(f"AI_MIN_SUCCESS_RATE: {os.getenv('AI_MIN_SUCCESS_RATE', '0.3')}")
    log(f"AI_DIAGNOSTIC_MODE: {os.getenv('AI_DIAGNOSTIC_MODE', '0')}")
    log(f"AI_MAX_FAILED_AUDIT: {os.getenv('AI_MAX_FAILED_AUDIT', '-1')}")
    log(f"AI_AUDIT_REQUIRE_GROUNDED_FEEDBACK: {os.getenv('AI_AUDIT_REQUIRE_GROUNDED_FEEDBACK', '1')}")
    log(f"FRONTEND_API_BASE_URL: {os.getenv('FRONTEND_API_BASE_URL', 'http://10.0.2.2:8000')}")
    log(f"ANDROID_EMULATOR_ID: {os.getenv('ANDROID_EMULATOR_ID', 'Medium_Phone_API_36.0')}")
    log(f"ANDROID_DEVICE_ID: {os.getenv('ANDROID_DEVICE_ID', 'emulator-5554')}")
    log(f"PRELOAD_BACKEND_IMAGES: {os.getenv('PRELOAD_BACKEND_IMAGES', '1')}")
    log(f"AUTO_OPEN_AI_REPORTS: {os.getenv('AUTO_OPEN_AI_REPORTS', '1')}")
    log("-------------------\n")

    # Run tests (these sys.exit on failure)
    run_backend_tests()
    run_backend_ai_batch_test()
    run_frontend_tests()

    ended = datetime.now()
    duration = ended - started

    log("\n===============================")
    log(" RUN SUMMARY")
    log("===============================")
    log(f"- Backend: {RESULTS['backend']}")
    log(f"- Backend AI Batch (Live): {RESULTS['backend_ai_batch']}")
    log(f"- Frontend unit/widget: {RESULTS['frontend_unit']}")
    log(f"- Frontend integration: {RESULTS['frontend_integration']}")
    log(f"- AI Live Enabled: {os.getenv('RUN_AI_LIVE') == '1'}")
    log(f"- AI Batch Always Enabled: {os.getenv('RUN_AI_BATCH_ALWAYS', '1') == '1'}")
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
        and (str(RESULTS["backend_ai_batch"]).startswith("PASSED") or str(RESULTS["backend_ai_batch"]).startswith("SKIPPED"))
        and (RESULTS["frontend_integration"] == "PASSED" or str(RESULTS["frontend_integration"]).startswith("SKIPPED"))
    )

    if all_ok:
        log("ALL TESTS COMPLETED SUCCESSFULLY\n")
        return

    log("TEST RUN COMPLETED WITH FAILURES\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
