"""Private local output only; never overwrite an existing backup or candidate."""
import csv
import json
import os
from pathlib import Path
import subprocess

from .codec import require


def private_directory(path):
    path = Path(path).expanduser().resolve()
    project = Path(__file__).resolve().parent.parent
    require(not path.is_relative_to(project), "Choose an output directory outside the repository/package")
    path.mkdir(parents=True, mode=0o700, exist_ok=False)
    if os.name == "nt":
        identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                                  capture_output=True, text=True, check=True)
        sid = next(csv.reader(identity.stdout.splitlines()))[1]
        require(sid.startswith("S-1-"), "Cannot identify Windows user SID")
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                                 f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                                capture_output=True, check=False)
        require(result.returncode == 0, "Cannot restrict Windows directory permissions; no secrets written")
    else:
        path.chmod(0o700)
    return path


def write_private(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def write_json(path, value):
    write_private(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
