// === Seeeduino (SDA=A4, SCL=A5) + DHT22 + SSD1306 OLED ===
// DHT22 on A9
// Heater:  A7 (LED) + A8 (relay)  : ON below 20°C, OFF at/above 24°C
// Fan:     A2 (LED) + A3 (relay)  : ON at/above 60% RH, OFF below 60% RH
// OLED on I2C (A4/A5). Serial prints full status every ~2 s.

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>

// ----- Pins -----
#define DHTPIN          A9
#define DHTTYPE         DHT22

#define LED_HEAT_PIN    A7
#define RELAY_HEAT_PIN  A8
#define LED_FAN_PIN     A2   // moved off A5 (I2C SCL)
#define RELAY_FAN_PIN   A3   // moved to keep A4/A5 free for I2C


// ----- OLED -----
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET    -1
#define OLED_ADDR1    0x3C
#define OLED_ADDR2    0x3D
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ----- Globals -----
DHT dht(DHTPIN, DHTTYPE);
bool heaterOn = false;
bool fanOn    = false;

// --- protocol state ---
bool autoMode = true;  // true=AUTO, false=MANUAL

// ----- Thresholds -----
float TEMP_ON_C  = 20.0;
float TEMP_OFF_C = 24.0;
float HUM_ON_RH  = 60.0;
float HUM_OFF_RH = 60.0;

// serial input buffer
String rxLine;



void sendStatus(float tC, bool tValid, float h, bool hValid) {
  Serial.print(F("STATUS,temp="));
  if (tValid) Serial.print(tC, 2); else Serial.print(F("nan"));
  Serial.print(F(",hum="));
  if (hValid) Serial.print(h, 2); else Serial.print(F("nan"));
  Serial.print(F(",heater=")); Serial.print(heaterOn ? 1 : 0);
  Serial.print(F(",fan="));    Serial.print(fanOn ? 1 : 0);
  Serial.print(F(",mode="));   Serial.print(autoMode ? F("AUTO") : F("MANUAL"));
  Serial.print(F(",temp_on="));  Serial.print(TEMP_ON_C, 2);
  Serial.print(F(",temp_off=")); Serial.print(TEMP_OFF_C, 2);
  Serial.print(F(",hum_on="));   Serial.print(HUM_ON_RH, 2);
  Serial.print(F(",hum_off="));  Serial.println(HUM_OFF_RH, 2);
}

void handleCommand(const String &line, float tC, bool tValid, float h, bool hValid) {
  // Commands:
  // GET
  // MODE,AUTO|MANUAL
  // SET,heater,0|1
  // SET,fan,0|1
  // SETPT,<name>,<value>   (temp_on,temp_off,hum_on,hum_off)

  if (line.equalsIgnoreCase(F("GET"))) {
    sendStatus(tC, tValid, h, hValid);
    return;
  }

  if (line.startsWith(F("MODE,"))) {
    String m = line.substring(5); m.trim(); m.toUpperCase();
    if (m == F("AUTO"))   autoMode = true;
    if (m == F("MANUAL")) autoMode = false;
    sendStatus(tC, tValid, h, hValid);
    return;
  }

  if (line.startsWith(F("SET,"))) {
    // SET,heater,1
    int c1 = line.indexOf(',', 4);
    if (c1 > 0) {
      String dev = line.substring(4, c1); dev.toLowerCase();
      String val = line.substring(c1 + 1); val.trim();
      bool on = (val == F("1"));
      if (dev == F("heater")) heaterOn = on;
      if (dev == F("fan"))    fanOn = on;
      autoMode = false; // switch to MANUAL when a SET occurs
      applyOutputs();
      sendStatus(tC, tValid, h, hValid);
    }
    return;
  }

  if (line.startsWith(F("SETPT,"))) {
    // SETPT,temp_on,19.5
    int c1 = line.indexOf(',', 6);
    if (c1 > 0) {
      String name = line.substring(6, c1); name.toLowerCase();
      String sval = line.substring(c1 + 1); sval.trim();
      float v = sval.toFloat();
      if (name == F("temp_on"))  TEMP_ON_C  = v;
      if (name == F("temp_off")) TEMP_OFF_C = v;
      if (name == F("hum_on"))   HUM_ON_RH  = v;
      if (name == F("hum_off"))  HUM_OFF_RH = v;
      sendStatus(tC, tValid, h, hValid);
    }
    return;
  }
}



