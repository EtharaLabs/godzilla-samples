// Help screens. `{BIN}` is replaced with the invoked program name.

pub const TOP_LONG: &str = r#"A fast formatter for YAML and Markdown.

Run `yamark <COMMAND> --help` for command-level help.

Usage: yamark <COMMAND>

Commands:
  format      
  to-yaml     Convert JSON-family input from stdin to formatted YAML
  git-filter  Git clean/smudge filter helpers for Markdown files
  help        Print this message or the help of the given subcommand(s)

Options:
  -h, --help
          Print help (see a summary with '-h')

"#;

pub const TOP_SHORT: &str = r#"A fast formatter for YAML and Markdown.

Usage: yamark <COMMAND>

Commands:
  format      
  to-yaml     Convert JSON-family input from stdin to formatted YAML
  git-filter  Git clean/smudge filter helpers for Markdown files
  help        Print this message or the help of the given subcommand(s)

Options:
  -h, --help  Print help (see more with '--help')

"#;

pub const HELP_LONG: &str = r#"A fast formatter for YAML and Markdown.

Run `yamark <COMMAND> --help` for command-level help.

Usage: {BIN} <COMMAND>

Commands:
  format      
  to-yaml     Convert JSON-family input from stdin to formatted YAML
  git-filter  Git clean/smudge filter helpers for Markdown files
  help        Print this message or the help of the given subcommand(s)

Options:
  -h, --help
          Print help (see a summary with '-h')
"#;

pub const FORMAT_HELP: &str = r#"Usage: {BIN} format [OPTIONS] [PATHS]...

Arguments:
  [PATHS]...  

Options:
      --check                        
      --diff                         
      --diagnostics                  
      --stdin-file-path <PATH>       
      --config <PATH>                
      --wrap <WRAP>                  [default: 72]
      --table-widths <TABLE_WIDTHS>  Table widths: fit contents or preserve source widths [default: fit]
      --canonical                    
      --preserve-footnotes           
      --line-width <LINE_WIDTH>      [default: 80]
      --prose-width <PROSE_WIDTH>    [default: 72]
      --indent-width <INDENT_WIDTH>  [default: 2]
      --compact                      
      --skip-embedded-formatters     
  -h, --help                         Print help
"#;

pub const TO_YAML_HELP: &str = r#"Convert JSON-family input from stdin to formatted YAML

Usage: {BIN} to-yaml [OPTIONS] --stdin-file-path <PATH>

Options:
      --stdin-file-path <PATH>       
      --config <PATH>                
      --line-width <LINE_WIDTH>      [default: 80]
      --prose-width <PROSE_WIDTH>    [default: 72]
      --indent-width <INDENT_WIDTH>  [default: 2]
      --compact                      
  -h, --help                         Print help
"#;

pub const GF_LONG: &str = r#"Git clean/smudge filter helpers for Markdown files.

These commands read Markdown from stdin and write formatted Markdown to stdout
for Git attributes filters.

Configure the filter driver with:
  yamark git-filter adopt
  yamark git-filter join
  yamark git-filter check
  yamark git-filter setup
  yamark git-filter teardown
  git config filter.yamark-md.clean "yamark git-filter clean --stdin-filename %f"
  git config filter.yamark-md.smudge "yamark git-filter smudge --stdin-filename %f --markdown-wrap-at-column 72"

Git only runs the filter for paths matched by attributes. Put these patterns in
.git/info/attributes for personal use or .gitattributes for a shared repo:
  *.md filter=yamark-md
  *.qmd filter=yamark-md
  *.Rmd filter=yamark-md
  *.rmd filter=yamark-md

Usage: {BIN} git-filter <COMMAND>

Commands:
  clean     
  smudge    
  adopt     Adopt the yamark Git filter for a shared repository
  join      Join a repository that has already adopted the yamark Git filter
  check     Check committed yamark Git filter blobs round-trip safely
  setup     Configure the yamark Git filter in a repository
  teardown  Remove the local yamark Git filter setup from a repository
  help      Print this message or the help of the given subcommand(s)

Options:
  -h, --help
          Print help (see a summary with '-h')
"#;

pub const GF_SHORT: &str = r#"Git clean/smudge filter helpers for Markdown files

Usage: {BIN} git-filter <COMMAND>

