#!/usr/bin/env python3
"""
Verifie que tout extrait Mira de la documentation est analysable.

Un document dont les exemples ne compilent pas est un document faux. Cet outil
extrait chaque bloc Mira des .md (```mira) et des .html (<code class="mi">),
puis l'essaie selon trois lectures, de la plus stricte a la plus permissive :

  module      le bloc est un fichier complet
  corps       le bloc est une suite d'instructions (enveloppee dans une fn)
  signatures  le bloc est une liste de signatures sans corps

Un extrait n'echoue que si aucune des trois ne passe.
"""
import sys, os, re, glob, html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mi

FENCE = re.compile(r'```mira\n(.*?)```', re.S)
TAG   = re.compile(r'<code class="mi( nocheck)?">(.*?)</code>', re.S)

ELISION = '\u2026'

def normalize(code):
    """`…` marque une elision dans la prose, pas dans le langage."""
    out = []
    for l in code.split('\n'):
        body = l.split('#')[0]
        if body.strip() == ELISION:   out.append(l.replace(ELISION, 'pass', 1))
        elif ELISION in body:         out.append(l.replace(ELISION, '0'))
        else:                         out.append(l)
    return '\n'.join(out)


def snippets(path):
    src = open(path, encoding='utf-8').read()
    if path.endswith('.md'):
        for m in FENCE.finditer(src):
            yield src[:m.start()].count('\n') + 1, m.group(1)
    else:
        for m in TAG.finditer(src):
            if m.group(1): continue           # `nocheck` : non analysable, assume
            yield src[:m.start()].count('\n') + 1, html.unescape(m.group(2))

def try_module(code):
    mi.parse(code, 'doc')

def try_body(code):
    body = '\n'.join('  ' + l if l.strip() else l for l in code.split('\n'))
    mi.parse('fn _doc():\n' + body + '\n', 'doc')

def try_sigs(code):
    out = []
    for l in code.split('\n'):
        t = l.rstrip()
        if not t.strip() or t.strip().startswith('#'): continue
        head = t.partition('  #')[0].rstrip()     # le ':' va AVANT le commentaire
        out.append(head if head.endswith(':') else head + ':')
        out.append('  0')
    mi.parse('\n'.join(out) + '\n', 'doc')

MODES = (('module', try_module), ('corps', try_body), ('signatures', try_sigs))

def check(path):
    rows = []
    for line, code in snippets(path):
        if not code.strip(): continue
        code = normalize(code)
        errs = {}
        for name, fn in MODES:
            try:
                fn(code); rows.append((line, name, None)); break
            except mi.MiError as e:
                errs[name] = f'{e.code} {e.msg}'
            except RecursionError:
                errs[name] = 'recursion'
        else:
            # un bloc ouvrant sur une declaration est un module rate ; sinon
            # c'est un fragment, et l'erreur utile vient du mode `corps`
            head = code.lstrip().split(' ', 1)[0]
            key = ('module' if head in ('fn', 'pub', 'mod', 'seal', 'draft', 'type', 'err')
                   else 'corps')
            rows.append((line, None, errs.get(key) or next(iter(errs.values()), '?')))
    return rows

def main(paths):
    total = bad = 0
    for p in paths:
        rows = check(p)
        if not rows: continue
        fails = [r for r in rows if r[1] is None]
        total += len(rows); bad += len(fails)
        kinds = {}
        for _, k, _ in rows:
            if k: kinds[k] = kinds.get(k, 0) + 1
        tag = ' · '.join(f'{v} {k}' for k, v in sorted(kinds.items()))
        mark = '✓' if not fails else '✗'
        print(f'  {mark} {os.path.basename(p):22} {len(rows):3} extraits   {tag}')
        for line, _, why in fails:
            print(f'      ligne {line}: {why}')
    print(f'{total - bad}/{total} extraits analysables')
    return 1 if bad else 0

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        args = sorted(glob.glob(os.path.join(root, '*.md')) +
                      glob.glob(os.path.join(root, 'bootstrap', '*.md')))
    sys.exit(main(args))
