#!/usr/bin/env python3
"""`mi api` pour TypeScript : surface publique seule, corps jetes, types
internes atteignables conserves. Compare a la strategie head/tail de dsh."""
import re, glob, os

THRESHOLD, HEAD, TAIL = 8192, 4096, 1024
MARKER = "\n\n[... tool result middle pruned ...]\n\n"
def dsh_prune(s):
    return s if len(s) <= THRESHOLD else s[:HEAD] + MARKER + s[-TAIL:]

DECL = re.compile(r'^(export\s+)?(default\s+)?(declare\s+)?(abstract\s+)?(async\s+)?'
                  r'(class|interface|namespace|enum|type|function|const|let|var)\s+'
                  r'([A-Za-z_$][\w$]*)')
DESCEND = re.compile(r'^\s*(export\s+)?(default\s+)?(declare\s+)?(abstract\s+)?'
                     r'(class|interface|namespace|enum)\b')
KEEPVAL = re.compile(r'^\s*(export\s+)?(declare\s+)?(const|let|var|type)\b')

def strip_bodies(lines):
    """Garde les signatures, jette les corps de fonctions et de methodes."""
    out, depth, skip = [], 0, None
    for ln in lines:
        o, c = ln.count('{'), ln.count('}')
        if skip is not None:
            depth += o - c
            if depth <= skip: skip = None
            continue
        net = o - c
        if net > 0 and not (DESCEND.match(ln) or KEEPVAL.match(ln)):
            out.append(re.sub(r'\s*\{\s*$', '', ln.rstrip()))
            skip = depth; depth += net; continue
        out.append(ln); depth += net
    return out

def chunks(src):
    """Decoupe le fichier en blocs de premier niveau, commentaires attaches."""
    lines, res, buf, depth, pending = src.split('\n'), [], [], 0, []
    for ln in lines:
        s = ln.strip()
        if depth == 0 and not buf and (s.startswith('//') or s.startswith('/*')
                                       or s.startswith('*') or s == ''):
            pending.append(ln); continue
        buf.append(ln)
        depth += ln.count('{') - ln.count('}')
        if depth <= 0 and buf:
            txt = '\n'.join(buf)
            if txt.strip():
                res.append((pending, buf))
            buf, pending, depth = [], [], 0
    if buf: res.append((pending, buf))
    return res

def api_digest(src, keep_doc=False):
    imports, kept, internal = [], [], []
    for pending, body in chunks(src):
        head = body[0].lstrip()
        if head.startswith('import ') or head.startswith('export * ') or head.startswith("import{"):
            m = re.search(r"from\s+'([^']+)'", '\n'.join(body))
            if m: imports.append(m.group(1).split('/')[-1])
            continue
        m = DECL.match(head)
        sig = '\n'.join(strip_bodies(body))
        doc = '\n'.join(l for l in pending if l.strip().startswith(('/**','*','*/'))) if keep_doc else ''
        entry = ((doc + '\n' if doc.strip() else '') + sig, m.group(7) if m else None)
        if head.startswith('export'):
            kept.append(entry)
        elif m and m.group(6) in ('type', 'interface', 'enum'):
            internal.append(entry)
        # le reste (helpers internes, constantes privees) est jete

    # types internes atteignables depuis la surface publique
    text = '\n'.join(t for t, _ in kept)
    changed = True
    while changed:
        changed = False
        for e in internal[:]:
            t, name = e
            if name and re.search(r'\b%s\b' % re.escape(name), text):
                kept.append(e); internal.remove(e); text += '\n' + t; changed = True

    out = []
    if imports:
        out.append('// imports: ' + ', '.join(sorted(set(imports))))
    out += [t for t, _ in kept]
    return re.sub(r'\n{3,}', '\n\n', '\n\n'.join(out)).strip() + '\n'

SYM = re.compile(r'^export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?'
                 r'(?:async\s+)?(?:class|interface|type|enum|function|const|let|var)\s+'
                 r'([A-Za-z_$][\w$]*)', re.M)

rows, T = [], [0]*7
for path in sorted(glob.glob('dsh-sample/*.ts')):
    src = open(path, encoding='utf-8').read()
    if len(src) <= THRESHOLD: continue
    p, d, dd = dsh_prune(src), api_digest(src), api_digest(src, keep_doc=True)
    syms = set(SYM.findall(src))
    kp = sum(1 for s in syms if re.search(r'\b%s\b' % re.escape(s), p))
    kd = sum(1 for s in syms if re.search(r'\b%s\b' % re.escape(s), d))
    r = (os.path.basename(path).replace('core_','').replace('_src_','/'),
         len(src), len(p), len(d), len(dd), len(syms), kp, kd)
    rows.append(r)
    for i,v in enumerate(r[1:]): T[i]+=v

print(f"{'fichier':<24}{'source':>9}{'head/tail':>10}{'digest':>8}{'+doc':>8}{' sym':>5}{' h/t':>5}{' dig':>5}")
print('-'*76)
for r in rows: print(f"{r[0]:<24}{r[1]:>9,}{r[2]:>10,}{r[3]:>8,}{r[4]:>8,}{r[5]:>5}{r[6]:>5}{r[7]:>5}")
print('-'*76)
print(f"{'TOTAL':<24}{T[0]:>9,}{T[1]:>10,}{T[2]:>8,}{T[3]:>8,}{T[4]:>5}{T[5]:>5}{T[6]:>5}")
print()
print(f"head/tail   : {T[1]/T[0]*100:5.1f} % des caracteres · {T[5]/T[4]*100:5.1f} % des symboles publics")
print(f"digest      : {T[2]/T[0]*100:5.1f} % des caracteres · {T[6]/T[4]*100:5.1f} % des symboles publics")
print(f"digest +doc : {T[3]/T[0]*100:5.1f} % des caracteres · {T[6]/T[4]*100:5.1f} % des symboles publics")
