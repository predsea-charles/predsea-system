import json, sys, datetime
events = json.load(sys.stdin)
for e in events[:30]:
    t = datetime.datetime.utcfromtimestamp(e['time']/1000).strftime('%H:%M:%S')
    print(f"{t}  {e['msg'][:120]}")
