# SPL Validator

**WARNING** This project is still in beta and under development

## Dependencies

This SPL syntax validator is based on the [PLY project](https://github.com/dabeaz/ply) (Python Lex Yacc).
Files are already onboarded in the lib folder but you might want to check for updates or just thank him.
Latest PLY version used: 3.11.

## Usage

For now, the core of the parser is in the file `spl_validator.py` which describes the syntax of SPL (tokens and grammar rules) and adds so more feature on top of it. The validator can be called using the function `analyze(s,verbose=False,print_errs=True,macro_files=[])`.

* `s` is the string to analyze
* `print_errs` (optional, default true) will output the errors found (syntax and wrong SPL usages) (logging.ERROR)
  * If disabled but in verbose mode, errors will not be displayed
* `verbose` (optional, default false) will output more information about elements being parsed (logging.DEBUG)
* `macro_files` (optional, default empty list) is the list of file paths for macro definitions (macros.conf) to use to expand the macros calls before running the analysis
  * If a macro is found but cannot be expanded, it will be discarded but the SPL might not be syntaxically valid without the content of the macro
* **NEW!** `optimize` (optional, default to True) is a boolean indicating whether to use the optimized PLY mode which leverage pre-compiled lex and yacc tables to initialize faster

Function return an object with the following attributes:

* `data`: information extracted from the SPL
  * `input`: fields that seem to be used by the query (and probably required in the events)
  * `output`: fields that seem available in the results, this is particularly useful when transforming commands are reducing the number of fields
  * `fields-effect``: The list of effects each command had on the available fields
    * `none`: No change done
    * `replace`: Sets a new list of fields available
    * `extend`: Adds new fields
    * `remove`: Removes some fields from the results
  * `filters`: A list of filters (field+operator+value) found at the level of the generating command (and in the possible subsearches) with the purpose to give an idea what the query is filtering
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
| appendcols | all args | | |
| appendpipe | all args | | |
| arules | all args | | |
| associate | all args | | |
| audit | | | |
| autoregress | all args | | case of numbers interval specifically handled for this rule, list of generated fields not handled |
| bin | all args | | |
| bucket | all args | | |
| bucketdir | all args | | |
| cefout | all args | | |
| chart | all args | | Grammar is quite complex, might be some bugs |
| cluster | all args | | |
| cofilter | | Name of outputed fields | |
| collect | all args | | |
| concurrency | all args | | |
| contingency | all args | | |
| convert | all args | | |
| correlate | all args | | |
| ctable | all args | | alias of contingency |
| datamodel | all args | | |
| dbinspect | all args | | |
| dedup | all args | | |
| delete | | | |
| delta | all args | | |
| diff | all args | | |
| erex | all args | | |
| eval | | | |
| eventcount | all args | | |
| eventstats | all args | | |
| expand | | | |
| extract | all args | | |
| fieldformat | | | |
| fields | | | |
| filldown | | | |
| fillnull | all args | | |
| findtypes | all args | | support the detection of an incorrect mode value |
| flatten | | | |
| folderize | all args | | |
| foreach | all args | | Unsure about the syntax expected for the subsearch, for now considering only an eval is allowed |
| format | all args | | |
| from | | | Checks usage of colon in dataset reference |
| gauge | | | Also giving the list of fields created |
| gentimes | all args | | |
| geom | all args | | |
| geomfilter | all args | | |
| geostats | all args | | |
| head | all args | | |
| highlight | | | |
| history | all args | | also giving the list of fields created according to the value of the arg |
| iconify | | | |
| inputcsv | all args and where | | |
| inputlookup | all args and where | | |
| iplocation | all args | | also giving the list of fields generated depending on the arguments |
| join | all args | | |
| kmeans | all args | | also giving the created field |
| loadjob | all args | | not testing if a sid and the searchsearch arg are provided at the same time |
| localize | all args | | |
| localop | | | |
| lookup | all args | | |
| makecontinuous | all args | | |
| makemv | all args | | |
| makeresults | all args | | also giving the list of fields created even with annotate set to true |
| map | all args | | |
| mcollect | all args | | makes sure index arg is provided |
| metadata | all args | | makes sure type is arg is provide and has a correct value, provides the list of created fields |
| metasearch | | | also gives the list of outputed fields |
| meventcollect | all args | | makes sure index arg is provided |
| mpreview | all args | | |
| msearch | all args | | |
| mstats | all args | | |
| multikv | all args | | fields and filter are handled as specific selector in the arguments |
| mulitsearch | | | |
| outputcsv | all args | | |
| outputlookup | all args | | |
| outputtext | all args | | |
| pivot | all args | | |
| predict | all args | cannot yet recognize multiple fields using multiple algos because this is too ambiguous | recognizing correctly fields like upper95 |
| rangemap | all args | | |
| rare | all args | | |
| redistribute | all args | | |
| regex | all args | | |
| relevancy | | | |
| reltime | | | |
| rename | | | |
| replace | | | |
| require | | | |
| rest | all args | | |
| return | | | |
| reverse | | | |
| run | all args | | |
| savedsearch | all args | | |
| script | all args | | |
| scrub | all args | | |
| search | accidently most args | probably args with special characters | |
| searchtxn | all args | | |
| selfjoin | all args | | |
| sendemail | all args | | |
| set | all args | | |
| setfields | | | |
| sichart | all args | | implemented as the replica of the chart command |
| sirare | all args | | implemented as an alias of the rare command |
| sistats | all args | | implemented as the replica of the stats command |
| sitimechart| all args | | implemented as the replica of the timechart command |
| sitop| all args | | implemented as the replica of the top command |
| sort | | | |
| spath | all args | | |
| stats | first group of args | arg after group by | |
| strcat | all args | | |
| streamstats | all args | | |
| table | | | |
| tags | all args | | also giving the list of created fields |
| tail | | | |
| timechart | all args | | `agg` arg might not be properly handled since it is badly documented, same for the commands with multiple aggregation terms |
| timewarp | all args | | |
| top | all args | | |
| transaction | all args | list of fields for arg mvlist because that is a nightmare to handle | |
| transpose | all args | | also giving the list of created fields except when header_field is being used |
| tstats | all args | | |
| typeahead | all args | | |
| typelearner | all args | | |
| typer | all args | | |
| union | all args | | |
| uniq | | | |
| untable | | | |
| walklex | all args | | |
| where | | | |
| x11 | | | |
| xmlkv | all args | | |
| xmlunescape | all args | | |
| xpath | all args | | |
| xyseries | all args | | |


## Testing

A small testing module has been written in `test.py` which runs a series of test defined in `test_conf.json`. Basically the purpose is to check if the SPL validator is doing its job properly.

`test_conf.json` is a simple JSON object which works as follows:

* `test_cases`: List of tests to run
  * `search`: Query to test
  * `exp_err`: Expected errors to be found
  * `tags`: List of tags used to select only some of the tests
* `selection`: List of combinations of tags to select tests to run
  * Example: `"selection": [["search","error"]]` will select test cases having both tags
  * Other example: `"selection": [["search"],["error"]]` will select test cases where at least one of the tags matched
  * Use `*` to select them all

## Macros handling

Another module has been implemented in `macros.py` to handle the case of Splunk search macros. Three functions are made available:

* `loadFile(fpath)` Loads the conf file at the given path and return a dictionary containing the stanzas found
* `expandMacro(macro,mconf)` Tries to expand the given macro call (without the backticks) using the provided macros configuration
  * The macros configuration expected is the one returned by the function `loadFile`
  * It return a dictionary with two fields:
    * `success`: Boolean indicating if the macro could be succesfully expanded
    * `text`: A string containing either the error message or the result of the macro extension
* `handleMacros(spl,macro_defs_paths=[])` Analyses the content of the provided SPL and loads the macro definitions from the list of file paths given in input
  * Return a dictionary containing three fields:
    * `txt`: the updated SPL (or not if no macro could be expanded)
    * `unique_macros_found`: The number of distinct macro calls found
    * `unique_macros_expanded`: The number of distinct macro calls expanded
      * This can be used to deduce if some macros could not be expanded and might cause future issues

The `handleMacros` function is used in the main parser to try to expanded the macros using the provided list of file configuration paths.

Keep in mind that the principle of macros goes against the concept of formal grammars, consequently they have to be expanded before any kind of analysis and the remaining ones should be discarded (which is done here by the lexer).

### About recursive macros

Recursive macros are supported, the process of macros detection and expanding is repeated until no more are found (unless none of those left could be expanded) up to 100 repetitions.

## Debugging

The PLY parser prints debugging information in the file `parser.out`, which contains elements such as the state machine description, helping understand how the parser behaves.

## Optimized mode

Thanks to the optimized mode of PLY, it is now possible to massively improve the start-up time of the parser (which was excruciatingly long in our case).
In this mode, PLY will generate table files for Lex (`lexer_tab.py`) and Yacc (`parsetab.py`) on the first execution, which are then reused on the next executions to initialize faster.

These table files mostly contain the documentation strings used by PLY to define the tokens and grammar rules. This is done because the optimized mode of Python (`-O`) ignores these documentation strings.
Keep in mind that if the implementation of the parser is changed, these table files need to be re-generated.

When using the optimized mode of PLY, it is now possible to run the python scripts with the `-O` flag.

This feature can be disabled through the "optimize" argument: `spl_validator.analyze(s,verbose=True,optimize=False)`

## Author

Romain Durban (romain.durban@gmail.com)

# License

The project is licensed under MIT License