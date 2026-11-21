#!/usr/bin/env python3
"""op-item.py — create or edit a 1Password item in the right category, with values in the category's
built-in fields, and never put a value on op's command line.

Values go into a JSON template file (mode 0600, inside a private 0700 temp dir) that op reads with
--template; the file is deleted right after. Secret values come from stdin, the clipboard, an env var
or a file — never from argv. Output is item metadata only: field ids, labels, types, sections and
whether a value is set. Python 3.9+, standard library only. Part of the jadlis-secrets plugin.

  op-item.py fields <category>                       # built-in fields of a category (local, no sign-in)
  op-item.py create --category <cat> --title <t> --vault <vault-id> [options]
  op-item.py edit <item-id> --vault <vault-id> [options]

Options:
  --op <cmd>             op binary or wrapper (default: op). E.g. ~/.claude/scripts/op-agent.sh
  --account <id>         pass --account to op (the human's own session, when several accounts are signed in)
  --set SPEC=VALUE       a NON-secret value (username, URL, hostname, date, notes). Repeatable.
  --secret SPEC=SOURCE   a secret; SOURCE = stdin | clipboard | env:NAME | file:PATH. Repeatable (stdin once).
  --url URL              website for autofill (Login, Password, API Credential); repeatable, first is primary
  --tags a,b             tags (create: set; edit: replace)
  --generate-password[=RECIPE]   let 1Password generate the password (Login, Password)
  --ssh-generate-key[=ed25519|rsa2048|rsa3072|rsa4096]  let 1Password generate an SSH key (SSH Key)
  --dry-run              op previews the item and saves nothing
  --allow-unsectioned    allow a custom field outside a section (default: refuse)

SPEC follows op's assignment syntax: [<section>.]<field>[[<type>]]
  built-in field: its id or label from `op-item.py fields <category>`, no type: username, credential, ccnum
  custom field:   section and type are required: 'Backblaze B2.bucket[text]', 'Billing.renews[date]'
  types: text, password|concealed, email, url, date (YYYY-MM-DD), monthYear (YYYYMM), phone, otp (otpauth:// URI)
  escape '.', '=', '[' or '\\' in a section or field name with a backslash.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TYPES = {
    'text': 'STRING', 'string': 'STRING',
    'password': 'CONCEALED', 'concealed': 'CONCEALED',
    'email': 'EMAIL', 'url': 'URL', 'date': 'DATE',
    'monthyear': 'MONTH_YEAR', 'month_year': 'MONTH_YEAR',
    'phone': 'PHONE', 'otp': 'OTP', 'totp': 'OTP',
}
KNOWN_FIELD_TYPES = {
    'STRING', 'CONCEALED', 'EMAIL', 'URL', 'DATE', 'MONTH_YEAR', 'PHONE', 'OTP', 'MENU',
    'CREDIT_CARD_TYPE', 'CREDIT_CARD_NUMBER', 'SSHKEY', 'ADDRESS', 'GENDER', 'REFERENCE',
}
SECRETS = []  # every secret value read, for redaction


def die(msg, code=2):
    for s in sorted(SECRETS, key=len, reverse=True):
        if len(s) >= 4:  # a 1–3 char value would mangle the message and is no real secret
            msg = msg.replace(s, '<redacted>')
    print(json.dumps({'ok': False, 'error': msg[:600]}, ensure_ascii=False))
    sys.exit(code)


def run(cmd, stdin=None):
    try:
        # op refuses `--template` while its stdin is a pipe, so a child never inherits our stdin
        if stdin is None:
            return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
        return subprocess.run(cmd, capture_output=True, text=True, input=stdin, timeout=90)
    except FileNotFoundError:
        die('not found: %s' % cmd[0])
    except subprocess.TimeoutExpired:
        die('%s timed out (a Touch ID prompt may be waiting)' % cmd[0])


def split_unescaped(s, ch):
    """Split at the first unescaped ch; return (head, tail or None). Unescapes the head."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            out.append(s[i + 1]); i += 2; continue
        if c == ch:
            return ''.join(out), s[i + 1:]
        out.append(c); i += 1
    return ''.join(out), None


