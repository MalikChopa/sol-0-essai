"""Print a refs JSON between markers in the job log and into the step summary (read back by compare_refs.py)."""
import os
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
print("REFS-BEGIN")
print(text, end="" if text.endswith("\n") else "\n")
print("REFS-END")
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as f:
        f.write("```json\n" + text + "\n```\n")
