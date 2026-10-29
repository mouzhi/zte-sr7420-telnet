"""Optional ProxyCommand: fixed LAN Telnet bootstrap, then transparent SSH transport."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import sys
import threading
import time

from .codec import require
from .telnet import Telnet


def connect_or_start(host, credentials_path):
    address = ipaddress.IPv4Address(host)
    require(any(address in ipaddress.ip_network(n) for n in
                ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")), "Only a numeric LAN IPv4 target is allowed")
    try:
        return socket.create_connection((str(address), 22), 3)
    except OSError:
        credentials = json.loads(Path(credentials_path).expanduser().read_text(encoding="utf-8"))
        require(credentials.get("host") == str(address) and credentials.get("port") == 23
                and credentials.get("username") == "root", "Bootstrap credentials target mismatch")
        client = Telnet(str(address), 23)
        try:
            client.start_ssh(credentials["username"], credentials["password"])
        finally:
            client.close()
        for attempt in range(10):
            try:
                return socket.create_connection((str(address), 22), 3)
            except OSError:
                if attempt == 9:
                    raise TimeoutError("SSH listener did not become ready")
                time.sleep(0.4)


def relay(connection, incoming, outgoing):
    connection.settimeout(None)
    def send():
        try:
            while True:
                data = incoming.read1(65536)
                if not data:
                    break
                connection.sendall(data)
        except OSError:
            pass
        finally:
            try:
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
    threading.Thread(target=send, daemon=True).start()
    try:
        while True:
            data = connection.recv(65536)
            if not data:
                break
            outgoing.write(data)
            outgoing.flush()
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--credentials", required=True, help="Local Telnet profile, never an SSH private key")
    args = parser.parse_args(argv)
    try:
        connection = connect_or_start(args.host, args.credentials)
        relay(connection, sys.stdin.buffer, sys.stdout.buffer)
    except Exception as exc:
        print("Router SSH transport failed: " + type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
