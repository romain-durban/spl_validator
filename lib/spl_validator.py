
import sys, os, re, json, logging, fnmatch, pkg_resources
from .ply import lex
from .ply import yacc
from . import macros

# LOGGING
logger = logging.getLogger('spl_validator')
logger.setLevel(logging.CRITICAL)
ch = logging.StreamHandler()
ch.setLevel(logging.CRITICAL)
formatter = logging.Formatter('[%(levelname)s] %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

# CONF
cmd_conf=None
try:
    with open(pkg_resources.resource_filename(__name__,'spl_commands.json')) as f:
        cmd_conf = json.load(f)
except FileNotFoundError:
    logger.critical("spl_commands.json not found")
    exit()

if cmd_conf is None:
    logger.critical("spl_commands.json could not be loaded")
    exit()

#---------------------------
#       LEX
#---------------------------

reserved = {
    'as' : 'AS_CLAUSE',
    'by' : 'BY_CLAUSE',
    'groupby' : 'GROUPBY_CLAUSE',
    'sortby' : 'SORTBY_CLAUSE',
    'or' : 'OR_OP',
    'and' : 'AND_OP',
    'not'  :'NOT_OP',
    'output': 'OUTPUT_OP',
    'outputnew': 'OUTPUT_NEW_OP',
    'in':'IN_OP',
    'with':'WITH_OP',
    'notin':'NOTIN_OP',
    'case':'CASE_OP',
    'term':'TERM_OP',
    'over':'OVER_OP',
    'bottom':'BOTTOM_OP',
    'splitrow': 'SPLITROW_OP',
    'splitcol':'SPLITCOL_OP',
    'filter': 'FILTER_OP',
    'limit': 'LIMIT_OP',
    'rowsummary': 'ROWSUMMARY_OP',
    'colsummary': 'COLSUMMARY_OP',
    'showother': 'SHOWOTHER_OP',
    'numcols': 'NUMCOLS_OP',
    'range': 'RANGE_OP',
    'period': 'PERIOD_OP',
    'truelabel': 'TRUELABEL_OP',
    'falselabel': 'FALSELABEL_OP'
}

tokens = [
    'DEQ','EQ','NEQ','PLUS', 'MINUS', 'TIMES', 'DIVIDE', 'MOD', 'LPAREN','RPAREN','QLPAREN','QRPAREN','LBRACK','RBRACK','COMMA',
    'NUMBER', 'FLOAT', 'QUOTE', 'COMP_OP', 'PIPE', 'DOT', 'COLON',
    'MACRO',
    'NAME','STRING','PATTERN','TIMESPECIFIER','DATE'
] + list(set(reserved.values())) + list(set([cmd_conf[cmd]["token_name"] for cmd in cmd_conf]))

literals = []

# Tokens

t_DEQ = r'\=\='
t_EQ = r'\='
t_NEQ = r'!\='
t_PLUS    = r'\+'
t_MINUS   = r'-'
t_TIMES   = r'\*'
t_DIVIDE  = r'/'
t_MOD = r'%'
t_LPAREN  = r'\('
t_RPAREN  = r'\)'
t_QLPAREN  = r'\"\(\"'
t_QRPAREN  = r'\"\)\"'
t_LBRACK  = r'\['
t_RBRACK  = r'\]'
t_PIPE = r'\|'
t_COMMA = r'\,'
t_QUOTE = r'"'
t_COMP_OP = r'(<=|>=|<|>)'
t_DOT = r'\.'
t_COLON = r':'

t_ignore = " \r\n\t"

def t_MACRO(t):
    r'`[^`]+`'
    #Perhaps in the future check macros existence/content
    pass

def t_newline(t):
    r'\n+'
    t.lexer.lineno += t.value.count("\n")

def t_DATE(t):
    r'\d+/\d+/\d+(:\d+:\d+:\d+)?'
    return t

#Strings
# Patterns (having a starting and/or trailing *, be careful to not catch simple multiplications)
def t_PATTERN(t):
    r'(\*[^\*\s]+\*|\*[a-zA-Z_\.\{\}\-:<>/]+|[a-zA-Z0-9_\.\{\}\-:<>/]+\*)'
    return t

def t_STRING(t):
    r'("([^"\\]*(\\.[^"\\]*)*)"|\'([^\'\\]*(\\.[^\'\\]*)*)\'|""|\'\')'
    t.value=t.value[1:-1]
    if t.value == "(":
        t.type = "QLPAREN"
    elif t.value == ")":
        t.type = "QRPAREN"
    return t

def t_NAME(t):
    r'([a-zA-Z0-9_\{\}/]*<<[a-zA-Z0-9_\{\}/@]+>>[a-zA-Z0-9_\{\}/]*|[a-zA-Z0-9_\{\}/\$][a-zA-Z0-9_\.\{\}\-:/@]*)'
    global cmd_conf
    if t.value.lower() in cmd_conf:
        t.value = t.value.lower()
        t.type = cmd_conf[t.value.lower()]["token_name"]    # Check for command names, lowercase
    else:
        t.type = reserved.get(t.value.lower(),"NAME")       # Check for reserved words, lowercase
        if not t.type == "NAME":
            t.value = t.value.lower()
    if t.value.isdigit():
        t.type = "NUMBER"
    if re.match(r'^\d+\.\d+$', t.value):
        t.type = "FLOAT"
    return t

def t_TIMESPECIFIER(t):
    r'[0-9a-zA-Z\+\-]*@[0-9a-zA-Z\+\-]+ '
    return t

def t_FLOAT(t):
    r'\d*\.\d+'
    t.value = float(t.value)
    return t

def t_NUMBER(t):
    r'\d+'
    t.value = int(t.value)
    return t

def t_error(t):
    report_error(t.lexpos,t.lexpos+len(t.value[0]),"Illegal character {}".format(t.value[0]),None,value=t.value[0])
    t.lexer.skip(1)

#---------------------------
#       YACC
#---------------------------

# Parsing rules

precedence = (
    ('left', 'EQ', 'NEQ', 'COMP_OP', 'DEQ'),
    ('left', 'PLUS', 'MINUS'),
    ('left', 'TIMES', 'DIVIDE'),
    ('right','AND_OP'),
    ('left','OR_OP'),
    ('right', 'UMINUS','NOT_OP')
)

#---------------------------
# Searches
#---------------------------
def p_mainsearch(p):
    '''mainsearch : search_exp'''
    p[0] = p[1]
    p[0]["type"] = "mainsearch"

def p_search_exp(p):
    '''search_exp : filters
              | filters PIPE commands
              | PIPE commands'''
    global scope_level, params, data
    flt,cmd=None,None
    fields = {"type":"search_exp","input":[],"output":[],"fields-effect":[],"content":[]}
    if len(p) == 4:
        flt=p[1]
        fields["content"] += p[1]["content"] + p[3]["content"]
        cmd=p[3]
        fields["fields-effect"]=p[3]["fields-effect"]
    elif len(p) == 3:
        cmd=p[2]
        fields["fields-effect"]=p[2]["fields-effect"]
        fields["content"] += p[2]["content"]
    elif len(p) == 2:
        flt=p[1]
        fields["content"] += p[1]["content"]
    if not flt is None:
        for f in flt["input"]:
            if not f in fields["input"] and f is not None:
                fields["input"].append(f)
    if not cmd is None:
        for f in cmd["input"]:
            if not f in fields["input"] and f is not None:
                fields["input"].append(f)
        for f in cmd["output"]:
            if not f in fields["output"] and f is not None:
                fields["output"].append(f)
    p[0] = fields
    logger.info("SEARCH [{}]: {}".format(scope_level,fields))
    if scope_level > 0:
        data["subsearches"].append({"level":scope_level,"data":fields})


def p_subsearch(p):
    '''subsearch : LBRACK new_scope commands RBRACK
                 | LBRACK new_scope PIPE commands RBRACK'''
    global scope_level
    p[0] = {"type":"subsearch","input":p[len(p)-2]["input"],"output":p[len(p)-2]["output"],"content":p[len(p)-2]["content"]}
    scope_level = scope_level -1

def p_subsearches(p):
    '''subsearches : subsearches subsearch
                   | subsearch'''
    p[0] = {"type":"subsearches","input":p[1]["input"],"output":p[1]["output"],"content":p[1]["content"]}
    if len(p) > 2:
        p[0]["input"] += p[2]["input"]
        p[0]["output"] += p[2]["output"]
        p[0]["content"] += p[2]["content"]

def p_new_scope(p):
    'new_scope :'
    global scope_level
    scope_level = scope_level +1

def p_subpipeline(p):
    'subpipeline : LBRACK commands RBRACK'
    p[0] = {"type":"subpipeline","input":p[2]["input"],"output":p[2]["output"]}

#---------------------------
# FILTERS
#---------------------------

# Logical fields conditions

def p_filters(p):
    '''filters : filters OR_OP filters_logic_term
               | filters_logic_term'''
    if len(p) == 4:
        p[0] = {"type":"filters","input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["output"],"content":p[1]["content"]+p[3]["content"],"op":p[1]["op"] + [p[2]] + p[3]["op"]}
    else:
        p[0] = {"type":"filters","input":p[1]["input"],"output":p[1]["output"],"content":p[1]["content"],"op":p[1]["op"]}

def p_filters_logic_term(p):
    '''filters_logic_term : filters_logic_term AND_OP filters_logic_factor
                          | filters_logic_term COMMA filters_logic_factor
                          | filters_logic_term filters_logic_factor
                          | filters_logic_factor'''
    if len(p) == 4:
        p[0] = {"type":"filters_logic_term","input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["output"],"content":p[1]["content"]+p[3]["content"],"op":p[1]["op"] + ["and"] + p[3]["op"]}
    elif len(p) == 3:
        p[0] = {"type":"filters_logic_term","input":p[1]["input"]+p[2]["input"],"output":p[1]["output"]+p[2]["output"],"content":p[1]["content"]+p[2]["content"],"op":p[1]["op"] + ["and"] + p[2]["op"]}
    else:
        p[0] = {"type":"filters_logic_term","input":p[1]["input"],"output":p[1]["output"],"content":p[1]["content"],"op":p[1]["op"]}

def p_filters_logic_factor(p):
    '''filters_logic_factor : filter
                            | filter filters_logic_factor
                            | filter COMMA filters_logic_factor
                            | filter AND_OP filters_logic_factor
                            | NOT_OP filters_logic_factor
                            | LPAREN filters RPAREN'''
    if isinstance(p[1],dict):
        p[0] = {"type":"filters_logic_factor","input":p[1]["input"],"output":p[1]["output"],"content":[p[1]["value"]],"op":[]}
        if len(p) > 2:
            p[0]["input"] += p[len(p)-1]["input"]
            p[0]["output"] += p[len(p)-1]["output"]
            p[0]["content"] += p[len(p)-1]["content"]
            p[0]["op"].append("and")
    else:
        if len(p) > 2:
            p[0] = {"type":"filters_logic_factor","input":p[2]["input"],"output":p[2]["output"],"content":p[2]["content"],"op":p[2]["op"]}
            if p[1] == "not":
                p[0]["op"] = [p[1]] + p[0]["op"]
        
# ---

def p_filter_eq(p):
    'filter : field_name EQ value'
    p[0] = {"type":"filter","input":[p[1]["field"]],"output":[],"value":p[3]["value"],"op":[p[2]]}

def p_filter_neq(p):
    'filter : field_name NEQ value'
    p[0] = {"type":"filter","input":[p[1]["field"]],"output":[],"value":p[3]["value"],"op":[p[2]]}

def p_filters_sub(p):
    'filter : subsearch'
    p[0] = {"type":"filter_subsearch","input":p[1]["output"],"output":[],"value":"","op":[]}

def p_filter_comp_1(p):
    '''filter : field_name COMP_OP NUMBER
              | field_name COMP_OP FLOAT'''
    p[0] = {"type":"filter","input":[p[1]["field"]],"output":[],"value":p[3],"op":[p[2]]}

def p_filter_comp_(p):
    '''filter : NUMBER COMP_OP field_name
              | FLOAT COMP_OP field_name'''
    p[0] = {"type":"filter","input":[p[3]["field"]],"output":[],"value":p[1],"op":[p[2]]}

def p_filter_in(p):
    '''filter : field_name IN_OP LPAREN values_list RPAREN'''
    p[0] = {"type":"filter","input":[p[1]["field"]],"output":[],"value":p[4]["values"],"op":[p[2]]}

def p_filter_phrases(p):
    '''filter : CASE_OP LPAREN value RPAREN
              | TERM_OP LPAREN value RPAREN'''
    p[0] = {"type":"filter_phrase","input":[],"output":[],"value":p[3],"op":[p[1]]}

def p_filter_any(p):
    '''filter : field_name EQ TIMES
              | TIMES'''
    if len(p) > 2:
        p[0] = {"type":"filter","input":[p[1]["field"]],"output":[],"value":p[3],"op":[p[2]]}
    else:
        p[0] = {"type":"filter","input":[],"output":[],"value":p[1],"op":[]}

def p_filter_notany(p):
    'filter : field_name NEQ TIMES'
    p[0] = {"type":"filter","input":[p[1]["field"]],"output":[],"value":p[3],"op":[p[2]]}

def p_filter_raw(p):
    'filter : value'
    p[0] = {"type":"filter","input":[],"output":[],"value":p[1]["value"],"op":[]}

# ERROR HANDLING
def p_filter_error(p):
    'filter : filter NAME error'
    p[0] = p[1]
    report_error(p.lexpos(2),p[3].lexpos,"Syntax error in a filter",p[3])

#---------------------------
# EXPRESSIONS
#---------------------------

# Logical conditions
def p_expression_logic(p):
    '''expression : expression_logic_exp'''
    s=""
    for pp in p[1:]:
        if isinstance(pp,dict) and "content" in pp:
            s += pp["content"]
        else:
            s += pp
    p[0] = {"type":"expression","content":s,"input":[],"output":[]}

def p_expression_logic_exp(p):
    '''expression_logic_exp : expression_logic_term OR_OP expression_logic_term
                            | expression_logic_term'''
    s=""
    for pp in p[1:]:
        if isinstance(pp,dict) and "content" in pp:
            s += pp["content"]
        else:
            s += " "+pp
    p[0] = {"type":"expression_logic_exp","content":s,"input":[],"output":[]}

def p_expression_logic_term(p):
    '''expression_logic_term : expression_logic_factor AND_OP expression_logic_term
                             | expression_logic_factor expression_logic_term
                             | expression_logic_factor'''
    s=" "
    for pp in p[1:]:
        if isinstance(pp,dict) and "content" in pp:
            s += pp["content"]
        else:
            s += " "+pp
    p[0] = {"type":"expression_logic_term","content":s,"input":[],"output":[]}

def p_expression_logic_factor(p):
    '''expression_logic_factor : expression_value
                               | NOT_OP expression_logic_factor
                               | LPAREN expression_logic_exp RPAREN'''
    s=""
    for pp in p[1:]:
        if isinstance(pp,dict) and "content" in pp:
            s += pp["content"]
        else:
            if pp == "not":
                s += " "
            s += pp
    p[0] = {"type":"expression_logic_factor","content":s,"input":[],"output":[]}

def p_expression_logic_factor_in(p):
    '''expression_logic_factor : expression_value IN_OP LPAREN values_list RPAREN'''
    s="{} IN ({})".format(p[1]["content"],",".join(p[4]["values"]))
    p[0] = {"type":"expression_logic_factor","input":[],"output":[],"content":s}

def p_expression_value(p):
    '''expression_value : expr_fun_call
                        | value'''
    s=""
    for pp in p[1:]:
        if isinstance(pp,dict):
            if "content" in pp:
                s += pp["content"]
            elif "value" in pp:
                s += pp["value"]
        else:
            s += pp
    p[0] = {"type":"expression_value","content":s,"input":[],"output":[]}

# Handling here some unwanted tokenizing with "*"
def p_expression_binop(p):
    '''expression_value : expression_value PLUS expression_value
                        | expression_value MINUS expression_value
                        | expression_value TIMES expression_value
                        | expression_value DIVIDE expression_value
                        | expression_value DEQ expression_value
                        | expression_value EQ expression_value
                        | expression_value NEQ expression_value
                        | expression_value COMP_OP expression_value
                        | expression_value MOD expression_value
                        | expression_value DOT expression_value
                        | expression_value PATTERN
                        | PATTERN expression_value
                        | LPAREN expression_value RPAREN'''
    s=""
    for pp in p[1:]:
        if isinstance(pp,dict) and "content" in pp:
            s += pp["content"]
        else:
            s += pp
    p[0] = {"type":"expression_value","content":s,"input":[],"output":[]}

# ---
def p_expression_fun_call(p):
    '''expr_fun_call : expr_fun LPAREN expression_fun_args RPAREN
                     | expr_fun LPAREN RPAREN'''
    p[0] = {"type":"expr_fun_call","content":[],"input":[],"output":[],"function":p[1]["content"]}
    if len(p) == 5:
        p[0]["content"]="{}({})".format(p[1]["content"],p[3]["content"])
    else:
        p[0]["content"]="{}()".format(p[1]["content"])


def p_expression_fun(p):
    '''expr_fun : NAME
                | CASE_OP
                | commands_names'''
    p[0] = {"type":"expression_value","content":p[1],"input":[],"output":[]}

def p_expression_fun_args(p):
    '''expression_fun_args : expression_fun_args COMMA expression 
                           | expression'''
    s=""
    for pp in p[1:]:
        if isinstance(pp,dict) and "content" in pp:
            s += pp["content"]
        else:
            s += pp
    p[0] = {"type":"expression_fun_args","content":s,"input":[],"output":[]}

#---------------------------
# Commands
#---------------------------
def p_commands(p):
    '''commands : commands PIPE command
                | command'''
    if len(p) == 4:
        p[0] = {"type":"command","input":p[1]["input"]+p[3]["input"],"output":[],"fields-effect":p[1]["fields-effect"]+[p[3]["fields-effect"]],"content":[]}
        if p[3]["fields-effect"] == "replace":
            p[0]["output"]=[]
            for f in p[3]["output"]:
                if "*" in f:
                    p[0]["output"] += filterFields(p[1]["output"],f)
                else:
                    p[0]["output"].append(f)
        elif p[3]["fields-effect"] == "remove":
            p[0]["output"]=[]
            rem=[]
            for f in p[3]["output"]:
                if "*" in f:
                    rem += filterFields(p[1]["output"],f)
                else:
                    rem.append(f)
            for f in p[1]["output"]:
                if not f in rem:
                    p[0]["output"].append(f)
        elif p[3]["fields-effect"] == "rename":
            p[0]["output"]=[]
            for f in p[1]["output"]:
                if not f in p[3]["input"]:
                    p[0]["output"].append(f)
            p[0]["output"] = p[0]["output"] + p[3]["output"]
        else:
            p[0]["output"] = p[1]["output"]+p[3]["output"]
        if "content" in p[1]:
            p[0]["content"] += p[1]["content"]
        if "content" in p[3]:
            p[0]["content"] += p[3]["content"]
    else:
        p[0]=p[1]
        p[0]["fields-effect"]=[p[1]["fields-effect"]]
        if not "content" in p[0]:
            p[0]["content"]=[]
    

# ERROR HANDLING
def p_commands_error(p):
    '''commands : commands PIPE error
                | commands PIPE commands_names error'''
    if len(p) == 5:
        report_error(p.lexpos(2),p[4].lexpos,"Syntax error in command {}".format(p[3]),p[4])
    else:
        report_error(p.lexpos(2),p[3].lexpos,"Unknown command name",p[3])
    p[0] = p[1]

def p_commands_names(p):
    '''commands_names : CMD_ABSTRACT
                      | CMD_ACCUM
                      | CMD_ADDCOLTOTALS
                      | CMD_ADDINFO
                      | CMD_ADDTOTALS
                      | CMD_ANALYSEFIELDS
                      | CMD_ANOMALIES
                      | CMD_ANOMALOUSVALUE
                      | CMD_ANOMALYDETECTION
                      | CMD_APPEND
                      | CMD_APPENDCOLS
                      | CMD_APPENDPIPE
                      | CMD_ARULES
                      | CMD_AUDIT
                      | CMD_AUTOREGRESS
                      | CMD_BIN
                      | CMD_BUCKETDIR
                      | CMD_CEFOUT
                      | CMD_CHART
                      | CMD_CLUSTER
                      | CMD_COFILTER
                      | CMD_COLLECT
                      | CMD_CONCURRENCY
                      | CMD_CONTINGENCY
                      | CMD_CONVERT
                      | CMD_CORRELATE
                      | CMD_DATAMODEL
                      | CMD_DBINSPECT
                      | CMD_DEDUP
                      | CMD_DELETE
                      | CMD_DELTA
                      | CMD_DIFF
                      | CMD_EREX
                      | CMD_EVAL
                      | CMD_EVENTCOUNT
                      | CMD_EVENTSTATS
                      | CMD_EXPAND
                      | CMD_EXTRACT
                      | CMD_FIELDFORMAT
                      | CMD_FIELDS
                      | CMD_FIELDSUMMARY
                      | CMD_FILLDOWN
                      | CMD_FILLNULL
                      | CMD_FINDTYPES
                      | CMD_FLATTEN
                      | CMD_FOLDERIZE
                      | CMD_FOREACH
                      | CMD_FORMAT
                      | CMD_FROM
                      | CMD_GAUGE
                      | CMD_GENTIMES
                      | CMD_GEOM
                      | CMD_GEOMFILTER
                      | CMD_GEOSTATS
                      | CMD_HEAD
                      | CMD_HIGHLIGHT
                      | CMD_HISTORY
                      | CMD_ICONIFY
                      | CMD_INPUTCSV
                      | CMD_INPUTLOOKUP
                      | CMD_IPLOCATION
                      | CMD_JOIN
                      | CMD_KMEANS
                      | CMD_KVFORM
                      | CMD_LOADJOB
                      | CMD_LOCALIZE
                      | CMD_LOCALOP
                      | CMD_LOOKUP
                      | CMD_MAKECONTINUOUS
                      | CMD_MAKEMV
                      | CMD_MAKERESULTS
                      | CMD_MAP
                      | CMD_MCOLLECT
                      | CMD_METADATA
                      | CMD_METASEARCH
                      | CMD_MEVENTCOLLECT
                      | CMD_MPREVIEW
                      | CMD_MSTATS
                      | CMD_MULTIKV
                      | CMD_MULTISEARCH
                      | CMD_MVCOMBINE
                      | CMD_MVEXPAND
                      | CMD_NOMV
                      | CMD_OUTLIER
                      | CMD_OUTPUTCSV
                      | CMD_OUTPUTLOOKUP
                      | CMD_OUTPUTTEXT
                      | CMD_PIVOT
                      | CMD_PREDICT
                      | CMD_RANGEMAP
                      | CMD_RARE
                      | CMD_REDISTRIBUTE
                      | CMD_REGEX
                      | CMD_RELEVANCY
                      | CMD_RELTIME
                      | CMD_RENAME
                      | CMD_REPLACE
                      | CMD_REQUIRE
                      | CMD_REST
                      | CMD_RETURN
                      | CMD_REVERSE
                      | CMD_REX
                      | CMD_RTORDER
                      | CMD_SAVEDSEARCH
                      | CMD_SCRIPT
                      | CMD_SCRUB
                      | CMD_SEARCH
                      | CMD_SEARCHTXN
                      | CMD_SELFJOIN
                      | CMD_SENDEMAIL
                      | CMD_SORT
                      | CMD_STATS
                      | CMD_STREAMSTATS
                      | CMD_TABLE
                      | CMD_TIMECHART
                      | CMD_TOP
                      | CMD_TRANSACTION
                      '''
    # Removed CMD_WHERE on purpose because it also is a operator in various commands
    # and this creates unwanted behaviours
    p[0] = p[1]

def p_op_names(p):
    '''op_names : SORTBY_CLAUSE
                | OUTPUT_OP
                | OUTPUT_NEW_OP
                | CASE_OP
                | TERM_OP
                | OVER_OP
                | BOTTOM_OP
                | SPLITROW_OP
                | SPLITCOL_OP
                | FILTER_OP
                | LIMIT_OP
                | ROWSUMMARY_OP
                | COLSUMMARY_OP
                | SHOWOTHER_OP
                | NUMCOLS_OP
                | RANGE_OP
                | PERIOD_OP
                | TRUELABEL_OP
                | FALSELABEL_OP
                '''
    # Excluding some more basic operators which are not supposed to be found elsewhere
    # Such as IN or AND or NOT and so on
    p[0] = p[1]

# SEARCH COMMAND
def p_command_search(p):
    'command : CMD_SEARCH filters'
    p[0] = {"type":"command","input":p[2]["input"],"output":[],"fields-effect":"none","content":p[2]["content"],"op":p[2]["op"]}

# STATS
def p_command_stats(p):
    '''command : CMD_STATS args_list agg_terms_list BY_CLAUSE fields_list
               | CMD_STATS agg_terms_list BY_CLAUSE fields_list
               | CMD_STATS args_list agg_terms_list
               | CMD_STATS agg_terms_list'''
    global params
    fields={"type":"command","input":[],"output":[],"fields-effect":"replace"}
    byclause,aggclause = [], []
    if len(p) == 6:
        byclause = p[5]["input"]
    elif len(p) == 5:
        byclause = p[4]["input"]
    for f in byclause:
        if f not in fields["input"] and f is not None:
            fields["input"].append(f)
            fields["output"].append(f)
    if len(p) == 6 or len(p) == 4:
        aggclause = p[3]
    else:
        aggclause = p[2]

    for f in aggclause["input"]:
        if f not in fields["input"] and f is not None:
            fields["input"].append(f)
    for f in aggclause["output"]:
        if f not in fields["output"] and f is not None:
            fields["output"].append(f)
        else:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Duplicate field '{}' in stats".format(f),None,value=f)
    p[0] = fields
    
    if len(p) == 6 or len(p) == 4:
        checkArgs(p,p[2]["args"])
    logger.info("Parsed a STATS: {}".format(fields))

# EVAL
def p_command_eval(p):
    'command : CMD_EVAL eval_exprs'
    global params
    p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend","content":p[2]["content"]}
    logger.info("Parsed a EVAL: {}".format(p[0]))

def p_command_eval_exprs(p):
    '''eval_exprs : eval_exprs COMMA eval_expr_assign
                  | eval_expr_assign'''
    if len(p) == 4:
        #p[0] = [p[1]] + p[3]
        p[0] = {"type":"eval_exprs","input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["input"],"content":p[1]["input"]+p[3]["content"]}
    else:
        #p[0] = [p[1]]
        p[0] = {"type":"eval_exprs","input":p[1]["input"],"output":p[1]["output"],"content":p[1]["content"]}

def p_command_eval_expr_assign(p):
    'eval_expr_assign : field_name EQ expression'
    p[0] = {"type":"eval_expr_assign","input":[p[1]["field"]]+p[3]["input"],"output":p[3]["output"],"content":[p[3]["content"]]}

def p_command_eval_expr_fun_value(p):
    '''eval_expr_fun_value : CMD_EVAL LPAREN expression RPAREN'''
    p[0] = {"type":"eval_expr_fun_value","input":p[3]["input"],"output":p[3]["output"],"content":p[3]["content"]}

def p_command_eval_expr_fun(p):
    '''eval_expr_fun : eval_expr_fun_value AS_CLAUSE field_name
                     | eval_expr_fun_value'''
    if len(p) == 4:
        p[0] = {"type":"eval_expr_fun","input":p[1]["input"],"output":[p[3]["field"]]+p[1]["output"],"content":p[1]["content"]}
    else:
        p[0] = {"type":"eval_expr_fun","input":p[1]["input"],"output":p[1]["output"],"content":p[1]["content"]}

# FIELDS COMMAND
def p_command_fields_keep(p):
    '''command : CMD_FIELDS PLUS fields_list
               | CMD_FIELDS fields_list'''
    p[0] = {"type":"command","input":p[len(p)-1]["input"],"output":p[len(p)-1]["input"],"fields-effect":"replace"}

def p_command_fields_remove(p):
    '''command : CMD_FIELDS MINUS fields_list'''
    p[0] = {"type":"command","input":p[3]["input"],"output":p[3]["input"],"fields-effect":"remove"}

# RENAME
def p_command_rename(p):
    'command : CMD_RENAME rfields_list'
    p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"rename"}

# SORT
def p_command_sort(p):
    '''command : CMD_SORT NUMBER sort_clause
               | CMD_SORT sort_clause
               | CMD_SORT NUMBER sort_clause NAME
               | CMD_SORT sort_clause NAME'''
    if len(p) == 4:
        p[0] = {"type":"command","input":p[3]["input"],"output":p[3]["output"],"fields-effect":"none"}
    else:
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"none"}

def p_command_sort_clause(p):
    '''sort_clause : sort_clause COMMA sort_term
                   | sort_term'''
    p[0] = {"type":"sort_clause","input":[],"output":[],"fields-effect":"none"}
    if len(p) == 4:
        p[0]["input"] = p[1]["input"] + [p[3]["field"]]
    else:
        p[0]["input"] = [p[1]["field"]]

def p_command_sort_term(p):
    '''sort_term : PLUS field_name
                 | MINUS field_name
                 | field_name'''
    p[0] = {"type":"sort_term","field":p[len(p)-1]["field"],"fields-effect":"none"}

# DEDUP
def p_command_dedup_args(p):
    '''command : CMD_DEDUP NUMBER fields_list args_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP fields_list args_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP NUMBER fields_list args_list
               | CMD_DEDUP fields_list args_list'''
    args=None
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    for pp in p[1:]:
        if "type" in pp:
            if pp["type"] in ["fields_list","sort_clause"]:
                p[0]["input"] += pp["input"]
            elif pp["type"] == "args_list":
                extendDict(args,pp["args"])
    checkArgs(p,args)

def p_command_dedup_noargs(p):
    '''command : CMD_DEDUP NUMBER fields_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP fields_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP NUMBER fields_list
               | CMD_DEDUP fields_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    for pp in p[1:]:
        if "type" in pp:
            if pp["type"] in ["fields_list","sort_clause"]:
                p[0]["input"] += pp["input"]


# BASIC NO FIELD COMMAND
def p_command_basic_no_field(p):
    '''command : CMD_ABSTRACT
               | CMD_ADDCOLTOTALS
               | CMD_ADDTOTALS
               | CMD_ADDINFO
               | CMD_ANOMALOUSVALUE
               | CMD_ANOMALYDETECTION
               | CMD_AUDIT
               | CMD_FILLNULL
               | CMD_REVERSE
               | CMD_APPENDPIPE
               | CMD_ASSOCIATE
               | CMD_TRANSACTION
               | CMD_CORRELATE
               | CMD_DBINSPECT
               | CMD_DELETE
               | CMD_DIFF
               | CMD_EVENTCOUNT
               | CMD_FIELDSUMMARY
               | CMD_FILLDOWN
               | CMD_GEOMFILTER
               | CMD_HISTORY
               | CMD_LOCALIZE
               | CMD_LOCALOP
               | CMD_MAKERESULTS
               | CMD_OUTLIER
               | CMD_KMEANS
               | CMD_MPREVIEW
               | CMD_OUTPUTTEXT
               | CMD_RELEVANCY
               | CMD_RELTIME
               | CMD_REQUIRE
               | CMD_RTORDER
               | CMD_SCRUB'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    p[0] = commands_args_and_fields_output_update(p,[])

# BASIC SINGLE FIELD COMMAND
def p_command_basic_single_field(p):
    '''command : CMD_EXPAND field_name
               | CMD_FLATTEN field_name
               | CMD_NOMV field_name'''
    p[0] = {"type":"command","input":[p[2]["field"]],"output":[],"fields-effect":"none","content":[]}

# BASIC SINGLE ARG COMMAND
def p_command_basic_single_arg(p):
    '''command : CMD_ANALYSEFIELDS args_term
               | CMD_APPENDPIPE args_term
               | CMD_CEFOUT args_term
               | CMD_HISTORY args_term
               | CMD_OUTPUTTEXT args_term'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    checkArgs(p,p[2]["args"])
    p[0]=commands_args_and_fields_output_update(p,p[2]["args"])

# BASIC ONLY ARGS COMMAND
def p_command_basic_only_args(p):
    '''command : CMD_ABSTRACT args_list
               | CMD_BUCKETDIR args_list
               | CMD_CLUSTER args_list
               | CMD_COLLECT args_list
               | CMD_CONCURRENCY args_list
               | CMD_DBINSPECT args_list
               | CMD_DIFF args_list
               | CMD_EVENTCOUNT args_list
               | CMD_FOLDERIZE args_list
               | CMD_GENTIMES args_list
               | CMD_GEOMFILTER args_list
               | CMD_MAKERESULTS args_list
               | CMD_KVFORM args_list
               | CMD_LOCALIZE args_list
               | CMD_METADATA args_list
               | CMD_MPREVIEW args_list
               | CMD_RTORDER args_list
               | CMD_SENDEMAIL args_list
               | CMD_SCRUB args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    checkArgs(p,p[2]["args"])
    p[0]=commands_args_and_fields_output_update(p,p[2]["args"])

# BASIC ONLY FIELDS
def p_command_basic_only_fields(p):
    '''command : CMD_TABLE fields_list
               | CMD_FILLDOWN fields_list
               | CMD_HIGHLIGHT fields_list
               | CMD_ICONIFY fields_list'''
    p[0] = {"type":"command","input":p[2]["input"],"output":[],"fields-effect":"none","content":[]}
    p[0] = commands_args_and_fields_output_update(p,[])

# BASIC FIELDS AND ARGS
def p_command_basic_args_and_fields(p):
    '''command : CMD_ADDCOLTOTALS command_params_fields_or_args
               | CMD_ADDTOTALS command_params_fields_or_args
               | CMD_FILLNULL command_params_fields_or_args
               | CMD_ANOMALOUSVALUE command_params_fields_or_args
               | CMD_ANOMALYDETECTION command_params_fields_or_args
               | CMD_ARULES command_params_fields_or_args
               | CMD_ASSOCIATE command_params_fields_or_args
               | CMD_TRANSACTION command_params_fields_or_args
               | CMD_FIELDSUMMARY command_params_fields_or_args
               | CMD_OUTLIER command_params_fields_or_args
               | CMD_KMEANS command_params_fields_or_args
               | CMD_MCOLLECT command_params_fields_or_args
               | CMD_MEVENTCOLLECT command_params_fields_or_args
               | CMD_SCRIPT command_params_fields_or_args
               | CMD_SELFJOIN command_params_fields_or_args'''
    p[0] = {"type":"command","input":p[2]["fields"],"output":[],"fields-effect":"none","content":[]}
    checkArgs(p,p[2]["args"])
    p[0] = commands_args_and_fields_output_update(p,p[2]["args"])
    
# Performs the transformations necessary for the generic rules of command
# containing arguments, a fields list or both or even none of all
def commands_args_and_fields_output_update(p,args):
    global cmd_conf
    out=p[0]
    if p[1] == "anomalydetection":
        if "action" in args:
            if args["action"] in ["filter","annotate"]:
                out["output"] = cmd_conf[p[1]]["created_fields"]["annotate_filter"]
            elif args["action"] in ["summary"]:
                out["output"] = cmd_conf[p[1]]["created_fields"]["summary"]
                out["fields-effect"]="replace"
        else:
            out["output"] = cmd_conf[p[1]]["created_fields"]["annotate_filter"]
    elif p[1] in ["af","analyzefields"]:
        out["input"] = p[2]["args"].values()
        out["output"] = cmd_conf[p[1]]["created_fields"]
        out["fields-effect"] = "replace"
    elif p[1] == "associate":
        out["output"] = cmd_conf[p[1]]["created_fields"]
        out["fields-effect"] = "replace"
    elif p[1] == "bucketdir":
        if "pathfield" in args:
            out["input"].append(args["pathfield"])
    elif p[1] == "table":
        out = {"type":"command","input":p[2]["input"],"output":p[2]["input"],"fields-effect":"replace"}
    elif p[1] == "cluster":
        if "field" in args:
                p[0]["input"].append(args["field"])
    elif p[1] == "dbinspect":
        out["fields-effect"] = "replace"
        out["output"] = cmd_conf[p[1]]["created_fields"]
        if "index" in args:
            out["input"].append("index")
            out["content"]=[args["index"]]
    elif p[1] == "diff":
        if "attribute" in args:
            p[0]["input"].append(args["attribute"])
    elif p[1] == "eventcount":
        if "index" in args:
            if isinstance(args["index"],list):
                p[0]["content"] = args["index"]
            else:
                p[0]["content"] = [args["index"]]
    elif p[1] == "makeresults":
        out["fields-effect"] = "generate"
        out["output"] = cmd_conf[p[1]]["created_fields"]["default"]
        if "annotate" in args and args["annotate"] in ["t","true","TRUE","True"]:
            out["output"] = cmd_conf[p[1]]["created_fields"]["annotate"]
    elif p[1] == "fieldsummary":
        out["fields-effect"] = "replace"
        out["output"] = cmd_conf[p[1]]["created_fields"]
    elif p[1] == "gentimes":
        out["fields-effect"] = "generate"
        out["output"] = cmd_conf[p[1]]["created_fields"]
    elif p[1] == "highlight":
        out["content"] = p[0]["input"]
        out["input"] = []
    elif p[1] == "history":
        out["fields-effect"] = "generate"
        if "events" in args and args["events"] in ["true","t","True"]:
            out["output"] += cmd_conf[p[1]]["created_fields"]["true"]
        else:
            out["output"] += cmd_conf[p[1]]["created_fields"]["false"]
    elif p[1] == "kmeans":
        if "cfield" in args:
            out["output"].append(args["cfield"])
        else:
            out["output"] += cmd_conf[p[1]]["created_fields"]
            out["fields-effect"] = "extend"
    elif p[1] == "kvform":
        if "field" in args:
            p[0]["input"].append(args["field"])
    elif p[1] in ["mcollect","meventcollect"]:
        if not "index" in args:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Missing index argument in command {}".format(p[1]),None,value="index")
    elif p[1] == "metadata":
        out["fields-effect"] = "generate"
        if not "type" in args:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Missing type argument in command {}".format(p[1]),None,value="type")
        elif args["type"] in cmd_conf[p[1]]["types"]:
            p[0]["output"].append(cmd_conf[p[1]]["types"][args["type"]])
        else:
            arg=args["type"]
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Invalid type {} in command {}, expected {}".format(arg,p[1],list(cmd_conf[p[1]]["types"].keys())),None,value=arg)
        if "index" in args:
            if isinstance(args["index"],list):
                out["content"] += args["index"]
            else:
                out["content"].append(args["index"])
        out["output"] += cmd_conf[p[1]]["created_fields"]
    elif p[1] == "mpreview":
        out["fields-effect"] = "generate"
        if "index" in args:
            if isinstance(args["index"],list):
                out["content"] += args["index"]
            else:
                out["content"].append(args["index"])
        if "filter" in args:
            out["content"].append(args["filter"])
    elif p[1] in ["outputtext","relevancy","reltime"]:
        out["fields-effect"] = "extend"
        out["output"] += cmd_conf[p[1]]["created_fields"]
    elif p[1] in ["script","run"]:
        out["content"] = out["input"]
        out["input"] = []
    elif p[1] == "sendemail":
        if not "to" in args:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Missing 'to' argument in command {}".format(p[1]),None,value="to")

    return out

# WHERE
def p_command_where(p):
    'command : CMD_WHERE expression'
    p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"none","content":[p[2]["content"]]}

# ACCUM
def p_command_accum(p):
    '''command : CMD_ACCUM field_name AS_CLAUSE field_name
               | CMD_ACCUM field_name'''
    if len(p) == 5:
        p[0] = {"type":"command","input":[p[2]["field"]],"output":[p[4]["field"]],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":[p[2]["field"]],"output":[],"fields-effect":"none"}

# ANOMALIES
def p_command_anomalies(p):
    '''command : CMD_ANOMALIES args_list BY_CLAUSE fields_list
               | CMD_ANOMALIES BY_CLAUSE fields_list
               | CMD_ANOMALIES args_list
               | CMD_ANOMALIES'''
    ipt=[]
    if len(p) == 5 or len(p) == 3:
        checkArgs(p,p[2]["args"])
        if "field" in p[2]["args"]:
            ipt.append(p[2]["args"]["field"])                
    
    p[0] = {"type":"command","input":ipt,"output":cmd_conf[p[1]]["created_fields"],"fields-effect":"extend"}

# APPEND
def p_command_append(p):
    '''command : CMD_APPEND args_list subsearch
               | CMD_APPENDCOLS args_list subsearch
               | CMD_APPEND subsearch
               | CMD_APPENDCOLS subsearch'''
    if len(p) == 4:
        checkArgs(p,p[2]["args"])
        p[0] = {"type":"command","input":p[3]["input"],"output":p[3]["output"],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}

# APPENDPIPE
def p_command_appendpipe(p):
    '''command : CMD_APPENDPIPE args_term subpipeline
               | CMD_APPENDPIPE subpipeline'''
    if len(p) == 4:
        checkArgs(p,p[2])
        p[0] = {"type":"command","input":p[3]["input"],"output":p[3]["output"],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}

# AUTOREGRESS
def p_command_autoregress(p):
    '''command : CMD_AUTOREGRESS rfield_term NAME EQ NUMBER
               | CMD_AUTOREGRESS field_name NAME EQ NUMBER
               | CMD_AUTOREGRESS rfield_term NAME EQ NAME
               | CMD_AUTOREGRESS field_name NAME EQ NAME
               | CMD_AUTOREGRESS rfield_term
               | CMD_AUTOREGRESS field_name'''
    if len(p) == 6 :
        checkArgs(p,p[3])
    if p[2]["type"] == "rfield_term":
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}
    elif p[2]["type"] == "field_name":
        p[0] = {"type":"command","input":[p[2]["field"]],"output":[],"fields-effect":"none"}

# BIN / BUCKET
def p_command_bin(p):
    '''command : CMD_BIN args_list rfield_term args_list
               | CMD_BIN args_list field_name args_list
               | CMD_BIN args_list field_name args_list AS_CLAUSE field_name args_list
               | CMD_BIN field_name args_list AS_CLAUSE field_name args_list
               | CMD_BIN args_list field_name args_list AS_CLAUSE field_name
               | CMD_BIN field_name args_list AS_CLAUSE field_name
               | CMD_BIN rfield_term args_list
               | CMD_BIN field_name args_list
               | CMD_BIN args_list rfield_term
               | CMD_BIN args_list field_name
               | CMD_BIN rfield_term
               | CMD_BIN field_name'''
    args={}
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend"}
    
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "rfield_term":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
            elif pp["type"] == "field_name":
                if len(p[0]["input"]) == 0:
                    p[0]["input"].append(pp["field"])
                else:
                    p[0]["output"].append(pp["field"])
    checkArgs(p,args)

# TOP
def p_command_top(p):
    '''command : CMD_TOP NUMBER command_params_by_and_fields_or_args
               | CMD_TOP command_params_by_and_fields_or_args'''
    data=p[len(p)-1]
    if "args" in data["args"]:
            checkArgs(p,data["args"]["args"])
    p[0] = {"type":"command","input":data["fields"]+data["by"],"output":[],"fields-effect":"none"}

# CHART
def p_command_chart(p):
    '''command : CMD_CHART command_chart_1 command_chart_2'''
    p[0] = {"type":"command","input":p[2]["input"]+p[3]["fields"],"output":p[2]["output"],"fields-effect":"replace"}
    args=p[2]["args"]
    extendDict(args,p[3]["args"])
    if "modes" in p[3] and "chart_by" in p[3]["modes"]:
        p[0]["output"] += p[3]["fields"]
    checkArgs(p,args)

def p_command_chart_1(p):
    '''command_chart_1 : args_list agg_or_eval_list
                       | agg_or_eval_list'''
    p[0] = {"type":"chart_1","input":p[len(p)-1]["input"],"output":p[len(p)-1]["output"],"args":{}}
    if len(p) == 3:
        extendDict(p[0]["args"],p[1]["args"])

def p_command_chart_2(p):
    '''command_chart_2 : command_chart_by_1
                       | command_chart_by_2
                       | command_chart_over
                       | command_chart_over command_chart_by_1
                       | command_chart_by_1 args_term
                       | command_chart_by_2 args_term
                       | command_chart_over args_term
                       | command_chart_over command_chart_by_1 args_term'''
    p[0] = {"type":"chart_2","fields":[],"args":{},"modes":[]}
    for pp in p:
        if "type" in pp:
            extendDict(p[0]["args"],pp["args"])
            p[0]["fields"] += pp["fields"]
            p[0]["modes"].append(pp["type"])
        else:
            extendDict(p[0]["args"],pp)

def p_command_chart_by_2(p):
    '''command_chart_by_2 : BY_CLAUSE field_name args_list field_name args_list chart_where_clause
                          | BY_CLAUSE field_name args_list field_name args_list
                          | BY_CLAUSE field_name field_name args_list chart_where_clause
                          | BY_CLAUSE field_name field_name args_list
                          | BY_CLAUSE field_name args_list field_name chart_where_clause
                          | BY_CLAUSE field_name args_list field_name
                          | BY_CLAUSE field_name field_name chart_where_clause
                          | BY_CLAUSE field_name field_name'''
    p[0] = {"type":"chart_by","fields":[],"args":{}}
    for pp in p[2:]:
        if "type" in pp:
                if pp["type"] == "args_list":
                    extendDict(p[0]["args"],pp["args"])
                elif pp["type"] == "field_name":
                    p[0]["fields"].append(pp["field"])


def p_command_chart_by_1(p):
    '''command_chart_by_1 : BY_CLAUSE field_name args_list chart_where_clause
                          | BY_CLAUSE field_name args_list
                          | BY_CLAUSE field_name chart_where_clause
                          | BY_CLAUSE field_name'''
    p[0] = {"type":"chart_by","fields":[p[2]["field"]],"args":{}}
    if len(p) > 3:
        if "type" in p[3] and p[3]["type"] == "args_list":
            p[0]["args"]=p[3]["args"]

def p_command_chart_over(p):
    '''command_chart_over : OVER_OP field_name args_list
                          | OVER_OP field_name'''
    p[0] = {"type":"chart_over","fields":[p[2]["field"]],"args":{}}
    if len(p) == 4:
        p[0]["args"]=p[3]["args"]


def p_command_chart_where_clause(p):
    '''chart_where_clause : agg_term IN_OP CMD_TOP NUMBER
                          | agg_term IN_OP BOTTOM_OP NUMBER
                          | agg_term NOTIN_OP CMD_TOP NUMBER
                          | agg_term NOTIN_OP BOTTOM_OP NUMBER
                          | agg_term COMP_OP NUMBER
                          | agg_term COMP_OP FLOAT'''
    p[0] = {"type":"chart_where_clause","fields":p[1]["input"],"options":[],"value":p[len(p)-1]}
    if len(p) > 4:
        p[0]["options"].append(p[2]).append(p[3]) 

# COFILTER
def p_command_cofilter(p):
    'command : CMD_COFILTER field_name field_name'
    p[0] = {"type":"command","input":[p[2]["field"],p[2]["field"]],"output":[],"fields-effect":"replace"}

# CONTINGENCY
def p_command_contingency(p):
    '''command : CMD_CONTINGENCY args_list field_name fields_list args_list
               | CMD_CONTINGENCY args_list field_name fields_list
               | CMD_CONTINGENCY field_name fields_list args_list
               | CMD_CONTINGENCY field_name field_name'''
    args={}
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"replace"}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["input"].append(pp["field"])
    # First field appears in the results along with the values of the second field
    p[0]["output"].append(p[0]["input"][0])
    checkArgs(p,args)

