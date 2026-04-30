"""
Sample traced application - simulates an "Order Processing" business flow.
Sends traces to the local OTel Collector, which forwards them to Tempo.

Usage:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    python trace_demo.py

Each run creates a trace with spans simulating:
  Place Order
    -> Validate Order
    -> Check Inventory
    -> Process Payment
    -> Send Confirmation
"""

import time
import random

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

ENDPOINT = "http://localhost:4317"

def setup_tracing():
    resource = Resource.create({
        "service.name": "order-service",
        "service.version": "1.0.0",
        "env": "dev",
    })
    exporter = OTLPSpanExporter(endpoint=ENDPOINT, insecure=True)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider

def simulate_step(tracer, name, min_ms=5, max_ms=50, error_rate=0.0):
    """Simulate a business step as a span with realistic timing."""
    with tracer.start_as_current_span(name) as span:
        duration = random.uniform(min_ms, max_ms) / 1000.0
        time.sleep(duration)
        span.set_attribute("duration_ms", round(duration * 1000, 1))

        if random.random() < error_rate:
            span.set_status(trace.StatusCode.ERROR, f"{name} failed")
            span.set_attribute("error", True)
            return False
    return True

def process_order(tracer, order_id):
    """Simulate a full order processing flow as a trace."""
    with tracer.start_as_current_span("place-order") as root:
        root.set_attribute("order.id", order_id)
        root.set_attribute("customer.tier", random.choice(["standard", "premium", "enterprise"]))

        # Step 1: Validate
        simulate_step(tracer, "validate-order", 2, 10)

        # Step 2: Inventory check
        simulate_step(tracer, "check-inventory", 10, 40)

        # Step 3: Payment (slowest, occasional failures)
        ok = simulate_step(tracer, "process-payment", 50, 200, error_rate=0.1)
        if not ok:
            root.set_status(trace.StatusCode.ERROR, "Payment failed")
            root.set_attribute("order.status", "failed")
            return

        # Step 4: Confirmation
        simulate_step(tracer, "send-confirmation", 5, 20)
        root.set_attribute("order.status", "completed")

def main():
    provider = setup_tracing()
    tracer = trace.get_tracer("order-service")

    print(f"Sending order traces to {ENDPOINT} ...")
    for i in range(10):
        order_id = f"ORD-{1000 + i}"
        process_order(tracer, order_id)
        print(f"  [{i+1}/10] Processed {order_id}")
        time.sleep(0.5)

    provider.shutdown()
    print("Done. Check Grafana > Explore > Tempo to see traces.")

if __name__ == "__main__":
    main()
