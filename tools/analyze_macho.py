"""Static analysis only. Never executes the supplied macOS executable."""

import argparse
import hashlib
import json
import re
import struct
from urllib.parse import urlsplit
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_ARCH_X86, CS_MODE_64, Cs


def load_slice(path, arch):
    raw = Path(path).read_bytes()
    cpu = {"x86_64": 0x01000007, "arm64": 0x0100000C}[arch]
    if raw[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("Expected a universal Mach-O executable")
    for i in range(struct.unpack_from(">I", raw, 4)[0]):
        kind, _, offset, size, _ = struct.unpack_from(">IIIII", raw, 8 + 20 * i)
        if kind == cpu:
            data = raw[offset : offset + size]
            break
    else:
        raise ValueError(f"Architecture {arch} absent")
    sections = []
    cursor = 32
    for _ in range(struct.unpack_from("<I", data, 16)[0]):
        command, size = struct.unpack_from("<II", data, cursor)
        if command == 0x19:
            for j in range(struct.unpack_from("<I", data, cursor + 64)[0]):
                p = cursor + 72 + 80 * j
                name = data[p : p + 16].rstrip(b"\0").decode()
                address, length, file_offset = struct.unpack_from("<QQI", data, p + 32)
                sections.append((name, address, length, file_offset))
        cursor += size
    return raw, data, sections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--arch", choices=["arm64", "x86_64"], default="arm64")
    parser.add_argument("--range", action="append", default=[], help="hex start:byte count")
    parser.add_argument("--xref", action="append", default=[], help="x86 target address")
    parser.add_argument("--needle", action="append", default=[])
    parser.add_argument("--inventory", action="store_true", help="Report service hostnames and shutdown-related binary strings without URL paths or keys")
    args = parser.parse_args()
    raw, data, sections = load_slice(args.binary, args.arch)
    print(json.dumps({"sha256": hashlib.sha256(raw).hexdigest(), "arch": args.arch}))
    if args.inventory:
        hosts = set()
        markers = set()
        interesting = re.compile(r"sunset|sunsetting|end.of.life|force.{0,12}(update|logout|signout)|minimum.{0,12}version|mandatory.{0,12}update|account.{0,12}(disabled|deleted)|remote.?config|feature.?flag", re.I)
        for name, address, size, offset in sections:
            if name not in ("__cstring", "__const", "__swift5_reflstr"):
                continue
            for match in re.finditer(rb"[ -~]{5,}", data[offset:offset + size]):
                value = match.group().decode()
                for url in re.findall(r"https?://[^\s\"<>]+", value):
                    try:
                        host = urlsplit(url).hostname
                        if host: hosts.add(host)
                    except ValueError:
                        pass
                if len(value) < 220 and interesting.search(value) and "://" not in value:
                    markers.add(value)
        print("HOSTS", json.dumps(sorted(hosts)))
        print("MARKERS", json.dumps(sorted(markers)))
    md = Cs(CS_ARCH_ARM64 if args.arch == "arm64" else CS_ARCH_X86, CS_MODE_64 if args.arch == "x86_64" else 0)
    md.skipdata = True
    for span in args.range:
        start, length = (int(x, 0) for x in span.split(":"))
        for name, address, size, offset in sections:
            if address <= start < address + size:
                p = offset + start - address
                print(f"\nRANGE {hex(start)} {name}")
                for at, width, op, operands in md.disasm_lite(data[p : p + length], start):
                    print(f"{at:#x}  {op:9} {operands}")
                break
        else:
            raise ValueError(f"Range {span} outside sections")
    targets = {int(x, 0): x for x in args.xref}
    for needle in args.needle:
        token = needle.encode()
        p = data.find(token)
        if p < 0:
            print("NEEDLE not found:", needle)
            continue
        for name, address, size, offset in sections:
            if offset <= p < offset + size:
                at = address + p - offset
                targets[at] = needle
                print("NEEDLE", needle, hex(at), name)
                break
    if targets and args.arch == "x86_64":
        _, address, size, offset = next(s for s in sections if s[0] == "__text")
        for at, width, op, operands in md.disasm_lite(data[offset : offset + size], address):
            if op in ("call", "jmp") and operands.startswith("0x"):
                target = int(operands, 16)
            else:
                match = re.search(r"\[rip ([+-]) (0x[0-9a-f]+)\]", operands)
                if not match:
                    continue
                target = at + width + (1 if match[1] == "+" else -1) * int(match[2], 16)
            if target in targets:
                print("XREF", hex(at), op, operands, targets[target])


if __name__ == "__main__":
    main()
