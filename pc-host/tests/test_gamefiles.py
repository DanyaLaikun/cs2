import struct
import unittest
import zlib

from telemetry_host.gamefiles import decode_bc, encode_png, lz4_block_decompress, parse_overview


class Lz4Test(unittest.TestCase):
    def test_literals_then_match(self):
        block = bytes([0x44]) + b"abcd" + bytes([4, 0])  # 4 literals, match offset 4 length 8
        self.assertEqual(lz4_block_decompress(block, 12), b"abcdabcdabcd")

    def test_overlapping_run(self):
        block = bytes([0x11]) + b"a" + bytes([1, 0])  # offset 1: repeat the previous byte
        self.assertEqual(lz4_block_decompress(block, 6), b"aaaaaa")

    def test_extended_lengths(self):
        literals = bytes(range(20))
        block = bytes([0xFF, 5]) + literals + bytes([20, 0, 3])  # 15+5 literals, match 15+3+4 = 22
        self.assertEqual(lz4_block_decompress(block, 42), literals + literals + literals[:2])

    def test_corrupt_offset(self):
        with self.assertRaises(ValueError):
            lz4_block_decompress(bytes([0x10]) + b"a" + bytes([9, 0]), 5)


class BlockCompressionTest(unittest.TestCase):
    def test_bc1_solid_block(self):
        block = struct.pack("<HHI", 0xF800, 0x001F, 0)  # all pixels use color0 = pure red
        self.assertEqual(decode_bc(block, 4, 4, bc3=False), bytes((255, 0, 0, 255)) * 16)

    def test_bc1_transparent_mode(self):
        block = struct.pack("<HHI", 0x001F, 0xF800, 0xFFFFFFFF)  # c0 <= c1: index 3 is transparent
        self.assertEqual(decode_bc(block, 4, 4, bc3=False), bytes(4) * 16)

    def test_bc3_alpha(self):
        alpha_bits = (0b001 * sum(1 << (3 * i) for i in range(16))).to_bytes(6, "little")  # every pixel -> alpha1
        block = bytes([255, 0]) + alpha_bits + struct.pack("<HHI", 0x07E0, 0, 0)  # green
        self.assertEqual(decode_bc(block, 4, 4, bc3=True), bytes((0, 255, 0, 0)) * 16)


class PngTest(unittest.TestCase):
    def test_round_trip(self):
        rgba = bytes(range(2 * 2 * 4))
        png = encode_png(2, 2, rgba)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height, depth, color_type = struct.unpack(">IIBB", png[16:26])
        self.assertEqual((width, height, depth, color_type), (2, 2, 8, 6))
        idat_len = struct.unpack(">I", png[33:37])[0]
        raw = zlib.decompress(png[41:41 + idat_len])
        self.assertEqual(raw, b"\0" + rgba[:8] + b"\0" + rgba[8:])


class OverviewTest(unittest.TestCase):
    def test_single_level(self):
        text = '"de_dust2"\n{\n "material" "overviews/de_dust2"\n "pos_x" "-2476"\n "pos_y" "3239"\n "scale" "4.4"\n}\n'
        self.assertEqual(parse_overview(text), {"posX": -2476, "posY": 3239, "scale": 4.4})

    def test_vertical_sections(self):
        text = """
        "de_nuke"
        {
            "pos_x" "-3453" "pos_y" "2887" "scale" "7.00"
            "verticalsections"
            {
                "default" { "AltitudeMax" "10000" "AltitudeMin" "-495" }  // upper radar
                "lower"   { "AltitudeMax" "-495"  "AltitudeMin" "-10000" }
            }
        }"""
        self.assertEqual(parse_overview(text), {"posX": -3453, "posY": 2887, "scale": 7, "splitZ": -495})

    def test_incomplete(self):
        self.assertIsNone(parse_overview('"x" { "pos_x" "1" }'))


if __name__ == "__main__":
    unittest.main()
