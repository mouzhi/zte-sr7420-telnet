"""Bounded root-login verifier; no command runner, transcript files or retry loop."""
import re
import socket
import time

from .codec import require
from .web import lan_host

PROMPT = r"(?:^|[\r\n])/ # ?(?:\r?\n)?$"


class Telnet:
    def __init__(self, host, port=23):
        self.sock = socket.create_connection((lan_host(host), port), 5)
        self.sock.settimeout(0.25)
        self.pending = b""

    def close(self):
        self.sock.close()

    def receive(self, pattern, seconds=6):
        end = time.monotonic() + seconds
        text = ""
        while time.monotonic() < end:
            try:
                incoming = self.sock.recv(8192)
            except socket.timeout:
                continue
            if not incoming:
                break
            self.pending += incoming
            data, index = bytearray(), 0
            while index < len(self.pending):
                if self.pending[index] != 255:
                    data.append(self.pending[index])
                    index += 1
                    continue
                if index + 1 >= len(self.pending):
                    break
                command = self.pending[index + 1]
                if command == 255:
                    data.append(255)
                    index += 2
                elif command in (251, 252, 253, 254):
                    if index + 2 >= len(self.pending):
                        break
                    option = self.pending[index + 2]
                    if command == 251:
                        self.sock.sendall(bytes([255, 254, option]))
                    elif command == 253:
                        self.sock.sendall(bytes([255, 252, option]))
                    index += 3
                elif command == 250:
                    finish = self.pending.find(bytes([255, 240]), index + 2)
                    if finish < 0:
                        break
                    index = finish + 2
                else:
                    index += 2
            self.pending = self.pending[index:]
            require(len(self.pending) < 65536 and len(text) < 65536, "Unexpected Telnet response size")
            text += data.decode("utf-8", "replace")
            if re.search(pattern, text, re.I):
                return text
        raise TimeoutError("Expected Telnet prompt not received")

    def send(self, value):
        require("\n" not in value and "\r" not in value, "Invalid Telnet input")
        self.sock.sendall(value.encode() + b"\r\n")

    def login(self, username, password):
        self.receive(r"(?:login|username)\s*:")
        self.send(username)
        self.receive(r"password\s*:")
        self.send(password)
        self.receive(PROMPT)

    def verify(self, username, password):
        self.login(username, password)
        self.send("id")
        identity = self.receive(PROMPT)
        require(re.search(r"\buid=0(?:\D|$)", identity) is not None, "Login is not a verified root shell")
        self.send("uname -n")
        host = self.receive(PROMPT)
        require(re.search(r"(?:^|[\r\n])SR7420(?:[\r\n]|$)", host) is not None,
                "Unexpected hostname: verify the device manually")
        return {"root_verified": True, "hostname": "SR7420", "transport": "LAN Telnet"}

    def start_ssh(self, username, password):
        """Fixed bootstrap action only; no arbitrary shell command parameter."""
        self.login(username, password)
        self.send('/Plugin/local-ssh/start.sh; printf "\\nSR7420_SSH_START:%s\\n" "$?"')
        reply = self.receive(PROMPT, seconds=25)
        require(re.search(r"(?:^|[\r\n])SR7420_SSH_START:0(?:[\r\n]|$)", reply) is not None,
                "SSH bootstrap did not report success")
