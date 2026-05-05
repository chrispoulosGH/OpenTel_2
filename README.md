# OpenTelemetry Demo Stack

Native Windows OpenTelemetry demo stack with:

- OpenTelemetry Collector agent for host metrics
- Central OpenTelemetry Collector
- Prometheus for metrics storage
- Tempo for trace storage
- Grafana for visualization
- Python utilities to generate traces, BPMN 2.0 XML, and ordered service-path segments

## Architecture

```text
Agent ──OTLP/gRPC──> Central Collector ──> Prometheus
         host metrics                   └─> Tempo

Instrumented apps ──OTLP/gRPC──> Central Collector ──> Tempo

Grafana reads from Prometheus and Tempo.
```

## Repository Layout

```text
agent/
  config-linux.yaml
  config-windows.yaml
  config-local-test.yaml
  start-agent.ps1
  stop-agent.ps1

central/
  collector-config-native.yaml
  prometheus.yaml
  tempo.yaml
  setup-from-downloads2.ps1
  start-native2.ps1
  stop-native2.ps1
  grafana/

tests/
  trace_demo.py
  nydmv_sim.py
  trace_to_bpmn2.py
  flows_<trace_id>.xml
  service_segments_<trace_id>.txt
```

## Prerequisites

- Windows PowerShell 5.1 or later
- Python installed and available as `python`
- Binaries downloaded and unpacked under `central\bin`
- `NO_PROXY` set for localhost traffic in the current PowerShell session:

```powershell
$env:NO_PROXY = "localhost,127.0.0.1"
```

## Start And Stop Services

### Start the central stack

From the repository root:

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\start-native2.ps1
```

This starts:

- Prometheus
- Tempo
- Central OpenTelemetry Collector
- Grafana

### Start the alert webhook service

From the repository root:

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\start-alert-webhook.ps1
```

This starts a local HTTP service Grafana can call when alerts fire.

Optional parameters:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\start-alert-webhook.ps1 -Port 8088 -BindHost 127.0.0.1 -AuthToken "replace-me"
```

Enable automatic BPMN ingestion on each alert webhook:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\start-alert-webhook.ps1 -AutoIngest -BpmnFile .\tests\flows.bpmn
```

With `-AutoIngest`, each received webhook event updates the specified BPMN file in place so annotations are visible directly in the diagram.

Stop it with:

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\stop-alert-webhook.ps1
```

### Stop the central stack

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\stop-native2.ps1
```

### Start the agent

The agent start script stops any existing agent first, then starts a fresh one.

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\agent\start-agent.ps1
```

### Stop the agent

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\agent\stop-agent.ps1
```

## Service URLs And Ports

### UI links

| Service | URL | Notes |
|---|---|---|
| Grafana | http://localhost:3000 | Default login is `admin / admin` unless changed |
| Prometheus | http://localhost:9090 | Metrics query UI |
| Tempo HTTP API | http://localhost:3200 | Used by the BPMN and service segment generators |
| Alert webhook service | http://127.0.0.1:8088/health | Receives Grafana alert webhooks |

### Collector and agent ports

| Component | Port | Purpose |
|---|---:|---|
| Central Collector | 4317 | OTLP gRPC ingest |
| Central Collector | 4318 | OTLP HTTP ingest |
| Central Collector | 13133 | Health endpoint |
| Tempo | 4320 | OTLP gRPC ingest from collector |
| Tempo | 4321 | OTLP HTTP ingest |
| Agent | 13134 | Health endpoint |
| Agent | 8889 | Agent self-telemetry metrics |

## What Runs Where

- The central collector uses `central\collector-config-native.yaml`
- The agent uses `agent\config-local-test.yaml`
- Both agent and central collector use the same `otelcol-contrib.exe` binary with different configs

## Verifying The Stack

### Metrics

Open Prometheus and query:

```text
system_cpu_time_seconds_total
```

Or open Grafana Explore and query the same metric from Prometheus.

### Traces

Open Grafana Explore and select the Tempo datasource, or query Tempo directly through:

```text
http://localhost:3200/api/search
```

## Generating Trace Data

### Simple trace demo

```powershell
cd C:\code\openTel_2\tests
python trace_demo.py
```

### NY DMV simulator

```powershell
cd C:\code\openTel_2\tests
python nydmv_sim.py
```

These scripts send traces to the central collector, which forwards them to Tempo.

## Generate BPMN And Service Segment Outputs

The generator reads traces from Tempo and writes:

- per-scenario BPMN XML files (`test_scenario_*_flow.xml`)
- per-scenario JSON files (`test_scenario_*_flow.json`)
- merged JSON (`flows_all_bpmn2.0.json`) built from individual scenario JSON files
- a plain-text list of contiguous service combinations

### Generate outputs from current traces

```powershell
cd C:\code\openTel_2\tests
python trace_to_bpmn2.py --tempo-url http://localhost:3200 --limit 60 --output flows.xml --segments-output service_segments.txt
```

