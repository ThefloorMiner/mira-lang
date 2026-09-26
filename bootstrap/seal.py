#!/usr/bin/env python3
"""
Porte de scellement — SPEC.md §5.1.

Applique les regles qu'un module doit satisfaire pour passer de `draft` a
`seal`. Chaque manquement sort en une ligne au format `llm` de §6 : un code
stable, un lieu, un sujet, et des reparations nommees.

Ce fichier dit aussi, en bas, ce qu'il ne verifie PAS. Un verificateur qui
tait ses angles morts est pire qu'aucun verificateur : il fait croire a une
preuve qu'il n'a pas faite.
"""
from __future__ import annotations
import os
from mi import N, MiError, parse

# ── effets portes par les modules ambiants (SPEC §13.2)
AMBIENT = {
    'io': 'io', 'log': 'io', 'fs': 'fs', 'net': 'net', 'http': 'net',
    'clock': 'clock', 'rand': 'rand', 'env': 'env', 'proc': 'proc',
    'chan': 'task', 'mutex': 'task', 'atom': 'task', 'gpu': 'gpu', 'ffi': 'ffi',
}
PURE_METHODS_ON_MAP = {'get', 'set', 'upsert', 'has', 'keys', 'values', 'pairs', 'drain', 'len'}


# ── methodes qui mutent leur receveur (SPEC §13.1)
MUTATING = {'push', 'pop', 'set', 'upsert', 'clear', 'insert', 'remove',
            'drain', 'extend', 'truncate', 'sort_in_place'}


def root_of(e):
    """Nom a la racine d'une chaine d'acces : a.b[i].c -> 'a'. None si compose."""
    while _is_node(e) and e.kind in ('Attr', 'Index', 'TupleGet', 'Method'):
        e = e.obj
    return e.name if _is_node(e) and e.kind == 'Name' else None


class Ob:
    """Une obligation ou une erreur. `sev` vaut 'E' (bloquant) ou 'O'."""
    __slots__ = ('code', 'file', 'line', 'kind', 'what', 'fix')
    def __init__(s, code, file, line, kind, what, fix=''):
        s.code, s.file, s.line = code, file, line
        s.kind, s.what, s.fix = kind, what, fix
    @property
    def sev(s): return s.code[0]
    def __str__(s):
        loc = f'{s.file}:{s.line}' if s.line else s.file
        row = f'{s.code} {loc}  {s.kind}  {s.what}'
        return row + (f'  fix:{s.fix}' if s.fix else '')


# ── parcours generique de l'arbre
def _is_node(x):
    # Typage canard plutot qu'isinstance : robuste meme si deux exemplaires
    # du module mi coexistent dans le processus.
    return hasattr(x, 'kind') and hasattr(x, '__dict__')

def walk(node):
    """Tous les noeuds d'arbre atteignables, en profondeur."""
    if _is_node(node):
        yield node
        items = [v for k, v in node.__dict__.items() if k not in ('kind', 'line')]
    elif isinstance(node, (list, tuple)):
        items = list(node)
    else:
        return
    for v in items:
        if _is_node(v) or isinstance(v, (list, tuple)):
            yield from walk(v)


def fn_body_nodes(fn):
    yield from walk(fn.body)


def is_waiver(test):
    """`test f: "raison"` — derogation explicite (SPEC §5.1.6).

    La spec ecrivait `test none: <raison>`, qui ne nomme pas l'item couvert et
    n'etait pas analysable. Un bloc dont le corps est une seule chaine litterale
    est sans ambiguite : une chaine nue n'est jamais une assertion utile."""
    b = test.body
    return (len(b) == 1 and b[0].kind == 'ExprStmt'
            and b[0].expr.kind == 'Str')


def waiver_reason(test):
    p = test.body[0].expr.parts
    return ''.join(x[1] for x in p if x[0] == 'lit')


