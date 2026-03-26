import tkinter as tk
from tkinter import ttk, messagebox, font
import serial
import threading
import time
import datetime
import subprocess
import json
import os
import urllib.request
import asyncio
import tempfile

# ── AI imports ─────────────────────────────────────────────────────────────────
# pip install openai SpeechRecognition pyaudio edge-tts pygame
import speech_recognition as sr
from openai import OpenAI
import edge_tts
import pygame

# ── Config file ────────────────────────────────────────────────────────────────
CONFIG_FILE = "stm32_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"reminders": [], "city": "Dhaka", "port": "COM16", "groq_api_key": ""}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Serial ──────────────────────────────────────────────────────────────────────
ser = None
config = load_config()

def connect_serial(port):
    global ser
    try:
        if ser and ser.is_open:
            ser.close()
        ser = serial.Serial(port, 115200, timeout=1)
        return True
    except:
        return False

def send_data(data):
    global ser
    try:
        if ser and ser.is_open:
            ser.write((data + "\n").encode())
    except:
        pass

def send_ai_state(state, text=""):
    """Send AI state update to OLED. Text uses | as delimiter (safe for commas)."""
    if text:
        send_data(f"TYPE:AI_STATE,STATE:{state},TEXT:{text}")
    else:
        send_data(f"TYPE:AI_STATE,STATE:{state}")

# ── TTS using edge-tts (Microsoft neural voices — much better than pyttsx3) ───
# Voice options (young & casual):
#   "en-US-AndrewNeural"   — young American guy, chill
#   "en-US-AriaNeural"     — young American woman, casual
#   "en-US-GuyNeural"      — standard American male
#   "en-GB-RyanNeural"     — British young guy
TTS_VOICE = "en-US-GuyNeural"

def speak(text):
    """Speak text using edge-tts neural voice. Works reliably every call."""
    try:
        # Init pygame mixer once
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        # Generate audio to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        # Run async TTS in a fresh event loop
        async def _tts():
            communicate = edge_tts.Communicate(text, TTS_VOICE, rate="+10%")
            await communicate.save(tmp_path)

        asyncio.run(_tts())

        # Play it with pygame
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.unload()
        os.remove(tmp_path)

    except Exception as e:
        print(f"[TTS error] {e}")

# ── Data collection ─────────────────────────────────────────────────────────────
def get_gpu_load():
    try:
        result = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command',
             "(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage')"
             ".CounterSamples | Measure-Object -Property CookedValue -Sum | "
             "Select-Object -ExpandProperty Sum"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode().strip()
        if result:
            return min(100, int(float(result)))
    except:
        pass
    return 0

def get_weather(city):
    try:
        url = f"https://wttr.in/{city}?format=j1"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        current = data["current_condition"][0]
        temp = current["temp_C"] + "°C"
        desc = current["weatherDesc"][0]["value"].split()[0]
        return temp, desc
    except:
        return "--°C", "N/A"

# ── Colors & Fonts ──────────────────────────────────────────────────────────────
BG       = "#0d0d0d"
SURFACE  = "#1a1a1a"
SURFACE2 = "#242424"
ACCENT   = "#00ff88"
ACCENT2  = "#00cc6a"
TEXT     = "#e8e8e8"
MUTED    = "#666666"
DANGER   = "#ff4444"
WARN     = "#ffaa00"
AI_COLOR = "#bb88ff"   # purple accent for AI mode

