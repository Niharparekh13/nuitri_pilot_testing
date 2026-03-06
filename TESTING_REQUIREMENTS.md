# NutriPilot Testing Requirements and Runbook

This file explains how to run all test suites in this workspace before pushing to your branch.

## 1) Scope

This runbook covers:

- Backend Python tests in `nuitri_pilot_backend/tests`
- Frontend Flutter tests in `nuitri_pilot_frontend/test` and `nuitri_pilot_frontend/integration_test`
- Full orchestrated test run via `run_tests.py`
- Live AI batch reporting artifacts (JSON, CSV, HTML)

## 2) Required Tools

Install these first:

1. Python 3.11.x
2. pip (comes with Python)
3. Flutter SDK (stable channel)
4. Git
5. Docker Desktop (optional, only if you want Mongo integration tests)
6. Android Emulator (AVD) available to Flutter (`emulator-5554`)

Mobile note:

- Frontend integration tests are executed on Android emulator (not Windows desktop).

## 3) Python and Flutter Dependencies

From workspace root:

```powershell
cd C:\Users\nihar\Desktop\nuitripilot
python -m pip install --upgrade pip
python -m pip install -r .\nuitri_pilot_backend\requirements
python -m pip install pytest pytest-cov pytest-html pytest-asyncio
```

Frontend dependencies:

```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_frontend
flutter pub get
flutter doctor
```

## 4) Required Environment Configuration

`run_tests.py` expects backend `.env` at:

- `nuitri_pilot_backend\.env`

By default, `run_tests.py` assumes this folder layout:

- `nuitri_pilot_frontend` and `nuitri_pilot_backend` are siblings of `nuitri_pilot_testing`

If your repos are elsewhere, set:

- `NUTRIPILOT_WORKSPACE_ROOT=<folder containing both repos>`

Minimum keys for non-live tests:

- Standard backend app keys from `conf_template.md` (Mongo/JWT/etc as needed)

Required for live AI tests:

- `OPEN_AI_API_KEY` or `OPENAI_API_KEY`
- `OPEN_AI_MODEL` (recommended: `gpt-4o-mini`)

## 5) Recommended One-Command Test Run

From testing repo:

```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_testing
python run_tests.py
```

Default behavior:

- Backend: runs non-live tests (`-m not ai_live`)
- Frontend: unit/widget tests + integration tests on Android emulator (if folder exists)
- Live AI tests: not included unless enabled

### Always run backend + emulator together (mobile app workflow)

Use two terminals so backend stays running while app is launched on emulator.

Terminal 1 (backend API):

