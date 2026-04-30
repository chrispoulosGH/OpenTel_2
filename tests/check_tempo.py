import urllib.request, json, time
time.sleep(3)
r = urllib.request.urlopen('http://localhost:3200/api/search?limit=50')
d = json.loads(r.read().decode())
print(f"Traces found: {d['metrics']['inspectedTraces']}")
for t in d['traces'][:20]:
    svc = t.get('rootServiceName', '?')
    name = t.get('rootTraceName', '?')
    dur = t.get('durationMs', 0)
    print(f"  {svc:35s} {name:40s} {dur}ms")
