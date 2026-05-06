import xml.etree.ElementTree as ET

tree = ET.parse('output/test_scenario_4_flow.xml')
root = tree.getroot()

# Register namespaces
namespaces = {
    'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
    'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
    'dc': 'http://www.omg.org/spec/DD/20100524/DC',
    'di': 'http://www.omg.org/spec/DD/20100524/DI'
}

for prefix, uri in namespaces.items():
    ET.register_namespace(prefix, uri)

# Find sequence flows from start event
edges = root.findall('.//bpmndi:BPMNEdge', namespaces)
for edge in edges:
    elem_ref = edge.get('bpmnElement', '')
    if 'SequenceFlow' in elem_ref:
        print(f'Sequence flow: {elem_ref}')
        waypoints = edge.findall('.//di:waypoint', namespaces)
        for i, wp in enumerate(waypoints[:3]):
            print(f'  WP{i}: x={wp.get("x")} y={wp.get("y")}')
        # Find what element this flow connects from
        for flow in root.findall('.//bpmn:sequenceFlow', namespaces):
            if flow.get('id') == elem_ref:
                src = flow.get('sourceRef')
                tgt = flow.get('targetRef')
                print(f'  From: {src} -> To: {tgt}')
                break
        break

# Check start shape bounds
shapes = root.findall('.//bpmndi:BPMNShape', namespaces)
for shape in shapes:
    shape_id = shape.get('id', '')
    if 'Start' in shape_id or 'start' in shape_id:
        bounds = shape.find('.//dc:Bounds', namespaces)
        if bounds:
            print(f'Start shape {shape_id}: x={bounds.get("x")} y={bounds.get("y")} w={bounds.get("width")} h={bounds.get("height")}')
