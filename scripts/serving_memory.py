"""Measure serving-process memory (Linux /proc), optionally after loading a bundle.

Run it inside the serving image to measure the runtime that Cloud Run uses:

    docker run --rm -v <bundle>:/models:ro --entrypoint uv bike-demand:lab7 \
        run --locked --no-sync python scripts/serving_memory.py /models

It loads the bundle with the API's own loader (checksum, feature order, probe).
It does not train, evaluate or serve requests.
"""

import json
import platform
import sys
from pathlib import Path


def rss_mib() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    raise RuntimeError("VmRSS unavailable; this measurement needs Linux")


def main(argv: list[str]) -> int:
    import uvicorn  # noqa: F401  (same imports as the serving process)

    from bike_demand.api import load_artifact

    result = {"platform": platform.platform(), "rss_after_imports_mib": rss_mib()}
    if argv:
        directory = Path(argv[0])
        loaded = load_artifact(directory)
        result.update(
            model_version=loaded.version,
            model_bytes=(directory / "model.joblib").stat().st_size,
            rss_after_load_mib=rss_mib(),
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
