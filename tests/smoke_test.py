"""
Smoke test — send a custom counter metric to the local OTel agent (or collector).
Verifies end-to-end flow: script → agent/collector → Prometheus → Grafana.

Usage:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    python smoke_test.py

Env vars (optional):
    OTEL_ENDPOINT  — default http://localhost:4317
"""

import os
import time

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

ENDPOINT = os.environ.get("OTEL_ENDPOINT", "http://localhost:4317")

def main():
    resource = Resource.create({
        "service.name": "smoke-test",
        "env": "dev",
    })

    exporter = OTLPMetricExporter(endpoint=ENDPOINT, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
    provider = MeterProvider(resource=resource, metric_readers=[reader])

    meter = provider.get_meter("smoke-test")
    counter = meter.create_counter("smoke_test_requests_total", description="Smoke test counter")

    print(f"Sending 10 increments to {ENDPOINT} ...")
    for i in range(10):
        counter.add(1, {"route": "/health"})
        print(f"  [{i+1}/10] sent")
        time.sleep(1)

    # Flush remaining metrics before exit
    provider.shutdown()
    print("Done. Check Prometheus/Grafana for 'smoke_test_requests_total'.")

if __name__ == "__main__":
    main()
