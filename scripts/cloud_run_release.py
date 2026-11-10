"""Serve an accepted bundle on Cloud Run, one reviewed step at a time.

Dry run by default: every step prints the exact gcloud command it would run.
Add --execute to run it. Works from PowerShell, macOS and Linux (no shell).

    setup     once: mount gs://BUCKET read-only at /models on the service
    upload    copy accepted/<version> to gs://BUCKET/accepted/<version>/ without
              overwriting, then re-download the model and compare its SHA-256
    deploy    new revision with MODEL_DIR=/models/accepted/<version>, no traffic,
              reachable through its own tag URL for the identity check
    traffic   send 100% of traffic to one named revision (switch or rollback)
    describe  revisions, tags, URLs and traffic split

The version defaults to artifacts/accepted/CURRENT.json. Each accepted version
keeps its own immutable bucket path and its own Cloud Run revision, so the
previous revision can take the traffic back without retraining or re-uploading.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

MOUNT = "/models"
FILES = ("model.joblib", "model-metadata.json", "acceptance.json")


def slug(text: str, limit: int) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:limit].strip("-")
    if not value or not value[0].isalpha():
        value = f"v-{value}"[:limit].strip("-")
    return value


def tag_for(version: str) -> str:
    return slug(f"v-{version}", 40)


def suffix_for(version: str, service: str, now: datetime) -> str:
    stamp = now.strftime("%m%d%H%M")
    room = 63 - len(service) - 1 - len(stamp) - 1
    return f"{slug(version, max(room, 1))}-{stamp}"


def load_bundle(store: Path, version: str | None) -> dict:
    """The local accepted bundle, verified against its acceptance record."""
    accepted = store / "accepted"
    if version is None:
        version = json.loads((accepted / "CURRENT.json").read_text())["model_version"]
    directory = accepted / version
    acceptance = json.loads((directory / "acceptance.json").read_text())
    digest = hashlib.sha256((directory / "model.joblib").read_bytes()).hexdigest()
    if digest != acceptance["model_sha256"]:
        raise SystemExit(f"{version}: local bytes differ from acceptance.json")
    return {"version": version, "directory": directory, "model_sha256": digest}


def service_args(args) -> list[str]:
    return [args.service, "--project", args.project, "--region", args.region]


def commands(args, now: datetime) -> list[list[str]]:
    gcloud = shutil.which("gcloud") or "gcloud"
    if args.step == "setup":
        return [
            [
                gcloud,
                "run",
                "services",
                "update",
                *service_args(args),
                "--add-volume",
                f"name=models,type=cloud-storage,bucket={args.bucket},readonly=true",
                "--add-volume-mount",
                f"volume=models,mount-path={MOUNT}",
            ]
        ]
    if args.step == "upload":
        bundle = load_bundle(args.store, args.version)
        prefix = f"gs://{args.bucket}/accepted/{bundle['version']}/"
        return [
            [
                gcloud,
                "storage",
                "cp",
                "--no-clobber",
                str(bundle["directory"] / name),
                prefix + name,
            ]
            for name in FILES
        ]
    if args.step == "deploy":
        bundle = load_bundle(args.store, args.version)
        return [
            [
                gcloud,
                "run",
                "deploy",
                *service_args(args),
                "--image",
                args.image,
                "--port",
                "8000",
                "--no-traffic",
                "--tag",
                tag_for(bundle["version"]),
                "--revision-suffix",
                suffix_for(bundle["version"], args.service, now),
                "--update-env-vars",
                f"MODEL_DIR={MOUNT}/accepted/{bundle['version']}",
            ]
        ]
    if args.step == "traffic":
        return [
            [
                gcloud,
                "run",
                "services",
                "update-traffic",
                *service_args(args),
                "--to-revisions",
                f"{args.revision}=100",
            ]
        ]
    return [
        [gcloud, "run", "services", "describe", *service_args(args), "--format", "json"]
    ]


def verify_upload(args) -> dict:
    """Read the uploaded model back and compare its SHA-256 with the local bytes."""
    bundle = load_bundle(args.store, args.version)
    gcloud = shutil.which("gcloud") or "gcloud"
    remote = f"gs://{args.bucket}/accepted/{bundle['version']}/model.joblib"
    data = subprocess.run(
        [gcloud, "storage", "cat", remote], capture_output=True, check=True
    ).stdout
    observed = hashlib.sha256(data).hexdigest()
    return {
        "claim": "uploaded_model_sha256",
        "expected": bundle["model_sha256"],
        "observed": observed,
        "result": "ok" if observed == bundle["model_sha256"] else "FAIL",
    }


def summarise(service: dict) -> dict:
    status = service.get("status", {})
    return {
        "url": status.get("url"),
        "latest_ready_revision": status.get("latestReadyRevisionName"),
        "traffic": [
            {key: item.get(key) for key in ("revisionName", "percent", "tag", "url")}
            for item in status.get("traffic", [])
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "step", choices=["setup", "upload", "deploy", "traffic", "describe"]
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--service", required=True)
    parser.add_argument("--bucket")
    parser.add_argument("--store", type=Path, default=Path("artifacts"))
    parser.add_argument("--version", help="accepted version; default CURRENT")
    parser.add_argument("--image", help="image built from reviewed main")
    parser.add_argument("--revision", help="revision that takes 100% of traffic")
    parser.add_argument("--execute", action="store_true", help="run, not print")
    args = parser.parse_args(argv)
    needs = {
        "setup": "bucket",
        "upload": "bucket",
        "deploy": "image",
        "traffic": "revision",
    }
    if args.step in needs and not getattr(args, needs[args.step]):
        parser.error(f"{args.step} needs --{needs[args.step]}")
    planned = commands(args, datetime.now(UTC))
    for command in planned:
        print(
            json.dumps({"step": args.step, "execute": args.execute, "command": command})
        )
        if not args.execute:
            continue
        if args.step == "describe":
            output = subprocess.run(command, capture_output=True, text=True, check=True)
            print(json.dumps(summarise(json.loads(output.stdout)), indent=2))
        else:
            subprocess.run(command, check=True)
    if args.step == "upload" and args.execute:
        result = verify_upload(args)
        print(json.dumps(result))
        return 0 if result["result"] == "ok" else 1
    if args.step == "deploy":
        bundle = load_bundle(args.store, args.version)
        print(
            json.dumps(
                {
                    "next": "check the tag URL before moving traffic",
                    "tag": tag_for(bundle["version"]),
                    "expected_version": bundle["version"],
                    "expected_sha256": bundle["model_sha256"],
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
