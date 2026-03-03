# Dave API Key Runbook (Local)

Single source of truth for Dave chat key setup on this project.

## Key resolution order

`/api/chat` resolves the Anthropic key in this order:

1. Environment variable: `ANTHROPIC_API_KEY`
2. macOS Keychain generic password service: `inspirations_anthropic_api_key`

Code reference: `src/inspirations/server.py` (`_get_api_key` + `/api/chat`).

## Verify key exists in Keychain

```bash
security find-generic-password -s inspirations_anthropic_api_key >/dev/null && echo "found"
```

## Add or update key in Keychain

```bash
security add-generic-password -U \
  -a "$USER" \
  -s inspirations_anthropic_api_key \
  -w 'sk-ant-REPLACE_WITH_REAL_KEY'
```

## Optional: session override via env var

Use this only for the current shell/session.

```bash
export ANTHROPIC_API_KEY='sk-ant-REPLACE_WITH_REAL_KEY'
```

## Safe verification (no full key print)

```bash
PYTHONPATH=src python3 - <<'PY'
from inspirations.server import _get_api_key
k = _get_api_key("ANTHROPIC_API_KEY", "inspirations_anthropic_api_key")
print("configured:", bool(k))
print("prefix:", (k or "")[:7])
print("length:", len(k or ""))
PY
```

## Notes

- Do not commit real API keys to git.
- Prefer Keychain for local persistence; use env var for temporary overrides.
