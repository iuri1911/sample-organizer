# Sample Organizer

A deterministic, tested pipeline that turns a messy pile of audio sample packs —
including old sample-CD disc images — into a clean, type-based library.

```
 ___ _   _ ___ ___   ___ ___
|_ _| | | | _ \_ _| |_ _/ _ \    SAMPLE ORGANIZER
 | || |_| |   /| | _ | | (_) |   by IURI.IO
|___|\___/|_|_\___(_)___\___/
```

It runs locally (no cloud round-trips), is dependency-light, and ships with a
test suite so new format support never silently breaks existing behavior.

## Why

Sample libraries accumulate chaos: dozens of packs, mixed formats, leftover
disc images (`.iso`, `.bin/.cue`), archives, and OS junk. This tool ingests
whatever you drop in, extracts the audio, and files everything by sound type —
the way most producers actually browse.

## What it handles

- **Audio:** WAV (16/24/32-bit, float, Broadcast/Acidized), AIFF / Apple Loops,
  FLAC, MP3, OGG.
- **Disc images:** `.iso` (ISO9660), `.bin` data tracks, `.bin` audio CDs
  **with or without a `.cue`** (no cue → sliced on silence into one WAV per sample),
  and images nested inside dropped folders.
- **Archives:** `.zip` / `.tar` natively; `.rar` / `.7z` if the tool is installed.
- **Formats needing external tools** (NRG/MDF/AKAI): detected and used if a tool
  is present, otherwise filed to `_Docs` with a log note — never a silent break.
- **OS junk:** `.DS_Store`, `__MACOSX/`, `._*` resource forks are deleted.

## How it works

The pipeline runs in a strict order — nothing is archived until extraction and
processing are done:

1. **Extract** disc images / archives → loose folders.
2. **Name** — classify audio by filename keywords → categories.
3. **Audio** — classify the remainder by DSP (duration, brightness, noisiness,
   onset density, sustain, pitch) → categories.
4. **Sweep (last)** — move images/archives/leftover non-audio to `_Docs/`,
   delete junk, remove emptied folders.

Library layout: `Drums/`, `Percussion/`, `Bass/`, `Melodic/`, `Vocals/`, `FX/`
(each with subcategories), plus `_Unsorted/`, `_Docs & Disc Images/`,
`_Libraries/` (curated, never touched), `_logs/`.

## Install

Requires Python 3.8+. Core extraction/sorting uses only the standard library.
The audio step uses `librosa` (auto-installed by the app on first use, or):

```bash
pip install librosa soundfile
```

## Usage

**App (native window):**

```bash
python3 app.py
```

Pick your working folder and an optional mirror-backup folder, then "Organize all".
On macOS you can double-click `Sample Organizer.command`.

**CLI:**

```bash
python3 samplelib.py --root /path/to/library --phase all
# or a single phase: extract | name | audio | sweep | backup
python3 samplelib.py --root /path/to/library --phase backup --dest /path/to/backup
```

## Tests

```bash
python3 run_tests.py
```

Builds synthetic fixtures (WAV/AIFF/ISO9660/CDDA bin/zip/junk), runs the whole
pipeline in a temp folder, and asserts every file lands correctly. Offline and
fast. Audio-phase tests skip automatically if `numpy`/`librosa` aren't installed.

## Project structure

```
samplelib.py   engine (all phases + format handlers)
app.py         native dark-themed GUI (Tkinter)
run_tests.py   self-contained test suite
banner.txt     ASCII banner shown in the app
```

## Cross-platform notes

The engine and GUI are pure Python and run on macOS, Linux, and Windows.
The `.command` launchers are macOS convenience wrappers; elsewhere run
`python3 app.py` directly.

## Contributing

When adding support for a new format or rule, add a matching test in
`run_tests.py` and keep the suite green.

## License

MIT — see [LICENSE](LICENSE).
