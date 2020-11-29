
import sys, os, re, json
from lib.ply import lex
from lib.ply import yacc

cmd_conf=None
with open('spl_commands.json') as f:
    cmd_conf = json.load(f)

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
    'in':'IN_OP'
}

tokens = [
    'EQ','PLUS', 'MINUS', 'TIMES', 'DIVIDE', 'LPAREN','RPAREN','LBRACK','RBRACK','COMMA',
    'NUMBER', 'FLOAT', 'QUOTE', 'COMP_OP', 'PIPE', 
    'MACRO',
    'NAME','STRING','PATTERN'
] + list(set(reserved.values())) + list(set([cmd_conf[cmd]["token_name"] for cmd in cmd_conf]))

literals = []

# Tokens

t_EQ = r'\='
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
t_COMP_OP = r'(<|>|<=|>=)'

t_ignore = " \r\n\t"

def t_MACRO(t):
    r'`[^`]+`'
    #Perhaps in the future check macros existence/content
    pass

def t_FLOAT(t):
    r'\d*\.\d+'
    t.value = float(t.value)
    return t

def t_NUMBER(t):
    r'\d+'
    t.value = int(t.value)
    return t

def t_newline(t):
    r'\n+'
    t.lexer.lineno += t.value.count("\n")

#Strings
def t_PATTERN(t):
    r'(\*[^\*\s]+\*|\*[a-zA-Z0-9_\.\{\}-]+|[a-zA-Z0-9_\.\{\}-]+\*)'
    return t

def t_STRING(t):
    r'"[^"]+"'
    t.value=t.value.strip('"')
    return t

def t_NAME(t):
    r'[a-zA-Z_\.][a-zA-Z0-9_\.\{\}-]*'
    global cmd_conf
    if t.value.lower() in cmd_conf:
        t.type = cmd_conf[t.value.lower()]["token_name"]    # Check for command names, lowercase
    else:
        t.type = reserved.get(t.value.lower(),"NAME")       # Check for reserved words, lowercase
    return t

def t_error(t):
    print("Illegal character '%s'" % t.value[0])
    t.lexer.skip(1)

# Build the lexer
lexer = lex.lex()

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
    fields = {"input":[],"output":[]}
    if len(p) == 4:
        flt=p[1]
        cmd=p[3]
    elif len(p) == 3:
        cmd=p[2]
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
    if params["verbose"]:
        print("SEARCH [{}]: {}".format(scope_level,fields))
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

def p_filters_sub(p):
    'filter : subsearch'
    p[0] = p[1]["output"]

def p_filter_comp_1(p):
    '''filter : NAME COMP_OP NUMBER'''
    p[0] = [p[1]]

def p_filter_comp_(p):
    '''filter : NUMBER COMP_OP NAME'''
    p[0] = [p[3]]

def p_filter_in(p):
    '''filter : NAME IN_OP LPAREN values_list RPAREN'''
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
    pass

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
        p[0] = {"input":p[1]["input"]+p[3]["input"],"output":[]}
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

