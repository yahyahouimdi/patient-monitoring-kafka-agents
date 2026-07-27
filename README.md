# multi agents Project

This repository implements a Kafka-based patient-monitoring pipeline for home care scenarios. It streams wearable, smart-home, and connectivity events into a two-tier agent architecture designed to detect urgent health conditions and generate severity-tagged support requests.

## Overview

The system is organized around two processing layers:

- Tier 1: a fast, deterministic rule-based safety layer that reacts immediately to critical thresholds such as low oxygen saturation, falls, or out-of-range vitals.
- Tier 2: a slower reasoning layer that combines patient context and environmental signals to produce richer, context-aware recommendations.

The project does not directly trigger medical actions. Instead, it produces structured support requests that describe what should happen next.

## Key features

- Real-time event streaming with Kafka
- Simulated sensor publishing for wearable and smart-home signals
- Topic-based architecture for vitals, context, connectivity, profiles, and alarms
- Rule-based alarm detection in Tier 1
- Retrieval and evaluation utilities in the TrackB component

## Repository structure

- kafka/: Kafka topic setup and sensor simulation scripts
- tiers/: Tier 1 and Tier 2 agent implementations
- TrackB/: benchmarks, retrieval utilities, and evaluation scripts
- docs/: supporting project documentation
- docker-compose.yml: local Kafka broker configuration
- requirement: Python dependencies for the project

## Prerequisites

Before running the project, make sure you have:

- Python 3.10+
- Docker Desktop or Docker Engine
- pip

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the required Python packages:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirement kafka-python
```

Start the local Kafka broker:

```powershell
docker compose up -d
```

Create the Kafka topics:

```powershell
python kafka\Create_topics.py
```

## Running the system

Run the sensor simulator in one terminal:

```powershell
python kafka\sensor_simulator.py
```

Run the agents in separate terminals:

```powershell
python tiers\tier1_agent.py
```

```powershell
python tiers\tier2_agent.py
```

You can stop the simulator and agents with Ctrl+C. To stop the Kafka container:

```powershell
docker compose down
```

## Notes

- Tier 2 is currently a scaffold and is intended for future reasoning, retrieval, or LLM-based enhancements.
- The main event topics are defined in kafka/Create_topics.py and are used by both agent tiers.
- The TrackB directory contains evaluation and retrieval benchmarking components that can be used for experiment analysis.


# Running the Project

Before running the project, make sure you have activated the virtual environment and started all required services (Kafka, Ollama, etc.).

## 1. Run Tier 2

From the project root, execute:

```bash
py -m TrackA.tier2_agent
```

---

## 2. Run Tier 1

Navigate to the `tiers` directory and run the Tier 1 agent:

```bash
cd tiers
py tier1_agent.py
```

---

## 3. Send Test Scenarios

To publish the predefined Kafka scenarios, navigate to the `kafka` directory and run:

```bash
cd kafka
py fixtures.py
```

---

## Execution Order

Run the components in the following order:

1. Start the required services (Kafka, Ollama, etc.).
2. Launch **Tier 2**:
   ```bash
   py -m TrackA.tier2_agent
   ```
3. Launch **Tier 1**:
   ```bash
   cd tiers
   py tier1_agent.py
   ```
4. Publish the test scenarios:
   ```bash
   cd kafka
   py fixtures.py
   ```

The system is now ready to process the incoming scenarios.

