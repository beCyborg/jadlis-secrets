---
name: secrets
description: "Access contract for agent work — every login, token and API key the agent uses lives in ONE 1Password vault (OP_VAULT in ~/.config/jadlis/agent.conf), read through the service-account wrapper op-agent.sh without Touch ID; passwords never enter the model context (secret-relay.py URL for browser-operator, blind clipboard for desktop-operator); Proton Pass aliases for sign-ups via proton-alias.sh. Triggers: where is the password, save the token, store this API key, create a login with a generated password, list the agent's accesses, rotate a password, new alias, set up agent secrets. RU triggers: пароль от, где пароль, сохрани токен, сохрани ключ, заведи доступ, создай логин, сгенерируй пароль, какие доступы есть, смени пароль, алиас для сервиса, настрой секреты агента. Do NOT use for: the sign-up flow itself → jadlis-signup; reading, waiting for or sending mail → jadlis-mail; paying or binding a card → the human."
disable-model-invocation: false
allowed-tools: Bash, Read
---

# secrets — where the agent's accesses live and how to use them

Settings: `~/.config/jadlis/agent.conf` (plain `KEY="value"` lines; template `agent.conf.example` in this plugin). Keys used here: `OP_VAULT`, `OP_ACCOUNT`, `OP_SA_KEYCHAIN_SERVICE`, `PASS_LOGIN_ITEM`, `PASS_VAULT`, `ALIAS_PREFIX`, `ALIAS_DOMAIN`. The scripts read the file themselves; in a Bash block get a value with `~/.claude/scripts/op-agent.sh --get OP_VAULT`.

Scripts live in `~/.claude/scripts/` after the install step (below). If `op-agent.sh --check` fails, run the install step first.

## Contract

1. **One store.** Every access the agent uses (logins, API keys, tokens, app passwords) is an item in the vault `OP_VAULT`. Nothing goes into files, `.env`, notes, memory or chat. Other vaults of the human are read only when the human names the exact item.
2. **No Touch ID.** `op-agent.sh <op args>` injects the service-account token from the macOS Keychain (service `OP_SA_KEYCHAIN_SERVICE`, account `$USER`) into one `op` call. The service account sees only `OP_VAULT`. No token in the Keychain → the wrapper falls back to plain `op` and prints a note on stderr: then every Bash call asks the human for Touch ID — tell the human and point to the install step.
3. **Refer to items by id.** Get ids from `item list`; use `op://<vault-id>/<item-id>/<field>` references. Names with dashes, slashes or non-Latin letters break `op read` references.
4. **A secret never enters the model context.** Never run `op read`, `--reveal` or `pbpaste` where the output lands in the transcript. Send a secret straight into a pipe, a `0600` file you delete, or a child process, and report only its length.
   - **Into a web form** (browser-operator): `secret-relay.py serve --op 'op://…'` prints a one-shot `127.0.0.1` URL; browser-operator fetches it inside `browser_run_code_unsafe` and fills the field. Full snippet: `secret-relay.py --help`.
   - **Out of a web page** (a key the site shows once): `secret-relay.py receive -- <command with {}>`; browser-operator POSTs the value, the command stores it.
   - **Into a native app** (desktop-operator): the blind clipboard — [references/blind-clipboard.md](references/blind-clipboard.md).
5. **Sign-ups, payments, phone checks.** The sign-up flow is jadlis-signup. Payments, card binding and phone verification stay with the human.

## Commands

```bash
A=~/.claude/scripts/op-agent.sh
V=$($A --get OP_VAULT)
$A --check                                                          # config, vault, token found? (never the token)
$A item list --vault "$V"                                           # inventory: ids and titles
$A item get <item-id> --vault "$V" --format json | jq '[.fields[] | {label, type}]'   # field labels, no values
$A item get <item-id> --vault "$V" --otp | ~/.claude/scripts/secret-relay.py serve    # TOTP for a form, ~30 s valid
```

### Create a login with a generated password

The password is generated inside 1Password and never leaves it at creation:

```bash
$A item create --vault "$V" --category login --title "<Service>" \
   --url "https://<service>" "username=<address>" \
   --generate-password=20,letters,digits,symbols \
   "notesPlain=Created by the agent on $(date +%F)." --format json | jq '{id, title}'
```

Then pass the password to the form with `secret-relay.py serve --op "op://$V/<item-id>/password"`. Item naming: `<Service>` for logins, `<Service> API key` for API credentials.

### Save a token someone gives you

Never type a token into a command line: assignment arguments show up in the process list. Feed it through stdin as a JSON template.

- The human copies the token, then you run (the value goes clipboard → stdin → 1Password; check only the length first):

```bash
pbpaste | wc -c                                                     # length only; Spokenly-style tools can overwrite the clipboard
pbpaste | python3 -c 'import json,sys; v=sys.stdin.read().strip(); print(json.dumps({"title": sys.argv[1], "category": "API_CREDENTIAL", "fields": [{"id": "credential", "type": "CONCEALED", "label": "credential", "value": v}]}))' "<Service> API key" \
  | $A item create - --vault "$V" --format json | jq '{id, title}'
printf '' | pbcopy                                                  # clear the clipboard
```

