/*
 * ============================================================
 *  BazaMops Walkie-Talkie Firmware
 *  Target : ESP32 D1 Mini (LOLIN / Wemos)
 *
 *  Features:
 *    - WiFi auto-connect + auto-reconnect
 *    - REST heartbeat + clock in/out
 *    - PTT: INMP441 mic → I2S → WebSocket stream
 *    - Incoming audio from WebSocket → I2S DAC speaker
 *    - LED status: green (connected), red (error), yellow (PTT / channel blink)
 *    - Channel change button: cycles to next PTT channel
 *      Yellow LED blinks N times to confirm channel number
 *
 *  Required libraries (Arduino Library Manager):
 *    - ArduinoJson      v6+  by Benoit Blanchon
 *    - WebSockets       by Markus Sattler  (arduinoWebSockets)
 *
 *  !! Before flashing: fill in CONFIGURATION section below !!
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <driver/i2s.h>

// ─── CONFIGURATION ───────────────────────────────────────────────────────────

#define WIFI_SSID      "YourWiFiSSID"
#define WIFI_PASSWORD  "YourWiFiPassword"

// Device credentials — copy from Dashboard → Urządzenia
#define DEVICE_ID      "radio_1"
#define API_SECRET     "paste_api_secret_here"

// REST API base URL (no trailing slash)
//   Local:  "http://192.168.1.100:5000"
//   Replit: "https://yourapp.replit.app"
#define API_HOST       "http://192.168.1.100:5000"

// WebSocket server
//   Local:  WS_HOST "192.168.1.100", WS_PORT 5000,  WS_USE_SSL false
//   Replit: WS_HOST "yourapp.replit.app", WS_PORT 443, WS_USE_SSL true
#define WS_HOST        "192.168.1.100"
#define WS_PORT        5000
#define WS_PATH        "/ws/audio"
#define WS_USE_SSL     false

// ─── PIN DEFINITIONS ─────────────────────────────────────────────────────────
//
// IMPORTANT: The Dx labels below map to the following GPIO numbers on the most
// common LOLIN/Wemos D1 Mini ESP32 (32-pin) variant:
//
//   D2 = GPIO21,  D3 = GPIO17,  D4 = GPIO16
//   D5 = GPIO18,  D6 = GPIO19,  D7 = GPIO23
//
// If your board differs, change the GPIO numbers here accordingly.
// Note: GPIO18/19/22 are also used by I2S speaker — do NOT reuse them for LEDs.
//
//   Verified conflict-free mapping (for boards where D5/D6/D7 ≠ 18/19/22):
//     D5 = GPIO14, D6 = GPIO12, D7 = GPIO13  ← set below

#define PIN_BTN_CLOCK_IN    21   // D2 — Clock In  button  (INPUT_PULLUP)
#define PIN_BTN_CLOCK_OUT   17   // D3 — Clock Out button  (INPUT_PULLUP)
#define PIN_BTN_PTT         16   // D4 — PTT button        (INPUT_PULLUP)
#define PIN_LED_GREEN       14   // D5 — Green LED  (WiFi/online)
#define PIN_LED_RED         12   // D6 — Red LED    (error)
#define PIN_LED_YELLOW      13   // D7 — Yellow LED (PTT active / channel confirm)
#define PIN_BTN_CHANNEL     27   // D8 / GPIO27 — Channel change button (INPUT_PULLUP)
//
// Channel change: press once → POST /api/channel/next → yellow blinks N times
// where N = channel order_index + 1 (channel 0 blinks 1×, channel 1 blinks 2×, …)

// ─── I2S MICROPHONE  –  INMP441 (input, I2S_NUM_0) ───────────────────────────
#define I2S_MIC_PORT   I2S_NUM_0
#define I2S_MIC_BCK    26        // Bit Clock
#define I2S_MIC_WS     25        // Word Select (L/R)
#define I2S_MIC_SD     33        // Serial Data

// ─── I2S SPEAKER  –  MAX98357 / UDA1334A / PCM5102 (output, I2S_NUM_1) ───────
#define I2S_SPK_PORT   I2S_NUM_1
#define I2S_SPK_BCLK   19        // Bit Clock
#define I2S_SPK_LRC    18        // L/R Clock
#define I2S_SPK_DOUT   22        // Data Out

// ─── AUDIO SETTINGS ──────────────────────────────────────────────────────────
#define SAMPLE_RATE     16000    // Hz
#define MIC_BUF_FRAMES  256      // 32-bit frames per I2S read  (INMP441 → 32-bit)
#define SPK_BUF_BYTES   512      // bytes per I2S write

// ─── TIMING ──────────────────────────────────────────────────────────────────
#define HEARTBEAT_MS    30000UL  // 30 s
#define WIFI_RETRY_MS   10000UL  // 10 s between reconnect attempts
#define DEBOUNCE_MS       300UL  // button debounce

// ─────────────────────────────────────────────────────────────────────────────

// Global objects & state
WebSocketsClient wsClient;

bool wsConnected    = false;
bool pttActive      = false;

unsigned long lastHeartbeat  = 0;
unsigned long lastWifiRetry  = 0;
unsigned long lastBtnIn      = 0;
unsigned long lastBtnOut     = 0;
unsigned long lastBtnPTT     = 0;
unsigned long lastBtnChannel = 0;

int currentChannelOrder = 0;  // Updated when server responds to /api/channel/next

// Audio buffers
int32_t micRaw[MIC_BUF_FRAMES];     // raw 32-bit from INMP441
int16_t micPCM[MIC_BUF_FRAMES];     // downconverted 16-bit for WebSocket

// ─────────────────────────────────────────────────────────────────────────────
//  SETUP
// ─────────────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[MOPS] Booting walkie-talkie firmware...");

  // Outputs & inputs
  pinMode(PIN_BTN_CLOCK_IN,  INPUT_PULLUP);
  pinMode(PIN_BTN_CLOCK_OUT, INPUT_PULLUP);
  pinMode(PIN_BTN_PTT,       INPUT_PULLUP);
  pinMode(PIN_BTN_CHANNEL,   INPUT_PULLUP);
  pinMode(PIN_LED_GREEN,     OUTPUT);
  pinMode(PIN_LED_RED,       OUTPUT);
  pinMode(PIN_LED_YELLOW,    OUTPUT);
  ledSet(PIN_LED_GREEN,  false);
  ledSet(PIN_LED_RED,    false);
  ledSet(PIN_LED_YELLOW, false);

  wifiConnect();
  i2sSetupMic();
  i2sSetupSpeaker();
  wsSetup();

  Serial.println("[MOPS] Ready.");
}

// ─────────────────────────────────────────────────────────────────────────────
//  LOOP
// ─────────────────────────────────────────────────────────────────────────────

void loop() {
  unsigned long now = millis();

  // ── WiFi watchdog ─────────────────────────────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    ledSet(PIN_LED_GREEN, false);
    // Blink red every 1 s to signal disconnection
    static unsigned long lastBlink = 0;
    static bool blinkState = false;
    if (now - lastBlink >= 1000) {
      lastBlink  = now;
      blinkState = !blinkState;
      ledSet(PIN_LED_RED, blinkState);
    }
    // Attempt reconnect every WIFI_RETRY_MS
    if (now - lastWifiRetry >= WIFI_RETRY_MS) {
      lastWifiRetry = now;
      Serial.println("[WiFi] Reconnecting...");
      WiFi.reconnect();
    }
    return;  // Skip everything else while offline
  }

  // WiFi OK
  ledSet(PIN_LED_RED,   false);
  ledSet(PIN_LED_GREEN, true);

  // ── WebSocket tick (must call every loop) ─────────────────────────────────
  wsClient.loop();

  // ── Heartbeat ─────────────────────────────────────────────────────────────
  if (now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    if (!apiHeartbeat()) {
      blinkLed(PIN_LED_RED, 2);
    }
  }

  // ── Clock In button (D2) ──────────────────────────────────────────────────
  if (digitalRead(PIN_BTN_CLOCK_IN) == LOW && now - lastBtnIn > DEBOUNCE_MS) {
    lastBtnIn = now;
    Serial.println("[BTN] Clock IN");
    bool ok = apiClock("clock_in");
    blinkLed(ok ? PIN_LED_GREEN : PIN_LED_RED, ok ? 1 : 3);
  }

  // ── Clock Out button (D3) ─────────────────────────────────────────────────
  if (digitalRead(PIN_BTN_CLOCK_OUT) == LOW && now - lastBtnOut > DEBOUNCE_MS) {
    lastBtnOut = now;
    Serial.println("[BTN] Clock OUT");
    bool ok = apiClock("clock_out");
    blinkLed(ok ? PIN_LED_GREEN : PIN_LED_RED, ok ? 1 : 3);
  }

  // ── Channel change button (D8/GPIO27) ─────────────────────────────────────
  if (digitalRead(PIN_BTN_CHANNEL) == LOW && now - lastBtnChannel > DEBOUNCE_MS) {
    lastBtnChannel = now;
    Serial.println("[BTN] Channel change");
    apiChannelNext();
  }

  // ── PTT button (D4) ───────────────────────────────────────────────────────
  bool pttDown = (digitalRead(PIN_BTN_PTT) == LOW);

  if (pttDown && !pttActive && now - lastBtnPTT > DEBOUNCE_MS) {
    lastBtnPTT = now;
    pttStart();
  } else if (!pttDown && pttActive) {
    pttStop();
  }

  // ── Mic → WebSocket stream while PTT held ─────────────────────────────────
  if (pttActive && wsConnected) {
    pttStreamMic();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  PTT
// ─────────────────────────────────────────────────────────────────────────────

void pttStart() {
  pttActive = true;
  ledSet(PIN_LED_YELLOW, true);
  Serial.println("[PTT] TX start");
  if (wsConnected) {
    wsClient.sendTXT("START");
  }
}

void pttStop() {
  pttActive = false;
  ledSet(PIN_LED_YELLOW, false);
  Serial.println("[PTT] TX end");
  if (wsConnected) {
    wsClient.sendTXT("END");
  }
}

/*
 * Read one chunk from the INMP441 and send as binary WebSocket frame.
 * INMP441 outputs 32-bit samples (18-bit MSB-aligned).
 * We downconvert to 16-bit signed PCM before sending.
 */
