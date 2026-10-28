"""Narrow Type-4 format implementation based on mkst/zte-config-utility.

See THIRD_PARTY_NOTICES.md and LICENSES/zte-config-utility.txt.
The model-wide key material below is published upstream, not a device credential.
"""
import hashlib
import struct
import zlib

from Cryptodome.Cipher import AES

MAGIC = 0x01020304
LIMIT = 8 * 1024 * 1024
KEY = hashlib.sha256(b"SR7410Key80748010").digest()
IV = hashlib.sha256(b"SR7410Iv80748010").digest()[:16]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(blob):
    """Return XML bytes and compression chunk size; reject truncation/corruption."""
    require(72 <= len(blob) <= LIMIT, "Invalid backup size")
    outer = struct.unpack(">15I", blob[:60])
    require(outer[:2] == (MAGIC, 4), "Unsupported format: expected raw Type-4 backup")
    # Only the single encrypted segment observed on the tested firmware is accepted.
    plain_size, cipher_size, more = struct.unpack(">3I", blob[60:72])
    require(more == 0 and cipher_size % 16 == 0, "Unsupported encrypted segment layout")
    require(60 <= plain_size <= cipher_size <= LIMIT, "Invalid segment lengths")
    require(cipher_size - plain_size < 16, "Invalid padding length")
    require(len(blob) == 72 + cipher_size, "Truncated backup or unexpected trailing bytes")
    plain = AES.new(KEY, AES.MODE_CBC, IV).decrypt(blob[72:])[:plain_size]
    header = struct.unpack(">15I", plain[:60])
    require(header[:2] == (MAGIC, 0), "Model key mismatch or invalid compressed payload")
    require(zlib.crc32(plain[:24]) & 0xFFFFFFFF == header[6], "Header CRC mismatch")
    require(0 < header[2] <= LIMIT and 0 < header[4] <= LIMIT, "Invalid XML size/chunk size")
    position, crc, total = 60, 0, 0
    parts = []
    while True:
        require(position + 12 <= len(plain), "Truncated compression header")
        size, compressed_size, following = struct.unpack(">3I", plain[position:position + 12])
        position += 12
        require(0 < size <= header[4] and total + size <= LIMIT, "Invalid XML chunk length")
        require(position + compressed_size <= len(plain), "Truncated compressed chunk")
        compressed = plain[position:position + compressed_size]
        position += compressed_size
        decoder = zlib.decompressobj()
        data = decoder.decompress(compressed, size + 1)
        require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
                "Invalid compressed stream")
        require(len(data) == size, "Decompressed length mismatch")
        parts.append(data)
        total += size
        crc = zlib.crc32(compressed, crc)
        if following == 0:
            break
    require(position == len(plain), "Unexpected compressed trailing bytes")
    require(total == header[2], "Total XML length mismatch")
    require(crc & 0xFFFFFFFF == header[5], "Payload CRC mismatch")
    return b"".join(parts), header[4]


def encode(xml, chunk_size):
    require(0 < len(xml) <= LIMIT and 0 < chunk_size <= LIMIT, "Invalid XML size")
    blocks, crc, cumulative = [], 0, 60
    for offset in range(0, len(xml), chunk_size):
        raw = xml[offset:offset + chunk_size]
        compressed = zlib.compress(raw, 9)
        # A final block terminates the stream even when it fills the chunk.
        following = offset + len(raw) < len(xml)
        if following:
            cumulative += len(compressed) + 12
        blocks.append(struct.pack(">3I", len(raw), len(compressed), cumulative if following else 0) + compressed)
        crc = zlib.crc32(compressed, crc)
    header = struct.pack(">6I", MAGIC, 0, len(xml), cumulative, chunk_size, crc & 0xFFFFFFFF)
    plain = header + struct.pack(">I", zlib.crc32(header) & 0xFFFFFFFF) + bytes(32) + b"".join(blocks)
    padded = plain + bytes((-len(plain)) % 16)
    encrypted = AES.new(KEY, AES.MODE_CBC, IV).encrypt(padded)
    blob = struct.pack(">15I", MAGIC, 4, *([0] * 13))
    blob += struct.pack(">3I", len(plain), len(encrypted), 0) + encrypted
    require(decode(blob)[0] == xml, "Encoding round-trip failed")
    return blob
