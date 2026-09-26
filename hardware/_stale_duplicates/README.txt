These two files were stale duplicates and have been moved here (not deleted).

  config.h               - an OLD config: it lacks DEVICE_ID, DEVICE_KEY, LDR_PIN,
                           RAIN_ADC_THRESHOLD and the LDR_* values the sketch needs, so the
                           sketch will NOT compile against it.
  crop_advisory_node.ino - a copy of the sketch that differs from the real one by one blank line.

The real, current sketch is  hardware/crop_advisory_node/crop_advisory_node.ino
with its config in           hardware/crop_advisory_node/config.h
(Arduino IDE requires the .ino to sit in a folder with the same name, which is why it lives there.)
Delete this folder whenever you like.
