"""
NY DMV Online Services - Trace Simulation
==========================================
Simulates 8 real NY DMV online transactions as OpenTelemetry traces with:
  - Database access spans (Oracle, MongoDB, PostgreSQL)
  - Parallel forks (concurrent backend calls)
  - Exclusive-OR forks (conditional branching)

Each service is a separate OTel "service.name" with realistic span trees.

Usage:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    $env:NO_PROXY = "localhost,127.0.0.1"
    python nydmv_sim.py

    # Options:
    python nydmv_sim.py --endpoint http://localhost:4317 --count 30
"""

import argparse
import random
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

from opentelemetry import trace, context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import StatusCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sim_delay(min_ms, max_ms):
    """Simulate realistic latency."""
    time.sleep(random.uniform(min_ms, max_ms) / 1000.0)


def db_span(tracer, db_system, db_name, operation, table, statement=None,
            min_ms=5, max_ms=60, error_rate=0.0):
    """Create a database span with standard OTel semantic attributes."""
    span_name = f"{db_system}.{operation}"
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("db.system", db_system)
        span.set_attribute("db.name", db_name)
        span.set_attribute("db.operation", operation)
        span.set_attribute("db.sql.table", table)
        if statement:
            span.set_attribute("db.statement", statement)
        sim_delay(min_ms, max_ms)
        if random.random() < error_rate:
            span.set_status(StatusCode.ERROR, f"{db_system} {operation} failed")
            span.set_attribute("error", True)
            return False
    return True


def http_span(tracer, method, url, min_ms=10, max_ms=80, error_rate=0.0):
    """Create an outbound HTTP span (external service call)."""
    span_name = f"{method} {url}"
    with tracer.start_as_current_span(span_name, kind=trace.SpanKind.CLIENT) as span:
        span.set_attribute("http.method", method)
        span.set_attribute("http.url", url)
        sim_delay(min_ms, max_ms)
        if random.random() < error_rate:
            span.set_attribute("http.status_code", 503)
            span.set_status(StatusCode.ERROR, "External service unavailable")
            return False
        span.set_attribute("http.status_code", 200)
    return True


def auth_span(tracer, customer_id):
    """Simulate NY.gov ID authentication."""
    with tracer.start_as_current_span("authenticate") as span:
        span.set_attribute("auth.provider", "ny.gov-id")
        span.set_attribute("customer.id", customer_id)
        sim_delay(15, 50)
        # Auth rarely fails
        if random.random() < 0.02:
            span.set_status(StatusCode.ERROR, "Authentication failed")
            return False
    return True


def payment_span(tracer, amount, method="credit_card", error_rate=0.05):
    """Simulate payment processing."""
    with tracer.start_as_current_span("process-payment") as span:
        span.set_attribute("payment.amount", amount)
        span.set_attribute("payment.currency", "USD")
        span.set_attribute("payment.method", method)
        sim_delay(80, 250)
        if random.random() < error_rate:
            span.set_status(StatusCode.ERROR, "Payment declined")
            span.set_attribute("error", True)
            return False
        span.set_attribute("payment.transaction_id", f"TXN-{random.randint(100000,999999)}")
    return True


@contextmanager
def parallel_fork(tracer, fork_name):
    """Context manager that creates a parent span for parallel work."""
    with tracer.start_as_current_span(fork_name) as span:
        span.set_attribute("fork.type", "parallel")
        yield span


def run_parallel(tracer, tasks):
    """
    Execute tasks in parallel, each inheriting the current span context.
    tasks: list of (callable, args) tuples.
    Returns list of results.
    """
    parent_ctx = otel_context.get_current()
    results = [None] * len(tasks)

    def _run(idx, fn, args):
        token = otel_context.attach(parent_ctx)
        try:
            results[idx] = fn(*args)
        finally:
            otel_context.detach(token)

    threads = []
    for i, (fn, args) in enumerate(tasks):
        t = threading.Thread(target=_run, args=(i, fn, args))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    return results


# ---------------------------------------------------------------------------
# Service 1: Renew Driver License
# ---------------------------------------------------------------------------