void pttStreamMic() {
  size_t bytesRead = 0;
  esp_err_t err = i2s_read(
    I2S_MIC_PORT,
    (void*)micRaw,
    sizeof(micRaw),
    &bytesRead,
    pdMS_TO_TICKS(10)
  );

  if (err != ESP_OK || bytesRead == 0) return;

  // Downconvert 32-bit → 16-bit (INMP441 data is in bits [31:14])
  size_t frames = bytesRead / sizeof(int32_t);
  for (size_t i = 0; i < frames; i++) {
    micPCM[i] = (int16_t)(micRaw[i] >> 14);
  }

  wsClient.sendBIN((uint8_t*)micPCM, frames * sizeof(int16_t));
}

// ─────────────────────────────────────────────────────────────────────────────
//  WEBSOCKET
// ─────────────────────────────────────────────────────────────────────────────

void wsSetup() {
  wsClient.onEvent(wsEvent);
  // Send device credentials as headers on handshake
  wsClient.setExtraHeaders(
    "X-Device-ID: " DEVICE_ID "\r\n"
    "X-API-Secret: " API_SECRET
  );
  wsClient.setReconnectInterval(5000);

  if (WS_USE_SSL) {
    wsClient.beginSSL(WS_HOST, WS_PORT, WS_PATH);
  } else {
    wsClient.begin(WS_HOST, WS_PORT, WS_PATH);
  }

  Serial.printf("[WS] Connecting to ws%s://%s:%d%s\n",
                WS_USE_SSL ? "s" : "", WS_HOST, WS_PORT, WS_PATH);
}

void wsEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {

    case WStype_CONNECTED:
      wsConnected = true;
      Serial.printf("[WS] Connected to %s%s\n", WS_HOST, WS_PATH);
      break;

    case WStype_DISCONNECTED:
      wsConnected = false;
      if (pttActive) pttStop();
      Serial.println("[WS] Disconnected — will retry");
      break;

    case WStype_TEXT: {
      // Server sends "AUDIO_START" / "AUDIO_END" to announce incoming audio
      String msg = String((char*)payload);
      Serial.printf("[WS] Text: %s\n", msg.c_str());
      break;
    }

    case WStype_BIN:
      // Incoming binary = PCM audio from another device → play on speaker
      if (length > 0) {
        speakerPlay(payload, length);
      }
      break;

    case WStype_ERROR:
      Serial.printf("[WS] Error (len=%u)\n", (unsigned)length);
      break;

    default:
      break;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  I2S SETUP
// ─────────────────────────────────────────────────────────────────────────────

void i2sSetupMic() {
  // INMP441 outputs 32-bit I2S frames (18-bit signed audio in MSB)
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,  // INMP441 is mono, L channel
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 4,
    .dma_buf_len          = MIC_BUF_FRAMES,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num   = I2S_MIC_BCK,
    .ws_io_num    = I2S_MIC_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_MIC_SD
  };
  i2s_driver_install(I2S_MIC_PORT, &cfg, 0, NULL);
  i2s_set_pin(I2S_MIC_PORT, &pins);
  i2s_zero_dma_buffer(I2S_MIC_PORT);
  Serial.println("[I2S] Microphone (INMP441) ready — BCK=" xstr(I2S_MIC_BCK)
                 " WS=" xstr(I2S_MIC_WS) " SD=" xstr(I2S_MIC_SD));
}

