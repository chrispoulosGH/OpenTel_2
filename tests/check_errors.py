#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import glob

ns_otel = {'otel': 'http://opentelemetry.io/bpmn/extensions'}
ET.register_namespace('otel', ns_otel['otel'])

files = glob.glob('output/test_scenario_*_flow.xml')
print("Checking for errorDataSet elements in generated XMLs:\n")
for fname in sorted(files):
    tree = ET.parse(fname)
    root = tree.getroot()
    error_sets = root.findall('.//otel:errorDataSet', ns_otel)
    if error_sets:
        print(f"{fname}: {len(error_sets)} errorDataSet(s)")
        for i, es in enumerate(error_sets[:2]):
            recs = es.findall(f'{{{ns_otel["otel"]}}}errorRecord')
            print(f"  Set {i}: {len(recs)} errorRecord(s)")
    else:
        print(f"{fname}: NO errorDataSet elements")
