# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-06-22

First public release.

### Added
- Single-engine pipeline (`samplelib.py`) with four ordered phases:
  extract → name → audio → sweep (archive last).
- Disc-image extraction: ISO9660 `.iso`, `.bin` data tracks, and audio CDs
  with or without a `.cue` (silence-slicing for cue-less CDDA).
- Archive extraction: `.zip`/`.tar` native; `.rar`/`.7z` via external tools.
- Name-based classification (keyword rules) and audio-based classification
  (DSP features) into a type-based library.
- Robust stdlib audio loader (WAV/AIFF, all common bit depths); junk and
  non-RIFF files quarantined.
- Native dark-themed GUI (`app.py`) with progress, live log, and folder pickers.
- Mirror backup to a second folder (e.g. iCloud) via rsync.
- Self-contained test suite (`run_tests.py`) covering every format and the
  full pipeline.
- Cross-platform: pure-Python fallback for silence detection (works on
  Python 3.13+ where `audioop` is removed).