# CONVERT
def p_command_convert(p):
    '''command : CMD_CONVERT args_term convert_list
               | CMD_CONVERT convert_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_term":
                extendDict(args,pp["args"])
            elif pp["type"] == "convert_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
    checkArgs(p,args)

def p_command_convert_list(p):
    '''convert_list : convert_list COMMA convert_fun
                    | convert_list convert_fun
                    | convert_fun'''
    p[0] = {"type":"convert_list","input":p[1]["input"],"output":p[1]["output"],"op":p[1]["op"]}
    if len(p) > 2:
        p[0]["input"] += p[len(p)-1]["input"]
        p[0]["output"] += p[len(p)-1]["output"]


def p_command_convert_fun(p):
    '''convert_fun : NAME LPAREN field_name RPAREN
                   | NAME LPAREN field_name RPAREN AS_CLAUSE field_name
                   | NAME LPAREN TIMES RPAREN
                   | NAME LPAREN TIMES RPAREN AS_CLAUSE field_name'''
    p[0] = {"type":"convert_fun","input":[],"output":[],"op":[p[1]]}
    if isinstance(p[3],dict):
        p[0]["input"].append(p[3]["field"])
    else:
        p[0]["input"].append(p[3])
    if isinstance(p[len(p)-1],dict) and p[len(p)-1]["type"] == "field_name":
        p[0]["output"].append(p[len(p)-1]["field"])

# DATAMODEL
def p_command_datamodel(p):
    '''command : CMD_DATAMODEL field_name field_name args_list field_name args_list
               | CMD_DATAMODEL field_name field_name field_name args_list
               | CMD_DATAMODEL field_name field_name args_list field_name 
               | CMD_DATAMODEL field_name args_list field_name args_list
               | CMD_DATAMODEL field_name field_name args_list
               | CMD_DATAMODEL field_name args_list field_name 
               | CMD_DATAMODEL field_name args_list
               | CMD_DATAMODEL args_list
               | CMD_DATAMODEL field_name field_name field_name
               | CMD_DATAMODEL field_name field_name
               | CMD_DATAMODEL field_name
               | CMD_DATAMODEL'''
    global cmd_conf
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"generate"}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "field_name":
                p[0]["output"].append(pp["field"])
        else:
            p[0]["output"].append(pp)
    if len(p[0]["output"]) == 3:
        sm=p[0]["output"][2]
        if not sm in cmd_conf[p[1]]["search_modes"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected datamode search mode '{}', expected {}".format(sm,cmd_conf[p[1]]["search_modes"]),None,value=sm)
    checkArgs(p,args)

# DELTA
def p_command_delta(p):
    '''command : CMD_DELTA args_term field_name AS_CLAUSE field_name
               | CMD_DELTA field_name AS_CLAUSE field_name args_term
               | CMD_DELTA field_name AS_CLAUSE field_name
               | CMD_DELTA args_term field_name
               | CMD_DELTA field_name args_term
               | CMD_DELTA field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend"}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_term":
                extendDict(args,pp["args"])
            elif pp["type"] == "field_name":
                if len(p[0]["input"]) == 0:
                    p[0]["input"].append(pp["field"])
                else:
                    p[0]["output"].append(pp["field"])
    if len(p[0]["output"]) == 0:
        p[0]["output"].append("{}({})".format(p[1],p[0]["input"][0]))
    checkArgs(p,args)