# ── Main App ────────────────────────────────────────────────────────────────────
class STM32App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STM32 Monitor")
        self.geometry("520x720")
        self.configure(bg=BG)
        self.resizable(False, False)

        self.weather_temp = "--°C"
        self.weather_desc = "N/A"
        self.weather_last = 0

        self.cpu_var    = tk.StringVar(value="0")
        self.ram_var    = tk.StringVar(value="0")
        self.gpu_var    = tk.StringVar(value="0")
        self.status_var = tk.StringVar(value="Not connected")

        # AI state
        self.ai_active      = False   # True while in conversation loop
        self.ai_stop_flag   = False   # Set to True to break the loop (PB0 pressed)
        self.ai_status_var  = tk.StringVar(value="Idle  —  press button on device")

        # Init pygame for audio
        pygame.init()

        self.build_ui()
        self.after(500, lambda: self.auto_connect("COM16"))

        # Serial read thread (watches for AI_BTN from STM32)
        self.serial_read_thread = threading.Thread(target=self.serial_read_loop, daemon=True)
        self.serial_read_thread.start()

        # Data send thread
        self.data_thread = threading.Thread(target=self.data_loop, daemon=True)
        self.data_thread.start()

    # ─────────────────────────────────────────────────────────────────────────
    # UI Build
    # ─────────────────────────────────────────────────────────────────────────
    def build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(20, 0))

        tk.Label(header, text="STM32", font=("Courier", 22, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(header, text=" MONITOR", font=("Courier", 22),
                 bg=BG, fg=TEXT).pack(side="left")

        self.status_dot = tk.Label(header, text="●", font=("Courier", 14),
                                   bg=BG, fg=DANGER)
        self.status_dot.pack(side="right")
        tk.Label(header, textvariable=self.status_var, font=("Courier", 10),
                 bg=BG, fg=MUTED).pack(side="right", padx=6)

        tk.Frame(self, bg=ACCENT, height=1).pack(fill="x", padx=20, pady=10)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=SURFACE, foreground=MUTED,
                        font=("Courier", 10), padding=[16, 8], borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", SURFACE2)],
                  foreground=[("selected", ACCENT)])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=20, pady=0)

        self.tab_monitor  = tk.Frame(nb, bg=BG)
        self.tab_clock    = tk.Frame(nb, bg=BG)
        self.tab_reminder = tk.Frame(nb, bg=BG)
        self.tab_ai       = tk.Frame(nb, bg=BG)

        nb.add(self.tab_monitor,  text="Monitor")
        nb.add(self.tab_clock,    text="Clock")
        nb.add(self.tab_reminder, text="Reminders")
        nb.add(self.tab_ai,       text="AI")

        self.build_monitor_tab()
        self.build_clock_tab()
        self.build_reminder_tab()
        self.build_ai_tab()

        tk.Frame(self, bg=ACCENT, height=1).pack(fill="x", padx=20, pady=(10, 0))
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=20, pady=8)
        tk.Label(footer, text="STM32 OLED Controller  //  128×64",
                 font=("Courier", 9), bg=BG, fg=MUTED).pack(side="left")

    # ── Monitor Tab ─────────────────────────────────────────────────────────────
    def build_monitor_tab(self):
        f = self.tab_monitor
        tk.Label(f, text="SYSTEM STATS", font=("Courier", 11, "bold"),
                 bg=BG, fg=MUTED).pack(pady=(20, 10))
        self.cpu_bar = self.make_stat_row(f, "CPU", self.cpu_var,  ACCENT)
        self.ram_bar = self.make_stat_row(f, "RAM", self.ram_var,  "#00aaff")
        self.gpu_bar = self.make_stat_row(f, "GPU", self.gpu_var,  "#ff6600")
        tk.Label(f, text="Live data sent to OLED every second",
                 font=("Courier", 9), bg=BG, fg=MUTED).pack(pady=20)

    def make_stat_row(self, parent, label, var, color):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=30, pady=8)
        tk.Label(row, text=label, font=("Courier", 12, "bold"),
                 bg=BG, fg=TEXT, width=5, anchor="w").pack(side="left")
        canvas = tk.Canvas(row, width=260, height=20, bg=SURFACE2,
                           highlightthickness=0)
        canvas.pack(side="left", padx=10)
        bar = canvas.create_rectangle(0, 0, 0, 20, fill=color, outline="")
        canvas.create_rectangle(0, 0, 260, 20, outline=MUTED, width=1)
        tk.Label(row, textvariable=var, font=("Courier", 12, "bold"),
                 bg=BG, fg=color, width=5, anchor="e").pack(side="left")
        tk.Label(row, text="%", font=("Courier", 12),
                 bg=BG, fg=MUTED).pack(side="left")
        return (canvas, bar, 260, color)

    def update_bar(self, bar_info, value):
        canvas, bar, width, color = bar_info
        fill_w = int(width * value / 100)
        canvas.coords(bar, 0, 0, fill_w, 20)
        if value > 85:
            canvas.itemconfig(bar, fill=DANGER)
        elif value > 60:
            canvas.itemconfig(bar, fill=WARN)
        else:
            canvas.itemconfig(bar, fill=color)

    # ── Clock Tab ───────────────────────────────────────────────────────────────
    def build_clock_tab(self):
        f = self.tab_clock
        tk.Label(f, text="CLOCK & WEATHER", font=("Courier", 11, "bold"),
                 bg=BG, fg=MUTED).pack(pady=(20, 10))

        clock_frame = tk.Frame(f, bg=SURFACE, relief="flat")
        clock_frame.pack(padx=30, pady=10, fill="x")
        self.clock_label = tk.Label(clock_frame, text="00:00:00",
                                    font=("Courier", 40, "bold"),
                                    bg=SURFACE, fg=ACCENT)
        self.clock_label.pack(pady=(20, 5))
        self.date_label = tk.Label(clock_frame, text="",
                                   font=("Courier", 13),
                                   bg=SURFACE, fg=TEXT)
        self.date_label.pack(pady=(0, 20))

        weather_frame = tk.Frame(f, bg=SURFACE, relief="flat")
        weather_frame.pack(padx=30, pady=10, fill="x")
        tk.Label(weather_frame, text="WEATHER", font=("Courier", 10, "bold"),
                 bg=SURFACE, fg=MUTED).pack(pady=(12, 4))
        self.weather_label = tk.Label(weather_frame, text="Fetching...",
                                      font=("Courier", 14, "bold"),
                                      bg=SURFACE, fg="#00aaff")
        self.weather_label.pack(pady=(0, 12))

        city_row = tk.Frame(f, bg=BG)
        city_row.pack(padx=30, pady=8, fill="x")
        tk.Label(city_row, text="City:", font=("Courier", 11),
                 bg=BG, fg=TEXT).pack(side="left")
        self.city_entry = tk.Entry(city_row, font=("Courier", 11),
                                   bg=SURFACE2, fg=TEXT, insertbackground=ACCENT,
                                   relief="flat", bd=5)
        self.city_entry.insert(0, config.get("city", "Dhaka"))
        self.city_entry.pack(side="left", padx=10, fill="x", expand=True)
        self.make_button(city_row, "Update", self.update_city).pack(side="left")
        self.update_clock()

    def update_clock(self):
        now = datetime.datetime.now()
        self.clock_label.config(text=now.strftime("%H:%M:%S"))
        self.date_label.config(text=now.strftime("%A, %d %B %Y"))
        self.after(1000, self.update_clock)

    def update_city(self):
        config["city"] = self.city_entry.get().strip()
        save_config(config)
        self.weather_last = 0

    # ── Reminder Tab ────────────────────────────────────────────────────────────
    def build_reminder_tab(self):
        f = self.tab_reminder
        tk.Label(f, text="REMINDERS", font=("Courier", 11, "bold"),
                 bg=BG, fg=MUTED).pack(pady=(20, 10))

        add_frame = tk.Frame(f, bg=SURFACE, relief="flat")
        add_frame.pack(padx=30, pady=5, fill="x")
        inner = tk.Frame(add_frame, bg=SURFACE)
        inner.pack(padx=15, pady=15, fill="x")
        tk.Label(inner, text="New reminder:", font=("Courier", 10),
                 bg=SURFACE, fg=MUTED).pack(anchor="w")
        self.reminder_entry = tk.Entry(inner, font=("Courier", 12),
                                       bg=SURFACE2, fg=TEXT,
                                       insertbackground=ACCENT,
                                       relief="flat", bd=5)
        self.reminder_entry.pack(fill="x", pady=6)
        self.reminder_entry.bind("<Return>", lambda e: self.add_reminder())
        self.make_button(inner, "+ Add Reminder", self.add_reminder).pack(anchor="e")

        list_frame = tk.Frame(f, bg=SURFACE)
        list_frame.pack(padx=30, pady=10, fill="both", expand=True)
        tk.Label(list_frame, text="ACTIVE REMINDERS", font=("Courier", 9, "bold"),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.reminder_listbox = tk.Listbox(
            list_frame, font=("Courier", 11),
            bg=SURFACE2, fg=TEXT, selectbackground=ACCENT,
            selectforeground=BG, relief="flat", bd=0,
            highlightthickness=0, activestyle="none"
        )
        self.reminder_listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.make_button(list_frame, "✕ Remove Selected",
                         self.remove_reminder, danger=True).pack(anchor="e", padx=12, pady=(0, 10))
        self.refresh_reminder_list()

    def add_reminder(self):
        text = self.reminder_entry.get().strip()
        if not text:
            return
        if len(config["reminders"]) >= 5:
            messagebox.showwarning("Limit", "Max 5 reminders on OLED.")
            return
        config["reminders"].append(text)
        save_config(config)
        self.reminder_entry.delete(0, "end")
        self.refresh_reminder_list()

    def remove_reminder(self):
        sel = self.reminder_listbox.curselection()
        if not sel:
            return
        config["reminders"].pop(sel[0])
        save_config(config)
        self.refresh_reminder_list()

    def refresh_reminder_list(self):
        self.reminder_listbox.delete(0, "end")
        for i, r in enumerate(config["reminders"]):
            self.reminder_listbox.insert("end", f"  {i+1}.  {r}")

    # ── AI Tab ───────────────────────────────────────────────────────────────────
    def build_ai_tab(self):
        f = self.tab_ai

        tk.Label(f, text="AI ASSISTANT", font=("Courier", 11, "bold"),
                 bg=BG, fg=AI_COLOR).pack(pady=(20, 6))

        # API key input
        key_frame = tk.Frame(f, bg=SURFACE)
        key_frame.pack(padx=30, pady=6, fill="x")
        inner_k = tk.Frame(key_frame, bg=SURFACE)
        inner_k.pack(padx=15, pady=12, fill="x")
        tk.Label(inner_k, text="Groq API Key:", font=("Courier", 10),
                 bg=SURFACE, fg=MUTED).pack(anchor="w")
        self.api_key_entry = tk.Entry(inner_k, font=("Courier", 11),
                                      bg=SURFACE2, fg=TEXT,
                                      insertbackground=AI_COLOR,
                                      relief="flat", bd=5, show="*")
        self.api_key_entry.insert(0, config.get("groq_api_key", ""))
        self.api_key_entry.pack(fill="x", pady=6)
        btn_row = tk.Frame(inner_k, bg=SURFACE)
        btn_row.pack(fill="x")
        self.make_button(btn_row, "Save Key", self.save_api_key,
                         color=AI_COLOR).pack(side="left")
        self.key_status = tk.Label(btn_row, text="", font=("Courier", 9),
                                   bg=SURFACE, fg=MUTED)
        self.key_status.pack(side="left", padx=10)




        # Status display
        status_frame = tk.Frame(f, bg=SURFACE)
        status_frame.pack(padx=30, pady=8, fill="x")
        tk.Label(status_frame, text="STATUS", font=("Courier", 9, "bold"),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.ai_dot = tk.Label(status_frame, text="●", font=("Courier", 14),
                               bg=SURFACE, fg=MUTED)
        self.ai_dot.pack(side="left", padx=(12, 4), pady=(0, 10))
        tk.Label(status_frame, textvariable=self.ai_status_var,
                 font=("Courier", 10), bg=SURFACE, fg=TEXT,
                 wraplength=340, justify="left").pack(side="left", pady=(0, 10))

        # Conversation log
        log_frame = tk.Frame(f, bg=SURFACE)
        log_frame.pack(padx=30, pady=6, fill="both", expand=True)
        tk.Label(log_frame, text="CONVERSATION LOG", font=("Courier", 9, "bold"),
                 bg=SURFACE, fg=MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.ai_log = tk.Text(log_frame, font=("Courier", 10),
                              bg=SURFACE2, fg=TEXT, relief="flat", bd=0,
                              highlightthickness=0, state="disabled",
                              wrap="word", height=8)
        self.ai_log.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.make_button(log_frame, "Clear Log", self.clear_ai_log).pack(
            anchor="e", padx=12, pady=(0, 10))

        # Manual test button
        self.make_button(f, "▶  Test AI (no button needed)",
                         self.manual_ai_trigger, color=AI_COLOR).pack(pady=8)


    def save_api_key(self):
        key = self.api_key_entry.get().strip()
        config["groq_api_key"] = key
        save_config(config)
        self.key_status.config(text="Saved!", fg=ACCENT)
        self.after(2000, lambda: self.key_status.config(text=""))

    def clear_ai_log(self):
        self.ai_log.config(state="normal")
        self.ai_log.delete("1.0", "end")
        self.ai_log.config(state="disabled")

    def log_ai(self, role, text):
        self.ai_log.config(state="normal")
        prefix = "You: " if role == "user" else "AI:  "
        self.ai_log.insert("end", f"{prefix}{text}\n\n")
        self.ai_log.see("end")
        self.ai_log.config(state="disabled")

    def set_ai_status(self, text, color=TEXT):
        self.ai_status_var.set(text)
        self.ai_dot.config(fg=color)

    def manual_ai_trigger(self):
        if not self.ai_active:
            self.start_ai_session()
        else:
            self.stop_ai_session()

    # ── AI Session logic ─────────────────────────────────────────────────────────
    def start_ai_session(self):
        self.ai_active    = True
        self.ai_stop_flag = False
        self.set_ai_status("Listening...", AI_COLOR)
        send_ai_state("LISTENING")
        t = threading.Thread(target=self.ai_conversation_loop, daemon=True)
        t.start()

    def stop_ai_session(self):
        """Called when PB0 is pressed — exits the conversation loop."""
        self.ai_stop_flag = True
        self.ai_active    = False
        self.set_ai_status("Idle  —  press button on device", MUTED)
        send_ai_state("IDLE")

    def ai_conversation_loop(self):
        """
        Continuous conversation: listen → think → speak → listen → ...
        Exits when ai_stop_flag is set (PB0 pressed).
        """
        while not self.ai_stop_flag:
            success = self.ai_single_turn()
            if not success:
                # Timeout / no speech — wait a beat then try again unless stopped
                if self.ai_stop_flag:
                    break
                time.sleep(0.5)
                if not self.ai_stop_flag:
                    self.after(0, lambda: self.set_ai_status("Listening...", AI_COLOR))
                    send_ai_state("LISTENING")

        # Cleanup
        self.ai_active = False
        self.after(0, lambda: self.set_ai_status("Idle  —  press button on device", MUTED))
        send_ai_state("IDLE")

    def ai_single_turn(self) -> bool:
        """
        One full turn: listen → ask LLM → speak.
        Returns True if a full Q&A happened, False if no speech was detected.
        """
        # ── 1. Listen ────────────────────────────────────────────────────────
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.pause_threshold  = 1.0

        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                self.after(0, lambda: self.set_ai_status("Listening...", AI_COLOR))
                send_ai_state("LISTENING")
                try:
                    audio = recognizer.listen(source, timeout=8, phrase_time_limit=10)
                except sr.WaitTimeoutError:
                    self.after(0, lambda: self.set_ai_status("Nothing heard — still listening...", WARN))
                    return False
        except Exception as e:
            self.after(0, lambda: self.set_ai_status(f"Mic error: {str(e)[:40]}", DANGER))
            return False

        # ── 2. Speech to text ────────────────────────────────────────────────
        if self.ai_stop_flag:
            return False

        try:
            question = recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            self.after(0, lambda: self.set_ai_status("Couldn't catch that — try again!", WARN))
            return False
        except Exception as e:
            self.after(0, lambda: self.set_ai_status(f"STT error: {str(e)[:40]}", DANGER))
            return False

        self.after(0, lambda q=question: self.log_ai("user", q))
        self.after(0, lambda: self.set_ai_status("Thinking...", WARN))
        send_ai_state("THINKING")

        # ── 3. Ask Groq ──────────────────────────────────────────────────────
        if self.ai_stop_flag:
            return False

        api_key = config.get("groq_api_key", "").strip()
        if not api_key:
            answer = "Yo, no API key set! Go add your Groq key in the AI tab real quick."
        else:
            try:
                client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system",
                         "content": (
                             "You are a chill, funny AI assistant built into an STM32 device. "
                             "Talk like a young, casual friend — not a corporate assistant. "
                             "Use casual language, contractions, and light humor when it fits. "
                             "Keep answers SHORT: 1 to 3 sentences max. "
                             "No markdown, no bullet points, no asterisks, no special characters. "
                             "Just speak naturally like you're texting a friend."
                         )},
                        {"role": "user", "content": question}
                    ],
                    max_tokens=120,
                    temperature=0.85
                )
                answer = resp.choices[0].message.content.strip()
            except Exception as e:
                answer = f"Oof, API threw an error: {str(e)[:60]}"

        # ── 4. Update status (SPEAKING — no text on OLED) ────────────────────
        if self.ai_stop_flag:
            return False

        send_ai_state("SPEAKING")          # OLED shows speaking animation, no text
        self.after(0, lambda a=answer: self.log_ai("ai", a))
        self.after(0, lambda a=answer: self.set_ai_status(f"AI: {a[:70]}...", AI_COLOR))

        # ── 5. Speak answer ──────────────────────────────────────────────────
        speak(answer)

        return True

    # ── Helpers ──────────────────────────────────────────────────────────────────
    def make_button(self, parent, text, cmd, danger=False, color=None):
        c = DANGER if danger else (color if color else ACCENT)
        btn = tk.Label(parent, text=text, font=("Courier", 10, "bold"),
                       bg=SURFACE2, fg=c, padx=12, pady=6, cursor="hand2")
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.config(bg=c, fg=BG))
        btn.bind("<Leave>", lambda e: btn.config(bg=SURFACE2, fg=c))
        return btn

    def auto_connect(self, port="COM16"):
        if connect_serial(port):
            self.status_var.set("Connected: " + port)
            self.status_dot.config(fg=ACCENT)
        else:
            self.status_var.set("Not connected")

    # ── Serial read loop (watches for AI_BTN from STM32) ─────────────────────────
    def serial_read_loop(self):
        while True:
            try:
                if ser and ser.is_open and ser.in_waiting:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line == "AI_BTN:ON" and not self.ai_active:
                        self.after(0, self.start_ai_session)
                    elif line == "AI_BTN:OFF":
                        # PB0 pressed — exit conversation loop
                        self.after(0, self.stop_ai_session)
            except:
                pass
            time.sleep(0.05)

    # ── Data send loop ────────────────────────────────────────────────────────────
    def data_loop(self):
        import psutil
        while True:
            try:
                cpu = int(psutil.cpu_percent(interval=1))
                ram = int(psutil.virtual_memory().percent)
                gpu = get_gpu_load()

                self.cpu_var.set(str(cpu))
                self.ram_var.set(str(ram))
                self.gpu_var.set(str(gpu))

                self.after(0, lambda c=cpu: self.update_bar(self.cpu_bar, c))
                self.after(0, lambda r=ram: self.update_bar(self.ram_bar, r))
                self.after(0, lambda g=gpu: self.update_bar(self.gpu_bar, g))

                send_data(f"TYPE:MONITOR,CPU:{cpu},RAM:{ram},GPU:{gpu}")

                now = datetime.datetime.now()
                time_str = now.strftime("%H:%M")
                date_str = now.strftime("%a %d %b")

                if time.time() - self.weather_last > 600:
                    self.weather_temp, self.weather_desc = get_weather(config.get("city", "Dhaka"))
                    self.weather_last = time.time()
                    self.after(0, lambda: self.weather_label.config(
                        text=f"{self.weather_temp}  {self.weather_desc}"))

                send_data(f"TYPE:CLOCK,TIME:{time_str},DATE:{date_str},TEMP:{self.weather_temp},DESC:{self.weather_desc}")

                reminders = config.get("reminders", [])
                count = len(reminders)
                r_data = f"TYPE:REMINDER,COUNT:{count}"
                for i, r in enumerate(reminders[:5]):
                    r_data += f",R{i}:{r}"
                send_data(r_data)

            except Exception as e:
                pass

            time.sleep(1)

if __name__ == "__main__":
    app = STM32App()
    app.mainloop()