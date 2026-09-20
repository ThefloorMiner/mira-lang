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

    def check_total_ops(s):
        for (mod, name), fn in s.fns.items():
            if s.asts[mod].mode != 'seal': continue
            maps = {p.name for p in fn.params if (p.type or '').startswith('Map')}
            for st in fn_body_nodes(fn):
                if st.kind == 'Let' and (st.type or '').startswith('Map'):
                    maps.add(st.name)
            for n in fn_body_nodes(fn):
                if n.kind != 'Index': continue
                base = getattr(n.obj, 'name', None)
                if base in maps:
                    s.add('O204', mod, n.line, 'index-dyn',
                          f'{base}[…]', 'upsert | get_or')
                else:
                    s.add('O220', mod, n.line, 'index-non-prouve',
                          f'{base or "…"}[…]', 'for-in | get | assert-range')

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

    # ═════════════════════════════════ pilote

    def run(s):
        s.infer_effects()
        for f in (s.check_modes, s.check_effects, s.check_annotations,
                  s.check_total_ops, s.check_regions, s.check_moves,
                  s.check_coverage, s.check_raw):
            f()
        # racines d'abord : erreurs avant obligations, puis par fichier et ligne
        s.obs.sort(key=lambda o: (o.sev != 'E', o.file, o.line, o.code))
        return s.obs


# ── ce que ce verificateur ne fait PAS
BLIND_SPOTS = [
    'Emprunts : `var` n\'est pas verifie. Deux emprunts exclusifs simultanes passent.',
    'Arithmetique : O221/O222 (§10.3) demandent une analyse de plages, absente.',
    'Types : aucune inference ni verification. O301 ne voit que les annotations manquantes.',
    'Verrous : O230 (§11.4) demande un graphe de rangs, absent.',
    'GPU : E240 (§12.2) n\'est pas implemente.',
    'Regions : le suivi de contamination est conservateur mais pas sain — une valeur '
    'de region rangee dans une structure qui sort par un autre chemin echappe au controle.',
]