# EREX
def p_command_erex(p):
    '''command : CMD_EREX args_list field_name args_list
               | CMD_EREX args_list field_name
               | CMD_EREX field_name args_list
               | CMD_EREX args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend"}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["output"].append(pp["field"])
    if "fromfield" in args:
        p[0]["input"].append(args["fromfield"])
    checkArgs(p,args)

# EVENTSTATS
def p_command_eventstats(p):
    '''command : CMD_EVENTSTATS args_term agg_terms_list BY_CLAUSE fields_list
               | CMD_EVENTSTATS agg_terms_list BY_CLAUSE fields_list args_term
               | CMD_EVENTSTATS agg_terms_list args_term BY_CLAUSE fields_list
               | CMD_EVENTSTATS agg_terms_list BY_CLAUSE fields_list
               | CMD_EVENTSTATS args_term agg_terms_list
               | CMD_EVENTSTATS agg_terms_list args_term
               | CMD_EVENTSTATS agg_terms_list
               '''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend"}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_term":
                extendDict(args,pp["args"])
            elif pp["type"] == "agg_terms_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
            elif pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
    checkArgs(p,args)

# EXTRACT
def p_command_extract(p):
    '''command : CMD_EXTRACT args_list value args_list
               | CMD_EXTRACT value args_list
               | CMD_EXTRACT args_list value
               | CMD_EXTRACT args_list
               | CMD_EXTRACT value
               | CMD_EXTRACT'''
    p[0] = {"type":"command","input":["_raw"],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "value":
            p[0]["content"].append(pp["value"])
    checkArgs(p,args)

# FIELDFORMAT
def p_command_fieldformat(p):
    'command : CMD_FIELDFORMAT field_name EQ expression_value'
    p[0] = {"type":"command","input":[p[2]["field"]],"output":[],"fields-effect":"none","content":[p[4]["content"]]}

# FINDTYPES
def p_command_findtypes(p):
    '''command : CMD_FINDTYPES args_term field_name field_name
               | CMD_FINDTYPES args_term field_name
               | CMD_FINDTYPES args_term
               | CMD_FINDTYPES'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_term":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            arg=pp["field"]
            if not arg in cmd_conf[p[1]]["modes"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["modes"])),None,value=arg)
    checkArgs(p,args)