def renew_license(tracer, customer_id):
    """
    Flow: Auth -> Check Eligibility (Oracle) -> [XOR: eligible?]
          -> Vision Test Verify (MongoDB) -> Payment -> Issue License
    """
    with tracer.start_as_current_span("renew-driver-license") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "renew-license")

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            root.set_attribute("outcome", "auth_failed")
            return

        # Check eligibility — business task wrapping Oracle call
        with tracer.start_as_current_span("check-eligibility") as step:
            step.set_attribute("step.description", "Verify license renewal eligibility")
            eligible = db_span(tracer, "oracle", "NYDMV_LICENSES", "SELECT",
                               "DRIVER_LICENSE",
                               f"SELECT status, expiry FROM DRIVER_LICENSE WHERE id='{customer_id}'",
                               min_ms=15, max_ms=80)

        # XOR: eligible or not?
        is_eligible = eligible and random.random() < 0.85
        with tracer.start_as_current_span("xor-eligibility-check") as xor:
            xor.set_attribute("fork.type", "exclusive")
            xor.set_attribute("eligibility.result", "eligible" if is_eligible else "not_eligible")

        if not is_eligible:
            with tracer.start_as_current_span("send-rejection-notice") as rej:
                rej.set_attribute("notification.type", "email")
                sim_delay(10, 30)
            root.set_status(StatusCode.ERROR, "Not eligible for renewal")
            root.set_attribute("outcome", "rejected")
            return

        # Verify vision test — business task wrapping MongoDB call
        with tracer.start_as_current_span("verify-vision-test") as step:
            step.set_attribute("step.description", "Check optometrist vision test record")
            db_span(tracer, "mongodb", "dmv_vision", "find",
                    "vision_tests",
                    '{"customer_id": "' + customer_id + '", "valid": true}',
                    min_ms=8, max_ms=40)

        # Payment
        if not payment_span(tracer, 64.50):
            root.set_status(StatusCode.ERROR, "Payment failed")
            root.set_attribute("outcome", "payment_failed")
            return

        # Issue license — business task wrapping Oracle UPDATE
        with tracer.start_as_current_span("issue-license") as step:
            step.set_attribute("step.description", "Update license status and expiry")
            db_span(tracer, "oracle", "NYDMV_LICENSES", "UPDATE",
                    "DRIVER_LICENSE",
                    f"UPDATE DRIVER_LICENSE SET status='RENEWED', expiry=SYSDATE+3650 WHERE id='{customer_id}'",
                    min_ms=10, max_ms=50)

        with tracer.start_as_current_span("queue-license-fulfillment") as ful:
            ful.set_attribute("fulfillment.type", "mail")
            sim_delay(5, 15)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Service 2: Renew Vehicle Registration
# ---------------------------------------------------------------------------

def renew_registration(tracer, customer_id):
    """
    Flow: Auth -> PARALLEL[Check Reg (Oracle), Verify Insurance (ext API)]
          -> [XOR: insurance ok?] -> Calc Fees (Postgres) -> Payment -> Mail Sticker
    """
    with tracer.start_as_current_span("renew-vehicle-registration") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "renew-registration")
        plate = f"NYS-{random.choice('ABCDEFGH')}{random.randint(1000,9999)}"
        root.set_attribute("vehicle.plate", plate)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Parallel fork: check registration + verify insurance
        with parallel_fork(tracer, "parallel-reg-insurance-check"):
            def _check_registration():
                with tracer.start_as_current_span("check-registration") as step:
                    step.set_attribute("step.description", "Look up current registration")
                    return db_span(tracer, "oracle", "NYDMV_VEHICLES", "SELECT",
                                   "REGISTRATIONS",
                                   f"SELECT * FROM REGISTRATIONS WHERE plate='{plate}'",
                                   20, 90)

            def _verify_insurance():
                with tracer.start_as_current_span("verify-insurance") as step:
                    step.set_attribute("step.description", "Verify active insurance policy")
                    return http_span(tracer, "GET",
                                     "https://insuranceverify.ny.gov/api/v1/status",
                                     30, 120, 0.03)

            results = run_parallel(tracer, [
                (_check_registration, ()),
                (_verify_insurance, ()),
            ])

        reg_ok, insurance_ok = results

        # XOR: insurance valid?
        insurance_valid = insurance_ok and random.random() < 0.90
        with tracer.start_as_current_span("xor-insurance-check") as xor:
            xor.set_attribute("fork.type", "exclusive")
            xor.set_attribute("insurance.valid", insurance_valid)

        if not insurance_valid:
            with tracer.start_as_current_span("send-insurance-lapse-notice") as notice:
                notice.set_attribute("notification.type", "email")
                sim_delay(10, 25)
            with tracer.start_as_current_span("record-insurance-violation") as step:
                step.set_attribute("step.description", "Record insurance lapse violation")
                db_span(tracer, "oracle", "NYDMV_VEHICLES", "INSERT",
                        "INSURANCE_VIOLATIONS",
                        "INSERT INTO INSURANCE_VIOLATIONS ...",
                        min_ms=10, max_ms=40)
            root.set_status(StatusCode.ERROR, "Insurance lapsed")
            root.set_attribute("outcome", "insurance_lapsed")
            return

        # Calculate fees — business task wrapping Postgres call
        with tracer.start_as_current_span("calculate-fees") as step:
            step.set_attribute("step.description", "Look up applicable registration fees")
            db_span(tracer, "postgresql", "dmv_fees", "SELECT",
                    "fee_schedule",
                    "SELECT base_fee, county_fee, plate_fee FROM fee_schedule WHERE type='registration'",
                    min_ms=5, max_ms=25)

        if not payment_span(tracer, 73.00 + random.uniform(10, 40)):
            root.set_status(StatusCode.ERROR, "Payment failed")
            root.set_attribute("outcome", "payment_failed")
            return

        # Update registration — business task wrapping Oracle UPDATE
        with tracer.start_as_current_span("update-registration") as step:
            step.set_attribute("step.description", "Mark registration as renewed")
            db_span(tracer, "oracle", "NYDMV_VEHICLES", "UPDATE",
                    "REGISTRATIONS",
                    f"UPDATE REGISTRATIONS SET status='RENEWED' WHERE plate='{plate}'",
                    min_ms=10, max_ms=40)

        with tracer.start_as_current_span("queue-sticker-fulfillment") as ful:
            ful.set_attribute("fulfillment.type", "mail")
            sim_delay(5, 15)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Service 3: Schedule Road Test
