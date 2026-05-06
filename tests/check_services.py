#!/usr/bin/env python3
import xml.etree.ElementTree as ET

tree = ET.parse('output/test_scenario_4_flow.xml')
root = tree.getroot()

# Find all service names in the BPMN diagram
ns_otel = {'otel': 'http://opentelemetry.io/bpmn/extensions'}
services = set()
for span_data in root.findall('.//otel:spanData', ns_otel):
    service = span_data.get('service')
    if service:
        services.add(service)

print("Services in test_scenario_4_flow.xml:")
for s in sorted(services):
    print(f"  - {s}")