# ERROR HANDLING
def p_commands_error(p):
    '''commands : commands PIPE error
                | commands PIPE commands_names error'''
    if len(p) == 5:
        report_error(p.lexpos(2),p[4].lexpos,"Syntax error in command {}".format(p[3]),p[4])
    else:
        report_error(p.lexpos(2),p[3].lexpos,"Unknown command name",p[3])
    p[0] = {"input":[],"output":[],"fields-effect":"none"}

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
                      | CMD_AUDIT
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
                      | CMD_WHERE 
                      '''
    p[0] = p[1]

# SEARCH COMMAND
def p_command_search(p):
    'command : CMD_SEARCH filters'
    p[0] = {"input":p[2],"output":[None],"fields-effect":"none"}

# STATS
def p_command_stats(p):
    '''command : CMD_STATS args_list agg_terms_list BY_CLAUSE fields_list
               | CMD_STATS agg_terms_list BY_CLAUSE fields_list
               | CMD_STATS args_list agg_terms_list
               | CMD_STATS agg_terms_list'''
    global params
    fields={"input":[],"output":[],"fields-effect":"replace"}
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
        for arg in p[2]:
            if not arg in cmd_conf[p[1]]["args"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(p[2],p[1],str(cmd_conf[p[1]]["args"])),None,value=p[2])
    if params["verbose"]:
        print("Parsed a STATS", fields)

# TABLE
def p_command_table(p):
    '''command : CMD_TABLE fields_list'''
    p[0] = {"input":p[2],"output":p[2],"fields-effect":"replace"}

# EVAL
def p_command_eval(p):
    'command : CMD_EVAL eval_exprs'
    global params
    p[0] = {"input":[],"output":p[2],"fields-effect":"extend"}
    if params["verbose"]:
        print("Parsed a EVAL", p[0])

def p_command_eval_exprs(p):
    '''eval_exprs : eval_expr_assign COMMA eval_exprs
                  | eval_expr_assign'''
    if len(p) == 4:
        p[0] = [p[1]] + p[3]
    else:
        p[0] = [p[1]]

def p_command_eval_expr_assign(p):
    'eval_expr_assign : field_name EQ expression'
    p[0] = p[1]

# FIELDS COMMAND
def p_command_fields_keep(p):
    '''command : CMD_FIELDS PLUS fields_list
               | CMD_FIELDS fields_list'''
    if len(p) == 4:
        p[0] = {"input":p[3],"output":p[3],"fields-effect":"replace"}
    else:
        p[0] = {"input":p[2],"output":p[2],"fields-effect":"replace"}

def p_command_fields_remove(p):
    '''command : CMD_FIELDS MINUS fields_list'''
    p[0] = {"input":p[3],"output":p[3],"fields-effect":"remove"}

# RENAME
def p_command_rename(p):
    'command : CMD_RENAME rfields_list'
    p[0] = p[2]
    p[0]["fields-effect"] = "rename"

# SORT
def p_command_sort(p):
    '''command : CMD_SORT NUMBER sort_clause
               | CMD_SORT sort_clause'''
    if len(p) == 4:
        p[0] = {"input":p[3],"output":p[3],"fields-effect":"none"}
    else:
        p[0] = {"input":p[2],"output":p[2],"fields-effect":"none"}

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
        p[0] = {"input":p[3]+p[6],"output":[],"fields-effect":"none"}
        args=p[4]
    elif len(p) == 6:
        p[0] = {"input":p[2]+p[5],"output":[],"fields-effect":"none"}
        args=p[3]
    elif len(p) == 5:
        p[0] = {"input":p[3],"output":[],"fields-effect":"none"}
        args=p[4]
    else:
        p[0] = {"input":p[2],"output":[],"fields-effect":"none"}
        args=p[2]
    for arg in args:
        if not arg in cmd_conf[p[1]]["args"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)


def p_command_dedup_noargs(p):
    '''command : CMD_DEDUP NUMBER fields_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP fields_list SORTBY_CLAUSE sort_clause
               | CMD_DEDUP NUMBER fields_list
               | CMD_DEDUP fields_list'''
    if len(p) == 6:
        p[0] = {"input":p[3]+p[5],"output":[],"fields-effect":"none"}
    elif len(p) == 5:
        p[0] = {"input":p[2]+p[4],"output":[],"fields-effect":"none"}
    elif len(p) == 4:
        p[0] = {"input":p[3],"output":[],"fields-effect":"none"}
    else:
        p[0] = {"input":p[2],"output":[],"fields-effect":"none"}


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
               | CMD_REVERSE'''
    p[0] = {"input":[],"output":[],"fields-effect":"none"}
    if p[1] == "anomalydetection":
        p[0]["output"] = cmd_conf[p[1]]["created_fields"]["annotate_filter"]

# BASIC SINGLE FIELD COMMAND
def p_command_basic_single_field(p):
    '''command : CMD_EXPAND field_name
               | CMD_FLATTEN field_name'''
    p[0] = {"input":[p[2]],"output":[],"fields-effect":"none"}

# BASIC SINGLE ARG COMMAND
def p_command_basic_single_arg(p):
    '''command : CMD_ANALYSEFIELDS args_term'''
    for arg in p[2]:
        if not arg in cmd_conf[p[1]]["args"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)
    if p[1] in ["af","analyzefields"]:
        p[0] = {"input":p[2].values(),"output":cmd_conf[p[1]]["created_fields"],"fields-effect":"replace"}
    else: 
        p[0] = {"input":[],"output":[],"fields-effect":"none"}

# BASIC ONLY ARGS COMMAND
def p_command_basic_only_args(p):
    '''command : CMD_ABSTRACT args_list
               | CMD_ADDCOLTOTALS args_list
               | CMD_ADDTOTALS args_list
               | CMD_ANOMALOUSVALUE args_list
               | CMD_ANOMALYDETECTION args_list
               | CMD_FILLNULL args_list'''
    p[0] = {"input":[],"output":[],"fields-effect":"none"}
    for arg in p[2]:
        if not arg in cmd_conf[p[1]]["args"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)
    if p[1] == "anomalydetection":
        if "action" in p[2]:
            if p[2]["action"] in ["filter","annotate"]:
                p[0]["output"] = cmd_conf[p[1]]["created_fields"]["annotate_filter"]
            elif p[2]["action"] in ["summary"]:
                p[0]["output"] = cmd_conf[p[1]]["created_fields"]["summary"]
                p[0]["fields-effect"]="replace"


