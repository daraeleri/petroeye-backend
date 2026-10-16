#include "cloud_link.h"

#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <sys/time.h>
#include <time.h>

#include "config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#define HAVE_SECRETS 1
#else
#define HAVE_SECRETS 0
#endif

// ------------------------------------------------------------
// Shared state (control loop on core 1 -> this task on core 0)
// ------------------------------------------------------------
static portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;
static TruckSnapshot g_snap;
static volatile bool g_valveChanged = false;
static volatile LinkState g_state = LinkState::Disabled;
static volatile uint32_t g_published = 0;

struct DeniedEvent {
  char reason[24];
  TruckSnapshot snap;
};
static QueueHandle_t g_denied = nullptr;

static char g_truckTopicBase[64];
static char g_clientId[48];

#if ENABLE_CLOUD && HAVE_SECRETS
static WiFiClientSecure g_tls;
static PubSubClient g_mqtt(g_tls);
#endif

// ------------------------------------------------------------
// Time: NTP when available, otherwise GPS time, otherwise none.
// The device contract requires a real UTC timestamp, so without one
// nothing is published (the backend would reject it anyway).
// ------------------------------------------------------------
static bool ntpSynced() {
  return time(nullptr) > 1700000000;  // after Nov 2023
}

static bool formatTimestamp(const TruckSnapshot& s, char* out, size_t n) {
  if (ntpSynced()) {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    struct tm t;
    gmtime_r(&tv.tv_sec, &t);
    snprintf(out, n, "%04d-%02d-%02dT%02d:%02d:%02d.%03ldZ", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour,
             t.tm_min, t.tm_sec, (long)(tv.tv_usec / 1000));
    return true;
  }
  if (s.gpsTimeValid && s.gpsYear >= 2024) {
    // GPS time + time elapsed since it was read.
    struct tm t = {};
    t.tm_year = s.gpsYear - 1900;
    t.tm_mon = s.gpsMonth - 1;
    t.tm_mday = s.gpsDay;
    t.tm_hour = s.gpsHour;
    t.tm_min = s.gpsMinute;
    t.tm_sec = s.gpsSecond;
    // mktime treats tm as local time; TZ is UTC on the ESP32 unless changed.
    time_t base = mktime(&t);
    uint32_t elapsed = millis() - s.gpsTimeAtMs + s.gpsCenti * 10;
    time_t sec = base + elapsed / 1000;
    struct tm u;
    gmtime_r(&sec, &u);
    snprintf(out, n, "%04d-%02d-%02dT%02d:%02d:%02d.%03luZ", u.tm_year + 1900, u.tm_mon + 1, u.tm_mday, u.tm_hour,
             u.tm_min, u.tm_sec, (unsigned long)(elapsed % 1000));
    return true;
  }
  return false;
}

// JSON helpers ("null" when a value is unknown, as the contract requires)
static void fmtNum(char* out, size_t n, bool valid, double v, int decimals) {
  if (!valid) {
    snprintf(out, n, "null");
  } else {
    snprintf(out, n, "%.*f", decimals, v);
  }
}

#if ENABLE_CLOUD && HAVE_SECRETS

static bool publish(const char* kind, const char* payload) {
  char topic[96];
  snprintf(topic, sizeof(topic), "%s/%s", g_truckTopicBase, kind);
  return g_mqtt.publish(topic, payload, false);
}

static bool publishTelemetry(const TruckSnapshot& s) {
  char ts[32];
  if (!formatTimestamp(s, ts, sizeof(ts))) return false;
  char lat[20], lon[20], spd[16], crs[16], hdop[12], dist[12];
  fmtNum(lat, sizeof(lat), s.gpsFix, s.lat, 6);
  fmtNum(lon, sizeof(lon), s.gpsFix, s.lon, 6);
  fmtNum(spd, sizeof(spd), s.gpsFix && s.speedValid, s.speedKmh, 1);
  fmtNum(crs, sizeof(crs), s.gpsFix && s.courseValid, s.courseDeg, 1);
  fmtNum(hdop, sizeof(hdop), s.gpsFix && s.hdopValid, s.hdop, 2);
  fmtNum(dist, sizeof(dist), s.distanceValid, s.distanceCm, 1);
  char json[384];
  snprintf(json, sizeof(json),
           "{\"schema_version\":2,\"truck_id\":\"%s\",\"ts\":\"%s\",\"gps_fix\":%s,\"lat\":%s,\"lon\":%s,"
           "\"speed_kmh\":%s,\"course_deg\":%s,\"sats\":%d,\"hdop\":%s,\"distance_cm\":%s,\"valve_open\":%s}",
           TRUCK_ID, ts, s.gpsFix ? "true" : "false", lat, lon, spd, crs, s.gpsFix ? s.sats : 0, hdop, dist,
           s.valveOpen ? "true" : "false");
  bool ok = publish("telemetry", json);
  if (ok) g_published = g_published + 1;
  return ok;
}