void i2sSetupSpeaker() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_RIGHT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 4,
    .dma_buf_len          = SPK_BUF_BYTES / 2,
    .use_apll             = false,
    .tx_desc_auto_clear   = true,   // fill with zeros on underrun
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num   = I2S_SPK_BCLK,
    .ws_io_num    = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DOUT,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };
  i2s_driver_install(I2S_SPK_PORT, &cfg, 0, NULL);
  i2s_set_pin(I2S_SPK_PORT, &pins);
  i2s_zero_dma_buffer(I2S_SPK_PORT);
  Serial.println("[I2S] Speaker ready — BCLK=" xstr(I2S_SPK_BCLK)
                 " LRC=" xstr(I2S_SPK_LRC) " DOUT=" xstr(I2S_SPK_DOUT));
}

void speakerPlay(uint8_t* pcm16, size_t len) {
  size_t written = 0;
  i2s_write(I2S_SPK_PORT, pcm16, len, &written, pdMS_TO_TICKS(20));
}

// ─────────────────────────────────────────────────────────────────────────────
//  HTTP API
// ─────────────────────────────────────────────────────────────────────────────

bool apiHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  http.begin(API_HOST "/api/device/heartbeat");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<96> doc;
  doc["device_id"] = DEVICE_ID;
  doc["secret"]    = API_SECRET;
  String body;
  serializeJson(doc, body);

  int code = http.POST(body);
  bool ok  = (code == 200);
  Serial.printf("[HB] %s (HTTP %d)\n", ok ? "ok" : "fail", code);
  http.end();
  return ok;
}

bool apiClock(const char* action) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  http.begin(API_HOST "/api/clock");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(8000);

  StaticJsonDocument<128> doc;
  doc["device_id"] = DEVICE_ID;
  doc["secret"]    = API_SECRET;
  doc["action"]    = action;
  String body;
  serializeJson(doc, body);

  int code = http.POST(body);
  bool ok  = (code == 200);

  if (code > 0) {
    Serial.printf("[Clock/%s] HTTP %d – %s\n",
                  action, code, http.getString().c_str());
  } else {
    Serial.printf("[Clock/%s] Error: %s\n",
                  action, http.errorToString(code).c_str());
  }
  http.end();
  return ok;
}

/*
 * Request the server to cycle this device to the next audio channel.
 * Server responds with { channel_name, channel_order }.
 * Yellow LED blinks (channel_order + 1) times to confirm the new channel.
 */
void apiChannelNext() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(API_HOST "/api/channel/next");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(6000);

  StaticJsonDocument<96> doc;
  doc["device_id"] = DEVICE_ID;
  doc["secret"]    = API_SECRET;
  String body;
  serializeJson(doc, body);

  int code = http.POST(body);
  if (code == 200) {
    String resp = http.getString();
    StaticJsonDocument<128> res;
    if (!deserializeJson(res, resp)) {
      const char* chName = res["channel_name"] | "?";
      int chOrder        = res["channel_order"] | 0;
      currentChannelOrder = chOrder;
      Serial.printf("[CH] → %s (order %d)\n", chName, chOrder);
      // Blink yellow N = order+1 times (min 1, max 8 to stay responsive)
      int blinks = constrain(chOrder + 1, 1, 8);
      blinkChannelConfirm(blinks);
    }
  } else {
    Serial.printf("[CH] Error HTTP %d\n", code);
    blinkLed(PIN_LED_RED, 2);
  }
  http.end();
}

