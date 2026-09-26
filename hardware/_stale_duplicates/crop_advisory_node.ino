// crop_advisory_node.ino  (v3 -- matches actual hardware)
//
// ESP32 field sensor node for the Voice-First Crop Advisory project.
// Hardware: ESP32-WROOM-32 DevKit, DHT22, FC-28 soil moisture (with LM393
// comparator board), MH-RD rain plate (with LM393 comparator board), LM393
// LDR ambient-light module.
//
// Design principles carried over from v2 (see hardware/README.md for the
// full reasoning):
//  - No NTP time sync -- days-since-sowing is computed on the BACKEND.
//  - DHT22 failure sends NULL for temperature/humidity, never a fake value.
//  - Soil moisture is a smoothed, calibrated INDEX, not a lab measurement.
//  - device_id + sequence number sent so the backend can reject duplicates.
//  - Ambient light (LDR) is sent as a purely informational field -- it
//    never gates an alert and is never seen by the LLM.
//
// Required libraries (install via Arduino IDE Library Manager):
//   - "DHT sensor library" by Adafruit
//   - "Adafruit Unified Sensor" (dependency of the above)
//   - "ArduinoJson" by Benoit Blanchon
//
// Board: ESP32 DevKit (select "ESP32 Dev Module" in Tools > Board)

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

#include "config.h"

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long sequenceNumber = 0;

// ---------- Wi-Fi connection ----------
bool connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to Wi-Fi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi connected. IP: " + WiFi.localIP().toString());
    return true;
  }
  Serial.println("\nWi-Fi connection failed after ~15 seconds (30 attempts).");
  return false;
}

// ---------- Averaged analog read helper (reduces jitter on stage) ----------
long readAveraged(int pin, int samples = 16) {
  long total = 0;
  for (int i = 0; i < samples; i++) {
    total += analogRead(pin);
    delay(10);
  }
  return total / samples;
}

// ---------- FC-28 soil moisture -> 0-100 index ----------
// NOTE: this is a relative INDEX from calibration, not a laboratory
// volumetric-water-content measurement. FC-28 uses exposed metal prongs
// (resistive sensing) which corrode with prolonged soil contact -- expect
// drift over weeks and recalibrate periodically.
float readSoilMoistureIndex() {
  long raw = readAveraged(SOIL_PIN);
  // Lower raw value = wetter soil, for this sensor family.
  float index = 100.0 * ((float)(SOIL_ADC_DRY - raw) / (float)(SOIL_ADC_DRY - SOIL_ADC_WET));
  if (index < 0) index = 0;
  if (index > 100) index = 100;
  return index;
}

// ---------- MH-RD rain plate: lower raw = more water detected ----------
bool readIsRaining() {
  long raw = readAveraged(RAIN_PIN, 8);
  return raw < RAIN_ADC_THRESHOLD;
}

// ---------- LM393 LDR -> 0-100 ambient light index (informational only) ----------
float readLightLevel() {
  long raw = readAveraged(LDR_PIN, 8);
  // Lower raw value = brighter, for this sensor family (LM393 comparator boards
  // typically output higher voltage/ADC in darkness). Calibrate and confirm
  // the direction on YOUR module with analog_sensor_calibration.ino.
  float index = 100.0 * ((float)(LDR_ADC_DARK - raw) / (float)(LDR_ADC_DARK - LDR_ADC_BRIGHT));
  if (index < 0) index = 0;
  if (index > 100) index = 100;
  return index;
}

// ---------- Send JSON payload to backend ----------
bool sendSensorData(float soilMoisture, bool dhtOk, float temperature, float humidity,
                     bool raining, float lightLevel) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi not connected, skipping send.");
    return false;
  }

  HTTPClient http;
  http.begin(BACKEND_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  http.setTimeout(15000);

  StaticJsonDocument<384> doc;
  doc["device_id"] = DEVICE_ID;
  doc["sequence"] = sequenceNumber;
  doc["soil_moisture"] = soilMoisture;
  doc["raining"] = raining;
  doc["light_level"] = lightLevel;

  // Only include temperature/humidity if the DHT22 read succeeded --
  // otherwise leave them out entirely so the backend receives null,
  // which correctly triggers a SENSOR_FAULT alert instead of a fake reading.
  if (dhtOk) {
    doc["temperature"] = temperature;
    doc["humidity"] = humidity;
  }

  String payload;
  serializeJson(doc, payload);

  Serial.println("Sending payload: " + payload);
  int httpResponseCode = http.POST(payload);

  bool success = false;
  if (httpResponseCode > 0) {
    Serial.printf("HTTP response code: %d\n", httpResponseCode);
    String response = http.getString();
    Serial.println("Response: " + response);
    success = (httpResponseCode == 200);
  } else {
    Serial.printf("HTTP POST failed, error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
  return success;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Crop Advisory Field Node Starting (v3) ===");

  dht.begin();
  connectWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi dropped, reconnecting...");
    connectWiFi();
  }

  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();
  bool dhtOk = !(isnan(humidity) || isnan(temperature));

  if (!dhtOk) {
    Serial.println("DHT22 read failed -- reporting sensor fault (NOT fabricating a value).");
  }

  float soilMoisture = readSoilMoistureIndex();
  bool raining = readIsRaining();
  float lightLevel = readLightLevel();

  Serial.println("---- Readings ----");
  Serial.printf("Soil moisture index: %.1f / 100\n", soilMoisture);
  if (dhtOk) {
    Serial.printf("Temperature: %.1f C\n", temperature);
    Serial.printf("Humidity: %.1f %%\n", humidity);
  } else {
    Serial.println("Temperature/Humidity: FAULT (DHT22 not responding)");
  }
  Serial.printf("Raining now: %s\n", raining ? "yes" : "no");
  Serial.printf("Ambient light index: %.1f / 100\n", lightLevel);
  Serial.printf("Sequence: %lu\n", sequenceNumber);

  bool sent = sendSensorData(soilMoisture, dhtOk, temperature, humidity, raining, lightLevel);
  Serial.println(sent ? "Data sent successfully." : "Data send failed (will retry with a fresh reading next cycle).");

  sequenceNumber++;

  Serial.printf("Waiting %lu ms until next reading...\n\n", (unsigned long)READING_INTERVAL_MS);
  delay(READING_INTERVAL_MS);
}
