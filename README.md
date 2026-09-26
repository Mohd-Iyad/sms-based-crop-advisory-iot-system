[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
# Crop Advisory IoT System

An IoT-based crop advisory platform that combines field sensing, rule-based agricultural decision logic, weather data, market information, and SMS delivery to provide actionable crop advisories.

> **Prototype:** This system is a proof-of-concept. Agronomic thresholds require validation against the target crop variety, local soil conditions, and region-specific agricultural recommendations before real-world deployment.

---

## Overview

The system connects an ESP32-based field node to a Python backend that processes environmental readings and determines relevant agricultural conditions.

The platform is designed around a simple principle:

**Sense → Validate → Analyse → Advise → Deliver**

Field measurements are evaluated using deterministic, versioned rules. Relevant advisories are then delivered to configured recipients through SMS.

The architecture also includes weather cross-verification, multilingual messaging, delivery management, a monitoring dashboard, and reproducible demonstration scenarios.

---

## System Architecture

```text
┌──────────────────────┐
│     ESP32 Node       │
│                      │
│ Soil / Environmental │
│      Sensors         │
└──────────┬───────────┘
           │
           │ HTTP
           ▼
┌──────────────────────┐
│    FastAPI Backend   │
│                      │
│ Validation           │
│ State Management     │
│ Rule Engine          │
│ Advisory Generation  │
└───────┬───────┬──────┘
        │       │
        │       ├──────────────► Weather Data
        │       │
        │       └──────────────► Mandi Data
        │
        ▼
┌──────────────────────┐
│   Delivery Layer     │
│                      │
│ SMS / Voice          │
│ Multi-recipient      │
│ Retry & Backoff      │
└──────────┬───────────┘
           │
           ▼
     Farmer / Users

           ▲
           │
┌──────────┴───────────┐
│     Web Dashboard    │
│                      │
│ Live readings        │
│ Active alerts        │
│ Delivery status      │
│ Demonstration tools  │
└──────────────────────┘
```

---

## Key Capabilities

### Deterministic Advisory Engine

Agricultural decisions are generated through versioned rules rather than relying on an LLM to interpret raw sensor values.

The system supports:

- Soil-moisture condition detection
- Hysteresis-based threshold handling
- Sensor-fault detection
- Fertilizer timing advisories
- Harvest-related decision-support signals
- Rain-versus-irrigation cross-verification
- Rule version tracking

### Intelligent Alert Management

The system does not repeatedly notify users for an unchanged condition.

State-change detection and configurable cooldown periods prevent unnecessary SMS delivery while allowing new or persistent conditions to be communicated.

### Sensor Fault Handling

Invalid or unavailable sensor measurements are treated as faults rather than being replaced with fabricated values.

For example, a failed DHT22 reading is represented as a sensor fault instead of generating a plausible temperature or humidity value.

### Weather Cross-Verification

Excess-moisture conditions can be cross-checked against observed rainfall data before generating the advisory.

The system distinguishes between:

- Rain-confirmed moisture
- Likely irrigation
- Unknown weather condition

### Multi-recipient Delivery

Advisories can be delivered to multiple configured recipients.

Each recipient has an independent delivery job, allowing retry and backoff handling without one failed recipient blocking other deliveries.

### Multilingual SMS

Built-in SMS templates support:

- English
- Hindi
- Kannada

Numeric values are inserted programmatically rather than translated through an LLM.

### Live Monitoring Dashboard

The dashboard provides:

- Latest field readings
- Active alerts
- Last SMS status
- Delivery information
- Demonstration controls
- Language selection
- Simulated advisory scenarios

### Reproducible Demonstration Scenarios

Named demonstration scenarios allow specific advisory conditions to be reproduced without waiting for the corresponding physical condition to occur naturally.

This provides a controlled way to demonstrate the system during presentations and evaluations.

---

## Engineering Approach

A key design decision is separating **agricultural decision logic** from **language generation and message delivery**.

```text
Sensor Data
    │
    ▼
Validation
    │
    ▼
Rule Engine
    │
    ├──► Alert Code
    │
    ├──► Rule Version
    │
    └──► Supporting Facts
             │
             ▼
      Message Planner
             │
        ┌────┴────┐
        ▼         ▼
       SMS      Voice
```

The LLM is not responsible for determining agricultural thresholds or inventing numerical measurements.

This keeps the core advisory path deterministic and auditable.

---

## Technology Stack

### Backend

- Python
- FastAPI
- Pydantic
- Uvicorn

### Embedded

- ESP32
- Arduino framework
- Environmental sensors
- Soil-moisture sensing
- HTTP communication

### External Services

- Twilio / TextBee for SMS delivery
- Open-Meteo for weather information
- data.gov.in for mandi information
- Gemini for voice-message language rendering

### Testing

- Pytest
- API tests
- Rule-engine tests
- Integration tests
- Dashboard tests
- Regression tests

---

## Repository Structure

```text
crop-advisory-iot-system/
│
├── agronomy/
│   ├── paddy_profile.py
│   └── AGRONOMY_SOURCES.md
│
├── hardware/
│   ├── crop_advisory_node/
│   ├── analog_sensor_calibration.ino
│   ├── soil_calibration.ino
│   ├── circuit_diagram.svg
│   ├── block_diagram.svg
│   └── flow_diagram.svg
│
├── repositories/
│
├── services/
│
├── tests/
│
├── main.py
├── rule_engine.py
├── state_manager.py
├── message_planner.py
├── sms_i18n.py
├── telephony.py
├── weather.py
├── mandi.py
├── dashboard.py
├── config.py
├── requirements.txt
└── README.md
```

---

## Hardware

The field node is based on an ESP32 and communicates sensor readings to the backend over HTTP.

Hardware documentation and diagrams are available in:

```text
hardware/
```

This directory contains:

- Firmware
- Sensor calibration programs
- Circuit diagram
- System block diagram
- System flow diagram
- Hardware configuration template

Private credentials are intentionally excluded from the repository.

---

## Backend Components

| Component | Responsibility |
|---|---|
| `main.py` | FastAPI application and request handling |
| `models.py` | Input validation |
| `rule_engine.py` | Agricultural decision logic |
| `state_manager.py` | State-change and cooldown management |
| `message_planner.py` | Advisory message construction |
| `sms_i18n.py` | Multilingual SMS templates |
| `telephony.py` | SMS and voice delivery |
| `weather.py` | Weather and rainfall data |
| `mandi.py` | Market-price data |
| `dashboard.py` | Monitoring and demonstration interface |
| `config.py` | Environment-based configuration |
| `agronomy/` | Versioned crop rules and sources |
| `tests/` | Automated test suite |

---

## Security

Credentials are not stored directly in the source code.

Runtime configuration is supplied through environment variables and private hardware configuration.

The repository includes:

```text
.env.example
hardware/config.example.h
```

while sensitive files such as:

```text
.env
config.h
```

are excluded through `.gitignore`.

Device requests are protected using a shared device key, and incoming data is subject to validation and duplicate-sequence checks.

---

## Testing

The project includes automated tests covering:

- Advisory rules
- Hysteresis behaviour
- Sensor faults
- API behaviour
- Dashboard behaviour
- Delivery queue
- Integrations
- Regression cases

Run the test suite with:

```bash
pytest tests/ -v
```

---

## Deployment

The backend can be run locally for development and hardware demonstrations.

Example:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

For remote deployment, the backend can be hosted as a web service with runtime environment variables supplied by the hosting platform.

The ESP32 can then communicate with the deployed backend through HTTPS.

---

## Limitations

This is a prototype and has several known limitations:

- Agricultural thresholds require field validation.
- Alert state is currently maintained in memory.
- Persistent storage would be required for a production deployment.
- Rate limiting requires further implementation.
- Sensor silence detection currently appears on the dashboard but does not independently trigger an SMS.
- HTTPS communication currently does not perform certificate pinning.

These limitations are documented rather than hidden because they affect production readiness.

---

## Project Status

**Current stage:** Functional prototype

The system currently includes:

- ESP32 field sensing
- Backend processing
- Deterministic advisory rules
- Sensor fault handling
- Weather cross-verification
- SMS delivery
- Multi-recipient delivery
- Multilingual SMS
- Live dashboard
- Demonstration scenarios
- Automated tests

---

## License

See `LICENSE` for licensing information.