# ---------------------------------------------------------------------------

def schedule_road_test(tracer, customer_id):
    """
    Flow: Auth -> Check Permit (Oracle) -> [XOR: permit valid?]
          -> Query Available Slots (MongoDB) -> Reserve Slot (MongoDB) -> Payment -> Confirm
    """
    with tracer.start_as_current_span("schedule-road-test") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "schedule-road-test")
        county = random.choice(["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island",
                                "Westchester", "Nassau", "Suffolk", "Albany", "Buffalo"])
        root.set_attribute("test.county", county)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Check permit — business task wrapping Oracle call
        with tracer.start_as_current_span("check-permit-status") as step:
            step.set_attribute("step.description", "Verify learner permit is valid")
            db_span(tracer, "oracle", "NYDMV_LICENSES", "SELECT",
                    "LEARNER_PERMITS",
                    f"SELECT status, issued_date FROM LEARNER_PERMITS WHERE customer_id='{customer_id}'",
                    min_ms=15, max_ms=70)

        # XOR: permit valid?
        permit_valid = random.random() < 0.80
        with tracer.start_as_current_span("xor-permit-check") as xor:
            xor.set_attribute("fork.type", "exclusive")
            xor.set_attribute("permit.valid", permit_valid)

        if not permit_valid:
            with tracer.start_as_current_span("reject-invalid-permit") as rej:
                rej.set_attribute("rejection.reason", "permit expired or not found")
                sim_delay(5, 15)
            root.set_status(StatusCode.ERROR, "Invalid permit")
            root.set_attribute("outcome", "invalid_permit")
            return

        # Find available slots — business task wrapping MongoDB query
        with tracer.start_as_current_span("find-available-slots") as step:
            step.set_attribute("step.description", "Search for open road test appointments")
            db_span(tracer, "mongodb", "dmv_scheduling", "find",
                    "road_test_slots",
                    '{"county": "' + county + '", "available": true, "date": {"$gte": "2026-04-01"}}',
                    min_ms=10, max_ms=50)

        # Reserve slot — business task wrapping MongoDB update
        with tracer.start_as_current_span("reserve-slot") as step:
            step.set_attribute("step.description", "Reserve selected appointment slot")
            db_span(tracer, "mongodb", "dmv_scheduling", "updateOne",
                    "road_test_slots",
                    '{"$set": {"available": false, "customer_id": "' + customer_id + '"}}',
                    min_ms=8, max_ms=35)

        # Payment for road test
        if not payment_span(tracer, 40.00):
            root.set_status(StatusCode.ERROR, "Payment failed")
            root.set_attribute("outcome", "payment_failed")
            return

        with tracer.start_as_current_span("send-confirmation") as conf:
            conf.set_attribute("notification.type", "email_and_sms")
            sim_delay(10, 30)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Service 4: Get Driving Record
