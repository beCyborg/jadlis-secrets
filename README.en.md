[Русский](README.md) · English

# The agent's accesses in one 1Password vault — no Touch ID, no passwords in the chat

The `/secrets` skill for Claude Code keeps every login, token and key the agent uses in one
1Password vault. The agent reads them through a service account, so 1Password does not ask for
Touch ID on every command. A password never enters the model's context: a one-shot local URL
carries it into a web form, and a "blind" clipboard carries it into a native app.

```
claude plugin marketplace add https://github.com/beCyborg/jadlis-hub.git
claude plugin install jadlis-secrets@jadlis
```

## Why

- **One place for accesses.** The agent keeps no passwords in files, `.env`, notes or memory.
  Everything sits in one vault that only the agent's service account can see.
- **No Touch ID.** The `op-agent.sh` wrapper takes the service-account token from the macOS
  Keychain and hands it to one `op` command. Without a token it falls back to plain `op` with
  Touch ID and says so.
- **The model never sees the password.** `secret-relay.py` starts a one-shot server on
  `127.0.0.1` with a random port and path. The browser agent fetches the password with one request
  and fills the field at once. Then the server exits.
- **Aliases for sign-ups.** `proton-alias.sh` creates Proton Pass aliases named
  `<prefix>-<service>`, lists them and disables the ones you no longer need.

## Installing

You need Claude Code, macOS, a 1Password account that may create service accounts and the
[1Password CLI](https://developer.1password.com/docs/cli/). The Proton Pass CLI is needed only for
aliases.

1. The plugin:

   ```
   claude plugin marketplace add https://github.com/beCyborg/jadlis-hub.git
   claude plugin install jadlis-secrets@jadlis
   ```

2. Tools: `brew install --cask 1password-cli`, plus `brew install proton-pass-cli` for aliases.
3. Scripts. Copy them from the plugin folder to `~/.claude/scripts/` (`claude plugin list` shows
   the plugin path, or ask Claude to do this step):

   ```
   mkdir -p ~/.claude/scripts
   cp <plugin folder>/scripts/* ~/.claude/scripts/
   chmod +x ~/.claude/scripts/op-agent.sh ~/.claude/scripts/secret-relay.py ~/.claude/scripts/proton-alias.sh
   ```

4. Settings. Copy the example and fill it in:

   ```
   mkdir -p ~/.config/jadlis
   cp -n <plugin folder>/agent.conf.example ~/.config/jadlis/agent.conf
   ```

5. Service account. Create a separate vault for the agent in 1Password. Then on
   my.1password.com → Developer → Service Accounts create a service account with access to that
   vault only. The token is shown once — copy it.
6. Token into the Keychain. Run this in a terminal and paste the token when it asks:

   ```
   security add-generic-password -s op-service-account-agent -a "$USER" -w
   ```

   The service name must match `OP_SA_KEYCHAIN_SERVICE` in the settings. Do not put the token in
   the command itself: it would land in the shell history.
7. Check: `~/.claude/scripts/op-agent.sh --check` must show `token=found`.

Uninstall: `claude plugin uninstall jadlis-secrets@jadlis`. The scripts and settings stay — remove
them by hand.

## Using it

Ask in plain words: "where is the password for X", "save this token", "create a login for X with a
generated password", "what accesses does the agent have", "rotate the password for X", "make an
alias for X". Claude calls the skill itself.

- **Login with a generated password.** 1Password generates a 20-character password. It stays in
  the vault; `secret-relay.py` carries it into the form.
- **A token someone gave you.** Copy it to the clipboard. Claude moves it into 1Password through
  stdin, checks only its length and clears the clipboard.
- **A key a site shows once.** The browser agent sends it to `secret-relay.py receive`, which
  stores it in 1Password or the Keychain at once.
- **A Mac app.** The desktop agent pastes the password through the blind clipboard: copy without
  printing, paste, check the length, clear the clipboard. The rule is in
  [skills/secrets/references/blind-clipboard.md](skills/secrets/references/blind-clipboard.md).
- **Aliases.** `proton-alias.sh create <service> --dry-run` shows what would be created and
  creates nothing. Without `--dry-run` it creates the alias and prints JSON with an `alias` field.

Self-test of the scripts without reading any secret: `zsh tests/selftest.sh`.

## Settings

The file `~/.config/jadlis/agent.conf` holds `KEY="value"` lines and `#` comments. Put every value
in double quotes. The file is shared by the jadlis-secrets, jadlis-signup, jadlis-mail and
jadlis-browser plugins: each reads only its own keys. It holds no secrets.

| Key | Meaning |
|---|---|
| `OP_VAULT` | the agent's 1Password vault (name or id) |
| `OP_ACCOUNT` | the 1Password account, when several are signed in |
| `OP_SA_KEYCHAIN_SERVICE` | Keychain item name that holds the service-account token |
| `PASS_LOGIN_ITEM` | item in `OP_VAULT` with the Proton login used to sign pass-cli in |
| `PASS_VAULT` | Proton Pass vault for aliases (default `Personal`) |
| `ALIAS_PREFIX`, `ALIAS_DOMAIN` | alias prefix and the expected domain |
| `BROWSER_PROFILE` | Chrome profile for the browser agent (jadlis-browser) |
| `MAIL_ACCOUNT`, `MAIL_FOLDER` | mailbox and folder that receive verification mail (jadlis-mail) |
| `SIGNUP_NAME` | name for sign-up forms (jadlis-signup) |
| `ALLOW_OAUTH` | "Continue with Google" sign-in: `no` means a human does it |

The scripts read the file from `JADLIS_AGENT_CONF`, otherwise from `~/.config/jadlis/agent.conf`.
Without the file they print a clear error and exit with code 78.

## Limits

- macOS only: the token lives in the macOS Keychain.
- The service account sees only its own vault and cannot create vaults. The agent reads other
  vaults through plain `op` with Touch ID, and only by an exact reference from the human.
- Creating the service account, putting the token into the Keychain and signing in to Proton are
  the human's steps. The token and the Proton password must not pass through Claude.
- pass-cli cannot choose the alias domain: it uses the default from the Proton Pass settings. Some
  services reject alias domains.
- Some pass-cli builds cannot sign in without a browser. Then the script asks you to run
  `pass-cli login` once by hand.
- The plugin does not pay, bind cards or pass phone verification.
