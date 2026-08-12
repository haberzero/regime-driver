# Security Policy

## ⚠️ Development status

This project is **in development and not yet released** (see `README.md`). No
security guarantees are made. Use only in controlled/isolated environments.

## Reporting a vulnerability

Please **do not** open a public issue for security bugs. Report privately to the
maintainer (see the project's git author / GitHub account `haberzero`) or open a
**draft/private** advisory on GitHub (Settings → Security → Advisories).

We aim to acknowledge reports within 7 days.

## Security model / key handling

- **Keys are never committed.** Model API keys live in `~/.regime/keys/*.key`
  (gitignored) or env vars (`OPENCODE_GO_API_KEY`, `DEEPSEEK_API_KEY`), and are
  injected into worker/dialog-control containers only at runtime (`-e` env).
- Repo `docker/*/opencode.json` and `config.example.toml` use `{env:...}`
  placeholders only — never real keys.
- `regime doctor` reports key **presence only**, never the value.
- This tool drives real AI models, Docker containers, and can auto-execute code.
  Treat its output as untrusted and run it in an isolated sandbox.

## Reporting guideline

Include: environment, affected version/commit, steps to reproduce, expected vs
actual, and any impact. Do not include real secrets in the report.
