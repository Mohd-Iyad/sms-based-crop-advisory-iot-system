// soil_calibration.ino
//
// Run this FIRST, before the main firmware, to find the correct
// SOIL_ADC_DRY and SOIL_ADC_WET values for YOUR specific sensor unit.
// Cheap capacitive sensors vary from unit to unit, so skipping this
// step means your moisture percentages will be inaccurate.
//
// How to use:
//   1. Upload this sketch, open Serial Monitor at 115200 baud.
//   2. Hold the sensor in open air (completely dry) -- note the printed value.
//      This becomes SOIL_ADC_DRY in config.h.
//   3. Submerge the sensor tip fully in a glass of water -- note the printed value.
//      This becomes SOIL_ADC_WET in config.h.
//   4. Update those two numbers in config.h, then upload the main firmware.

#define SOIL_PIN 34

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Soil sensor calibration -- reading raw ADC value every second.");
  Serial.println("Test in dry air first, then fully submerged in water.");
}

void loop() {
  int raw = analogRead(SOIL_PIN);
  Serial.printf("Raw ADC value: %d\n", raw);
  delay(1000);
}