# FOREACH
def p_command_foreach(p):
    '''command : CMD_FOREACH args_list fields_list args_list subsearch_foreach
               | CMD_FOREACH fields_list args_list subsearch_foreach
               | CMD_FOREACH args_list fields_list subsearch_foreach
               | CMD_FOREACH fields_list subsearch_foreach
               | CMD_FOREACH args_list TIMES args_list subsearch_foreach
               | CMD_FOREACH TIMES args_list subsearch_foreach
               | CMD_FOREACH args_list TIMES subsearch_foreach
               | CMD_FOREACH TIMES subsearch_foreach'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
            elif pp["type"] == "subsearch_foreach":
                p[0]["input"] += pp["input"]
                p[0]["content"] += pp["content"]
        else:
            p[0]["input"].append(pp)
    checkArgs(p,args)

def p_command_foreach_subsearch(p):
    '''subsearch_foreach : LBRACK CMD_EVAL eval_expr_assign RBRACK'''
    p[0] = {"type":"subsearch_foreach","input":p[3]["input"],"output":p[3]["output"],"fields-effect":"none","content":p[3]["content"]}

# FORMAT
def p_command_format(p):
    '''command : CMD_FORMAT args_list STRING STRING STRING STRING STRING STRING args_list
               | CMD_FORMAT STRING STRING STRING STRING STRING STRING args_list
               | CMD_FORMAT args_list STRING STRING STRING STRING STRING STRING
               | CMD_FORMAT STRING STRING STRING STRING STRING STRING
               | CMD_FORMAT args_list
               | CMD_FORMAT'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
        else:
            p[0]["content"].append(pp)
    checkArgs(p,args)

