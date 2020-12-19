import sys, os

import spl_validator  

s='''index="idx" sourcetype="stats_" event_id IN (1,"3") (a OR ( b AND c) d)
[search partitions=2 index="idx2" sourcetype="logs" OR host="wkst"]
[| inputlookup append=true testfile where event_id > 0 | fields - test]
| stats count, values(event_id) as eid, dc(host) by index, sourcetype, eid
| table eid, index
| eval desc="This is a message", success=if(true(error OR NOT (worked)),"no","yes"), value = -1 + ( 2 * 3)
| search success=yes
| dedup 5 host,sourcetype keepevents=true 
'''
s='source=all_month.csv place=*alaska* mag>=3.5 | stats count BY mag | rename mag AS magnitude | rangemap field=magnitude green=3.9-4.2 yellow=4.3-4.6 red=4.7-5.0 default=gray | stats sum(count) by range | eval sort_field=case(range=\"red\",1, range=\"yellow\",2, range=\"green\",3, range=\"gray\",4) | sort sort_field'

print(s)

spl_validator.analyze(s,verbose=True,macro_files=[])