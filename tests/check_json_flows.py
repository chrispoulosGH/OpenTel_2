import json
with open('output/test_scenario_4_flow.json') as f:
    data = json.load(f)
diagram = data.get('diagram', [])
flows = [x for x in diagram if x.get('type') == 'flow' or x.get('shape') == 'line']
print(f'Total items: {len(diagram)}')
print(f'Flows: {len(flows)}')
if flows:
    print(json.dumps(flows[0], indent=2)[:600])
else:
    print('No flows found. Last 3 items:')
    for x in diagram[-3:]:
        print(f'  {x.get("id")}: {x.get("type")}')
