
import sys, os, re, json, logging
from lib.ply import lex
from lib.ply import yacc

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
    with open('spl_commands.json') as f:
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
    'sortby' : 'SORTBY_CLAUSE',
    'or' : 'OR_OP',
    'and' : 'AND_OP',
    'not'  :'NOT_OP',
    'output': 'OUTPUT_OP',
    'outputnew': 'OUTPUT_NEW_OP',
    'in':'IN_OP',
    'notin':'NOTIN_OP',
    'case':'CASE_OP',
    'term':'TERM_OP',
    'over':'OVER_OP',
    'bottom':'BOTTOM_OP'
}

tokens = [
    'EQ','NEQ','PLUS', 'MINUS', 'TIMES', 'DIVIDE', 'LPAREN','RPAREN','LBRACK','RBRACK','COMMA',
    'NUMBER', 'FLOAT', 'QUOTE', 'COMP_OP', 'PIPE', 
    'MACRO',
    'NAME','STRING','PATTERN','TIMESPECIFIER','DATE'
] + list(set(reserved.values())) + list(set([cmd_conf[cmd]["token_name"] for cmd in cmd_conf]))

literals = []

# Tokens

t_EQ = r'\='
t_NEQ = r'!\='
t_PLUS    = r'\+'
t_MINUS   = r'-'
t_TIMES   = r'\*'
t_DIVIDE  = r'/'
t_LPAREN  = r'\('
t_RPAREN  = r'\)'
t_LBRACK  = r'\['
t_RBRACK  = r'\]'
t_PIPE = r'\|'
t_COMMA = r'\,'
t_QUOTE = r'"'
t_COMP_OP = r'(<=|>=|<|>)'

t_ignore = " \r\n\t"

def t_MACRO(t):
    r'`[^`]+`'
    #Perhaps in the future check macros existence/content
    pass

def t_newline(t):
    r'\n+'
    t.lexer.lineno += t.value.count("\n")

def t_TIMESPECIFIER(t):
    r'[0-9a-zA-Z\+\-]*@[0-9a-zA-Z\+\-]+'
    return t

def t_DATE(t):
    r'\d+/\d+/\d+:\d+:\d+:\d+'
    return t

#Strings
def t_PATTERN(t):
    r'(\*[^\*\s]+\*|\*[a-zA-Z0-9_\.\{\}\-]+|[a-zA-Z0-9_\.\{\}\-]+\*)'
    return t

def t_STRING(t):
    r'"[^"]+"'
    t.value=t.value.strip('"')
    return t

def t_NAME(t):
    r'[a-zA-Z0-9_\{\}][a-zA-Z0-9_\.\{\}\-]*'
    global cmd_conf
    if t.value.lower() in cmd_conf:
        t.type = cmd_conf[t.value.lower()]["token_name"]    # Check for command names, lowercase
    else:
        t.type = reserved.get(t.value.lower(),"NAME")       # Check for reserved words, lowercase
    if t.value.isdigit():
        t.type = "NUMBER"
    if re.match(r'^\d+\.\d+$', t.value):
        t.type = "FLOAT"
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

lexer = None

#---------------------------
#       YACC
#---------------------------

# Parsing rules

precedence = (
    ('left', 'PLUS', 'MINUS'),
    ('left', 'TIMES', 'DIVIDE'),
    ('right','OR_OP'),
    ('right','AND_OP'),
    ('right', 'UMINUS','NOT_OP')
)

#---------------------------
# Searches
#---------------------------
def p_mainsearch(p):
    '''mainsearch : search_exp'''
    p[0] = p[1]

def p_search_exp(p):
    '''search_exp : filters_invok
              | filters_invok PIPE commands
              | PIPE commands'''
    global scope_level, params, data
    flt,cmd=None,None
    fields = {"input":[],"output":[],"fields-effect":[]}
    if len(p) == 4:
        flt=p[1]
        cmd=p[3]
        fields["fields-effect"]=p[3]["fields-effect"]
    elif len(p) == 3:
        cmd=p[2]
        fields["fields-effect"]=p[2]["fields-effect"]
    elif len(p) == 2:
        flt=p[1]
    if not flt is None:
        for f in flt:
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
    '''subsearch : LBRACK new_scope search_exp RBRACK'''
    global scope_level
    p[0] = p[3]
    scope_level = scope_level -1

