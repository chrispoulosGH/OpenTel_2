import json

for fname in ["output/test_scenario_1_flow.json", "output/flows_all_bpmn2.0.json"]:
    print(f"\n=== {fname} ===")
    with open(fname) as f:
        data = json.load(f)

    diagrams = data.get("diagram", []) if isinstance(data, dict) else data
    found = False
    for rec in diagrams:
        if not isinstance(rec, dict):
            continue
        label = str(rec.get("label", ""))
        if "Amp-MM" in label:
            found = True
            print(f"id={rec.get('id')}  label={label}")
            errors = rec.get("errors", [])
            print(f"  errors count: {len(errors)}")
            for e in errors:
                print(f"    {e}")
    if not found:
        print("  (no Amp-MM tasks found)")
