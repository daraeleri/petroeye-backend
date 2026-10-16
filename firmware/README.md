# PetroEye truck firmware (ESP32)

Reference firmware for the prototype truck: Dabble Bluetooth driving, GPS geofence valve interlock, ultrasonic tank level, LCD — **plus the link to the PetroEye digital twin** (Wi-Fi + MQTT over TLS to EMQX → backend → dashboard).

It keeps the original firmware's pins, Dabble button map and safety rules, and adds:

| Change | Why |
| ------ | --- |
| Unique Bluetooth name per board (`PetroEye-truck-001-A1B2`, last 4 = MAC) | A replacement board no longer shares a name with the old board your phone remembers |
| Truck stops the moment the phone disconnects | Before, it kept driving until the 1.5 s command timeout |
| Boot screen shows the **reason for the last reset** (`BROWNOUT!`, `CRASH`, …) | Brown-outs from the motor/servo/relay supply look exactly like "Bluetooth keeps dropping" |
| LCD pages for Bluetooth and cloud status | You can see on the truck whether Dabble is connected and whether data reaches the dashboard |
| Ultrasonic: median of 5 pings, 3 ms timeout | ~5× less time blocked per reading than 7 pings × 15 ms |
| Network runs on the ESP32's second core | Wi-Fi joins and TLS handshakes can't freeze driving or the valve interlocks |
| Refused valve requests are reported (`valve_open_denied`) | The dashboard alerts when someone tries to discharge outside a zone |
| Geofence radius 8 m (was 1 m) | A NEO-6M is only accurate to a few metres; 1 m kept the valve shut |
| Optional test mode to force the valve open | Exercises the "valve opened outside geofence" alert (off by default) |

## Setup (Arduino IDE)

1. **Board package**: *Boards Manager* → "esp32 by Espressif Systems" (2.0.x or 3.x both work). Board: **ESP32 Dev Module** (or your DOIT DevKit V1).
2. **Partition scheme**: *Tools → Partition Scheme →* **Huge APP (3MB No OTA/1MB SPIFFS)**. Bluetooth + Wi-Fi + TLS don't fit the default 1.2 MB app partition.
3. **Libraries** (*Library Manager*): `TinyGPSPlus` (Mikal Hart), `ESP32Servo` (Kevin Harrington), `LiquidCrystal I2C` (Frank de Brabander / marcoschwartz), `PubSubClient` (Nick O'Leary).
4. **Secrets**: copy `petroeye_truck/secrets.example.h` to `petroeye_truck/secrets.h` and fill in:
   - `WIFI_SSID` / `WIFI_PASSWORD` — a **2.4 GHz** network; the driver's phone hotspot works well (the phone is next to the truck for Dabble anyway).
   - `MQTT_HOST` — the EMQX deployment address; `MQTT_USERNAME` / `MQTT_PASSWORD` — the **truck-001** credential (not the backend's).
   - `MQTT_CA_CERT` — download *CA Certificate* from the EMQX deployment overview and paste its contents.
   `secrets.h` is gitignored — never commit it.
5. Open `petroeye_truck/petroeye_truck.ino`, check `config.h` (truck ID, pins, zones, tank), upload.
6. Optional: *Serial Monitor* at **115200** shows chip model, PSRAM, reset reason, Bluetooth name and cloud state.

Command line (CI): `pio run -e core2` (Arduino-ESP32 2.x) or `pio run -e core3` (3.x) from this folder.

## Make the dashboard match the truck

In https://petroeye-frontend.vercel.app (admin/operator):

1. **Truck**: `truck-001` already exists (it must match `TRUCK_ID`).
2. **Tank calibration** (truck page → Tank → *Calibrate*): shape **Horizontal cylinder**, diameter **8.6** cm, length **29** cm, sensor offset **2.3** cm (= 10.9 − 8.6). Same geometry as the firmware's own volume calculation.
3. **Geofences** (Live map → *+ Geofence*, *Applies to: truck-001*):
   - "Start zone" at 4.103175, 9.755538, radius = `GEOFENCE_RADIUS_M`
   - "Destination zone" at 4.103057, 9.755324, same radius

   If these don't match `config.h`, the truck and the dashboard disagree about where discharging is allowed.

## What you'll see on the dashboard

| On the truck | In the dashboard |
| ------------ | ---------------- |
| Driving | Position + track on the live map, speed, "Moving" |
| TRIANGLE inside a zone (stopped) | Valve OPEN, authorized discharge with litres |
| TRIANGLE outside a zone / while moving / no GPS | **"Valve open attempt refused"** alert (critical outside a zone or without GPS) |
| Test mode: hold TRIANGLE 3 s outside a zone, release | **Critical "Valve opened outside geofence"** + unauthorized discharge |
| Power off / crash | "Device dropped offline" (MQTT Last Will) |

## Second ESP32 won't connect to Dabble — checklist

Work through these in order; the LCD and Serial Monitor now tell you most of the answers.

1. **The phone remembers the old board.** Android pairs by MAC address, and both boards used the same Bluetooth name. In the phone's *Settings → Bluetooth*, **forget/unpair every old entry** for the truck. With this firmware the name ends in 4 hex digits (shown on the LCD at boot) — pair *that* one, then select it in Dabble.
2. **Wrong chip.** Dabble's gamepad here uses **Bluetooth Classic**. Only the original ESP32 (ESP32-WROOM-32 / DevKit V1) has it; **ESP32-S2, S3 and C3 don't** (the sketch now refuses to compile for them). Check the metal can on the module.
3. **ESP32-WROVER board (has PSRAM).** On WROVER modules GPIO16/17 are wired to the PSRAM chip, and the GPS is on 16/17. The Serial Monitor prints a warning at boot if PSRAM is present — move the GPS to GPIO4 (RX) / GPIO33 (TX) and change `config.h`.
4. **Brown-outs.** If the LCD boot screen says `RESET:BROWNOUT!`, the supply dipped (Bluetooth radio peaks + servo/relay/motor current on a weak power bank or thin USB cable). Use a good cable/power bank for the ESP32, keep the servo and motors on their own supplies, and share only ground.
5. **GPIO12 (ultrasonic TRIG) is a boot strapping pin.** If anything holds it HIGH at power-on the ESP32 picks 1.8 V flash and boots erratically — this varies between boards, so it can work on one and not another. Move TRIG to **GPIO19** and set `PIN_US_TRIG 19`.
6. **HC-SR04 ECHO is 5 V.** Put a divider (1 kΩ series + 2 kΩ to GND) before GPIO13. Driving 5 V straight into a GPIO can damage the chip — consistent with how the first board died (hot within seconds, no upload).
7. **Core 3.x board package.** Pairing prompts behave differently from 2.0.x on some phones. If the phone shows a pairing code, accept it; if pairing keeps failing, try board package **2.0.17**.
8. **Wi-Fi + Bluetooth together.** They share one radio. The firmware leaves Wi-Fi modem-sleep on (required for coexistence); don't add `WiFi.setSleep(false)`. If Bluetooth still stutters, set `ENABLE_CLOUD 0` to confirm, then use a stronger Wi-Fi signal.

## Bring-up order (from the project report)

Board alone (upload, no heating) → power rails → LCD → GPS outdoors → ultrasonic (with ECHO divider) → servo → relay (valve disconnected) → motors (wheels raised, correct motor voltage) → Bluetooth commands → interlocks → cloud (Wi-Fi + dashboard) → tank calibration → integrated test.