static bool publishStatus(const TruckSnapshot& s, bool online) {
  char ts[32];
  if (!formatTimestamp(s, ts, sizeof(ts))) return false;
  char json[256];
  snprintf(json, sizeof(json),
           "{\"schema_version\":2,\"truck_id\":\"%s\",\"ts\":\"%s\",\"online\":%s,\"firmware_version\":\"%s\","
           "\"rssi_dbm\":%d,\"uptime_s\":%lu}",
           TRUCK_ID, ts, online ? "true" : "false", FIRMWARE_VERSION, (int)WiFi.RSSI(),
           (unsigned long)(millis() / 1000));
  return publish("status", json);
}

static bool publishDenied(const DeniedEvent& e) {
  char ts[32];
  if (!formatTimestamp(e.snap, ts, sizeof(ts))) return false;
  char lat[20], lon[20];
  fmtNum(lat, sizeof(lat), e.snap.gpsFix, e.snap.lat, 6);
  fmtNum(lon, sizeof(lon), e.snap.gpsFix, e.snap.lon, 6);
  char json[256];
  snprintf(json, sizeof(json),
           "{\"schema_version\":2,\"truck_id\":\"%s\",\"ts\":\"%s\",\"type\":\"valve_open_denied\","
           "\"reason\":\"%s\",\"gps_fix\":%s,\"lat\":%s,\"lon\":%s}",
           TRUCK_ID, ts, e.reason, e.snap.gpsFix ? "true" : "false", lat, lon);
  return publish("event", json);
}

static bool connectMqtt() {
  // Last Will: the broker publishes this if the truck drops off without
  // saying goodbye. No "ts" — that's how the backend recognises it.
  char will[128];
  snprintf(will, sizeof(will), "{\"schema_version\":2,\"truck_id\":\"%s\",\"online\":false}", TRUCK_ID);
  char willTopic[96];
  snprintf(willTopic, sizeof(willTopic), "%s/status", g_truckTopicBase);
  return g_mqtt.connect(g_clientId, MQTT_USERNAME, MQTT_PASSWORD, willTopic, 1, false, will, true);
}

