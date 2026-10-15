#!/usr/bin/env python3
"""Sweep ESP-SDR (ESP32-S2) LO upward and record PLL lock + spectrum per step.

Usage: sweep.py PORT START_MHZ STOP_MHZ STEP_MHZ [--gain N] [--rate IDX] [--out PREFIX]
Writes PREFIX.csv (per-step PLL + power stats), PREFIX.npz (spectra) and
PREFIX.png (waterfall: one row per LO step, centred on the LO).
"""
import argparse, struct, sys, time, zlib
import numpy as np
import serial

RATES = [80, 40, 20, 10, 8, 4, 16]  # MS/s by rate index


class Sdr:
    def __init__(self, port):
        # Keep DTR/RTS low: toggling them resets the S2 into ROM download mode.
        self.s = serial.Serial(port=None, baudrate=115200, timeout=5)
        self.s.dtr = self.s.rts = False
        self.s.port = port
        self.s.open()
        time.sleep(4)  # opening the port reboots the S2 shortly afterwards
        self.s.reset_input_buffer()
        self.sync()

    def sync(self):
        """Skip boot log / stale replies until our SYNC nonce echoes back."""
        nonce = int(time.time() * 1000)
        deadline = time.time() + 10
        while time.time() < deadline:
            self.s.write(f"SYNC {nonce}\n".encode())
            end = time.time() + 1
            while time.time() < end:
                if self.s.readline().decode(errors="replace").strip().endswith(f"SYNC {nonce}"):
                    time.sleep(0.2); self.s.reset_input_buffer()
                    return
        raise TimeoutError("board did not answer SYNC")

    def cmd(self, line):
        self.s.write((line + "\n").encode())
        reply = self.s.readline().decode(errors="replace").strip()
        if not reply:
            raise TimeoutError(f"no reply to {line!r}")
        return reply

    def capture(self, n, rate):
        head = self.cmd(f"CAP16 {n} {rate}")
        if not head.startswith("DATA"):
            raise RuntimeError(f"capture failed: {head}")
        _, count, crc, _us = head.split()
        payload = self.s.read(int(count) * 2)
        if zlib.crc32(payload) != int(crc, 16):
            raise RuntimeError("CRC mismatch")
        raw = np.frombuffer(payload, dtype=np.int8).astype(np.float32)
        return (raw[0::2] + 1j * raw[1::2]) / 128.0


def parse_pll(reply):
    fields = dict(kv.split("=") for kv in reply.split()[2:])
    return {k: (int(v, 16) if k in ("status", "now") else int(v)) for k, v in fields.items()}


def spectrum(iq, nfft=1024):
    iq = iq - iq.mean()  # drop DC so the LO-leak spike doesn't dominate
    segs = len(iq) // nfft
    win = np.hanning(nfft)
    ps = np.zeros(nfft)
    for k in range(segs):
        ps += np.abs(np.fft.fft(iq[k * nfft:(k + 1) * nfft] * win)) ** 2
    return 10 * np.log10(np.fft.fftshift(ps / segs) + 1e-12)


def write_png(path, img):
    """Greyscale-to-colour PNG writer (no matplotlib needed)."""
    lo, hi = np.percentile(img, [2, 99.8])
    v = np.clip((img - lo) / (hi - lo + 1e-9), 0, 1)
    rgb = np.stack([np.clip(1.5 * v, 0, 1), np.clip(1.5 * v - 0.4, 0, 1) * 0.9 + 0.1 * v,
                    np.clip(0.6 - abs(v - 0.3) * 2, 0, 1) + np.clip(v - 0.85, 0, 1) * 4], -1)
    rgb = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    h, w, _ = rgb.shape
    rows = b"".join(b"\0" + rgb[y].tobytes() for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port"); ap.add_argument("start", type=int)
    ap.add_argument("stop", type=int); ap.add_argument("step", type=int)
    ap.add_argument("--gain", type=int, help="manual gain index (default: hardware AGC)")
    ap.add_argument("--rate", type=int, default=1, help="rate index, default 1 = 40 MS/s")
    ap.add_argument("--samples", type=int, default=8192)
    ap.add_argument("--out", default="sweep")
    ap.add_argument("--lomode", choices=["AUTO", "DIRECT", "DIV"], default="AUTO",
                    help="force direct PLL or the 5/6 divider (diagnostic)")
    a = ap.parse_args()

    sdr = Sdr(a.port)
    print(sdr.cmd("INFO"), "|", sdr.cmd("VERSION?"), file=sys.stderr)
    print(sdr.cmd(f"GAIN MANUAL {a.gain}" if a.gain is not None else "GAIN HARDWARE"), file=sys.stderr)

    print(sdr.cmd(f"LOMODE {a.lomode}"), file=sys.stderr)
    freqs, spectra, rows = [], [], []
    with open(a.out + ".csv", "w") as csv:
        csv.write("mhz,searched,ok,best,cap,first,last,good,f4,f8,status,now,power_db,peak_over_median_db\n")
        for mhz in range(a.start, a.stop + 1, a.step):
            ok = sdr.cmd(f"FREQ {mhz}")
            if ok != "OK":
                print(f"{mhz}: {ok}", file=sys.stderr); continue
            pll = parse_pll(sdr.cmd("PLL?"))
            iq = sdr.capture(a.samples, a.rate)
            sp = spectrum(iq)
            power = 10 * np.log10(np.mean(np.abs(iq - iq.mean()) ** 2) + 1e-12)
            pom = float(sp.max() - np.median(sp))
            freqs.append(mhz); spectra.append(sp)
            csv.write(",".join(str(x) for x in [mhz, *pll.values(), f"{power:.2f}", f"{pom:.2f}"]) + "\n")
            csv.flush()
            print(f"{mhz:5d} MHz  lock={'Y' if pll['ok'] or not pll['searched'] else 'N'} "
                  f"best={pll['best']:3d} cap={pll['cap']:3d} good={pll['good']:3d} "
                  f"f4={pll['f4']:3d} f8={pll['f8']:3d} pwr={power:6.1f} dB  peak/med={pom:5.1f} dB")
    sdr.cmd("LOMODE AUTO"); sdr.cmd("GAIN HARDWARE"); sdr.cmd("RELEASE")  # hand the LCD view back
    np.savez(a.out + ".npz", freqs=np.array(freqs), spectra=np.array(spectra), rate=RATES[a.rate])
    write_png(a.out + ".png", np.repeat(np.array(spectra), 4, axis=0))
    print(f"wrote {a.out}.csv/.npz/.png", file=sys.stderr)


if __name__ == "__main__":
    main()
