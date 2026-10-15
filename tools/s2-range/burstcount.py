#!/usr/bin/env python3
"""Count bursty captures per frequency: fraction whose wideband power rises
>6 dB above that frequency's quietest-quartile median. Receive only."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep import Sdr, parse_pll
port, freqs = sys.argv[1], [int(f) for f in sys.argv[2:]]
sdr = Sdr(port); sdr.cmd("GAIN MANUAL 30")
for mhz in freqs:
    sdr.cmd(f"FREQ {mhz}"); pll = parse_pll(sdr.cmd("PLL?"))
    p = []
    for _ in range(40):
        iq = sdr.capture(8192, 1); iq = iq - iq.mean()
        # power in 256-sample blocks; burstiness = max block vs median block
        blk = (np.abs(iq[:8192].reshape(32, 256)) ** 2).mean(1)
        p.append(10 * np.log10(blk.max() / np.median(blk)))
    p = np.array(p); floor = np.median(np.sort(p)[:10])
    lock = "Y" if (pll["ok"] or not pll["searched"]) else "N"
    print(f"{mhz} lock={lock} bursty={np.mean(p > floor + 6) * 100:4.0f}%  max_rise={p.max():5.1f} dB", flush=True)
sdr.cmd("GAIN HARDWARE"); sdr.cmd("RELEASE")