def _txt(e):
    """Operande court pour l'affichage d'une obligation : valeur litterale,
    nom simple, `…` sinon."""
    if e.kind == 'Num': return str(e.v)
    if e.kind == 'Name': return e.name
    return '…'


class Sealer:
    def __init__(s, asts, root):
        s.asts, s.root, s.obs = asts, root, []
        s.files = {m: f'{m}.mi' for m in asts}
        # table globale des fonctions : (module, nom) -> declaration
        s.fns = {}
        for mname, m in asts.items():
            for d in m.decls:
                if d.kind == 'Fn': s.fns[(mname, d.name)] = d
        s.eff = {}          # effets inferes, point fixe

    def add(s, code, mod, line, kind, what, fix=''):
        s.obs.append(Ob(code, s.files[mod], line, kind, what, fix))

    # ═════════════════════════════════ 1. effets (§5.1.4)

    def _direct_effects(s, mod, fn):
        """Effets visibles dans le corps, plus les effets des appelees."""
        out, calls = set(), set()
        for n in fn_body_nodes(fn):
            if n.kind in ('Method', 'Attr') and getattr(n.obj, 'kind', '') == 'Name':
                base = n.obj.name
                if base in AMBIENT: out.add(AMBIENT[base])
                elif (base, n.name) in s.fns: calls.add((base, n.name))
            elif n.kind == 'Call' and n.fn.kind == 'Name':
                if (mod, n.fn.name) in s.fns: calls.add((mod, n.fn.name))
            elif n.kind in ('Spawn', 'Par'):
                out.add('task')
            elif n.kind == 'Region' and n.device == 'gpu':
                out.add('gpu')
        return out, calls

    def infer_effects(s):
        direct = {}
        for (mod, name), fn in s.fns.items():
            direct[(mod, name)] = s._direct_effects(mod, fn)
            s.eff[(mod, name)] = set(direct[(mod, name)][0])
        changed = True
        while changed:                      # point fixe sur le graphe d'appel
            changed = False
            for key, (own, calls) in direct.items():
                before = len(s.eff[key])
                for c in calls:
                    if c in s.eff: s.eff[key] |= s.eff[c]
                if len(s.eff[key]) != before: changed = True

    def check_effects(s):
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            declared, inferred = set(fn.effects), s.eff[(mod, name)]
            for e in sorted(inferred - declared):
                s.add('E512', mod, fn.line, 'effet-non-declare',
                      f'{e} sur {name}', f'+{e}')
            for e in sorted(declared - inferred):
                s.add('O513', mod, fn.line, 'effet-inutile',
                      f'{e} declare sur {name}, jamais utilise', 'pure')

    # ═════════════════════════════════ 2. frontieres publiques (§5.1.2)

    def check_annotations(s):
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal' or not fn.pub: continue
            for p in fn.params:
                if not p.type:
                    s.add('O301', mod, fn.line, 'type-inconnu',
                          f'{name}.{p.name}', 'annotate')
            if fn.ret is None and 'Unit' not in (fn.ret or ''):
                has_value = any(n.kind == 'Return' and n.expr for n in fn_body_nodes(fn))
                if has_value or fn.body and fn.body[-1].kind == 'ExprStmt':
                    s.add('O301', mod, fn.line, 'retour-inconnu', name, 'annotate')

    # ═════════════════════════════════ 3. operations partielles (§10.3)

    def _div_guards(s, fn):
        """Decharge de O222 : `assert d != 0` ou `assert d > 0` (d nom simple,
        0 litteral) placee au NIVEAU SUPERIEUR du corps. Un assert y est
        l'instruction la moins chere qui prouve une borne : l'appel qui atteint
        la division l'a necessairement franchie (E330 sinon). Un assert dans un
        `if` ou une boucle ne dit rien de la valeur au moment de la division.

        Rend (affirms, rebinds, spans, lams) :
          affirms : nom -> lignes d'affirmation au niveau superieur
          rebinds : nom -> lignes ou le nom est reassigne, redefini ou lie, a
                    quelque profondeur — regle de lignes, pas de flux de donnees
          spans   : etendues [lo, hi] des corps de boucle
          lams    : id() des noeuds sous un lambda : un `d` y est un autre `d`
        """
        affirms, rebinds, spans, lams = {}, {}, [], set()
        def rebind(nm, line): rebinds.setdefault(nm, []).append(line)
        for st in fn.body:
            if st.kind == 'Assert':
                e = st.expr
                if (e.kind == 'Bin' and e.op in ('!=', '>')
                        and e.l.kind == 'Name' and e.r.kind == 'Num'
                        and isinstance(e.r.v, int) and e.r.v == 0):
                    affirms.setdefault(e.l.name, []).append(st.line)
        for n in walk(fn.body):
            if n.kind == 'Assign' and n.target.kind == 'Name':
                rebind(n.target.name, n.line)       # `d = …` comme `d -= …`
            elif n.kind == 'Let':
                rebind(n.name, n.line)
            elif n.kind == 'LetTuple':
                for nm in n.names: rebind(nm, n.line)
            elif n.kind == 'For':
                for nm in n.names: rebind(nm, n.line)
                lines = [m.line for m in walk(n.body)]
                if lines: spans.append((min(lines), max(lines)))
            elif n.kind == 'While':
                lines = [m.line for m in walk(n.body)]
                if lines: spans.append((min(lines), max(lines)))
            elif n.kind == 'Lambda':
                lams.update(id(m) for m in walk(n.body))
        return affirms, rebinds, spans, lams

    def _proved(s, guards, node):
        affirms, rebinds, spans, lams = guards
        d = node.r
        if id(node) in lams: return False       # diviseur d'un lambda : autre portee
        rs = rebinds.get(d.name, ())
        for g in affirms.get(d.name, ()):
            if g >= node.line: continue
            if any(g < r < node.line for r in rs):
                continue                        # d reassigne entre l'assert et la division
            loop = [(lo, hi) for lo, hi in spans if lo <= node.line <= hi]
            if loop and any(lo <= r <= hi for lo, hi in loop for r in rs):
                continue                        # d modifie dans la boucle qui divise
            return True
        return False

    def check_total_ops(s):
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            maps = {p.name for p in fn.params if (p.type or '').startswith('Map')}
            for st in fn_body_nodes(fn):
                if st.kind == 'Let' and (st.type or '').startswith('Map'):
                    maps.add(st.name)
            guards = s._div_guards(fn)
            for n in fn_body_nodes(fn):
                if n.kind == 'Index':
                    base = getattr(n.obj, 'name', None)
                    if base in maps:
                        s.add('O204', mod, n.line, 'index-dyn',
                              f'{base}[…]', 'upsert | get_or')
                    else:
                        s.add('O220', mod, n.line, 'index-non-prouve',
                              f'{base or "…"}[…]', 'for-in | get | assert-range')
                elif n.kind == 'Bin' and n.op in ('/', '%'):
                    d = n.r
                    if d.kind == 'Num' and isinstance(d.v, int) and d.v != 0:
                        continue                    # diviseur litteral non nul : rien a prouver
                    if d.kind == 'Name' and s._proved(guards, n):
                        continue                    # `assert d != 0` avant la division
                    s.add('O222', mod, n.line, 'div-non-prouve',
                          f'{_txt(n.l)} {n.op} {_txt(d)}', 'assert | try')

    # ═════════════════════════════════ 4. echappement de region (§2.3)

    def check_regions(s):
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            for i, st in enumerate(fn.body):
                if st.kind == 'Region':
                    tail = (i == len(fn.body) - 1)
                    s._region(mod, st, tail)
            for n in fn_body_nodes(fn):
                if n.kind == 'Region' and n not in fn.body:
                    s._region(mod, n, False)

    def _region(s, mod, reg, is_tail):
        g, tainted = reg.name, set()

        def out_call(e):
            return (e.kind == 'Method' and e.name == 'out'
                    and getattr(e.obj, 'kind', '') == 'Name' and e.obj.name == g)

        def t(x):
            """Contamination d'une expression. `g.out(v)` assainit tout son
            sous-arbre : on elague, on ne se contente pas d'ignorer le noeud."""
            if _is_node(x):
                if out_call(x): return False
                if x.kind == 'RegionNew': return True
                if x.kind == 'Name': return x.name in tainted
                return any(t(v) for k, v in x.__dict__.items()
                           if k not in ('kind', 'line'))
            if isinstance(x, (list, tuple)):
                return any(t(v) for v in x)
            return False

        def value_of(stmts):
            """Taint de la valeur produite par un bloc."""
            if not stmts: return False
            last = stmts[-1]
            if last.kind == 'ExprStmt': return t(last.expr)
            if last.kind == 'Match':
                return any(value_of(b) for _, b in last.arms)
            if last.kind == 'If':
                return value_of(last.body) or (last.els and value_of(last.els))
            return False

        def scan(stmts):
            for st in stmts:
                if st.kind == 'Let':
                    if t(st.expr): tainted.add(st.name)
                elif st.kind == 'LetTuple':
                    if t(st.expr): tainted.update(st.names)
                elif st.kind == 'Assign' and st.target.kind == 'Name':
                    if t(st.expr): tainted.add(st.target.name)
                elif st.kind == 'For':
                    if t(st.iter): tainted.update(st.names)
                    scan(st.body)
                elif st.kind == 'Match':
                    dirty = t(st.subj)
                    for pat, body in st.arms:
                        if dirty: tainted.update(pat.binds)
                        scan(body)
                elif st.kind == 'Return':
                    if t(st.expr):
                        s.add('E211', mod, st.line, 'echappement-region',
                              f'valeur allouee dans {g}:{reg.line}', 'g.out | own')
                elif st.kind in ('If', 'While', 'With', 'Par', 'Region'):
                    scan(st.body)
                    if getattr(st, 'els', None): scan(st.els)

        scan(reg.body)
        if is_tail and value_of(reg.body):
            last = reg.body[-1]
            s.add('E211', mod, last.line, 'echappement-region',
                  f'valeur de region {g}:{reg.line} rendue par la fonction', 'g.out | own')

    # ═════════════════════════════════ 5. propriete : usage apres deplacement

    def check_moves(s):
        own_params = {k: [i for i, p in enumerate(d.params) if p.mode == 'own']
                      for k, d in s.fns.items()}
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            moved, skip = {}, set()   # nom -> ligne du deplacement ; noeuds a ignorer
            for st in fn.body:
                for n in walk(st):
                    if n.kind == 'Name' and n.name in moved and id(n) not in skip:
                        s.add('E204', mod, n.line, 'valeur-deplacee',
                              f'{n.name} (deplacee {moved[n.name]})', 'own | clone | region')
                        del moved[n.name]               # une seule fois par nom
                    key = None
                    if n.kind == 'Call' and n.fn.kind == 'Name': key = (mod, n.fn.name)
                    elif n.kind == 'Method' and getattr(n.obj, 'kind', '') == 'Name':
                        key = (n.obj.name, n.name)
                    if key in own_params:
                        for idx in own_params[key]:
                            if idx < len(n.args) and n.args[idx].kind == 'Name':
                                moved[n.args[idx].name] = n.line
                                # l'argument du deplacement n'est pas un usage
                                # apres deplacement : walk le visite juste apres
                                skip.add(id(n.args[idx]))

    # ═════════════════════════════════ 6. tests, regimes, raw (§5.1.1/5/6/7)

    def check_coverage(s):
        for mname, m in s.asts.items():
            if m.mode != 'seal': continue
            named = set()
            for d in m.decls:
                if d.kind == 'Test':
                    named.add(d.name)          # une derogation couvre aussi
                    if is_waiver(d): continue
                    named.update(n.name for n in walk(d.body) if n.kind == 'Name')
            for d in m.decls:
                if d.kind == 'Fn' and d.pub and d.name not in named:
                    s.add('O410', mname, d.line, 'pub-non-teste', d.name,
                          'add-test | waive')

    def check_modes(s):
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            if fn.mode == 'draft':
                s.add('E401', mod, fn.line, 'draft-dans-seal', name, 'seal | remove')
            for n in fn_body_nodes(fn):
                if n.kind == 'Method' and getattr(n.obj, 'kind', '') == 'Name':
                    callee = s.fns.get((n.obj.name, n.name))
                    if callee is not None and callee.mode == 'draft':
                        s.add('E401', mod, n.line, 'appel-vers-draft',
                              f'{n.obj.name}.{n.name}', 'seal')

    def check_raw(s):
        for (mod, name), fn in s.fns.items():
            for n in fn_body_nodes(fn):
                if n.kind == 'Raw':
                    s.add('E720', mod, n.line, 'raw-sans-justification', name,
                          'safety:<raison>')


    # ═════════════════════════════════ 7. emprunts (§2.1)

    def check_borrows(s):
        """Mutabilite et unicite des emprunts exclusifs.

        Faux negatifs assumes : on ne conclut que lorsque la racine d'un acces
        est un nom simple et connu de la portee. Un emprunt a travers une
        expression composee n'est pas verifie plutot que signale a tort — un
        verificateur qui crie au loup sur du code correct se fait desactiver.
        """
        varidx = {k: [i for i, p in enumerate(d.params) if p.mode == 'var']
                  for k, d in s.fns.items()}
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            scope = {p.name: ('mut' if p.mode in ('var', 'own') else 'shared')
                     for p in fn.params}
            s._bblock(mod, fn.body, scope, varidx)

    def _callee(s, n, mod):
        if n.kind == 'Call' and n.fn.kind == 'Name':   return (mod, n.fn.name)
        if n.kind == 'Method' and getattr(n.obj, 'kind', '') == 'Name':
            return (n.obj.name, n.name)
        return None

    def _bexpr(s, mod, e, scope, varidx):
        for n in walk(e):
            # mutation par methode
            if n.kind == 'Method' and n.name in MUTATING:
                r = root_of(n.obj)
                if r and scope.get(r) == 'shared':
                    s.add('E205', mod, n.line, 'mutation-sans-var',
                          f'{r}.{n.name}()', 'var | own')
            # passage a un parametre `var`
            key = s._callee(n, mod)
            if key in varidx and varidx[key]:
                seen, exclusive, dup = {}, [], set()
                for i, a in enumerate(getattr(n, 'args', [])):
                    r = root_of(a)
                    if r is None: continue
                    seen.setdefault(r, []).append(i)
                    if i in varidx[key]:
                        if scope.get(r) == 'shared':
                            s.add('E207', mod, n.line, 'exclusif-sur-partage',
                                  f'{r} en position {i}', 'var | own | clone')
                        if r in exclusive: dup.add(r)
                        exclusive.append(r)
                for r in dict.fromkeys(exclusive):
                    if r in dup:                      # racine
                        s.add('E206', mod, n.line, 'exclusif-double',
                              f'{r} emprunte deux fois', 'clone | split')
                    elif len(seen[r]) > 1:            # sinon seulement, la cascade
                        s.add('E208', mod, n.line, 'alias-pendant-exclusif',
                              f'{r} lu pendant son emprunt exclusif', 'clone | reorder')

    def _bblock(s, mod, stmts, scope, varidx):
        for st in stmts:
            k = st.kind
            if k == 'Let':
                s._bexpr(mod, st.expr, scope, varidx)
                scope[st.name] = 'mut' if st.mut else 'shared'
            elif k == 'LetTuple':
                s._bexpr(mod, st.expr, scope, varidx)
                for nm in st.names: scope[nm] = 'mut' if st.mut else 'shared'
            elif k == 'Assign':
                s._bexpr(mod, st.expr, scope, varidx)
                r = root_of(st.target)
                if r and scope.get(r) == 'shared':
                    what = r if st.target.kind == 'Name' else f'{r} (via {st.target.kind.lower()})'
                    s.add('E205', mod, st.line, 'mutation-sans-var', what, 'var | own')
            elif k == 'For':
                s._bexpr(mod, st.iter, scope, varidx)
                inner = dict(scope)
                # le mode d'une liaison de boucle est herite de la collection
                # parcourue, et seulement quand celle-ci est un nom simple.
                m = scope.get(st.iter.name, 'shared') if st.iter.kind == 'Name' else None
                for nm in st.names:
                    if m is None: inner.pop(nm, None)
                    else: inner[nm] = m
                s._bblock(mod, st.body, inner, varidx)
            elif k == 'Match':
                s._bexpr(mod, st.subj, scope, varidx)
                for pat, body in st.arms:
                    inner = dict(scope)
                    for b in pat.binds: inner.pop(b, None)
                    s._bblock(mod, body, inner, varidx)
            elif k in ('If', 'While', 'Region', 'Par', 'With'):
                for f in ('cond', 'expr', 'iter'):
                    if getattr(st, f, None) is not None:
                        s._bexpr(mod, getattr(st, f), scope, varidx)
                inner = dict(scope)
                if k == 'With': inner[st.name] = 'mut'
                if k == 'Region': inner[st.name] = 'shared'
                s._bblock(mod, st.body, inner, varidx)
                if getattr(st, 'els', None): s._bblock(mod, st.els, dict(scope), varidx)
            elif k in ('ExprStmt', 'Return', 'Spawn', 'Assert'):
                if getattr(st, 'expr', None) is not None:
                    s._bexpr(mod, st.expr, scope, varidx)

    # ═════════════════════════════════ pilote

    def run(s):
        s.infer_effects()
        for f in (s.check_modes, s.check_effects, s.check_annotations,
                  s.check_total_ops, s.check_regions, s.check_moves,
                  s.check_coverage, s.check_raw, s.check_borrows):
            f()
        # racines d'abord : erreurs avant obligations, puis par fichier et ligne
        s.obs.sort(key=lambda o: (o.sev != 'E', o.file, o.line, o.code))
        return s.obs


