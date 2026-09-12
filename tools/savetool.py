#!/usr/bin/env python3
"""
Read and edit PopCraft's Ruffle save file.

    tools/savetool.py show          dump the story-mode level table
    tools/savetool.py unlock        unlock all levels
    tools/savetool.py lock          re-lock everything except level 1
    tools/savetool.py repair        rewrite the save compressed, changing nothing else
    tools/savetool.py --swf PopCraft.swf show   operate on the other build's save

The save is a Flash Local Shared Object holding one key, "cookie", whose value is a
zlib-compressed ByteArray written by popcraft.UserCookieManager. Layout:

    [0:2]   int16   cookie version (currently 3)
    [2:86]  14 x LevelRecord, 6 bytes each: unlocked:u8, expert:u8, score:int32 (big-endian)
    [86:]   PlayerStats, EndlessLevelManager, PrizeManager, SavedPlayerBits

Only the LevelRecord block is touched; everything after byte 86 is spliced through
untouched, so the other four data sources keep whatever they had.

IMPORTANT: compress with zlib level 9. That is what AS3's ByteArray.compress() emits
(header 78 da), and Ruffle's uncompress() rejects a level-6 stream (78 9c) here: the
game silently resets the save and rewrites it when that happens.

Quit the game before editing; it rewrites the save on exit paths and will clobber edits.
"""

import argparse
import os
import struct
import sys
import zlib

SAVE_ROOT = os.path.expanduser("~/.local/share/ruffle/SharedObjects/localhost")
# Ruffle keys each save by the full path of the SWF that wrote it, so this must match wherever
# the SWFs actually live. Derived from this script's location so moving the tree still works.
SWF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
NUM_LEVELS = 14


def save_path(swf):
    return os.path.join(SAVE_ROOT, SWF_DIR.lstrip("/"), swf, "popcraft.sol")


def u29(b, i):
    n = 0
    for _ in range(3):
        byte = b[i]; i += 1
        n = (n << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return n, i
    return (n << 8) | b[i], i + 1


def u29_encode(n):
    if n < 0x80:     return bytes([n])
    if n < 0x4000:   return bytes([(n >> 7) | 0x80, n & 0x7F])
    if n < 0x200000: return bytes([(n >> 14) | 0x80, ((n >> 7) & 0x7F) | 0x80, n & 0x7F])
    return bytes([(n >> 22) | 0x80, ((n >> 15) & 0x7F) | 0x80,
                  ((n >> 8) & 0x7F) | 0x80, n & 0xFF])


def parse(raw):
    """Locate the cookie ByteArray. Returns (payload_start, payload_end, decompressed)."""
    if raw[0:2] != b"\x00\xbf" or raw[6:10] != b"TCSO":
        sys.exit("not a Flash Local Shared Object")
    i = 16
    namelen = struct.unpack(">H", raw[i:i + 2])[0]; i += 2 + namelen
    amf = struct.unpack(">I", raw[i:i + 4])[0]; i += 4
    if amf != 3:
        sys.exit(f"expected an AMF3 body, got version {amf}")
    hdr, i = u29(raw, i)
    key = raw[i:i + (hdr >> 1)].decode(); i += hdr >> 1
    if key != "cookie":
        sys.exit(f"unexpected key {key!r}")
    if raw[i] != 0x0C:
        sys.exit("cookie value is not a ByteArray")
    i += 1
    lenpos = i                      # where the U29 length starts
    blen, i = u29(raw, i)
    if (blen >> 1) > len(raw) - i:
        sys.exit(f"corrupt save: ByteArray declares {blen >> 1} bytes but only "
                 f"{len(raw) - i} remain")
    payload = raw[i:i + (blen >> 1)]
    try:
        cookie = zlib.decompress(payload)
    except zlib.error:
        # A build with the readLocalCookie() aliasing bug stored the cookie uncompressed.
        # Read it anyway; rebuild() always writes it back compressed.
        if payload[0:1] != b"\x00":
            sys.exit("cookie is neither zlib nor a recognisable raw cookie")
        print("note: save was stored uncompressed; it will be rewritten compressed",
              file=sys.stderr)
        cookie = payload
    return lenpos, i, i + (blen >> 1), cookie


def rebuild(raw, lenpos, end, cookie):
    """Splice a new cookie in, fixing the U29 and the SOL length field.

    lenpos must be where the old U29 length begins, since it can be 1..4 bytes wide, and a
    multi-byte one cannot be found by scanning backwards from the payload (its final byte
    has the high bit clear, like a single-byte one).
    """
    comp = zlib.compress(cookie, 9)
    out = raw[:lenpos] + u29_encode((len(comp) << 1) | 1) + comp + raw[end:]
    return out[:2] + struct.pack(">I", len(out) - 6) + out[6:]


def records(cookie):
    for n in range(NUM_LEVELS):
        o = 2 + n * 6
        yield n, o, cookie[o], cookie[o + 1], struct.unpack(">i", cookie[o + 2:o + 6])[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["show", "unlock", "lock", "repair"])
    ap.add_argument("--swf", default="PopCraft-offline.swf",
                    help="which build's save to use (each SWF has its own)")
    args = ap.parse_args()

    path = save_path(args.swf)
    if not os.path.exists(path):
        sys.exit(f"no save at {path}\n(run the game once to create one)")

    with open(path, "rb") as fh:
        raw = fh.read()
    lenpos, _start, end, cookie = parse(raw)
    cookie = bytearray(cookie)
    version = struct.unpack(">h", cookie[0:2])[0]

    if args.command == "show":
        print(f"{path}\ncookie version {version}, {len(cookie)} bytes\n")
        print(" lvl  unlocked  expert  score")
        for n, _, unl, exp, score in records(cookie):
            print(f"  {n + 1:2d}     {bool(unl)!s:5}   {bool(exp)!s:5}  {score:6d}")
        return

    if args.command == "repair":
        # Rewrite as-is; rebuild() always emits a level-9 zlib stream, which is what
        # ByteArray.uncompress() expects.
        with open(path, "wb") as fh:
            fh.write(rebuild(raw, lenpos, end, bytes(cookie)))
        print(f"rewrote {path} in canonical compressed form")
        return

    before = bytes(cookie)
    for n, o, _, _, _ in records(cookie):
        cookie[o] = 1 if args.command == "unlock" else (1 if n == 0 else 0)
    if args.command == "lock":
        for _, o, _, _, _ in records(cookie):
            struct.pack_into(">i", cookie, o + 2, 0)

    if bytes(cookie) == before:
        print("no change needed")
        return

    assert len(cookie) == len(before), "cookie length must not change"
    with open(path, "wb") as fh:
        fh.write(rebuild(raw, lenpos, end, bytes(cookie)))
    print(f"{args.command}ed all levels -> {path}")


if __name__ == "__main__":
    main()
