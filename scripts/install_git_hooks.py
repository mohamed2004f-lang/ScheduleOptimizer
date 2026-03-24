from pathlib import Path
import shutil
import stat


ROOT = Path(__file__).resolve().parents[1]
SOURCE_HOOK = ROOT / "scripts" / "hooks" / "pre-commit"
TARGET_HOOK = ROOT / ".git" / "hooks" / "pre-commit"


def main():
    if not SOURCE_HOOK.exists():
        raise FileNotFoundError(f"Source hook not found: {SOURCE_HOOK}")
    if not (ROOT / ".git").exists():
        raise RuntimeError("This directory does not look like a git repository (.git not found).")

    TARGET_HOOK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_HOOK, TARGET_HOOK)

    # Try to set executable bit (useful on Git Bash / WSL / Unix-like envs)
    try:
        mode = TARGET_HOOK.stat().st_mode
        TARGET_HOOK.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass

    print("Git hook installed successfully:")
    print(f"- source: {SOURCE_HOOK}")
    print(f"- target: {TARGET_HOOK}")


if __name__ == "__main__":
    main()