void applyOutputs() {
  // Invert RELAY_* writes here if your relays are active-LOW
  digitalWrite(LED_HEAT_PIN,    heaterOn ? HIGH : LOW);
  digitalWrite(RELAY_HEAT_PIN,  heaterOn ? HIGH : LOW);
  digitalWrite(LED_FAN_PIN,     fanOn    ? HIGH : LOW);
  digitalWrite(RELAY_FAN_PIN,   fanOn    ? HIGH : LOW);
}

void oledShow(float tC, bool tValid, float h, bool hValid) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(F("Env Monitor"));

  display.setTextSize(2);
  display.setCursor(0, 16);
  display.print(F("T: "));
  if (tValid) { display.print(tC, 1); display.print((char)247); display.print(F("C")); }
  else        { display.print(F("--.-C")); }

  display.setCursor(0, 40);
  display.print(F("H: "));
  if (hValid) { display.print(h, 1); display.print(F("%")); }
  else        { display.print(F("--.-%")); }

  display.setTextSize(1);
  display.setCursor(96, 0);
  display.print(heaterOn ? F("HEAT") : F("----"));
  display.setCursor(96, 10);
  display.print(fanOn ? F("FAN") : F("---"));

  display.display();
}

void setup() {
  pinMode(LED_HEAT_PIN,   OUTPUT);
  pinMode(RELAY_HEAT_PIN, OUTPUT);
  pinMode(LED_FAN_PIN,    OUTPUT);
  pinMode(RELAY_FAN_PIN,  OUTPUT);
  heaterOn = false;
  fanOn    = false;
  applyOutputs();

  Serial.begin(115200);
  delay(50);
  Serial.println(F("DHT22 + OLED (A4/A5 I2C) starting…"));

  pinMode(DHTPIN, INPUT_PULLUP);   // still add external 10k if needed
  dht.begin();
  delay(1500);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR1)) {
    Serial.println(F("OLED @0x3C not found, trying 0x3D…"));
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR2)) {
      Serial.println(F("SSD1306 init failed (check wiring/address)."));
    }
  }

  if (display.width() > 0) {
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 18);
    display.print(F("SmartHome"));
    display.setTextSize(1);
    display.setCursor(0, 44);
    display.print(F("DHT22 + OLED ready"));
    display.display();
    delay(1200);
  }
}

void loop() {
  float h = NAN, tC = NAN;
  for (int i = 0; i < 3; i++) {
    h  = dht.readHumidity();
    tC = dht.readTemperature();
    if (!isnan(h) && !isnan(tC)) break;
    delay(200);
  }

  bool tValid = !isnan(tC);
  bool hValid = !isnan(h);

  // --- control logic ---
  if (autoMode) {
    // temperature hysteresis
    if (!isnan(tC)) {
      if (!heaterOn && tC < TEMP_ON_C)   heaterOn = true;
      if (heaterOn  && tC >= TEMP_OFF_C) heaterOn = false;
    }
    // humidity threshold
    if (!isnan(h)) {
      if (!fanOn && h >= HUM_ON_RH) fanOn = true;
      if (fanOn  && h < HUM_OFF_RH) fanOn = false;
    }
  }
  // if MANUAL, heaterOn/fanOn are only changed by SET commands
  
  applyOutputs();

  Serial.print(F("Temp C: "));
  if (tValid) Serial.print(tC, 2); else Serial.print(F("invalid"));
  Serial.print(F(" | Hum %: "));
  if (hValid) Serial.print(h, 2); else Serial.print(F("invalid"));
  Serial.print(F(" | HEAT(A7/A8): "));
  Serial.print(heaterOn ? F("ON") : F("OFF"));
  Serial.print(F(" | FAN(A2/A3): "));
  Serial.println(fanOn ? F("ON") : F("OFF"));

  if (display.width() > 0) oledShow(tC, tValid, h, hValid);

  while (Serial.available()) {
  char c = (char)Serial.read();
  if (c == '\n' || c == '\r') {
    if (rxLine.length()) {
      handleCommand(rxLine, tC, tValid, h, hValid);
      rxLine = "";
    }
  } else {
    if (rxLine.length() < 200) rxLine += c;
  }
}

  delay(2000);
}
