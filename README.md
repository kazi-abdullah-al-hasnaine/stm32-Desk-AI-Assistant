# STM32 OLED Monitor

A 4-mode OLED display connected to your PC via USB, showing live system stats, clock + weather, reminders, and an AI voice assistant. Controlled by two buttons. Managed from a Python desktop UI.

---

## What You Need

**Hardware**
- STM32F103C8 (Blue Pill)
- ST-Link V2 (for flashing)
- 0.96" OLED display (128×64, I2C, SSD1306)
- 2× tactile push buttons
- Breadboard + jumper wires
- 2× USB cables (one for ST-Link, one for STM32 USB port)
- Microphone (connected to your PC, for the AI mode)

**Software**
- Arduino IDE 2.x
- Python 3.x

---

## Step 1 — Install the STM32F1 Arduino Core

This project uses the **Roger Clark / STM32duino STM32F1 core** — not the official ST core.

1. Open Arduino IDE
2. Go to **File → Preferences**
3. Under **Additional boards manager URLs**, add:
   ```
   https://dan.drown.org/stm32duino/package_STM32duino_index.json
   ```
4. Go to **Tools → Board → Boards Manager**
5. Search for **STM32F1** and install **STM32F1xx/GD32F1xx boards** by stm32duino

---

## Step 2 — Install Required Libraries

### USBComposite for STM32F1 (manual install — not in Library Manager)

1. Go to: https://github.com/arpruss/USBComposite_stm32f1
2. Click **Code → Download ZIP**
3. In Arduino IDE: **Sketch → Include Library → Add .ZIP Library**
4. Select the downloaded ZIP

### Adafruit SSD1306 + GFX (via Library Manager)

1. Go to **Sketch → Include Library → Manage Libraries**
2. Search **Adafruit SSD1306** → Install
3. Search **Adafruit GFX Library** → Install (installs automatically as dependency too)

---

## Step 3 — Board Settings in Arduino IDE

Go to **Tools** and set the following:

| Setting | Value |
|---|---|
| Board | Generic STM32F103C series |
| Variant | STM32F103C8 (20k RAM, 64k Flash) |
| CPU Speed | 72 MHz |
| Upload Method | STLink |

---

## Step 4 — Wiring

### OLED Display (I2C)

| OLED Pin | STM32 Pin |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SDA | PB7 |
| SCL | PB6 |

> Use **3.3V only** — do not connect to 5V.

### Buttons

| Button | STM32 Pin | Function |
|---|---|---|
| Mode button (one side) | PA3 | Cycle through normal modes |
| Mode button (other side) | GND | — |
| AI button (one side) | PB0 | Toggle AI mode on/off |
| AI button (other side) | GND | — |

No resistors needed — the code uses `INPUT_PULLUP` for both buttons.

### USB Connections

```
PC  ──USB──►  ST-Link  ──SWD──►  STM32   (flashing only)
PC  ──USB──►  STM32 USB port              (runtime serial data)
```

Both cables plugged in at the same time during normal use.

---

## Step 5 — Flash the STM32

1. Open `stm32_monitor.ino` in Arduino IDE
2. Connect ST-Link to PC and to STM32 SWD pins (SWDIO, SWCLK, GND, 3.3V)
3. Make sure **BOOT0 jumper = 0** (normal run mode)
4. Click **Upload**
5. After flashing, plug the STM32's own USB cable into your PC
6. In Device Manager you should see a new serial port (e.g. COM16)

---

## Step 6 — Install Python Dependencies

Open a terminal and run:

```bash
pip install pyserial psutil openai SpeechRecognition pyaudio edge-tts pygame
```

> **Note:** `pyaudio` can sometimes fail to install on Windows. If it does, download the matching `.whl` from https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio and install it manually with `pip install <filename>.whl`.

---

## Step 7 — Get a Groq API Key (for AI mode)

The AI assistant uses **Groq** to run the LLM (fast, free tier available).

1. Go to https://console.groq.com and sign up / log in
2. Navigate to **API Keys** and create a new key
3. Copy the key — you'll paste it into the Python UI in Step 9

---

## Step 8 — Run the Python UI

```bash
python monitor_ui.py
```

The app connects to **COM16** automatically on startup. The dot in the top-right corner turns green when connected.

