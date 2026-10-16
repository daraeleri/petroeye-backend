// ============================================================
// PETROEYE — SMART LIQUID DELIVERY VEHICLE FIRMWARE
//
//  1. Dabble Bluetooth vehicle control (Bluetooth Classic SPP)
//  2. GPS geofencing (local, fail-closed valve interlock)
//  3. Ultrasonic tank telemetry
//  4. Solenoid valve security
//  5. LCD telemetry
//  6. Cloud link to the PetroEye digital twin (Wi-Fi + MQTT/TLS)
//
// Board: original ESP32 (ESP32-WROOM-32 / DevKit V1). ESP32-S2/S3/C3
// have no Bluetooth Classic and cannot talk to Dabble's Classic mode.
// Arduino IDE: Tools → Partition Scheme → "Huge APP (3MB No OTA)"
// (Bluetooth + Wi-Fi + TLS don't fit the default 1.2 MB partition).
//
// Libraries: TinyGPSPlus, ESP32Servo, LiquidCrystal_I2C, PubSubClient.
// Copy secrets.example.h → secrets.h and fill it in.
// ============================================================

#include <Arduino.h>
#include <BluetoothSerial.h>
#include <ESP32Servo.h>
#include <LiquidCrystal_I2C.h>
#include <TinyGPS++.h>
#include <Wire.h>
#if __has_include(<esp_mac.h>)
#include <esp_mac.h>  // Arduino-ESP32 core 3.x
#endif
#include <esp_system.h>
#include <math.h>

#include "cloud_link.h"
#include "config.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error "Bluetooth Classic is not available on this board. Use an original ESP32 (WROOM-32 / DevKit V1)."
#endif

// ============================================================
// HARDWARE OBJECTS
// ============================================================
BluetoothSerial SerialBT;
Servo steeringServo;
LiquidCrystal_I2C lcd(LCD_I2C_ADDRESS, 16, 2);
TinyGPSPlus gps;
HardwareSerial GPS_Serial(2);

char btName[40];
char deviceTag[8];  // last 4 hex digits of the MAC, e.g. "A1B2"

// ============================================================
// STATE
// ============================================================
enum GeoZone { GEO_NO_FIX, GEO_START, GEO_DESTINATION, GEO_EN_ROUTE };
enum MotionState { MOTOR_STOPPED, MOTOR_FORWARD, MOTOR_REVERSE };
enum Command {
  CMD_NONE, CMD_START, CMD_SELECT, CMD_FORWARD, CMD_REVERSE,
  CMD_LEFT, CMD_RIGHT, CMD_CLOSE_VALVE, CMD_OPEN_VALVE, CMD_RELEASE
};

GeoZone currentGeoZone = GEO_NO_FIX;
MotionState motionState = MOTOR_STOPPED;
bool controlSubsystemActive = false;
bool solenoidOpen = false;
bool forcedOpen = false;          // test mode only
volatile bool btConnected = false;

double currentLatitude = 0, currentLongitude = 0;
double distanceToStart = 0, distanceToDestination = 0;
bool gpsPositionAvailable = false;
unsigned long lastGPSPositionTime = 0;

float lastDistanceCm = 0;
float liquidHeightCm = 0, liquidVolumeMl = 0;
bool ultrasonicValid = false;

uint8_t packetBuffer[8];
int packetIndex = 0;

unsigned long lastValidBluetoothPacket = 0;
unsigned long lastUltrasonicMeasurement = 0;
unsigned long lastLCDUpdate = 0, lastLCDScroll = 0;
unsigned long triangleDownAt = 0;  // when TRIANGLE was pressed (test force-open)
unsigned long lastDeniedReport = 0;

int lcdPage = 0, lcdScrollPosition = 0;
const int LCD_PAGES = 6;