```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_backend
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Terminal 2 (frontend on Android emulator):

```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_frontend
.\scripts\run_android_emulator.ps1 -ApiBaseUrl "http://10.0.2.2:8000"
```

Notes:

- `10.0.2.2` is required for Android emulator to reach host backend.
- Keep Terminal 1 running while using the mobile app in emulator.

## 6) Live AI Test Modes (Important)

### A) Run all live AI suites

```powershell
$env:RUN_AI_LIVE="1"
$env:RUN_AI_JUDGE="1"
python run_tests.py
```

Current defaults inside `run_tests.py` live mode:

- `AI_MIN_MARK=0`
- `AI_MIN_SUCCESS_RATE=0.3`
- Legacy eval file excluded unless explicitly enabled

### B) Run dedicated 100-case AI image batch only

```powershell
$env:RUN_AI_LIVE="0"
$env:RUN_AI_JUDGE="0"
$env:RUN_AI_BATCH_100="1"
$env:FRONTEND_API_BASE_URL="http://10.0.2.2:8000"
$env:ANDROID_EMULATOR_ID="Medium_Phone_API_36.0"
$env:ANDROID_DEVICE_ID="emulator-5554"
python run_tests.py
```

What this run includes:

- Backend dedicated 100-case live AI batch (`test_ai_image_batch_100_live`)
- Frontend integration tests on Android emulator (`emulator-5554`)
- No Windows desktop integration target

### C) Include legacy AI eval file (not recommended by default)

```powershell
$env:RUN_AI_LIVE="1"
$env:RUN_AI_LEGACY_EVAL="1"
python run_tests.py
```

### D) Disable auto-opening HTML reports

```powershell
$env:AUTO_OPEN_AI_REPORTS="0"
python run_tests.py
```

## 7) Run Backend Tests Directly (without orchestrator)

From backend folder:

```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_backend
python -m pytest -q
```

Non-live only:

```powershell
python -m pytest -q -m "not ai_live"
```

Live only:

```powershell
python -m pytest -q -m "ai_live" --ignore=tests/ai_eval/test_ai_batch_live.py
```

## 8) Backend Test Files and Commands

From `nuitri_pilot_backend`:

```powershell
python -m pytest -q tests\test_root.py
python -m pytest -q tests\api\test_auth_required.py
python -m pytest -q tests\api\test_root_contract.py
python -m pytest -q tests\unit\test_ai_golden_mocked.py
python -m pytest -q tests\unit\test_ai_service_mocked.py
python -m pytest -q tests\unit\test_token.py
python -m pytest -q tests\integration\test_mongo_real.py
python -m pytest -q tests\live\test_ai_live.py
python -m pytest -q tests\live\test_ai_golden_live.py
python -m pytest -q tests\live\test_ai_regression_live.py
python -m pytest -q tests\live\test_agent_schema_regression_live.py
python -m pytest -q tests\ai_eval\test_ai_batch_image_live.py
python -m pytest -q tests\ai_eval\test_ai_batch_live.py
```

Related eval utility:

```powershell
python tests\ai_eval\update_baseline.py
```

## 9) Frontend Test Files and Commands

From `nuitri_pilot_frontend`:

```powershell
flutter test
flutter test test\widget_test.dart
flutter test test\navigation_test.dart
flutter test integration_test -d emulator-5554
flutter test integration_test\app_e2e_test.dart -d emulator-5554
```

Recommended emulator runner:

```powershell
.\scripts\test_android_emulator.ps1
```

Run app on emulator (non-test/manual run):

```powershell
.\scripts\run_android_emulator.ps1 -ApiBaseUrl "http://10.0.2.2:8000"
```

Useful emulator env overrides for orchestrator:

```powershell
$env:FRONTEND_API_BASE_URL="http://10.0.2.2:8000"
$env:ANDROID_EMULATOR_ID="Medium_Phone_API_36.0"
$env:ANDROID_DEVICE_ID="emulator-5554"
$env:PRELOAD_BACKEND_IMAGES="1"   # set to 0 to skip image preload
python run_tests.py
```

## 10) Test Artifacts (What to Present)

### Orchestrator log

- `nuitri_pilot_testing\test_logs\test_run_YYYYMMDD_HHMMSS.log`

### Backend standard reports

- `nuitri_pilot_backend\test_reports\pytest-junit.xml`
- `nuitri_pilot_backend\test_reports\pytest-report.html`
- `nuitri_pilot_backend\test_reports\coverage.xml`
- `nuitri_pilot_backend\test_reports\html\index.html`

### Dedicated AI batch standard reports

- `nuitri_pilot_backend\test_reports\ai_batch\ai-batch-junit.xml`
- `nuitri_pilot_backend\test_reports\ai_batch\ai-batch-pytest-report.html`

### AI 100-case presentation and data reports

- `nuitri_pilot_backend\tests\ai_eval\runs\*_image_batch_*.json`
- `nuitri_pilot_backend\tests\ai_eval\runs\*_image_batch_*.csv`
- `nuitri_pilot_backend\tests\ai_eval\runs\*_image_batch_*.html`

These include:

- Per-case code, mark, latency, feedback
- Count of scored cases (`code=0` and `mark>0`)
- Count of unreadable-label feedback cases
- Failure summary

## 11) Pre-Push Checklist

Before pushing your branch:

1. Run `python run_tests.py` from `nuitri_pilot_testing`.
2. Verify no failed backend or frontend suites.
3. If AI/live changes were touched, run at least one live AI mode and review:
   - `ai-batch-pytest-report.html`
   - latest `*_image_batch_*.html` report
4. Confirm `.env` and secrets are not committed.
5. Confirm generated logs/reports are ignored by git policy (if required by your repo workflow).
6. Include test evidence (report paths/screenshots) in PR description.
