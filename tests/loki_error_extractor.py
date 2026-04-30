"""
Loki Error Extractor
====================
Queries Loki API to extract error logs by service.
Provides error data for enriching BPMN XML with error metadata.

Usage:
    from loki_error_extractor import query_errors_per_service, ErrorRecord
    
    errors_by_service = query_errors_per_service(
        loki_url="http://localhost:3100",
        hours_back=2
    )
    
    for service_name, error_records in errors_by_service.items():
        for error in error_records:
            print(f"{service_name}: {error.message}")
"""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta


@dataclass
class ErrorRecord:
    """Serializable error metadata extracted from Loki logs."""
    timestamp: str          # ISO format timestamp
    timestamp_ns: int       # Nanoseconds since epoch
    service_name: str
    level: str              # ERROR, WARN, etc.
    event: str              # sql_error, etc.
    message: str            # Log message
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)


def _parse_kv_pairs(text: str) -> Dict[str, str]:
    """Parse key=value pairs from plaintext log content."""
    parsed: Dict[str, str] = {}
    for match in re.finditer(r"(\w+)=([^\s]+)", text):
        key = match.group(1).strip()
        value = match.group(2).strip().strip('"\'')
        parsed[key] = value
    return parsed


def _parse_log_message(log_text: str) -> Dict[str, str]:
    """
    Parse structured log message to extract key-value pairs.

    Handles both:
    - Plain text: level=ERROR event=sql_error trace_id=...
    - Loki JSON-wrapped logs: {"body":"...key=value...","trace_id":"..."}
    """
    data: Dict[str, str] = {}

    # Try JSON first (common Loki format for OTLP logs)
    try:
        payload = json.loads(log_text)
        if isinstance(payload, dict):
            for key in ("trace_id", "span_id", "level", "severity_text", "event", "service"):
                value = payload.get(key)
                if value is not None:
                    data[key] = str(value)

            body = payload.get("body")
            if isinstance(body, str):
                data.update(_parse_kv_pairs(body))
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback to plain-text parsing
    if not data:
        data.update(_parse_kv_pairs(log_text))

    # Normalize severity field names
    if "level" not in data and "severity_text" in data:
        data["level"] = data["severity_text"]

    return data


def query_service_names(
    loki_url: str = "http://localhost:3100",
    hours_back: int = 2,
) -> List[str]:
    """
    Query Loki labels API to discover all unique service names.
    Returns list of distinct service_name label values.
    """
    try:
        # Calculate time range (Loki uses nanoseconds)
        end_ns = int(datetime.utcnow().timestamp() * 1e9)
        start_ns = int((datetime.utcnow() - timedelta(hours=hours_back)).timestamp() * 1e9)

        # Query labels endpoint for service_name label values
        url = f"{loki_url}/loki/api/v1/label/service_name/values?start={start_ns}&end={end_ns}"
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode())

        services = data.get("data", [])
        return sorted(set(services))
    except Exception as e:
        print(f"Error querying service names from Loki: {e}")
        return []


def query_errors_for_service(
    service_name: str,
    loki_url: str = "http://localhost:3100",
    hours_back: int = 2,
    limit: int = 100,
) -> List[ErrorRecord]:
    """
    Query Loki for logs from a specific service and extract ERROR/sql_error entries.
    Searches message content for error indicators since level label may not be set.
    Returns list of ErrorRecord objects.
    """
    try:
        # Calculate time range (Loki uses nanoseconds)
        end_ns = int(datetime.utcnow().timestamp() * 1e9)
        start_ns = int((datetime.utcnow() - timedelta(hours=hours_back)).timestamp() * 1e9)

        # Build LogQL query: look for service and filter for errors in message
        # Note: LogQL doesn't support OR in filters, so we query all and filter in Python
        logql_query = f'{{service_name="{service_name}"}}'
        encoded_query = urllib.parse.quote(logql_query)

        url = (
            f"{loki_url}/loki/api/v1/query_range"
            f"?query={encoded_query}"
            f"&start={start_ns}"
            f"&end={end_ns}"
            f"&limit={limit}"
            f"&direction=backward"
        )

        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode())

        errors = []
        status = data.get("status")
        if status != "success":
            print(f"Loki query failed for {service_name}: {data.get('error', 'unknown error')}")
            return errors

        results = data.get("data", {}).get("result", [])
        for result in results:
            values = result.get("values", [])
            for timestamp_ns_str, log_text in values:
                timestamp_ns = int(timestamp_ns_str)
                timestamp_s = timestamp_ns / 1e9
                timestamp = datetime.utcfromtimestamp(timestamp_s).isoformat() + "Z"

                # Check if log contains error indicators
                log_lower = log_text.lower()
                if not any(indicator in log_lower for indicator in ["error", "sql_error", "event=sql_error"]):
                    continue

                # Parse log message for structured data
                parsed = _parse_log_message(log_text)
                
                error = ErrorRecord(
                    timestamp=timestamp,
                    timestamp_ns=timestamp_ns,
                    service_name=service_name,
                    level=parsed.get("level", "ERROR"),
                    event=parsed.get("event", "unknown"),
                    message=log_text,
                    trace_id=parsed.get("trace_id"),
                    span_id=parsed.get("span_id"),
                    attributes=parsed,
                )
                errors.append(error)

        return errors
    except urllib.error.URLError as e:
        print(f"Network error querying Loki for {service_name}: {e}")
        return []
    except Exception as e:
        print(f"Error querying Loki for {service_name}: {e}")
        return []


def query_errors_per_service(
    loki_url: str = "http://localhost:3100",
    hours_back: int = 2,
    limit: int = 100,
) -> Dict[str, List[ErrorRecord]]:
    """
    Query Loki to extract all ERROR logs grouped by service name.
    Returns dict mapping service_name -> list of ErrorRecord objects.
    """
    services = query_service_names(loki_url=loki_url, hours_back=hours_back)
    if not services:
        print(f"No services found in Loki within last {hours_back} hours")
        return {}

    print(f"Found {len(services)} services in Loki")

    errors_by_service = {}
    for service_name in services:
        errors = query_errors_for_service(
            service_name,
            loki_url=loki_url,
            hours_back=hours_back,
            limit=limit,
        )
        if errors:
            errors_by_service[service_name] = errors
            print(f"  {service_name}: {len(errors)} error(s)")

    return errors_by_service


def get_errors_for_service_if_any(
    service_name: str,
    errors_by_service: Dict[str, List[ErrorRecord]],
) -> List[ErrorRecord]:
    """
    Safely retrieve errors for a service from the lookup dict.
    Returns empty list if service has no errors.
    """
    return errors_by_service.get(service_name, [])
