# Contributing to GHOSTWIRE

Thanks for wanting to help build this. All kinds of contributions are welcome.

## Ways to help

- **New modules** (breach sources, social platforms, certificate tools, and more)
- **Bug fixes**, especially tool-output parsing and error handling
- **UI and theme** improvements
- **Docs**: setup guides for other distros, usage examples

## Quick start

1. Fork the repo and clone your fork.
2. Create a virtualenv and install the dependencies (see the README).
3. Make a branch: `git checkout -b feature/my-module`
4. Run the app with `python ghostwire.py` and try your change.
5. Open a pull request describing what it does and how you tested it.

## Adding a module

A module has two parts in `ghostwire.py`:

1. **A handler**, `do_<name>(a)`. It receives the parsed arguments and prints
   results with `out()` and `head()`. Use `run(cmd)` to wrap a CLI tool,
   `get(url)` for HTTP, and `find_tool(name)` to locate binaries.
2. **A sub-parser** in `main()`: `sub.add_parser("Name", help="...")` with
   its arguments, then register it in the dispatch at the bottom.

Keep each module self-contained, and use the existing ones as a template.

## Ground rules

- **Public sources only.** No scraping behind logins, credential stuffing, or
  anything designed to break into accounts or systems.
- **Safe defaults.** Anything that could notify or harm a target (for example
  password-recovery probes) must be opt-in and clearly labeled.
- **Never commit secrets**: API keys, tokens or personal data. Read keys from
  a form field or an environment variable.
- **Be gentle with other people's services.** Respect rate limits and timeouts.
- Match the existing style: plain Python, minimal dependencies, clear output.

## Reporting bugs

Open an issue with your OS, Python version, the module you used, and the
output you got. Redact any personal data.

## Licensing of contributions

By submitting a pull request you agree that your contribution can be
distributed under the project's license, as stated in the repository.