def p_new_scope(p):
    'new_scope :'
    global scope_level
    scope_level = scope_level +1

def p_subpipeline(p):
    'subpipeline : LBRACK commands RBRACK'
    p[0] = p[2]

#---------------------------
# FILTERS
#---------------------------
def p_filters_invok(p):
    '''filters_invok : CMD_SEARCH filters
                     | filters'''
    global scope_level
    if len(p) == 3:
        p[0] = p[2]
        if scope_level == 0:
            #Unecessary CMD_SEARCH in mainsearch context
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected SEARCH in the beginning of the main search",None)
    else:
        p[0] = p[1]
        if scope_level > 0:
            #Missing CMD_SEARCH in subsearch context
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Missing SEARCH in the beginning of the subsearch",None)

def p_filters(p):
    '''filters : filter filters
               | filter'''
    if len(p) == 3:
        p[0] = p[1] + p[2]
    else:
        p[0] = p[1]

# Logical conditions
def p_filters_logic(p):
    '''filters : filters_logic_exp'''
    p[0] = p[1]

def p_filters_logic_exp(p):
    '''filters_logic_exp : filters_logic_exp OR_OP filters_logic_term
                         | filters_logic_term'''
    if len(p) == 4:
        p[0] = p[1] + p[3]
    else:
        p[0] = p[1]

def p_filters_logic_term(p):
    '''filters_logic_term : filters_logic_term AND_OP filters_logic_factor
                          | filters_logic_term filters_logic_factor
                          | filters_logic_factor'''
    if len(p) == 4:
        p[0] = p[1] + p[3]
    elif len(p) == 3:
        p[0] = p[1] + p[2]
    else:
        p[0] = p[1]

def p_filters_logic_factor(p):
    '''filters_logic_factor : filter
                            | NOT_OP filters_logic_factor
                            | LPAREN filters_logic_exp RPAREN'''
    if len(p) > 2:
        p[0] = p[2]
    else:
        p[0] = p[1]
# ---

def p_filter_eq(p):
    'filter : NAME EQ value'
    p[0] = [p[1]]

def p_filter_neq(p):
    'filter : NAME NEQ value'
    p[0] = [p[1]]

def p_filters_sub(p):
    'filter : subsearch'
    p[0] = p[1]["output"]

def p_filter_comp_1(p):
    '''filter : NAME COMP_OP NUMBER
              | NAME COMP_OP FLOAT'''
    p[0] = [p[1]]

def p_filter_comp_(p):
    '''filter : NUMBER COMP_OP NAME
              | FLOAT COMP_OP NAME'''
    p[0] = [p[3]]

def p_filter_in(p):
    '''filter : NAME IN_OP LPAREN values_list RPAREN'''
    p[0] = [p[1]]

def p_filter_phrases(p):
    '''filter : CASE_OP LPAREN value RPAREN
              | TERM_OP LPAREN value RPAREN'''
    p[0] = []

def p_filter_any(p):
    'filter : NAME EQ TIMES'
    p[0] = [p[1]]

def p_filter_notany(p):
    'filter : NAME NEQ TIMES'
    p[0] = [p[1]]

def p_filter_raw(p):
    'filter : value'
    p[0] = [None]

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
    p[0] = []

def p_expression_logic_exp(p):
    '''expression_logic_exp : expression_logic_term OR_OP expression_logic_term
                            | expression_logic_term'''
    pass

def p_expression_logic_term(p):
    '''expression_logic_term : expression_logic_factor AND_OP expression_logic_term
                             | expression_logic_factor'''
    pass

def p_expression_logic_factor(p):
    '''expression_logic_factor : expression_value
                               | NOT_OP expression_logic_factor
                               | LPAREN expression_logic_exp RPAREN'''
    pass

def p_expression_value(p):
    '''expression_value : expr_fun LPAREN expression_fun_args RPAREN
                        | value'''
    pass