def parse_spec(arg):
    """'[section.]field[type]=value' → (section, field, type, value). Escapes as in op."""
    # find the first unescaped '='
    i, esc = 0, False
    while i < len(arg):
        if esc:
            esc = False
        elif arg[i] == '\\':
            esc = True
        elif arg[i] == '=':
            break
        i += 1
    if i >= len(arg):
        die('expected SPEC=VALUE, got no "=" in a spec (value not shown)')
    spec, value = arg[:i], arg[i + 1:]
    ftype = None
    m = re.search(r'(?<!\\)\[([A-Za-z_]+)\]$', spec)
    if m:
        ftype = m.group(1).lower()
        spec = spec[:m.start()]
        if ftype not in TYPES:
            die('unknown field type [%s]; use one of: %s' % (ftype, ', '.join(sorted(set(TYPES)))))
    head, tail = split_unescaped(spec, '.')
    if tail is None:
        section, field = None, head
    else:
        section, field = head, split_unescaped(tail, '\0')[0]
    if not field:
        die('empty field name in a spec')
    return section, field, ftype, value


def read_secret(source, used_stdin):
    if source == 'stdin':
        if used_stdin[0]:
            die('only one --secret can read stdin')
        used_stdin[0] = True
        v = sys.stdin.read()
    elif source == 'clipboard':
        v = run(['pbpaste']).stdout
    elif source.startswith('env:'):
        v = os.environ.get(source[4:], '')
    elif source.startswith('file:'):
        try:
            with open(os.path.expanduser(source[5:]), encoding='utf-8') as fh:
                v = fh.read()
        except OSError as e:
            die('cannot read secret file: %s' % e.strerror)
    else:
        die('secret SOURCE must be stdin | clipboard | env:NAME | file:PATH')
    v = v.rstrip('\r\n')
    if not v:
        die('empty secret from %s' % source.split(':')[0])
    SECRETS.append(v)
    return v


def categories():
    r = run(['op', 'item', 'template', 'list', '--format', 'json'])
    if r.returncode:
        die('op item template list failed: ' + r.stderr.strip())
    return [c['name'] for c in json.loads(r.stdout)]


def resolve_category(name):
    norm = lambda s: re.sub(r'[^a-z]', '', s.lower())
    for c in categories():
        if norm(c) == norm(name):
            return c
    die('unknown category %r; see `op item template list`' % name)


def template(category):
    r = run(['op', 'item', 'template', 'get', category, '--format', 'json'])
    if r.returncode:
        die('op item template get failed: ' + r.stderr.strip())
    return json.loads(r.stdout)


def sec_label(item, sec_id):
    for s in item.get('sections') or []:
        if s.get('id') == sec_id:
            return s.get('label') or sec_id
    return sec_id


def find_builtin(item, section, field):
    """Built-in = a field already present (template or item) matched by id or label, in the named section if any."""
    f_low = field.lower()
    for f in item.get('fields') or []:
        sid = (f.get('section') or {}).get('id')
        if section is not None:
            if sid is None or section.lower() not in (sid.lower(), sec_label(item, sid).lower()):
                continue
        if f_low in ((f.get('id') or '').lower(), (f.get('label') or '').lower()):
            return f
    return None


def ensure_section(item, label):
    for s in item.setdefault('sections', []) or []:
        if label.lower() in ((s.get('id') or '').lower(), (s.get('label') or '').lower()):
            return s['id']
    item['sections'].append({'id': label, 'label': label})
    return label


def apply(item, assigns, allow_unsectioned):
    applied = []
    for section, field, ftype, value, secret in assigns:
        f = find_builtin(item, section, field) if not ftype else None
        if f is not None:
            f['value'] = value
            sid = (f.get('section') or {}).get('id')
            applied.append({'field': f.get('label') or f.get('id'), 'builtin_or_existing': True,
                            'section': sec_label(item, sid) if sid else None, 'type': f.get('type'),
                            'secret': secret})
            continue
        if section is None and not allow_unsectioned:
            die('%r is not a built-in field of %s; a custom field needs a section and a type, '
                'e.g. "Details.%s[text]=…" (see `op-item.py fields %s`)'
                % (field, item.get('category'), field, item.get('category')))
        t = TYPES[ftype] if ftype else ('CONCEALED' if secret else 'STRING')
        nf = {'label': field, 'type': t, 'value': value}
        if section is not None:
            nf['section'] = {'id': ensure_section(item, section)}
        item.setdefault('fields', []).append(nf)
        applied.append({'field': field, 'builtin_or_existing': False, 'section': section, 'type': t,
                        'secret': secret})
    return applied


