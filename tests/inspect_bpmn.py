import xml.etree.ElementTree as ET

ns = {'b': 'http://www.omg.org/spec/BPMN/20100524/MODEL'}
t = ET.parse(r'C:\code\openTel_2\tests\nydmv_flows.xml')
r = t.getroot()

print("=== Element counts ===")
print(f"  parallelGateway: {len(r.findall('.//b:parallelGateway', ns))}")
print(f"  exclusiveGateway: {len(r.findall('.//b:exclusiveGateway', ns))}")
print(f"  serviceTask: {len(r.findall('.//b:serviceTask', ns))}")
print(f"  sequenceFlow: {len(r.findall('.//b:sequenceFlow', ns))}")
print(f"  process: {len(r.findall('.//b:process', ns))}")
print()

# Show first 2 processes with their tasks
for proc in r.findall('.//b:process', ns)[:3]:
    pid = proc.get('id')
    doc = proc.find('b:documentation', ns)
    if doc is not None and doc.text:
        lines = doc.text.strip().split('\n')
        print(f"--- {pid}: {lines[1] if len(lines)>1 else ''} / {lines[2] if len(lines)>2 else ''} ---")

    for task in proc.findall('b:serviceTask', ns):
        name = task.get('name', '').replace('\n', ' | ')
        print(f"  Task: {name}")

    for gw in proc.findall('b:parallelGateway', ns):
        print(f"  ParallelGW: {gw.get('id')}")

    for gw in proc.findall('b:exclusiveGateway', ns):
        print(f"  ExclusiveGW: {gw.get('id')} name={gw.get('name','')}")

    print()
