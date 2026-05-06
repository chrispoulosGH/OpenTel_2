#!/usr/bin/env python3
import requests
import json
import urllib.parse
from datetime import datetime, timedelta

end_ns = int(datetime.utcnow().timestamp() * 1e9)
start_ns = int((datetime.utcnow() - timedelta(hours=24)).timestamp() * 1e9)

# Query for all services - check if there are any ERROR level logs
logql_query = '{level="ERROR"}'
# Don't quote the query - let requests handle URL encoding
url = f"http://localhost:3100/loki/api/v1/query_range?query={urllib.parse.quote(logql_query)}&start={start_ns}&end={end_ns}&limit=5&direction=backward"

try:
    r = requests.get(url, timeout=20)
    print(f"Status code: {r.status_code}")
    print(f"Response text (first 500 chars):\n{r.text[:500]}")
    
    if r.status_code == 200:
        data = r.json()
        results = data.get('data', {}).get('result', [])
        if results:
            print(f"\nFound {len(results)} result(s)")
            first_log = results[0]['values'][0][1]
            print("Sample ERROR level log:")
            print(first_log[:300] + "...")
        else:
            print("No ERROR level logs found in Loki")
            print("\nChecking available log levels...")
            logql_query2 = '{service_name="ABPT"}'
            url2 = f"http://localhost:3100/loki/api/v1/query_range?query={urllib.parse.quote(logql_query2)}&start={start_ns}&end={end_ns}&limit=1&direction=backward"
            r2 = requests.get(url2, timeout=20)
            if r2.status_code == 200:
                data2 = r2.json()
                results2 = data2.get('data', {}).get('result', [])
                if results2:
                    stream = results2[0]['stream']
                    print(f"  Available labels: {stream}")
                    level = stream.get('level', 'NOT_SET')
                    print(f"  ABPT logs have level={level}")

except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