# ---------------------------------------------------------------------------

def get_driving_record(tracer, customer_id):
    """
    Flow: Auth -> Query Records (Oracle) -> PARALLEL[Generate PDF, Calculate Points]
          -> Payment -> Deliver Document
    """
    with tracer.start_as_current_span("get-driving-record") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "get-driving-record")
        record_type = random.choice(["standard", "CDL", "lifetime"])
        root.set_attribute("record.type", record_type)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Query driving records — business task wrapping Oracle call
        with tracer.start_as_current_span("query-driving-history") as step:
            step.set_attribute("step.description", "Retrieve full driving history")
            db_span(tracer, "oracle", "NYDMV_RECORDS", "SELECT",
                    "DRIVING_HISTORY",
                    f"SELECT * FROM DRIVING_HISTORY WHERE customer_id='{customer_id}' ORDER BY event_date DESC",
                    min_ms=30, max_ms=150)

        # Parallel: generate PDF + calculate points
        with parallel_fork(tracer, "parallel-record-processing"):
            def generate_pdf():
                with tracer.start_as_current_span("generate-pdf") as span:
                    span.set_attribute("document.format", "PDF")
                    span.set_attribute("document.type", record_type)
                    sim_delay(50, 200)
                return True

            def calculate_points():
                with tracer.start_as_current_span("calculate-points") as step:
                    step.set_attribute("step.description", "Sum violation points in 18-month window")
                    return db_span(tracer, "oracle", "NYDMV_RECORDS", "SELECT",
                                   "VIOLATION_POINTS",
                                   f"SELECT SUM(points) FROM VIOLATION_POINTS WHERE customer_id='{customer_id}' AND date > SYSDATE-548",
                                   min_ms=10, max_ms=60)

            results = run_parallel(tracer, [
                (generate_pdf, ()),
                (calculate_points, ()),
            ])

        # Payment
        fee = {"standard": 10.00, "CDL": 10.00, "lifetime": 15.00}[record_type]
        if not payment_span(tracer, fee):
            root.set_status(StatusCode.ERROR, "Payment failed")
            root.set_attribute("outcome", "payment_failed")
            return

        with tracer.start_as_current_span("deliver-document") as deliver:
            deliver.set_attribute("delivery.method", "download")
            sim_delay(5, 20)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Service 5: Change Address
# ---------------------------------------------------------------------------

def change_address(tracer, customer_id):
    """
    Flow: Auth -> Validate Address (ext geocoding) ->
          PARALLEL[Update License DB, Update Registration DB, Update Title DB] -> Confirm
    """
    with tracer.start_as_current_span("change-address") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "change-address")
        new_zip = f"{random.randint(10001, 14975)}"
        root.set_attribute("address.new_zip", new_zip)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Validate address — business task wrapping external HTTP call
        with tracer.start_as_current_span("validate-address") as step:
            step.set_attribute("step.description", "Validate new address via NY geocoding service")
            addr_ok = http_span(tracer, "POST",
                                "https://geocoder.ny.gov/api/v2/validate",
                                min_ms=40, max_ms=150, error_rate=0.02)

        if not addr_ok:
            with tracer.start_as_current_span("reject-invalid-address") as rej:
                rej.set_attribute("rejection.reason", "address validation failed")
                sim_delay(5, 10)
            root.set_status(StatusCode.ERROR, "Invalid address")
            root.set_attribute("outcome", "invalid_address")
            return

        # Parallel 3-way fork: update all three Oracle databases
        with parallel_fork(tracer, "parallel-address-update"):
            def _update_license_db():
                with tracer.start_as_current_span("update-license-address") as step:
                    step.set_attribute("step.description", "Update address on driver license")
                    return db_span(tracer, "oracle", "NYDMV_LICENSES", "UPDATE",
                                   "DRIVER_LICENSE",
                                   f"UPDATE DRIVER_LICENSE SET address_zip='{new_zip}' WHERE customer_id='{customer_id}'",
                                   10, 50)

            def _update_registration_db():
                with tracer.start_as_current_span("update-registration-address") as step:
                    step.set_attribute("step.description", "Update address on vehicle registrations")
                    return db_span(tracer, "oracle", "NYDMV_VEHICLES", "UPDATE",
                                   "REGISTRATIONS",
                                   f"UPDATE REGISTRATIONS SET address_zip='{new_zip}' WHERE customer_id='{customer_id}'",
                                   10, 50)

            def _update_title_db():
                with tracer.start_as_current_span("update-title-address") as step:
                    step.set_attribute("step.description", "Update address on vehicle titles")
                    return db_span(tracer, "oracle", "NYDMV_TITLES", "UPDATE",
                                   "VEHICLE_TITLES",
                                   f"UPDATE VEHICLE_TITLES SET address_zip='{new_zip}' WHERE customer_id='{customer_id}'",
                                   10, 50)

            results = run_parallel(tracer, [
                (_update_license_db, ()),
                (_update_registration_db, ()),
                (_update_title_db, ()),
            ])

        with tracer.start_as_current_span("send-confirmation") as conf:
            conf.set_attribute("notification.type", "email")
            sim_delay(5, 15)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Service 6: Pay TVB Ticket