# BASIC ONLY FIELDS
def p_command_basic_only_fields(p):
    '''command : CMD_ADDCOLTOTALS fields_list
               | CMD_ADDTOTALS fields_list
               | CMD_FILLNULL fields_list
               | CMD_ANOMALOUSVALUE fields_list
               | CMD_ANOMALYDETECTION fields_list'''
    p[0] = {"input":p[2],"output":[],"fields-effect":"none"}
    if p[1] == "anomalydetection":
        p[0]["output"] = cmd_conf[p[1]]["created_fields"]["annotate_filter"]

# BASIC FIELDS AND ARGS
def p_command_basic_field_and_args(p):
    '''command : CMD_ADDCOLTOTALS args_list fields_list
               | CMD_ADDTOTALS args_list fields_list
               | CMD_FILLNULL args_list fields_list
               | CMD_ANOMALOUSVALUE args_list fields_list
               | CMD_ANOMALYDETECTION args_list fields_list'''
    p[0] = {"input":p[3],"output":[],"fields-effect":"none"}
    for arg in p[2]:
        if not arg in cmd_conf[p[1]]["args"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)
    if p[1] == "anomalydetection":
        if "action" in p[2]:
            if p[2]["action"] in ["filter","annotate"]:
                p[0]["output"] = cmd_conf[p[1]]["created_fields"]["annotate_filter"]
            elif p[2]["action"] in ["summary"]:
                p[0]["output"] = cmd_conf[p[1]]["created_fields"]["summary"]
                p[0]["fields-effect"]="replace"

# WHERE
def p_command_where(p):
    'command : CMD_WHERE expression'
    p[0] = {"input":[],"output":[],"fields-effect":"none"}

# LOOKUP
def p_command_lookup(p):
    '''command : CMD_LOOKUP NAME any_fields_list OUTPUT_OP any_fields_list
               | CMD_LOOKUP NAME any_fields_list OUTPUT_NEW_OP any_fields_list
               | CMD_LOOKUP NAME any_fields_list
               | CMD_LOOKUP NAME'''
    if len(p) > 3:
        p[0] = {"input":p[3],"output":[],"fields-effect":"extend"}
    else:
        p[0] = {"input":[],"output":[],"fields-effect":"none"}
    if len(p) > 4:
        p[0]["output"] = p[5]

def p_command_lookup_args(p):
    '''command : CMD_LOOKUP args_list NAME any_fields_list OUTPUT_OP any_fields_list
               | CMD_LOOKUP args_list NAME any_fields_list OUTPUT_NEW_OP any_fields_list
               | CMD_LOOKUP args_list NAME any_fields_list
               | CMD_LOOKUP args_list NAME'''
    if len(p) > 4:
        p[0] = {"input":p[3],"output":[],"fields-effect":"extend"}
    else:
        p[0] = {"input":[],"output":[],"fields-effect":"none"}
    if len(p) > 4:
        p[0]["output"] = p[5]
    for arg in p[2]:
        if not arg in cmd_conf[p[1]]["args"]:
            report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)

# INPUTLOOKUP
def p_command_inputlookup(p):
    '''command : CMD_INPUTLOOKUP args_list NAME CMD_WHERE expression
               | CMD_INPUTLOOKUP NAME CMD_WHERE expression
               | CMD_INPUTLOOKUP args_list NAME
               | CMD_INPUTLOOKUP NAME'''

    p[0] = {"input":[],"output":[],"fields-effect":"none"}
    if len(p) == 6 or len(p) == 4:
        for arg in p[2]:
            if not arg in cmd_conf[p[1]]["args"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)

# OUTPUTLOOKUP
def p_command_outputlookup(p):
    '''command : CMD_OUTPUTLOOKUP args_list NAME
               | CMD_OUTPUTLOOKUP NAME'''

    p[0] = {"input":[],"output":[],"fields-effect":"none"}
    if len(p) == 4:
        for arg in p[2]:
            if not arg in cmd_conf[p[1]]["args"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)
# ACCUM
def p_command_accum(p):
    '''command : CMD_ACCUM field_name AS_CLAUSE field_name
               | CMD_ACCUM field_name'''
    if len(p) == 5:
        p[0] = {"input":[p[2]],"output":[p[4]],"fields-effect":"extend"}
    else:
        p[0] = {"input":[p[2]],"output":[],"fields-effect":"none"}