What this does:

1. Queries Tempo for recent traces
2. Groups related traces into flows
3. Builds per-scenario BPMN 2.0 process models
4. Extracts every contiguous ordered service segment of length 2 or more
5. Writes scenario BPMN XML files to `tests\output\test_scenario_*_flow.xml`
6. Writes scenario JSON files to `tests\output\test_scenario_*_flow.json`
7. Writes merged JSON to `tests\output\flows_all_bpmn2.0.json`
8. Writes the segment list to `tests\output\service_segments_<trace_id>.txt`

### Generator options

| Option | Default | Description |
|---|---|---|
| `--tempo-url` | `http://localhost:3200` | Tempo API endpoint |
| `--limit` | `60` | Maximum traces to read |
| `--output` | `flows_all_bpmn2.0.json` | Base name used for merged JSON output path (`<name>.json`) and scenario XML naming |
| `--segments-output` | `service_segments.txt` | Base segment list name. The script writes `service_segments_<trace_id>.txt` |

## Typical Workflow

```powershell
cd C:\code\openTel_2
$env:NO_PROXY = "localhost,127.0.0.1"

powershell -NoProfile -ExecutionPolicy Bypass -File .\central\start-native2.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\agent\start-agent.ps1

cd .\tests
python trace_demo.py
python trace_to_bpmn2.py --tempo-url http://localhost:3200 --limit 60 --output flows.xml --segments-output service_segments.txt
```

## Grafana Alert Webhook Setup

Use this to notify your local endpoint when thresholds are exceeded or errors occur.

1. Start webhook service:

```powershell
cd C:\code\openTel_2
powershell -NoProfile -ExecutionPolicy Bypass -File .\central\start-alert-webhook.ps1
```

2. In Grafana (`http://localhost:3000`), go to:
  `Alerting` -> `Contact points` -> `New contact point`

3. Choose integration type `Webhook` and set URL:

```text
http://127.0.0.1:8088/grafana/alert
```

4. If you started the service with `-AuthToken`, set this header in Grafana contact point:

```text
Authorization: Bearer <your-token>
```

5. Create or edit an alert rule in Grafana and select this contact point in a notification policy.

6. Trigger the rule, then verify webhook events were recorded in:

```text
central\bin\alert-webhook\alerts.ndjson
```

### Service endpoints

- `GET /health` for liveness checks
- `POST /grafana/alert` for Grafana webhook payloads
- `POST /threshold-exceeded` for custom threshold notifications
- `POST /error` for custom error notifications

## Ingest Alerts Into BPMN XML

Use this when you want alert/threshold events visible directly inside BPMN diagrams.

1. Generate BPMN XML as usual (for example with `tests\trace_to_bpmn2.py`).
2. Ensure alert events exist in:

```text
central\bin\alert-webhook\alerts.ndjson
```

3. Run alert ingestion:

```powershell
cd C:\code\openTel_2
c:\code\openTel_2\.venv\Scripts\python.exe .\tests\ingest_alerts_into_bpmn.py --bpmn .\tests\flows.bpmn
```

This writes a new file next to the input BPMN named:

```text
<original_name>_with_alerts.xml
```

Optional parameters:

```powershell
c:\code\openTel_2\.venv\Scripts\python.exe .\tests\ingest_alerts_into_bpmn.py --bpmn .\tests\flows.bpmn --alerts-file .\central\bin\alert-webhook\alerts.ndjson --output .\tests\flows_alerts.xml --max-items 5
```

### How matching works

- Best match: `trace_id` + `service` in alert payload
- Next: `service` only
- Fallback: global process-level annotation when no service/trace keys exist

For best task-level mapping from Grafana webhook payloads, include labels like:

```text
service=<service-name>
trace_id=<trace-id>
severity=<level>
```

### Endpoint-driven ingestion (automatic)

If the webhook service is started with `-AutoIngest -BpmnFile <path>`, then each call to `POST /grafana/alert` automatically runs BPMN ingestion for that file.

This gives a direct flow:

1. Grafana alert fires.
2. Grafana calls webhook endpoint.
3. Service appends alert to NDJSON log.
4. Service ingests alerts into the associated BPMN XML.

## Notes

- `trace_to_bpmn2.py` does not create traces. It only reads what is already stored in Tempo.
- `trace_to_bpmn2.py` writes per-scenario XML/JSON files and then builds `flows_all_bpmn2.0.json` from the scenario JSON files.
- `trace_to_bpmn2.py` appends the primary trace ID to the segment output file name, so `service_segments.txt` becomes `service_segments_<trace_id>.txt`.
- For a path like `A -> B -> C`, the output includes `A -> B`, `B -> C`, and `A -> B -> C`.
- If you see `No traces found in Tempo.`, run one of the trace-producing scripts first.
- Grafana does not store traces itself. Tempo stores the traces.
- Clearing Tempo storage removes stored traces.
