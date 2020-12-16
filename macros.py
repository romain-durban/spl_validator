import sys, os, configparser, re

'''
Doc:
	https://docs.python.org/3/library/configparser.html
'''

# Imports a macro conf file
def loadFile(fpath):
	config = configparser.ConfigParser()
	config.read(fpath)
	data={}
	for s in config.sections():
		data[s]=config[s]
	return data

# Based on the macro conf provided, expand the given macro call
# return an object with attribute "success" indicate if operation went well
# and "text" with either the error message or the expanded macro
def expandMacro(macro,mconf):
	# Expected format : macro_name OR macro_name(arg1) OR macro_name(arg1,arg2) OR macro_name(name1=arg1,name2=arg2)
	reg = re.compile('(?P<macro_name>[a-zA-Z][a-zA-Z0-9_\.]*)(\((?P<args>[^,\(\)]+(,[^,\(\)]+)*)\))?')
	m = reg.search(macro)
	mname = m.group("macro_name")
	margs = m.group("args")
	nb_args=0
	# Returns an error if we could not even get the macro name
	if mname is None:
		return {"success":False,"text":"Wrong macro call format"}
	if not margs is None:	# if any arg
		if "," in margs:	# iif args list, split
			margs = margs.split(",")
			nb_args=len(margs)
		else:
			nb_args=1
	if nb_args > 0:	# Builds the expected stanza name of format macro_name OR macro_name(args_number)
		stanza="{}({})".format(mname,nb_args)
	else:
		stanza=mname
	#If macro stanza found
	if stanza in mconf:
		if nb_args > 0:
			mapping={}
			args=[a.strip() for a in mconf[stanza]["args"].split(",")]	# split args def and trim
			for ma in margs:
				if "=" in ma:	# Case of named arguments handled first
					aname,avalue=ma.split("=")
					if aname in args:
						mapping[aname]=avalue
			for i in range(len(args)):	# Go 1 by 1 be default
				if not args[i] in mapping:
					mapping[args[i]]=margs[i]
			s=mconf[stanza]["definition"].strip('"')
			for arg in mapping:	# Now replace the argument with the values found
				s=s.replace("${}$".format(arg),mapping[arg])
			return {"success":True,"text":s}	
		else:
			return {"success":True,"text":mconf[stanza]["definition"]}
	else:	# Macro not found, either wrong call or it does not exists
		return {"success":False,"text":"Could not find macro with stanza {}".format(stanza)}

def handleMacros(spl,macro_defs_paths):
	macro_defs={}
	# In case only 1 string is given instead of a list
	if not isinstance(macro_defs_paths,list):
		macro_defs_paths=[macro_defs_paths]
	# Loading all macro definition files
	for p in macro_defs_paths:
		macro_defs[p]=loadFile(p)
	#Extracting macro calls from the spl
	mcalls=list(set(re.findall("`([^`]+)`",s)))
	msub={}
	# Trying to expand the macros accross all the available definitions
	for p in macro_defs:
		for mcall in mcalls:
			if not mcall in msub:
				res=expandMacro(mcall,macro_defs[p])
				if res["success"]:
					msub[mcall]=res["text"]
	# Replacing in the original string
	res={"text":spl,"unique_macros_found":len(mcalls),"unique_macros_expanded":len(msub)}
	for mcall in msub:
		res["text"]=res["text"].replace("`{}`".format(mcall),msub[mcall])
	return res

'''
s="`foobar(arg1,arg2)` source=*sysmon* | stats count by host | eval max=`fooeval(a,b)`"
print(handleMacros(s,["macros.conf"]))
'''