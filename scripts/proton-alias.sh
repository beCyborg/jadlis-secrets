#!/bin/zsh
# proton-alias.sh — Proton Pass hide-my-email aliases for sign-ups, named <ALIAS_PREFIX>-<service-slug>.
# Part of the jadlis-secrets plugin. Settings: ~/.config/jadlis/agent.conf (override the path with JADLIS_AGENT_CONF):
#   ALIAS_PREFIX     alias prefix (default agent) -> <prefix>-<slug>.<random suffix>@<domain>
#   ALIAS_DOMAIN     optional; the domain the alias should end with. pass-cli cannot pick it: it uses the default
#                    alias domain set in Proton Pass. A different result is reported as a warning.
#   PASS_VAULT       Proton Pass vault for new aliases (default Personal)
#   PASS_LOGIN_ITEM  1Password item (in OP_VAULT) with the Proton login; used only when pass-cli is signed out
#   OP_VAULT         1Password vault of PASS_LOGIN_ITEM (read through op-agent.sh)
#
# Usage: proton-alias.sh create <service-slug> [--dry-run]   -> {"id", "alias", ...}; --dry-run creates nothing
#        proton-alias.sh list [--all]                          -> active aliases with ALIAS_PREFIX (--all: every alias)
#        proton-alias.sh trash <item-id>                       -> move an alias item to trash (disables the alias)
#        proton-alias.sh --help
set -euo pipefail

me=${0:t}
self=${0:A}
here=${self:h}
conf=${JADLIS_AGENT_CONF:-$HOME/.config/jadlis/agent.conf}

usage() { sed -n '2,14p' "$self" | sed 's/^# \{0,1\}//'; }

load_conf() {
  setopt local_options extended_glob
  if [[ ! -r $conf ]]; then
    print -u2 "$me: config not found: $conf"
    print -u2 "$me: copy agent.conf.example from the jadlis-secrets plugin there and fill ALIAS_PREFIX and PASS_LOGIN_ITEM."
    exit 78
  fi
  local line key val
  local -a known=(OP_VAULT ALIAS_PREFIX ALIAS_DOMAIN PASS_VAULT PASS_LOGIN_ITEM)
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line =~ '^[[:space:]]*([A-Z_][A-Z0-9_]*)=(.*)$' ]] || continue
    key=$match[1]; val=$match[2]
    (( ${known[(Ie)$key]} )) || continue
    if [[ $val =~ '^"([^"]*)"' || $val =~ "^'([^']*)'" ]]; then
      val=$match[1]
    else
      val=${val%%[[:space:]]\#*}
      val=${val%%[[:space:]]#}
    fi
    typeset -g "$key=$val"
  done < $conf
}

op_agent() {
  local a
  for a in "$here/op-agent.sh" "$HOME/.claude/scripts/op-agent.sh"; do
    [[ -x $a ]] && { print -r -- $a; return; }
  done
  print -u2 "$me: op-agent.sh not found next to this script or in ~/.claude/scripts"; exit 69
}

signed_in() { pass-cli info >/dev/null 2>&1; }

# Sign pass-cli in as the Proton user with the login stored in 1Password. Values go only to files in a private
# temp dir that lives for the one login call; nothing is printed.
relogin() {
  if [[ -z ${PASS_LOGIN_ITEM:-} ]]; then
    print -u2 "$me: pass-cli is signed out and PASS_LOGIN_ITEM is empty — run 'pass-cli login' yourself once"; exit 77
  fi
  if ! pass-cli login --help 2>&1 | grep -q -- '--interactive'; then
    print -u2 "$me: this pass-cli build has no headless login (--interactive); run 'pass-cli login' yourself once"; exit 77
  fi
  local A user rc=0
  local -a totp_env=()
  A=$(op_agent)
  user=$("$A" item get "$PASS_LOGIN_ITEM" --vault "$OP_VAULT" --fields label=username 2>/dev/null) || {
    print -u2 "$me: cannot read the username of 1Password item PASS_LOGIN_ITEM in OP_VAULT"; exit 77; }
  login_dir=$(mktemp -d); chmod 700 "$login_dir"
  trap 'rm -rf "$login_dir"' EXIT
  "$A" item get "$PASS_LOGIN_ITEM" --vault "$OP_VAULT" --fields label=password --reveal | tr -d '\n' > "$login_dir/pw"
  if "$A" item get "$PASS_LOGIN_ITEM" --vault "$OP_VAULT" --otp 2>/dev/null | tr -d '\n' > "$login_dir/totp" \
     && [[ -s $login_dir/totp ]]; then
    totp_env=(PROTON_PASS_TOTP_FILE="$login_dir/totp")
  fi
  env PROTON_PASS_PASSWORD_FILE="$login_dir/pw" "${totp_env[@]}" \
    pass-cli login --interactive "$user" </dev/null >/dev/null 2>&1 || rc=$?
  rm -rf "$login_dir"
  (( rc == 0 )) && signed_in || { print -u2 "$me: pass-cli login failed (rc=$rc); a TOTP code works once per 30 s — retry after it changes"; exit 77; }
}

ensure_session() { signed_in || relogin; }

cmd=${1:-}
case $cmd in
  -h|--help|help) usage; exit 0 ;;
  create|list|trash) shift ;;
  *) usage >&2; exit 64 ;;
