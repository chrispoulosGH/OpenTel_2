import json

data = json.load(open('output/flows_all_bpmn2.0.json'))

events = [x for x in data['diagram'] if x.get('type') == 'event']
tasks = [x for x in data['diagram'] if x.get('type') == 'task']
gateways = [x for x in data['diagram'] if x.get('type') in {'parallel', 'parallelGateway'}]
flows = [x for x in data['diagram'] if x.get('type') == 'flow']

print("=== Structure Verification ===")
print(f"Events: {len(events)}")
for e in events:
    print(f"  - {e.get('name')} (id: {e.get('id')})")

print(f"\nTasks: {len(tasks)}")
shared_tasks = [t for t in tasks if 'Shared' in t.get('id', '')]
branch_tasks = [t for t in tasks if 'Shared' not in t.get('id', '')]
print(f"  - Shared: {len(shared_tasks)}")
for t in shared_tasks:
    print(f"    - {t.get('name')} ({t.get('id')})")
print(f"  - Branch tasks: {len(branch_tasks)}")

print(f"\nGateways: {len(gateways)}")
for g in gateways:
    print(f"  - {g.get('name')} ({g.get('id')}, type: {g.get('type')})")

print(f"\nFlows: {len(flows)}")
print(f"  - Start to ABPT: {any('Flow_Start_to_ABPT' in f.get('id', '') for f in flows)}")
print(f"  - ABPT to Fork: {any('Flow_ABPT_to_Fork' in f.get('id', '') for f in flows)}")
print(f"  - Fork to branches: {len([f for f in flows if f.get('sourceRef') == 'ParGW_Fork_Shared'])}")
print(f"  - Branches to Join: {len([f for f in flows if f.get('targetRef') == 'ParGW_Join_Shared'])}")
print(f"  - Join to TDICE: {any('Flow_Join_to_TDICE' in f.get('id', '') for f in flows)}")
print(f"  - TDICE to End: {any('Flow_TDICE_to_End' in f.get('id', '') for f in flows)}")

print(f"\nTotal records: {len(data['diagram'])}")
