# Contributing to ProjectVault

Thanks for helping. Small, focused changes are the easiest to review.

## Set up

ProjectVault's core uses only the Python standard library (Python 3.9 or newer).

```bash
git clone <your-fork-url>
cd projectvault
pip install -r requirements-dev.txt
```

## Run the tests

```bash
python -m pytest -q
```

Tests run offline. Network and cloud libraries are mocked, so you do not need any accounts or keys.

## Style

- Keep the core dependency-free. Optional libraries (`google-api-python-client`, `google-auth`, `boto3`) are imported only when needed.
- Follow the style of the surrounding code. Keep functions short and add a comment where the reason is not obvious.
- Never log tokens, keys or the contents of `.env`.
- Use generic examples in docs and tests (`my-project`, `example.com`). Do not add real names, tokens or paths.

## Pull requests

1. Open an issue first for anything bigger than a small fix.
2. Keep one change per pull request.
3. Add or update a test when behaviour changes.
4. Update the docs and `CHANGELOG.md` if users will notice the change.
5. Make sure `python -m pytest -q` passes before you push.

## Reporting bugs

Use the bug report template. For security problems, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