# ── ce que ce verificateur ne fait PAS
BLIND_SPOTS = [
    'Emprunts : mutabilite et unicite verifiees seulement quand la racine de l\'acces \n    est un nom simple connu de la portee. A travers une expression composee \n    (`a.b[i]`, un resultat d\'appel), rien n\'est conclu — faux negatif assume.',
    'Arithmetique : O221 (§10.3) demande une analyse de plages, absente.',
    'Divisions : O222 (§10.3) couvert en conservateur — tout `/` ou `%` dont le \n    diviseur n\'est pas un litteral entier non nul est une obligation. Seule \n    forme de decharge : `assert d != 0` ou `assert d > 0` (d nom simple) au \n    niveau superieur du corps, avant la division, sans que d soit reassigne \n    entre les deux ni dans une boucle qui contient la division — regle de \n    lignes, pas de flux de donnees. Un assert dans un `if` ou une boucle ne \n    decharge jamais, toute autre affirmation ne prouve rien, et les affectations \n    composees `/=` et `%=` ne sont pas comptees.',
    'Types : aucune inference ni verification. O301 ne voit que les annotations manquantes.',
    'Verrous : O230 (§11.4) demande un graphe de rangs, absent.',
    'GPU : E240 (§12.2) n\'est pas implemente.',
    'Regions : le suivi de contamination est conservateur mais pas sain — une valeur '
    'de region rangee dans une structure qui sort par un autre chemin echappe au controle.',
]