# ANOMALIES
def p_command_anomalies(p):
    '''command : CMD_ANOMALIES args_list BY_CLAUSE fields_list
               | CMD_ANOMALIES BY_CLAUSE fields_list
               | CMD_ANOMALIES args_list
               | CMD_ANOMALIES'''
    ipt=[]
    if len(p) == 5 or len(p) == 3:
        for arg in p[2]:
            if not arg in cmd_conf[p[1]]["args"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)
            elif arg == "field":
                ipt.append(p[2]["field"])
    
    p[0] = {"input":ipt,"output":cmd_conf[p[1]]["created_fields"],"fields-effect":"extend"}

def p_command_append(p):
    '''command : CMD_APPEND args_list subsearch
               | CMD_APPEND subsearch'''
    if len(p) == 4:
        for arg in p[2]:
            if not arg in cmd_conf[p[1]]["args"]:
                report_error(p.lexpos(1),p.lexspan(len(p)-1)[1],"Unexpected argument '{}' in {}, expected {}".format(arg,p[1],str(cmd_conf[p[1]]["args"])),None,value=arg)
        p[0] = {"input":p[3]["input"],"output":p[3]["output"],"fields-effect":"extend"}
    else:
        p[0] = {"input":p[2]["input"],"output":p[2]["output"],"fields-effect":"extend"}

#---------------------------
# AGGREGATION fields
#---------------------------
def p_agg_terms_list(p):
    '''agg_terms_list : agg_terms_list COMMA agg_term
                      | agg_terms_list agg_term
                      | agg_term'''
    if len(p) == 4:
        p[0] = {"input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["output"]}
    elif len(p) == 3:
        p[0] = {"input":p[1]["input"]+p[2]["input"],"output":p[1]["output"]+p[2]["output"]}
    else:
        p[0] = p[1]

def p_agg_term(p):
    '''agg_term : agg_fun LPAREN field_name RPAREN AS_CLAUSE field_name
                | agg_fun LPAREN field_name RPAREN
                | agg_fun'''
    if len(p) == 7:
        p[0] = {"input":[p[3]],"output":[p[6]]}
    elif len(p) == 5:
        p[0] = {"input":[p[3]],"output":["{}({})".format(p[1],p[3])]}
    else:
        p[0] = {"input":[None],"output":[p[1]]}
    

def p_agg_fun(p):
    'agg_fun : NAME'
    p[0] = p[1]

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
        p[0] = {"input":p[1]["input"]+p[3]["input"],"output":p[1]["output"]+p[3]["output"]}
    elif len(p) == 3:
        p[0] = {"input":p[1]["input"]+p[2]["input"],"output":p[1]["output"]+p[2]["output"]}
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
    p[0] = {"input":[p[1]],"output":[p[3]]}

def p_field_name(p):
    '''field_name : NAME'''
    p[0] = p[1]

#---------------------------
# Args
#---------------------------
def p_args_list(p):
    '''args_list : args_list args_term
                 | args_term'''
    if len(p) == 3:
        p[0] = p[1].copy()
        for key in p[2]:
            p[0][key] = p[2][key]
    else:
        p[0] = p[1].copy()

def p_args_term(p):
    'args_term : NAME EQ value'
    p[0]={}
    p[0][p[1]]=p[3]

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
    #raise SyntaxError
#errorlog=yacc.NullLogger()
parser = yacc.yacc(debug=True)

#---------------------------
#       CUSTOM FUNCTIONS
#---------------------------
#Custom global vars
scope_level=0
errors={"list":[],"ref":{}}
params={"verbose":True}
data = {"main":{},"subsearches":[]}

def init_analyser():
    global errors, scope_level, data
    errors={"list":[],"ref":{}}
    scope_level=0
    data = {"main":{},"subsearches":[]}

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
            print("[ERROR]\t[{}->{}] {}\n\t{}".format(st,ed,msg,err_str))
        else:
            err_str=s[st:min(ed+10,len(s))]
            print("[ERROR]\t[{}->{}] {} : for value '{}' of type {}\n\t{}".format(st,ed,msg,tk.value,tk.type,err_str))


#---------------------------
#       EXECUTION
#---------------------------

def analyze(s,verbose=False,print_errs=True):
    global errors, params, data
    try:
        init_analyser()
        params["verbose"]=verbose
        r = yacc.parse(s,tracking=True,debug=False)
        if print_errs:
            print_errors(s)
        print("[RES]\tfinished")
        data["main"]=r
        return {"data":data,"errors":errors,"errors_count":len(errors["ref"])}
    except SyntaxError:
        pass