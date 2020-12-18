import sys, os, configparser, re

'''
Doc:
	https://docs.python.org/3/library/configparser.html
'''

#------------
# GLOBAL VAR
#------------
macro_defs={}	# To cache the files import in case of repeated usages

# Imports a macro conf file
def loadFile(fpath):
	# Splunk config files handle multiline values differently
	# Need to replace \ by a newline followed by an indentation
	f=open(fpath,"r")
	fcontent=f.read()
	fcontent=fcontent.replace("\\\n","\n\t")
	f.close()
	#---
	config = configparser.ConfigParser()
	config.read_string(fcontent)
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
			margs=[margs]
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

def handleMacros(spl,macro_defs_paths=[]):
	global macro_defs
	# In case only 1 string is given instead of a list
	if not isinstance(macro_defs_paths,list):
		macro_defs_paths=[macro_defs_paths]
	# Loading all macro definition files
	for p in macro_defs_paths:
		if not p in macro_defs:	#Not loading again if already in cache
			macro_defs[p]=loadFile(p)
	ret={"text":spl,"unique_macros_found":0,"unique_macros_expanded":0}
	#Extracting macro calls from the spl
	mcalls=list(set(re.findall("`([^`]+)`",spl)))
	nb_rec=1
	while len(mcalls) > 0 and nb_rec < 100:
		msub={}
		# Trying to expand the macros accross all the available definitions
		for p in macro_defs:
			for mcall in mcalls:
				if not mcall in msub:
					res=expandMacro(mcall,macro_defs[p])
					if res["success"]:
						msub[mcall]=res["text"]
		# Replacing in the original string
		ret["unique_macros_found"] += len(mcalls)
		ret["unique_macros_expanded"] += len(msub)
		for mcall in msub:
			ret["text"]=ret["text"].replace("`{}`".format(mcall),msub[mcall])
		mcalls=list(set(re.findall("`([^`]+)`",ret["text"])))
		# To stop the repetition in case there some macros that could not be expanded
		# No need to try in vain 100 times if the previous attempt didn't achieve anything
		if len(msub) == 0:
			mcalls=[]	
		nb_rec += 1
	return ret

'''
s="`foobar(arg1,arg2)` source=*sysmon* | stats count by host | eval max=`fooeval(a,b)`"
print(handleMacros(s,["macros.conf"]))
'''