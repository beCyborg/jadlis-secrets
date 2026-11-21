# Changelog — jadlis-secrets

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Для человека

- Агент сохраняет каждый секрет в подходящую категорию 1Password: логин — в «Логин», ключ API — в «API Credential», карту — в «Банковская карта», сервер — в «Сервер». Значения попадают во встроенные поля категории, а не в текст заметки.
- Новый скрипт `op-item.py` записывает значения через временный файл с правами 0600 и никогда не передаёт их в аргументах команды.

### Technical

- Added `scripts/op-item.py`: create/edit by category template, built-in fields first, custom fields only in a named section, secrets from stdin/clipboard/env/file, `--dry-run`, metadata-only output; SSH Key generation without a template (op 2.42 refuses `--template` for SSH keys).
- `secret-relay.py receive --stdin`: hands the value to the command's stdin instead of a `{}` argument.
- `skills/secrets/SKILL.md`: category table; token recipes use `op-item.py`.

## [1.0.0] — 2026-11-03 — Первый выпуск / First release

### Для человека

- Скилл `/jadlis-secrets:secrets`: все доступы агента лежат в одном хранилище 1Password, агент читает их через сервисный аккаунт без Touch ID.
- Пароль не попадает в контекст модели: в веб-форму его передаёт одноразовый локальный адрес, в приложение — слепой буфер обмена.
- Рецепты: логин со сгенерированным паролем из 20 символов, сохранить выданный токен, сменить пароль или токен сервисного аккаунта.
- Алиасы Proton Pass для регистраций: создать (с пробным запуском), показать список, отключить.
- Общий файл настроек `~/.config/jadlis/agent.conf` для плагинов secrets, signup, mail и browser; образец — `agent.conf.example`.

### For agents

- Added: `skills/secrets/SKILL.md` — contract (one vault, ids, no secret in context), commands, generated-password login, token save via stdin JSON template (`op item create -`), rotation, install step, aliases, gotchas; `references/blind-clipboard.md` for desktop-operator.
- Added: `scripts/op-agent.sh` — injects the service-account token from Keychain `OP_SA_KEYCHAIN_SERVICE` / `$USER` into one `op` call; adds `--account $OP_ACCOUNT` when set; falls back to plain `op` (Touch ID) with a stderr note; `--check`, `--get KEY`; exit 78 when the config is missing.
- Added: `scripts/secret-relay.py` (stdlib, Python 3.9+) — `serve` (stdin, `--op REF`, `--otp ITEM`, `--literal` for tests) and `receive -- cmd {}`; one request, 127.0.0.1 only, random port and path, `--timeout`.
- Added: `scripts/proton-alias.sh` — `create <slug> [--dry-run]` → JSON with `id` and `alias`, `list [--all]`, `trash <id>`, `--help`; signs pass-cli in from `PASS_LOGIN_ITEM` via `login --interactive` when that flag exists.
- Added: `agent.conf.example` — every key of the shared contract plus optional `PASS_VAULT`; all values double-quoted; scripts parse the file (allow-listed keys, no `source`).
- Added: `tests/selftest.sh` — offline checks (syntax, parser, relay one-shot, alias guards).
