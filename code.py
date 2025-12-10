"""
Quartz Code — Music Player (FINAL v2)
Features:
 - Dark themed playlist (Spotify-like)
 - Embedded album art extraction (MP3 APIC, MP4 covr, FLAC pictures)
 - Play / Pause / Stop / Next / Prev
 - Seek with immediate UI update and robust duration handling
 - Volume, Shuffle, Repeat (Off/All/One)
 - Search/filter playlist, Save/Load playlist
 - Keyboard shortcuts (Space, ←, →, Delete, Ctrl+S, Ctrl+O)
 - No pydub dependency (compatible with Python 3.13)

Save as: quartz_music_player_final_v2.py
Requires: customtkinter, pygame, mutagen, pillow
Install: pip install customtkinter pygame mutagen pillow
"""
import os
import json
import random
import io
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import pygame
from PIL import Image, ImageTk, ImageOps

from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.id3 import ID3, APIC, error as ID3Error

# ----------- Config -----------
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_W, APP_H = 1100, 660
PLAYLIST_FILE = "playlist.json"

pygame.mixer.init()

# ----------- Helpers -----------
def format_time(sec):
    try:
        sec = int(sec)
        return f"{sec//60:02d}:{sec%60:02d}"
    except:
        return "00:00"

def get_length(path):
    """Primary length getter using mutagen where possible."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            return MP3(path).info.length
        if ext == ".flac":
            return FLAC(path).info.length
        if ext in (".mp4", ".m4a", ".aac"):
            return MP4(path).info.length
        # fallback may raise but handled by caller
        return pygame.mixer.Sound(path).get_length()
    except:
        return 0.0

def get_length_fallback(path):
    """Try get_length (mutagen), then pygame Sound as a fallback."""
    try:
        l = get_length(path)
        if l and l > 0:
            return l
    except:
        pass
    try:
        s = pygame.mixer.Sound(path)
        return s.get_length()
    except:
        return 0.0

def extract_embedded_art(path):
    """Return PIL.Image or None. Supports MP3 APIC, MP4 covr, FLAC pictures."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            try:
                tags = ID3(path)
            except ID3Error:
                return None
            apics = tags.getall("APIC")
            if apics:
                return Image.open(io.BytesIO(apics[0].data)).convert("RGBA")
            return None
        elif ext in (".m4a", ".mp4"):
            audio = MP4(path)
            covr = audio.tags.get("covr")
            if covr:
                return Image.open(io.BytesIO(covr[0])).convert("RGBA")
            return None
        elif ext == ".flac":
            audio = FLAC(path)
            if audio.pictures:
                return Image.open(io.BytesIO(audio.pictures[0].data)).convert("RGBA")
            return None
    except:
        return None

