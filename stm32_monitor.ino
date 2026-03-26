#include <USBComposite.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1
#define BUTTON_PIN    PA3   // existing mode-cycle button
#define AI_BUTTON_PIN PB0   // NEW: AI mode toggle button

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
USBCompositeSerial CompositeSerial;

// ── Mode ──────────────────────────────────────────────────────────────────────
// currentMode: 0=Monitor, 1=Clock, 2=Reminders
// aiMode:      true = AI mode active (overrides currentMode display)
int currentMode = 0;
bool aiMode     = false;

// ── Button debounce ───────────────────────────────────────────────────────────
unsigned long lastButtonPress   = 0;
unsigned long lastAIButtonPress = 0;
const int DEBOUNCE_MS = 250;
bool lastButtonState   = HIGH;
bool lastAIButtonState = HIGH;

// ── Normal mode data ──────────────────────────────────────────────────────────
String cpu = "0", ram = "0", gpu = "0";
String timeStr    = "00:00";
String dateStr    = "Mon 01 Jan";
String weatherDesc = "---";
String weatherTemp = "--";
String reminders[5] = {"", "", "", "", ""};
int reminderCount  = 0;
int reminderScroll = 0;
unsigned long lastScroll = 0;

// ── AI mode state ─────────────────────────────────────────────────────────────
// STATE: "IDLE" | "LISTENING" | "THINKING" | "ANSWER"
String aiState   = "IDLE";
String aiAnswer  = "";          // answer text from Python (may be long)
int    answerScroll   = 0;      // which line is shown first
unsigned long lastAnswerScroll = 0;

// ── Fading indicator bar ──────────────────────────────────────────────────────
bool barVisible = false;
unsigned long barStart = 0;
const int BAR_HOLD_MS = 600;
const int BAR_FADE_MS = 400;
int barBlink = 0;

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
int centerX(const String& text, int sz) {
  return (128 - (int)text.length() * 6 * sz) / 2;
}

void drawStatBar(int x, int y, int w, int h, int pct) {
  display.drawRect(x, y, w, h, WHITE);
  int fill = (w - 2) * pct / 100;
  if (fill > 0) display.fillRect(x + 1, y + 1, fill, h - 2, WHITE);
}

// Wrap a long string into lines of maxChars width
// Returns number of lines written into lines[]
int wrapText(const String& text, int maxChars, String lines[], int maxLines) {
  int count = 0;
  int start = 0;
  int len   = text.length();
  while (start < len && count < maxLines) {
    if (len - start <= maxChars) {
      lines[count++] = text.substring(start);
      break;
    }
    int cut = start + maxChars;
    // Try to break on a space
    int sp = -1;
    for (int i = cut; i > start; i--) {
      if (text.charAt(i) == ' ') { sp = i; break; }
    }
    if (sp == -1) sp = cut;
    lines[count++] = text.substring(start, sp);
    start = sp + 1;
  }
  return count;
}

// ─────────────────────────────────────────────────────────────────────────────
// Normal page renderers
// ─────────────────────────────────────────────────────────────────────────────
void renderMonitor() {
  int cpuVal = cpu.toInt();
  int ramVal = ram.toInt();
  int gpuVal = gpu.toInt();

  display.fillRect(0, 0, 128, 11, WHITE);
  display.setTextColor(BLACK);
  display.setCursor(30, 2);
  display.print("SYS MONITOR");
  display.setTextColor(WHITE);

  display.setCursor(2, 16);
  display.print("CPU");
  drawStatBar(28, 15, 96, 10, cpuVal);

  display.setCursor(2, 32);
  display.print("RAM");
  drawStatBar(28, 31, 96, 10, ramVal);

  display.setCursor(2, 48);
  display.print("GPU");
  drawStatBar(28, 47, 96, 10, gpuVal);
}

void renderClock() {
  display.setTextSize(3);
  display.setCursor(centerX(timeStr, 3), 10);
  display.print(timeStr);

  display.drawFastHLine(20, 38, 88, WHITE);

  display.setTextSize(1);
  display.setCursor(centerX(dateStr, 1), 44);
  display.print(dateStr);

  String wLine = weatherTemp + "C  " + weatherDesc;
  display.setCursor(centerX(wLine, 1), 54);
  display.print(wLine);
}