# ---------------------------------------------------------------------------

def pay_tvb_ticket(tracer, customer_id):
    """
    Flow: Auth -> Lookup Ticket (MongoDB) -> [XOR: found?]
          -> [XOR: plea type?]
             guilty:     Calc Fine -> Payment -> Update Record (Oracle)
             not-guilty: Schedule Hearing (MongoDB)
    """
    with tracer.start_as_current_span("pay-tvb-ticket") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "pay-tvb-ticket")
        ticket_num = f"TVB-{random.randint(2000000, 9999999)}"
        root.set_attribute("ticket.number", ticket_num)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Lookup ticket — business task wrapping MongoDB call
        with tracer.start_as_current_span("lookup-ticket") as step:
            step.set_attribute("step.description", "Search for ticket in TVB system")
            db_span(tracer, "mongodb", "dmv_tickets", "findOne",
                    "tvb_tickets",
                    '{"ticket_number": "' + ticket_num + '"}',
                    min_ms=8, max_ms=40)

        # XOR: ticket found?
        ticket_found = random.random() < 0.92
        with tracer.start_as_current_span("xor-ticket-lookup") as xor:
            xor.set_attribute("fork.type", "exclusive")
            xor.set_attribute("ticket.found", ticket_found)

        if not ticket_found:
            with tracer.start_as_current_span("return-not-found") as nf:
                nf.set_attribute("error.detail", "Ticket not found in TVB system")
                sim_delay(3, 10)
            root.set_status(StatusCode.ERROR, "Ticket not found")
            root.set_attribute("outcome", "not_found")
            return

        # XOR: plea type?
        plea = random.choice(["guilty", "guilty", "guilty", "not_guilty"])  # 75% guilty
        with tracer.start_as_current_span("xor-plea-type") as xor:
            xor.set_attribute("fork.type", "exclusive")
            xor.set_attribute("plea.type", plea)

        if plea == "guilty":
            # Calculate fine
            with tracer.start_as_current_span("calculate-fine") as calc:
                calc.set_attribute("violation.type",
                                   random.choice(["speeding", "red_light", "cell_phone", "failure_to_yield"]))
                sim_delay(5, 20)
                fine = random.choice([80, 100, 150, 200, 250])
                calc.set_attribute("fine.amount", fine)

            if not payment_span(tracer, fine):
                root.set_status(StatusCode.ERROR, "Payment failed")
                root.set_attribute("outcome", "payment_failed")
                return

            # Update violation record — business task wrapping Oracle call
            with tracer.start_as_current_span("record-violation-points") as step:
                step.set_attribute("step.description", "Add points to driving record")
                db_span(tracer, "oracle", "NYDMV_RECORDS", "UPDATE",
                        "VIOLATION_POINTS",
                        f"INSERT INTO VIOLATION_POINTS (customer_id, ticket, points, date) VALUES ('{customer_id}', '{ticket_num}', 3, SYSDATE)",
                        min_ms=10, max_ms=50)

            root.set_attribute("outcome", "paid")

        else:
            # Schedule hearing — business task wrapping MongoDB call
            with tracer.start_as_current_span("schedule-hearing") as step:
                step.set_attribute("step.description", "Create hearing record for not-guilty plea")
                db_span(tracer, "mongodb", "dmv_tickets", "updateOne",
                        "tvb_hearings",
                        '{"$set": {"ticket": "' + ticket_num + '", "plea": "not_guilty", "status": "hearing_scheduled"}}',
                        min_ms=10, max_ms=40)

            with tracer.start_as_current_span("send-hearing-notice") as notice:
                notice.set_attribute("notification.type", "certified_mail")
                sim_delay(5, 15)

            root.set_attribute("outcome", "hearing_scheduled")


