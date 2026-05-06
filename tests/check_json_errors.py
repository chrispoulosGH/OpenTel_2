#!/usr/bin/env python3
import json

for i in [4, 8, 10]:
    path = f'output/test_scenario_{i}_flow.json'
    with open(path) as f:
        data = json.load(f)
    
    tasks_with_errors = [t for t in data.get('diagram', []) if t.get('type') == 'task' and t.get('errors')]
    print(f'test_scenario_{i}: {len(tasks_with_errors)} task(s) with errors')
    if tasks_with_errors:
        for task in tasks_with_errors[:2]:
            errs = task.get('errors', [])
            print(f'  {task.get("name")}: {len(errs)} error(s)')
            if errs:
                print(f'    Sample: {errs[0].get("error_message", "")[:80]}')
