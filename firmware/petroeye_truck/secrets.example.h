// ============================================================
// Copy this file to secrets.h and fill it in.
// secrets.h is gitignored — never commit real passwords.
// ============================================================
#pragma once

// Wi-Fi the truck joins (e.g. the driver's phone hotspot — the phone is
// already next to the truck for Dabble). 2.4 GHz only: the ESP32 can't
// use 5 GHz networks.
#define WIFI_SSID "your-hotspot-name"
#define WIFI_PASSWORD "your-hotspot-password"

// EMQX Cloud Serverless deployment (Overview tab).
#define MQTT_HOST "xxxxxxxx.ala.us-east-1.emqxsl.com"
#define MQTT_PORT 8883
// Device credential for THIS truck (EMQX → Access Control → Authentication).
#define MQTT_USERNAME "truck-001"
#define MQTT_PASSWORD "change-me"

// CA certificate: download it from the EMQX deployment Overview
// ("CA Certificate" ↓), open the .crt/.pem file in a text editor and
// paste everything from -----BEGIN CERTIFICATE----- to
// -----END CERTIFICATE----- between the R"EOF( and )EOF" markers.
static const char MQTT_CA_CERT[] = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE THE EMQX CA CERTIFICATE HERE
-----END CERTIFICATE-----
)EOF";
