# Hardware Folder — Setup Instructions (v3, matches your actual components)

## Your hardware

- ESP32-WROOM-32 DevKit
- DHT22 temperature/humidity sensor
- FC-28 soil moisture sensor (probe + LM393 comparator board)
- MH-RD rain plate (plate + LM393 comparator board)
- LM393 LDR module (ambient light — 4 pins: VCC, GND, D0, A0)

## What's in this folder

| File | What it is |
|---|---|
| `block_diagram.svg` | System-level architecture |
| `flow_diagram.svg` | Firmware logic flowchart — matches `crop_advisory_node.ino` exactly |
| `circuit_diagram.svg` | Wiring diagram for your exact 4 modules |
| `config.example.h` | Template — copy to `crop_advisory_node/config.h` and fill in your real values |
| `crop_advisory_node/` | **The main firmware** (`crop_advisory_node.ino` + its `config.h`). Arduino IDE needs the sketch inside a folder of the same name, so open the `.ino` from here |
| `_stale_duplicates/` | Old copies of the sketch/config that no longer match the firmware. Ignore (safe to delete) |
| `analog_sensor_calibration.ino` | Run this first — calibrates soil, rain, and LDR together in one pass |

## Step-by-step: what to do right now

### Step 1 — Wire everything (do this before touching any code)

Open `circuit_diagram.svg` in a browser and wire exactly as shown:

- **DHT22**: VCC → 3V3, GND → GND, DATA → GPIO4 (add a 10kΩ pull-up
  resistor between DATA and VCC only if your module doesn't already have
  one built into its breakout board)
- **FC-28** (via its LM393 comparator board): VCC → 3V3, GND → GND, **A0** → GPIO34
  — the probe itself just plugs into the 2-pin header on the comparator board
- **MH-RD** (via its LM393 comparator board): VCC → 3V3, GND → GND, **A0** → GPIO35
  — same pattern, plate plugs into the comparator board
- **LM393 LDR module**: VCC → 3V3, GND → GND, **A0** → GPIO32

Important: on all three comparator boards, you're wiring **A0** (analog
output), not **D0**. D0 is a fixed digital trigger set by the onboard blue
potentiometer — this project reads the raw analog value instead, since that
gives an actual index rather than a single on/off threshold baked into the
hardware.

All grounds are common — every sensor's GND goes to the same ground rail as
the ESP32.

### Step 2 — Install Arduino IDE support for ESP32

1. Arduino IDE → **File → Preferences** → Additional Board Manager URLs, add:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
2. **Tools → Board → Boards Manager** → search "esp32" → install the
   package by Espressif Systems.
3. Select **Tools → Board → ESP32 Dev Module**.
4. Plug in your board via USB, select the correct **Port**.

### Step 3 — Install required libraries

**Sketch → Include Library → Manage Libraries**, install:
- **DHT sensor library** (Adafruit)
- **Adafruit Unified Sensor** (installs automatically as a dependency)
- **ArduinoJson** (Benoit Blanchon)

### Step 4 — Calibrate all three analog sensors in one pass

1. Open `analog_sensor_calibration.ino`, upload it to your ESP32.
2. Open **Tools → Serial Monitor** at `115200` baud. You'll see three raw
   values printed every second: `Soil raw`, `Rain raw`, `LDR raw`.
3. **Soil (FC-28)**: hold the probe in dry air, note the value (→
   `SOIL_ADC_DRY`). Submerge the probe tip fully in a glass of water, note
   that value (→ `SOIL_ADC_WET`).
4. **Rain (MH-RD)**: with the plate completely dry, note the value. Flick a
   few drops of water onto the plate, note that value. Set
   `RAIN_ADC_THRESHOLD` roughly halfway between the two.
5. **LDR**: cover it fully (or turn off the room lights), note the value
   (→ `LDR_ADC_DARK`). Shine a torch/phone flashlight directly on it, note
   that value (→ `LDR_ADC_BRIGHT`).

Skipping this step means all three readings will be meaningless — every
individual sensor unit reads differently, especially the FC-28 and MH-RD
comparator boards, which also have a manual sensitivity potentiometer that
affects the raw analog range.

### Step 5 — Create and fill in config.h

1. Copy `config.example.h` to `crop_advisory_node/config.h` (next to the `.ino`).
2. Fill in:
   - `WIFI_SSID` / `WIFI_PASSWORD`
   - `BACKEND_URL` — for local testing `http://<your PC's IPv4>:8000/sensor-data`
     (start the server with `start_server.bat`); once deployed, your Render URL + `/sensor-data`
   - `DEVICE_ID` / `DEVICE_KEY` (must match your backend's `.env`)
   - All five calibration values from Step 4

`crop_advisory_node/config.h` is gitignored — your real Wi-Fi password and
device key never get committed.

### Step 6 — Upload and test the main firmware

1. Open `crop_advisory_node/crop_advisory_node.ino` (with `config.h` in the same folder —
   Arduino IDE shows both as tabs).
2. Upload to your ESP32.
3. Open Serial Monitor at `115200` baud. You should see it connect to
   Wi-Fi, then print all four sensor readings and confirm each POST to
   your backend on the configured interval.
4. Because of the backend's state-change logic, an unchanged reading will
   **not** re-trigger a call every cycle — this is intentional (see the
   main `README.md`).

## Demo sequence that shows the system actually thinking

1. **Action** — dip the FC-28 probe in water (or pull it into dry air) →
   watch the dashboard update → phone rings.
2. **No repeat spam** — leave it in the same state for the next cycle → no
   second call, proving the anti-spam fix.
3. **Failure handling** — unplug the DHT22 → dashboard shows an honest
   sensor-fault alert instead of a fake reading.
4. **Rain trigger** — flick a few drops of water onto the MH-RD plate →
   `rain_detected_now` flips to true in the next reading.
5. Mention the LDR reading on the dashboard as an example of a sensor that
   was deliberately scoped as informational-only rather than forced into
   the alert logic — a good answer if a judge asks "why doesn't light level
   trigger anything?"

## Known limitations (state these once, don't over-apologize)

- FC-28's exposed metal prongs corrode with prolonged soil contact —
  expect calibration drift over weeks; a real deployment would either
  recalibrate periodically or use a coated/capacitive probe instead.
- The LM393 comparator boards' A0 range depends partly on the onboard
  potentiometer's physical position — if you bump it, recalibrate.
- Solar + battery power was deliberately not attempted this week — see the
  main README's "what was NOT built" note.
