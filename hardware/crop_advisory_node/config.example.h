#ifndef CONFIG_H
#define CONFIG_H

// ---- Wi-Fi credentials ----
#define WIFI_SSID "YOUR_WIFI_NAME"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// ---- Backend endpoint ----
#define BACKEND_URL "YOUR_BACKEND_URL"

// ---- Device identity ----
#define DEVICE_ID       "FIELD-001"
#define DEVICE_KEY      "demo-key-123"

// ---- Pin assignments ----
#define DHT_PIN         4
#define DHT_TYPE        DHT22

#define SOIL_PIN        34
#define RAIN_PIN        35
#define LDR_PIN         32

// ---- Reading interval ----
// A new reading every 15 seconds, measured from the start of one reading to the start of the
// next. (For long-term field use 5+ minutes is plenty.)
#define READING_INTERVAL_MS   (15UL * 1000UL)

// ---- FC-28 soil moisture calibration ----
// Latest values from your calibration test
#define SOIL_ADC_DRY       4095
#define SOIL_ADC_WET       1600

// ---- MH-RD rain plate calibration ----
// Latest threshold calculated from your observed dry/wet readings
#define RAIN_ADC_THRESHOLD  2750

// ---- LM393 LDR calibration ----
// Latest observed extremes from your calibration test
#define LDR_ADC_DARK       0
#define LDR_ADC_BRIGHT     4095

#endif