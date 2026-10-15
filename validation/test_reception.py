#!/usr/bin/env python3
"""Bounded LOLIN-to-Feather tone test. Requires pyserial and numpy.

Requires the supplied Mini firmware. Does not flash either board.
Use with both boards in an RF-shielded enclosure.
"""
import argparse
import json
import time
import zlib
from pathlib import Path
import numpy as np
import serial

TARGET = 2298264784
RX_LO = 2298000000
FS = 16000000
N = 4096

def connect(name):
    s = serial.Serial(port=None, baudrate=2000000, timeout=.1, write_timeout=5)
    s.dtr = s.rts = False
    s.port = name
    s.open()
    return s

def command(s, text):
    s.write((text+'\n').encode())
    response = s.readline().decode().strip()
    if response.startswith('ERR') or not response:
        raise RuntimeError(f'{text}: {response!r}')
    return response

def exact(s, count):
    data = bytearray()
    while len(data) < count:
        chunk = s.read(count-len(data))
        if not chunk:
            raise TimeoutError(f'Short capture: {len(data)}/{count}')
        data.extend(chunk)
    return data

def analyze(samples):
    x = samples - samples.mean()
    power = abs(np.fft.fft(x*np.hanning(len(x))))**2
    offsets = np.fft.fftfreq(len(x), 1/FS)
    # Inspect both signs: a mirrored receiver I/Q convention must be reported,
    # rather than silently relabeling the RF frequency.
    result = []
    for sign in (1, -1):
        center = sign*(TARGET-RX_LO)
        region = abs(offsets-center) < 150000
        noise_region = (abs(offsets-center) > 200000) & (abs(offsets-center) < 500000)
        indices = np.flatnonzero(region)
        peak = indices[np.argmax(power[region])]
        floor = max(float(np.median(power[noise_region])), 1e-12)
        result.append(dict(sign=sign, offset_hz=float(offsets[peak]),
                           peak_power=float(power[peak]),
                           contrast_db=float(10*np.log10(max(power[peak],1e-12)/floor))))
    return result

def capture(s):
    header = command(s, f'CAP16 {N} 6').split()
    if len(header) != 4 or header[0] != 'DATA' or int(header[1]) != N:
        raise RuntimeError(f'Unexpected capture header: {header}')
    data = exact(s, N*2)
    if zlib.crc32(data) != int(header[2], 16):
        raise RuntimeError('Capture checksum mismatch')
    iq = np.frombuffer(data, dtype=np.int8).astype(float).reshape(-1, 2)
    return dict(host_time=time.time(), capture_us=int(header[3]),
                candidates=analyze(iq[:,0]+1j*iq[:,1]))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mini-port', required=True)
    p.add_argument('--feather-port', required=True)
    p.add_argument('--shielded', action='store_true', help='Both boards are in an RF-shielded enclosure')
    p.add_argument('--output', type=Path, default=Path('reception-results.json'))
    args = p.parse_args()
    if not args.shielded:
        p.error('This out-of-ISM-band test requires --shielded and RF containment.')
    f = m = None
    result = dict(target_nominal_hz=TARGET, receiver_lo_nominal_hz=RX_LO,
                  sample_rate_nominal_hz=FS, receiver_gain_index=30, baseline=[], active=[], after=[])
    try:
        f = connect(args.feather_port)
        m = connect(args.mini_port)
        until = time.monotonic()+3
        while time.monotonic() < until:
            f.read(8192)
            m.read(8192)
        f.timeout = m.timeout = 5
        result['identities'] = dict(feather=command(f,'INFO'), mini=command(m,'INFO'))
        result['versions'] = dict(feather=command(f,'VERSION?'), mini=command(m,'VERSION?'))
        assert command(f,'FREQ 2298') == 'OK'
        assert command(f,'GAIN MANUAL 30') == 'OK'
        for _ in range(12):
            result['baseline'].append(capture(f))
        result['transmissions'] = []
        for _ in range(5):
            m.timeout = 5
            m.write(b'TXTONE 200 13 16\n')
            tx_start = m.readline().decode().strip()
            if tx_start != f'TONESTART {TARGET} 12000 16':
                raise RuntimeError(tx_start)
            m.timeout = .001
            until = time.monotonic()+6
            incoming = bytearray()
            while time.monotonic() < until:
                incoming.extend(m.read(m.in_waiting or 1))
                if b'\n' in incoming:
                    break
                result['active'].append(capture(f))
            tx_end = incoming.decode().strip()
            result['transmissions'].append(dict(start=tx_start,end=tx_end))
            if not tx_end.startswith('TONEEND 200 0 '):
                raise RuntimeError(f'Transmitter did not finish cleanly: {tx_end}')
        for _ in range(12):
            result['after'].append(capture(f))
        comparisons = []
        for index, sign in enumerate((1, -1)):
            off = [r['candidates'][index]['peak_power'] for r in result['baseline']+result['after']]
            on = [r['candidates'][index]['peak_power'] for r in result['active']]
            if not on:
                raise RuntimeError('No active captures')
            threshold = max(off)*10  # exceed every off capture by at least 10 dB
            hits = [r['candidates'][index] for r in result['active']
                    if r['candidates'][index]['peak_power'] > threshold
                    and r['candidates'][index]['contrast_db'] >= 15]
            comparisons.append(dict(sign=sign, hits=len(hits), strongest=hits[:10],
                max_on_to_max_off_db=float(10*np.log10(max(on)/max(max(off),1e-12)))))
        result['comparisons'] = comparisons
        result['detected'] = any(r['hits'] >= 2 for r in comparisons)
        result['interpretation'] = ('Repeated transmitter-correlated energy near the nominal target; '
            'absolute RF accuracy remains uncalibrated.' if result['detected'] else
            'No confirmed detection. This does not prove the hardware cannot receive the target.')
        print(result['interpretation'])
    finally:
        if f:
            try:
                command(f,'GAIN HARDWARE')
                command(f,'RELEASE')
            except Exception:
                pass
            f.close()
        if m:
            m.close()
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    return 0 if result['detected'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