def p_expression_binop(p):
    '''expression_value : expression_value PLUS expression_value
                        | expression_value MINUS expression_value
                        | expression_value TIMES expression_value
                        | expression_value DIVIDE expression_value
                        | expression_value EQ expression_value
                        | expression_value COMP_OP expression_value
                        | LPAREN expression_value RPAREN'''
    pass

# ---

def p_expression_fun(p):
    'expr_fun : NAME'
    p[0] = p[1]

def p_expression_fun_args(p):
    '''expression_fun_args : expression COMMA expression_fun_args
                           | expression'''
    pass

#---------------------------
# Commands
#---------------------------
def p_commands(p):
    '''commands : commands PIPE command
                | command'''
    if len(p) == 4:
        p[0] = {"input":p[1]["input"]+p[3]["input"],"output":[],"fields-effect":p[1]["fields-effect"]+[p[3]["fields-effect"]]}
        if p[3]["fields-effect"] == "replace":
            p[0]["output"] = p[3]["output"]
        elif p[3]["fields-effect"] == "remove":
            p[0]["output"]=[]
            for f in p[1]["output"]:
                if not f in p[3]["output"]:
                    p[0]["output"].append(f)
        elif p[3]["fields-effect"] == "rename":
            p[0]["output"]=[]
            for f in p[1]["output"]:
                if not f in p[3]["input"]:
                    p[0]["output"].append(f)
            p[0]["output"] = p[0]["output"] + p[3]["output"]
        else:
            p[0]["output"] = p[1]["output"]+p[3]["output"]
    else:
        p[0]=p[1]
        p[0]["fields-effect"]=[p[0]["fields-effect"]]

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
                      | CMD_DEDUP
                      | CMD_EVAL
                      | CMD_EXPAND
                      | CMD_FIELDS
                      | CMD_FILLNULL
                      | CMD_FLATTEN
                      | CMD_INPUTLOOKUP
                      | CMD_LOOKUP
                      | CMD_OUTPUTLOOKUP
                      | CMD_RENAME
                      | CMD_REVERSE
                      | CMD_SEARCH
                      | CMD_SORT
                      | CMD_STATS
                      | CMD_TABLE
                      | CMD_TOP
                      | CMD_TRANSACTION
                      | CMD_WHERE 
                      '''
    p[0] = p[1]

# SEARCH COMMAND
def p_command_search(p):
    'command : CMD_SEARCH filters'
    p[0] = {"input":p[2],"output":[],"fields-effect":"none"}

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
        byclause = p[5]
    elif len(p) == 5:
        byclause = p[4]
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
    p[0] = {"input":[],"output":p[2],"fields-effect":"extend"}
    logger.info("Parsed a EVAL: {}".format(p[0]))

def p_command_eval_exprs(p):
    '''eval_exprs : eval_exprs COMMA eval_expr_assign
                  | eval_expr_assign'''
    if len(p) == 4:
        p[0] = [p[1]] + p[3]
    else:
        p[0] = [p[1]]

def p_command_eval_expr_assign(p):
    'eval_expr_assign : field_name EQ expression'
    p[0] = p[1]

def p_command_eval_expr_fun_value(p):
    '''eval_expr_fun_value : CMD_EVAL LPAREN expression RPAREN'''
    p[0] = p[3]

def p_command_eval_expr_fun(p):
    '''eval_expr_fun : eval_expr_fun_value AS_CLAUSE field_name
                     | eval_expr_fun_value'''
    if len(p) == 4:
        p[0] = {"type":"eval_expr_fun","input":p[1],"output":[p[3]]}
    else:
        p[0] = {"type":"eval_expr_fun","input":p[1],"output":[]}

# FIELDS COMMAND
def p_command_fields_keep(p):
    '''command : CMD_FIELDS PLUS fields_list
               | CMD_FIELDS fields_list'''
    if len(p) == 4:
        p[0] = {"type":"command","input":p[3],"output":p[3],"fields-effect":"replace"}
    else:
        p[0] = {"type":"command","input":p[2],"output":p[2],"fields-effect":"replace"}

def p_command_fields_remove(p):
    '''command : CMD_FIELDS MINUS fields_list'''
    p[0] = {"type":"command","input":p[3],"output":p[3],"fields-effect":"remove"}

# RENAME
def p_command_rename(p):
    'command : CMD_RENAME rfields_list'
    p[0] = p[2]
    p[0]["fields-effect"] = "rename"
    p[0]["type"] = "command"

# SORT
def p_command_sort(p):
    '''command : CMD_SORT NUMBER sort_clause
               | CMD_SORT sort_clause'''
    if len(p) == 4:
        p[0] = {"type":"command","input":p[3],"output":p[3],"fields-effect":"none"}
    else:
        p[0] = {"type":"command","input":p[2],"output":p[2],"fields-effect":"none"}

def p_command_sort_clause(p):
    '''sort_clause : sort_term COMMA sort_clause
                   | sort_term'''
    if len(p) == 3:
        p[0] = p[1] + p[2]
    else:
        p[0] = p[1]

def p_command_sort_term(p):
    '''sort_term : PLUS field_name
                 | MINUS field_name
                 | field_name'''
    if len(p) == 3:
        p[0] = [p[2]]
    else:
        p[0] = [p[1]]

# DEDUP
def p_command_dedup_args(p):
    '''command : CMD_DEDUP NUMBER fields_list args_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP fields_list args_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP NUMBER fields_list args_list
               | CMD_DEDUP fields_list args_list'''
    args=None
    if len(p) == 7:
        p[0] = {"type":"command","input":p[3]+p[6],"output":[],"fields-effect":"none"}
        args=p[4]["args"]
    elif len(p) == 6:
        p[0] = {"type":"command","input":p[2]+p[5],"output":[],"fields-effect":"none"}
        args=p[3]["args"]
    elif len(p) == 5:
        p[0] = {"type":"command","input":p[3],"output":[],"fields-effect":"none"}
        args=p[4]["args"]
    else:
        p[0] = {"type":"command","input":p[2],"output":[],"fields-effect":"none"}
        args=p[2]["args"]
    checkArgs(p,args)

def p_command_dedup_noargs(p):
    '''command : CMD_DEDUP NUMBER fields_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP fields_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP NUMBER fields_list
               | CMD_DEDUP fields_list'''
    if len(p) == 6:
        p[0] = {"type":"command","input":p[3]+p[5],"output":[],"fields-effect":"none"}
    elif len(p) == 5:
        p[0] = {"type":"command","input":p[2]+p[4],"output":[],"fields-effect":"none"}
    elif len(p) == 4:
        p[0] = {"type":"command","input":p[3],"output":[],"fields-effect":"none"}
    else:
        p[0] = {"type":"command","input":p[2],"output":[],"fields-effect":"none"}


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
               | CMD_TRANSACTION'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    p[0]=commands_args_and_fields_output_update(p,[])

# BASIC SINGLE FIELD COMMAND
def p_command_basic_single_field(p):
    '''command : CMD_EXPAND field_name
               | CMD_FLATTEN field_name'''
    p[0] = {"type":"command","input":[p[2]],"output":[],"fields-effect":"none"}

# BASIC SINGLE ARG COMMAND
def p_command_basic_single_arg(p):
    '''command : CMD_ANALYSEFIELDS args_term
               | CMD_APPENDPIPE args_term
               | CMD_CEFOUT args_term'''
    checkArgs(p,p[2])
    if p[1] in ["af","analyzefields"]:
        p[0] = {"type":"command","input":p[2].values(),"output":cmd_conf[p[1]]["created_fields"],"fields-effect":"replace"}
    else: 
        p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}

# BASIC ONLY ARGS COMMAND
def p_command_basic_only_args(p):
    '''command : CMD_ABSTRACT args_list
               | CMD_BUCKETDIR args_list'''
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    checkArgs(p,p[2]["args"])
    p[0]=commands_args_and_fields_output_update(p,p[2])

# BASIC ONLY FIELDS
def p_command_basic_only_fields(p):
    '''command : CMD_TABLE fields_list'''
    p[0] = {"type":"command","input":p[2],"output":[],"fields-effect":"none"}
    p[0]=commands_args_and_fields_output_update(p,[])

# BASIC FIELDS AND ARGS
def p_command_basic_args_and_fields(p):
    '''command : CMD_ADDCOLTOTALS command_params_fields_or_args
               | CMD_ADDTOTALS command_params_fields_or_args
               | CMD_FILLNULL command_params_fields_or_args
               | CMD_ANOMALOUSVALUE command_params_fields_or_args
               | CMD_ANOMALYDETECTION command_params_fields_or_args
               | CMD_ARULES command_params_fields_or_args
               | CMD_ASSOCIATE command_params_fields_or_args
               | CMD_TRANSACTION command_params_fields_or_args'''
    p[0] = {"type":"command","input":p[2]["fields"],"output":[],"fields-effect":"none"}
    checkArgs(p,p[2]["args"])
    p[0]=commands_args_and_fields_output_update(p,p[2]["args"])
    
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
    elif p[1] == "associate":
        out["output"] = cmd_conf[p[1]]["created_fields"]
        out["fields-effect"] = "replace"
    elif p[1] == "bucketdir":
        if "pathfield" in args:
            out["input"].append(args["pathfield"])
    elif p[1] == "table":
        p[0] = {"type":"command","input":p[2],"output":p[2],"fields-effect":"replace"}
    return out

# WHERE
def p_command_where(p):
    'command : CMD_WHERE expression'
    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}

# LOOKUP
def p_command_lookup(p):
    '''command : CMD_LOOKUP NAME any_fields_list OUTPUT_OP any_fields_list
               | CMD_LOOKUP NAME any_fields_list OUTPUT_NEW_OP any_fields_list
               | CMD_LOOKUP NAME any_fields_list
               | CMD_LOOKUP NAME'''
    if len(p) > 3:
        p[0] = {"type":"command","input":p[3],"output":[],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    if len(p) > 4:
        p[0]["output"] = p[5]

def p_command_lookup_args(p):
    '''command : CMD_LOOKUP args_list NAME any_fields_list OUTPUT_OP any_fields_list
               | CMD_LOOKUP args_list NAME any_fields_list OUTPUT_NEW_OP any_fields_list
               | CMD_LOOKUP args_list NAME any_fields_list
               | CMD_LOOKUP args_list NAME'''
    if len(p) > 4:
        p[0] = {"type":"command","input":p[3],"output":[],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    if len(p) > 4:
        p[0]["output"] = p[5]
    checkArgs(p,p[2]["args"])

# INPUTLOOKUP
def p_command_inputlookup(p):
    '''command : CMD_INPUTLOOKUP args_list NAME CMD_WHERE expression
               | CMD_INPUTLOOKUP NAME CMD_WHERE expression
               | CMD_INPUTLOOKUP args_list NAME
               | CMD_INPUTLOOKUP NAME'''

    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    if len(p) == 6 or len(p) == 4:
        checkArgs(p,p[2]["args"])

# OUTPUTLOOKUP
def p_command_outputlookup(p):
    '''command : CMD_OUTPUTLOOKUP args_list NAME
               | CMD_OUTPUTLOOKUP NAME'''

    p[0] = {"type":"command","input":[],"output":[],"fields-effect":"none"}
    if len(p) == 4:
        checkArgs(p,p[2]["args"])
# ACCUM
def p_command_accum(p):
    '''command : CMD_ACCUM field_name AS_CLAUSE field_name
               | CMD_ACCUM field_name'''
    if len(p) == 5:
        p[0] = {"type":"command","input":[p[2]],"output":[p[4]],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":[p[2]],"output":[],"fields-effect":"none"}

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
    if isinstance(p[2],dict):
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}
    else:
        p[0] = {"type":"command","input":[p[2]],"output":[],"fields-effect":"none"}

# BIN / BUCKET
def p_command_bin(p):
    '''command : CMD_BIN args_list rfield_term args_list
               | CMD_BIN args_list field_name args_list
               | CMD_BIN rfield_term args_list
               | CMD_BIN field_name args_list
               | CMD_BIN args_list rfield_term
               | CMD_BIN args_list field_name
               | CMD_BIN rfield_term
               | CMD_BIN field_name'''
    args={}
    data=extractData(p)
    if "args" in data:
        for obj in data["args"]:
            extendDict(args,data["args"][obj])
    checkArgs(p,args)
    if len(p) == 5 and isinstance(p[3],dict):
        p[0] = {"type":"command","input":p[3]["input"],"output":p[3]["output"],"fields-effect":"extend"}
    elif len(p) == 4 and isinstance(p[2],dict) and "input" in p[2]:
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}
    elif len(p) == 4 and isinstance(p[3],dict) and "input" in p[3]:
        p[0] = {"type":"command","input":p[3]["input"],"output":p[3]["output"],"fields-effect":"extend"}
    elif len(p) == 3 and isinstance(p[2],dict):
        p[0] = {"type":"command","input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}
    elif len(p) == 3:
        p[0] = {"type":"command","input":[p[2]],"output":[],"fields-effect":"none"}
    else:
        if isinstance(p[3],dict):
            p[0] = {"type":"command","input":[p[2]],"output":[],"fields-effect":"none"}
        else:
            p[0] = {"type":"command","input":[p[3]],"output":[],"fields-effect":"none"}

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
        else:
            p[0]["fields"].append(pp)


def p_command_chart_by_1(p):
    '''command_chart_by_1 : BY_CLAUSE field_name args_list chart_where_clause
                          | BY_CLAUSE field_name args_list
                          | BY_CLAUSE field_name chart_where_clause
                          | BY_CLAUSE field_name'''
    p[0] = {"type":"chart_by","fields":[p[2]],"args":{}}
    if len(p) > 3:
        if "type" in p[3] and p[3]["type"] == "args_list":
            p[0]["args"]=p[3]["args"]

def p_command_chart_over(p):
    '''command_chart_over : OVER_OP field_name args_list
                          | OVER_OP field_name'''
    p[0] = {"type":"chart_over","fields":[p[2]],"args":{}}
    if len(p) == 4:
        p[0]["args"]=p[3]["args"]


def p_command_chart_where_clause(p):
    '''chart_where_clause : agg_term IN_OP CMD_TOP NUMBER
                          | agg_term IN_OP BOTTOM_OP NUMBER
                          | agg_term NOTIN_OP CMD_TOP NUMBER
                          | agg_term NOTIN_OP BOTTOM_OP NUMBER
                          | agg_term COMP_OP NUMBER
                          | agg_term COMP_OP FLOAT'''
    p[0] = {"type":"chart_where_clause","fields":[p[1]],"options":[],"value":p[len(p)-1]}
    if len(p) > 4:
        p[0]["options"].append(p[2]).append(p[3]) 

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
    if len(p) == 5:
        data["by"]=p[3]
        data["fields"] = p[1]["fields"]
        for k in p[1]["args"]:
            data["args"][k]=p[1]["args"][k]
        for k in p[4]:
            data["args"][k]=p[4][k]
    elif len(p) == 4:
        if p[1] == "by":
            data["by"]=p[2]
            data["args"]=p[3]["args"]
        else:
            data["by"]=p[3]
            data["fields"] = p[1]["fields"]
            data["args"]=p[1]["args"]
    elif len(p) == 3:
        data["by"]=p[2]
    elif len(p) == 2:
        data["args"] = p[1]["args"]
        data["fields"] = p[1]["fields"]
    p[0] = data

def p_command_params_fields_or_args(p):
    '''command_params_fields_or_args : args_list fields_list args_list
                               | args_list fields_list
                               | fields_list args_list
                               | args_list
                               | fields_list'''
    data = {"args":{},"fields":[]}
    if len(p) == 4:
        data["fields"] = p[2]
        for k in p[1]["args"]:
            data["args"][k]=p[1]["args"][k]
        for k in p[3]["args"]:
            data["args"][k]=p[3]["args"][k]
    elif len(p) == 3:
        if isinstance(p[1],dict):
            data = {"args":p[1]["args"],"fields":p[2]}
        else:
            data = {"args":p[2]["args"],"fields":p[1]}
    else:
        if isinstance(p[1],dict):
            data = {"args":p[1]["args"],"fields":[]}
        else:
            data = {"args":{},"fields":p[1]}
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
        a[k]=b[k]

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
                | NAME LPAREN agg_term_arg RPAREN
                | NAME AS_CLAUSE field_name
                | NAME'''
    if len(p) == 7:
        p[0] = {"type":"agg_term","input":[p[3]],"output":[p[6]]}
    elif len(p) == 5:
        p[0] = {"type":"agg_term","input":[p[3]],"output":["{}({})".format(p[1],p[3])]}
    elif len(p) == 4:
        p[0] = {"type":"agg_term","input":[p[1]],"output":[p[3]]}
    else:
        p[0] = {"type":"agg_term","input":[],"output":[p[1]]}