# FROM
def p_command_from(p):
    '''command : CMD_FROM field_name COLON field_name
               | CMD_FROM field_name field_name
               | CMD_FROM field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"generate","content":[]}
    if len(p) > 3:
        p[0]["input"].append("{}:{}".format(p[2]["field"],p[len(p)-1]["field"]))
    else:
        arg=p[2]["field"]
        if not ":" in arg:
            report_error(p.lexpos(1),p.lexspan(2)[0]+len(arg),"Malformated dataset information '{}' in {}, expected <dataset_type>:<dataset_name>".format(arg,p[1]),None,value=arg)
        else:
            p[0]["input"].append(arg)

#GAUGE
def p_command_gauge(p):
    'command : CMD_GAUGE field_or_num_list'
    p[0] = {"type":"command","input":p[2]["input"],"output":["x"],"fields-effect":"replace","content":[]}
    if len(p[2]["values"]) > 1:
        for i in range(1,len(p[2]["values"])):  # adding y1, y2 depending on the number of range values
            p[0]["output"].append("y{}".format(i))
    else:
        p[0]["output"] += ["y1","y2"] #default 2 values, range = 0 to 100

# GEOM
def p_command_geom(p):
    '''command : CMD_GEOM args_list field_name args_list
               | CMD_GEOM args_list field_name
               | CMD_GEOM field_name args_list
               | CMD_GEOM field_name
               | CMD_GEOM'''
    p[0] = {"type":"command","input":[],"output":[cmd_conf[p[1]]["created_fields"]],"fields-effect":"extend","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["content"].append(pp["field"])
    checkArgs(p,args)
    if "featureIdField" in args:
        p[0]["input"].append(args["featureIdField"])
    else:
        p[0]["input"].append("featureId")

# GEOSTATS
def p_command_geostats(p):
    '''command : CMD_GEOSTATS args_list agg_terms_list BY_CLAUSE field_name args_list
               | CMD_GEOSTATS args_list agg_terms_list BY_CLAUSE field_name
               | CMD_GEOSTATS agg_terms_list BY_CLAUSE field_name args_list
               | CMD_GEOSTATS args_list agg_terms_list args_list
               | CMD_GEOSTATS args_list agg_terms_list
               | CMD_GEOSTATS agg_terms_list args_list
               | CMD_GEOSTATS agg_terms_list'''
    p[0] = {"type":"command","input":[],"output":[cmd_conf[p[1]]["created_fields"]],"fields-effect":"replace","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "agg_terms_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
                p[0]["content"] += pp["content"]
            elif pp["type"] == "field_name":
                p[0]["input"].append(pp["field"])
    checkArgs(p,args)

# HEAD
def p_commend_head(p):
    '''command : CMD_HEAD args_list expression args_list
               | CMD_HEAD expression args_list
               | CMD_HEAD args_list expression
               | CMD_HEAD expression
               | CMD_HEAD'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "expression":
                p[0]["content"].append(pp["content"])
    checkArgs(p,args)

# INPUTLOOKUP / INPUTCSV
def p_command_inputlookup(p):
    '''command : CMD_INPUTLOOKUP args_list field_name CMD_WHERE expression
               | CMD_INPUTLOOKUP field_name CMD_WHERE expression
               | CMD_INPUTLOOKUP args_list field_name
               | CMD_INPUTLOOKUP field_name
               | CMD_INPUTCSV args_list field_name CMD_WHERE expression
               | CMD_INPUTCSV field_name CMD_WHERE expression
               | CMD_INPUTCSV args_list field_name
               | CMD_INPUTCSV field_name'''

    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"generate","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "expression":
                p[0]["content"].append(pp["content"])
            elif pp["type"] == "field_name":
                p[0]["content"].append(pp["field"])
    checkArgs(p,args)

# IPLOCATION
def p_command_iplocation(p):
    '''command : CMD_IPLOCATION args_list field_name args_list
               | CMD_IPLOCATION field_name args_list
               | CMD_IPLOCATION args_list field_name
               | CMD_IPLOCATION field_name
               | CMD_IPLOCATION'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["input"].append(pp["field"])
    flist=cmd_conf[p[1]]["created_fields"]["default"]
    prefix=""
    if "allfields" in args and args["allfields"] in ["true","t","True"]:
        flist += cmd_conf[p[1]]["created_fields"]["extended"]
    if "prefix" in args:
        prefix=args["prefix"]
    p[0]["output"] += [prefix+f for f in flist]
    checkArgs(p,args)

# JOIN
def p_command_join(p):
    '''command : CMD_JOIN args_list fields_list args_list subsearch args_list
               | CMD_JOIN args_list fields_list args_list subsearch
               | CMD_JOIN fields_list args_list subsearch args_list
               | CMD_JOIN args_list fields_list subsearch args_list
               | CMD_JOIN args_list fields_list subsearch
               | CMD_JOIN fields_list args_list subsearch
               | CMD_JOIN fields_list subsearch
               | CMD_JOIN args_list subsearch args_list
               | CMD_JOIN args_list subsearch
               | CMD_JOIN subsearch args_list
               | CMD_JOIN subsearch'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "fields_list":
            p[0]["input"] += pp["input"]
        elif pp["type"] == "subsearch":
            p[0]["input"] += pp["input"]
            p[0]["output"] += pp["output"]
            p[0]["content"] += pp["content"]
    checkArgs(p,args)

# LOADJOB
def p_command_loadjob(p):
    '''command : CMD_LOADJOB value args_list
               | CMD_LOADJOB args_list
               | CMD_LOADJOB value'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"generate","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "value":
            p[0]["content"].append(pp["value"])
    if "savedsearch" in args:
        p[0]["content"].append(args["savedsearch"])
    checkArgs(p,args)

# LOOKUP
def p_command_lookup(p):
    '''command : CMD_LOOKUP field_name any_fields_list OUTPUT_OP any_fields_list
               | CMD_LOOKUP field_name any_fields_list OUTPUT_NEW_OP any_fields_list
               | CMD_LOOKUP field_name any_fields_list
               | CMD_LOOKUP field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend","content":[p[2]["field"]]}
    args={}
    if len(p) > 3:
        p[0]["input"] += p[3]["input"]+p[3]["output"]
    if len(p) > 4:
        p[0]["output"] = p[5]["input"]

def p_command_lookup_args(p):
    '''command : CMD_LOOKUP args_list field_name any_fields_list OUTPUT_OP any_fields_list
               | CMD_LOOKUP args_list field_name any_fields_list OUTPUT_NEW_OP any_fields_list
               | CMD_LOOKUP args_list field_name any_fields_list
               | CMD_LOOKUP args_list field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend","file":p[3]["field"]}
    if len(p) > 4:
        p[0]["input"] += p[4]["input"]+p[4]["output"]
    if len(p) > 6:
        p[0]["output"] = p[5]["input"]
    checkArgs(p,p[2]["args"])

# MAKECONTINUOUS
def p_command_makecontinuous(p):
    '''command : CMD_MAKECONTINUOUS args_list field_name args_list
               | CMD_MAKECONTINUOUS field_name args_list
               | CMD_MAKECONTINUOUS args_list field_name
               | CMD_MAKECONTINUOUS args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "field_name":
                p[0]["input"].append(pp["field"])
    checkArgs(p,args)

# MAKEMV
def p_command_makemv(p):
    '''command : CMD_MAKEMV args_list field_name args_list
               | CMD_MAKEMV args_list field_name
               | CMD_MAKEMV field_name args_list
               | CMD_MAKEMV field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "field_name":
                p[0]["input"].append(pp["field"])
    checkArgs(p,args)

# MAP
def p_command_map(p):
    '''command : CMD_MAP args_list value
               | CMD_MAP value args_list
               | CMD_MAP value
               | CMD_MAP args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "value":
            p[0]["content"].append(pp["value"])
    if "search" in args:
        p[0]["content"].append(args["search"])
    checkArgs(p,args)

# METASEARCH
def p_command_metasearch(p):
    '''command : CMD_METASEARCH filters
               | CMD_METASEARCH'''
    p[0] = {"type":"command","input":[],"output":cmd_conf[p[1]]["created_fields"],"fields-effect":"generate","content":[]}
    if len(p) > 2:
        p[0]["input"] = p[2]["input"]
        p[0]["content"] = [p[2]["content"]]

# MSTATS
def p_command_mstats(p):
    '''command : CMD_MSTATS mstats_1 mstats_2
               | CMD_MSTATS mstats_1'''
    p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"generate","content":p[2]["content"]}
    args=p[2]["args"]
    if len(p) > 3:
        extendDict(args,p[3]["args"])
        p[0]["input"] += p[3]["input"]
        p[0]["output"] += p[3]["output"]
        p[0]["content"] += p[3]["content"]
    checkArgs(p,args)

