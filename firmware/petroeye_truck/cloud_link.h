// ============================================================
// Cloud link: Wi-Fi + NTP + MQTT over TLS to the PetroEye backend.
//
// Runs in its own FreeRTOS task on core 0, so a slow Wi-Fi join or a
// TLS handshake (1–3 s) can never freeze the control loop on core 1
// (motors, valve interlocks, Bluetooth commands).
//
// The control loop only hands over snapshots; it never waits on the
// network. Payloads follow docs/hardware-integration-guide.md (schema v2).
// ============================================================
#pragma once
#include <Arduino.h>

struct TruckSnapshot {
  // GPS
  bool gpsFix = false;      // recent, valid position
  double lat = 0, lon = 0;
  bool speedValid = false;
  float speedKmh = 0;
  bool courseValid = false;
  float courseDeg = 0;
  int sats = 0;
  bool hdopValid = false;
  float hdop = 0;
  // GPS clock (fallback when NTP isn't synced yet)
  bool gpsTimeValid = false;
  uint16_t gpsYear = 0;
  uint8_t gpsMonth = 0, gpsDay = 0, gpsHour = 0, gpsMinute = 0, gpsSecond = 0, gpsCenti = 0;
  uint32_t gpsTimeAtMs = 0;  // millis() when that GPS time was read
  // Tank + valve
  bool distanceValid = false;
  float distanceCm = 0;     // median ultrasonic distance (raw — the backend computes volume)
  bool valveOpen = false;
  bool moving = false;
};

enum class LinkState : uint8_t {
  Disabled,     // ENABLE_CLOUD 0 or secrets.h missing values
  NoWifi,
  NoTime,       // Wi-Fi up, waiting for NTP/GPS time
  NoBroker,     // connecting / reconnecting to MQTT
  Online,
};

void cloudBegin(const char* deviceTag);
void cloudUpdate(const TruckSnapshot& s);         // latest state; cheap, never blocks
void cloudValveChanged();                         // publish telemetry right away
void cloudValveDenied(const char* reason, const TruckSnapshot& s);  // alert the dashboard
LinkState cloudState();
const char* cloudStateText();
uint32_t cloudPublished();                        // telemetry messages sent (for the LCD)
