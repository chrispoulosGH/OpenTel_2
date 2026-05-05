import urllib.request as R
import urllib.parse as P
import json
import time

svc = "Amp-MM - Invenio"
end_ns = int(time.time() * 1e9)
start_ns = end_ns - int(6 * 3600 * 1e9)

# Raw logs for service
query = '{service_name="' + svc + '"}'
enc = P.quote(query)
url = f"http://localhost:3100/loki/api/v1/query_range?query={enc}&start={start_ns}&end={end_ns}&limit=10&direction=backward"
try:
    resp = R.urlopen(url, timeout=10)
    data = json.loads(resp.read())
    results = data.get("data", {}).get("result", [])
    print(f"=== Raw Loki logs for '{svc}' ===")
    print(f"Stream count: {len(results)}")
    for s in results:
        print("Labels:", s.get("stream", {}))
        for ts, line in s.get("values", []):
            print(" LINE:", line[:300])
except Exception as e:
    print("ERROR:", e)

# Also check what query_errors_for_service does with a bigger limit
print("\n=== query_errors_for_service (hours_back=8, limit=100) ===")
from loki_error_extractor import query_errors_for_service
errors = query_errors_for_service(svc, hours_back=8, limit=100)
print("count:", len(errors))
for e in errors:
    print(f"  trace_id={repr(e.trace_id)} span_id={repr(e.span_id)} event={e.event}")
    print(f"    msg: {e.message[:150]}")
