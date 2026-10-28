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