def p_agg_term_arg(p):
    '''agg_term_arg : eval_expr_fun_value
                    | field_name'''
    p[0]=p[1]

def p_agg_or_eval_list(p):
    '''agg_or_eval_list : agg_terms_list
                        | eval_expr_fun'''
    p[0] = {"type":"agg_or_eval_list","input":p[1]["input"],"output":p[1]["output"]}

#---------------------------
# FIELDS
#---------------------------
def p_anyfields_list(p):
    '''any_fields_list : rfields_list
                       | fields_list'''
    p[0] = p[1]

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
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    elif len(p) == 3:
        p[0] = p[1] + [p[2]]
    else:
        p[0] = [p[1]]

def p_rfield_term(p):
    '''rfield_term : field_name AS_CLAUSE field_name'''
    p[0] = {"type":"rfield_term","input":[p[1]],"output":[p[3]]}

def p_field_name(p):
    '''field_name : NAME
                  | PATTERN'''
    p[0] = p[1]

def p_field_name_agg_fun(p):
    'field_name : NAME LPAREN field_name RPAREN'
    # Case when a field has been named after the use of an agregation function
    p[0]="{}({})".format(p[1],p[3])

#---------------------------
# Args
#---------------------------
def p_args_list(p):
    '''args_list : args_list args_term
                 | args_term'''
    p[0] = {"type":"args_list","args":{}}
    if len(p) == 3:
        p[0]["args"] = p[1]["args"].copy()
        for key in p[2]:
            p[0]["args"][key] = p[2][key]
    else:
        p[0]["args"] = p[1].copy()

