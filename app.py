#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Native dark-themed window (Tkinter) driving the sample pipeline.

Runs on the LOCAL working folder and can mirror-backup to iCloud.
Calls the samplelib engine directly (extract -> name -> audio -> sweep).
Everything is logged to _logs/app_<datetime>.log.
"""
import os, sys, json, threading, queue, subprocess, time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
import samplelib as S

CONFIG = os.path.join(APP_DIR, "_app_config.json")
PY = sys.executable or "python3"
CATS = ["Drums", "Percussion", "Bass", "Melodic", "Vocals", "FX", "_Unsorted", "_Libraries"]

def load_cfg():
    try:
        with open(CONFIG, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_cfg(c):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f: json.dump(c, f, indent=2)
    except Exception: pass

def guess_icloud():
    p = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Samples")
    return p if os.path.isdir(p) else ""

def count_audio(folder):
    n = 0
    for _, _, fs in os.walk(folder):
        for f in fs:
            if S.ext_of(f) in S.AUDIO_EXT: n += 1
    return n

def main():
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext

    cfg = load_cfg()
    root = tk.Tk()
    root.title("Sample Organizer")
    root.geometry("700x900"); root.minsize(640, 820)

    DARK = dict(bg="#1c1c1e", surface="#2c2c2e", surface2="#3a3a3c",
                text="#e8e8e8", muted="#9aa0a6", accent="#3b82f6", border="#3a3a3c")
    MUTED = DARK["muted"]
    root.configure(bg=DARK["bg"])
    style = ttk.Style()
    try: style.theme_use("clam")
    except Exception: pass
    style.configure(".", background=DARK["bg"], foreground=DARK["text"], fieldbackground=DARK["surface"],
                    bordercolor=DARK["border"], lightcolor=DARK["surface"], darkcolor=DARK["surface"],
                    troughcolor=DARK["surface"], focuscolor=DARK["bg"])
    style.configure("TFrame", background=DARK["bg"])
    style.configure("TLabel", background=DARK["bg"], foreground=DARK["text"])
    style.configure("TLabelframe", background=DARK["bg"], bordercolor=DARK["border"])
    style.configure("TLabelframe.Label", background=DARK["bg"], foreground=DARK["muted"])
    style.configure("TCheckbutton", background=DARK["bg"], foreground=DARK["text"])
    style.map("TCheckbutton", background=[("active", DARK["bg"])],
              indicatorcolor=[("selected", DARK["accent"]), ("!selected", DARK["surface2"])])
    style.configure("TButton", background=DARK["surface"], foreground=DARK["text"],
                    bordercolor=DARK["border"], padding=7, relief="flat")
    style.map("TButton", background=[("active", DARK["surface2"]), ("disabled", DARK["bg"])],
              foreground=[("disabled", DARK["muted"])])
    style.configure("Horizontal.TProgressbar", troughcolor=DARK["surface"], background=DARK["accent"],
                    bordercolor=DARK["border"], lightcolor=DARK["accent"], darkcolor=DARK["accent"])

    state = {"working": cfg.get("working", APP_DIR), "backup": cfg.get("backup", guess_icloud()),
             "running": False, "logfile": None}
    q = queue.Queue()
    frm = ttk.Frame(root); frm.pack(fill="both", expand=True)

    try:
        with open(os.path.join(APP_DIR, "banner.txt"), encoding="utf-8") as bf: _banner = bf.read().rstrip("\n")
    except Exception:
        _banner = "IURI.IO  SAMPLE ORGANIZER"
    tk.Label(frm, text=_banner, font=("Menlo", 9), justify="left", anchor="w",
             bg=DARK["bg"], fg=DARK["accent"]).pack(anchor="w", padx=14, pady=(12, 6))

    work_var = tk.StringVar(value=state["working"]); back_var = tk.StringVar(value=state["backup"])
    def pick(var, key):
        d = filedialog.askdirectory(initialdir=var.get() or os.path.expanduser("~"))
        if d:
            var.set(d); state[key] = d
            save_cfg({"working": work_var.get(), "backup": back_var.get()}); refresh()
    def folder_row(label, var, key):
        row = ttk.Frame(frm); row.pack(fill="x", padx=14, pady=6)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Label(row, textvariable=var, foreground=MUTED, anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Choose", command=lambda: pick(var, key)).pack(side="right")
    folder_row("Working (local):", work_var, "working")
    folder_row("Backup (iCloud):", back_var, "backup")

    counts_frm = ttk.LabelFrame(frm, text="Library"); counts_frm.pack(fill="x", padx=14, pady=8)
    count_vars = {}; grid = ttk.Frame(counts_frm); grid.pack(fill="x", padx=8, pady=8)
    for i, c in enumerate(CATS):
        cell = ttk.Frame(grid); cell.grid(row=i // 4, column=i % 4, sticky="w", padx=10, pady=4)
        ttk.Label(cell, text=c, foreground=MUTED).pack(anchor="w")
        v = tk.StringVar(value="—"); count_vars[c] = v
        ttk.Label(cell, textvariable=v, font=("Helvetica", 13, "bold")).pack(anchor="w")

    steps_frm = ttk.LabelFrame(frm, text="Steps"); steps_frm.pack(fill="x", padx=14, pady=4)
    v0 = tk.BooleanVar(value=True); v1 = tk.BooleanVar(value=True); v2 = tk.BooleanVar(value=True)
    ttk.Checkbutton(steps_frm, text="0 · Extract disc images / archives", variable=v0).pack(anchor="w", padx=10, pady=2)
    ttk.Checkbutton(steps_frm, text="1 · Classify by name", variable=v1).pack(anchor="w", padx=10, pady=2)
    ttk.Checkbutton(steps_frm, text="2 · Classify by audio (_Unsorted)", variable=v2).pack(anchor="w", padx=10, pady=2)
    ttk.Label(steps_frm, text="Archiving to _Docs always runs last.", foreground=MUTED).pack(anchor="w", padx=10, pady=(0, 8))

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(frm, textvariable=status_var, foreground=MUTED).pack(anchor="w", padx=14)
    bar = ttk.Progressbar(frm, mode="determinate", maximum=100); bar.pack(fill="x", padx=14, pady=(2, 6))

    log = scrolledtext.ScrolledText(frm, height=9, font=("Menlo", 11), state="disabled", wrap="none",
                                    bg=DARK["surface"], fg=DARK["text"], insertbackground=DARK["text"],
                                    selectbackground=DARK["accent"], relief="flat", borderwidth=0, highlightthickness=0)
    log.pack(fill="both", expand=True, padx=14, pady=(0, 6))

    btns = ttk.Frame(frm); btns.pack(fill="x", padx=14, pady=(0, 12))
    btn_run = ttk.Button(btns, text="▶  Organize all"); btn_run.pack(side="left")
    btn_bkp = ttk.Button(btns, text="☁  Backup to iCloud (mirror)"); btn_bkp.pack(side="left", padx=8)

    def logline(s):
        log.configure(state="normal"); log.insert("end", s + "\n"); log.see("end"); log.configure(state="disabled")
        if state["logfile"]:
            try: state["logfile"].write(s + "\n"); state["logfile"].flush()
            except Exception: pass
    def refresh():
        w = work_var.get()
        for c in CATS:
            count_vars[c].set(str(count_audio(os.path.join(w, c))) if os.path.isdir(os.path.join(w, c)) else "0")
    def set_running(on):
        state["running"] = on
        btn_run.configure(state="disabled" if on else "normal")
        btn_bkp.configure(state="disabled" if on else "normal")
    def drain():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log": logline(val)
                elif kind == "status": status_var.set(val)
                elif kind == "progress": bar.configure(mode="determinate"); bar["value"] = val
                elif kind == "pulse_on": bar.configure(mode="indeterminate"); bar.start(12)
                elif kind == "pulse_off": bar.stop(); bar.configure(mode="determinate"); bar["value"] = 0
                elif kind == "refresh": refresh()
                elif kind == "done": set_running(False)
        except queue.Empty: pass
        root.after(120, drain)

    def open_log():
        logdir = os.path.join(work_var.get(), "_logs"); os.makedirs(logdir, exist_ok=True)
        ts = time.strftime("%Y-%m-%d_%H%M%S")
        state["logfile"] = open(os.path.join(logdir, f"app_{ts}.log"), "w", encoding="utf-8"); return ts

    def emit(msg): q.put(("log", msg))
    def prog(i, n): q.put(("progress", int(i * 100 / max(1, n)))); q.put(("status", f"{i}/{n}"))

    def ensure_librosa():
        if subprocess.run([PY, "-c", "import librosa"], capture_output=True).returncode == 0: return True
        emit("  installing librosa (1-2 min)..."); q.put(("pulse_on", 0))
        for extra in ([], ["--user"], ["--break-system-packages"]):
            subprocess.run([PY, "-m", "pip", "install", "-q", *extra, "librosa", "soundfile"])
            if subprocess.run([PY, "-c", "import librosa"], capture_output=True).returncode == 0:
                q.put(("pulse_off", 0)); return True
        q.put(("pulse_off", 0)); return False

    def worker_pipeline():
        ts = open_log(); w = work_var.get()
        emit(f"=== run {ts} ===")
        try:
            if v0.get():
                q.put(("status", "Extracting")); q.put(("pulse_on", 0))
                S.phase_extract(w, emit, prog); q.put(("pulse_off", 0))
            if v1.get():
                q.put(("status", "Classifying by name")); q.put(("pulse_on", 0))
                S.phase_name(w, emit); q.put(("pulse_off", 0))
            if v2.get():
                if ensure_librosa():
                    q.put(("status", "Classifying by audio")); S.phase_audio(w, emit, prog)
                else:
                    emit("  ! librosa unavailable — audio step skipped.")
            q.put(("status", "Archiving (sweep)")); q.put(("pulse_on", 0))
            S.phase_sweep(w, emit); q.put(("pulse_off", 0))
            q.put(("progress", 100)); q.put(("status", "Done ✓"))
        except Exception as e:
            emit(f"ERROR: {e}"); q.put(("status", "Error"))
        emit("=== end ==="); q.put(("refresh", 0)); q.put(("done", 0))

    def worker_backup():
        ts = open_log(); b = back_var.get()
        if not b:
            emit("Choose the backup (iCloud) folder first."); q.put(("done", 0)); return
        q.put(("status", "Backup (mirror)…")); q.put(("pulse_on", 0))
        rc = S.phase_backup(work_var.get(), b, emit)
        q.put(("pulse_off", 0)); q.put(("status", "Backup done ✓" if rc == 0 else "Backup had errors"))
        q.put(("done", 0))

    def start(fn):
        if state["running"]: return
        set_running(True); threading.Thread(target=fn, daemon=True).start()
    btn_run.configure(command=lambda: start(worker_pipeline))
    btn_bkp.configure(command=lambda: start(worker_backup))

    refresh(); root.after(120, drain); root.mainloop()

if __name__ == "__main__":
    main()
