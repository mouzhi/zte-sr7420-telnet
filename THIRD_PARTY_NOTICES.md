# Third-party attribution

The narrow Type-4 backup codec in `sr7420/codec.py` is based on the format research and implementation in [mkst/zte-config-utility](https://github.com/mkst/zte-config-utility), MIT licensed, Copyright (c) 2024 Mark Street.

Reference revision: [`e3a1a7f56c2df26a02f52f72b16173d0702d9ad0`](https://github.com/mkst/zte-config-utility/tree/e3a1a7f56c2df26a02f52f72b16173d0702d9ad0).

Relevant upstream sources:

- [`zcu/xcryptors.py`](https://github.com/mkst/zte-config-utility/blob/e3a1a7f56c2df26a02f52f72b16173d0702d9ad0/zcu/xcryptors.py): CBC key derivation and encrypted segment layout.
- [`zcu/compression.py`](https://github.com/mkst/zte-config-utility/blob/e3a1a7f56c2df26a02f52f72b16173d0702d9ad0/zcu/compression.py): chunked zlib container and CRC fields.
- [`examples/auto.py`](https://github.com/mkst/zte-config-utility/blob/e3a1a7f56c2df26a02f52f72b16173d0702d9ad0/examples/auto.py): published SR7410 model key/IV strings.

The upstream MIT license is retained in [LICENSES/zte-config-utility.txt](LICENSES/zte-config-utility.txt). The model-wide constants are public format knowledge, not credentials from a user's device.

AES is supplied by the separately installed [PyCryptodome / pycryptodomex](https://www.pycryptodome.org/) dependency; its code is not vendored here.

No manufacturer firmware, decompiled firmware source, real router exports, third-party Telnet-enabler binaries, user secrets, or captured sessions are redistributed.

## Dropbear SSH adaptation

`patches/dropbear-2026.94-sr7420-pty.patch` is a local adaptation for [mkj/dropbear](https://github.com/mkj/dropbear) release `DROPBEAR_2026.94`, commit [`28216cd9af822732a1549b78621c2ea9a76a0fe5`](https://github.com/mkj/dropbear/tree/28216cd9af822732a1549b78621c2ea9a76a0fe5). It adds a private Linux devpts allocator and resets an inherited signal mask at server startup. It is not an upstream official feature or an unmodified official binary.

The upstream license, including Matt Johnston's and the OpenSSH/Tatu Ylonen notice for `sshpty.c`, is retained in [LICENSES/dropbear.txt](LICENSES/dropbear.txt). Only a small source patch is included; full Dropbear source, linked libraries and built binaries are not vendored or published as release artifacts by this repository.

The build script obtains official source and uses the user's cross toolchain. If you redistribute a resulting binary, you are responsible for the licenses and source obligations of Dropbear and every linked component, including the chosen C library. The repository's MIT license does not replace those obligations.