// ============================================================
// SNAPSHOT FOR THE CLOUD LINK
// ============================================================
TruckSnapshot makeSnapshot() {
  TruckSnapshot s;
  s.gpsFix = gpsPositionAvailable && currentGeoZone != GEO_NO_FIX;
  s.lat = currentLatitude;
  s.lon = currentLongitude;
  s.speedValid = gps.speed.isValid();
  s.speedKmh = gps.speed.kmph();
  s.courseValid = gps.course.isValid();
  s.courseDeg = gps.course.deg();
  s.sats = gps.satellites.isValid() ? gps.satellites.value() : 0;
  s.hdopValid = gps.hdop.isValid();
  s.hdop = gps.hdop.hdop();
  if (gps.date.isValid() && gps.time.isValid() && gps.date.year() >= 2024) {
    s.gpsTimeValid = true;
    s.gpsYear = gps.date.year();
    s.gpsMonth = gps.date.month();
    s.gpsDay = gps.date.day();
    s.gpsHour = gps.time.hour();
    s.gpsMinute = gps.time.minute();
    s.gpsSecond = gps.time.second();
    s.gpsCenti = gps.time.centisecond();
    s.gpsTimeAtMs = millis() - gps.time.age();
  }
  s.distanceValid = ultrasonicValid;
  s.distanceCm = lastDistanceCm;
  s.valveOpen = solenoidOpen;
  s.moving = motionState != MOTOR_STOPPED ||
             (s.gpsFix && s.speedValid && s.speedKmh > MOVING_SPEED_KMH);
  return s;
}

// ============================================================
// MOTORS / STEERING
// ============================================================
void closeSolenoid();

void stopMotors() {
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  digitalWrite(PIN_IN3, LOW);
  digitalWrite(PIN_IN4, LOW);
  motionState = MOTOR_STOPPED;
}

void moveForward() {
  closeSolenoid();  // never move with the valve open
  digitalWrite(PIN_IN1, HIGH);
  digitalWrite(PIN_IN2, LOW);
  digitalWrite(PIN_IN3, HIGH);
  digitalWrite(PIN_IN4, LOW);
  motionState = MOTOR_FORWARD;
}

void moveReverse() {
  closeSolenoid();
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, HIGH);
  digitalWrite(PIN_IN3, LOW);
  digitalWrite(PIN_IN4, HIGH);
  motionState = MOTOR_REVERSE;
}

void steerLeft() { steeringServo.write(STEERING_LEFT); }
void steerCenter() { steeringServo.write(STEERING_CENTER); }
void steerRight() { steeringServo.write(STEERING_RIGHT); }

// ============================================================
// VALVE
// ============================================================
void setValve(bool open) {
  if (open == solenoidOpen) return;
  digitalWrite(PIN_RELAY, open ? RELAY_ON : RELAY_OFF);
  solenoidOpen = open;
  if (!open) forcedOpen = false;
  cloudValveChanged();  // the dashboard sees valve changes immediately
  Serial.printf("[valve] %s\n", open ? "OPEN" : "CLOSED");
}

void closeSolenoid() { setValve(false); }

// Why an open request is refused (nullptr = allowed). The same reasons
// are sent to the dashboard in a "valve_open_denied" event.
const char* valveDenyReason() {
  if (!controlSubsystemActive) return "control_disabled";
  if (motionState != MOTOR_STOPPED) return "moving";
  if (!gpsPositionAvailable || currentGeoZone == GEO_NO_FIX) return "no_gps_fix";
  if (currentGeoZone != GEO_START && currentGeoZone != GEO_DESTINATION) return "outside_geofence";
  return nullptr;
}

void requestOpenValve() {
  const char* reason = valveDenyReason();
  if (reason == nullptr) {
    setValve(true);
    return;
  }
  closeSolenoid();
  Serial.printf("[valve] open DENIED: %s\n", reason);
  // One report per press (Dabble may repeat packets while a key is held).
  if (millis() - lastDeniedReport > 2000) {
    lastDeniedReport = millis();
    cloudValveDenied(reason, makeSnapshot());
  }
}

#if ENABLE_TEST_FORCE_OPEN
// Test only: force the valve open even outside a zone so the dashboard's
// "valve opened outside geofence" alert can be exercised.
void forceOpenValve() {
  if (!controlSubsystemActive || motionState != MOTOR_STOPPED) return;
  forcedOpen = true;
  setValve(true);
  Serial.println("[valve] TEST FORCE OPEN");
}
#endif

