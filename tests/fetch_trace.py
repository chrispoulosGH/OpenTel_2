"""Quick script to fetch and print a trace's span tree from Tempo."""
import urllib.request, json

# Get a trace ID
r = urllib.request.urlopen('http://localhost:3200/api/search?limit=1')
search = json.loads(r.read().decode())
tid = search['traces'][0]['traceID']
print(f"Trace ID: {tid}\n")

# Fetch full trace
r = urllib.request.urlopen(f'http://localhost:3200/api/traces/{tid}')
data = json.loads(r.read().decode())

for batch in data.get('batches', []):
    res = batch.get('resource', {})
    svc = 'unknown'
    for attr in res.get('attributes', []):
        if attr['key'] == 'service.name':
            svc = attr['value'].get('stringValue', '')
    for scope_spans in batch.get('scopeSpans', []):
        for span in scope_spans.get('spans', []):
            dur_ns = int(span['endTimeUnixNano']) - int(span['startTimeUnixNano'])
            print(f"svc={svc}  span={span['name']}  spanId={span['spanId']}  parentSpanId={span.get('parentSpanId','')}  dur_ms={dur_ns/1e6:.1f}")
            for attr in span.get('attributes', []):
                key = attr['key']
                val = attr['value'].get('stringValue') or attr['value'].get('intValue') or attr['value'].get('doubleValue') or attr['value'].get('boolValue', '')
                print(f"    {key} = {val}")
