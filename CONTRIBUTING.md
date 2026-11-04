# Contributing to SessionGit

Hey! Thanks for wanting to contribute. I built this because I kept losing track of what Claude and I were working on across sessions, and figured I wasn't alone.

## Quick Start

```bash
git clone https://github.com/cliffhangerchaos-cloud/sessiongit.git
cd sessiongit
pip install -e ".[dev]"
pytest tests/
```

If tests pass, you're good to go.

## What I'm Looking For

Honestly? Anything that makes this more useful. Some ideas:

- Bug fixes (always appreciated)
- Better error messages (mine are sometimes cryptic)
- Performance improvements (the search could be faster)
- Platform-specific fixes (Windows is a pain, help me out here)
- Documentation improvements (if something confused you, it'll confuse others)

## How to Contribute

1. Fork it
2. Make your changes
3. Add tests if you're adding features
4. Make sure existing tests still pass
5. Open a PR

I'll try to review within a couple days. I have a day job so weekends are usually when I have time.

## Code Style

I use `black` for formatting and `ruff` for linting. Just run:

```bash
black src/
ruff check src/
```

Don't stress too much about style though - I can clean it up if needed.

## Testing

Run the full test suite:
```bash
pytest tests/ -v
```

About 5 tests fail on Windows due to path/encoding weirdness. I know about them. If your PR makes more tests fail, we should probably figure out why.

## Architecture Overview

The core idea is content-addressed storage (like Git):

```
~/.sessiongit/
  objects/          # File content stored by SHA256 hash
    ab/cd123...    # Deduplicated, compressed
  sessions/         # Conversation history
    sess_abc/
      meta.json     # Session metadata
      turns/        # Each conversation turn
```

Main components:
- `ObjectStore` - handles content-addressed storage
- `SessionManager` - creates sessions, commits turns
- `FileTracker` - tracks file changes and generates diffs
- MCP server - integrates with Claude Desktop

## What Needs Work

Check the issues tagged `help wanted` or `good first issue`. Some areas that need attention:

- Auto-capture is flaky as hell (monitor mode doesn't work reliably)
- Search could be way faster with better indexing
- Export/import could use more formats
- Windows console encoding issues
- Better CLI output formatting
- VSCode extension would be cool

## Decision Making

For small stuff (bug fixes, docs, minor features) - just send a PR.

For bigger changes (new features, architecture changes) - open an issue first so we can discuss. I don't want you to waste time building something I won't merge.

## First Time Contributing?

Look for issues labeled `good first issue`. I try to keep a few easy ones available. Or if you just fixed a typo, that's cool too.

## Questions?

Open an issue or discussion. I'm pretty responsive, just be patient if I'm slow to reply - again, day job.

## Code of Conduct

Don't be a jerk. That's it. We're all just trying to build something useful here.

## License

By contributing, you agree your code will be under the MIT license (same as the project).

---

Seriously though, thanks for contributing. Even if it's just fixing a typo in the README, it helps.
