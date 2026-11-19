This is a reverse-engineering task. You are given a compiled program and its documentation. Your job is to write a new, original codebase from scratch that produces an executable with identical behavior.
You must figure out the behavior solely by running and interacting with the provided program and reading its documentation.
Writing original code based on observed behavior is the entire point of this task.

Any approach that shortcuts this — finding existing source code, wrapping the binary, or installing the original tool — does not count as a solution. It will be detected: a submission that embeds a copy of the provided executable is rejected, and one that runs it does not work (your program is checked without it).

<RULES>
## What is not allowed

### 1. Obtaining source code
The only source of truth about what the executable does is the executable itself and its bundled documentation. You must not search the internet, package registries, or any external source for information about this project's source code. Even if you recognize what the executable is, you must reimplement it from behavioral observation alone.

This includes but is not limited to:
- Cloning or browsing the original repository, its forks, or mirrors
- Downloading the project from package registries (`cargo install <project>`, `go get <module>`, `pip install <project>`, `apt-get source <project>`, `npm install <project>`, ...)
- Fetching source tarballs from project websites
- Using a package manager to download the project as a dependency and then reading its cached source
- Searching the web for the project's source code or implementation details

### 2. Wrapping or reusing the original binary
Your submission must be a genuine reimplementation. The provided `./executable` is for observation only — your final solution must not depend on it, or on any other pre-built version of the same tool, at runtime or at build time.

This includes but is not limited to:
- Writing a wrapper script that delegates to the original binary
- Copying, encoding (base64, hex, compression, archives) or embedding the provided binary in your submission
- Writing a `compile.sh` that simply makes the provided binary executable or copies it
- Building a binary whose main function shells out to an external copy of the tool

### 3. Binary analysis of the provided executable
All information about the provided `./executable` must be obtained by interacting with it through its normal user interface (command-line arguments, stdin/stdout/stderr, files, environment variables).
- You MUST NOT decompile `./executable` or use disassemblers on it
- You MUST NOT use strace, ltrace, or similar tracing/instrumentation tools on `./executable`

This restriction applies ONLY to the provided `./executable`. You may use any analysis tools on binaries that you build yourself.

## What IS allowed
- Running the executable with any inputs, flags, arguments, files and environment variables to observe its behavior
- Reading any documentation bundled in the workspace
</RULES>

## Task context

The workspace is `/workspace` (a git repository). It contains:
- `./executable` — the program to reproduce (you can run it, but not read it).
- Its user documentation: `LICENSE`, `NOTICE`, `README.md`, `docs/src/SUMMARY.md`, `docs/src/educators/README.md`, `docs/src/educators/answer-keys.md`, `docs/src/educators/session-1.md`, `docs/src/educators/session-2.md`, `docs/src/educators/session-3.md`, `docs/src/educators/session-4.md`, `docs/src/educators/session-5.md`, `docs/src/introduction.md`, `docs/src/learn/01-values-and-inference.md`, `docs/src/learn/02-functions-currying-pipes.md`, `docs/src/learn/03-option.md`, `docs/src/learn/04-result.md`, `docs/src/learn/05-adts-and-match.md`, `docs/src/learn/06-records.md`, `docs/src/learn/07-collections.md`, `docs/src/learn/08-tuples.md`, `docs/src/learn/09-typed-holes.md`, `docs/src/learn/10-mutation.md`, `docs/src/learn/11-effects.md`, `docs/src/learn/12-python-interop.md`, `docs/src/learn/13-computation-expressions.md`, `docs/src/learn/14-units-of-measure.md`, `docs/src/learn/15-modules.md`, `docs/src/learn/16-capstone.md`, `docs/src/learn/17-recursion.md`, `docs/src/learn/18-async.md`.
- `assets/` — sample input files in formats you could not easily create yourself.
- The program reads one environment variable of its own: `PYFUN_PYTHON`, when set and not empty, names the Python interpreter that `run`, `build --native` and the package commands use (otherwise it looks for `python`, then `python3`, on PATH), and the package commands install through `uv` when `uv` is on PATH. Observe the details by running the program.

## Your task

Implement the source code for a program with exactly the same behavior as `./executable`: the same output on stdout and stderr, the same exit codes, and the same effects on files, for every input.
- Write your implementation in Rust, the language of the original program (Rust 1.99.1 with `cargo`, standard library only). `./compile.sh` must build it from your source code into a native executable. A submission written in another language, or whose program runs another language's interpreter (Python, Perl, Node.js, ...), is not accepted, and neither is one with fewer than 50 lines of Rust source. One exception: the original itself starts a `python` interpreter (with or without a version suffix), and your program may do the same wherever the original does; the program's own work must still be done in Rust. All code in your workspace counts, not only your program: code in other languages (shell, Python, Perl, ...), including your own test scripts and tools, may be at most 5% of the workspace's code lines, or the submission is not accepted. Keep scratch scripts outside the workspace (for example in /tmp), or write your tests in Rust.
- No project-specific dependencies are pre-installed and you do NOT have access to the internet, so you cannot download packages. Use only the standard libraries and tools already installed.
- Provide an executable `./compile.sh` at the workspace root that builds your program and leaves the final compiled Rust binary (a native executable, not a script or launcher) at `./executable` in the workspace root. It will be run on a fresh checkout of your repository without internet access. If `./compile.sh` fails on a fresh checkout, your task has failed.
- When you are done, your workspace (without `./executable` and without a `./target` build directory) is copied into a fresh container with no internet access, `./compile.sh` is run there, and the `./executable` it produces is compared with the original program on many inputs.
- Make sure the executable and every build artifact are listed in `.gitignore`, then commit your work.

You SHOULD extensively test the executable to understand its behavior before and while writing code. Your program's behavior will be compared with the original's on inputs beyond the ones you try. If the program has an interactive terminal interface, `tmux` is installed to help you drive it.

## Recommended workflow
1. Read all documentation files.
2. Explore the executable's behavior systematically: `--help`, every subcommand and flag, normal inputs, edge cases, and error cases.
3. Design and write your implementation, then compare its behavior with the original on many inputs.
4. Run `./compile.sh` from a clean checkout to make sure it works, and commit.

When you are completely done, commit your work and stop.
