# NutriPilot Testing

Shared testing harness for the NutriPilot split repos.

## Repos this runner targets
- ../nuitri_pilot_backend
- ../nuitri_pilot_frontend

## Quick start
```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_testing
python run_tests.py
```

Frontend integration tests are run against Android emulator (`emulator-5554`), not Windows desktop.

## Run whole app (backend + frontend) with one command
```powershell
cd C:\Users\nihar\Desktop\nuitripilot\nuitri_pilot_testing
python run_app.py
```

Useful options:
```powershell
# backend only
python run_app.py --backend-only

# custom emulator/API target
python run_app.py --device-id emulator-5554 --api-base-url http://10.0.2.2:8000

# skip preload image push
python run_app.py --no-preload-images
```

## Optional workspace override
Set `NUTRIPILOT_WORKSPACE_ROOT` if frontend/backend are not sibling folders.
