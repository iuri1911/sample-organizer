#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_tests.py — Self-contained test suite for the sample-library pipeline.

Builds synthetic fixtures (WAV 16/24-bit, AIFF, hand-rolled ISO9660, raw CDDA
bin, zip, OS junk) in a temp folder, runs the whole pipeline, and asserts that
every file lands where it should. Offline, no touching the real library.

Run:  python3 run_tests.py
Audio-phase tests are skipped automatically if numpy/librosa are not installed.
"""
import os, sys, struct, wave, tempfile, shutil, zipfile, math, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import samplelib as S

try:
    import numpy, librosa  # noqa
    HAVE_AUDIO = True
except Exception:
    HAVE_AUDIO = False

# ---------------- tiny test runner ----------------
PASS = FAIL = 0
def check(cond, name):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  PASS  {name}")
    else:    FAIL += 1; print(f"  FAIL  {name}")

# ---------------- fixture builders ----------------
def write_wav(path, freq=440, dur=0.3, sr=44100, ch=2, sw=2, amp=0.4, silence=False):
    n = int(sr * dur); frames = bytearray()
    for i in range(n):
        v = 0.0 if silence else amp * math.sin(2 * math.pi * freq * i / sr)
        if sw == 2: s = int(v * 32767); samp = struct.pack('<h', s)
        elif sw == 3:
            s = int(v * (2**23 - 1)); samp = struct.pack('<i', s)[:3]
        elif sw == 1: samp = struct.pack('B', int((v + 1) * 127))
        else: s = int(v * (2**31 - 1)); samp = struct.pack('<i', s)
        frames += samp * ch
    w = wave.open(path, 'wb'); w.setnchannels(ch); w.setsampwidth(sw); w.setframerate(sr)
    w.writeframes(bytes(frames)); w.close()

def write_noise_wav(path, dur=0.2, sr=44100, ch=2):
    import random
    n = int(sr * dur); frames = bytearray()
    for i in range(n):
        s = int(random.uniform(-1, 1) * 20000); frames += struct.pack('<h', s) * ch
    w = wave.open(path, 'wb'); w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(bytes(frames)); w.close()

def write_aiff(path, freq=300, dur=0.3, sr=44100):
    import aifc
    n = int(sr * dur); frames = bytearray()
    for i in range(n):
        s = int(0.4 * 32767 * math.sin(2 * math.pi * freq * i / sr))
        frames += struct.pack('>h', s) * 2          # AIFF = big-endian
    w = aifc.open(path, 'wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(bytes(frames)); w.close()

def make_iso9660(files, out_path):
    """Minimal ISO9660 with a flat root of files. files: {NAME.EXT: bytes}."""
    LB = 2048
    b16 = lambda v: struct.pack('<H', v) + struct.pack('>H', v)
    b32 = lambda v: struct.pack('<I', v) + struct.pack('>I', v)
    def rec(ident, lba, length, is_dir):
        rl = 33 + len(ident)
        if rl % 2: rl += 1
        r = bytearray(rl)
        r[0] = rl; r[2:10] = b32(lba); r[10:18] = b32(length)
        r[25] = 0x02 if is_dir else 0; r[28:32] = b16(1)
        r[32] = len(ident); r[33:33 + len(ident)] = ident
        return bytes(r)
    lbas = {}; cur = 21
    for nm, data in files.items():
        lbas[nm] = cur; cur += (len(data) + LB - 1) // LB
    total = cur
    root = bytearray()
    root += rec(b'\x00', 20, LB, True); root += rec(b'\x01', 20, LB, True)
    for nm, data in files.items():
        root += rec(nm.encode('ascii') + b';1', lbas[nm], len(data), False)
    root = bytes(root).ljust(LB, b'\x00')
    pvd = bytearray(LB)
    pvd[0] = 1; pvd[1:6] = b'CD001'; pvd[6] = 1
    pvd[8:40] = b' ' * 32; pvd[40:72] = b'TEST_VOL'.ljust(32)
    pvd[80:88] = b32(total); pvd[120:124] = b16(1); pvd[124:128] = b16(1)
    pvd[128:132] = b16(LB); pvd[132:140] = b32(10)
    pvd[140:144] = struct.pack('<I', 18); pvd[148:152] = struct.pack('>I', 19)
    pvd[156:190] = rec(b'\x00', 20, LB, True)
    term = bytearray(LB); term[0] = 255; term[1:6] = b'CD001'; term[6] = 1
    pt = bytearray([1, 0]) + struct.pack('<I', 20) + struct.pack('<H', 1) + b'\x00\x00'
    with open(out_path, 'wb') as f:
        f.write(b'\x00' * 16 * LB); f.write(bytes(pvd)); f.write(bytes(term))
        f.write(bytes(pt).ljust(LB, b'\x00')); f.write(bytes(pt).ljust(LB, b'\x00'))
        f.write(root)
        for nm, data in files.items():
            f.write(data.ljust(((len(data) + LB - 1) // LB) * LB, b'\x00'))

def make_cdda_bin(path, n_segments=3):
    """Raw CDDA: tones separated by silence (>=0.5s)."""
    sr, ch = 44100, 2; out = bytearray()
    def tone(dur, freq, amp=10000):
        fr = bytearray()
        for i in range(int(sr * dur)):
            s = int(amp * math.sin(2 * math.pi * freq * i / sr)); fr += struct.pack('<h', s) * ch
        return fr
    def sil(dur): return bytes(int(sr * dur) * ch * 2)
    out += sil(0.2)
    for k in range(n_segments):
        out += tone(0.3, 200 + 100 * k); out += sil(0.6)
    # pad to whole 2352-byte sectors
    pad = (-len(out)) % 2352
    out += bytes(pad)
    open(path, 'wb').write(bytes(out))

def small_wav_bytes(name_hint="kick"):
    import io
    buf = io.BytesIO()
    w = wave.open(buf, 'wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(struct.pack('<h', 1000) * 2 * 4410); w.close()
    return buf.getvalue()

# ---------------- tests ----------------
def t_name_classifier():
    cases = {
        "Big Kick 01": ("Drums", "Kicks"), "Punchy Snare": ("Drums", "Snares"),
        "808 Bass C": ("Bass", ""), "Open Hat 3": ("Drums", "Hi-Hats"),
        "Female Adlib Yeah": ("Vocals", "Sung & Adlibs"), "Warm Pad": ("Melodic", "Synths & Pads"),
        "Conga Hit": ("Percussion", "Hits"), "Vinyl Scratch": ("FX", "Scratches"),
        "Amen Breakbeat": ("Drums", "Drum Loops & Breaks"),
    }
    for nm, exp in cases.items():
        got = S.classify_parts(["Pack", nm + ".wav"])
        check(got == exp, f"name: {nm} -> {got}")
    check(S.classify_parts(["Pack", "zzxx_cryptic.wav"]) == ("_Unsorted", "Pack"), "name: cryptic -> _Unsorted")

def t_audio_loader(tmp):
    for sw, tag in [(2, "16bit"), (3, "24bit")]:
        p = os.path.join(tmp, f"tone_{tag}.wav"); write_wav(p, sw=sw)
        y, sr = S.load_audio(p)
        check(y is not None and len(y) > 0, f"loader: WAV {tag} loads")
    pa = os.path.join(tmp, "tone.aiff"); write_aiff(pa)
    y, sr = S.load_audio(pa); check(y is not None and len(y) > 0, "loader: AIFF loads")
    pj = os.path.join(tmp, "junk.wav"); open(pj, 'wb').write(b'\x00\x05\x16\x07Mac OS X' * 8)
    y, sr = S.load_audio(pj); check(y is None, "loader: junk (non-RIFF) -> None")

def t_audio_classify(tmp):
    pk = os.path.join(tmp, "k.wav"); write_wav(pk, freq=55, dur=0.25)
    ft = S.audio_features(pk); check(ft is not None and ft['dur'] > 0, "audio: features computed")

def t_cdda_split(tmp):
    binp = os.path.join(tmp, "disc.bin"); make_cdda_bin(binp, 3)
    out = os.path.join(tmp, "disc_out")
    n = S._cdda_split(binp, out, "disc")
    check(n == 3, f"cdda split: {n} segments (expected 3)")

def t_iso_extract(tmp):
    iso = os.path.join(tmp, "test.iso")
    make_iso9660({"KICK01.WAV": small_wav_bytes(), "SNARE1.WAV": small_wav_bytes(),
                  "READ.TXT": b"hello"}, iso)
    out = os.path.join(tmp, "iso_out")
    with open(iso, 'rb') as f:
        n = S._extract_iso(S._IsoReader(f), out)
    got = sorted(os.listdir(out)) if os.path.isdir(out) else []
    check(n == 2 and "KICK01.WAV" in got and "SNARE1.WAV" in got and "READ.TXT" not in got,
          f"iso: extracted {n} wavs {got}")

def t_zip_extract(tmp):
    z = os.path.join(tmp, "pack.zip")
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr("Kick 9.wav", small_wav_bytes()); zf.writestr("notes.txt", "x")
    out = os.path.join(tmp, "zip_out")
    ok = S.extract_archive(z, out, print)
    check(ok and os.path.exists(os.path.join(out, "Kick 9.wav")), "zip: extracted")

def t_full_pipeline(tmp):
    root = os.path.join(tmp, "Lib"); os.makedirs(root)
    for c in ["Drums", "Percussion", "Bass", "Melodic", "Vocals", "FX", "_Unsorted", S.DOCS, "_Libraries", "_logs"]:
        os.makedirs(os.path.join(root, c), exist_ok=True)
    # protected library must stay untouched
    os.makedirs(os.path.join(root, "_Libraries", "MyLib"))
    write_wav(os.path.join(root, "_Libraries", "MyLib", "DontMove Kick.wav"))
    # a loose pack with named audio + non-audio + junk + __MACOSX
    pk = os.path.join(root, "NewPack", "drums"); os.makedirs(pk)
    write_wav(os.path.join(pk, "Big Kick.wav")); write_wav(os.path.join(pk, "Tight Snare.wav"))
    open(os.path.join(root, "NewPack", "manual.pdf"), 'wb').write(b"%PDF-1.4 x")
    open(os.path.join(root, "NewPack", ".DS_Store"), 'wb').write(b"junk")
    mac = os.path.join(root, "NewPack", "__MACOSX"); os.makedirs(mac)
    open(os.path.join(mac, "._Big Kick.wav"), 'wb').write(b"\x00\x05\x16\x07")
    # a loose zip with audio
    with zipfile.ZipFile(os.path.join(root, "Loops.zip"), 'w') as zf:
        zf.writestr("Hat Loop.wav", small_wav_bytes())
    # a CDDA bin without cue (inside a folder)
    discdir = os.path.join(root, "AudioCD"); os.makedirs(discdir)
    make_cdda_bin(os.path.join(discdir, "scd.bin"), 2)

    log = lambda *a: None
    S.run_all(root, log)

    def has(*parts): return os.path.exists(os.path.join(root, *parts))
    check(has("Drums", "Kicks", "Big Kick.wav"), "pipeline: kick -> Drums/Kicks")
    check(has("Drums", "Snares", "Tight Snare.wav"), "pipeline: snare -> Drums/Snares")
    check(has("_Libraries", "MyLib", "DontMove Kick.wav"), "pipeline: _Libraries untouched")
    check(has(S.DOCS, "NewPack", "manual.pdf"), "pipeline: pdf -> _Docs (last)")
    check(not has("NewPack"), "pipeline: source pack removed when empty")
    check(not os.path.isdir(os.path.join(root, "NewPack", "__MACOSX")), "pipeline: __MACOSX gone")
    # zip audio classified
    check(has("Drums", "Hi-Hats", "Hat Loop.wav") or has("Drums", "Drum Loops & Breaks", "Hat Loop.wav"),
          "pipeline: zip audio classified")
    # CDDA split produced audio that got organized somewhere (not left loose)
    check(not has("AudioCD") or not any(f.endswith('.bin') for _,_,fs in os.walk(os.path.join(root,"AudioCD")) for f in fs)
          or has(S.DOCS, "AudioCD", "scd.bin"), "pipeline: cdda bin handled")
    # no audio left loose in root (everything categorized)
    loose_audio = [f for name, base in S.gather_loose(root) for _, _, fs in os.walk(base) for f in fs if S.ext_of(f) in S.AUDIO_EXT]
    check(len(loose_audio) == 0, f"pipeline: no loose audio left ({len(loose_audio)})")

def main():
    print("=" * 56); print(" SAMPLE LIBRARY — TEST SUITE"); print("=" * 56)
    tmp = tempfile.mkdtemp(prefix="samptest_")
    try:
        print("\n[name classifier]"); t_name_classifier()
        print("\n[cdda split]"); t_cdda_split(tmp)
        print("\n[iso extract]"); t_iso_extract(tmp)
        print("\n[zip extract]"); t_zip_extract(tmp)
        if HAVE_AUDIO:
            print("\n[audio loader]"); t_audio_loader(tmp)
            print("\n[audio classify]"); t_audio_classify(tmp)
        else:
            print("\n[audio] SKIPPED (numpy/librosa not installed)")
        print("\n[full pipeline]"); t_full_pipeline(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 56)
    print(f" RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 56)
    sys.exit(1 if FAIL else 0)

if __name__ == "__main__":
    main()
