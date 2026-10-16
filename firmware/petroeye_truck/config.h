// ============================================================
// PetroEye truck firmware — configuration
//
// Everything you may need to change per truck lives here.
// Secrets (Wi-Fi, MQTT password, CA certificate) go in secrets.h,
// which is NOT committed: copy secrets.example.h to secrets.h.
// ============================================================
#pragma once

// ------------------------------------------------------------
// Identity
// ------------------------------------------------------------
// Must match the truck registered in the dashboard and the MQTT
// topic petrotwin/<TRUCK_ID>/... (letters, digits, - and _ only).
#define TRUCK_ID "truck-001"
#define FIRMWARE_VERSION "1.0.0"

// Bluetooth name shown in Dabble. The last 4 hex digits of the board's
// MAC address are appended (e.g. "PetroEye-truck-001-A1B2"), so a
// replacement board never shares a name with an old one the phone
// still remembers.
#define BT_NAME_PREFIX "PetroEye-" TRUCK_ID

// ------------------------------------------------------------
// Pins (see docs/hardware-integration-guide.md, Appendix A of the report)
// ------------------------------------------------------------
// L298N motor driver (ENA/ENB jumpers ON, direction control only)
#define PIN_IN1 25
#define PIN_IN2 26
#define PIN_IN3 27
#define PIN_IN4 14

#define PIN_SERVO 18   // steering servo signal (servo powered from its own 6 V supply)
#define PIN_RELAY 32   // solenoid relay input, active-LOW

#define PIN_LCD_SDA 21
#define PIN_LCD_SCL 22
#define LCD_I2C_ADDRESS 0x27

// HC-SR04. ECHO outputs 5 V: it MUST go through a divider
// (e.g. 1 kΩ in series + 2 kΩ to GND) before reaching the ESP32.
//
// TRIG is on GPIO12 to match the existing wiring. GPIO12 is a boot
// "strapping" pin: if anything holds it HIGH at power-on, the ESP32
// selects 1.8 V flash and fails to boot or behaves erratically, and
// whether that happens differs from board to board. RECOMMENDED: move
// the TRIG wire to GPIO19 (free, no boot role) and set 19 here.
#define PIN_US_TRIG 12
#define PIN_US_ECHO 13

// NEO-6M GPS on UART2. NOTE: on ESP32-WROVER boards (with PSRAM)
// GPIO16/17 are wired to the PSRAM chip — use 4 (RX) / 33 (TX) instead.
#define PIN_GPS_RX 16  // ESP32 RX  <- GPS TX
#define PIN_GPS_TX 17  // ESP32 TX  -> GPS RX
#define GPS_BAUD 9600

// ------------------------------------------------------------
// Relay
// ------------------------------------------------------------
#define RELAY_ON LOW
#define RELAY_OFF HIGH

// ------------------------------------------------------------
// Steering (calibrate against the real linkage)
// ------------------------------------------------------------
#define STEERING_LEFT 75
#define STEERING_CENTER 90
#define STEERING_RIGHT 115

// ------------------------------------------------------------
// Tank (horizontal cylinder). Measure on the finished tank.
// In the dashboard, set the same calibration on the truck page:
//   shape = horizontal cylinder, diameter = 2 x TANK_RADIUS_CM,
//   length = TANK_LENGTH_CM,
//   sensor offset = SENSOR_TO_BOTTOM_CM - 2 x TANK_RADIUS_CM.
// ------------------------------------------------------------
#define TANK_RADIUS_CM 4.3f
#define TANK_LENGTH_CM 29.0f
#define SENSOR_TO_BOTTOM_CM 10.9f
#define MAX_TANK_VOLUME_ML 1500.0f
#define US_SAMPLES 5          // median of 5, as the device contract asks
#define US_TIMEOUT_US 3000UL  // 3 ms ≈ 50 cm round trip; the tank is < 12 cm

// ------------------------------------------------------------
// Geofence (local, fail-closed valve interlock)
//
// Create the SAME zones in the dashboard (Live map → + Geofence,
// assigned to this truck) so the cloud alerts agree with the truck.
//
// A NEO-6M is typically accurate to 2.5–5 m in open sky; a 1 m radius
// means the valve almost never opens. 8 m is a practical minimum.
// ------------------------------------------------------------
#define START_LAT 4.103175
#define START_LON 9.755538
#define DEST_LAT 4.103057
#define DEST_LON 9.755324
#define GEOFENCE_RADIUS_M 8.0
#define GPS_FIX_TIMEOUT_MS 5000UL

// ------------------------------------------------------------
// Test mode: force the valve open (for testing the cloud alerts)
//
// When enabled, HOLDING TRIANGLE for FORCE_OPEN_HOLD_MS and releasing
// opens the valve even OUTSIDE a geofence (the truck must still be
// stopped). The dashboard then raises a critical
// "valve opened outside geofence" alert. Keep this OFF in real use.
// ------------------------------------------------------------
#define ENABLE_TEST_FORCE_OPEN 0
#define FORCE_OPEN_HOLD_MS 3000UL

// ------------------------------------------------------------
// Timing
// ------------------------------------------------------------
#define ULTRASONIC_INTERVAL_MS 500UL
#define LCD_SCROLL_INTERVAL_MS 180UL
#define MOTION_TIMEOUT_MS 1500UL      // verify against Dabble's real packet rate

// Telemetry (device contract): every 3 s while moving or discharging,
// every 30 s while parked, immediately when the valve changes.
#define TELEMETRY_ACTIVE_MS 3000UL
#define TELEMETRY_IDLE_MS 30000UL
#define STATUS_INTERVAL_MS 30000UL
#define MOVING_SPEED_KMH 3.0

// ------------------------------------------------------------
// Cloud link (Wi-Fi + MQTT over TLS). Set to 0 to run Bluetooth-only.
// ------------------------------------------------------------
#define ENABLE_CLOUD 1
#define MQTT_TOPIC_PREFIX "petrotwin"
#define MQTT_KEEPALIVE_S 30
#define NTP_SERVER_1 "pool.ntp.org"
#define NTP_SERVER_2 "time.google.com"
