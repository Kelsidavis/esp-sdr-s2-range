import importlib.util,json,time,zlib
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('reception','outputs/golden-ratio-radio-test/test_reception.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
f=t.connect('/dev/cu.usbmodem2101');m=t.connect('/dev/cu.usbmodem1101')
n=4096;captures={};results={'runs':[],'target_nominal_hz':t.TARGET}
def shot():
    header=t.command(f,f'CAP16 {n} 6').split()
    assert header[0]=='DATA' and int(header[1])==n,header
    raw=t.exact(f,n*2);assert zlib.crc32(raw)==int(header[2],16)
    x=np.frombuffer(raw,dtype=np.int8).astype(float).reshape(-1,2)
    return x[:,0]+1j*x[:,1]
def characterize(x):
    x=x-x.mean();power=abs(np.fft.fft(x*np.hanning(n)))**2
    freq=np.fft.fftfreq(n,1/t.FS);floor=max(float(np.median(power[abs(freq)>100000])),1e-12)
    order=np.argsort(power)[-8:][::-1]
    return {'rms':float(np.sqrt(np.mean(abs(x)**2))),
            'clipped_fraction':float(np.mean((abs(x.real)>125)|(abs(x.imag)>125))),
            'peaks':[dict(offset_hz=float(freq[j]),power=float(power[j]),
                          contrast_db=float(10*np.log10(max(power[j],1e-12)/floor))) for j in order]}
try:
    until=time.monotonic()+3
    while time.monotonic()<until:f.read(8192);m.read(8192)
    f.timeout=m.timeout=5
    for lo,gain in ((2298,55),(2298,40),(2294,40)):
        print('RUN',lo,gain,flush=True)
        assert t.command(f,f'FREQ {lo}')=='OK'
        assert t.command(f,f'GAIN MANUAL {gain}')=='OK'
        run={'lo_mhz':lo,'gain':gain,'baseline':[],'active':[],'after':[]}
        ri=len(results['runs'])
        for j in range(8):
            x=shot();captures[f'r{ri}_off{j}']=x;run['baseline'].append(characterize(x))
        for batch in range(3):
            m.timeout=5;m.write(b'TXTONE 200 5 16\n');start=m.readline().decode().strip()
            assert start=='TONESTART 2298264784 12000 16',start
            m.timeout=.001;incoming=bytearray();until=time.monotonic()+4
            while time.monotonic()<until:
                incoming.extend(m.read(m.in_waiting or 1))
                if b'\n' in incoming:break
                x=shot();captures[f'r{ri}_on{len(run["active"])}']=x
                run['active'].append(characterize(x))
            end=incoming.decode().strip();assert end.startswith('TONEEND 200 0 '),end
            run.setdefault('tx',[]).append({'start':start,'end':end})
        for j in range(8):
            x=shot();captures[f'r{ri}_after{j}']=x;run['after'].append(characterize(x))
        results['runs'].append(run)
        Path('outputs/golden-ratio-radio-test/survey-results.json').write_text(json.dumps(results,indent=2)+'\n')
        np.savez_compressed('outputs/golden-ratio-radio-test/survey-captures.npz',**captures)
        best=max(run['active'],key=lambda x:x['peaks'][0]['contrast_db'])
        print('ACTIVE',len(run['active']),'BEST',best,flush=True)
finally:
    try:t.command(f,'GAIN HARDWARE');t.command(f,'FREQ 2298');t.command(f,'RELEASE')
    finally:f.close();m.close()
