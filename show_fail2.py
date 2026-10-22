import json
d=json.load(open('evals/results/hard_baseline.json'))
[print(k, v['notes'], [c['input'] for c in v['tool_calls']], v['answer'][:400]) for k,v in d.items() if not v['passed']]
