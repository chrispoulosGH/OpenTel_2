import xml.etree.ElementTree as ET
tree = ET.parse(r'C:\code\openTel_2\tests\flows.bpmn')
root = tree.getroot()
print("XML is valid BPMN 2.0")
print(f"Root tag: {root.tag}")
print(f"Top-level elements: {len(list(root))}")
for c in root:
    tag = c.tag.split('}')[1] if '}' in c.tag else c.tag
    print(f"  {tag}: id={c.get('id','')}")
