# ScheduleOptimizer Runbook

## 1) Prerequisites

- Windows + PowerShell
- Python 3.11+ (prefer the same version across team machines)
- Git

---

## 2) First-Time Setup

From the project root:

```powershell
cd C:\Users\BARCODE\ScheduleOptimizer

# If PowerShell blocks script execution in this session
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
python -m pip install -r requirements.txt
```

---

## 3) Run the System

```powershell
python app.py
```

Open:

- http://127.0.0.1:5000

Stop the app:

- Press `Ctrl + C` in the same terminal.

---

## 4) Backup Before Major Updates

Create a quick SQLite backup before risky changes:

```powershell
Copy-Item "backend\database\mechanical.db" "backups\mechanical_$(Get-Date -Format yyyyMMdd_HHmmss).db"
```

---

## 5) Update Local System from GitHub

```powershell
git pull origin master
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

---

## 6) Safe Git Workflow (Commit + Push)

Review changes:

```powershell
git status
```

Stage only intended code files (avoid logs/cache/binaries):

```powershell
git add app.py backend frontend
```

Commit:

```powershell
git commit -m "Clear summary of your update"
```

Push:

```powershell
git push origin master
```

---

## 7) Post-Deployment Smoke Checks

- Login works
- `transcript_page` shows students and transcript data
- Actual registrations save and refresh without manual page reload
- Enrollment plans show pending list and academic quick summary
- Reports open and export (Excel/PDF)

---

## 8) Common Issues & Quick Fixes

### PowerShell execution policy error

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### `ModuleNotFoundError`

Usually virtualenv is inactive:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### UI seems stale after updates

Use hard refresh:

- `Ctrl + F5`

### CSRF failures on POST

- Ensure requests are same-origin
- Ensure pages load `common.js` and CSRF meta tag

---

## 9) Recommended `.gitignore` Hygiene

Ensure these are ignored:

- `__pycache__/`
- `*.pyc`
- `logs/*.log`
- `ngrok.zip`


---

## 10) Auto-Update System Docs

Update the latest project changes section automatically from git history:

```powershell
python scripts/update_system_docs.py
```

Install shared git hooks for this repository (run once per machine):

```powershell
python scripts/install_git_hooks.py
```
