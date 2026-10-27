#!/usr/bin/env python3
"""Out-of-process audit script.

Runs audit_system() and prints the result as JSON to stdout.
Exit code 0 on success, non-zero on any error.

Invoked by integrity.run_independent_audit() in a child process;
the parent captures stdout and parses the JSON.
"""
import json
import os
import sys

# Ensure pc-host/ is on the path regardless of cwd
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)  # pc-host/
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from telemetry_host.security.sysaudit import audit_system
    profile = audit_system()
    print(json.dumps(profile.as_dict()), flush=True)
    sys.exit(0)
except Exception as exc:
    print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
    sys.exit(1)
