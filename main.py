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
s='`get_all_windows_index` source=usgs place=*California* | stats count by magType | append maxtime=10 [search index=usgs_* source=usgs place=*California* | stats count] | anomalies'
print(s)

spl_validator.analyze(s,verbose=True)