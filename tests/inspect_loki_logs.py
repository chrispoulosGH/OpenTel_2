#!/usr/bin/env python3
"""Inspect actual logs from Loki."""

import urllib.request
import json
import time
import urllib.parse

end_ns = int(time.time() * 1e9)
start_ns = int((time.time() - 2*3600) * 1e9)

# Query all logs from service
q = '{service_name="Amp-MM - Invenio"}'
eq = urllib.parse.quote(q)
url = f'http://localhost:3100/loki/api/v1/query_range?query={eq}&start={start_ns}&end={end_ns}&limit=10&direction=backward'

print(f"Querying: {url}\n")
r = urllib.request.urlopen(url, timeout=10)
data = json.loads(r.read().decode())
results = data.get('data', {}).get('result', [])

print(f"Found {len(results)} result stream(s)\n")
for i, result in enumerate(results):
    print(f"Stream {i+1}:")
    stream = result.get('stream', {})
    for key, val in stream.items():
        print(f"  {key}: {val}")
    
    values = result.get('values', [])
    print(f"  Values: {len(values)} log entries")
    for ts, msg in values[:5]:
        print(f"    TS: {ts}")
        print(f"    MSG: {msg[:150]}")
    print()
