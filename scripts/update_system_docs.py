import subprocess
from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
OVERVIEW_PATH = ROOT / "docs" / "PROJECT_OVERVIEW.md"
RUNBOOK_PATH = ROOT / "docs" / "RUNBOOK.md"

START_MARKER = "<!-- AUTO_LATEST_CHANGES_START -->"
END_MARKER = "<!-- AUTO_LATEST_CHANGES_END -->"


def _run_git_log(limit: int = 10):
    cmd = [
        "git",
        "log",
        f"-n{limit}",
        "--date=short",
        "--pretty=format:%h|%ad|%s",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return []
    rows = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        rows.append({"sha": parts[0].strip(), "date": parts[1].strip(), "subject": parts[2].strip()})
    return rows


def _build_latest_changes_block(rows):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append("## Latest Changes (Auto)")
    lines.append("")
    lines.append(f"_Last generated: {now}_")
    lines.append("")
    if not rows:
        lines.append("- No git history found.")
    else:
        for r in rows:
            lines.append(f"- `{r['sha']}` ({r['date']}): {r['subject']}")
    lines.append("")
    return "\n".join(lines)


def _upsert_marked_section(path: Path, section_text: str):
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{START_MARKER}\n{section_text}\n{END_MARKER}\n"
    if START_MARKER in content and END_MARKER in content:
        before = content.split(START_MARKER, 1)[0]
        after = content.split(END_MARKER, 1)[1]
        new_content = before.rstrip() + "\n\n" + block + after.lstrip()
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n" + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")


def _ensure_runbook_note():
    if not RUNBOOK_PATH.exists():
        return
    content = RUNBOOK_PATH.read_text(encoding="utf-8")
    marker = "## 10) Auto-Update System Docs"
    if marker in content:
        return
    appendix = (
        "\n---\n\n"
        "## 10) Auto-Update System Docs\n\n"
        "Update the latest project changes section automatically from git history:\n\n"
        "```powershell\n"
        "python scripts/update_system_docs.py\n"
        "```\n"
    )
    RUNBOOK_PATH.write_text(content + appendix, encoding="utf-8")


def main():
    rows = _run_git_log(limit=10)
    section = _build_latest_changes_block(rows)
    _upsert_marked_section(OVERVIEW_PATH, section)
    _ensure_runbook_note()
    print("System docs updated:")
    print(f"- {OVERVIEW_PATH}")
    print(f"- {RUNBOOK_PATH}")


if __name__ == "__main__":
    main()