Commands:
  clean     
  smudge    
  adopt     Adopt the yamark Git filter for a shared repository
  join      Join a repository that has already adopted the yamark Git filter
  check     Check committed yamark Git filter blobs round-trip safely
  setup     Configure the yamark Git filter in a repository
  teardown  Remove the local yamark Git filter setup from a repository
  help      Print this message or the help of the given subcommand(s)

Options:
  -h, --help  Print help (see more with '--help')
"#;

pub const GF_CLEAN: &str = r#"Usage: {BIN} git-filter clean --stdin-filename <STDIN_FILENAME>

Options:
      --stdin-filename <STDIN_FILENAME>  
  -h, --help                             Print help
"#;

pub const GF_SMUDGE: &str = r#"Usage: {BIN} git-filter smudge [OPTIONS] --stdin-filename <STDIN_FILENAME>

Options:
      --stdin-filename <STDIN_FILENAME>                    
      --markdown-wrap-at-column <MARKDOWN_WRAP_AT_COLUMN>  [default: 72]
  -h, --help                                               Print help
"#;

pub const GF_ADOPT: &str = r#"Adopt the yamark Git filter for a shared repository

Usage: {BIN} git-filter adopt [OPTIONS] [PATHS]...

Arguments:
  [PATHS]...  Specific Markdown paths to filter; defaults to Markdown file patterns

Options:
      --repo <PATH>
          Repository path; defaults to the current repository
      --yamark <PATH>
          Yamark executable stored in the filter command; defaults to this executable
      --markdown-wrap-at-column <MARKDOWN_WRAP_AT_COLUMN>
          Working-tree column width used by the smudge filter [default: 72]
  -h, --help
          Print help
"#;

pub const GF_JOIN: &str = r#"Join a repository that has already adopted the yamark Git filter

Usage: {BIN} git-filter join [OPTIONS]

Options:
      --repo <PATH>
          Repository path; defaults to the current repository
      --yamark <PATH>
          Yamark executable stored in the filter command; defaults to this executable
      --markdown-wrap-at-column <MARKDOWN_WRAP_AT_COLUMN>
          Working-tree column width used by the smudge filter [default: 72]
  -h, --help
          Print help
"#;

pub const GF_CHECK: &str = r#"Check committed yamark Git filter blobs round-trip safely

Usage: {BIN} git-filter check [OPTIONS]

Options:
      --repo <PATH>
          Repository path; defaults to the current repository
      --markdown-wrap-at-column <MARKDOWN_WRAP_AT_COLUMN>
          Working-tree column width used by the smudge filter [default: 72]
  -h, --help
          Print help
"#;

pub const GF_SETUP: &str = r#"Configure the yamark Git filter in a repository

Usage: {BIN} git-filter setup [OPTIONS] [PATHS]...

Arguments:
  [PATHS]...  Specific Markdown paths to filter; defaults to Markdown file patterns

Options:
      --repo <PATH>
          Repository path; defaults to the current repository
      --yamark <PATH>
          Yamark executable stored in the filter command; defaults to this executable
      --markdown-wrap-at-column <MARKDOWN_WRAP_AT_COLUMN>
          Working-tree column width used by the smudge filter [default: 72]
  -h, --help
          Print help
"#;

pub const GF_TEARDOWN: &str = r#"Remove the local yamark Git filter setup from a repository

Usage: {BIN} git-filter teardown [OPTIONS]

Options:
      --repo <PATH>  Repository path; defaults to the current repository
  -h, --help         Print help
"#;

pub const HELP_HELP: &str = r#"Print this message or the help of the given subcommand(s)

Usage: {BIN} help [COMMAND]...

Arguments:
  [COMMAND]...  Print help for the subcommand(s)
"#;

pub const NOARGS: &str = r#"A fast formatter for YAML and Markdown.

Usage: {BIN} <COMMAND>

Commands:
  format      
  to-yaml     Convert JSON-family input from stdin to formatted YAML
  git-filter  Git clean/smudge filter helpers for Markdown files
  help        Print this message or the help of the given subcommand(s)

Options:
  -h, --help  Print help (see more with '--help')
"#;
pub const TOP_SHORT_BIN: &str = NOARGS;

pub const GF_HELP_HELP: &str = r#"Print this message or the help of the given subcommand(s)

Usage: {BIN} git-filter help [COMMAND]...

Arguments:
  [COMMAND]...  Print help for the subcommand(s)
"#;
