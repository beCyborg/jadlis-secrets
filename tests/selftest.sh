#!/bin/zsh
# Offline self-test for the jadlis-secrets scripts: syntax, config parser, relay one-shot behaviour, alias CLI guards.
# Reads no secret and creates nothing. Run from the repo root: zsh tests/selftest.sh
set -uo pipefail
root=${0:A:h:h}; s=$root/scripts; fails=0
ok()   { print "ok   $1"; }
bad()  { print "FAIL $1"; (( fails++ )); }
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT

for f in $s/*.sh; do zsh -n $f && ok "zsh -n ${f:t}" || bad "zsh -n ${f:t}"; done
python3 -m py_compile $s/secret-relay.py && ok "py_compile secret-relay.py" || bad "py_compile"
rm -rf $s/__pycache__

cat > $t/agent.conf <<'CONF'
# comment
OP_VAULT="Agent Vault"
OP_ACCOUNT='acct-1'   # trailing comment
OP_SA_KEYCHAIN_SERVICE=jadlis-selftest-missing-service # comment
PATH="/should/be/ignored"
CONF
export JADLIS_AGENT_CONF=$t/agent.conf
[[ $($s/op-agent.sh --get OP_VAULT) == "Agent Vault" ]] && ok "parser: double quotes with spaces" || bad "parser: double quotes"
[[ $($s/op-agent.sh --get OP_ACCOUNT) == "acct-1" ]] && ok "parser: single quotes + comment" || bad "parser: single quotes"
[[ $($s/op-agent.sh --get OP_SA_KEYCHAIN_SERVICE) == "jadlis-selftest-missing-service" ]] && ok "parser: bare value + comment" || bad "parser: bare value"
$s/op-agent.sh --check >/dev/null; [[ $? == 1 ]] && ok "--check reports a missing token" || bad "--check"
JADLIS_AGENT_CONF=$t/none $s/op-agent.sh --get OP_VAULT 2>/dev/null; [[ $? == 78 ]] && ok "missing config -> exit 78" || bad "missing config"

out=$($s/secret-relay.py serve --literal relay-selftest --timeout 20)
url=$(print -r -- $out | python3 -c 'import json,sys;print(json.load(sys.stdin)["url"])')
[[ $url == http://127.0.0.1:* ]] && ok "relay binds 127.0.0.1" || bad "relay url $url"
[[ $out != *relay-selftest* ]] && ok "relay output has no value" || bad "relay leaked the value"
[[ $(curl -s $url) == relay-selftest ]] && ok "relay first GET serves the value" || bad "relay first GET"
sleep 1
curl -s -m 3 $url >/dev/null; [[ $? != 0 ]] && ok "relay second GET refused (process exited)" || bad "relay second GET"
o2=$($s/secret-relay.py receive --timeout 20 -- sh -c 'test "$1" = typed' _ {})
u2=$(print -r -- $o2 | python3 -c 'import json,sys;print(json.load(sys.stdin)["url"])')
[[ $(curl -s -X POST --data typed $u2) == '{"rc": 0, "length": 5}' ]] && ok "relay receive runs the command" || bad "relay receive"

$s/proton-alias.sh --help >/dev/null && ok "proton-alias --help" || bad "proton-alias --help"
$s/proton-alias.sh create Bad_Slug --dry-run 2>/dev/null; [[ $? == 64 ]] && ok "proton-alias rejects a bad slug" || bad "slug guard"
if command -v pass-cli >/dev/null; then
  d=$($s/proton-alias.sh create selftest --dry-run)
  [[ $d == *'"dry_run":true'*'"prefix":"agent-selftest"'* ]] && ok "proton-alias dry-run creates nothing" || bad "dry-run: $d"
fi
print; (( fails == 0 )) && print "all passed" || { print "$fails failed"; exit 1; }
