# Loki Error Extraction & BPMN XML Enrichment

## Overview

This implementation integrates error data from Loki logs into BPMN 2.0 XML diagrams. Error logs are queried by service name and embedded as extension elements in service tasks.

## Components Created

### 1. Loki Error Extractor Module
**File:** [`loki_error_extractor.py`](loki_error_extractor.py)

Core functions:
- `query_service_names()` - Discovers all unique services in Loki
- `query_errors_for_service(service_name)` - Extracts error logs for a service
- `query_errors_per_service()` - Queries all services for errors
- `get_errors_for_service_if_any()` - Safe lookup for error data

**Error Record Structure:**
```python
@dataclass
class ErrorRecord:
    timestamp: str          # ISO format timestamp
    timestamp_ns: int       # Nanoseconds since epoch
    service_name: str
    level: str              # ERROR, WARN, etc.
    event: str              # sql_error, etc.
    message: str            # Full log message
    trace_id: Optional[str]
    span_id: Optional[str]
    attributes: Dict[str, str]  # Parsed key=value pairs from log
```

### 2. BPMN Generation Enhancements
**File:** [`trace_to_bpmn2.py`](trace_to_bpmn2.py)

**New Methods:**
- `BPMNBuilder._add_error_extensions(element, error_data)` - Adds error metadata to XML
- Updated `_add_element()` to accept and process `error_data`
- Updated `_emit_nodes()` to lookup errors per service
- Updated `add_process()` to pass errors through the flow

**New CLI Arguments:**
```bash
--loki-url http://localhost:3100        # Loki backend URL
--loki-hours-back 2                     # Time window for error search
```

## Usage

### Generate BPMN with Error Enrichment

```bash
cd c:\code\openTel_2\tests
python trace_to_bpmn2.py \
    --tempo-url http://localhost:3200 \
    --loki-url http://localhost:3100 \
    --loki-hours-back 2 \
    --limit 10 \
    --output flows_with_errors.xml
```

### Query Errors Directly

```python
from loki_error_extractor import query_errors_per_service

errors_by_service = query_errors_per_service(
    loki_url="http://localhost:3100",
    hours_back=2
)

for service, errors in errors_by_service.items():
    print(f"{service}: {len(errors)} error(s)")
    for error in errors:
        print(f"  {error.timestamp}: {error.event}")
        print(f"  {error.message}")
```

## XML Output Structure

### Service Task with Error Extension
```xml
<serviceTask id="Task_5" name="Amp-MM - Invenio">
  <extensionElements>
    <otel:spanDataSet>
      <!-- Trace span data -->
    </otel:spanDataSet>
    
    <otel:errorDataSet>
      <otel:errorRecord 
        timestamp="2026-04-29T14:30:45.123Z"
        service="Amp-MM - Invenio"
        level="ERROR"
        event="sql_error"
        traceId="43f1cc297125bbc256d743e2bc1e0f25"
        spanId="xyz123">
        
        <otel:message>
          service=Amp-MM - Invenio level=ERROR event=sql_error 
          column not found in table db_e.main_table
        </otel:message>
        
        <otel:attributes>
          <otel:attribute key="db.operation" value="SELECT" />
          <otel:attribute key="db.table" value="main_table" />
        </otel:attributes>
      </otel:errorRecord>
    </otel:errorDataSet>
  </extensionElements>
</serviceTask>
```

## Data Flow

```
Loki Backend (localhost:3100)
         ↓
    query_service_names()  → Discover services in Loki
         ↓
    query_errors_for_service(service_name)  → Extract ERROR logs
         ↓
         ↓ LogQL Query
         ↓ {service_name="<svc>"} filters all logs
         ↓ Python client filters for "error", "sql_error" in message
         ↓
    ErrorRecord objects
         ↓
         ↓ Passed to trace_to_bpmn2.py
         ↓
    _add_error_extensions() → Create XML error elements
         ↓
    BPMN XML with Error Metadata
```

## Log Query Strategy

**Loki Label Query:**
```
{service_name="Amp-MM - Invenio"}
```

**Python Filtering:**
- Searches message body for indicators: "error", "ERROR", "sql_error", "event=sql_error"
- Parses structured key=value pairs from log message
- Extracts: level, event, trace_id, span_id, custom attributes

**Why This Approach:**
- Loki labels may not include `level=ERROR` if not explicitly set by exporter
- Message body contains full structured log information
- More flexible for various logging patterns

## Error Parsing

Logs are parsed for structured attributes using pattern: `key=value`

Example log message:
```
service=Amp-MM - Invenio level=ERROR event=sql_error 
trace_id=43f1cc297125bbc256d743e2bc1e0f25 
message="column not found in table"
```

Parsed into:
```python
{
    'service': 'Amp-MM - Invenio',
    'level': 'ERROR',
    'event': 'sql_error',
    'trace_id': '43f1cc297125bbc256d743e2bc1e0f25',
    'message': 'column not found in table'
}
```

## Integration Points

### 1. Service Task Identification
- Service name extracted from first span in task's `span_data`
- Used to lookup errors: `errors_by_service[service_name]`

### 2. Error Attachment
- Errors added via `_add_error_extensions()`
- Creates sibling `errorDataSet` element alongside `spanDataSet`
- Multiple errors per service supported

### 3. Trace Correlation
- Error records include `trace_id` and `span_id`
- Can be matched back to OTEL spans for correlation
- Enriches error context with trace metadata

## Testing

**Test Files:**
- [`test_loki_queries.py`](test_loki_queries.py) - Validates LogQL queries
- [`inspect_loki_logs.py`](inspect_loki_logs.py) - Inspects log structure
- [`loki_error_extractor.py`](loki_error_extractor.py) - Can be imported and tested

**Test Service Discovery:**
```python
python -c "from loki_error_extractor import query_service_names; \
  print(query_service_names())"
```

**Test Error Extraction:**
```python
python -c "from loki_error_extractor import query_errors_for_service; \
  errors = query_errors_for_service('Amp-MM - Invenio'); \
  print(f'Errors: {len(errors)}')"
```

## Generated XML Files

- `flows_with_errors.xml` - Main merged BPMN with all services
- `<chain_id>_flow.xml` - Individual trace BPMN files (one per unique chain)
- `Business_Process_Flow_High_Level.xml` - High-level summary

All include error extension elements where applicable.

## Next Steps

1. **Verify Error Capture:** Ensure SQL error scenarios trigger logging
   - Run: `python run_abpt_chains.py --chain test_scenario_X --runs 3`
   - Verify logs reach Loki

2. **View in BPMN Modeler:** Import generated XML into:
   - Camunda Modeler
   - Bizagi Studio
   - bpmn.js viewer
   - Error metadata visible in extension elements

3. **Dashboard Integration:** Query error extension elements for:
   - Error timeline per service
   - Root cause analysis
   - Performance correlation

4. **Custom Analysis:** Parse XML and extract:
   ```python
   import xml.etree.ElementTree as ET
   tree = ET.parse('flows_with_errors.xml')
   root = tree.getroot()
   
   for task in root.findall('.//{*}serviceTask'):
       service_name = task.get('name')
       errors = task.find('.//{*}errorDataSet')
       if errors is not None:
           print(f"{service_name}: {len(errors)} errors")
   ```

## Architecture Notes

- **Stateless:** Error extraction happens at BPMN generation time
- **Async:** Loki queries don't block trace processing
- **Scalable:** Handles multiple services and high error volumes
- **Extensible:** Error record structure can be enhanced with additional fields
- **Retryable:** Network errors logged but don't fail XML generation
