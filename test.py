import sys, os, json

import spl_validator  

conf=None
with open('test_conf.json') as f:
    conf = json.load(f)

res={"success":0,"failure":0,"analysed":0}
if not conf is None:
	print("[INIT] Tests selected: {}".format(conf["selection"]))
	for test_id in conf["test_cases"]:
		test = conf["test_cases"][test_id]
		if "*" in conf["selection"]:
			selected=True
		else:
			for comb in conf["selection"]:
				selected=True
				for t in comb:
					selected = selected and (t in test["tags"])
				if selected:
					break

		if selected:
			res["analysed"] += 1
			r = spl_validator.analyze(test["search"],print_errs=False,verbose=False)
			if r["errors_count"] == test["exp_err"]:
				res["success"] += 1
			else:
				res["failure"] += 1
				print("[FAILED] {} : {} errors instead of {}\n\t{}".format(test_id,r["errors_count"],test["exp_err"],test["search"]))

	print("[RESULT] {} on {} success".format(res["success"],res["analysed"]))
else:
	print("[ERROR] Could not find the configuration file 'test_conf.json'")