# ---------------------------------------------------------------------------
# Service 7: Order Personalized Plates
# ---------------------------------------------------------------------------

def order_personalized_plates(tracer, customer_id):
    """
    Flow: Auth -> Check Availability (MongoDB) -> [XOR: available?]
          -> Reserve Combo (MongoDB) -> Payment -> Submit Fulfillment (Postgres)
    """
    with tracer.start_as_current_span("order-personalized-plates") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "order-personalized-plates")
        combo = random.choice(["ILOVENY", "BIGAPPL", "JETS4VR", "YANKS1",
                                "NYDMV1", "METSFAN", "GDFISH", "BKLN99"])
        root.set_attribute("plate.requested", combo)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Check availability — business task wrapping MongoDB call
        with tracer.start_as_current_span("check-plate-availability") as step:
            step.set_attribute("step.description", "Check if plate combination is available")
            db_span(tracer, "mongodb", "dmv_plates", "findOne",
                    "plate_combinations",
                    '{"combo": "' + combo + '", "status": "available"}',
                    min_ms=5, max_ms=30)

        # XOR: available?
        available = random.random() < 0.65
        with tracer.start_as_current_span("xor-availability-check") as xor:
            xor.set_attribute("fork.type", "exclusive")
            xor.set_attribute("plate.available", available)

        if not available:
            # Suggest alternatives — business task wrapping MongoDB query
            with tracer.start_as_current_span("suggest-alternatives") as step:
                step.set_attribute("step.description", "Find similar available combinations")
                db_span(tracer, "mongodb", "dmv_plates", "find",
                        "plate_combinations",
                        '{"combo": {"$regex": "^' + combo[:3] + '"}, "status": "available", "$limit": 5}',
                        min_ms=10, max_ms=50)

            with tracer.start_as_current_span("return-alternatives") as alt:
                alt.set_attribute("alternatives.count", random.randint(2, 5))
                sim_delay(3, 10)

            root.set_attribute("outcome", "unavailable")
            return

        # Reserve the combination — business task wrapping MongoDB update
        with tracer.start_as_current_span("reserve-plate-combo") as step:
            step.set_attribute("step.description", "Reserve plate combination for customer")
            db_span(tracer, "mongodb", "dmv_plates", "updateOne",
                    "plate_combinations",
                    '{"$set": {"status": "reserved", "customer_id": "' + customer_id + '"}}',
                    min_ms=5, max_ms=25)

        # Payment
        if not payment_span(tracer, 60.00):
            root.set_status(StatusCode.ERROR, "Payment failed")
            root.set_attribute("outcome", "payment_failed")
            return

        # Submit fulfillment — business task wrapping Postgres INSERT
        with tracer.start_as_current_span("submit-plate-order") as step:
            step.set_attribute("step.description", "Submit manufacturing order for plates")
            db_span(tracer, "postgresql", "dmv_fulfillment", "INSERT",
                    "plate_orders",
                    "INSERT INTO plate_orders (customer_id, combo, plate_type, status) VALUES ...",
                    min_ms=10, max_ms=40)

        with tracer.start_as_current_span("queue-manufacturing") as mfg:
            mfg.set_attribute("fulfillment.estimated_weeks", random.randint(4, 8))
            sim_delay(5, 15)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Service 8: Check Registration Status
# ---------------------------------------------------------------------------

