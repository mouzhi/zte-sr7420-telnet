import argparse
import getpass
import hashlib
import json
from pathlib import Path
import secrets
import sys

from .codec import decode, encode, require
from .config import FIRMWARE, MODEL, patch
from .storage import private_directory, write_json, write_private
from .telnet import Telnet
from .web import Router, lan_host


def backup(args):
    password = getpass.getpass("Router admin password (not saved): ")
    router = Router(args.host)
    try:
        router.login(password)
        identity = router.identity()
        require(identity == {"model": MODEL, "firmware": FIRMWARE}, "Untested model/firmware; this release stops here")
        blob = router.backup()
        decode(blob)
    finally:
        router.close()
    folder = private_directory(args.output_dir)
    write_private(folder / "original.bin", blob)
    write_json(folder / "backup-manifest.json", {
        **identity, "host": lan_host(args.host), "sha256": hashlib.sha256(blob).hexdigest()})
    return {"backup_saved": True, "directory": str(folder), "crc_verified": True, **identity}


def prepare(args):
    source = Path(args.backup_dir).expanduser().resolve()
    manifest = json.loads((source / "backup-manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("model") == MODEL and manifest.get("firmware") == FIRMWARE,
            "Unsupported model/firmware in backup manifest")
    host = lan_host(manifest["host"])
    blob = (source / "original.bin").read_bytes()
    require(hashlib.sha256(blob).hexdigest() == manifest.get("sha256"), "Backup hash mismatch")
    xml, chunk_size = decode(blob)
    password = secrets.token_urlsafe(24)
    modified, changes = patch(xml, password)
    candidate = encode(modified, chunk_size)
    require(decode(candidate)[0] == modified, "Candidate round-trip mismatch")
    folder = private_directory(args.output_dir)
    write_private(folder / "candidate.bin", candidate)
    write_json(folder / "telnet-credentials.json", {"host": host, "port": 23, "username": "root", "password": password})
    report = {"status": "PREPARED_NOT_APPLIED", "model": MODEL, "firmware": FIRMWARE,
              "original_sha256": manifest["sha256"], "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
              "changes": changes, "wan_telnet_enabled": False, "crc_and_roundtrip_verified": True,
              "warning": "Manual config restore may reboot the router. Preserve original.bin."}
    write_json(folder / "candidate-report.json", report)
    return {**report, "directory": str(folder)}


def verify(args):
    credentials = json.loads(Path(args.credentials).expanduser().read_text(encoding="utf-8"))
    require(credentials.get("username") == "root" and credentials.get("port") == 23, "Unexpected credentials profile")
    client = Telnet(credentials["host"], credentials["port"])
    try:
        return client.verify(credentials["username"], credentials["password"])
    finally:
        client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner-only SR7420 LAN Telnet research workflow; never uploads/restores config")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("backup", help="Authenticate and export a private original backup")
    command.add_argument("--host", required=True, help="Your router's numeric LAN IPv4 address")
    command.add_argument("--output-dir", required=True, help="New private directory OUTSIDE this repository")
    command.set_defaults(run=backup)
    command = sub.add_parser("prepare", help="Offline: change four fields and create a separate candidate")
    command.add_argument("--backup-dir", required=True)
    command.add_argument("--output-dir", required=True, help="New private directory OUTSIDE this repository")
    command.set_defaults(run=prepare)
    command = sub.add_parser("verify", help="Read-only root login check after MANUAL restore/reboot")
    command.add_argument("--credentials", required=True)
    command.set_defaults(run=verify)
    args = parser.parse_args(argv)
    try:
        result = args.run(args)
    except (ValueError, OSError, KeyError, TimeoutError) as exc:
        # Never include server bodies, credentials, or arbitrary exception text.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print("Stopped: " + message, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