- The token is on a web page: `~/.claude/scripts/secret-relay.py receive -- ~/.claude/scripts/op-agent.sh item edit <item-id> --vault "$V" 'credential={}'` and hand the URL to browser-operator. Create the empty item first with `item create … --category "API Credential" --title "<Service> API key"`.
- The token must sit in the Keychain instead (another tool reads it there): `secret-relay.py receive -- security add-generic-password -s <service> -a "$USER" -w {} -U`, or let the human run `security add-generic-password -s <service> -a "$USER" -w` in a terminal (it prompts for the value).
- If the human already pasted a token into the chat, store it, say it is now in the transcript, and suggest rotating it.

### Rotate

A password: generate the new value in 1Password, then change it on the site at once (relay the old value with `serve --op` before the edit if the site asks for it, the new one after). 1Password keeps the previous value in the item's password history.

```bash
$A item edit <item-id> --vault "$V" --generate-password=20,letters,digits,symbols --format json | jq '{id, title}'
```

A token: create the new one on the service, store it (above), then revoke the old one.

**Service-account token** (the human does this): my.1password.com → Developer → Service Accounts → create a new account for `OP_VAULT` only (the token is shown once), then in a terminal:

```bash
security add-generic-password -s "<OP_SA_KEYCHAIN_SERVICE>" -a "$USER" -U -w    # prompts for the token; never put it on the command line
~/.claude/scripts/op-agent.sh --check
```

Revoke the old service account afterwards.

## Proton Pass aliases for sign-ups

```bash
P=~/.claude/scripts/proton-alias.sh
$P create <service-slug> --dry-run     # shows the prefix and whether pass-cli is signed in; creates nothing
$P create <service-slug>               # {"id": …, "alias": "<ALIAS_PREFIX>-<slug>.<suffix>@<domain>"}
$P list                                # active aliases with ALIAS_PREFIX; --all for every alias
$P trash <item-id>                     # disable an alias
```

- Slug: lowercase letters, digits, inner dashes (`notion`, `shop-example`). One alias per service.
- pass-cli must run as the Proton user. Agent and personal-access-token sessions are read-only for item creation. Signed out → the script signs in with `PASS_LOGIN_ITEM` from `OP_VAULT` (username, password, one-time code). A one-time code works once per 30 s; a second sign-in inside the same window fails. Some pass-cli builds lack the headless `login --interactive`; the script then asks the human to run `pass-cli login` once.
- pass-cli cannot choose the alias domain: it uses the default set in Proton Pass. `ALIAS_DOMAIN` only checks the result and adds a `warning`.
- Some services reject alias domains at verification. Then ask the human for another address; never invent a `+` address.

## Install (once, by the human)

1. Tools: `brew install --cask 1password-cli` and `brew install proton-pass-cli` (the latter only for aliases).
2. Scripts: `mkdir -p ~/.claude/scripts && cp "${CLAUDE_PLUGIN_ROOT}/scripts/"* ~/.claude/scripts/ && chmod +x ~/.claude/scripts/op-agent.sh ~/.claude/scripts/secret-relay.py ~/.claude/scripts/proton-alias.sh`
3. Config: `mkdir -p ~/.config/jadlis && cp -n "${CLAUDE_PLUGIN_ROOT}/agent.conf.example" ~/.config/jadlis/agent.conf`, then fill `OP_VAULT`, `OP_ACCOUNT` (if several 1Password accounts are signed in), `OP_SA_KEYCHAIN_SERVICE`, and for aliases `PASS_LOGIN_ITEM`, `ALIAS_PREFIX`. `cp -n` never overwrites an existing file.
4. 1Password: create one vault for the agent, then a service account with read/write access to that vault only (my.1password.com → Developer → Service Accounts). Copy the token once.
5. Keychain, in a terminal: `security add-generic-password -s "<OP_SA_KEYCHAIN_SERVICE>" -a "$USER" -w` — it prompts for the token. Never pass the token as an argument.
6. Proton Pass (optional): put the Proton login (username, password, one-time code) into an item in `OP_VAULT` and name it in `PASS_LOGIN_ITEM`; run `pass-cli login` once.
7. Check: `~/.claude/scripts/op-agent.sh --check` → `token=found`; `~/.claude/scripts/proton-alias.sh create test --dry-run`.

When helping with the install, run steps 2, 3 and 7 yourself; steps 4–6 are the human's (the token and the Proton password must not pass through you).

## Gotchas

- Do not export `OP_SERVICE_ACCOUNT_TOKEN` globally — the wrapper scopes it to one command.
- A service account cannot create vaults and sees only its granted vault: «not found» means a missing grant, not a missing item.
- `--generate-password` recipe: `<length>,letters,digits,symbols` (any order, length 1–64). Default without a recipe is 32 characters.
- `secret-relay.py serve --literal <text>` is for tests only: the value is visible in the process list and the transcript.