// ============================================================
// GPS
// ============================================================
void processGPS() {
  while (GPS_Serial.available() > 0) gps.encode(GPS_Serial.read());

  if (gps.location.isValid() && gps.location.isUpdated()) {
    currentLatitude = gps.location.lat();
    currentLongitude = gps.location.lng();
    lastGPSPositionTime = millis();
    gpsPositionAvailable = true;
  }

  if (!gpsPositionAvailable || millis() - lastGPSPositionTime > GPS_FIX_TIMEOUT_MS) {
    gpsPositionAvailable = false;
    currentGeoZone = GEO_NO_FIX;
    if (!forcedOpen) closeSolenoid();  // fail closed
    return;
  }

  distanceToStart = TinyGPSPlus::distanceBetween(currentLatitude, currentLongitude, START_LAT, START_LON);
  distanceToDestination = TinyGPSPlus::distanceBetween(currentLatitude, currentLongitude, DEST_LAT, DEST_LON);

  if (distanceToStart <= GEOFENCE_RADIUS_M) currentGeoZone = GEO_START;
  else if (distanceToDestination <= GEOFENCE_RADIUS_M) currentGeoZone = GEO_DESTINATION;
  else currentGeoZone = GEO_EN_ROUTE;

  if (currentGeoZone != GEO_START && currentGeoZone != GEO_DESTINATION && !forcedOpen) closeSolenoid();
}

// ============================================================
// ULTRASONIC + TANK VOLUME
// ============================================================
float getFilteredDistance() {
  float readings[US_SAMPLES];
  int valid = 0;
  for (int i = 0; i < US_SAMPLES; i++) {
    digitalWrite(PIN_US_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(PIN_US_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_US_TRIG, LOW);
    unsigned long duration = pulseIn(PIN_US_ECHO, HIGH, US_TIMEOUT_US);
    if (duration > 0) readings[valid++] = duration * 0.0343f / 2.0f;
    delay(12);  // let echoes die down (≥ 10 ms between pings)
  }
  if (valid == 0) return -1.0f;
  // insertion sort → median
  for (int i = 1; i < valid; i++) {
    float v = readings[i];
    int j = i - 1;
    while (j >= 0 && readings[j] > v) {
      readings[j + 1] = readings[j];
      j--;
    }
    readings[j + 1] = v;
  }
  return readings[valid / 2];
}

void updateTankTelemetry() {
  unsigned long now = millis();
  if (now - lastUltrasonicMeasurement < ULTRASONIC_INTERVAL_MS) return;
  lastUltrasonicMeasurement = now;

  float d = getFilteredDistance();
  // HC-SR04 can't see closer than ~2 cm; past the tank bottom is an error.
  if (d < 2.0f || d > SENSOR_TO_BOTTOM_CM + 1.0f) {
    ultrasonicValid = false;  // keep the last volume; don't pretend the tank is empty
    return;
  }
  ultrasonicValid = true;
  lastDistanceCm = d;

  const float R = TANK_RADIUS_CM;
  float h = SENSOR_TO_BOTTOM_CM - d;
  if (h < 0.20f) h = 0.0f;
  if (h > 2.0f * R) h = 2.0f * R;
  liquidHeightCm = h;

  float volume = 0.0f;
  if (h > 0.0f) {
    float c = constrain((R - h) / R, -1.0f, 1.0f);
    float rad = max(0.0f, 2.0f * R * h - h * h);
    volume = (R * R * acosf(c) - (R - h) * sqrtf(rad)) * TANK_LENGTH_CM;
  }
  liquidVolumeMl = constrain(volume, 0.0f, MAX_TANK_VOLUME_ML);
}

// ============================================================
// DABBLE
// ============================================================
bool isValidPacket(const uint8_t* p) {
  return p[0] == 0xFF && p[1] == 0x01 && p[2] == 0x01 && p[3] == 0x01 && p[4] == 0x02 && p[7] == 0x00;
}

Command decodeCommand(const uint8_t* p) {
  uint8_t b5 = p[5], b6 = p[6];
  if (b5 == 0x01 && b6 == 0x00) return CMD_START;
  if (b5 == 0x02 && b6 == 0x00) return CMD_SELECT;
  if (b5 == 0x10 && b6 == 0x00) return CMD_FORWARD;      // X
  if (b5 == 0x20 && b6 == 0x00) return CMD_REVERSE;      // SQUARE
  if (b5 == 0x00 && b6 == 0x04) return CMD_LEFT;
  if (b5 == 0x00 && b6 == 0x08) return CMD_RIGHT;
  if (b5 == 0x08 && b6 == 0x00) return CMD_CLOSE_VALVE;  // CIRCLE
  if (b5 == 0x04 && b6 == 0x00) return CMD_OPEN_VALVE;   // TRIANGLE
  if (b5 == 0x00 && b6 == 0x00) return CMD_RELEASE;
  return CMD_NONE;
}

void processCommand(Command cmd) {
  if (cmd == CMD_NONE) return;
  lastValidBluetoothPacket = millis();

  if (cmd == CMD_START) {
    controlSubsystemActive = true;
    return;
  }
  if (cmd == CMD_SELECT) {
    stopMotors();
    steerCenter();
    closeSolenoid();
    controlSubsystemActive = false;
    return;
  }
  if (!controlSubsystemActive) {
    // Still tell the dashboard someone tried to open the valve.
    if (cmd == CMD_OPEN_VALVE) requestOpenValve();
    return;
  }

  switch (cmd) {
    case CMD_FORWARD: moveForward(); break;
    case CMD_REVERSE: moveReverse(); break;
    case CMD_LEFT: steerLeft(); break;
    case CMD_RIGHT: steerRight(); break;
    case CMD_CLOSE_VALVE: closeSolenoid(); break;
    case CMD_OPEN_VALVE:
      if (triangleDownAt == 0) triangleDownAt = millis();
      requestOpenValve();
      break;
    case CMD_RELEASE:
#if ENABLE_TEST_FORCE_OPEN
      if (triangleDownAt && millis() - triangleDownAt >= FORCE_OPEN_HOLD_MS && !solenoidOpen) forceOpenValve();
#endif
      triangleDownAt = 0;
      stopMotors();
      steerCenter();
      break;
    default: break;
  }
}

void processBluetooth() {
  while (SerialBT.available() > 0) {
    uint8_t b = SerialBT.read();
    if (packetIndex == 0) {
      if (b == 0xFF) packetBuffer[packetIndex++] = b;  // sync on the start byte
      continue;
    }
    packetBuffer[packetIndex++] = b;
    if (packetIndex >= 8) {
      if (isValidPacket(packetBuffer)) processCommand(decodeCommand(packetBuffer));
      packetIndex = 0;
    }
  }
}

// Bluetooth connect/disconnect. A dropped phone link stops the truck at once
// instead of waiting for the motion timeout.
void btCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t*) {
  if (event == ESP_SPP_SRV_OPEN_EVT) {
    btConnected = true;
  } else if (event == ESP_SPP_CLOSE_EVT) {
    btConnected = false;
  }
}

