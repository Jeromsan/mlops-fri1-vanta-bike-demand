"""Run one command and keep its raw evidence: argv, times, exit code, output.

    uv run --locked python scripts/record.py reports/lab7-run 03-run-c1 -- \
        uv run --locked python -m bike_demand.pipeline run --candidate ...

Writes <dir>/<name>.json (command, UTC start/end, exit code) next to
<name>.out and <name>.err, unedited. Returns the command's own exit code, so an
expected rejection (2) or block (3) stays visible to the caller.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[2] != "--":
        print(__doc__, file=sys.stderr)
        return 64
    directory, name, command = Path(argv[0]), argv[1], argv[3:]
    directory.mkdir(parents=True, exist_ok=True)
    for suffix in (".json", ".out", ".err"):
        if (directory / f"{name}{suffix}").exists():
            print(
                f"{name}{suffix} exists; evidence is never overwritten", file=sys.stderr
            )
            return 65
    started = datetime.now(UTC).isoformat()
    result = subprocess.run(command, capture_output=True)
    (directory / f"{name}.out").write_bytes(result.stdout)
    (directory / f"{name}.err").write_bytes(result.stderr)
    record = {
        "command": command,
        "cwd": str(Path.cwd()),
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "exit_code": result.returncode,
    }
    (directory / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