> If your STM32 is on a different COM port, open `monitor_ui.py` and change `COM16` in the `auto_connect` call near the bottom of `__init__`.

---

## Step 9 — Set Up the AI Assistant

1. Open the app and go to the **AI tab**
2. Paste your Groq API key into the **Groq API Key** field
3. Click **Save Key**

That's it — the key is saved to `stm32_config.json` and loaded automatically on future runs.

---

## How to Use

### Buttons

| Button | Pin | Action |
|---|---|---|
| Mode button | PA3 | Cycles through Monitor → Clock/Weather → Reminders (normal mode only) |
| AI button | PB0 | Toggles AI mode on or off |

A thin indicator bar appears at the bottom of the screen during mode transitions and fades away after ~1 second.

### Normal Modes (cycle with PA3 button)

```
Monitor  →  Clock / Weather  →  Reminders  →  Monitor  → ...
```

### AI Mode (toggle with PB0 button)

Press **PB0** to enter AI mode. The OLED shows **AI MODE** at the top and cycles through four states:

| OLED State | What's happening |
|---|---|
| Idle | Waiting — shows "Press button to ask a question" |
| Listening | Mic icon with animated dots — recording your voice |
| Thinking | Spinner animation — waiting for Groq to respond |
| Speaking | Animated sound wave bars — TTS audio playing |

Press **PB0** again at any time to exit AI mode and return to the normal display.

You can also trigger AI mode from the Python UI using the **▶ Test AI** button in the AI tab — no physical button needed.

The AI conversation loops continuously (listen → think → speak → listen…) until you press PB0 to stop.

### Monitor Page
Shows live CPU, RAM, and GPU usage sent from your PC.

### Clock / Weather Page
Shows the current time, date, and weather for your configured city.
Update the city from the **Clock tab** in the Python UI.

### Reminders Page
Shows up to 5 reminders. Add and remove them from the **Reminders tab** in the Python UI.
If more than 3 reminders are set, the list auto-scrolls every 3 seconds.

---

## Python UI Overview

| Tab | What it does |
|---|---|
| Monitor | Live CPU / RAM / GPU bars with color coding |
| Clock | Live clock display + city input for weather |
| Reminders | Add / remove reminders saved to `stm32_config.json` |
| AI | Groq API key input, live status indicator, conversation log, manual trigger button |

Settings and reminders are saved to `stm32_config.json` in the same folder as the script — they persist between runs.

---

## Troubleshooting

**OLED not showing anything**
- Check VCC is 3.3V not 5V
- Check SDA → PB7 and SCL → PB6
- Make sure I2C address is `0x3C` (most common) — if not, change it in the sketch

**STM32 USB not showing up as serial port**
- Make sure the sketch is flashed and STM32 USB cable is plugged in
- The USBComposite library must be installed correctly
- Device Manager should show it as a serial port, not a generic USB device

**Python shows "Not connected"**
- Check the COM port number in Device Manager
- Edit `monitor_ui.py` and change `COM16` to your actual port

**GPU shows 0**
- Run `monitor_ui.py` or the terminal as **Administrator** (right-click → Run as Administrator)
- The GPU counter requires elevated permissions on Windows

**Weather shows `---`**
- Check your internet connection
- The city name must be recognisable by wttr.in (e.g. `London`, `New York`, `Dhaka`)

**AI mode: mic not working / "Mic error"**
- Make sure a microphone is connected to your PC
- Try running the script as Administrator
- If `pyaudio` failed to install, see the note in Step 6

**AI mode: "No API key set"**
- Go to the **AI tab** in the Python UI, paste your Groq key, and click **Save Key**

**AI mode: API error**
- Check your internet connection
- Verify your Groq API key is valid at https://console.groq.com
- Free tier has rate limits — wait a moment and try again

**AI button (PB0) not responding**
- Check the button is wired to PB0 and GND
- Make sure the sketch was re-flashed after adding the second button

---

## File Reference

| File | Description |
|---|---|
| `stm32_monitor.ino` | Arduino sketch for STM32 |
| `monitor_ui.py` | Python desktop UI |
| `stm32_config.json` | Auto-generated config (reminders, city, Groq API key) |
| `README.md` | This file |
