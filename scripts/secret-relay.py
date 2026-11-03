#!/usr/bin/env python3
"""secret-relay.py — move one secret between Bash and a browser page without the clipboard, a file or the model context.
Part of the jadlis-secrets plugin. Python 3.9+, standard library only.

serve   — a one-shot server on a random 127.0.0.1 port hands the secret to ONE GET of a random path, then exits
          (or exits after --timeout seconds). Prints {"ok", "url", "pid", "timeout", "length"} — never the value.
          Where the secret comes from (pick one):
            secret-relay.py serve --op 'op://<vault-id>/<item-id>/password'   # read via op-agent.sh (no Touch ID)
            secret-relay.py serve --otp <item-id>                             # current TOTP code via op-agent.sh
            <command> | secret-relay.py serve                                 # stdin
            secret-relay.py serve --literal relay-selftest                    # TESTS ONLY: argv is visible in ps
          In browser_run_code_unsafe (page.request runs in the MCP server process; the page JS never sees it):
            const loc = page.locator(SEL); await loc.waitFor({ state: 'visible', timeout: 15000 });  // before the GET
            const r = await page.request.get(URL); if (r.status() !== 200) return 'relay ' + r.status();
            const v = await r.text();
            try { await loc.fill(v, { timeout: 10000 }); }   // a failed fill prints the value in its error text
            catch (e) { return 'fill failed: ' + String(e.message).split(v).join('<redacted>').slice(0, 300); }
            return v.length;
receive — a one-shot server takes ONE POST of a value to a random path and runs the command after `--` with
          every `{}` argument replaced by the value; answers the POST with {"rc", "length"} only.
            secret-relay.py receive -- security add-generic-password -s <service> -a "$USER" -w {} -U
            secret-relay.py receive -- ~/.claude/scripts/op-agent.sh item edit <item-id> 'credential={}'
          In browser_run_code_unsafe: const v = await page.locator(SEL).inputValue();
            return await (await page.request.post(URL, { data: v })).json();   // {rc, length}
Options: --timeout S (default 120 for serve, 300 for receive). Each call gets its own port and path; nothing is
written to disk. A stuck relay: kill <pid>.
"""
import http.server
import json
import os
import secrets
import socket
import subprocess
import sys
import threading


def usage(code=64):
    (sys.stdout if code == 0 else sys.stderr).write(__doc__)
    sys.exit(code)


def fail(msg, code=2):
    print(json.dumps({'ok': False, 'error': msg}))
    sys.exit(code)


def op_agent():
    here = os.path.dirname(os.path.realpath(__file__))
    for cand in (os.path.join(here, 'op-agent.sh'), os.path.expanduser('~/.claude/scripts/op-agent.sh')):
        if os.access(cand, os.X_OK):
            return cand
    fail('op-agent.sh not found next to secret-relay.py or in ~/.claude/scripts')


def read_via_op(op_args):
    try:
        r = subprocess.run([op_agent()] + op_args, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        fail('op-agent.sh timed out (a Touch ID prompt may be waiting)')
    if r.returncode != 0:
        fail('op-agent.sh failed rc=%d: %s' % (r.returncode, (r.stderr or '').strip()[:200]))
    return r.stdout


args = sys.argv[1:]
if args[:1] in (['-h'], ['--help']):
    usage(0)
if not args or args[0] not in ('serve', 'receive'):
    usage()
mode = args.pop(0)
timeout = 120 if mode == 'serve' else 300
source = None
cmd = None
while args:
    a = args[0]
    if a == '--timeout' and len(args) > 1:
        timeout = int(args[1]); args = args[2:]
    elif mode == 'serve' and a in ('--op', '--otp', '--literal') and len(args) > 1:
        if source:
            usage()
        source = (a, args[1]); args = args[2:]
    elif mode == 'receive' and a == '--':
        cmd = args[1:]; args = []
    else:
        usage()

if mode == 'receive':
    if not cmd:
        usage()
    if not any('{}' in a for a in cmd):
        sys.stderr.write('receive: the command needs a {} placeholder\n'); sys.exit(64)
    value = None
else:
    if source is None:
        raw = sys.stdin.read()
    elif source[0] == '--op':
        raw = read_via_op(['read', source[1]])
    elif source[0] == '--otp':
        raw = read_via_op(['item', 'get', source[1], '--otp'])
    else:
        raw = source[1]
    value = raw.rstrip('\r\n')
    if not value:
        fail('empty secret')

token = secrets.token_urlsafe(18)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('127.0.0.1', 0))  # loopback only, random free port
sock.listen(4)
port = sock.getsockname()[1]
url = 'http://127.0.0.1:%d/%s' % (port, token)

pid = os.fork()
if pid:
    out = {'ok': True, 'url': url, 'pid': pid, 'timeout': timeout}
    if value is not None:
        out['length'] = len(value)
    print(json.dumps(out))
    sys.stdout.flush()
    os._exit(0)

# child: detach and serve once
os.setsid()
devnull = os.open(os.devnull, os.O_RDWR)
for fd in (0, 1, 2):
    os.dup2(devnull, fd)
done = threading.Event()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        b = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if mode != 'serve' or self.path != '/' + token or done.is_set():
            return self._send(404, '{}')
        done.set()
        self._send(200, value, 'text/plain; charset=utf-8')

    def do_POST(self):
        if mode != 'receive' or self.path != '/' + token or done.is_set():
            return self._send(404, '{}')
        v = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode().rstrip('\r\n')
        if not v:
            return self._send(400, json.dumps({'rc': None, 'length': 0, 'error': 'empty value'}))
        done.set()
        try:
            r = subprocess.run([a.replace('{}', v) for a in cmd], capture_output=True, text=True, timeout=60)
            err = (r.stderr or '').replace(v, '<redacted>')[:200]
            body = {'rc': r.returncode, 'length': len(v)}
            if r.returncode:
                body['stderr'] = err
            self._send(200, json.dumps(body))
        except Exception as e:  # noqa: BLE001 — report any failure without the value
            self._send(200, json.dumps({'rc': None, 'length': len(v), 'error': str(e).replace(v, '<redacted>')[:200]}))


srv = http.server.HTTPServer(('127.0.0.1', port), Handler, bind_and_activate=False)
srv.socket = sock
threading.Thread(target=srv.serve_forever, daemon=True).start()
done.wait(timeout)
srv.shutdown()
os._exit(0)
