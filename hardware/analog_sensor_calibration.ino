// analog_sensor_calibration.ino
//
// Run this FIRST, before the main firmware, to find the correct calibration
// values for all three analog sensors in ONE pass (soil, rain, LDR), since
// they're wired to separate ADC pins and can be read simultaneously.
//
// How to use:
//   1. Upload this sketch, open Serial Monitor at 115200 baud.
//   2. SOIL: hold the FC-28 probe in open air (dry) -- note "Soil raw".
//            This becomes SOIL_ADC_DRY in config.h.
//      Then submerge the probe tip fully in a glass of water -- note the
//      value. This becomes SOIL_ADC_WET.
//   3. RAIN: with the MH-RD plate completely dry, note "Rain raw" -- set
//      RAIN_ADC_THRESHOLD roughly halfway between this and the value you
//      see after flicking a few drops of water onto the plate.
//   4. LDR: cover the LDR fully (or turn off the lights) -- note "LDR raw"
//      as LDR_ADC_DARK. Then shine a torch/phone light directly on it --
//      note that value as LDR_ADC_BRIGHT.
//   5. Update all five values in config.h, then upload the main firmware.

#define SOIL_PIN 34
#define RAIN_PIN 35
#define LDR_PIN  32

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Analog sensor calibration -- reading all three raw ADC values every second.");
  Serial.println("Test each sensor's dry/wet or dark/bright extremes as described in this file's header comment.");
}

void loop() {
  int soil = analogRead(SOIL_PIN);
  int rain = analogRead(RAIN_PIN);
  int ldr = analogRead(LDR_PIN);
  Serial.printf("Soil raw: %4d   |   Rain raw: %4d   |   LDR raw: %4d\n", soil, rain, ldr);
  delay(1000);
}
