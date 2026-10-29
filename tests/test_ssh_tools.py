import base64
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from sr7420 import ssh_bridge, ssh_setup
from sr7420.telnet import Telnet


def synthetic_public_key():
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + bytes(range(32))
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " invented-device-comment\n"


class BundleTests(unittest.TestCase):
    def test_generate_only_public_material_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = root / "test.pub"
            key.write_text(synthetic_public_key())
            result = ssh_setup.generate("192.168.1.1", "192.168.1.0/24", key, root / "bundle")
            self.assertEqual({p.name for p in result.iterdir()},
                             {"authorized_keys", "lan.conf", "start.sh", "ssh-bundle-manifest.json"})
            self.assertNotIn("invented-device-comment", (result / "authorized_keys").read_text())
            self.assertEqual((result / "lan.conf").read_text(), "LAN_IP=192.168.1.1\nLAN_CIDR=192.168.1.0/24\n")
            self.assertIn(b"/var/run/local-ssh-pts", (result / "start.sh").read_bytes())
            with self.assertRaises(FileExistsError):
                ssh_setup.generate("192.168.1.1", "192.168.1.0/24", key, result)

    def test_private_key_malformed_key_and_multiple_keys_rejected(self):
        for value in ("-----BEGIN OPENSSH PRIVATE KEY-----", "ssh-ed25519 not-valid-base64",
                      synthetic_public_key() * 2, "ssh-ed25519 " + base64.b64encode(b"bad").decode()):
            with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                ssh_setup.public_ed25519(value)

    def test_reject_unsafe_network_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / "test.pub"
            key.write_text(synthetic_public_key())
            for ip, cidr in [("0.0.0.0", "0.0.0.0/0"), ("192.168.1.1", "192.168.2.0/24"),
                             ("192.168.1.0", "192.168.1.0/24"), ("192.168.1.255", "192.168.1.0/24"),
                             ("192.168.1.1", "192.168.1.5/24")]:
                with self.subTest(ip=ip, cidr=cidr), self.assertRaises(ValueError):
                    ssh_setup.generate(ip, cidr, key, Path(temp) / "never-created")
            self.assertFalse((Path(temp) / "never-created").exists())


class BridgeTests(unittest.TestCase):
    def profile(self, root, **extra):
        path = Path(root) / "profile.json"
        path.write_text(json.dumps({"host": "192.168.1.1", "port": 23, "username": "root",
                                    "password": "fixture-only-password", **extra}))
        return path

    def test_ready_ssh_does_not_read_credentials_or_use_telnet(self):
        connection = Mock()
        with patch.object(socket, "create_connection", return_value=connection), \
             patch.object(ssh_bridge, "Telnet") as telnet:
            self.assertIs(ssh_bridge.connect_or_start("192.168.1.1", "nonexistent-file"), connection)
            telnet.assert_not_called()

    def test_bootstrap_once_then_connect(self):
        with tempfile.TemporaryDirectory() as temp:
            credentials = self.profile(temp)
            connection = Mock()
            with patch.object(socket, "create_connection", side_effect=[OSError(), connection]), \
                 patch.object(ssh_bridge, "Telnet") as telnet:
                self.assertIs(ssh_bridge.connect_or_start("192.168.1.1", credentials), connection)
                telnet.return_value.start_ssh.assert_called_once_with("root", "fixture-only-password")
                telnet.return_value.close.assert_called_once()

    def test_wrong_host_never_sends_telnet_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            credentials = self.profile(temp, host="192.168.2.1")
            with patch.object(socket, "create_connection", side_effect=OSError()), \
                 patch.object(ssh_bridge, "Telnet") as telnet, self.assertRaises(ValueError):
                ssh_bridge.connect_or_start("192.168.1.1", credentials)
            telnet.assert_not_called()

    def test_bootstrap_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            credentials = self.profile(temp)
            with patch.object(socket, "create_connection", side_effect=OSError()), \
                 patch.object(ssh_bridge, "Telnet") as telnet:
                telnet.return_value.start_ssh.side_effect = ValueError("fixture failed")
                with self.assertRaises(ValueError):
                    ssh_bridge.connect_or_start("192.168.1.1", credentials)
                telnet.return_value.start_ssh.assert_called_once()
                telnet.return_value.close.assert_called_once()

    def test_command_echo_does_not_count_as_success(self):
        client = Telnet.__new__(Telnet)
        with patch.object(client, "login"), patch.object(client, "send"), \
             patch.object(client, "receive", return_value='echo SR7420_SSH_START:0\r\n/ # '), \
             self.assertRaises(ValueError):
            client.start_ssh("root", "fixture")

    def test_relay_preserves_binary_stream_and_half_close(self):
        ours, peer = socket.socketpair()
        received = []
        def server():
            chunks = []
            while True:
                data = peer.recv(1024)
                if not data:
                    break
                chunks.append(data)
            received.append(b"".join(chunks))
            peer.sendall(b"SSH-2.0-fixture\r\n\x00\xff\n")
            peer.close()
        task = threading.Thread(target=server, daemon=True)
        task.start()
        outgoing = io.BytesIO()
        ssh_bridge.relay(ours, io.BufferedReader(io.BytesIO(b"client\x00\xff\r\n")), outgoing)
        task.join(timeout=3)
        self.assertEqual(received, [b"client\x00\xff\r\n"])
        self.assertEqual(outgoing.getvalue(), b"SSH-2.0-fixture\r\n\x00\xff\n")


if __name__ == "__main__":
    unittest.main()
