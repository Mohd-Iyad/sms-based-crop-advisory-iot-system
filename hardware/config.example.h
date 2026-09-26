// config.example.h
//
// Copy this file to "config.h" and fill in your own values.
// config.h is gitignored -- it will contain your real Wi-Fi password and
// device key, so it must NEVER be committed to GitHub. Only this .example
// file (with placeholder values) is safe to commit.

#ifndef CONFIG_H
#define CONFIG_H

// ---- Wi-Fi credentials ----
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// ---- Backend endpoint ----
// Use your local backend while testing (e.g. http://192.168.1.x:8000/sensor-data --
// the IPv4 address of the PC running the server, on the same Wi-Fi as the ESP32),
// then switch to your hosted domain once that's live, e.g.:
// "https://crop-advisory-backend-xxxx.onrender.com/sensor-data" or "https://advisory.example.com/sensor-data"
// https:// is handled by the sketch (it encrypts but does not verify the certificate; see
// crop_advisory_node.ino). Write the https:// address directly: an http:// address that the
// host redirects to https will fail.
#define BACKEND_URL     "https://YOUR-RENDER-APP.onrender.com/sensor-data"

// ---- Device identity ----
// Must match a device your backend expects. Also sent as a header so the
// backend can reject requests that don't know this shared secret (set
// EXPECTED_DEVICE_KEY to the same value in your backend's .env).
#define DEVICE_ID       "FIELD-001"
#define DEVICE_KEY      "demo-key-123"

// ---- Pin assignments (match hardware/circuit_diagram.svg) ----
// Your actual hardware: DHT22, FC-28 soil moisture (via LM393 comparator
// board), MH-RD rain plate (via LM393 comparator board), LM393 LDR module.
#define DHT_PIN         4      // DHT22 data pin
#define DHT_TYPE        DHT22
#define SOIL_PIN        34     // FC-28 comparator board AOUT (ADC1_6)
#define RAIN_PIN        35     // MH-RD comparator board AOUT (ADC1_7)
#define LDR_PIN         32     // LM393 LDR module AOUT (ADC1_4)

// ---- Reading interval ----
#define READING_INTERVAL_MS   (15UL * 1000UL)   // 15 seconds start-to-start; use 5+ minutes for long-term field use

// ---- FC-28 soil moisture calibration ----
// Raw ADC values from YOUR sensor in fully dry air vs. fully in water.
// Run analog_sensor_calibration.ino FIRST to find these for your specific
// sensor unit, then update the values below. This is a relative INDEX, not
// a laboratory volumetric-water-content measurement -- call it that in
// your pitch, not "soil moisture percentage".
// NOTE: FC-28 uses two exposed metal prongs (resistive sensing), which
// corrode with prolonged soil contact -- expect drift over weeks and plan
// to recalibrate periodically, or note this as a known limitation.
#define SOIL_ADC_DRY    3000   // raw analogRead() value in dry air (placeholder -- recalibrate!)
#define SOIL_ADC_WET    1200   // raw analogRead() value fully submerged in water (placeholder -- recalibrate!)

// ---- MH-RD rain plate threshold ----
// Lower raw reading = more water detected on the plate. Find your own
// dry-plate baseline with analog_sensor_calibration.ino and set the
// threshold roughly halfway between dry and a few water drops on the plate.
#define RAIN_ADC_THRESHOLD   2000   // placeholder -- recalibrate!

// ---- LM393 LDR calibration ----
// Raw ADC values in full darkness (covered) vs. bright light (torch/sun).
// Used only to compute an informational ambient-light index -- this never
// gates an alert or reaches the LLM.
#define LDR_ADC_DARK    3200   // placeholder -- recalibrate!
#define LDR_ADC_BRIGHT  600    // placeholder -- recalibrate!

#endif
