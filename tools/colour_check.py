#!/usr/bin/env python3
"""Colour checks behind the numbers in README.md.

1. Gamut error of the HVS plane matrix (BT.2020 YCbCr to RGB with the
   BT.2020 to BT.709 conversion folded in, PQ domain) against the exact
   conversion in linear light, and the same for no conversion and for the
   2.4/2.2 shortcut in Kodi's video shaders. Every variant goes through the
   same PWL curve, so only the gamut handling differs.
2. Kodi's Hable (shader formula, including that shortcut) next to the HVS
   curve.

Frames: PQ BT.2020 video as full range 16-bit RGB, 960 pixels wide, e.g.

    ffmpeg -ss 1250 -i film.mkv -frames:v 1 -an -sn \\
      -vf "scale=960:-2:in_color_matrix=bt2020:in_range=tv:out_range=pc,format=rgb48le" \\
      -f rawvideo frame1.raw

    colour_check.py frame1.raw frame2.raw ...
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pwl_gen as g  # noqa: E402

ent, _, _, _ = g.fit(lambda e: g.curve(e, 4000, 203))
lut = g.hw_eval(ent, np.arange(4096)) / 4095.0

M2020_709 = np.array([[1.6605, -0.5876, -0.0728],
                      [-0.1246, 1.1329, -0.0083],
                      [-0.0182, -0.1006, 1.1187]])
Kr, Kb = 0.2627, 0.0593
Kg = 1 - Kr - Kb

# HVS words 0x00f00000, 0xfc30d4a8, 0x000a36a9: limited range scale -> full range
K = 255 / 224
HW = {"cr_r": 2.551 / K, "cr_g": -0.95 / K, "cb_g": -0.064 / K, "cb_b": 2.662 / K}
BT2020 = {"cr_r": 2 * (1 - Kr), "cr_g": -2 * Kr * (1 - Kr) / Kg,
          "cb_g": -2 * Kb * (1 - Kb) / Kg, "cb_b": 2 * (1 - Kb)}


def tm(v):
    return lut[np.round(np.clip(v, 0, 1) * 4095).astype(int)]


def lab(rgb):
    """BT.709 RGB shown on a 2.4 display -> CIELAB (D65)."""
    lin = np.clip(rgb, 0, 1) ** 2.4
    xyz = lin @ np.array([[0.4124, 0.3576, 0.1805],
                          [0.2126, 0.7152, 0.0722],
                          [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def csc(y, cb, cr, c):
    return np.stack([y + c["cr_r"] * cr,
                     y + c["cb_g"] * cb + c["cr_g"] * cr,
                     y + c["cb_b"] * cb], -1)


def gamut_errors(frames):
    variants = {"HVS matrix": [], "no gamut conversion": [], "Kodi shader 2.4/2.2": []}
    for f in frames:
        pq = (np.fromfile(f, dtype="<u2").astype(np.float64) / 65535).reshape(-1, 3)
        y = pq @ np.array([Kr, Kg, Kb])
        keep = y > 0.1  # skip black bars and near black
        pq, y = pq[keep], y[keep]
        cb = (pq[:, 2] - y) / (2 * (1 - Kb))
        cr = (pq[:, 0] - y) / (2 * (1 - Kr))
        ref = lab(tm(g.pq_oetf(np.clip(g.pq_eotf(pq) @ M2020_709.T, 0, None))))
        kodi = np.clip(np.clip(pq, 0, None) ** 2.4 @ M2020_709.T, 0, None) ** (1 / 2.2)
        for name, rgb in (("HVS matrix", csc(y, cb, cr, HW)),
                          ("no gamut conversion", csc(y, cb, cr, BT2020)),
                          ("Kodi shader 2.4/2.2", kodi)):
            variants[name].append(np.linalg.norm(lab(tm(rgb)) - ref, axis=-1))
    print("CIE76 error against the exact conversion in linear light")
    for name, d in variants.items():
        d = np.concatenate(d)
        print(f"  {name:20s} mean {d.mean():5.2f}  95th {np.percentile(d, 95):5.2f}  "
              f"99th {np.percentile(d, 99):5.2f}  max {d.max():5.2f}  ({d.size} pixels)")


def hable(x):
    A, B, C, D, E, F = 0.15, 0.5, 0.1, 0.2, 0.02, 0.3
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F


def kodi_hable(L, lumin):
    """% of white on a 2.4 display for a grey of L cd/m2 (tone mapping parameter 1)."""
    seen = g.pq_eotf(g.pq_oetf(L) ** (2.4 / 2.2))  # the 2.4/2.2 shortcut on greys
    v = hable(np.array(seen / 50.0)) / hable(np.array(lumin / 100.0))
    return float(np.clip(v, 0, 1)) ** (2.4 / 2.2) * 100


def hable_table():
    print("\nGrey, % of white   Kodi Hable 1000   Kodi Hable 4000   no metadata (400)   HVS curve")
    for L in (1, 10, 100, 203, 1000):
        ours = tm(np.array([g.pq_oetf(L)]))[0] ** 2.4 * 100
        print(f"  {L:5} cd/m2      {kodi_hable(L, 1000):8.1f}          {kodi_hable(L, 4000):8.1f}"
              f"          {kodi_hable(L, 400):8.1f}          {ours:8.1f}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        gamut_errors(sys.argv[1:])
    hable_table()
