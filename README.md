# SPL Validator

**WARNING** This project is still in beta and under development

## Dependencies

This SPL syntax validator is based on the [PLY project](https://github.com/dabeaz/ply) (Python Lex Yacc).
Files are already onboarded in the lib folder but you might want to check for updates or just thank him.

## Usage

For now, the core of the parser is in the file `spl_validator.py` which describes the syntax of SPL (tokens and grammar rules) and adds so more feature on top of it. The validator can be called using the function `analyze(s,verbose=False,print_errs=True)`.

* `s` is the string to analyze
* `verbose` (optional,default false) will output more information about element being parsed
* `print_errs` (optional, default true) will output the errors found (syntax and wrong SPL usages)

Function return an object with the following attributes:

* `data`: information extracted from the SPL
  * `input`: fields that seem to be used by the query (and probably required in the events)
  * `output`: fields that seem available in the results, this is particularly useful when transforming commands are reducing the number of fields
* `errors`: Object containing the errors found in the SPL.
  * `list`: List of errors identifiers in order of appearance
  * `ref`: Dictionnary containing the list of errors associated to a given error identifier
    * **error identifiers** are unique IDs computed when an error was found for a specific symbol at a specific position in the tested query
    * **error identifiers** are useful in case a same syntax error is caught in several ways, the latest reported error is the one displayed
    * **error identifiers** are either related to a specific token (position + type) or an error message (start and end position + abnormal value)
* `errors_count`: Number of errors found

Syntax can then be checked either by importing `spl_validator` in your own script and calling the `analyze` function, or by putting your query to test in the `main.py` script which does the calling for you.

## Supported SPL commands

SPL commands specification is done in the `spl_commands.json` file

| Command name | Supported | Unsupported | Comments |
| ------------ | --------- | ----------- | -------- |
| abstract | all args | | |
| accum | | | |
| addcoltotals | all args | | |
| addinfo | | | |
| addtotals | all args | | |
| analyzefields | all args | | also giving the list of fields created and extract field name analysed |
| anomalies | all args | | also giving the list of fields created and extract field name analysed |
| anomalousvalue | all args | | |
| anomalies | all args | | also giving the list of fields created |
| append | all args | | |
| audit | | | |
| dedup | all args | | |
| eval | | | |
| expand | | | |
| fields | | | |
| fillnull | all args | | |
| flatten | | | |
| inputlookup | all args and where | | |
| lookup | all args | | |
| outputlookup | all args | | |
| rename | | | |
| reverse | | | |
| search | accidently most args | probably args with special characters | |
| sort | | | |
| stats | first group of args | arg after group by | |
| table | | | |
| where | | | |


## Testing

A small testing module has been written in `test.py` which runs a series of test defined in `test_conf.json`. Basically the purpose is to check if the SPL validator is doing its job properly.

`test_conf.json` is a simple JSON object which works as follows:

* `test_cases`: List of tests to run
  * `search`: Query to test
  * `exp_err`: Expected errors to be found
  * `tags`: List of tags used to select only some of the tests
* `selection`: List of tags to select tests to run
  * Use `*` to select them all
