# Blind clipboard — how desktop-operator puts a secret into a native app

Use it only for native macOS apps (a settings dialog, a desktop client). For web pages use `secret-relay.py` with browser-operator instead: no clipboard there.

## Rule

The secret goes 1Password → clipboard → the field. It never passes through the model: the operator never types a password, 2FA code, token or card number from memory, never reads the clipboard back (`read_clipboard` is off-limits for secrets), and never quotes a secret in notes, logs or the report.

## Steps

1. The task prompt names the source: a 1Password reference (`op://<vault-id>/<item-id>/<field>`), an item id for a one-time code, or a scratchpad file.
2. Right before the paste, copy without printing (one Bash call, no output):
   - field: `~/.claude/scripts/op-agent.sh read 'op://<vault-id>/<item-id>/<field>' | tr -d '\n' | pbcopy`
   - one-time code (valid ~30 s, paste at once): `~/.claude/scripts/op-agent.sh item get <item-id> --otp | tr -d '\n' | pbcopy`
   - file: `pbcopy < <file> && rm <file>`
   - an item outside `OP_VAULT`: plain `op` instead of `op-agent.sh` (Touch ID), and only when the task names that reference.
3. Click the field, press cmd+v.
4. Check the length only: `pbpaste | wc -c` — never the value.
5. Clear the clipboard at once: `printf '' | pbcopy`.

## Edge cases

- A dialog asks for a secret the task gave no reference for → leave it open and report `BLOCKED` with the exact prompt text.
- A password shown in clear text on screen must not be transcribed. Use the app's copy button and store the value via the Keychain or 1Password route (`secret-relay.py receive`, or `pbpaste | … op-agent.sh item create -` from the skill).
- Dictation and clipboard managers can overwrite the clipboard: no dictation while a paste is pending; re-check the length right before cmd+v.
- Clipboard history apps keep copies: exclude the terminal from them, or clear the history after the run.
