"""
Data models for incoming sensor readings.

soil_moisture, temperature, and humidity are Optional[float] rather than
required floats -- this is deliberate. A DHT22 that fails to read should be
able to send `null` for temperature/humidity rather than the firmware
inventing a plausible-looking fake number. See rule_engine.py for how a
missing value is handled (it raises a SENSOR_FAULT alert code, it does not
get silently treated as fine).
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SensorData(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "device_id": "FIELD-001",
                "sequence": 42,
                "soil_moisture": 24.5,
                "temperature": 29.5,
                "humidity": 68.0,
                "raining": False,
                "light_level": 62.0,
            }
        }
    )

    device_id: str = Field(..., min_length=1, max_length=64)
    # strict: a JSON `true` or a numeric string is not a sequence number.
    # The upper bound is the largest value the ESP32's `unsigned long` can hold.
    sequence: int = Field(..., strict=True, ge=0, le=4_294_967_295)

    # Range limits reject obviously garbage readings before they reach any logic.
    # NaN/Infinity are rejected explicitly (they are not valid JSON, but Python's parser accepts them).
    soil_moisture: Optional[float] = Field(None, ge=0, le=100, allow_inf_nan=False)
    temperature: Optional[float] = Field(None, ge=-10, le=60, allow_inf_nan=False)
    humidity: Optional[float] = Field(None, ge=0, le=100, allow_inf_nan=False)
    raining: Optional[bool] = None
    light_level: Optional[float] = Field(None, ge=0, le=100, allow_inf_nan=False)  # LDR-derived ambient light index, informational only

    @field_validator("device_id")
    @classmethod
    def _device_id_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("device_id must not be blank")
        return value
