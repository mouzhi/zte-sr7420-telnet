import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import struct
import zlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch as mock_patch
from urllib.parse import parse_qs

from sr7420 import cli, codec, config
from sr7420.storage import private_directory, write_private
from sr7420.telnet import Telnet, PROMPT
from sr7420.web import Router, lan_host
from tests.support import synthetic_xml


class ConfigTests(unittest.TestCase):
    def test_multichunk_and_exact_boundary(self):
        for data, size in [(synthetic_xml(), 256), (b"a" * 1024, 256), (b"small", 65536)]:
            with self.subTest(size=len(data)):
                self.assertEqual(codec.decode(codec.encode(data, size)), (data, size))

    def test_truncation_corruption_and_trailing_bytes(self):
        blob = codec.encode(synthetic_xml(), 65536)
        broken = bytearray(blob)
        broken[80] ^= 1
        for value in (blob[:-16], blob + b"x", bytes(broken), b"not a router backup"):
            with self.subTest(size=len(value)), self.assertRaises(ValueError):
                codec.decode(value)

    def test_crc_is_checked_not_just_decryption(self):
        from Cryptodome.Cipher import AES
        blob = codec.encode(synthetic_xml(), 65536)
        clear = bytearray(AES.new(codec.KEY, AES.MODE_CBC, codec.IV).decrypt(blob[72:]))
        clear[23] ^= 1
        clear[24:28] = struct.pack(">I", zlib.crc32(clear[:24]) & 0xFFFFFFFF)
        encrypted = AES.new(codec.KEY, AES.MODE_CBC, codec.IV).encrypt(clear)
        with self.assertRaisesRegex(ValueError, "Payload CRC mismatch"):
            codec.decode(blob[:72] + encrypted)

    def test_exact_four_changes_and_no_unrelated_edits(self):
        original = synthetic_xml()
        modified, changes = config.patch(original, "A" * 32)
        self.assertEqual(len(changes), 4)
        self.assertIn(b"KEEP_THIS_SYNTHETIC_VALUE", modified)
        self.assertIn(b'name="Wan_Enable" val="0"', modified)
        self.assertEqual(codec.decode(codec.encode(modified, 65536))[0], modified)
        reversed_xml = modified.replace(b'name="TS_Enable" val="1"', b'name="TS_Enable" val="0"')
        reversed_xml = reversed_xml.replace(b'name="Lan_Enable" val="1"', b'name="Lan_Enable" val="0"')
        reversed_xml = reversed_xml.replace(b'name="ServIPMode" val="1"', b'name="ServIPMode" val="0"')
        reversed_xml = reversed_xml.replace(("A" * 32).encode(), b"synthetic-old-value")
        self.assertEqual(original, reversed_xml)

    def test_unsafe_or_already_configured_state_is_rejected(self):
        for a, b in [(b'Wan_Enable" val="0', b'Wan_Enable" val="1'),
                     (b'TS_Enable" val="0', b'TS_Enable" val="1'),
                     (b'Ipv6Enable" val="1', b'Ipv6Enable" val="0'),
                     (b'Ipv4Level" val="High', b'Ipv4Level" val="Low')]:
            with self.subTest(field=a), self.assertRaises(ValueError):
                config.patch(synthetic_xml().replace(a, b), "A" * 32)

    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError):
            config.parse(b'<!DOCTYPE x [<!ENTITY y "z">]><x>&y;</x>')

    def test_output_no_clobber(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = private_directory(Path(temp) / "private")
            write_private(folder / "original.bin", b"first")
            with self.assertRaises(FileExistsError):
                write_private(folder / "original.bin", b"second")
            self.assertEqual((folder / "original.bin").read_bytes(), b"first")

    def test_cli_prepare_and_hash_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "backup"
            source.mkdir()
            blob = codec.encode(synthetic_xml(), 65536)
            (source / "original.bin").write_bytes(blob)
            manifest = {"model": config.MODEL, "firmware": config.FIRMWARE, "host": "192.168.1.1",
                        "sha256": hashlib.sha256(blob).hexdigest()}
            (source / "backup-manifest.json").write_text(json.dumps(manifest))
            args = type("Args", (), {"backup_dir": source, "output_dir": Path(temp) / "candidate"})()
            report = cli.prepare(args)
            self.assertEqual(report["status"], "PREPARED_NOT_APPLIED")
            credentials = json.loads((args.output_dir / "telnet-credentials.json").read_text())
            self.assertNotIn(credentials["password"], json.dumps(report))
            self.assertEqual((source / "original.bin").read_bytes(), blob)
            (source / "original.bin").write_bytes(blob[:-1])
            with self.assertRaises(ValueError):
                cli.prepare(args)

    def test_public_destination_rejected(self):
        for host in ("203.0.114.1", "0.0.0.0", "224.0.0.1", "example.com"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                lan_host(host)


class WebTests(unittest.TestCase):
    def test_auth_backup_cookie_rotation_keepalive_and_no_restore(self):
        blob = codec.encode(synthetic_xml(), 65536)
        events = []
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args): pass
            def reply(self, body, cookie=None, token=None):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                if cookie: self.send_header("Set-Cookie", cookie)
                if token: self.send_header("X_XSRF_TOKEN", token)
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                events.append((self.command, self.path, dict(self.headers), b""))
                if "login_token_json" in self.path:
                    self.reply(json.dumps({"logintoken": "fixture-nonce", "_sessionToken": "fixture-before"}).encode(), "sid=before")
                else: self.reply(b"fixture-index")
            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                events.append((self.command, self.path, dict(self.headers), data))
                if "login_entry" in self.path:
                    self.reply(json.dumps({"login_need_refresh": True, "sess_token": "fixture-after"}).encode(), "sid=after")
                elif "vue_loadprevent_data" in self.path:
                    self.reply(b"<root><IF_ERRORSTR>SUCC</IF_ERRORSTR></root>", token="fixture-export")
                else: self.reply(blob)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        router = Router("127.0.0.1", server.server_port)
        try:
            router.login("fixture-admin-password")
            self.assertEqual(router.backup(), blob)
        finally:
            router.close(); server.shutdown(); server.server_close(); thread.join()
        post = next(e for e in events if "login_entry" in e[1])
        form = parse_qs(post[3].decode())
        self.assertEqual(form["Password"], [hashlib.sha256(b"fixture-admin-passwordfixture-nonce").hexdigest()])
        self.assertNotIn(b"fixture-admin-password", post[3])
        export = events[-1]
        self.assertEqual(export[2]["Connection"], "keep-alive")
        self.assertEqual(export[2]["Cookie"], "sid=after")
        self.assertIn(b'name="config"', export[3])
        self.assertFalse(any("restore" in event[1] for event in events))


class TelnetTests(unittest.TestCase):
    def test_fragmented_negotiation_and_xml_not_prompt(self):
        class Socket:
            def __init__(self):
                self.chunks = [b"\xff", b"\xfd", b"\x18<row>\r\n", b"still data\r\n/ # "]
                self.sent = []
            def recv(self, size): return self.chunks.pop(0) if self.chunks else b""
            def sendall(self, data): self.sent.append(data)
        client = Telnet.__new__(Telnet)
        client.sock = Socket(); client.pending = b""
        output = client.receive(PROMPT)
        self.assertIn("still data", output)
        self.assertIn(bytes([255, 252, 24]), client.sock.sent)

    def test_no_uid_zero_means_not_verified(self):
        client = Telnet.__new__(Telnet)
        with mock_patch.object(client, "receive", side_effect=["login:", "Password:", "/ # ", "uid=1000(user)\r\n/ # "]), \
             mock_patch.object(client, "send"), self.assertRaises(ValueError):
            client.verify("root", "fixture-password")


if __name__ == "__main__":
    unittest.main()