def sanitize(it):
    sec = {s.get('id'): s.get('label') for s in it.get('sections') or []}
    return {
        'id': it.get('id'), 'title': it.get('title'), 'category': it.get('category'),
        'vault': (it.get('vault') or {}).get('name') or (it.get('vault') or {}).get('id'),
        'tags': it.get('tags'), 'urls': [u.get('href') for u in it.get('urls') or []],
        'sections': [s for s in sec.values() if s],
        'fields': [{'id': f.get('id'), 'label': f.get('label'), 'type': f.get('type'),
                    'purpose': f.get('purpose'),
                    'section': sec.get((f.get('section') or {}).get('id'), (f.get('section') or {}).get('label')),
                    'set': bool(f.get('value')) and not (f.get('type') in ('DATE', 'MONTH_YEAR') and str(f.get('value')) == '0')} for f in it.get('fields') or []],
    }


def write_template(obj):
    d = tempfile.mkdtemp(prefix='op-item-')
    os.chmod(d, 0o700)
    p = os.path.join(d, 'item.json')
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False)
    return d, p


def ssh_assign_mode(op, common, opt, raw, assigns, base):
    """SSH Key items: no template. Only NON-secret values, passed as op assignment statements."""
    args, applied = [], []
    for (spec, _), (section, field, ftype, _v, _s) in zip(raw, assigns):
        if field.lower() in ('notesplain', 'notes') and section is None and base[1] == 'create':
            die('SSH Key: op ignores notes at creation; put the text in a section field '
                '("Details.note[text]=…") or add notes with an edit afterwards')
        if section is None and field.lower() not in ('notesplain', 'notes') and not opt['unsect']:
            die('%r: a custom field on an SSH Key needs a section and a type' % field)
        args.append(spec)
        applied.append({'field': field, 'section': section, 'type': TYPES.get(ftype or 'text'), 'secret': False})
    cmd = op + base + common
    if opt['tags'] is not None:
        cmd.append('--tags=' + opt['tags'])
    r = run(cmd + args)
    if r.returncode:
        die('op %s failed rc=%d: %s' % (' '.join(base[:2]), r.returncode, r.stderr.strip()))
    try:
        out = json.loads(r.stdout)
    except ValueError:
        die('op returned non-JSON output (not shown)')
    print(json.dumps({'ok': True, 'dry_run': opt['dry'], 'applied': applied, 'item': sanitize(out)},
                     ensure_ascii=False, indent=1))


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'):
        sys.stdout.write(__doc__); sys.exit(0 if a else 64)
    mode = a.pop(0)
    if mode == 'fields':
        if not a:
            die('fields <category>')
        cat = resolve_category(' '.join(a))
        t = template(cat)
        print(json.dumps({'category': cat, 'json_category': t.get('category'),
                          'fields': sanitize(t)['fields'], 'sections': sanitize(t)['sections']},
                         ensure_ascii=False, indent=1))
        return
    if mode not in ('create', 'edit'):
        die('mode must be fields | create | edit')
    opt = {'op': 'op', 'account': None, 'category': None, 'title': None, 'vault': None, 'tags': None,
           'dry': False, 'gen': None, 'ssh': None, 'unsect': False, 'item': None}
    urls, raw = [], []
    if mode == 'edit':
        if not a or a[0].startswith('--'):
            die('edit <item-id> --vault <vault-id> …')
        opt['item'] = a.pop(0)
    while a:
        k = a.pop(0)
        key, _, inline = k.partition('=')
        def val():
            if inline:
                return inline
            if not a:
                die('missing value for ' + key)
            return a.pop(0)
        if key in ('--op', '--account', '--category', '--title', '--vault', '--tags'):
            opt[key[2:]] = val()
        elif key == '--url':
            urls.append(val())
        elif key == '--set':
            raw.append((val(), False))
        elif key == '--secret':
            raw.append((val(), True))
        elif key == '--dry-run':
            opt['dry'] = True
        elif key == '--generate-password':
            opt['gen'] = inline or 'letters,digits,symbols,24'
        elif key == '--ssh-generate-key':
            opt['ssh'] = inline or 'ed25519'
        elif key == '--allow-unsectioned':
            opt['unsect'] = True
        else:
            die('unknown option ' + key)
    if not opt['vault']:
        die('--vault <vault-id> is required (never rely on the default Private vault)')
    used_stdin = [False]
    assigns = []
    for spec, secret in raw:
        section, field, ftype, value = parse_spec(spec)
        if secret:
            value = read_secret(value, used_stdin)
        assigns.append((section, field, ftype, value, secret))

    op = [os.path.expanduser(opt['op'])]
    common = ['--vault', opt['vault'], '--format', 'json']
    if opt['account']:
        common += ['--account', opt['account']]
    if opt['dry']:
        common.append('--dry-run')

    if mode == 'create':
        if not opt['category'] or not opt['title']:
            die('create needs --category and --title')
        cat = resolve_category(opt['category'])
        if cat == 'SSH Key':
            # op 2.42: `--template` is refused for SSH Key items, and a template without --category stores
            # the private key as a plain STRING. The CLI can only GENERATE a key; import goes through the app.
            if any(x[4] for x in assigns):
                die('SSH Key: the CLI cannot import an existing private key (it would land as plain text). '
                    'Generate one here with --ssh-generate-key, or import the key in the 1Password app.')
            ssh_assign_mode(op, common, opt, raw, assigns, ['item', 'create', '--category', 'SSH Key',
                            '--title', opt['title'], '--ssh-generate-key=' + (opt['ssh'] or 'ed25519')])
            return
        item = template(cat)
        item['title'] = opt['title']
        if opt['tags']:
            item['tags'] = [t.strip() for t in opt['tags'].split(',') if t.strip()]
        if urls:
            item['urls'] = [{'href': u, 'primary': i == 0} for i, u in enumerate(urls)]
        applied = apply(item, assigns, opt['unsect'])
        cmd = op + ['item', 'create'] + common
        if opt['gen']:
            cmd.append('--generate-password=' + opt['gen'])
        if opt['ssh']:
            cmd.append('--ssh-generate-key=' + opt['ssh'])
    else:
        g = run(op + ['item', 'get', opt['item'], '--vault', opt['vault'], '--format', 'json']
                + (['--account', opt['account']] if opt['account'] else []))
        if g.returncode:
            die('op item get failed: ' + g.stderr.strip())
        item = json.loads(g.stdout)
        if item.get('category') == 'SSH_KEY':
            if any(x[4] for x in assigns):
                die('SSH Key items take no template edits; change the key itself in the 1Password app.')
            ssh_assign_mode(op, common, opt, raw, assigns, ['item', 'edit', opt['item']])
            return
        for f in item.get('fields') or []:
            if f.get('value'):
                SECRETS.append(str(f['value']))
        odd = sorted({f.get('type') for f in item.get('fields') or []} - KNOWN_FIELD_TYPES)
        if odd or item.get('files'):
            die('refusing a template edit: the item has %s; a template edit could overwrite them. '
                'Edit it in the 1Password app.' % (('field types ' + ', '.join(odd)) if odd else 'file attachments'))
        if opt['tags'] is not None:
            item['tags'] = [t.strip() for t in opt['tags'].split(',') if t.strip()]
        if urls:
            item['urls'] = [{'href': u, 'primary': i == 0} for i, u in enumerate(urls)]
        applied = apply(item, assigns, opt['unsect'])
        cmd = op + ['item', 'edit', opt['item']] + common
        if opt['gen']:
            cmd.append('--generate-password=' + opt['gen'])

    d, p = write_template(item)
    try:
        r = run(cmd + ['--template=' + p])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if r.returncode:
        die('op item %s failed rc=%d: %s' % (mode, r.returncode, r.stderr.strip()))
    try:
        out = json.loads(r.stdout)
    except ValueError:
        die('op returned non-JSON output (not shown)')
    print(json.dumps({'ok': True, 'dry_run': opt['dry'], 'applied': applied, 'item': sanitize(out)},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