// ============================================================
// SAFETY
// ============================================================
void motionSafety() {
  bool linkLost = !btConnected;
  bool stale = millis() - lastValidBluetoothPacket > MOTION_TIMEOUT_MS;
  if (motionState != MOTOR_STOPPED) {
    closeSolenoid();  // never discharge while moving
    if (linkLost || stale) {
      stopMotors();
      steerCenter();
    }
  }
  if (linkLost && controlSubsystemActive) {
    controlSubsystemActive = false;  // reconnect + START to drive again
    closeSolenoid();
  }
}

// ============================================================
// LCD
// ============================================================
String geoText() {
  String sats = gps.satellites.isValid() ? String(gps.satellites.value()) : "?";
  switch (currentGeoZone) {
    case GEO_START: return "START D:" + String(distanceToStart, 1) + "m SAT:" + sats;
    case GEO_DESTINATION: return "DEST D:" + String(distanceToDestination, 1) + "m SAT:" + sats;
    case GEO_EN_ROUTE: return "EN ROUTE SAT:" + sats;
    default: return "GPS:NO FIX SAT:" + sats;
  }
}

String pageText(int page) {
  switch (page) {
    case 0:
      return ultrasonicValid ? "VOLUME:" + String((int)liquidVolumeMl) + "mL HEIGHT:" + String(liquidHeightCm, 1) + "cm"
                             : "TANK SENSOR ERROR";
    case 1: return geoText();
    case 2:
      return String(controlSubsystemActive ? "CONTROL:ON " : "CONTROL:OFF ") +
             (motionState == MOTOR_FORWARD ? "FORWARD" : motionState == MOTOR_REVERSE ? "REVERSE" : "STOPPED");
    case 3: return String(solenoidOpen ? (forcedOpen ? "VALVE:FORCED OPEN" : "VALVE:OPEN") : "VALVE:CLOSED");
    case 4: return String("CLOUD:") + cloudStateText() + " SENT:" + String(cloudPublished());
    default: return String("BT:") + btName + (btConnected ? " CONNECTED" : " WAITING");
  }
}