static void cloudTask(void*) {
  uint32_t lastWifiTry = 0, lastMqttTry = 0, wifiBackoff = 2000, mqttBackoff = 2000;
  uint32_t lastTelemetry = 0, lastStatus = 0;
  bool timeStarted = false, announced = false;

  WiFi.mode(WIFI_STA);
  // NOTE: never call WiFi.setSleep(false) here. With Bluetooth running the
  // ESP32 *requires* modem sleep so Wi-Fi and Bluetooth can share the radio.
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiTry = millis();

  g_tls.setCACert(MQTT_CA_CERT);
  g_tls.setHandshakeTimeout(15);
  g_mqtt.setServer(MQTT_HOST, MQTT_PORT);
  g_mqtt.setBufferSize(768);  // default 256 B is too small for a telemetry message
  g_mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  g_mqtt.setSocketTimeout(10);

  for (;;) {
    uint32_t now = millis();
    TruckSnapshot s;
    portENTER_CRITICAL(&g_mux);
    s = g_snap;
    portEXIT_CRITICAL(&g_mux);

    // --- Wi-Fi ---------------------------------------------------------
    if (WiFi.status() != WL_CONNECTED) {
      g_state = LinkState::NoWifi;
      announced = false;
      if (now - lastWifiTry > wifiBackoff) {
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        lastWifiTry = now;
        wifiBackoff = min<uint32_t>(wifiBackoff * 2, 30000);
      }
      vTaskDelay(pdMS_TO_TICKS(200));
      continue;
    }
    wifiBackoff = 2000;

    // --- Time ----------------------------------------------------------
    if (!timeStarted) {
      configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);  // UTC
      timeStarted = true;
    }
    char probe[32];
    if (!formatTimestamp(s, probe, sizeof(probe))) {
      g_state = LinkState::NoTime;
      vTaskDelay(pdMS_TO_TICKS(250));
      continue;
    }

    // --- MQTT ----------------------------------------------------------
    if (!g_mqtt.connected()) {
      g_state = LinkState::NoBroker;
      announced = false;
      if (now - lastMqttTry > mqttBackoff) {
        lastMqttTry = now;
        if (connectMqtt()) {
          mqttBackoff = 2000;
          Serial.println("[cloud] MQTT connected");
        } else {
          Serial.printf("[cloud] MQTT connect failed, state=%d\n", g_mqtt.state());
          mqttBackoff = min<uint32_t>(mqttBackoff * 2, 60000);
        }
      }
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    g_state = LinkState::Online;
    g_mqtt.loop();

    if (!announced) {
      announced = publishStatus(s, true);
      lastStatus = now;
      lastTelemetry = 0;  // send a reading right away
    }

    // Denied valve requests → events (dashboard alerts).
    DeniedEvent e;
    while (g_denied && xQueueReceive(g_denied, &e, 0) == pdTRUE) {
      publishDenied(e);
    }

    bool active = s.moving || s.valveOpen;
    uint32_t interval = active ? TELEMETRY_ACTIVE_MS : TELEMETRY_IDLE_MS;
    if (g_valveChanged || lastTelemetry == 0 || now - lastTelemetry >= interval) {
      g_valveChanged = false;
      if (publishTelemetry(s)) lastTelemetry = now;
    }
    if (now - lastStatus >= STATUS_INTERVAL_MS) {
      publishStatus(s, true);
      lastStatus = now;
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

#endif  // ENABLE_CLOUD && HAVE_SECRETS

// ------------------------------------------------------------
// Public API (called from the control loop)
// ------------------------------------------------------------
void cloudBegin(const char* deviceTag) {
  snprintf(g_truckTopicBase, sizeof(g_truckTopicBase), "%s/%s", MQTT_TOPIC_PREFIX, TRUCK_ID);
  snprintf(g_clientId, sizeof(g_clientId), "truck-%s-%s", TRUCK_ID, deviceTag);
#if ENABLE_CLOUD && HAVE_SECRETS
  g_denied = xQueueCreate(4, sizeof(DeniedEvent));
  g_state = LinkState::NoWifi;
  // Core 0 next to the Wi-Fi/Bluetooth stacks; the Arduino loop stays on core 1.
  xTaskCreatePinnedToCore(cloudTask, "cloud", 10240, nullptr, 1, nullptr, 0);
#else
  g_state = LinkState::Disabled;
  Serial.println("[cloud] disabled (ENABLE_CLOUD=0 or secrets.h missing)");
#endif
}

void cloudUpdate(const TruckSnapshot& s) {
  portENTER_CRITICAL(&g_mux);
  g_snap = s;
  portEXIT_CRITICAL(&g_mux);
}

void cloudValveChanged() { g_valveChanged = true; }

void cloudValveDenied(const char* reason, const TruckSnapshot& s) {
  if (!g_denied) return;
  DeniedEvent e;
  strncpy(e.reason, reason, sizeof(e.reason) - 1);
  e.reason[sizeof(e.reason) - 1] = '\0';
  e.snap = s;
  xQueueSend(g_denied, &e, 0);  // drop if full rather than block the control loop
}

LinkState cloudState() { return g_state; }

const char* cloudStateText() {
  switch (g_state) {
    case LinkState::Disabled: return "CLOUD OFF";
    case LinkState::NoWifi: return "NO WIFI";
    case LinkState::NoTime: return "WAIT TIME";
    case LinkState::NoBroker: return "MQTT...";
    case LinkState::Online: return "ONLINE";
  }
  return "?";
}

uint32_t cloudPublished() { return g_published; }