def check_registration_status(tracer, customer_id):
    """
    Flow: Auth -> Query Registration (Oracle) ->
          PARALLEL[Check Insurance Status, Check Inspection Status] -> Return Status
    """
    with tracer.start_as_current_span("check-registration-status") as root:
        root.set_attribute("customer.id", customer_id)
        root.set_attribute("dmv.transaction", "check-registration-status")
        plate = f"NYS-{random.choice('ABCDEFGH')}{random.randint(1000,9999)}"
        root.set_attribute("vehicle.plate", plate)

        if not auth_span(tracer, customer_id):
            root.set_status(StatusCode.ERROR, "Auth failed")
            return

        # Query registration — business task wrapping Oracle call
        with tracer.start_as_current_span("query-registration") as step:
            step.set_attribute("step.description", "Look up vehicle registration by plate")
            db_span(tracer, "oracle", "NYDMV_VEHICLES", "SELECT",
                    "REGISTRATIONS",
                    f"SELECT * FROM REGISTRATIONS WHERE plate='{plate}'",
                    min_ms=15, max_ms=60)

        # Parallel: check insurance + check inspection
        with parallel_fork(tracer, "parallel-status-checks"):
            def check_insurance():
                with tracer.start_as_current_span("check-insurance-status") as step:
                    step.set_attribute("step.description", "Verify insurance with state registry")
                    return http_span(tracer, "GET",
                                     "https://insuranceverify.ny.gov/api/v1/status",
                                     min_ms=20, max_ms=100)

            def check_inspection():
                with tracer.start_as_current_span("check-inspection-status") as step:
                    step.set_attribute("step.description", "Check last inspection record")
                    return db_span(tracer, "oracle", "NYDMV_VEHICLES", "SELECT",
                                   "INSPECTION_RECORDS",
                                   f"SELECT last_inspection, result FROM INSPECTION_RECORDS WHERE plate='{plate}'",
                                   min_ms=10, max_ms=50)

            results = run_parallel(tracer, [
                (check_insurance, ()),
                (check_inspection, ()),
            ])

        with tracer.start_as_current_span("compile-status-response") as resp:
            resp.set_attribute("registration.active", True)
            resp.set_attribute("insurance.verified", bool(results[0]))
            resp.set_attribute("inspection.current", bool(results[1]))
            sim_delay(3, 10)

        root.set_attribute("outcome", "completed")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# All 8 services with relative traffic weights (realistic distribution)
SERVICES = [
    ("nydmv-license-service",      renew_license,              20),   # high traffic
    ("nydmv-registration-service", renew_registration,         25),   # highest
    ("nydmv-road-test-service",    schedule_road_test,         10),
    ("nydmv-records-service",      get_driving_record,         12),
    ("nydmv-address-service",      change_address,             15),
    ("nydmv-ticket-service",       pay_tvb_ticket,              8),
    ("nydmv-plates-service",       order_personalized_plates,   5),
    ("nydmv-registration-service", check_registration_status,  18),   # same svc as renew
]


def setup_provider(service_name, endpoint):
    """Create an OTel TracerProvider for a given service."""
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "1.0.0",
        "deployment.environment": "dev",
        "service.namespace": "nydmv",
    })
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def main():
    parser = argparse.ArgumentParser(description="NY DMV Online Services - Trace Simulation")
    parser.add_argument("--endpoint", default="http://localhost:4317", help="OTel Collector OTLP gRPC endpoint")
    parser.add_argument("--count", type=int, default=30, help="Total number of transactions to simulate")
    args = parser.parse_args()

    print(f"NY DMV Trace Simulation")
    print(f"  Endpoint: {args.endpoint}")
    print(f"  Transactions: {args.count}")
    print()

    # Build weighted list for random selection
    weighted = []
    for svc_name, fn, weight in SERVICES:
        weighted.extend([(svc_name, fn)] * weight)

    # Create providers per unique service name
    unique_services = {svc_name for svc_name, _, _ in SERVICES}
    providers = {}
    for svc_name in unique_services:
        providers[svc_name] = setup_provider(svc_name, args.endpoint)

    # Stats
    stats = {}

    for i in range(args.count):
        svc_name, fn = random.choice(weighted)
        provider = providers[svc_name]

        # Get tracer directly from this service's provider (avoids global override)
        tracer = provider.get_tracer(svc_name)

        customer_id = f"NYS-{random.randint(10000000, 99999999)}"

        fn(tracer, customer_id)

        short_name = fn.__name__
        stats[short_name] = stats.get(short_name, 0) + 1
        print(f"  [{i+1}/{args.count}] {svc_name} / {short_name} (customer {customer_id})")
        time.sleep(random.uniform(0.1, 0.4))

    # Shutdown all providers
    for provider in providers.values():
        provider.shutdown()

    print(f"\nTransaction summary:")
    for name, count in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")
    print(f"\nDone. Run trace_to_bpmn.py to generate BPMN 2.0 XML from these traces.")


if __name__ == "__main__":
    main()
