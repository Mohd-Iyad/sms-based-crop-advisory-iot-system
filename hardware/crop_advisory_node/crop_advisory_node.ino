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
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include "config.h"

// Time between the START of one reading cycle and the start of the next. config.h
// normally sets this; the fallback keeps the sketch compiling with an older config.h.
#ifndef READING_INTERVAL_MS
#define READING_INTERVAL_MS (15UL * 1000UL)
#endif

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long sequenceNumber = 0;
unsigned long lastCycleStartMs = 0;
bool firstCycle = true;

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

  // Declared before `http` so it is destroyed after it.
  WiFiClientSecure secureClient;
  HTTPClient http;
  if (String(BACKEND_URL).startsWith("https://")) {
    // A hosted backend (a domain) is https only. setInsecure() ENCRYPTS the traffic but does
    // not check the server's certificate, so it protects against eavesdropping, not against
    // someone impersonating the server. For that, use secureClient.setCACert(<root CA>) instead.
    secureClient.setInsecure();
    http.begin(secureClient, BACKEND_URL);
    http.setConnectTimeout(8000);   // the TLS handshake takes a few seconds
  } else {
    http.begin(BACKEND_URL);        // plain http: a backend on the local network
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  // The backend replies 202 within milliseconds (delivery is async), so a short timeout is fine.
  http.setConnectTimeout(5000);
  http.setTimeout(10000);

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
    // The v3+ backend answers 202 Accepted (reading stored, SMS sent afterwards by its
    // worker). Treat any 2xx as success; 401 = device key mismatch, 422 = bad payload.
    success = (httpResponseCode >= 200 && httpResponseCode < 300);
  } else {
    Serial.printf("HTTP POST failed, error %d: %s\n", httpResponseCode, http.errorToString(httpResponseCode).c_str());
    Serial.printf("  -> could not reach %s from ESP32 IP %s\n", BACKEND_URL, WiFi.localIP().toString().c_str());
    Serial.println("  -> check: server running with --host 0.0.0.0, PC IP unchanged (ipconfig),");
    Serial.println("     Windows Firewall allows TCP 8000, PC and ESP32 on the same Wi-Fi.");
  }

  http.end();
  return success;
}

// ---------- DHT22 read with retries ----------
// An occasional failed DHT22 read is normal (a timing glitch on the single data wire). A real
// fault sends an SMS to the farmer, so try up to 3 times, 2.1 s apart (the sensor needs >= 2 s
// between reads), before reporting one. A genuinely dead sensor still fails all 3 attempts.
bool readDHT(float &temperature, float &humidity) {
  for (int attempt = 0; attempt < 3; attempt++) {
    humidity = dht.readHumidity();
    temperature = dht.readTemperature();
    if (!isnan(humidity) && !isnan(temperature)) {
      return true;
    }
    if (attempt < 2) {
      Serial.println("DHT22 read failed, retrying...");
      delay(2100);
    }
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Crop Advisory Field Node Starting (v3) ===");

  dht.begin();
  connectWiFi();
}

void loop() {
  // Wait until the next cycle is due. The interval is measured start-to-start with
  // millis(), so the time spent reading sensors and POSTing does not stretch it: readings
  // stay READING_INTERVAL_MS apart. Unsigned subtraction stays correct when millis()
  // rolls over (after ~49 days).
  if (!firstCycle && (millis() - lastCycleStartMs) < READING_INTERVAL_MS) {
    delay(50);
    return;
  }
  firstCycle = false;
  lastCycleStartMs = millis();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi dropped, reconnecting...");
    connectWiFi();
  }

  float humidity = NAN;
  float temperature = NAN;
  bool dhtOk = readDHT(temperature, humidity);

  if (!dhtOk) {
    Serial.println("DHT22 failed 3 reads in a row -- reporting sensor fault (NOT fabricating a value).");
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

  Serial.printf("Next reading %lu s after this one started...\n\n", (unsigned long)(READING_INTERVAL_MS / 1000UL));
}