void renderReminders() {
  display.fillRect(0, 0, 128, 11, WHITE);
  display.setTextColor(BLACK);
  display.setCursor(34, 2);
  display.print("REMINDERS");
  display.setTextColor(WHITE);

  if (reminderCount == 0) {
    display.setCursor(18, 32);
    display.print("No tasks found");
  } else {
    for (int i = 0; i < 3 && i < reminderCount; i++) {
      int idx = (reminderScroll + i) % reminderCount;
      String r = reminders[idx];
      if ((int)r.length() > 18) r = r.substring(0, 17) + "..";
      display.setCursor(4, 16 + i * 15);
      display.print("> ");
      display.print(r);
    }
    if (reminderCount > 3 && millis() - lastScroll > 3000) {
      lastScroll = millis();
      reminderScroll = (reminderScroll + 1) % reminderCount;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// AI mode renderers
// ─────────────────────────────────────────────────────────────────────────────

// Shared top bar (same style as SYS MONITOR)
void drawAITopBar() {
  display.fillRect(0, 0, 128, 11, WHITE);
  display.setTextColor(BLACK);
  display.setCursor(37, 2);
  display.print("AI  MODE");
  display.setTextColor(WHITE);
}

// Animated dots helper — returns "." / ".." / "..." based on time
String animDots() {
  int phase = (millis() / 400) % 3;
  if (phase == 0) return ".";
  if (phase == 1) return "..";
  return "...";
}

void renderAIListening() {
  drawAITopBar();
  // Big icon area
  display.drawCircle(64, 36, 14, WHITE);
  display.fillCircle(64, 36, 9, WHITE);
  // Mic stem
  display.drawFastVLine(64, 50, 6, WHITE);
  display.drawFastHLine(58, 56, 12, WHITE);
  // Label
  display.setCursor(22, 56);
  display.print("Listening" + animDots());
}

void renderAIThinking() {
  drawAITopBar();
  display.setCursor(centerX("Thinking", 1), 24);
  display.print("Thinking" + animDots());
  // Spinner: draw an arc approximation using pixels
  int cx = 64, cy = 44, r = 10;
  unsigned long t = millis() / 80;
  for (int i = 0; i < 8; i++) {
    float angle = (i * 45 + t * 20) * 3.14159 / 180.0;
    int px = cx + (int)(r * cos(angle));
    int py = cy + (int)(r * sin(angle));
    uint8_t bright = (i < 3) ? 1 : 0;  // trail effect
    if (bright) display.drawPixel(px, py, WHITE);
  }
}

void renderAISpeaking() {
  drawAITopBar();
  // Animated sound wave bars
  int cx = 64;
  int cy = 38;
  int bars = 7;
  int barW = 6;
  int gap  = 3;
  int totalW = bars * barW + (bars - 1) * gap;
  int startX = cx - totalW / 2;
  unsigned long t = millis();
  for (int i = 0; i < bars; i++) {
    // Each bar oscillates at a slightly different phase
    float phase = i * 0.7f;
    float wave  = sin((t / 180.0f) + phase);
    int h = 6 + (int)(wave * 10);
    if (h < 4) h = 4;
    int x = startX + i * (barW + gap);
    display.fillRect(x, cy - h / 2, barW, h, WHITE);
  }
  display.setCursor(centerX("Speaking...", 1), 56);
  display.print("Speaking...");
}

void renderAIIdle() {
  drawAITopBar();
  display.setCursor(10, 28);
  display.print("Press button to");
  display.setCursor(22, 40);
  display.print("ask a question");
}

// ─────────────────────────────────────────────────────────────────────────────
// Fading indicator bar (normal mode only)
// ─────────────────────────────────────────────────────────────────────────────
void drawIndicatorBar() {
  if (!barVisible) return;
  unsigned long elapsed = millis() - barStart;

  if (elapsed >= (unsigned long)(BAR_HOLD_MS + BAR_FADE_MS)) {
    barVisible = false;
    return;
  }

  if (elapsed > (unsigned long)BAR_HOLD_MS) {
    unsigned long fadeElapsed = elapsed - BAR_HOLD_MS;
    int period = 60;
    int onTime = period - (int)(period * fadeElapsed / BAR_FADE_MS);
    barBlink++;
    if ((barBlink * 20) % period > onTime) return;
  }

  int segW = 128 / 3;
  int x0 = currentMode * segW + 4;
  display.fillRect(x0, 62, segW - 8, 2, WHITE);
}

// ─────────────────────────────────────────────────────────────────────────────
// Data parsing
// ─────────────────────────────────────────────────────────────────────────────
void parseData(const String& data) {
  auto extract = [&](const String& key) -> String {
    int i = data.indexOf(key + ":");
    if (i == -1) return "";
    int start = i + key.length() + 1;
    int end = data.indexOf(",", start);
    if (end == -1) end = data.indexOf("|", start);
    return end == -1 ? data.substring(start) : data.substring(start, end);
  };

  String type = extract("TYPE");

  if (type == "MONITOR") {
    cpu = extract("CPU");
    ram = extract("RAM");
    gpu = extract("GPU");
  } else if (type == "CLOCK") {
    timeStr    = extract("TIME");
    dateStr    = extract("DATE");
    weatherTemp = extract("TEMP");
    weatherDesc = extract("DESC");
  } else if (type == "REMINDER") {
    reminderCount = extract("COUNT").toInt();
    for (int i = 0; i < reminderCount && i < 5; i++)
      reminders[i] = extract("R" + String(i));

  // ── AI state updates from Python ──────────────────────────────────────────
  } else if (type == "AI_STATE") {
    aiState = extract("STATE");
    if (aiState == "IDLE") {
      aiAnswer     = "";
      answerScroll = 0;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Button handling
// ─────────────────────────────────────────────────────────────────────────────
void checkButton() {
  // Original mode-cycle button (only active in normal mode)
  bool state = digitalRead(BUTTON_PIN);
  if (state == LOW && lastButtonState == HIGH) {
    if (millis() - lastButtonPress > DEBOUNCE_MS) {
      lastButtonPress = millis();
      if (!aiMode) {
        currentMode = (currentMode + 1) % 3;
        barVisible  = true;
        barStart    = millis();
        barBlink    = 0;
      }
    }
  }
  lastButtonState = state;

  // AI button — toggles AI mode on/off
  bool aiState2 = digitalRead(AI_BUTTON_PIN);
  if (aiState2 == LOW && lastAIButtonState == HIGH) {
    if (millis() - lastAIButtonPress > DEBOUNCE_MS) {
      lastAIButtonPress = millis();
      aiMode = !aiMode;
      if (aiMode) {
        // Entering AI mode — tell Python to start listening
        aiState      = "IDLE";
        aiAnswer     = "";
        answerScroll = 0;
        CompositeSerial.println("AI_BTN:ON");
      } else {
        // Leaving AI mode — tell Python to stop
        CompositeSerial.println("AI_BTN:OFF");
        aiState = "IDLE";
      }
    }
  }
  lastAIButtonState = aiState2;
}

// ─────────────────────────────────────────────────────────────────────────────
// Setup & Loop
// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  USBComposite.setProductString("STM32 Monitor");
  CompositeSerial.begin();
  USBComposite.begin();
  pinMode(BUTTON_PIN,    INPUT_PULLUP);
  pinMode(AI_BUTTON_PIN, INPUT_PULLUP);   // NEW button
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.clearDisplay();
  display.setTextColor(WHITE);
  display.display();
}

void loop() {
  if (CompositeSerial.available()) {
    String data = CompositeSerial.readStringUntil('\n');
    if (data.length() > 0) parseData(data);
  }

  checkButton();

  display.clearDisplay();
  display.setTextSize(1);

  if (aiMode) {
    // ── AI mode display ──────────────────────────────────────────────────────
    if      (aiState == "LISTENING") renderAIListening();
    else if (aiState == "THINKING")  renderAIThinking();
    else if (aiState == "SPEAKING")  renderAISpeaking();
    else                             renderAIIdle();
  } else {
    // ── Normal mode display ──────────────────────────────────────────────────
    switch (currentMode) {
      case 0: renderMonitor();   break;
      case 1: renderClock();     break;
      case 2: renderReminders(); break;
    }
    drawIndicatorBar();
  }

  display.display();
  delay(10);
}