esac

load_conf
command -v pass-cli >/dev/null || { print -u2 "$me: pass-cli is not installed — brew install proton-pass-cli"; exit 127; }
prefix_base=${ALIAS_PREFIX:-agent}
vault=${PASS_VAULT:-Personal}

case $cmd in
  create)
    slug=${1:-}; dry=0
    [[ ${2:-} == --dry-run || ${1:-} == --dry-run ]] && dry=1
    [[ $slug == --dry-run ]] && slug=${2:-}
    if [[ ! $slug =~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$' ]]; then
      print -u2 "$me: service slug must be lowercase letters, digits and inner dashes (e.g. notion, shop-example)"; exit 64
    fi
    prefix="$prefix_base-$slug"
    if (( dry )); then
      si=false; signed_in && si=true
      printf '{"dry_run":true,"prefix":"%s","vault":"%s","alias_domain":"%s","signed_in":%s,"would_sign_in":%s}\n' \
        "$prefix" "$vault" "${ALIAS_DOMAIN:-}" "$si" "$([[ $si == true ]] && print false || print true)"
      exit 0
    fi
    ensure_session
    out=$(pass-cli item alias create --vault-name "$vault" --prefix "$prefix" --output json)
    ALIAS_DOMAIN=${ALIAS_DOMAIN:-} python3 -c '
import json, os, sys
d = json.loads(sys.stdin.read())
alias = d.get("alias_email") or d.get("alias") or d.get("email") or ""
out = {"id": d.get("id") or d.get("item_id"), "alias": alias}
dom = os.environ.get("ALIAS_DOMAIN", "").lstrip("@")
if dom and alias and not alias.endswith("@" + dom) and not alias.endswith("." + dom):
    out["warning"] = "alias domain differs from ALIAS_DOMAIN; set the default alias domain in Proton Pass settings"
print(json.dumps(out if alias else d))' <<< "$out"
    ;;
  list)
    all=0; [[ ${1:-} == --all ]] && all=1
    ensure_session
    pass-cli item list --vault-name "$vault" --filter-type alias --filter-state active --output json --show-secrets |
      PREFIX="$prefix_base-" ALL=$all python3 -c '
import json, os, sys
items = json.load(sys.stdin).get("items", [])
p, show_all = os.environ["PREFIX"], os.environ["ALL"] == "1"
rows = [{"id": i.get("id"), "alias": i.get("alias_email", ""), "title": (i.get("content") or {}).get("title", "")}
        for i in items if show_all or i.get("alias_email", "").startswith(p)]
print(json.dumps(rows, ensure_ascii=False, indent=1))'
    ;;
  trash)
    id=${1:?item id (from: proton-alias.sh list)}
    ensure_session
    pass-cli item trash --vault-name "$vault" --item-id "$id"
    ;;
esac