void updateLCD() {
  unsigned long now = millis();
  if (now - lastLCDScroll < LCD_SCROLL_INTERVAL_MS) return;
  lastLCDScroll = now;

  String text = "                " + pageText(lcdPage) + "                ";
  if (lcdScrollPosition > (int)text.length() - 16) {
    lcdScrollPosition = 0;
    lcdPage = (lcdPage + 1) % LCD_PAGES;
    lcd.clear();
    return;
  }
  lcd.setCursor(0, 0);
  lcd.print(text.substring(lcdScrollPosition, lcdScrollPosition + 16));
  lcd.setCursor(0, 1);
  if (!btConnected) lcd.print("BT: NOT PAIRED  ");
  else lcd.print(controlSubsystemActive ? "CONTROL ENABLED " : "PRESS START     ");
  lcdScrollPosition++;
}

const char* resetReasonText() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "POWER ON";
    case ESP_RST_BROWNOUT: return "BROWNOUT!";  // supply sagged: check power wiring
    case ESP_RST_PANIC: return "CRASH";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "WATCHDOG";
    case ESP_RST_SW: return "SOFTWARE";
    case ESP_RST_EXT: return "RESET BTN";
    default: return "OTHER";
  }
}

// ============================================================
// SETUP / LOOP
// ============================================================
void setup() {
  // Safe outputs first: relay OFF before anything else initialises.
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, RELAY_OFF);
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  stopMotors();
  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  digitalWrite(PIN_US_TRIG, LOW);

  Serial.begin(115200);
  delay(50);

  steeringServo.attach(PIN_SERVO);
  steerCenter();

  Wire.begin(PIN_LCD_SDA, PIN_LCD_SCL);
  lcd.init();
  lcd.backlight();
  lcd.clear();

  // Unique Bluetooth name per board.
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_BT);
  snprintf(deviceTag, sizeof(deviceTag), "%02X%02X", mac[4], mac[5]);
  snprintf(btName, sizeof(btName), "%s-%s", BT_NAME_PREFIX, deviceTag);

  Serial.printf("\nPetroEye %s fw %s | chip %s rev %d | PSRAM %u B | reset: %s\n", TRUCK_ID, FIRMWARE_VERSION,
                ESP.getChipModel(), ESP.getChipRevision(), (unsigned)ESP.getPsramSize(), resetReasonText());
  if (ESP.getPsramSize() > 0 && (PIN_GPS_RX == 16 || PIN_GPS_TX == 17)) {
    Serial.println("WARNING: PSRAM board — GPIO16/17 belong to PSRAM. Move the GPS to GPIO4/33.");
  }

  lcd.setCursor(0, 0);
  lcd.print("RESET:");
  lcd.print(resetReasonText());
  lcd.setCursor(0, 1);
  lcd.print(deviceTag);
  lcd.print(" ");
  lcd.print(TRUCK_ID);

  SerialBT.register_callback(btCallback);
  if (!SerialBT.begin(btName)) {
    Serial.println("Bluetooth init FAILED");
    lcd.clear();
    lcd.print("BT INIT FAILED");
  } else {
    Serial.printf("Bluetooth ready: %s\n", btName);
  }

  GPS_Serial.begin(GPS_BAUD, SERIAL_8N1, PIN_GPS_RX, PIN_GPS_TX);
  cloudBegin(deviceTag);

  delay(2500);  // keep the boot screen readable
  lcd.clear();
}

void loop() {
  processBluetooth();
  processGPS();
  updateTankTelemetry();
  motionSafety();
  cloudUpdate(makeSnapshot());
  updateLCD();
}
