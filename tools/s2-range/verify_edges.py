#!/usr/bin/env python3
"""Shielded TX->RX check of the S2 tuning edges: the Mini (TXTONE with LO
argument) sends tone bursts at LO + 4.264784 MHz, the Feather captures at a
receive LO and looks for the tone. Confirmation uses the golden-ratio test's
rule: >=2 on-captures whose target peak beats every off-capture by 10 dB and
the local floor by 15 dB.

Usage: verify_edges.py MINI FEATHER --shielded TX_LO[:RX_LO[:MODE]] ...
MODE (AUTO/DIV/DIRECT) is applied to both boards. RX_LO defaults to TX_LO.
"""
import argparse, json, os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep import Sdr, parse_pll

TONE_OFFSET = 4.264784e6
FS, N, RATE = 16e6, 12284, 6  # rate index 6: 768 us per capture; --rate 1 = 40 MS/s
SEARCH = 250e3               # allowance for the ~65 kHz board-to-board error


def tone_peak(iq, expected):
    """Best peak within SEARCH of +/-expected (both I/Q sign conventions)."""
    iq = iq - iq.mean()
    spec = np.abs(np.fft.fft(iq * np.hanning(len(iq)))) ** 2
    f = np.fft.fftfreq(len(iq), 1 / FS)
    best = None
    for sign in (1, -1):
        sel = np.abs(f - sign * expected) < SEARCH
        if not sel.any():
            continue
        k = np.flatnonzero(sel)[np.argmax(spec[sel])]
        local = np.abs(f - f[k]) < 1.5e6
        floor = np.median(spec[local])
        cand = (10 * np.log10(spec[k]), 10 * np.log10(spec[k] / floor), f[k])
        if best is None or cand[0] > best[0]:
            best = cand
    return best or (-np.inf, 0.0, np.nan)  # (peak_db, contrast_db, offset_hz)


def run(mini, feather, tx_lo, rx_lo, mode, gain_tx, gain_rx, sessions, expect=None):
    for b in (mini, feather):
        b.cmd(f"LOMODE {mode}")
    feather.cmd(f"GAIN MANUAL {gain_rx}")
    feather.cmd("BANDWIDTH 0" if RATE == 1 else "LPF AUTO")  # widest filter only for 40 MS/s
    assert feather.cmd(f"FREQ {rx_lo}") == "OK"
    rx_pll = parse_pll(feather.cmd("PLL?"))
    expected = (tx_lo - rx_lo) * 1e6 + TONE_OFFSET if expect is None else expect
    off = [tone_peak(feather.capture(N, RATE), expected) for _ in range(10)]
    on, tx_results = [], []
    for _ in range(sessions):
        reply = {}
        def tx():
            reply["start"] = mini.cmd(f"TXTONE 200 5 {gain_tx} {tx_lo}")
            if reply["start"].startswith("TONESTART"):
                reply["end"] = mini.s.readline().decode().strip()
        t = threading.Thread(target=tx); t.start()
        time.sleep(0.15)
        while t.is_alive():
            on.append(tone_peak(feather.capture(N, RATE), expected))
        t.join(); tx_results.append(reply)
        if not reply["start"].startswith("TONESTART"):
            break
    tx_pll = parse_pll(mini.cmd("PLL?"))
    off += [tone_peak(feather.capture(N, RATE), expected) for _ in range(10)]
    off_max = max(p for p, _, _ in off)
    hits = [(p, c, f) for p, c, f in on if p > off_max + 10 and c > 15]
    for b in (mini, feather):
        b.cmd("LOMODE AUTO")
    return {
        "tx_lo": tx_lo, "rx_lo": rx_lo, "mode": mode, "expected_offset_hz": expected,
        "tx": tx_results, "tx_pll": tx_pll, "rx_pll": rx_pll,
        "on_captures": len(on), "off_captures": len(off), "hits": len(hits),
        "confirmed": len(hits) >= 2,
        "best_rise_db": max(p for p, _, _ in on) - off_max if on else None,
        "hit_offsets_hz": sorted({round(f) for _, _, f in hits}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mini"); ap.add_argument("feather")
    ap.add_argument("tests", nargs="+")
    ap.add_argument("--shielded", action="store_true", required=True)
    ap.add_argument("--tx-gain", type=int, default=16)
    ap.add_argument("--rx-gain", type=int, default=30)
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--out", default="runs/verify.json")
    ap.add_argument("--rate", type=int, choices=[1, 6], default=6, help="6 = 16 MS/s, 1 = 40 MS/s")
    a = ap.parse_args()
    global FS, RATE
    RATE, FS = a.rate, {1: 40e6, 6: 16e6}[a.rate]
    mini, feather = Sdr(a.mini), Sdr(a.feather)
    results = []
    try:
        for spec in a.tests:
            parts = spec.split(":")
            tx_lo = int(parts[0]); rx_lo = int(parts[1]) if len(parts) > 1 and parts[1] else tx_lo
            mode = parts[2] if len(parts) > 2 and parts[2] else "AUTO"
            # optional 4th field: expected baseband offset in MHz (hypothesis tests)
            expect = float(parts[3]) * 1e6 if len(parts) > 3 else None
            r = run(mini, feather, tx_lo, rx_lo, mode, a.tx_gain, a.rx_gain, a.sessions, expect)
            results.append(r)
            txs = r["tx"][0].get("start", "")[:20] if r["tx"] else ""
            print(f"TX {tx_lo:4d} RX {rx_lo:4d} {mode:6s} tx={txs!r:24s} "
                  f"rxlock={r['rx_pll']['ok'] or not r['rx_pll']['searched']} "
                  f"hits={r['hits']}/{r['on_captures']} rise={r['best_rise_db'] or 0:5.1f} dB "
                  f"{'CONFIRMED' if r['confirmed'] else '-'} {r['hit_offsets_hz'][:3]}", flush=True)
    finally:
        json.dump(results, open(a.out, "w"), indent=1, default=float)
        for b in (mini, feather):
            b.cmd("LOMODE AUTO")
        feather.cmd("GAIN HARDWARE"); feather.cmd("LPF AUTO"); feather.cmd("FREQ 2298")
        feather.cmd("RELEASE"); mini.cmd("RELEASE")


if __name__ == "__main__":
    main()