def p_args_term(p):
    '''args_term : NAME EQ args_value
                 | commands_names EQ args_value'''
    # Command names have to be allowed as argument names for cases
    # like append which can be both a command or an argument
    p[0]={}
    p[0][p[1]]=p[3]

def p_args_value(p):
    '''args_value : value
                  | eval_expr_fun_value'''
    p[0] = p[1]

#---------------------------
# Values
#---------------------------
def p_value_number(p):
    """value : NUMBER
             | FLOAT
             | MINUS NUMBER %prec UMINUS
             | MINUS FLOAT %prec UMINUS"""
    if len(p) == 3:
        p[0]="-"+str(p[2])
    else:
        p[0]=str(p[1])

def p_value_string(p):
    """value : QUOTE NAME QUOTE
             | STRING
             | NAME
             | PATTERN
             | QUOTE QUOTE"""
    if len(p) == 4:
        p[0] = p[2]
    elif len(p) == 3:
        p[0]=""
    else:
        p[0]=str(p[1])

def p_value_time(p):
    'value : TIMESPECIFIER'
    p[0]=str(p[1])

def p_value_date(p):
    'value : DATE'
    p[0]=str(p[1])

def p_values_list(p):
    '''values_list : values_list COMMA value
                   | value'''
    if len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0]=[p[1]]

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
        report_error(-10,-1,"Syntax error in at AOF",None)

parser = None

#---------------------------
#       CUSTOM FUNCTIONS
#---------------------------
#Custom global vars
scope_level=0
errors={"list":[],"ref":{}}
params={"verbose":True,"print_errs":True}
data = {"main":{},"subsearches":[]}

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
    if lexer is None:
        logger.info("Lexer initializing")
        lex.lex(errorlog=logger)
    if parser is None:
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

def analyze(s,verbose=False,print_errs=True):
    global errors, params, data, logger
    try:
        params["verbose"]=verbose
        params["print_errs"]=print_errs
        init_analyser()
        r = yacc.parse(s,tracking=True,debug=False)
        if print_errs:
            print_errors(s)
        logger.info("[RES] finished")
        data["main"]=r
        return {"data":data,"errors":errors,"errors_count":len(errors["ref"])}
    except SyntaxError:
        pass