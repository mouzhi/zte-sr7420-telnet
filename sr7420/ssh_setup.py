"""Generate an offline SSH deployment bundle. Never reads private keys or contacts a router."""
import argparse
import base64
from importlib.resources import files
import ipaddress
from pathlib import Path
import struct
import sys

from .codec import require
from .storage import private_directory, write_json, write_private


def public_ed25519(text):
    fields = text.strip().split()
    require(len(fields) >= 2 and fields[0] == "ssh-ed25519", "Supply a single Ed25519 PUBLIC .pub file")
    require("\n" not in text.strip() and "\r" not in text.strip(), "Expected exactly one public key")
    blob = base64.b64decode(fields[1], validate=True)
    prefix = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32)
    require(len(blob) == len(prefix) + 32 and blob.startswith(prefix), "Invalid Ed25519 public key encoding")
    # Strip user/device comments from the copied public key.
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + "\n"


def generate(lan_ip, lan_cidr, public_key, output_dir):
    address = ipaddress.IPv4Address(lan_ip)
    network = ipaddress.IPv4Network(lan_cidr, strict=True)
    allowed = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    require(any(network.subnet_of(ipaddress.ip_network(n)) for n in allowed), "Use an RFC1918 LAN subnet")
    require(network.prefixlen <= 30 and address in network
            and address not in (network.network_address, network.broadcast_address), "LAN address/subnet mismatch")
    key = public_ed25519(Path(public_key).expanduser().read_text(encoding="utf-8"))
    directory = private_directory(output_dir)
    write_private(directory / "authorized_keys", key.encode())
    write_private(directory / "lan.conf", f"LAN_IP={address}\nLAN_CIDR={network}\n".encode())
    write_private(directory / "start.sh", files("sr7420").joinpath("assets/start-ssh.sh").read_bytes())
    write_json(directory / "ssh-bundle-manifest.json", {"status": "GENERATED_NOT_DEPLOYED",
               "listener_port": 22, "interface": "br0", "password_auth": False,
               "note": "Build binary separately. Generate the host private key on the router."})
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan-ip", required=True)
    parser.add_argument("--lan-cidr", required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        folder = generate(args.lan_ip, args.lan_cidr, args.public_key, args.output_dir)
    except Exception as exc:
        print("Bundle generation stopped: " + type(exc).__name__, file=sys.stderr)
        return 1
    print("Private deployment bundle generated (NOT deployed): " + str(folder))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
