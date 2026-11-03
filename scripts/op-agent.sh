#!/bin/zsh
# op-agent.sh — run the 1Password CLI (op) as the agent's service account, so no Touch ID prompt appears.
# Part of the jadlis-secrets plugin. Settings: ~/.config/jadlis/agent.conf (override the path with JADLIS_AGENT_CONF).
#   OP_SA_KEYCHAIN_SERVICE  Keychain item (service) with the service-account token; Keychain account = $USER
#   OP_ACCOUNT              optional; passed as --account when set and the call has no --account of its own
#   OP_VAULT                not used here; callers pass --vault "$OP_VAULT" themselves
# No token in the Keychain -> falls back to plain `op` (the 1Password app asks for Touch ID) with a note on stderr.
#
# Usage: op-agent.sh <op arguments…>
#        op-agent.sh item list --vault "$OP_VAULT"
#        op-agent.sh read "op://<vault-id>/<item-id>/password" | <consumer>   # pipe it, never print it
#        op-agent.sh --check     # config path, vault, whether the token is in the Keychain (never the token)
#        op-agent.sh --get OP_VAULT   # print one config value (OP_VAULT, OP_ACCOUNT, OP_SA_KEYCHAIN_SERVICE)
set -euo pipefail

me=${0:t}
conf=${JADLIS_AGENT_CONF:-$HOME/.config/jadlis/agent.conf}

load_conf() {
  setopt local_options extended_glob
  if [[ ! -r $conf ]]; then
    print -u2 "$me: config not found: $conf"
    print -u2 "$me: copy agent.conf.example from the jadlis-secrets plugin there and fill OP_VAULT and OP_SA_KEYCHAIN_SERVICE."
    exit 78
  fi
  local line key val
  local -a known=(OP_VAULT OP_ACCOUNT OP_SA_KEYCHAIN_SERVICE)
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

load_conf
if [[ ${1:-} == --get ]]; then
  case ${2:-} in
    OP_VAULT|OP_ACCOUNT|OP_SA_KEYCHAIN_SERVICE) print -r -- "${(P)2:-}"; exit 0 ;;
    *) print -u2 "$me: --get takes OP_VAULT, OP_ACCOUNT or OP_SA_KEYCHAIN_SERVICE"; exit 64 ;;
  esac
fi
svc=${OP_SA_KEYCHAIN_SERVICE:-op-service-account-agent}
tok=$(security find-generic-password -s "$svc" -a "$USER" -w 2>/dev/null || true)

if [[ ${1:-} == --check ]]; then
  print "config:   $conf"
  print "vault:    ${OP_VAULT:-<empty>}"
  print "account:  ${OP_ACCOUNT:-<not set>}"
  print "keychain: service=$svc account=$USER token=$([[ -n $tok ]] && print found || print MISSING)"
  print "op:       $(command -v op >/dev/null && op --version || print 'not installed')"
  [[ -n $tok ]]; exit
fi

if (( $# == 0 )) || [[ $1 == -h || $1 == --help ]]; then
  sed -n '2,13p' "${0:A}" | sed 's/^# \{0,1\}//'
  (( $# == 0 )) && exit 64 || exit 0
fi

command -v op >/dev/null || { print -u2 "$me: 1Password CLI (op) is not installed — brew install --cask 1password-cli"; exit 127; }

args=("$@")
if [[ -n ${OP_ACCOUNT:-} && ${args[(I)--account*]} -eq 0 ]]; then
  args=(--account "$OP_ACCOUNT" "${args[@]}")
fi

if [[ -z $tok ]]; then
  print -u2 "$me: no service-account token in Keychain (service $svc, account $USER); falling back to plain op — expect a Touch ID prompt"
  exec op "${args[@]}"
fi
OP_SERVICE_ACCOUNT_TOKEN="$tok" exec op "${args[@]}"