/*
 * Blink yellow LED N times with a longer pause between groups,
 * used specifically for channel confirmation.
 * (Separate from blinkLed to use a distinct timing pattern.)
 */
void blinkChannelConfirm(int n) {
  bool prevGreen = digitalRead(PIN_LED_GREEN);
  for (int i = 0; i < n; i++) {
    ledSet(PIN_LED_YELLOW, true);
    delay(200);
    ledSet(PIN_LED_YELLOW, false);
    delay(150);
  }
  // Restore green
  if (WiFi.status() == WL_CONNECTED) {
    ledSet(PIN_LED_GREEN, prevGreen);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  WiFi
// ─────────────────────────────────────────────────────────────────────────────

void wifiConnect() {
  Serial.printf("[WiFi] Connecting to SSID: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Blink green while waiting (up to 10 s)
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    ledSet(PIN_LED_GREEN, i % 2 == 0);
    delay(250);
  }

  if (WiFi.status() == WL_CONNECTED) {
    ledSet(PIN_LED_GREEN, true);
    Serial.printf("[WiFi] Connected  IP: %s\n",
                  WiFi.localIP().toString().c_str());
  } else {
    ledSet(PIN_LED_GREEN, false);
    Serial.println("[WiFi] Could not connect on startup — will retry in loop");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  LED HELPERS
// ─────────────────────────────────────────────────────────────────────────────

inline void ledSet(int pin, bool on) {
  digitalWrite(pin, on ? HIGH : LOW);
}

/*
 * Blink `pin` for `times` short pulses.
 * Restores the original state of PIN_LED_GREEN afterwards
 * so the solid-green "connected" light is not permanently lost.
 */
void blinkLed(int pin, int times) {
  bool prevGreen = digitalRead(PIN_LED_GREEN);
  for (int i = 0; i < times; i++) {
    ledSet(pin, true);
    delay(120);
    ledSet(pin, false);
    delay(100);
  }
  // Restore green if we blinked something else and WiFi is up
  if (pin != PIN_LED_GREEN && WiFi.status() == WL_CONNECTED) {
    ledSet(PIN_LED_GREEN, prevGreen);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Stringify helpers for Serial.println pin numbers
// ─────────────────────────────────────────────────────────────────────────────
#define xstr(s) str(s)
#define str(s) #s

/*
 * ============================================================
 *  REST API Reference
 * ============================================================
 *
 *  POST /api/device/heartbeat  { device_id, secret }
 *    → { ok: true }
 *
 *  POST /api/clock             { device_id, secret, action:"clock_in"|"clock_out" }
 *    → { ok, action, clock_in_time }  or  { ok, points_earned, hours }
 *
 *  POST /api/channel/next      { device_id, secret }
 *    → { ok, channel_id, channel_name, channel_order }
 *    Yellow LED blinks (channel_order + 1) times to confirm.
 *
 * ============================================================
 *  WebSocket Audio Protocol  /ws/audio
 * ============================================================
 *
 *  Authentication via HTTP headers on handshake:
 *    X-Device-ID: <DEVICE_ID>
 *    X-API-Secret: <API_SECRET>
 *
 *  On connect server sends:
 *    JSON  {"type":"connected","channel_id":N,"device_id":"..."}
 *
 *  Client → Server:
 *    TEXT  "START"          — device starts transmitting
 *    BIN   <PCM16 chunk>    — mono 16-bit signed, 16 kHz, little-endian
 *    TEXT  "END"            — device finished transmitting
 *
 *  Server → Client (forwarded from other devices on same channel):
 *    JSON  {"type":"AUDIO_START","from":"device_id"}
 *    BIN   <PCM16 chunk>    — same format
 *    JSON  {"type":"AUDIO_END","from":"device_id"}
 *
 *  Channel switch: call POST /api/channel/next → server reassigns device.
 *  The WS handler auto-detects the new channel on next message.
 * ============================================================
 */