# ----------- App -----------
class QuartzPlayer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Quartz Code — Music Player")
        self.geometry(f"{APP_W}x{APP_H}")
        self.minsize(900, 560)

        # state
        self.playlist = []            # list of file paths
        self.idx = None               # current index
        self.playing = False
        self.paused = False
        self.length = 0.0
        self.shuffle = False
        self.repeat = "off"           # off / all / one
        self._manual_seek_pos = None  # used after seeking to stabilize UI

        # layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=4)
        self.grid_rowconfigure(0, weight=1)

        self._build_left()
        self._build_right()
        self._build_footer()
        self._bind_shortcuts()

        # start update loop
        self.after(250, self._update_loop)

    # ---- Left: Playlist ----
    def _build_left(self):
        left = ctk.CTkFrame(self, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        left.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(left, text="Playlist", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10,4)
        )

        # search
        self.search_var = tk.StringVar()
        search = ctk.CTkEntry(left, placeholder_text="Search...", textvariable=self.search_var)
        search.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        search.bind("<KeyRelease>", lambda e: self._filter_playlist())

        # dark list container
        list_container = ctk.CTkFrame(left, fg_color="#0f0f10", corner_radius=8)
        list_container.grid(row=2, column=0, sticky="nsew", padx=12, pady=(6,12))
        list_container.grid_rowconfigure(0, weight=1)
        list_container.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            list_container, bg="#0b0b0c", fg="#e6e6e6",
            selectbackground="#2b8cff", bd=0, highlightthickness=0,
            activestyle="none", exportselection=False
        )
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.listbox.bind("<Double-Button-1>", lambda e: self.play_selected())
        self.listbox.bind("<Delete>", lambda e: self.remove_selected())

        sb = tk.Scrollbar(list_container, command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=sb.set)

        # buttons
        btnrow = ctk.CTkFrame(left)
        btnrow.grid(row=3, column=0, sticky="ew", padx=12)
        btnrow.grid_columnconfigure((0,1,2,3), weight=1)
        ctk.CTkButton(btnrow, text="Add Files", command=self.add_files).grid(row=0, column=0, padx=6)
        ctk.CTkButton(btnrow, text="Add Folder", command=self.add_folder).grid(row=0, column=1, padx=6)
        ctk.CTkButton(btnrow, text="Remove", command=self.remove_selected).grid(row=0, column=2, padx=6)
        ctk.CTkButton(btnrow, text="Clear", command=self.clear_playlist).grid(row=0, column=3, padx=6)

    # ---- Right: Player ----
    def _build_right(self):
        right = ctk.CTkFrame(self, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        # header
        header = ctk.CTkFrame(right, corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        header.grid_columnconfigure(1, weight=1)

        self.art_size = 160
        self.art_label = ctk.CTkLabel(header, text="")
        self.art_label.grid(row=0, column=0, rowspan=2, padx=12, pady=12)
        self._set_art_placeholder()

        self.title_label = ctk.CTkLabel(header, text="No track selected", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.grid(row=0, column=1, sticky="w", padx=10, pady=(20,0))
        self.path_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=11))
        self.path_label.grid(row=1, column=1, sticky="w", padx=10)

        # progress
        prog = ctk.CTkFrame(right, corner_radius=8)
        prog.grid(row=1, column=0, sticky="ew", padx=10, pady=(0,10))
        prog.grid_columnconfigure(1, weight=1)

        self.curr_lbl = ctk.CTkLabel(prog, text="00:00")
        self.curr_lbl.grid(row=0, column=0, padx=12)
        self.total_lbl = ctk.CTkLabel(prog, text="/ 00:00")
        self.total_lbl.grid(row=0, column=2, padx=12)
        self.slider = ctk.CTkSlider(prog, from_=0, to=100, command=self._on_seek)
        self.slider.grid(row=0, column=1, sticky="ew", padx=8)

        # controls
        ctrl = ctk.CTkFrame(right)
        ctrl.grid(row=2, column=0, pady=10)
        ctk.CTkButton(ctrl, text="⏮", width=70, command=self.prev_song).grid(row=0, column=0, padx=8)
        self.play_btn = ctk.CTkButton(ctrl, text="▶", width=100, command=self.play_pause)
        self.play_btn.grid(row=0, column=1, padx=8)
        ctk.CTkButton(ctrl, text="⏹", width=70, command=self.stop_song).grid(row=0, column=2, padx=8)
        ctk.CTkButton(ctrl, text="⏭", width=70, command=self.next_song).grid(row=0, column=3, padx=8)

        # bottom: volume, modes, save/load
        bottom = ctk.CTkFrame(right, corner_radius=8)
        bottom.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        bottom.grid_columnconfigure(2, weight=1)

        volf = ctk.CTkFrame(bottom, fg_color="transparent")
        volf.grid(row=0, column=0, padx=10)
        ctk.CTkLabel(volf, text="Vol").pack(side="left", padx=4)
        self.vol_var = tk.DoubleVar(value=0.85)
        ctk.CTkSlider(volf, from_=0, to=1, variable=self.vol_var, command=self.set_volume).pack(side="left", padx=4)

        left_controls = ctk.CTkFrame(bottom, fg_color="transparent")
        left_controls.grid(row=0, column=1, sticky="w")
        ctk.CTkButton(left_controls, text="Save List", width=90, command=self.save_playlist).pack(side="left", padx=6)
        ctk.CTkButton(left_controls, text="Load List", width=90, command=self.load_playlist).pack(side="left", padx=6)

        modes = ctk.CTkFrame(bottom, fg_color="transparent")
        modes.grid(row=0, column=2, sticky="e")
        self.shuffle_btn = ctk.CTkButton(modes, text="Shuffle", width=100, command=self.toggle_shuffle)
        self.shuffle_btn.pack(side="left", padx=8)
        self.repeat_btn = ctk.CTkButton(modes, text="Repeat: Off", width=120, command=self.cycle_repeat)
        self.repeat_btn.pack(side="left", padx=8)

    # ---- Footer ----
    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(footer, text="Created by Quartz Code", font=ctk.CTkFont(size=11)).pack(side="right", padx=12)

    # ---- Shortcuts ----
    def _bind_shortcuts(self):
        self.bind("<space>", lambda e: self.play_pause())
        self.bind("<Right>", lambda e: self.next_song())
        self.bind("<Left>", lambda e: self.prev_song())
        self.bind("<Delete>", lambda e: self.remove_selected())
        self.bind("<Control-s>", lambda e: self.save_playlist())
        self.bind("<Control-o>", lambda e: self.load_playlist())

    # ---- Playlist ops ----
    def add_files(self):
        files = filedialog.askopenfilenames(title="Select audio files", filetypes=[("Audio", "*.mp3 *.flac *.wav *.m4a *.mp4 *.aac")])
        self._add_paths(list(files))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        exts = (".mp3", ".flac", ".wav", ".m4a", ".mp4", ".aac", ".ogg")
        found = []
        for r, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(exts):
                    found.append(os.path.join(r, f))
        self._add_paths(found)

    def _add_paths(self, paths):
        added = False
        for p in paths:
            if p and p not in self.playlist:
                self.playlist.append(p)
                self.listbox.insert(tk.END, os.path.basename(p))
                added = True
        if added and self.idx is None:
            self.idx = 0

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        i = sel[0]
        self.listbox.delete(i)
        self.playlist.pop(i)
        if self.idx == i:
            self.stop_song()
            self.idx = None
        elif self.idx is not None and i < self.idx:
            self.idx -= 1

    def clear_playlist(self):
        self.listbox.delete(0, tk.END)
        self.playlist.clear()
        self.idx = None
        self.stop_song()

    def save_playlist(self):
        try:
            with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(self.playlist, f, indent=2)
            messagebox.showinfo("Saved", f"Playlist saved to {PLAYLIST_FILE}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def load_playlist(self):
        if not os.path.exists(PLAYLIST_FILE):
            messagebox.showwarning("Not found", f"No saved playlist ({PLAYLIST_FILE})")
            return
        try:
            with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.clear_playlist()
            self._add_paths(data)
            messagebox.showinfo("Loaded", "Playlist loaded")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _filter_playlist(self):
        q = self.search_var.get().strip().lower()
        self.listbox.delete(0, tk.END)
        for p in self.playlist:
            name = os.path.basename(p)
            if not q or q in name.lower():
                self.listbox.insert(tk.END, name)

    # ---- Album art ----
    def _set_art_placeholder(self):
        img = Image.new("RGBA", (self.art_size, self.art_size), (30,30,32,255))
        img = ImageOps.expand(img, border=2, fill=(60,60,60))
        tki = ImageTk.PhotoImage(img)
        self.art_label.configure(image=tki)
        self.art_label.image = tki

    def _display_pil_image(self, pil_img):
        try:
            img = ImageOps.fit(pil_img, (self.art_size, self.art_size), Image.LANCZOS)
            tki = ImageTk.PhotoImage(img)
            self.art_label.configure(image=tki)
            self.art_label.image = tki
        except:
            self._set_art_placeholder()

    def _set_art_for(self, path):
        img = extract_embedded_art(path)
        if img:
            self._display_pil_image(img)
            return
        folder = os.path.dirname(path)
        for name in ("cover.jpg","cover.png","folder.jpg","album.jpg"):
            cand = os.path.join(folder, name)
            if os.path.exists(cand):
                try:
                    self._display_pil_image(Image.open(cand))
                    return
                except:
                    break
        self._set_art_placeholder()

    # ---- Playback ----
    def _load_track(self, idx):
        if idx is None or idx < 0 or idx >= len(self.playlist):
            return False
        path = self.playlist[idx]
        try:
            pygame.mixer.music.load(path)
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not load file:\n{e}")
            return False

        # Use fallback to get a reliable length
        self.length = get_length_fallback(path) or 0.0
        if self.length and self.length > 0:
            self.total_lbl.configure(text="/ " + format_time(self.length))
        else:
            self.total_lbl.configure(text="/ 00:00")

        self.slider.set(0)
        self.title_label.configure(text=os.path.basename(path))
        self.path_label.configure(text=os.path.dirname(path))
        self._set_art_for(path)
        return True

    def play_selected(self):
        sel = self.listbox.curselection()
        if sel:
            name = self.listbox.get(sel[0])
            for i,p in enumerate(self.playlist):
                if os.path.basename(p) == name:
                    self.idx = i
                    break
        else:
            if self.idx is None and self.playlist:
                self.idx = 0
        self.start_playback()

    def start_playback(self):
        if self.idx is None:
            return
        ok = self._load_track(self.idx)
        if not ok:
            return
        pygame.mixer.music.play()
        pygame.mixer.music.set_volume(self.vol_var.get())
        self.playing = True
        self.paused = False
        self.play_btn.configure(text="⏸")
        self._highlight_current()

    def play_pause(self):
        if not self.playlist:
            return
        if not self.playing:
            if self.idx is None:
                self.idx = 0
            self.start_playback()
        else:
            if self.paused:
                pygame.mixer.music.unpause()
                self.paused = False
                self.play_btn.configure(text="⏸")
            else:
                pygame.mixer.music.pause()
                self.paused = True
                self.play_btn.configure(text="▶")

    def stop_song(self):
        pygame.mixer.music.stop()
        self.playing = False
        self.paused = False
        self.play_btn.configure(text="▶")
        self.slider.set(0)
        self.curr_lbl.configure(text="00:00")

    def next_song(self):
        if not self.playlist:
            return
        if self.shuffle:
            self.idx = random.randrange(len(self.playlist))
        else:
            if self.idx is None:
                self.idx = 0
            else:
                self.idx += 1
                if self.idx >= len(self.playlist):
                    if self.repeat == "all":
                        self.idx = 0
                    else:
                        self.stop_song()
                        return
        self.start_playback()

    def prev_song(self):
        if not self.playlist:
            return
        self.idx = (self.idx - 1) % len(self.playlist) if self.repeat == "all" else max(0, (self.idx or 0) - 1)
        self.start_playback()

    # ---- Seek: robust + immediate UI update ----
    def _on_seek(self, val):
        # val: 0..100 (percentage)
        if not self.playing:
            return
        if self.idx is None or self.idx >= len(self.playlist):
            return
        path = self.playlist[self.idx]

        # compute seconds; refresh length if unknown
        length = self.length if (self.length and self.length > 0) else get_length_fallback(path)
        if length and length > 0:
            sec = (float(val) / 100.0) * length
        else:
            # best-effort: treat val as seconds
            try:
                sec = float(val)
            except:
                sec = 0.0

        # try to jump
        try:
            pygame.mixer.music.play(start=sec)
        except:
            # don't crash; still update UI
            pass

        # re-check length and update total label
        try:
            new_len = get_length_fallback(path)
            if new_len and new_len > 0:
                self.length = new_len
                self.total_lbl.configure(text="/ " + format_time(self.length))
        except:
            pass

        # update UI immediately
        try:
            self.curr_lbl.configure(text=format_time(sec))
            if self.length and self.length > 0:
                self.slider.set((sec / self.length) * 100)
            else:
                self.slider.set(val)
        except:
            pass

        # use manual pos for next update loop iteration
        self._manual_seek_pos = sec

    # ---- Misc ----
    def set_volume(self, *a):
        try:
            pygame.mixer.music.set_volume(self.vol_var.get())
        except:
            pass

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.shuffle_btn.configure(fg_color="#2b8cff" if self.shuffle else None)

    def cycle_repeat(self):
        if self.repeat == "off":
            self.repeat = "all"; self.repeat_btn.configure(text="Repeat: All")
        elif self.repeat == "all":
            self.repeat = "one"; self.repeat_btn.configure(text="Repeat: One")
        else:
            self.repeat = "off"; self.repeat_btn.configure(text="Repeat: Off")

    def _highlight_current(self):
        # refresh filter then select current basename
        self._filter_playlist()
        if self.idx is None: return
        base = os.path.basename(self.playlist[self.idx])
        for i in range(self.listbox.size()):
            if self.listbox.get(i) == base:
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(i)
                self.listbox.see(i)
                break

    # ---- Update loop ----
    def _update_loop(self):
        if self.playing and not self.paused:
            # use manual seek position once if present
            if self._manual_seek_pos is not None:
                pos = self._manual_seek_pos
                self._manual_seek_pos = None
            else:
                pos = pygame.mixer.music.get_pos() / 1000.0
            if pos < 0:
                pos = 0

            if self.length and pos >= self.length - 0.4:
                # track ended
                if self.repeat == "one":
                    pygame.mixer.music.play()
                else:
                    self.next_song()
            else:
                if self.length and self.length > 0:
                    try:
                        self.slider.set((pos / self.length) * 100)
                    except:
                        pass
                try:
                    self.curr_lbl.configure(text=format_time(pos))
                except:
                    pass

        self.after(250, self._update_loop)

# ---- Run ----
if __name__ == "__main__":
    app = QuartzPlayer()
    # center window on screen
    x = (app.winfo_screenwidth() // 2) - (APP_W // 2)
    y = (app.winfo_screenheight() // 2) - (APP_H // 2)
    app.geometry(f"{APP_W}x{APP_H}+{x}+{y}")
    app.mainloop()
