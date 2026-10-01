"""PostToolUse hook (Edit|Write): fast checks right after a file changes, so mistakes surface at once.

  * frontend UI text (src/**/*.tsx, src/lib/i18n/*.ts): run the i18n checker - every key in English, Kannada and Hindi,
    no hard-coded UI text;
  * backend Python: compile the file to catch syntax errors.
Exit 2 sends the failure back to Claude to fix; everything else passes silently.
"""
import json
import os
import py_compile
import subprocess
import sys

try:
    path = (json.load(sys.stdin).get("tool_input", {}).get("file_path") or "").replace("\\", "/")
except Exception:
    sys.exit(0)

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "/frontend/src/" in path and path.endswith((".ts", ".tsx")):
    r = subprocess.run(["node", "scripts/check-i18n.mjs"], cwd=os.path.join(root, "frontend"),
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("i18n check failed (add the text to en.ts, kn.ts and hi.ts):\n" + (r.stdout + r.stderr)[-2000:], file=sys.stderr)
        sys.exit(2)
elif "/backend/" in path and path.endswith(".py") and os.path.exists(path):
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"Python syntax error in {path}:\n{e.msg}", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