def p_command_mstats_1(p):
    '''mstats_1 : args_list agg_terms_list args_list
                | args_list agg_terms_list
                | agg_terms_list args_list
                | agg_terms_list'''
    p[0] = {"type":"mstats_1","input":[],"output":[],"fields-effect":"none","content":[],"args":{}}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(p[0]["args"],pp["args"])
        elif pp["type"] == "agg_terms_list":
            p[0]["input"] += pp["input"]
            p[0]["output"] += pp["output"]
            p[0]["content"] += pp["content"]

def p_command_mstats_2(p):
    '''mstats_2 : mstats_2_where mstats_2_by
                | mstats_2_where
                | mstats_2_by'''
    p[0] = {"type":"mstats_2","input":p[1]["input"],"output":p[1]["output"],"fields-effect":"none","content":p[1]["content"],"args":p[1]["args"]}
    if len(p) > 2:
        extendDict(p[0]["args"],p[2]["args"])
        p[0]["input"] += p[2]["input"]
        p[0]["output"] += p[2]["output"]
        p[0]["content"] += p[2]["content"]


def p_command_mstats_2_where(p):
    '''mstats_2_where : CMD_WHERE filters args_list mstats_2_by
                      | CMD_WHERE filters mstats_2_by
                      | CMD_WHERE filters args_list
                      | CMD_WHERE filters'''
    p[0] = {"type":"mstats_2_where","input":[],"output":[],"fields-effect":"none","content":[],"args":{}}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(p[0]["args"],pp["args"])
            elif pp["type"] == "filters":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
                p[0]["content"] += pp["content"]
            elif pp["type"] == "mstats_2_by":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
                p[0]["content"] += pp["content"]

def p_command_mstats_2_by(p):
    '''mstats_2_by : BY_CLAUSE fields_list args_list
                   | GROUPBY_CLAUSE fields_list args_list
                   | BY_CLAUSE fields_list
                   | GROUPBY_CLAUSE fields_list'''
    p[0] = {"type":"mstats_2_by","input":[],"output":[],"fields-effect":"none","content":[],"args":{}}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(p[0]["args"],pp["args"])
            elif pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]

