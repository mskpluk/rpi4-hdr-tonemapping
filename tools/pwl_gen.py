#!/usr/bin/env python3
"""PQ to SDR curve for the BCM2711 HVS gamma block.

BT.2390 EETF in the PQ domain, then BT.1886 (2.4) encoding, fitted to the
16-point piecewise linear function of the HVS5 gamma block.

    pwl_gen.py [source peak cd/m2] [SDR white cd/m2]    (default 4000 203)

Prints the 32 words for vc4.hvs5_pq_pwl as C source and as a kernel
command line value, the fit error, and a few sample points.
"""
import sys

import numpy as np

m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875


def pq_eotf(e):
    p = np.power(np.clip(e, 0, 1), 1 / m2)
    return 10000 * np.power(np.maximum(p - c1, 0) / (c2 - c3 * p), 1 / m1)


def pq_oetf(L):
    y = np.power(np.clip(L, 0, 10000) / 10000, m1)
    return np.power((c1 + c2 * y) / (1 + c3 * y), m2)


def curve(e, src_peak=4000.0, white=203.0):
    """PQ signal -> SDR signal (BT.1886 2.4) with white at `white` cd/m2."""
    # BT.2390 EETF: highlights rolled off in the PQ domain into `white`
    smax = pq_oetf(src_peak)
    tmax = pq_oetf(white)
    E1 = np.clip(e / smax, 0, 1)
    maxl = tmax / smax
    ks = 1.5 * maxl - 0.5
    t = (E1 - ks) / (1 - ks)
    p = ((2 * t**3 - 3 * t**2 + 1) * ks + (t**3 - 2 * t**2 + t) * (1 - ks)
         + (-2 * t**3 + 3 * t**2) * maxl)
    E2 = np.where(E1 < ks, E1, p)
    L = pq_eotf(E2 * smax)
    return np.clip(L / white, 0, 1) ** (1 / 2.4)


def hw_eval(entries, x):
    """What the hardware computes: C (U12.4) + (x - X) * gradient (U4.8)."""
    xs = np.array([e[0] for e in entries])
    i = np.searchsorted(xs, x, side="right") - 1
    c = np.array([e[1] for e in entries])[i] / 16.0
    g = np.array([e[2] for e in entries])[i] / 256.0
    return np.clip(c + (x - xs[i]) * g, 0, 4095)


def fit(f, n=16):
    X = np.arange(4096)
    Y = f(X / 4095.0) * 4095

    def build(knots):
        ent = []
        for k in range(n):
            x0 = knots[k]
            x1 = knots[k + 1] if k + 1 < n else 4095
            y0, y1 = Y[x0], Y[x1]
            g = (y1 - y0) / max(x1 - x0, 1)
            ent.append((int(x0), int(round(y0 * 16)), int(min(round(g * 256), 0xfff))))
        return ent

    def maxerr(ent):
        return np.max(np.abs(hw_eval(ent, X) - Y))

    # greedy: go as far as the error bound allows, bisect on the bound
    def greedy(tol):
        knots = [0]
        while knots[-1] < 4095 and len(knots) <= n:
            a = knots[-1]
            best = a + 1
            for b in range(a + 1, 4096):
                seg = Y[a:b + 1]
                lin = Y[a] + (Y[b] - Y[a]) * (np.arange(b - a + 1) / (b - a))
                if np.max(np.abs(seg - lin)) <= tol:
                    best = b
                else:
                    break
            knots.append(best)
        return knots

    lo, hi = 0.0, 200.0
    for _ in range(30):
        mid = (lo + hi) / 2
        k = greedy(mid)
        if len(k) <= n + 1 and k[-1] >= 4095:
            hi = mid
        else:
            lo = mid
    k = greedy(hi)[:n]
    while len(k) < n:
        k.append(min(k[-1] + 1, 4095))
    ent = build(k)
    return ent, maxerr(ent), X, Y


if __name__ == "__main__":
    src_peak = float(sys.argv[1]) if len(sys.argv) > 1 else 4000
    white = float(sys.argv[2]) if len(sys.argv) > 2 else 203
    ent, err, _, _ = fit(lambda e: curve(e, src_peak, white))
    print(f"/* PQ to SDR: BT.2390 EETF {src_peak:.0f} -> {white:.0f} cd/m2, "
          f"BT.1886 2.4; max error {err:.1f}/4095 */")
    words = []
    for x, c, g in ent:
        words += [(x << 20) | c, g]
        print(f"\t0x{(x << 20) | c:08x}, 0x{g:08x}, "
              f"/* x {x:4d} c {c / 16:7.1f} grad {g / 256:6.3f} */")
    print("\nvc4.hvs5_pq_pwl=" + ",".join(str(w) for w in words))
    print()
    for L in (0.1, 1, 10, 100, white, 1000, src_peak):
        e = pq_oetf(L)
        hw = hw_eval(ent, np.array([int(round(e * 4095))]))[0] / 4095
        print(f"{L:7g} cd/m2  PQ {e:.3f} -> {hw:.3f}, {100 * hw ** 2.4:5.1f} % of SDR white")
