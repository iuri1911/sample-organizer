#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
samplelib.py — Single engine for the sample-library pipeline.

Phases, in this order (rule: nothing goes to _Docs until extract+process finish):
  1. EXTRACT  disc images and archives -> loose folders
  2. NAME     classify audio in loose folders -> categories (keyword rules)
  3. AUDIO    classify whatever is left in _Unsorted -> categories (DSP)
  4. SWEEP    move images/archives/non-audio -> _Docs ; delete junk ; remove empties
  (+ BACKUP   rsync mirror to iCloud)

No dependencies for extract/name/sweep (stdlib only). The AUDIO phase uses
librosa/numpy (installed on demand by the app). Formats needing an external
tool are detected; if the tool is missing they go to _Docs with a log note
(never a silent break).

CLI:
  python3 samplelib.py --root . --phase all
  python3 samplelib.py --root . --phase extract|name|audio|sweep
  python3 samplelib.py --root . --phase backup --dest <icloud>
  python3 samplelib.py --root . --pending      (count images/archives to extract)
"""
import os, re, sys, json, wave, shutil, subprocess, time
try: import aifc
except Exception: aifc = None
try: import audioop
except Exception: audioop = None

__version__ = "1.0.0"

def _rms16(frag):
    """RMS of a 16-bit PCM fragment. Uses audioop if present, else pure-Python
    (audioop was removed in Python 3.13)."""
    if audioop is not None:
        try: return audioop.rms(frag, 2)
        except Exception: pass
    import array
    a = array.array("h"); a.frombytes(frag[:len(frag) // 2 * 2])
    if not a: return 0
    return int((sum(x * x for x in a) / len(a)) ** 0.5)

# ===================== CONFIG =====================
DOCS = "_Docs & Disc Images"
CANON_TOP = {"Drums", "Percussion", "Bass", "Melodic", "Vocals", "FX",
             "_Unsorted", DOCS, "_Libraries", "_logs"}
AUDIO_EXT   = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg"}
IMAGE_EXT   = {".iso", ".bin", ".nrg", ".mdf", ".img"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
JUNK_NAMES  = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}
SKIP_EXT    = {".py", ".command", ".sh", ".md", ".json", ".log", ".pyc"}
SKIP_PREFIX = ("sononym.db",)
LOGMARK     = "\x01PROGRESS\t"
SECT, LB    = 2352, 2048

def ext_of(f): return os.path.splitext(f)[1].lower()

# ===================== NAME CLASSIFIER =====================
def drum_sub(s):
    if re.search(r'\b(roll|rolls|fill|fills)\b', s): return ("Drums", "Fills & Rolls")
    if re.search(r'(bass ?drum|bassdrum|\bbd\b|\bkick|\bkik|808 kick|monster kick|deep space kick)', s): return ("Drums", "Kicks")
    if re.search(r'(snare|\bsd\b|sidestick|side stick)', s):
        return ("Drums", "Claps") if 'clap' in s else ("Drums", "Snares")
    if 'clap' in s: return ("Drums", "Claps")
    if re.search(r'(hi ?hat|hihat|hi-hat|\bhat\b|hats)', s): return ("Drums", "Hi-Hats")
    if re.search(r'(ride|crash|cymbal|china|splash)', s): return ("Drums", "Cymbals & Rides")
    if re.search(r'\btom', s): return ("Drums", "Toms")
    return ("Drums", "Hits & Kits")

def classify_by_name(name):
    s = name
    if 'vocal fx' in s or 'vox fx' in s: return ("Vocals", "Vocal FX")
    if re.search(r'(speech|robot speech|talking|end sequence)', s): return ("Vocals", "Spoken")
    if re.search(r'(vocal|\bvox\b|sung|adlib|ad-lib|ad lib|hook|chorus|choir|beatbox|mouth percussion|jb-style|sex vocal|\bchant|rag vox)', s): return ("Vocals", "Sung & Adlibs")
    if 'scratch' in s: return ("FX", "Scratches")
    if re.search(r'(breakbeat|break intro|drum ?break)', s): return ("Drums", "Drum Loops & Breaks")
    if 'percussion break' in s or 'percussion loop' in s: return ("Percussion", "Loops")
    if re.search(r'\bbreak\b', s) and 'guitar' not in s: return ("Drums", "Drum Loops & Breaks")
    if re.search(r'(riser|sweep|uplifter|downlifter)', s): return ("FX", "Risers & Sweeps")
    if re.search(r'\bbass\b|basses|bassline|sub-?bass', s) and not re.search(r'bass ?drum|bassdrum|bass ?kick', s): return ("Bass", "")
    if re.search(r'(atmos|atmospher|ambient|drone)', s): return ("FX", "Atmospheres")
    if re.search(r'(sci-?fi|techno fx|industrial.*fx|\brobot|vectorizer|man machine|kraftwerk.*fx|electronik|bleep|blip|vocoder|star ?wars|star-?trek|science fiction)', s): return ("FX", "Sci-Fi & Tech FX")
    if re.search(r'(bass ?drum|bassdrum|\bbd\b|\bkick|\bkik|tr808|tr909|tr727|cr78|rhythm 77|eight-o-eight|nine-o-nine|seven-2-seven|r-eight|r8 |909|808 |drum m-c|synth drum|analogue.*drum)', s): return drum_sub(s)
    if re.search(r'(snare|\bsd\b|hi ?hat|hihat|\bhat\b|hats|\bride\b|crash|cymbal|\btom\b|toms|\bclap|rimshot|\bfill|\broll)', s): return drum_sub(s)
    if re.search(r'(flute|woodwind|\bsax\b|clarinet|oboe)', s): return ("Melodic", "Brass & Winds")
    if re.search(r'(percussion|\bperc\b|conga|bongo|shaker|tambourin|\btamb\b|cabasa|agogo|surdo|cuica|timbal|\bblock|rattle|\bgong|\bbong|clave|guiro|maraca|tabla|cowbell|triangle)', s):
        return ("Percussion", "Loops" if ('loop' in s or 'groove' in s) else "Hits")
    if re.search(r'(stab|\bchord|hits & chord)', s): return ("Melodic", "Stabs & Chords")
    if re.search(r'(\bhorn|brass|trumpet|trombone)', s): return ("Melodic", "Brass & Winds")
    if re.search(r'(guitar|strum|\briff\b)', s): return ("Melodic", "Guitars")
    if re.search(r'(string|violin|cello|orchestral)', s): return ("Melodic", "Strings")
    if re.search(r'(piano|organ|keyboard|\bkeys\b|rhodes|wurli|\bbell)', s): return ("Melodic", "Keys")
    if re.search(r'(synth|\bpad\b|pads|pluck|\blead\b|\barp|sh ?101|ob-x|moog)', s): return ("Melodic", "Synths & Pads")
    if re.search(r'(vocoder loop|melod|groove)', s): return ("Melodic", "Melodic Loops")
    if re.search(r'(animal|whale|cuckoo|siren|zapper|\bwind|tremor|crackle|buzz|\bfx\b|sfx|power fx|electric fx|percussive fx|mother earth|record fx|shatter|concussion|comedy|screamer|psycho|effect)', s): return ("FX", "Misc FX")
    return None

FOLDER_MAP = [
    (r'kick', ("Drums", "Kicks")), (r'snare', ("Drums", "Snares")),
    (r'\bclap', ("Drums", "Claps")), (r'hi.?hat|\bhat', ("Drums", "Hi-Hats")),
    (r'cymbal|\bride|crash', ("Drums", "Cymbals & Rides")), (r'\btom', ("Drums", "Toms")),
    (r'fill|roll', ("Drums", "Fills & Rolls")), (r'break|drum.?loop', ("Drums", "Drum Loops & Breaks")),
    (r'conga|bongo|shaker|tabla|agogo|tamb|cowbell|\bblock|triangle|\bbell|perc', ("Percussion", "Hits")),
    (r'\bbass', ("Bass", "")), (r'key|piano|organ|rhodes', ("Melodic", "Keys")),
    (r'guitar', ("Melodic", "Guitars")), (r'brass|\bhorn|\bsax|wind|flute', ("Melodic", "Brass & Winds")),
    (r'string', ("Melodic", "Strings")), (r'stab|chord', ("Melodic", "Stabs & Chords")),
    (r'synth|\bpad|\blead|pluck', ("Melodic", "Synths & Pads")),
    (r'vocal.?fx|vox.?fx', ("Vocals", "Vocal FX")), (r'speech|spoken', ("Vocals", "Spoken")),
    (r'sung|adlib|ad.?lib|hook|sing', ("Vocals", "Sung & Adlibs")),
    (r'crowd|chant', ("Vocals", "Crowds & Chants")), (r'vocal|\bvox', ("Vocals", "Sung & Adlibs")),
    (r'scratch', ("FX", "Scratches")), (r'atmos|ambient', ("FX", "Atmospheres")),
    (r'sci.?fi|tech.?fx', ("FX", "Sci-Fi & Tech FX")), (r'riser|sweep', ("FX", "Risers & Sweeps")),
    (r'\bfx\b|sfx|effect', ("FX", "Misc FX")), (r'drum', ("Drums", "Hits & Kits")),
    (r'percussion', ("Percussion", "Hits")), (r'\bloop', ("Melodic", "Melodic Loops")),
]

def classify_by_folder(parts):
    for seg in reversed(parts[:-1]):
        low = seg.lower()
        for pat, cat in FOLDER_MAP:
            if re.search(pat, low):
                if cat[0] == "Percussion" and 'loop' in low: return ("Percussion", "Loops")
                return cat
    return None

def classify_parts(parts):
    name = os.path.splitext(parts[-1])[0].lower()
    return classify_by_name(name) or classify_by_folder(parts) or ("_Unsorted", parts[0])

# ===================== AUDIO (DSP) =====================
def load_audio(path, target_sr=22050):
    """Load WAV/AIFF via stdlib; FLAC/MP3/OGG via librosa if available.
    Returns (mono_float32, sr) or (None, None) if invalid/junk."""
    import numpy as np
    e = ext_of(path)
    try:
        if e == ".wav":
            with open(path, "rb") as fh:
                if fh.read(4) != b"RIFF": return None, None
            w = wave.open(path, "rb"); ch, sw, sr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(nf); w.close(); endian = "<"
        elif e in (".aif", ".aiff"):
            if aifc is None: return _load_librosa(path, target_sr)
            w = aifc.open(path, "rb"); ch, sw, sr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(nf); w.close(); endian = ">"
        else:
            return _load_librosa(path, target_sr)
        if not raw: return None, None
        if sw == 2:   a = np.frombuffer(raw, dtype=endian + "i2").astype(np.float32) / 32768.0
        elif sw == 1: a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
        elif sw == 4: a = np.frombuffer(raw, dtype=endian + "i4").astype(np.float32) / 2147483648.0
        elif sw == 3:
            b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            if endian == "<": a = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)).astype(np.float32)
            else:            a = (b[:, 2] | (b[:, 1] << 8) | (b[:, 0] << 16)).astype(np.float32)
            a[a >= 2**23] -= 2**24; a /= float(2**23)
        else: return None, None
        if ch > 1: a = a.reshape(-1, ch).mean(axis=1)
        if sr != target_sr and a.size:
            import librosa; a = librosa.resample(a, orig_sr=sr, target_sr=target_sr); sr = target_sr
        return a, sr
    except Exception:
        return _load_librosa(path, target_sr)

def _load_librosa(path, sr):
    try:
        import librosa
        y, s = librosa.load(path, sr=sr, mono=True)
        return (y, s) if y.size else (None, None)
    except Exception:
        return None, None

def audio_features(path):
    import numpy as np, librosa
    y, sr = load_audio(path, 22050)
    if y is None or y.size == 0: return None
    dur = float(len(y) / sr)
    if dur < 0.05: return None
    rms = librosa.feature.rms(y=y)[0]
    cent = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))
    flat = float(np.mean(librosa.feature.spectral_flatness(y=y)))
    n_onsets = len(librosa.onset.onset_detect(y=y, sr=sr, units='time'))
    peak = float(np.max(rms)) + 1e-9
    tail = float(np.mean(rms[int(len(rms) * 0.6):])) if len(rms) > 4 else 0.0
    sustain = tail / peak
    try:
        f0 = librosa.yin(y, fmin=40, fmax=2000, sr=sr); pitch = float(np.median(f0)) if np.isfinite(f0).any() else 0.0
    except Exception: pitch = 0.0
    return dict(dur=dur, cent=cent, zcr=zcr, flat=flat, n_onsets=n_onsets, sustain=sustain, pitch=pitch)

def audio_classify(ft):
    d, cent, zcr, flat, n, sus, pitch = ft['dur'], ft['cent'], ft['zcr'], ft['flat'], ft['n_onsets'], ft['sustain'], ft['pitch']
    if d >= 1.8 and n >= 4:
        return ("Drums", "Drum Loops & Breaks") if flat > 0.05 else ("Melodic", "Melodic Loops")
    if d >= 2.5 and sus > 0.25:
        return ("FX", "Atmospheres") if flat > 0.04 else ("Melodic", "Synths & Pads")
    percussive = (d < 1.6 and sus < 0.25); noisy = (flat > 0.06 or zcr > 0.12)
    if percussive and noisy:
        if cent < 700:  return ("Drums", "Kicks")
        if cent < 2500: return ("Drums", "Snares")
        if cent < 6000: return ("Drums", "Hi-Hats")
        return ("Drums", "Cymbals & Rides")
    if pitch > 0 and flat < 0.05:
        return ("Bass", "") if (pitch < 150 and d < 2.5) else ("Melodic", "Synths & Pads")
    if percussive:
        return ("Drums", "Kicks") if cent < 500 else ("Percussion", "Hits")
    return ("FX", "Misc FX")

# ===================== ISO / CUE / CDDA =====================
class _IsoReader:
    def __init__(self, f): self.f = f
    def read_lb(self, lba, length): self.f.seek(lba * LB); return self.f.read(length)

class _BinMode1Reader:
    def __init__(self, f): self.f = f
    def read_lb(self, lba, length):
        out = bytearray(); blk = 0
        while len(out) < length:
            self.f.seek((lba + blk) * SECT + 16); out += self.f.read(LB); blk += 1
        return bytes(out[:length])

def _extract_iso(reader, outdir):
    le = lambda b: int.from_bytes(b, 'little')
    pvd = reader.read_lb(16, LB)
    if pvd[1:6] != b'CD001': return 0
    n = [0]
    def walk(lba, length, rel, depth=0):
        if depth > 14: return
        data = reader.read_lb(lba, length); i = 0
        while i < len(data):
            rlen = data[i]
            if rlen == 0:
                nxt = ((i // LB) + 1) * LB
                if nxt <= i: break
                i = nxt; continue
            rec = data[i:i + rlen]
            if len(rec) < 33: break
            flags, lenfi = rec[25], rec[32]; fid = rec[33:33 + lenfi]
            clba, clen = le(rec[2:6]), le(rec[10:14])
            if not (lenfi == 1 and fid in (b'\x00', b'\x01')):
                nm = fid.decode('latin-1').split(';')[0]
                if flags & 0x02:
                    if clba != lba: walk(clba, clen, rel + '/' + nm, depth + 1)
                elif ext_of(nm) in AUDIO_EXT:
                    od = outdir + rel; os.makedirs(od, exist_ok=True)
                    with open(os.path.join(od, nm), 'wb') as fo: fo.write(reader.read_lb(clba, clen))
                    n[0] += 1
            i += rlen
    root = pvd[156:156 + 34]; walk(le(root[2:6]), le(root[10:14]), '')
    return n[0]

def _probe_iso(path):
    """Return 'iso2048' | 'bin2352' | None (where CD001 sits)."""
    try:
        with open(path, 'rb') as f:
            f.seek(16 * LB)
            if f.read(2048)[1:6] == b'CD001': return 'iso2048'
            f.seek(16 * SECT + 16)
            if f.read(2048)[1:6] == b'CD001': return 'bin2352'
    except OSError: pass
    return None

def _msf(m, s, f): return (m * 60 + s) * 75 + f

def _parse_cue(cue):
    tracks, num, typ = [], None, None
    try: lines = open(cue, encoding="latin-1", errors="replace")
    except OSError: return tracks
    for line in lines:
        m = re.match(r'\s*TRACK\s+(\d+)\s+(\S+)', line)
        if m: num, typ = int(m.group(1)), m.group(2)
        mi = re.match(r'\s*INDEX\s+01\s+(\d+):(\d+):(\d+)', line)
        if mi and num is not None: tracks.append((num, typ, _msf(*map(int, mi.groups())))); num = None
    return tracks

def _cdda_from_cue(binpath, tracks, outdir, label):
    total = os.path.getsize(binpath) // SECT; n = 0; os.makedirs(outdir, exist_ok=True)
    with open(binpath, 'rb') as f:
        for idx, (num, typ, start) in enumerate(tracks):
            end = tracks[idx + 1][2] if idx + 1 < len(tracks) else total
            if typ != "AUDIO": continue
            f.seek(start * SECT); raw = f.read((end - start) * SECT)
            _write_wav(os.path.join(outdir, f"{label}_track{num:02d}.wav"), raw); n += 1
    return n

def _cdda_split(binpath, outdir, label, thresh=200, gap_windows=8, min_dur=0.10):
    """Slice raw CDDA (16-bit/44.1k/stereo) on silence. Uses audioop (stdlib)."""
    SR, ch, w = 44100, 2, 2; win = int(SR * 0.05) * ch * w
    segs = []; start = None; gap = 0; pos = 0
    with open(binpath, 'rb') as f:
        while True:
            c = f.read(win)
            if not c: break
            silent = _rms16(c) < thresh
            if not silent:
                if start is None: start = pos
                gap = 0
            elif start is not None:
                gap += 1
                if gap >= gap_windows: segs.append((start, pos - gap * win)); start = None; gap = 0
            pos += len(c)
    if start is not None: segs.append((start, pos))
    minb = int(SR * min_dur) * ch * w
    keep = [(s, e) for s, e in segs if e - s >= minb]
    if len(keep) <= 1: return _cdda_whole(binpath, outdir, label)
    os.makedirs(outdir, exist_ok=True); n = 0
    with open(binpath, 'rb') as f:
        for i, (s, e) in enumerate(keep, 1):
            f.seek(s); _write_wav(os.path.join(outdir, f"{label}_{i:03d}.wav"), f.read(e - s)); n += 1
    return n

def _cdda_whole(binpath, outdir, label):
    os.makedirs(outdir, exist_ok=True)
    with open(binpath, 'rb') as f: raw = f.read()
    _write_wav(os.path.join(outdir, f"{label}.wav"), raw); return 1

def _write_wav(path, raw, sr=44100, ch=2, width=2):
    w = wave.open(path, 'wb'); w.setnchannels(ch); w.setsampwidth(width); w.setframerate(sr); w.writeframes(raw); w.close()

# ===================== ARCHIVES =====================
def _have(tool): return shutil.which(tool) is not None

def extract_archive(path, outdir, log):
    e = ext_of(path); os.makedirs(outdir, exist_ok=True)
    try:
        if e == ".zip":
            import zipfile
            with zipfile.ZipFile(path) as z: z.extractall(outdir)
            return True
        if e in (".tar", ".gz", ".tgz"):
            import tarfile
            with tarfile.open(path) as t: t.extractall(outdir)
            return True
        if e == ".7z":
            if _have("7z"): subprocess.run(["7z", "x", "-y", "-o" + outdir, path], capture_output=True); return True
            if _have("7za"): subprocess.run(["7za", "x", "-y", "-o" + outdir, path], capture_output=True); return True
        if e == ".rar":
            if _have("unar"): subprocess.run(["unar", "-f", "-o", outdir, path], capture_output=True); return True
            if _have("unrar"): subprocess.run(["unrar", "x", "-y", path, outdir], capture_output=True); return True
    except Exception as ex:
        log(f"     error unpacking {os.path.basename(path)}: {ex}")
    log(f"     ! no tool for {e} ({os.path.basename(path)}) — will go to _Docs."); return False

# ===================== IDEMPOTENCY =====================
def _logpath(root): return os.path.join(root, DOCS, "_extracted.log")
def _done(root):
    try: return set(l.strip() for l in open(_logpath(root), encoding="utf-8") if l.strip())
    except OSError: return set()
def _mark(root, label):
    os.makedirs(os.path.join(root, DOCS), exist_ok=True)
    with open(_logpath(root), "a", encoding="utf-8") as f: f.write(label + "\n")

# ===================== PHASE 1: EXTRACT =====================
def find_extractables(root):
    out = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isfile(p) and ext_of(name) in (IMAGE_EXT | ARCHIVE_EXT): out.append((p, "root"))
        elif os.path.isdir(p) and name not in CANON_TOP and name != DOCS:
            for dp, _, fs in os.walk(p):
                for f in sorted(fs):
                    if ext_of(f) in (IMAGE_EXT | ARCHIVE_EXT): out.append((os.path.join(dp, f), "root"))
    docs = os.path.join(root, DOCS)
    if os.path.isdir(docs):
        for dp, _, fs in os.walk(docs):
            for f in sorted(fs):
                if ext_of(f) in (IMAGE_EXT | ARCHIVE_EXT): out.append((os.path.join(dp, f), "_Docs"))
    return out

def pending(root):
    done = _done(root)
    return [p for p, _ in find_extractables(root)
            if os.path.splitext(os.path.basename(p))[0] not in done]

def _extract_one(path, root, log):
    label = os.path.splitext(os.path.basename(path))[0]
    outdir = os.path.join(root, label); e = ext_of(path)
    try:
        if e in ARCHIVE_EXT:
            ok = extract_archive(path, outdir, log)
            return (sum(1 for _, _, fs in os.walk(outdir) for _ in fs) if ok else 0)
        if e == ".iso":
            kind = _probe_iso(path)
            with open(path, 'rb') as f:
                if kind == 'bin2352': return _extract_iso(_BinMode1Reader(f), outdir)
                return _extract_iso(_IsoReader(f), outdir)
        if e == ".bin":
            kind = _probe_iso(path)
            if kind == 'bin2352':
                with open(path, 'rb') as f: return _extract_iso(_BinMode1Reader(f), outdir)
            if kind == 'iso2048':
                with open(path, 'rb') as f: return _extract_iso(_IsoReader(f), outdir)
            cue = os.path.splitext(path)[0] + '.cue'; tracks = _parse_cue(cue)
            if tracks and any(t[1] == "AUDIO" for t in tracks): return _cdda_from_cue(path, tracks, outdir, label)
            return _cdda_split(path, outdir, label)        # CDDA without cue
        if e in (".nrg", ".mdf", ".img"):
            log(f"     ! {e} needs an external tool (bchunk/7z) — not native; going to _Docs.")
            return 0
    except Exception as ex:
        log(f"  x {label}: ERROR -> {ex}"); return 0
    return 0

def phase_extract(root, log, progress=None):
    items = find_extractables(root); done = _done(root)
    pend = [(p, o) for p, o in items if os.path.splitext(os.path.basename(p))[0] not in done]
    log(f">> EXTRACT — {len(items)} found, {len(pend)} pending")
    total = 0
    for i, (p, origin) in enumerate(pend, 1):
        label = os.path.splitext(os.path.basename(p))[0]
        n = _extract_one(p, root, log)
        if n > 0:
            log(f"  ok {label}: {n} file(s)  [{origin}]"); _mark(root, label); total += n
        else:
            log(f"  ! {label}: 0 extracted (unsupported native format or empty).")
        if progress: progress(i, len(pend))
    log(f"   EXTRACT done: {total} files.")
    return total

# ===================== PHASE 2: NAME =====================
def gather_loose(root):
    src = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full) and name not in CANON_TOP: src.append((name, full))
    return src

def _safe(dp):
    if not os.path.exists(dp): return dp
    b, e = os.path.splitext(dp); i = 2
    while os.path.exists(f"{b} ({i}){e}"): i += 1
    return f"{b} ({i}){e}"

def phase_name(root, log):
    moved = 0
    for label, base in gather_loose(root):
        for dp, dirs, fs in os.walk(base):
            if "__MACOSX" in dp.split(os.sep): continue
            for f in fs:
                if ext_of(f) not in AUDIO_EXT: continue
                ap = os.path.join(dp, f); rel = os.path.relpath(ap, base)
                parts = [label] + rel.split(os.sep)
                top, sub = classify_parts(parts)
                dest = os.path.join(root, top, sub, f) if sub else os.path.join(root, top, f)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(ap, _safe(dest)); moved += 1
    log(f">> NAME — {moved} audio files classified by name.")
    return moved

# ===================== PHASE 3: AUDIO =====================
def phase_audio(root, log, progress=None):
    base = os.path.join(root, "_Unsorted")
    if not os.path.isdir(base): log(">> AUDIO — _Unsorted empty."); return 0
    paths = []
    for dp, dirs, fs in os.walk(base):
        if "_corrupt" in dp: continue
        dirs[:] = [d for d in dirs if d != "_corrupt"]
        for f in sorted(fs):
            if ext_of(f) in AUDIO_EXT: paths.append(os.path.join(dp, f))
    log(f">> AUDIO — analyzing {len(paths)} file(s)")
    moved = 0
    for i, p in enumerate(paths, 1):
        try:
            ft = audio_features(p)
            cat = ("_Unsorted", "_corrupt") if ft is None else audio_classify(ft)
        except Exception:
            cat = ("_Unsorted", "_corrupt")
        dest = os.path.join(root, cat[0], cat[1], os.path.basename(p)) if cat[1] else os.path.join(root, cat[0], os.path.basename(p))
        os.makedirs(os.path.dirname(dest), exist_ok=True); shutil.move(p, _safe(dest)); moved += 1
        if progress and (i % 10 == 0 or i == len(paths)): progress(i, len(paths))
    log(f"   AUDIO done: {moved} moved.")
    return moved

# ===================== PHASE 4: SWEEP (archive last) =====================
def phase_sweep(root, log):
    docs = os.path.join(root, DOCS); moved = deleted = 0
    for label, base in gather_loose(root):
        for dp, dirs, fs in os.walk(base):
            if "__MACOSX" in dp.split(os.sep):
                for f in fs:
                    try: os.remove(os.path.join(dp, f)); deleted += 1
                    except OSError: pass
                continue
            for f in fs:
                ap = os.path.join(dp, f); e = ext_of(f)
                if f in JUNK_NAMES or f.startswith("._"):
                    try: os.remove(ap); deleted += 1
                    except OSError: pass
                elif e in AUDIO_EXT or e in SKIP_EXT or f.startswith(SKIP_PREFIX):
                    pass
                else:
                    rel = os.path.relpath(ap, base); dest = os.path.join(docs, label, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True); shutil.move(ap, _safe(dest)); moved += 1
    for label, base in gather_loose(root):
        for dp, dirs, fs in os.walk(base, topdown=False):
            for f in fs:
                if f in JUNK_NAMES:
                    try: os.remove(os.path.join(dp, f))
                    except OSError: pass
            try:
                if not os.listdir(dp): os.rmdir(dp)
            except OSError: pass
    log(f">> SWEEP — {moved} to _Docs, {deleted} junk deleted, empty folders removed.")
    return moved, deleted

# ===================== BACKUP =====================
def phase_backup(root, dest, log):
    if not dest: log("Backup: destination folder not set."); return 1
    if not _have("rsync"): log("Backup: rsync not found."); return 1
    cmd = ["rsync", "-a", "--delete", "--info=progress2", root.rstrip("/") + "/", dest.rstrip("/") + "/"]
    log(">> BACKUP (mirror) -> " + dest)
    return subprocess.call(cmd)

# ===================== ORCHESTRATOR =====================
def run_all(root, log=print, progress=None):
    phase_extract(root, log, progress)
    phase_name(root, log)
    phase_audio(root, log, progress)
    phase_sweep(root, log)

# ===================== CLI =====================
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--phase", default="all", choices=["all", "extract", "name", "audio", "sweep", "backup"])
    ap.add_argument("--dest", default="")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--progress", action="store_true")
    a = ap.parse_args(); root = os.path.abspath(a.root)
    if a.pending: print(len(pending(root))); return
    prog = (lambda i, n: print(f"{LOGMARK}{i}\t{n}", flush=True)) if a.progress else None
    if a.phase == "all": run_all(root, print, prog)
    elif a.phase == "extract": phase_extract(root, print, prog)
    elif a.phase == "name": phase_name(root, print)
    elif a.phase == "audio": phase_audio(root, print, prog)
    elif a.phase == "sweep": phase_sweep(root, print)
    elif a.phase == "backup": phase_backup(root, a.dest, print)

if __name__ == "__main__":
    main()
