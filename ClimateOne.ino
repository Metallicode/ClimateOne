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

// ----- Thresholds -----
const float TEMP_ON_C   = 20.0;  // heater ON below this
const float TEMP_OFF_C  = 24.0;  // heater OFF at/above this
const float HUM_ON_RH   = 60.0;  // fan ON at/above this
const float HUM_OFF_RH  = 60.0;  // fan OFF below this (set 58.0 for hysteresis)

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

  if (tValid) {
    if (!heaterOn && tC < TEMP_ON_C)   heaterOn = true;
    if (heaterOn  && tC >= TEMP_OFF_C) heaterOn = false;
  }
  if (hValid) {
    if (!fanOn && h >= HUM_ON_RH) fanOn = true;
    if (fanOn  && h < HUM_OFF_RH) fanOn = false;
  }

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

  delay(2000);
}
