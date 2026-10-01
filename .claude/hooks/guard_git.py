"""PreToolUse hook (Bash): stop commits that break the project's git rules before they happen.

Blocks (exit 2, reason on stderr):
  * a commit message with a Co-Authored-By line or Claude/AI attribution - commits are authored only by rajukumar-tech;
  * staging secrets or local data: .env, *.db, backend/uploads/;
  * force-pushing master.
"""
import json
import re
import sys

try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
except Exception:
    sys.exit(0)  # never block on a hook input we cannot read

problems = []
if re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
    if re.search(r"co-authored-by", cmd, re.I) or re.search(r"generated with \[?claude|noreply@anthropic\.com", cmd, re.I):
        problems.append("Commit messages must not carry Co-Authored-By or Claude attribution - the author is rajukumar-tech only.")
if re.search(r"\bgit\b[^|;&]*\badd\b", cmd):
    if re.search(r"(^|\s|/)\.env(\s|$)|\.db(\s|$)|backend/uploads", cmd):
        problems.append("Do not stage .env, *.db or backend/uploads/ - secrets and local data never go to GitHub.")
    if re.search(r"\badd\s+(-f|--force)\b", cmd):
        problems.append("Do not force-add ignored files.")
if re.search(r"\bgit\b[^|;&]*\bpush\b[^|;&]*(--force\b|-f\b)", cmd) and "master" in cmd:
    problems.append("Do not force-push master.")

if problems:
    print("Blocked by .claude/hooks/guard_git.py:\n- " + "\n- ".join(problems), file=sys.stderr)
    sys.exit(2)
sys.exit(0)