# MULTIKV
def p_command_multikv(p):
    '''command : CMD_MULTIKV args_list CMD_FIELDS fields_list args_list FILTER_OP values_list args_list
               | CMD_MULTIKV args_list CMD_FIELDS fields_list args_list FILTER_OP values_list
               | CMD_MULTIKV args_list CMD_FIELDS fields_list FILTER_OP values_list args_list
               | CMD_MULTIKV CMD_FIELDS fields_list args_list NAME values_list args_list
               | CMD_MULTIKV CMD_FIELDS fields_list FILTER_OP values_list args_list
               | CMD_MULTIKV args_list CMD_FIELDS fields_list FILTER_OP values_list
               | CMD_MULTIKV CMD_FIELDS fields_list args_list FILTER_OP values_list
               | CMD_MULTIKV CMD_FIELDS fields_list FILTER_OP values_list
               | CMD_MULTIKV args_list CMD_FIELDS fields_list args_list
               | CMD_MULTIKV args_list CMD_FIELDS fields_list
               | CMD_MULTIKV CMD_FIELDS fields_list args_list
               | CMD_MULTIKV CMD_FIELDS fields_list
               | CMD_MULTIKV args_list FILTER_OP values_list args_list
               | CMD_MULTIKV FILTER_OP values_list args_list
               | CMD_MULTIKV args_list FILTER_OP values_list
               | CMD_MULTIKV FILTER_OP values_list
               | CMD_MULTIKV args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
            elif pp["type"] == "values_list":
                p[0]["content"] += pp["values"]
        else:
            if not pp in cmd_conf[p[1]]["selectors"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected selector {} in {}, expected {}".format(pp,p[1],cmd_conf[p[1]]["selectors"]),None,value=pp)
    checkArgs(p,args)

# MULTISEARCH
def p_command_multisearch(p):
    '''command : CMD_MULTISEARCH subsearches'''
    p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"generate","content":p[2]["content"]}

# MVCOMBINE / MVEXPAND
def p_command_mvcombine(p):
    '''command : CMD_MVCOMBINE args_term field_name
               | CMD_MVCOMBINE field_name args_term
               | CMD_MVCOMBINE field_name
               | CMD_MVEXPAND args_term field_name
               | CMD_MVEXPAND field_name args_term
               | CMD_MVEXPAND field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    for pp in p[2:]:
        if pp["type"] == "args_term":
            checkArgs(p,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["input"].append(pp["field"])

# OUTPUTLOOKUP / OUTPUTCSV
def p_command_outputlookup(p):
    '''command : CMD_OUTPUTLOOKUP args_list field_name args_list
               | CMD_OUTPUTLOOKUP args_list field_name
               | CMD_OUTPUTLOOKUP field_name args_list
               | CMD_OUTPUTLOOKUP field_name
               | CMD_OUTPUTCSV args_list field_name args_list
               | CMD_OUTPUTCSV args_list field_name
               | CMD_OUTPUTCSV field_name args_list
               | CMD_OUTPUTCSV field_name'''

    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["content"].append(pp["field"])
    checkArgs(p,args)

# PIVOT
def p_command_pivot(p):
    '''command : CMD_PIVOT field_name field_name pivot_element'''
    p[0] = {"type":"command","input":p[4]["input"],"output":p[4]["output"],"fields-effect":"generate","content":[p[2]["field"],p[3]["field"]]+p[4]["content"]}

    checkArgs(p,p[4]["args"])

def p_command_pivot_element(p):
    '''pivot_element : pivot_cell_value pivot_split pivot_element_2
                     | pivot_cell_value COMMA pivot_split COMMA pivot_element_2
                     | pivot_cell_value pivot_split
                     | pivot_cell_value COMMA pivot_split
                     | pivot_cell_value'''
    p[0] = {"type":"pivot_element","input":[],"output":[],"content":[],"args":{}}
    for pp in p[1:]:
        if isinstance(pp,dict):
            extendDict(p[0]["args"],pp["args"])
            p[0]["input"] += pp["input"]
            p[0]["output"] += pp["output"]
            p[0]["content"] += pp["content"]

def p_command_pivot_cell_value(p):
    '''pivot_cell_value : NAME LPAREN field_name RPAREN AS_CLAUSE field_name
                        | NAME LPAREN field_name RPAREN'''
    p[0] = {"type":"pivot_cell_value","input":[p[3]["field"]],"output":[],"content":[],"args":{}}
    if len(p) > 5:
        p[0]["output"].append(p[len(p)-1]["field"])

def p_command_pivot_split(p):
    '''pivot_split : pivot_splitcol COMMA pivot_split
                   | pivot_splitrow COMMA pivot_split
                   | pivot_splitcol pivot_split
                   | pivot_splitrow pivot_split
                   | pivot_splitcol
                   | pivot_splitrow'''
    p[0] = {"type":"pivot_split","input":[],"output":[],"content":[],"args":{}}
    for pp in p[1:]:
        if isinstance(pp,dict):
            extendDict(p[0]["args"],pp["args"])
            p[0]["input"] += pp["input"]
            p[0]["output"] += pp["output"]
            p[0]["content"] += pp["content"]

def p_command_pivot_splitcol(p):
    '''pivot_splitcol : SPLITCOL_OP field_name RANGE_OP basic_args_list
                      | SPLITCOL_OP field_name PERIOD_OP NAME
                      | SPLITCOL_OP field_name TRUELABEL_OP field_name FALSELABEL_OP field_name
                      | SPLITCOL_OP field_name TRUELABEL_OP field_name
                      | SPLITCOL_OP field_name FALSELABEL_OP field_name
                      | SPLITCOL_OP field_name'''
    p[0] = {"type":"pivot_splitcol","input":[p[2]["field"]],"output":[p[2]["field"]],"content":[],"args":{}}
    if len(p) > 3:
        if not isinstance(p[4],dict):
            p[0]["content"].append(p[4])
        elif p[4]["type"] == "field_name":
            p[0]["content"].append(p[4]["field"])
        elif p[4]["type"] == "basic_args_list":
            extendDict(p[0]["args"],p[4]["args"])
    if len(p) > 5:
        p[0]["content"].append(p[6]["field"])

def p_command_pivot_splitrow(p):
    '''pivot_splitrow : SPLITROW_OP field_name RANGE_OP basic_args_list
                      | SPLITROW_OP field_name PERIOD_OP NAME
                      | SPLITROW_OP field_name TRUELABEL_OP field_name FALSELABEL_OP field_name
                      | SPLITROW_OP field_name TRUELABEL_OP field_name
                      | SPLITROW_OP field_name FALSELABEL_OP field_name
                      | SPLITROW_OP field_name
                      | SPLITROW_OP field_name AS_CLAUSE field_name RANGE_OP args_list
                      | SPLITROW_OP field_name AS_CLAUSE field_name PERIOD_OP NAME
                      | SPLITROW_OP field_name AS_CLAUSE field_name TRUELABEL_OP field_name FALSELABEL_OP field_name
                      | SPLITROW_OP field_name AS_CLAUSE field_name TRUELABEL_OP field_name
                      | SPLITROW_OP field_name AS_CLAUSE field_name FALSELABEL_OP field_name
                      | SPLITROW_OP field_name AS_CLAUSE field_name'''
    p[0] = {"type":"pivot_splitrow","input":[p[2]["field"]],"output":[p[2]["field"]],"content":[],"args":{}}
    if len(p) > 3:
        for i in range(4,len(p)):
            pp=p[i]
            if isinstance(pp,dict):
                if pp["type"] == "basic_args_list":
                    extendDict(p[0]["args"],pp["args"])
                elif pp["type"] == "field_name":
                    if p[i-1] == "as":
                        p[0]["output"]=[pp["field"]]
                    else:
                        p[0]["content"].append(pp["field"])
            elif p[i-1] == "period":
                p[0]["content"].append(pp)

def p_command_pivot_element_2(p):
    '''pivot_element_2 : pivot_element_term pivot_element_2
                       | pivot_element_term'''
    p[0] = {"type":"pivot_element_2","input":[],"output":[],"content":[],"args":{}}
    for pp in p[1:]:
        extendDict(p[0]["args"],pp["args"])
        p[0]["input"] += pp["input"]
        p[0]["output"] += pp["output"]
        p[0]["content"] += pp["content"]

def p_command_pivot_element_term(p):
    '''pivot_element_term : FILTER_OP field_name COMP_OP value
                          | FILTER_OP field_name IN_OP value
                          | FILTER_OP field_name NAME value
                          | LIMIT_OP field_name BY_CLAUSE CMD_TOP NUMBER NAME LPAREN field_name RPAREN
                          | LIMIT_OP field_name BY_CLAUSE BOTTOM_OP NUMBER NAME LPAREN field_name RPAREN
                          | ROWSUMMARY_OP NAME
                          | COLSUMMARY_OP NAME
                          | SHOWOTHER_OP NAME
                          | CMD_SORT NUMBER sort_clause
                          | CMD_SORT sort_clause
                          | CMD_SORT NUMBER sort_clause NAME
                          | CMD_SORT sort_clause NAME '''
    p[0] = {"type":"pivot_element_term","input":[],"output":[],"content":[],"args":{}}
    op=p[1]
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "field_name":
                p[0]["input"].append(pp["field"])
            elif pp["type"] == "sort_clause":
                p[0]["input"] += pp["input"]

# PREDICT
def p_command_predict(p):
    '''command : CMD_PREDICT predict_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend","content":[]}
    args={}
    p[0]["input"] += p[2]["input"]
    p[0]["output"] += p[2]["output"]
    extendDict(args,p[2]["args"])
    todel={}
    for arg in args:
        if re.match("^(upper|lower)\d{2}$",arg):    #looking to replace fields like upper95 by upperXX
            arg_name=arg[:len(arg)-2]+"XX"
            todel[arg]=arg_name
            p[0]["output"].append(args[arg])
        if arg in ["correlate","suppress"]:
            p[0]["input"].append(args[arg])
    # Renaming the fields in the dictionary
    for td in todel:
        args[todel[td]]=args[td]
        del args[td]
    checkArgs(p,args)

def p_command_predict_list(p):
    '''predict_list : predict_list field_name args_list
                    | predict_list rfield_term args_list
                    | predict_list fields_list
                    | predict_list rfields_list
                    | fields_list args_list
                    | rfields_list args_list
                    | fields_list
                    | rfields_list'''
    p[0] = {"type":"predict_list","input":[],"output":[],"fields-effect":"extend","content":[],"args":{}}
    for pp in p[1:]:
        if pp["type"] == "args_list":
            extendDict(p[0]["args"],pp["args"])
        elif pp["type"] == "field_name":
            p[0]["input"].append(pp["field"])
        elif pp["type"]  in ["rfield_term","fields_list","rfields_list"]:
            p[0]["input"] += pp["input"]
            p[0]["output"] += pp["output"]
        elif pp["type"] == "predict_list":
            p[0]["input"] += pp["input"]
            p[0]["output"] += pp["output"]
            extendDict(p[0]["args"],pp["args"])

# RANGEMAP
def p_command_rangemap(p):
    '''command : CMD_RANGEMAP args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    for arg in p[2]["args"]:
        if not arg in cmd_conf[p[1]]["args"]:
            p[0]["input"].append(arg)
        elif arg == "field":
            p[0]["input"].append(p[2]["args"][arg])
        p[0]["content"].append(p[2]["args"][arg])

# RARE
def p_command_rare(p):
    '''command : CMD_RARE args_list fields_list BY_CLAUSE fields_list args_list
               | CMD_RARE args_list fields_list BY_CLAUSE fields_list
               | CMD_RARE fields_list BY_CLAUSE fields_list args_list
               | CMD_RARE fields_list BY_CLAUSE fields_list
               | CMD_RARE args_list fields_list args_list
               | CMD_RARE args_list fields_list
               | CMD_RARE fields_list args_list
               | CMD_RARE fields_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
    checkArgs(p,args)

# REDISTRIBUTE
def p_command_redistribute(p):
    '''command : CMD_REDISTRIBUTE args_term BY_CLAUSE fields_list
               | CMD_REDISTRIBUTE BY_CLAUSE fields_list args_term
               | CMD_REDISTRIBUTE BY_CLAUSE fields_list
               | CMD_REDISTRIBUTE args_term
               | CMD_REDISTRIBUTE'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    if len(p) > 2:
        for pp in p[2:]:
            if isinstance(pp,dict):
                if pp["type"] == "args_term":
                    checkArgs(p,pp["args"])
                elif pp["type"] == "fields_list":
                    p[0]["input"] += pp["input"]

# REGEX
def p_command_regex(p):
    '''command : CMD_REGEX field_name EQ STRING
               | CMD_REGEX field_name NEQ STRING
               | CMD_REGEX STRING'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[p[len(p)-1]]}
    if isinstance(p[2],dict):
        p[0]["input"].append(p[2]["field"])

# REPLACE
def p_command_replace(p):
    '''command : CMD_REPLACE replace_list IN_OP fields_list
               | CMD_REPLACE replace_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none","content":[]}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
            elif pp["type"] == "replace_list":
                p[0]["content"] += pp["content"]

def p_command_replace_term(p):
    '''replace_list : replace_list value WITH_OP value
                    | replace_list COMMA value WITH_OP value
                    | value WITH_OP value'''
    p[0] = {"type":"replace_list","input":[],"output":[],"content":[]}
    for pp in p[1:]:
        if isinstance(pp,dict):
            if pp["type"] == "value":
                p[0]["content"].append(pp["value"])
            elif pp["type"] == "replace_list":
                p[0]["content"] += pp["content"]

# REST
def p_command_rest(p):
    '''command : CMD_REST args_list NAME args_list
               | CMD_REST args_list NAME
               | CMD_REST NAME args_list
               | CMD_REST NAME'''
    p[0] = {"type":"replace_list","input":[],"output":[],"fields-effect":"generate","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
        else:
            p[0]["content"].append(pp)
    for arg in args:
        if not arg in cmd_conf[p[1]]["args"]:
            p[0]["input"].append(args[arg])

# RETURN
def p_command_return(p):
    '''command : CMD_RETURN NUMBER args_list fields_list args_list
               | CMD_RETURN NUMBER args_list fields_list
               | CMD_RETURN NUMBER fields_list args_list
               | CMD_RETURN NUMBER fields_list
               | CMD_RETURN NUMBER args_list
               | CMD_RETURN args_list fields_list args_list
               | CMD_RETURN args_list fields_list
               | CMD_RETURN fields_list args_list
               | CMD_RETURN fields_list
               | CMD_RETURN args_list
               | CMD_RETURN'''
    p[0] = {"type":"replace_list","input":[],"output":["search"],"fields-effect":"generate","content":[]}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                p[0]["input"] += list(pp["args"].keys())
            elif pp["type"] == "fields_list":
                for f in pp["input"]:
                    if f[0] == "$":
                        p[0]["input"].append(f[1:]) #reformating $field
                    else:
                        p[0]["input"].append(f)

# REX
def p_command_rex(p):
    '''command : CMD_REX args_list STRING args_list
               | CMD_REX args_list STRING
               | CMD_REX STRING args_list
               | CMD_REX STRING'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
        else:
            reg=re.compile("\?<([^>]+)>")   # Extracting named groups
            newfields=reg.findall(pp)
            if len(newfields) > 0:
                p[0]["output"] += newfields
    checkArgs(p,args)

# SAVESEARCH
def p_command_savedsearch(p):
    '''command : CMD_SAVEDSEARCH args_list field_name args_list
               | CMD_SAVEDSEARCH args_list field_name
               | CMD_SAVEDSEARCH field_name args_list
               | CMD_SAVEDSEARCH field_name'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"generate","content":[]}
    args={}
    for pp in p[2:]:
        if pp["type"] == "args_list":
            extendDict(args,pp["args"])
        elif pp["type"] == "field_name":
            p[0]["content"].append(pp["field"])
    for arg in args:
        if not arg in cmd_conf[p[1]]["args"]:
            p[0]["content"].append(args[arg])

# SEARCHTXN
def p_command_searchtxn(p):
    '''command : CMD_SEARCHTXN field_name filters'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"generate","content":[]}
    for pp in p[2:]:
        if pp["type"] == "field_name":
            p[0]["content"].append(pp["field"])
        elif pp["type"] == "filters":
            for inp in pp["input"]:
                if not inp in cmd_conf[p[1]]["args"]:
                    p[0]["input"].append(inp)

# STREAMSTATS
def p_command_streamstats(p):
    '''command : CMD_STREAMSTATS streamstats_args agg_terms_list streamstats_args BY_CLAUSE fields_list streamstats_args
               | CMD_STREAMSTATS agg_terms_list streamstats_args BY_CLAUSE fields_list streamstats_args
               | CMD_STREAMSTATS streamstats_args agg_terms_list BY_CLAUSE fields_list streamstats_args
               | CMD_STREAMSTATS streamstats_args agg_terms_list streamstats_args BY_CLAUSE fields_list
               | CMD_STREAMSTATS streamstats_args agg_terms_list BY_CLAUSE fields_list
               | CMD_STREAMSTATS agg_terms_list BY_CLAUSE fields_list streamstats_args
               | CMD_STREAMSTATS agg_terms_list BY_CLAUSE fields_list
               | CMD_STREAMSTATS agg_terms_list streamstats_args BY_CLAUSE fields_list
               | CMD_STREAMSTATS streamstats_args agg_terms_list streamstats_args
               | CMD_STREAMSTATS agg_terms_list streamstats_args
               | CMD_STREAMSTATS streamstats_args agg_terms_list
               | CMD_STREAMSTATS agg_terms_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"extend"}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "streamstats_args":
                extendDict(args,pp["args"])
            elif pp["type"] == "agg_terms_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
            elif pp["type"] == "fields_list":
                p[0]["input"] += pp["input"]
    checkArgs(p,args)

def p_command_streamstats_args(p):
    '''streamstats_args : streamstats_args COMMA streamstats_args_term
                        | streamstats_args streamstats_args_term
                        | streamstats_args_term'''
    p[0] = {"type":"streamstats_args","args":p[1]["args"]}
    if len(p) > 2:
        extendDict(p[0]["args"],p[len(p)-1]["args"])

def p_command_streamstats_args_term(p):
    '''streamstats_args_term : args_term
                             | NAME EQ QLPAREN expression QRPAREN'''
    p[0] = {"type":"streamstats_args_term","args":{}}
    if isinstance(p[1],dict):
        p[0]["args"] = p[1]["args"]
    else:
        p[0]["args"][p[1]] = "\"(\"{}\")\"".format(p[4]["content"])

# TIMECHART
def p_command_timechart_agg(p):
    '''command : CMD_TIMECHART args_list agg_or_eval_list BY_CLAUSE field_name args_list CMD_WHERE chart_where_clause args_list
               | CMD_TIMECHART args_list agg_or_eval_list BY_CLAUSE field_name args_list CMD_WHERE chart_where_clause
               | CMD_TIMECHART args_list agg_or_eval_list BY_CLAUSE field_name args_list
               | CMD_TIMECHART args_list agg_or_eval_list BY_CLAUSE field_name
               | CMD_TIMECHART agg_or_eval_list BY_CLAUSE field_name args_list CMD_WHERE chart_where_clause args_list
               | CMD_TIMECHART agg_or_eval_list BY_CLAUSE field_name args_list CMD_WHERE chart_where_clause
               | CMD_TIMECHART agg_or_eval_list BY_CLAUSE field_name args_list
               | CMD_TIMECHART agg_or_eval_list BY_CLAUSE field_name
               | CMD_TIMECHART args_list agg_terms_list args_list
               | CMD_TIMECHART args_list agg_terms_list
               | CMD_TIMECHART agg_terms_list args_list
               | CMD_TIMECHART agg_terms_list'''
    p[0] = {"type":"command","input":[],"output":["_time"],"fields-effect":"replace","content":[]}
    args={}
    for pp in p[2:]:
        if isinstance(pp,dict):
            if pp["type"] == "args_list":
                extendDict(args,pp["args"])
            elif pp["type"] == "agg_or_eval_list":
                p[0]["input"] += pp["input"]
                p[0]["output"] += pp["output"]
                p[0]["content"] += pp["content"]
            elif pp["type"] == "field_name":
                p[0]["input"].append(pp["field"])
                p[0]["output"].append(pp["field"])
    checkArgs(p,args)



#--------------------
# Generic args positioning
#--------------------

def p_command_params_by_and_fields_or_args(p):
    '''command_params_by_and_fields_or_args : command_params_fields_or_args BY_CLAUSE fields_list args_list
                          | command_params_fields_or_args BY_CLAUSE fields_list
                          | BY_CLAUSE fields_list args_list
                          | BY_CLAUSE fields_list
                          | command_params_fields_or_args'''
    data = {"args":{},"fields":[],"by":[]}
    for pp in p[1:]:
        if isinstance(pp,dict):
            if pp["type"] == "command_params_fields_or_args":
                data["fields"] += pp["fields"]
            elif pp["type"] == "args_list":
                extendDict(data["args"],pp["args"])
            elif pp["type"] == "fields_list":
                data["by"] += pp["input"]
    p[0] = data

def p_command_params_fields_or_args(p):
    '''command_params_fields_or_args : args_list fields_list args_list
                               | args_list fields_list
                               | fields_list args_list
                               | args_list
                               | fields_list'''
    data = {"type":"command_params_fields_or_args","args":{},"fields":[]}
    for pp in p[1:]:
        if pp["type"] == "args_list":
            extendDict(data["args"],pp["args"])
        elif pp["type"] == "fields_list":
            data["fields"] += pp["input"]
    p[0] = data

#---------------------------
# Custom command function
#---------------------------
def checkArgs(p,args):
    global cmd_conf
    for arg in args:
        if not arg in cmd_conf[p[1]]["args"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)

def extractData(p):
    data={}
    for i in range(1,len(p)):
        d=p[i]
        if "type" in d:
            if not d["type"] in data:
                data[d["type"]]=[]
            data[d["type"]].append(d)
    return data

def extendDict(a,b):
    for k in b:
        if not k in a:
            a[k]=b[k]
        else:
            if isinstance(a[k],list):
                a[k].append(b[k])
            else:
                a[k]=[a[k],b[k]]

def filterFields(flist,pattern):
    return fnmatch.filter(flist,pattern)

#---------------------------
# AGGREGATION fields
#---------------------------
def p_agg_terms_list(p):
    '''agg_terms_list : agg_terms_list COMMA agg_term
                      | agg_terms_list agg_term
                      | agg_term'''
    if len(p) == 4:
        p[0] = {"type":"agg_terms_list","input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["output"]}
    elif len(p) == 3:
        p[0] = {"type":"agg_terms_list","input":p[1]["input"]+p[2]["input"],"output":p[1]["output"]+p[2]["output"]}
    else:
        p[0] = p[1]

def p_agg_term(p):
    '''agg_term : NAME LPAREN agg_term_arg RPAREN AS_CLAUSE field_name
                | NAME LPAREN agg_term_arg RPAREN AS_CLAUSE TIMES
                | NAME LPAREN agg_term_arg RPAREN
                | NAME AS_CLAUSE field_name
                | NAME AS_CLAUSE TIMES
                | NAME'''
    if len(p) == 7:
        if isinstance(p[6],dict):
            p[0] = {"type":"agg_term","input":p[3]["input"],"output":[p[6]["field"]]}
        else:
            p[0] = {"type":"agg_term","input":p[3]["input"],"output":[p[6]]}
    elif len(p) == 5:
        p[0] = {"type":"agg_term","input":p[3]["input"],"output":["{}({})".format(p[1],p[3]["input"][0])]}
    elif len(p) == 4:
        if isinstance(p[3],dict):
            p[0] = {"type":"agg_term","input":[p[1]],"output":[p[3]["field"]]}
        else:
            p[0] = {"type":"agg_term","input":[p[1]],"output":[p[3]]}
    else:
        p[0] = {"type":"agg_term","input":[p[1]],"output":[p[1]]}

def p_agg_term_arg(p):
    '''agg_term_arg : eval_expr_fun_value
                    | field_name
                    | TIMES'''
    p[0] = {"type":"agg_term_arg","input":[""],"output":[]}
    if "type" in p[1]:
        if p[1]["type"] == "eval_expr_fun_value":
            p[0]["content"] = p[1]["content"]
        elif p[1]["type"] == "field_name":
            p[0]["input"] = [p[1]["field"]]

def p_agg_or_eval_list(p):
    '''agg_or_eval_list : agg_terms_list
                        | eval_expr_fun'''
    p[0] = {"type":"agg_or_eval_list","input":p[1]["input"],"output":p[1]["output"],"content":[]}
    if p[1]["type"] == "eval_expr_fun":
        p[0]["content"].append(p[1]["content"])

def p_agg_or_eval(p):
    '''agg_or_eval : agg_term
                   | eval_expr_fun'''
    p[0] = {"type":"agg_or_eval","input":p[1]["input"],"output":p[1]["output"],"content":[]}
    if p[1]["type"] == "eval_expr_fun":
        p[0]["content"].append(p[1]["content"])

#---------------------------
# FIELDS
#---------------------------
def p_anyfields_list(p):
    '''any_fields_list : any_fields_list COMMA rfield_term
                       | any_fields_list rfield_term
                       | any_fields_list COMMA field_name
                       | any_fields_list field_name
                       | rfield_term
                       | field_name'''
    p[0] = {"type":"any_fields_list","input":[],"output":[]}
    if len(p) > 2:
        p[0] = {"type":"any_fields_list","input":p[1]["input"],"output":p[1]["output"]}
    if p[len(p)-1]["type"] == "rfield_term":
        p[0]["input"] += p[len(p)-1]["input"]
        p[0]["output"] += p[len(p)-1]["output"]
    else:
        p[0]["input"] += [p[len(p)-1]["field"]]

def p_rfields_list(p):
    '''rfields_list : rfields_list COMMA rfield_term
                    | rfields_list rfield_term
                    | rfield_term'''
    if len(p) == 4:
        p[0] = {"type":"rfields_list","input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["output"]}
    elif len(p) == 3:
        p[0] = {"type":"rfields_list","input":p[1]["input"]+p[2]["input"],"output":p[1]["output"]+p[2]["output"]}
    else:
        p[0] = p[1]

def p_fields_list(p):
    '''fields_list : fields_list COMMA field_name
                   | fields_list field_name
                   | field_name'''
    p[0] = {"type":"fields_list","input":[],"output":[]}
    if len(p) == 4:
        p[0]["input"] = p[1]["input"] + [p[3]["field"]]
    elif len(p) == 3:
        p[0]["input"] = p[1]["input"] + [p[2]["field"]]
    else:
        p[0]["input"] = [p[1]["field"]]

def p_rfield_term(p):
    '''rfield_term : field_name AS_CLAUSE field_name'''
    p[0] = {"type":"rfield_term","input":[p[1]["field"]],"output":[p[3]["field"]]}

def p_field_name(p):
    '''field_name : NAME
                  | PATTERN
                  | STRING
                  | commands_names
                  | op_names'''
    p[0] = {"type":"field_name","field":p[1]}

def p_field_name_agg_fun(p):
    '''field_name : NAME LPAREN field_name RPAREN
                  | commands_names LPAREN field_name RPAREN'''
    # Case when a field has been named after the use of an agregation function
    p[0] = {"type":"field_name","field":["{}({})".format(p[1],p[3]["field"])]}

def p_field_name_subsearch(p):
    '''field_name : subsearch'''
    p[0] = p[1]
    p[0]["field"]=""

def p_field_or_num_list(p):
    '''field_or_num_list : field_or_num_list field_or_num
                         | field_or_num'''
    p[0] = {"type":"field_or_num_list","values":[p[len(p)-1]["value"]],"input":[p[len(p)-1]["field"]],"output":[]}
    if len(p) > 2:
        p[0]["values"] = p[1]["values"] + p[0]["values"]
        p[0]["input"] = p[1]["input"] + p[0]["input"]

def p_field_or_num(p):
    '''field_or_num : field_name
                    | NUMBER
                    | MINUS NUMBER'''
    p[0] = {"type":"field_or_num","value":"","field":""}
    if isinstance(p[1],dict):
        p[0]["value"] = p[1]["field"]
        p[0]["field"] = p[1]["field"]
    else:
        if len(p) > 2:
            p[0]["value"] = "-{}".format(p[1])
        else:
            p[0]["value"] = p[1]

#---------------------------
# Args
#---------------------------
def p_args_list(p):
    '''args_list : args_list args_term
                 | args_term'''
    p[0] = {"type":"args_list","args":{}}
    p[0]["args"] = p[1]["args"].copy()
    if len(p) == 3:
        extendDict(p[0]["args"],p[2]["args"])

def p_args_term(p):
    '''args_term : NAME EQ args_value
                 | commands_names EQ args_value
                 | op_names EQ args_value'''
    # Command names have to be allowed as argument names for cases
    # like append which can be both a command or an argument
    p[0] = {"type":"args_term","args":{}}
    p[0]["args"][p[1].lower()]=p[3]["value"]

def p_args_value(p):
    '''args_value : value
                  | eval_expr_fun_value
                  | expr_fun_call
                  | TIMES
                  | chart_limit
                  | op_names
                  | commands_names'''
    p[0] = {"type":"args_value","value":""}
    if "type" in p[1]:
        if p[1]["type"] == "eval_expr_fun_value":
            p[0]["value"] = p[1]["content"]
        elif p[1]["type"] == "value":
            p[0]["value"] = p[1]["value"]
        elif "content" in p[1]:
            p[0]["value"] = p[1]["content"]
    else:
        p[0]["value"] = p[1]

def p_command_basic_args_list(p):
    '''basic_args_list : basic_args_list basic_args_term
                       | basic_args_term'''
    p[0] = {"type":"pivot_args_list","input":[],"output":[],"content":[],"args":p[1]["args"]}
    if len(p) > 2:
        extendDict(p[0]["args"],p[2]["args"])

def p_command_pbasic_args_term(p):
    '''basic_args_term : NAME EQ args_value'''
    p[0] = {"type":"basic_args_term","input":[],"output":[],"content":[],"args":{}}
    p[0]["args"][p[1].lower()]=p[3]["value"]

def p_command_chart_limit(p):
    '''chart_limit : BOTTOM_OP NUMBER
                   | CMD_TOP NUMBER'''
    p[0] = {"type":"chart_limit","content":["{} {}".format(p[1],p[2])]}

#---------------------------
# Values
#---------------------------
def p_value_number(p):
    """value : NUMBER
             | FLOAT
             | MINUS NUMBER %prec UMINUS
             | MINUS FLOAT %prec UMINUS"""
    p[0] = {"type":"value","value":""}
    if len(p) == 3:
        p[0]["value"] = "-"+str(p[2])
    else:
        p[0]["value"] = str(p[1])

def p_value_string(p):
    """value : QUOTE NAME QUOTE
             | STRING
             | NAME
             | PATTERN
             | QUOTE QUOTE
             | op_names"""
    p[0] = {"type":"value","value":""}
    if len(p) == 4:
        p[0]["value"] = p[2]
    elif len(p) == 3:
        p[0]["value"] = ""
    else:
        p[0]["value"] = str(p[1])

def p_value_time(p):
    'value : TIMESPECIFIER'
    p[0] = {"type":"value","value":str(p[1])}

def p_value_date(p):
    'value : DATE'
    p[0] = {"type":"value","value":str(p[1])}

def p_value_minus(p):
    'value : MINUS NAME'
    p[0] = {"type":"value","value":"-{}".format(str(p[2]))}

def p_values_list(p):
    '''values_list : values_list COMMA value
                   | value'''
    p[0] = {"type":"values_list","values":[]}
    if len(p) == 4:
        p[0]["values"] = p[1]["values"] + [p[3]["value"]]
    else:
        p[0]["values"].append(p[1]["value"])

def p_value_subsearch(p):
    'value : subsearch'
    p[0] = {"type":"value","value":"[...]"}

'''
def p_empty(p):
        'empty :'
        pass
'''

#---------------------------
# Built-in mandatory functions
#---------------------------

def p_error(p):
    if p:
        report_error(max(0,p.lexpos-10),p.lexpos+len(str(p.value)),"Unexpected symbol",p)
    else:
        report_error(-20,-1,"Unexpected end of query",None)



#---------------------------
#       CUSTOM FUNCTIONS
#---------------------------
#Custom global vars
scope_level=0
errors={"list":[],"ref":{}}
params={"verbose":True,"print_errs":True}
data = {"main":{},"subsearches":[]}
lexer = None
parser = None

def init_analyser():
    global errors, scope_level, data, logger, parser, lex
    errors={"list":[],"ref":{}}
    scope_level=0
    data = {"main":{},"subsearches":[]}
    if params["verbose"]:
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    elif params["print_errs"]:
        logger.setLevel(logging.ERROR)
        ch.setLevel(logging.ERROR)
    else:
        logger.setLevel(logging.CRITICAL)
        ch.setLevel(logging.CRITICAL)
    #Initializing parser only once
    if parser is None:
        logger.info("Lexer initializing")
        lexer = lex.lex(errorlog=logger)
        logger.info("Yacc initializing")
        parser = yacc.yacc(debug=True,errorlog=logger)
    logger.info("Parser initialization finished")

def error_build_token_id(tk):
    return "{}_{}".format(str(tk.lexpos),str(tk.value))

def error_build_message_id(st,ed,value):
    return "{}_{}_{}".format(str(st),str(ed),str(value))

def report_error(st,ed,msg,tk,value=None):
    global errors
    if tk is None:
        tkid=error_build_message_id(st,ed,value)
        if not tkid in errors["ref"]:
            errors["ref"][tkid] = [{"start_pos":st,"end_pos":ed,"message":msg,"token":tk}]
            errors["list"].append(tkid)
        else:
            errors["ref"][tkid].append({"start_pos":st,"end_pos":ed,"message":msg,"token":tk})
    else:
        tkid=error_build_token_id(tk)
        if not tkid in errors["ref"]:
            errors["ref"][tkid] = [{"start_pos":st,"end_pos":ed,"message":msg,"token":tk}]
            errors["list"].append(tkid)
        else:
            errors["ref"][tkid].append({"start_pos":st,"end_pos":ed,"message":msg,"token":tk})

def print_errors(s):
    global errors
    for eid in errors["list"]:
        e=errors["ref"][eid][-1]
        st,ed,msg,tk=e["start_pos"],e["end_pos"],e["message"],e["token"]
        if st < 0:
            st,ed = max(0,len(s) + st), max(0,len(s) + ed)
        if tk is None:
            err_str=s[st:ed]
            logger.error("[{}->{}] {}\n\t{}".format(st,ed,msg,err_str))
        else:
            err_str=s[st:min(ed+10,len(s))]
            logger.error("[{}->{}] {} : for value '{}' of type {}\n\t{}".format(st,ed,msg,tk.value,tk.type,err_str))


#---------------------------
#       EXECUTION
#---------------------------

def analyze(s,verbose=False,print_errs=True,macro_files=[]):
    global errors, params, data, logger
    try:
        params["verbose"]=verbose
        params["print_errs"]=print_errs
        init_analyser()
        if len(macro_files) > 0:
            res = macros.handleMacros(s,macro_files)
            if res["unique_macros_found"] > 0:
                logger.info("{} unique macros found and {} were expanded".format(res["unique_macros_found"],res["unique_macros_expanded"]))
            if res["unique_macros_found"] > res["unique_macros_expanded"]:
                logger.warning("{} macros could not be expanded".format(res["unique_macros_found"]-res["unique_macros_expanded"]))
            s = res["text"]
        r = yacc.parse(s,tracking=True,debug=False)
        if print_errs:
            print_errors(s)
        logger.info("[RES] finished")
        data["main"]=r
        return {"data":data,"errors":errors,"errors_count":len(errors["ref"])}
    except SyntaxError:
        pass