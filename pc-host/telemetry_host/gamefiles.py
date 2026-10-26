"""Read radar images and overview calibration straight out of the local CS2 install.

Everything here is read-only against the game files: pak01_dir.vpk (Valve's VPK v2 archive) holds
the radar textures as compiled Source 2 textures (`*.vtex_c`) and the overview files
(`resource/overviews/<map>.txt`) with the world-to-radar calibration. Radar textures are stored
as BGRA8888 with LZ4-compressed mip levels; this module decodes them to PNG with the standard
library only (zlib for PNG, a small LZ4 block decoder).
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .steam import find_cs2_dir, parse_vdf

RADAR_DIR_IN_VPK = "panorama/images/overheadmaps/"
OVERVIEW_DIR_IN_VPK = "resource/overviews/"
_VPK_SIGNATURE = 0x55AA1234
_EMBEDDED = 0x7FFF  # archive index meaning "stored inside the _dir.vpk itself"

# Texture formats, in ValveResourceFormat's VTexFormat numbering.
_FMT_DXT1 = 1
_FMT_DXT5 = 2
_FMT_RGBA8888 = 4
_FMT_BGRA8888 = 28
_BLOCK_BYTES = {_FMT_DXT1: 8, _FMT_DXT5: 16}
_EXTRA_COMPRESSED_MIP_SIZE = 4


# --- VPK ------------------------------------------------------------------------------------------


@dataclass
class VpkEntry:
    archive: int
    offset: int
    length: int
    preload: bytes


class Vpk:
    """Directory of a multi-part VPK (v1 or v2). Only the directory is read up front."""

    def __init__(self, dir_path: Path) -> None:
        self.dir_path = dir_path
        data = dir_path.read_bytes()
        signature, version, tree_size = struct.unpack_from("<III", data, 0)
        if signature != _VPK_SIGNATURE or version not in (1, 2):
            raise ValueError(f"{dir_path} is not a VPK v1/v2 directory")
        header = 28 if version == 2 else 12
        self._embedded_base = header + tree_size
        self._dir_data = data
        self.entries: dict[str, VpkEntry] = {}
        pos = header
        while True:
            ext, pos = _cstr(data, pos)
            if not ext:
                break
            while True:
                folder, pos = _cstr(data, pos)
                if not folder:
                    break
                while True:
                    name, pos = _cstr(data, pos)
                    if not name:
                        break
                    _crc, preload, archive, offset, length, _term = struct.unpack_from("<IHHIIH", data, pos)
                    pos += 18
                    folder_path = "" if folder == " " else folder + "/"
                    ext_part = "" if ext == " " else "." + ext
                    self.entries[f"{folder_path}{name}{ext_part}"] = VpkEntry(archive, offset, length, data[pos:pos + preload])
                    pos += preload

    def read(self, path: str) -> bytes:
        entry = self.entries[path]
        if entry.length == 0:
            return entry.preload
        if entry.archive == _EMBEDDED:
            start = self._embedded_base + entry.offset
            return entry.preload + self._dir_data[start:start + entry.length]
        part = self.dir_path.with_name(self.dir_path.name.replace("_dir.vpk", f"_{entry.archive:03d}.vpk"))
        with open(part, "rb") as f:
            f.seek(entry.offset)
            return entry.preload + f.read(entry.length)

    def list(self, prefix: str) -> list[str]:
        return sorted(p for p in self.entries if p.startswith(prefix))


def _cstr(buf: bytes, pos: int) -> tuple[str, int]:
    end = buf.index(b"\0", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


# --- Source 2 textures ----------------------------------------------------------------------------


def decode_vtex(blob: bytes) -> tuple[int, int, bytes]:
    """Decode the top mip of a compiled texture to (width, height, RGBA bytes)."""
    file_size, _header_version, _type_version, block_offset, block_count = struct.unpack_from("<IHHII", blob, 0)
    blocks: dict[str, tuple[int, int]] = {}
    pos = 8 + block_offset
    for _ in range(block_count):
        kind = blob[pos:pos + 4].decode("ascii", "replace")
        rel, size = struct.unpack_from("<II", blob, pos + 4)
        blocks[kind] = (pos + 4 + rel, size)
        pos += 12
    if "DATA" not in blocks:
        raise ValueError("texture has no DATA block")
    data = blocks["DATA"][0]
    width, height, depth, fmt, mip_count = struct.unpack_from("<HHHBB", blob, data + 20)
    extra_rel, extra_count = struct.unpack_from("<II", blob, data + 32)
    if fmt not in (_FMT_RGBA8888, _FMT_BGRA8888, *_BLOCK_BYTES) or depth != 1:
        raise ValueError(f"unsupported texture format {fmt} (depth {depth})")

    compressed_sizes: list[int] | None = None
    table = data + 32 + extra_rel
    for i in range(extra_count):
        kind, rel, _size = struct.unpack_from("<III", blob, table + i * 12)
        if kind != _EXTRA_COMPRESSED_MIP_SIZE:
            continue
        at = table + i * 12 + 4 + rel
        is_compressed, sizes_rel, mips = struct.unpack_from("<III", blob, at)
        if is_compressed:
            compressed_sizes = list(struct.unpack_from(f"<{mips}i", blob, at + 4 + sizes_rel))

    def mip_bytes(m: int) -> int:
        w, h = max(1, width >> m), max(1, height >> m)
        if fmt in _BLOCK_BYTES:
            return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * _BLOCK_BYTES[fmt]
        return w * h * 4

    # Mips are stored smallest first; mip 0 (full size) comes last.
    raw_sizes = [mip_bytes(m) for m in range(mip_count)]
    stored = compressed_sizes or raw_sizes
    pos = file_size + sum(stored[m] for m in range(1, mip_count))
    chunk = blob[pos:pos + stored[0]]
    pixels = lz4_block_decompress(chunk, raw_sizes[0]) if compressed_sizes and stored[0] != raw_sizes[0] else chunk
    if len(pixels) != raw_sizes[0]:
        raise ValueError(f"expected {raw_sizes[0]} bytes of pixels, got {len(pixels)}")
    if fmt in _BLOCK_BYTES:
        return width, height, decode_bc(pixels, width, height, bc3=fmt == _FMT_DXT5)
    if fmt == _FMT_BGRA8888:
        rgba = bytearray(pixels)
        rgba[0::4], rgba[2::4] = pixels[2::4], pixels[0::4]
        pixels = bytes(rgba)
    return width, height, pixels


def _rgb565(c: int) -> tuple[int, int, int]:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def decode_bc(data: bytes, width: int, height: int, *, bc3: bool) -> bytes:
    """Decode BC1 (DXT1) or BC3 (DXT5) block-compressed data to RGBA."""
    out = bytearray(width * height * 4)
    block = 16 if bc3 else 8
    pos = 0
    for by in range((height + 3) // 4):
        for bx in range((width + 3) // 4):
            alphas: tuple[int, ...] = ()
            abits = 0
            if bc3:
                a0, a1 = data[pos], data[pos + 1]
                abits = int.from_bytes(data[pos + 2:pos + 8], "little")
                if a0 > a1:
                    alphas = (a0, a1, *(((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)))
                else:
                    alphas = (a0, a1, *(((5 - k) * a0 + k * a1) // 5 for k in range(1, 5)), 0, 255)
            c0, c1, cbits = struct.unpack_from("<HHI", data, pos + (8 if bc3 else 0))
            (r0, g0, b0), (r1, g1, b1) = _rgb565(c0), _rgb565(c1)
            if bc3 or c0 > c1:
                colors = (
                    bytes((r0, g0, b0, 255)), bytes((r1, g1, b1, 255)),
                    bytes(((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255)),
                    bytes(((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255)),
                )
            else:
                colors = (
                    bytes((r0, g0, b0, 255)), bytes((r1, g1, b1, 255)),
                    bytes(((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255)), bytes(4),
                )
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    break
                row = (y * width + bx * 4) * 4
                for px in range(min(4, width - bx * 4)):
                    i = py * 4 + px
                    o = row + px * 4
                    out[o:o + 4] = colors[(cbits >> (2 * i)) & 3]
                    if bc3:
                        out[o + 3] = alphas[(abits >> (3 * i)) & 7]
            pos += block
    return bytes(out)


def lz4_block_decompress(src: bytes, expected_size: int) -> bytes:
    """LZ4 block format (no frame header). Overlapping matches are expanded by pattern repetition."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        literals = token >> 4
        if literals == 15:
            while True:
                b = src[i]
                i += 1
                literals += b
                if b != 255:
                    break
        dst += src[i:i + literals]
        i += literals
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(dst):
            raise ValueError("corrupt LZ4 block (bad match offset)")
        length = token & 15
        if length == 15:
            while True:
                b = src[i]
                i += 1
                length += b
                if b != 255:
                    break
        length += 4
        start = len(dst) - offset
        if offset >= length:
            dst += dst[start:start + length]
        else:
            pattern = bytes(dst[start:])
            dst += (pattern * (length // offset + 1))[:length]
    if len(dst) != expected_size:
        raise ValueError(f"LZ4 produced {len(dst)} bytes, expected {expected_size}")
    return bytes(dst)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


# --- overviews ------------------------------------------------------------------------------------


def parse_overview(text: str) -> dict[str, Any] | None:
    """Calibration from resource/overviews/<map>.txt in maps.json form, or None if incomplete."""
    doc = parse_vdf(text)
    root = next(iter(doc.values()), None)
    if not isinstance(root, dict):
        return None
    body = {k.lower(): v for k, v in root.items()}
    try:
        entry: dict[str, Any] = {
            "posX": float(body["pos_x"]),
            "posY": float(body["pos_y"]),
            "scale": float(body["scale"]),
        }
    except (KeyError, ValueError):
        return None
    sections = body.get("verticalsections")
    if isinstance(sections, dict):
        lower = next((v for k, v in sections.items() if k.lower() == "lower" and isinstance(v, dict)), None)
        if lower is not None:
            bounds = {k.lower(): v for k, v in lower.items()}
            try:
                entry["splitZ"] = float(bounds["altitudemax"])
            except (KeyError, ValueError):
                pass
    for key in ("posX", "posY", "scale", "splitZ"):
        if key in entry and float(entry[key]).is_integer():
            entry[key] = int(entry[key])
    return entry


# --- command --------------------------------------------------------------------------------------


def extract_radars(out_dir: Path, maps_file: Path, *, cs2_dir: Path | None = None, update_maps: bool = True) -> int:
    game = cs2_dir or find_cs2_dir()
    if game is None:
        print("Could not find CS2; pass --cs2-dir", file=sys.stderr)
        return 1
    vpk_path = game / "game" / "csgo" / "pak01_dir.vpk"
    if not vpk_path.exists():
        print(f"{vpk_path} not found", file=sys.stderr)
        return 1
    print(f"Reading {vpk_path}")
    vpk = Vpk(vpk_path)

    overviews: dict[str, dict[str, Any]] = {}
    for path in vpk.list(OVERVIEW_DIR_IN_VPK):
        if path.endswith(".txt"):
            entry = parse_overview(vpk.read(path).decode("utf-8", "replace"))
            if entry:
                overviews[Path(path).stem.lower()] = entry

    # Prefer the "_psd" radar; fall back to "_tga" where that is all the game ships.
    textures: dict[str, str] = {}
    for path in vpk.list(RADAR_DIR_IN_VPK):
        name = Path(path).name
        for suffix in ("_radar_psd.vtex_c", "_radar_tga.vtex_c"):
            if name.endswith(suffix):
                image = name[: -len(suffix)]
                base = image[: -len("_lower")] if image.endswith("_lower") else image
                if base in overviews and (image not in textures or suffix.startswith("_radar_psd")):
                    textures[image] = path

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for image, path in sorted(textures.items()):
        try:
            width, height, rgba = decode_vtex(vpk.read(path))
        except ValueError as exc:
            print(f"  skip {image}: {exc}")
            continue
        target = out_dir / f"{image}.png"
        target.write_bytes(encode_png(width, height, rgba))
        written += 1
        print(f"  {target.name:<28} {width}x{height}  {target.stat().st_size // 1024} KB")
        if image.endswith("_lower") and image[: -len("_lower")] in overviews:
            overviews[image[: -len("_lower")]].setdefault("lowerImage", image)
    print(f"Wrote {written} radar image(s) to {out_dir}")

    if update_maps:
        _update_maps_file(maps_file, overviews)
    return 0 if written else 1


def _update_maps_file(maps_file: Path, overviews: dict[str, dict[str, Any]]) -> None:
    current: dict[str, Any] = json.loads(maps_file.read_text(encoding="utf-8")) if maps_file.exists() else {}
    merged = {k: v for k, v in current.items() if k.startswith("_")}
    changes = []
    for name in sorted(set(current) | set(overviews)):
        if name.startswith("_"):
            continue
        if name in overviews:
            fresh = overviews[name]
            if name in current and current[name] != fresh:
                changes.append(f"  {name}: {current[name]} -> {fresh}")
            elif name not in current:
                changes.append(f"  {name}: added {fresh}")
            merged[name] = fresh
        else:
            merged[name] = current[name]
    lines = ["{"]
    items = list(merged.items())
    for i, (key, value) in enumerate(items):
        lines.append(f"  {json.dumps(key)}: {json.dumps(value)}{',' if i < len(items) - 1 else ''}")
    lines.append("}")
    maps_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Calibration from the game's overview files written to {maps_file}")
    print("\n".join(changes) if changes else "  (no changes)")
