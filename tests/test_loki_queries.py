#!/usr/bin/env python3
"""Test various Loki queries to find errors."""

import urllib.request
import json
import time
import urllib.parse

end_ns = int(time.time() * 1e9)
start_ns = int((time.time() - 2*3600) * 1e9)

# Test different queries
queries = [
    '{service_name="Amp-MM - Invenio"}',
    '{service_name="Amp-MM - Invenio"} |= "sql_error"',
    '{service_name="Amp-MM - Invenio", level="ERROR"}',
]

for q in queries:
    try:
        eq = urllib.parse.quote(q)
        url = f'http://localhost:3100/loki/api/v1/query_range?query={eq}&start={start_ns}&end={end_ns}&limit=10&direction=backward'
        r = urllib.request.urlopen(url, timeout=10)
        data = json.loads(r.read().decode())
        status = data.get('status')
        results = data.get('data', {}).get('result', [])
        hits = sum(len(r.get('values', [])) for r in results)
        print(f'{q[:60]}: status={status} hits={hits}')
        if hits > 0 and results:
            # Print first result
            first_val = results[0].get('values', [])[0] if results[0].get('values') else None
            if first_val:
                print(f'  First: {first_val[1][:100]}')
    except Exception as e:
        print(f'{q[:60]}: ERROR - {e}')
