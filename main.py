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
s='(index IN (abc-idx,abc-idx-more*) OR (index IN (abc,dbe-adv) tag=authentication tag=success tag=arg1 OR tag=arg2) ) '

print(s)

spl_validator.analyze(s,verbose=True,macro_files=[])