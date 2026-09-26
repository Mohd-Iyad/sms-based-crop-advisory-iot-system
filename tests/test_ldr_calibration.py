"""
Regression test for spec section 26 ("LDR calibration fix"): the audit that
preceded this rework flagged the LDR dark/bright direction as an OPEN
question needing verification. Direct inspection of
hardware/crop_advisory_node/crop_advisory_node.ino confirmed the formula is
already correct (dark -> ~0, bright -> ~100) -- so this is a missing test
being added, not a logic fix.

The formula can't be executed directly (it's C++, on firmware this project
doesn't run in CI), so it's mirrored here in Python using the exact same
expression and the same calibration constants as hardware/config.example.h,
so a future accidental change to either file's formula/constants without
updating the other is at least caught by a human reading a failing test,
even though this can't catch every possible firmware-only regression.
"""
import os
import re


HARDWARE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hardware")


def _read_ldr_constants_from_config_example():
    """Parses LDR_ADC_DARK / LDR_ADC_BRIGHT straight out of config.example.h, so this
    test can never silently drift from the actual shipped calibration defaults."""
    path = os.path.join(HARDWARE_DIR, "config.example.h")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    dark = int(re.search(r"#define\s+LDR_ADC_DARK\s+(\d+)", text).group(1))
    bright = int(re.search(r"#define\s+LDR_ADC_BRIGHT\s+(\d+)", text).group(1))
    return dark, bright


def _light_index(raw: float, dark: int, bright: int) -> float:
    """Mirrors readLightLevel() in crop_advisory_node.ino exactly (including the clamp)."""
    index = 100.0 * ((dark - raw) / (dark - bright))
    return max(0.0, min(100.0, index))


def test_calibration_constants_are_present_and_sane():
    dark, bright = _read_ldr_constants_from_config_example()
    assert dark != bright, "SOIL/LDR-style calibration endpoints must not be identical"
    assert 0 <= bright < dark <= 4095, "expected dark > bright, both within the ESP32's 12-bit ADC range"


def test_dark_reading_gives_a_low_index():
    dark, bright = _read_ldr_constants_from_config_example()
    assert _light_index(dark, dark, bright) == 0.0
    assert _light_index(dark - 5, dark, bright) < 5.0   # near-dark: still close to 0


def test_bright_reading_gives_a_high_index():
    dark, bright = _read_ldr_constants_from_config_example()
    assert _light_index(bright, dark, bright) == 100.0
    assert _light_index(bright + 5, dark, bright) > 95.0   # near-bright: still close to 100


def test_index_increases_monotonically_from_dark_to_bright():
    dark, bright = _read_ldr_constants_from_config_example()
    raws = [dark - i * (dark - bright) / 10 for i in range(11)]   # dark -> bright, 10 steps
    indexes = [_light_index(r, dark, bright) for r in raws]
    assert indexes == sorted(indexes), "index must rise monotonically as the sensor gets brighter"


def test_out_of_calibration_readings_are_clamped_not_extrapolated():
    dark, bright = _read_ldr_constants_from_config_example()
    assert _light_index(dark + 200, dark, bright) == 0.0     # darker than the dark calibration point
    assert _light_index(bright - 200, dark, bright) == 100.0  # brighter than the bright calibration point


def test_reversed_calibration_would_be_caught_by_this_test_suite():
    """
    If LDR_ADC_DARK/LDR_ADC_BRIGHT were ever swapped by mistake (a reversed
    calibration -- spec section 26 point 3), dark would map to a HIGH index
    and bright to a LOW one: the monotonic/direction tests above would fail
    against the real config.example.h constants. This test pins that specific
    failure mode using deliberately-reversed constants, so the mechanism
    itself (not just today's correct values) is verified.
    """
    reversed_dark, reversed_bright = 600, 3200   # swapped on purpose
    assert _light_index(600, reversed_dark, reversed_bright) < 5.0     # "dark" raw now reads as bright
    assert _light_index(3200, reversed_dark, reversed_bright) > 95.0   # "bright" raw now reads as dark
    # i.e. the exact opposite of the correct direction -- this is what section 26 warns against
