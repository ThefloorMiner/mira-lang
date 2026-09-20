#!/usr/bin/env python3
"""
mi — amorce de Mira, regime `draft` uniquement.

Ce n'est pas la VM de la phase 1 : c'est l'implementation de reference qui
sert a prouver que la grammaire de SPEC.md §3.1 est analysable sans ambiguite
et que la semantique tient. Elle est lente et ne scelle rien.

    mi run  F [-- args]   execute
    mi test F             lance les blocs `test` et `prop`
    mi api  F             surface publique (SPEC.md §7)
    mi lex  F             jetons, pour deboguer l'indentation
"""
from __future__ import annotations
import sys, os, re, random

# ═══════════════════════════════════════════════════════ jetons

KEYWORDS = {
    'fn','let','var','own','pub','type','trait','impl','err','ok','for','in',
    'if','else','while','match','return','test','prop','region','par','spawn',
    'raw','as','and','or','not','true','false','none','some','pass','break',
    'continue','derive','self','seal','draft','mod','with','gpu','use',
}
OPS = ['->','==','!=','<=','>=','+=','-=','*=','/=','..','|','(',')','[',']',
       '{','}',',',':','.','?','!','=','<','>','+','-','*','/','%']

class Tok:
    __slots__ = ('kind','val','line')
    def __init__(s, kind, val, line): s.kind, s.val, s.line = kind, val, line
    def __repr__(s): return f'{s.kind}({s.val!r})@{s.line}'

class MiError(Exception):
    def __init__(s, code, line, msg, fix=''):
        s.code, s.line, s.msg, s.fix = code, line, msg, fix
        super().__init__(msg)

# ═══════════════════════════════════════════════════════ lexeur

def _scan_interp(raw, line):
    """Decoupe le contenu d'une chaine en morceaux litteraux et expressions."""
    parts, buf, i, n = [], '', 0, len(raw)
    while i < n:
        c = raw[i]
        if c == '\\' and i + 1 < n:
            buf += {'n':'\n','t':'\t','r':'\r','\\':'\\','"':'"','{':'{','}':'}'}.get(raw[i+1], raw[i+1])
            i += 2; continue
        if c == '{':
            if buf: parts.append(('lit', buf)); buf = ''
            depth, j, instr = 1, i + 1, False
            while j < n and depth:
                if raw[j] == '"': instr = not instr
                elif not instr:
                    if raw[j] in '([{': depth += 1
                    elif raw[j] in ')]}': depth -= 1
                if depth: j += 1
            inner = raw[i+1:j]
            spec = ''
            d = 0
            for k, ch in enumerate(inner):
                if ch in '([{': d += 1
                elif ch in ')]}': d -= 1
                elif ch == ':' and d == 0: spec = inner[k+1:]; inner = inner[:k]; break
            parts.append(('expr', inner, spec))
            i = j + 1; continue
        buf += c; i += 1
    if buf: parts.append(('lit', buf))
    return parts

def lex(src):
    toks, i, line, n = [], 0, 1, len(src)
    indents, depth, at_start = [0], 0, True
    def push(k, v): toks.append(Tok(k, v, line))
    while i < n:
        if at_start and depth == 0:
            j, ind = i, 0
            while j < n and src[j] in ' \t':
                ind += 1 if src[j] == ' ' else 4; j += 1
            if j >= n or src[j] == '\n' or src[j] == '#':
                while j < n and src[j] != '\n': j += 1
                i = j + 1; line += 1; continue
            if src[j] == '.':                      # continuation de chaine (§3.4)
                if toks and toks[-1].kind == 'NEWLINE': toks.pop()
                i = j; at_start = False; continue
            if ind > indents[-1]:
                indents.append(ind); push('INDENT', ind)
            while ind < indents[-1]:
                indents.pop(); push('DEDENT', ind)
                if ind > indents[-1]:
                    raise MiError('E101', line, 'indentation incoherente', 'fmt')
            i = j; at_start = False; continue
        c = src[i]
        if c == '\n':
            if depth == 0 and toks and toks[-1].kind != 'NEWLINE':
                push('NEWLINE', None)
            at_start = True; i += 1; line += 1; continue
        if c in ' \t': i += 1; continue
        if c == '#':
            while i < n and src[i] != '\n': i += 1
            continue
        if c == '"':
            # Le scanner doit connaitre l'interpolation : un guillemet a
            # l'interieur d'un {..} appartient a l'expression, pas a la chaine.
            j, esc, brace = i + 1, False, 0    # `brace`, surtout pas `depth`
            while j < n:
                if esc: esc = False
                elif src[j] == '\\': esc = True
                elif src[j] == '{': brace += 1
                elif src[j] == '}': brace = max(0, brace - 1)
                elif src[j] == '"' and brace == 0: break
                j += 1
            if j >= n: raise MiError('E102', line, 'chaine non terminee')
            push('STR', _scan_interp(src[i+1:j], line))
            i = j + 1; continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == '_'): j += 1
            if j + 1 < n and src[j] == '.' and src[j+1].isdigit():
                j += 1
                while j < n and src[j].isdigit(): j += 1
                push('NUM', float(src[i:j].replace('_', '')))
            else:
                push('NUM', int(src[i:j].replace('_', '')))
            i = j; continue
        if c.isalpha() or c == '_':
            j = i
            while j < n and (src[j].isalnum() or src[j] == '_'): j += 1
            w = src[i:j]
            push('KW' if w in KEYWORDS else 'NAME', w)
            i = j; continue
        for op in OPS:
            if src.startswith(op, i):
                if op in '([{': depth += 1
                elif op in ')]}': depth -= 1
                push('OP', op); i += len(op); break
        else:
            raise MiError('E103', line, f'caractere inattendu {c!r}')
    if toks and toks[-1].kind != 'NEWLINE': push('NEWLINE', None)
    while len(indents) > 1: indents.pop(); push('DEDENT', 0)
    push('EOF', None)
    return toks

# ═══════════════════════════════════════════════════════ arbre

class N:
    def __init__(s, kind, line=0, **kw):
        s.kind, s.line = kind, line; s.__dict__.update(kw)
    def __repr__(s):
        d = {k: v for k, v in s.__dict__.items() if k not in ('kind', 'line')}
        return f'{s.kind}{d}'

CMP = ('==','!=','<','<=','>','>=')

class Parser:
    def __init__(s, toks, file='<mem>'):
        s.t, s.i, s.file = toks, 0, file
        s.nocast = 0   # `with X as Y` : `as` y est un lieur, pas une conversion

    # ── curseur
    def peek(s, k=0):  return s.t[min(s.i + k, len(s.t) - 1)]
    def at(s, kind, val=None):
        t = s.peek(); return t.kind == kind and (val is None or t.val == val)
    def atkw(s, *ws): return s.peek().kind == 'KW' and s.peek().val in ws
    def next(s): s.i += 1; return s.t[s.i - 1]
    def eat(s, kind, val=None):
        if not s.at(kind, val):
            t = s.peek()
            got = t.kind if t.kind in ('INDENT', 'DEDENT', 'NEWLINE', 'EOF') else t.val
            raise MiError('E110', t.line, f'attendu {val or kind}, trouve {got}')
        return s.next()
    def opt(s, kind, val=None):
        if s.at(kind, val): return s.next()
        return None
    def skipnl(s):
        while s.at('NEWLINE'): s.next()

    # ── types (analyses pour `mi api`, non verifies en draft)
    def type_(s):
        pre = ''
        if (s.at('NAME') and s.peek().val in ('rc', 'arc')
                and s.peek(1).kind in ('NAME', 'KW')):
            pre = s.next().val + ' '          # partage compte (§2.4)
        if s.at('OP', '('):
            s.next(); parts = []
            while not s.at('OP', ')'):
                parts.append(s.type_())
                if not s.opt('OP', ','): break
            s.eat('OP', ')'); base = '(' + ', '.join(parts) + ')'
        else:
            base = s.eat('NAME').val if s.at('NAME') else s.eat('KW').val
            if s.at('OP', '['):
                s.next(); args = []
                while not s.at('OP', ']'):
                    args.append(s.type_())
                    if not s.opt('OP', ','): break
                s.eat('OP', ']'); base += '[' + ', '.join(args) + ']'
        if s.opt('OP', '?'): base += '?'
        if s.opt('OP', '!'):
            base += '!'
            if s.at('NAME') and s.peek().val[0].isupper(): base += s.next().val
        return pre + base

    # ── module
    def module(s, name):
        mode, decls = 'draft', []
        s.skipnl()
        if s.atkw('seal', 'draft') and s.peek(1).kind == 'KW' and s.peek(1).val == 'mod':
            mode = s.next().val; s.next(); name = s.eat('NAME').val; s.skipnl()
        elif s.atkw('mod'):
            s.next(); name = s.eat('NAME').val; s.skipnl()
        while not s.at('EOF'):
            s.skipnl()
            if s.at('EOF'): break
            decls.append(s.item())
            s.skipnl()
        return N('Module', name=name, mode=mode, decls=decls)

    def item(s):
        mode, is_pub = None, False
        if s.atkw('seal', 'draft', 'gpu'): mode = s.next().val
        if s.atkw('pub'): s.next(); is_pub = True
        if s.atkw('fn'):   return s.fn(mode, is_pub)
        if s.atkw('test'): return s.test()
        if s.atkw('type'): return s.typedecl(is_pub)
        if s.atkw('err'):  return s.errdecl(is_pub)
        t = s.peek()
        raise MiError('E111', t.line, f'declaration attendue, trouve {t.val!r}')

    def fn(s, mode, is_pub):
        ln = s.eat('KW', 'fn').line
        name = s.eat('NAME').val
        s.eat('OP', '(')
        params = []
        while not s.at('OP', ')'):
            pmode = s.next().val if s.atkw('var', 'own') else None
            pname = s.eat('NAME').val if s.at('NAME') else s.eat('KW', 'self').val
            ptype = s.type_() if s.opt('OP', ':') else None
            params.append(N('Param', name=pname, mode=pmode, type=ptype))
            if not s.opt('OP', ','): break
        s.eat('OP', ')')
        ret = s.type_() if s.opt('OP', '->') else None
        effects = []
        if s.opt('OP', '+'):
            while s.at('NAME') or s.atkw('gpu'):
                effects.append(s.next().val)
        s.eat('OP', ':')
        return N('Fn', line=ln, name=name, mode=mode, pub=is_pub, params=params,
                 ret=ret, effects=effects, body=s.block())

    def typedecl(s, is_pub):
        ln = s.eat('KW', 'type').line
        name = s.eat('NAME').val
        s.eat('OP', '=')
        if s.at('OP', '{'):                       # enregistrement
            s.next(); fields = []
            while not s.at('OP', '}'):
                s.skipnl()
                fname = s.eat('NAME').val; s.eat('OP', ':')
                fields.append((fname, s.type_()))
                s.opt('OP', ','); s.skipnl()
            s.eat('OP', '}')
            body = '{' + ', '.join(f'{k}: {v}' for k, v in fields) + '}'
            variants = None
        else:                                      # somme : A | B(T)
            variants = []
            while True:
                vn = s.eat('NAME').val
                payload = None
                if s.opt('OP', '('): payload = s.type_(); s.eat('OP', ')')
                variants.append((vn, payload))
                if not s.opt('OP', '|'): break
            body = ' | '.join(v + (f'({p})' if p else '') for v, p in variants)
            fields = None
        derive = []
        s.skipnl()
        if s.at('INDENT') and s.peek(1).kind == 'KW' and s.peek(1).val == 'derive':
            s.next(); s.next()
            while s.at('NAME'): derive.append(s.next().val)
            s.skipnl(); s.opt('DEDENT')
        return N('Type', line=ln, name=name, pub=is_pub, body=body,
                 fields=fields, variants=variants, derive=derive)

    def errdecl(s, is_pub):
        ln = s.eat('KW', 'err').line
        name = s.eat('NAME').val; s.eat('OP', '=')
        variants = []
        while True:
            vn = s.eat('NAME').val
            payload = None
            if s.opt('OP', '('): payload = s.type_(); s.eat('OP', ')')
            variants.append((vn, payload))
            if not s.opt('OP', '|'): break
        return N('Err', line=ln, name=name, pub=is_pub, variants=variants,
                 body=' | '.join(v + (f'({p})' if p else '') for v, p in variants))

    def test(s):
        ln = s.eat('KW', 'test').line
        name = s.eat('NAME').val if s.at('NAME') else s.next().val
        s.eat('OP', ':')
        return N('Test', line=ln, name=name, body=s.body_())

    # ── blocs et instructions
    def body_(s):
        """Bloc indente, ou instruction unique sur la meme ligne.

        Regle decouverte en ecrivant l'analyseur : `if c: a` est une
        instruction et n'exige pas de `else` ; `if c: a else: b` en position
        d'expression en exige un, puisque sans lui il n'a pas de valeur."""
        if s.at('NEWLINE'): return s.block()
        return [s.stmt()]

    def block(s):
        s.eat('NEWLINE'); s.eat('INDENT')
        stmts = []
        while not s.at('DEDENT') and not s.at('EOF'):
            s.skipnl()
            if s.at('DEDENT') or s.at('EOF'): break
            stmts.append(s.stmt()); s.skipnl()
        s.opt('DEDENT')
        return stmts

    def stmt(s):
        t = s.peek(); ln = t.line
        if s.atkw('let', 'var'):
            mut = s.next().val == 'var'
            if s.at('OP', '('):                      # destructuration (§11.2)
                s.next(); names = []
                while not s.at('OP', ')'):
                    names.append(s.eat('NAME').val)
                    if not s.opt('OP', ','): break
                s.eat('OP', ')'); s.eat('OP', '=')
                return N('LetTuple', line=ln, names=names, mut=mut, expr=s.expr())
            name = s.eat('NAME').val
            ty = s.type_() if s.opt('OP', ':') else None
            s.eat('OP', '=')
            return N('Let', line=ln, name=name, type=ty, mut=mut, expr=s.expr())
        if s.atkw('return'):
            s.next()
            e = None if s.at('NEWLINE') else s.expr()
            return N('Return', line=ln, expr=e)
        if s.atkw('if'):     return s.if_()
        if s.atkw('for'):
            s.next(); names = [s.eat('NAME').val]
            while s.opt('OP', ','): names.append(s.eat('NAME').val)
            s.eat('KW', 'in'); it = s.expr(); s.eat('OP', ':')
            return N('For', line=ln, names=names, iter=it, body=s.body_())
        if s.atkw('while'):
            s.next(); c = s.expr(); s.eat('OP', ':')
            return N('While', line=ln, cond=c, body=s.body_())
        if s.atkw('match'):  return s.match_()
        if s.atkw('with'):
            s.next()
            s.nocast += 1; e = s.expr(); s.nocast -= 1
            s.eat('KW', 'as')
            s.opt('KW', 'var'); nm = s.eat('NAME').val; s.eat('OP', ':')
            return N('With', line=ln, expr=e, name=nm, body=s.block())
        if s.atkw('region'):
            s.next(); nm = s.eat('NAME').val
            dev = None
            if s.at('NAME') and s.peek().val == 'on':
                s.next(); dev = s.next().val    # `gpu` est un mot-cle (§12.1)
            s.eat('OP', ':')
            return N('Region', line=ln, name=nm, device=dev, body=s.block())
        if s.atkw('par'):
            s.next(); s.eat('OP', ':')
            return N('Par', line=ln, body=s.block())
        if s.atkw('spawn'):
            s.next(); return N('Spawn', line=ln, expr=s.expr())
        if s.atkw('prop'):
            s.next(); nm = s.eat('NAME').val; s.eat('OP', ':')
            ty = s.type_(); s.eat('OP', '->')
            return N('Prop', line=ln, name=nm, type=ty, expr=s.expr())
        if s.atkw('pass'):     s.next(); return N('Pass', line=ln)
        if s.atkw('break'):    s.next(); return N('Break', line=ln)
        if s.atkw('continue'): s.next(); return N('Continue', line=ln)

        e = s.expr()
        for op in ('=', '+=', '-=', '*=', '/='):
            if s.at('OP', op):
                s.next(); return N('Assign', line=ln, target=e, op=op, expr=s.expr())
        return N('ExprStmt', line=ln, expr=e)

    def if_(s):
        ln = s.eat('KW', 'if').line
        cond = s.expr(); s.eat('OP', ':'); body = s.body_()
        els = None
        if not s.atkw('else'): s.skipnl()
        if s.atkw('else'):
            s.next()
            if s.atkw('if'): els = [s.if_()]
            else: s.eat('OP', ':'); els = s.body_()
        return N('If', line=ln, cond=cond, body=body, els=els)

    def match_(s):
        ln = s.eat('KW', 'match').line
        subj = s.expr(); s.eat('OP', ':')
        s.eat('NEWLINE'); s.eat('INDENT')
        arms = []
        while not s.at('DEDENT') and not s.at('EOF'):
            s.skipnl()
            if s.at('DEDENT') or s.at('EOF'): break
            pat = s.pattern(); s.eat('OP', ':')
            body = s.body_()
            arms.append((pat, body)); s.skipnl()
        s.opt('DEDENT')
        return N('Match', line=ln, subj=subj, arms=arms)

    def pattern(s):
        ln = s.peek().line
        if s.atkw('ok', 'err', 'some'):
            tag = s.next().val
            if s.at('OP', ':'): return N('Pat', line=ln, tag=tag, ctor=None, binds=[])
            if s.at('OP', '('):                       # some (a, b)
                s.next(); binds = []
                while not s.at('OP', ')'):
                    binds.append(s.eat('NAME').val if s.at('NAME') else s.next().val)
                    if not s.opt('OP', ','): break
                s.eat('OP', ')')
                return N('Pat', line=ln, tag=tag, ctor=None, binds=binds)
            nm = s.next().val
            if nm[0].isupper():                       # err Cycle(p)
                binds = []
                if s.opt('OP', '('):
                    while not s.at('OP', ')'):
                        binds.append(s.next().val)
                        if not s.opt('OP', ','): break
                    s.eat('OP', ')')
                return N('Pat', line=ln, tag=tag, ctor=nm, binds=binds)
            return N('Pat', line=ln, tag=tag, ctor=None, binds=[nm])
        if s.atkw('none'):  s.next(); return N('Pat', line=ln, tag='none', ctor=None, binds=[])
        if s.at('NAME', '_'): s.next(); return N('Pat', line=ln, tag='_', ctor=None, binds=[])
        if s.at('NAME') and s.peek().val[0].isupper():
            return N('Pat', line=ln, tag='variant', ctor=s.next().val, binds=[])
        return N('Pat', line=ln, tag='value', ctor=None, binds=[], expr=s.expr())

    # ── expressions
    def _is_lambda(s):
        """NAME '->'  ou  '(' params ')' '->'"""
        if s.at('NAME') and s.peek(1).kind == 'OP' and s.peek(1).val == '->': return True
        if s.at('OP', '('):
            d, k = 0, 0
            while True:
                t = s.peek(k)
                if t.kind == 'EOF': return False
                if t.kind == 'OP':
                    if t.val in '([{': d += 1
                    elif t.val in ')]}':
                        d -= 1
                        if d == 0:
                            nx = s.peek(k + 1)
                            return nx.kind == 'OP' and nx.val == '->'
                k += 1
        return False

    def expr(s):
        if s._is_lambda():
            ln = s.peek().line; params = []
            if s.at('NAME'):
                params.append(s.next().val)
            else:
                s.eat('OP', '(')
                while not s.at('OP', ')'):
                    params.append(s.eat('NAME').val)
                    if not s.opt('OP', ','): break
                s.eat('OP', ')')
            s.eat('OP', '->')
            return N('Lambda', line=ln, params=params, body=s.expr())
        return s.or_()

    def or_(s):
        e = s.and_()
        while s.atkw('or'):
            ln = s.next().line; e = N('Or', line=ln, l=e, r=s.and_())
        return e

    def and_(s):
        e = s.not_()
        while s.atkw('and'):
            ln = s.next().line; e = N('And', line=ln, l=e, r=s.not_())
        return e

    def not_(s):
        if s.atkw('not'):
            ln = s.next().line; return N('Not', line=ln, e=s.not_())
        return s.cmp_()

    def cmp_(s):
        e = s.range_()
        while s.peek().kind == 'OP' and s.peek().val in CMP:
            op = s.next(); e = N('Bin', line=op.line, op=op.val, l=e, r=s.range_())
        return e

    def range_(s):
        e = s.add_()
        if s.at('OP', '..'):
            ln = s.next().line; e = N('Range', line=ln, lo=e, hi=s.add_())
        return e

    def add_(s):
        e = s.mul_()
        while s.peek().kind == 'OP' and s.peek().val in ('+', '-'):
            op = s.next(); e = N('Bin', line=op.line, op=op.val, l=e, r=s.mul_())
        return e

    def mul_(s):
        e = s.unary()
        while s.peek().kind == 'OP' and s.peek().val in ('*', '/', '%'):
            op = s.next(); e = N('Bin', line=op.line, op=op.val, l=e, r=s.unary())
        return e

    def unary(s):
        if s.at('OP', '-'):
            ln = s.next().line; return N('Neg', line=ln, e=s.unary())
        return s.postfix()

    def postfix(s):
        e = s.primary()
        while True:
            t = s.peek()
            if t.kind == 'OP' and t.val == '.':
                s.next()
                if s.at('NUM'):                       # acces de tuple : p.1
                    e = N('TupleGet', line=t.line, obj=e, idx=s.next().val)
                else:
                    nm = s.eat('NAME').val
                    if nm == 'new':          # allocation en region : g.new T{..} (§2.3)
                        e = N('RegionNew', line=t.line, region=e, e=s.postfix()); continue
                    if s.at('OP', '('):
                        e = N('Method', line=t.line, obj=e, name=nm, args=s.args())
                    else:
                        e = N('Attr', line=t.line, obj=e, name=nm)
            elif t.kind == 'OP' and t.val == '(':
                e = N('Call', line=t.line, fn=e, args=s.args())
            elif t.kind == 'OP' and t.val == '[':
                s.next(); ix = s.expr(); s.eat('OP', ']')
                e = N('Index', line=t.line, obj=e, idx=ix)
            elif t.kind == 'OP' and t.val == '?':
                s.next(); e = N('Try', line=t.line, e=e)
            elif t.kind == 'KW' and t.val == 'as' and not s.nocast:
                s.next(); e = N('Cast', line=t.line, e=e, type=s.type_())
            elif (t.kind == 'OP' and t.val == '{' and e.kind == 'Name'
                  and e.name[0].isupper()):
                e = s.record(e.name, t.line)
            else:
                return e

    def args(s):
        s.eat('OP', '('); out = []
        while not s.at('OP', ')'):
            s.skipnl(); out.append(s.expr()); s.skipnl()
            if not s.opt('OP', ','): break
        s.eat('OP', ')')
        return out

    def record(s, name, ln):
        s.eat('OP', '{'); fields = []
        while not s.at('OP', '}'):
            s.skipnl()
            k = s.eat('NAME').val
            v = s.expr() if s.opt('OP', ':') else N('Name', line=ln, name=k)
            fields.append((k, v))
            s.opt('OP', ','); s.skipnl()
        s.eat('OP', '}')
        return N('Record', line=ln, name=name, fields=fields)

    def primary(s):
        t = s.peek(); ln = t.line
        if t.kind == 'NUM':  s.next(); return N('Num', line=ln, v=t.val)
        if t.kind == 'STR':
            s.next()
            parts = [p if p[0] == 'lit'
                     else ('expr', Parser(lex(p[1] + '\n')).expr(), p[2]) for p in t.val]
            return N('Str', line=ln, parts=parts)
        if t.kind == 'KW':
            if t.val == 'true':  s.next(); return N('Bool', line=ln, v=True)
            if t.val == 'false': s.next(); return N('Bool', line=ln, v=False)
            if t.val == 'none':  s.next(); return N('NoneLit', line=ln)
            if t.val in ('ok', 'err', 'some'):
                s.next()
                stop = (s.at('NEWLINE') or s.at('OP', ')') or s.at('OP', ',')
                        or s.at('OP', ':') or s.at('EOF') or s.at('DEDENT'))
                return N('Wrap', line=ln, tag=t.val, e=None if stop else s.expr())
            if t.val == 'if':                          # if en expression (§3.4)
                s.next(); c = s.expr(); s.eat('OP', ':'); a = s.expr()
                s.eat('KW', 'else'); s.eat('OP', ':')
                return N('IfExpr', line=ln, cond=c, a=a, b=s.expr())
            if t.val == 'self': s.next(); return N('Name', line=ln, name='self')
        if t.kind == 'NAME': s.next(); return N('Name', line=ln, name=t.val)
        if t.kind == 'OP' and t.val == '(':
            s.next(); s.skipnl()
            if s.at('OP', ')'): s.next(); return N('Tuple', line=ln, items=[])
            items = [s.expr()]; s.skipnl()
            while s.opt('OP', ','):
                s.skipnl()
                if s.at('OP', ')'): break
                items.append(s.expr()); s.skipnl()
            s.eat('OP', ')')
            return items[0] if len(items) == 1 else N('Tuple', line=ln, items=items)
        if t.kind == 'OP' and t.val == '[':
            s.next(); items = []
            while not s.at('OP', ']'):
                s.skipnl(); items.append(s.expr()); s.skipnl()
                if not s.opt('OP', ','): break
            s.eat('OP', ']')
            return N('List', line=ln, items=items)
        if t.kind == 'OP' and t.val == '{':
            s.next(); pairs = []
            while not s.at('OP', '}'):
                s.skipnl(); k = s.expr(); s.eat('OP', ':'); pairs.append((k, s.expr()))
                s.skipnl()
                if not s.opt('OP', ','): break
            s.eat('OP', '}')
            return N('MapLit', line=ln, pairs=pairs)
        got = t.kind if t.kind in ('INDENT', 'DEDENT', 'NEWLINE', 'EOF') else t.val
        raise MiError('E112', ln, f'expression attendue, trouve {got}')


def parse(src, name='main'):
    return Parser(lex(src)).module(name)

# ═══════════════════════════════════════════════════════ valeurs

class Unit:
    _i = None
    def __new__(c):
        if c._i is None: c._i = super().__new__(c)
        return c._i
    def __repr__(s): return 'ok'
UNIT = Unit()

class NoneV(Unit):
    _i = None
    def __repr__(s): return 'none'
NONE = NoneV()

class Ok:
    __slots__ = ('v',)
    def __init__(s, v): s.v = v
    def __eq__(s, o): return isinstance(o, Ok) and s.v == o.v
    def __repr__(s): return 'ok' if s.v is UNIT else f'ok {show(s.v)}'

class Err:
    __slots__ = ('v',)
    def __init__(s, v): s.v = v
    def __eq__(s, o): return isinstance(o, Err) and s.v == o.v
    def __repr__(s): return f'err {show(s.v)}'

class Variant:
    __slots__ = ('name', 'payload')
    def __init__(s, name, payload=None): s.name, s.payload = name, payload
    def __eq__(s, o):
        return isinstance(o, Variant) and s.name == o.name and s.payload == o.payload
    def __hash__(s): return hash((s.name, s.payload))
    def __repr__(s):
        return s.name if s.payload is None else f'{s.name}({show(s.payload)})'

class Record:
    __slots__ = ('tname', 'f')
    def __init__(s, tname, f): s.tname, s.f = tname, f
    def __eq__(s, o): return isinstance(o, Record) and s.f == o.f
    def __repr__(s):
        return s.tname + '{' + ', '.join(f'{k}: {show(v)}' for k, v in s.f.items()) + '}'

class Fn:
    __slots__ = ('decl', 'env', 'name')
    def __init__(s, decl, env, name=None):
        s.decl, s.env, s.name = decl, env, name or getattr(decl, 'name', '<lambda>')

class Native:
    __slots__ = ('name', 'f')
    def __init__(s, name, f): s.name, s.f = name, f

class Mod:
    __slots__ = ('name', 'env', 'ast')
    def __init__(s, name, env, ast=None): s.name, s.env, s.ast = name, env, ast

def show(v):
    if v is True: return 'true'
    if v is False: return 'false'
    if isinstance(v, str): return v
    if isinstance(v, float): return f'{v:g}'
    if isinstance(v, list): return '[' + ', '.join(show(x) for x in v) + ']'
    if isinstance(v, tuple): return '(' + ', '.join(show(x) for x in v) + ')'
    if isinstance(v, dict):
        return '{' + ', '.join(f'{show(k)}: {show(x)}' for k, x in v.items()) + '}'
    return repr(v)

# signaux de controle
class RetSig(Exception):
    def __init__(s, v): s.v = v
class BrkSig(Exception): pass
class ContSig(Exception): pass
class PropSig(Exception):           # `?` remonte une erreur ou un none
    def __init__(s, v): s.v = v

# ═══════════════════════════════════════════════════════ mi api  (SPEC §7)

def api(mod):
    effects = sorted({e for d in mod.decls
                      if d.kind == 'Fn' and d.pub for e in d.effects})
    head = f'mod {mod.name}' + (' + ' + ' '.join(effects) if effects else '')
    lines, count = [head], 0
    for d in mod.decls:
        if d.kind == 'Type' and d.pub:
            sfx = ('  derive ' + ' '.join(d.derive)) if d.derive else ''
            lines.append(f'  {d.name}{d.body}{sfx}' if d.fields is not None
                         else f'  type {d.name} = {d.body}{sfx}')
            count += 1
        elif d.kind == 'Err' and d.pub:
            lines.append(f'  err {d.name} = {d.body}'); count += 1
        elif d.kind == 'Fn' and d.pub:
            ps = ', '.join((f'{p.mode} ' if p.mode else '') + p.name +
                           (f': {p.type}' if p.type else '') for p in d.params)
            sig = f'  pub fn {d.name}({ps})'
            if d.ret: sig += f' -> {d.ret}'
            if d.effects: sig += ' + ' + ' '.join(d.effects)
            lines.append(sig); count += 1
    # types internes atteignables depuis une signature publique : sans eux le
    # digest est incomplet — on ne peut pas traiter une erreur qu'on ignore.
    hidden = {d.name: d for d in mod.decls
              if d.kind in ('Type', 'Err') and not d.pub}
    changed = True
    while changed:
        changed = False
        joined = '\n'.join(lines)
        for nm, d in list(hidden.items()):
            if re.search(rf'\b{re.escape(nm)}\b', joined):
                lines.append(f'  err {d.name} = {d.body}' if d.kind == 'Err'
                             else f'  {d.name}{d.body}')
                del hidden[nm]; count += 1; changed = True

    import hashlib
    body = '\n'.join(lines)
    toks = len(re.findall(r'\w+|[^\w\s]', body))
    sha = hashlib.sha256(body.encode()).hexdigest()[:6]
    return body + f'\n# {count} items · {toks} tokens · sha {sha}'

# ═══════════════════════════════════════════════════════ interprete (draft)

class Env(dict):
    def __init__(s, parent=None): super().__init__(); s.parent = parent
    def look(s, k, line=0):
        e = s
        while e is not None:
            if k in e: return e[k]
            e = e.parent
        raise MiError('E320', line, f'nom inconnu {k!r}', 'annotate')
    def put(s, k, v):
        e = s
        while e is not None:
            if k in e: e[k] = v; return
            e = e.parent
        s[k] = v

def truthy(v):
    return not (v is False or v is NONE or v is None or
                (isinstance(v, (list, dict, str)) and len(v) == 0) or v == 0)

class Interp:
    def __init__(s, mods, allow=None):
        s.mods, s.allow, s.out = mods, allow, []

    # ── appel
    def call(s, f, args, line=0):
        if isinstance(f, Native): return f.f(*args)
        if not isinstance(f, Fn):
            raise MiError('E321', line, f'{show(f)} n\'est pas appelable')
        d = f.decl
        env = Env(f.env)
        names = d.params if d.kind == 'Fn' else [N('Param', name=p) for p in d.params]
        for i, p in enumerate(names):
            env[p.name] = args[i] if i < len(args) else NONE
        if d.kind == 'Lambda':
            return s.eval(d.body, env)
        try:
            return s.block(d.body, env)
        except RetSig as r:
            return r.v

    def block(s, stmts, env):
        last = UNIT
        for st in stmts:
            last = s.stmt(st, env)
        return last

    # ── instructions
    def stmt(s, st, env):
        k = st.kind
        if k == 'ExprStmt': return s.eval(st.expr, env)
        if k == 'Let':
            env[st.name] = s.eval(st.expr, env); return UNIT
        if k == 'LetTuple':
            v = s.eval(st.expr, env)
            for nm, x in zip(st.names, v): env[nm] = x
            return UNIT
        if k == 'Assign':
            v = s.eval(st.expr, env)
            t = st.target
            if st.op != '=':
                cur = s.eval(t, env)
                v = {'+=': lambda a, b: a + b, '-=': lambda a, b: a - b,
                     '*=': lambda a, b: a * b, '/=': lambda a, b: a / b}[st.op](cur, v)
            if t.kind == 'Name': env.put(t.name, v)
            elif t.kind == 'Index':
                o = s.eval(t.obj, env); o[s.eval(t.idx, env)] = v
            elif t.kind == 'Attr':
                o = s.eval(t.obj, env); o.f[t.name] = v
            else: raise MiError('E322', st.line, 'cible d\'affectation invalide')
            return UNIT
        if k == 'Return': raise RetSig(s.eval(st.expr, env) if st.expr else UNIT)
        if k == 'If':
            if truthy(s.eval(st.cond, env)): return s.block(st.body, Env(env))
            if st.els is not None: return s.block(st.els, Env(env))
            return UNIT
        if k == 'For':
            it = s.eval(st.iter, env)
            if isinstance(it, dict): it = list(it.items())
            for v in it:
                e2 = Env(env)
                if len(st.names) == 1: e2[st.names[0]] = v
                else:
                    for nm, x in zip(st.names, v): e2[nm] = x
                try: s.block(st.body, e2)
                except BrkSig: break
                except ContSig: continue
            return UNIT
        if k == 'While':
            while truthy(s.eval(st.cond, env)):
                try: s.block(st.body, Env(env))
                except BrkSig: break
                except ContSig: continue
            return UNIT
        if k == 'Match': return s.match(st, env)
        if k in ('Region', 'Par', 'With'):
            e2 = Env(env)
            if k == 'Region':
                renv = Env()
                # g.out(x) : promotion hors de l'arene. En draft tout est
                # compte par references, donc la copie est un non-evenement.
                renv['out'] = Native('out', lambda x: x)
                e2[st.name] = Mod(st.name, renv)
            if k == 'With':   e2[st.name] = s.eval(st.expr, env)
            return s.block(st.body, e2)
        if k == 'Spawn': return s.eval(st.expr, env)                 # sequentiel ici
        if k == 'Pass':  return UNIT
        if k == 'Break': raise BrkSig()
        if k == 'Continue': raise ContSig()
        if k == 'Prop':  return UNIT
        raise MiError('E323', st.line, f'instruction non geree {k}')

    def match(s, st, env):
        v = s.eval(st.subj, env)
        for pat, body in st.arms:
            e2 = Env(env)
            if s.fits(pat, v, e2):
                return s.block(body, e2)
        return UNIT

    def fits(s, pat, v, env):
        t = pat.tag
        if t == '_': return True
        if t == 'value': return s.eval(pat.expr, env) == v
        if t == 'none': return v is NONE
        if t == 'variant':
            return isinstance(v, Variant) and v.name == pat.ctor
        if t == 'some':
            if v is NONE: return False
            if pat.binds:
                if len(pat.binds) == 1: env[pat.binds[0]] = v
                else:
                    for nm, x in zip(pat.binds, v):
                        if nm != '_': env[nm] = x
            return True
        if t in ('ok', 'err'):
            want = Ok if t == 'ok' else Err
            if not isinstance(v, want): return False
            inner = v.v
            if pat.ctor:
                if not (isinstance(inner, Variant) and inner.name == pat.ctor):
                    return False
                if pat.binds: env[pat.binds[0]] = inner.payload
            elif pat.binds:
                env[pat.binds[0]] = inner
            return True
        return False

    # ── expressions
    def eval(s, e, env):
        k = e.kind
        if k == 'Num':     return e.v
        if k == 'Bool':    return e.v
        if k == 'NoneLit': return NONE
        if k == 'Name':    return env.look(e.name, e.line)
        if k == 'Str':
            out = []
            for p in e.parts:
                if p[0] == 'lit': out.append(p[1])
                else:
                    v = s.eval(p[1], env)
                    out.append(format(v, p[2]) if p[2] else show(v))
            return ''.join(out)
        if k == 'List':   return [s.eval(x, env) for x in e.items]
        if k == 'Tuple':  return tuple(s.eval(x, env) for x in e.items)
        if k == 'MapLit': return {s.eval(a, env): s.eval(b, env) for a, b in e.pairs}
        if k == 'Range':  return list(range(s.eval(e.lo, env), s.eval(e.hi, env)))
        if k == 'Lambda': return Fn(e, env)
        if k == 'Neg':    return -s.eval(e.e, env)
        if k == 'Not':    return not truthy(s.eval(e.e, env))
        if k == 'And':
            l = s.eval(e.l, env)
            return s.eval(e.r, env) if truthy(l) else l
        if k == 'Or':
            l = s.eval(e.l, env)
            if l is NONE or isinstance(l, Err) or l is False: return s.eval(e.r, env)
            return l
        if k == 'Bin':
            a, b = s.eval(e.l, env), s.eval(e.r, env)
            if e.op == '==': return a == b
            if e.op == '!=': return a != b
            try:
                return {'+': lambda x, y: x + y, '-': lambda x, y: x - y,
                        '*': lambda x, y: x * y, '/': lambda x, y: x / y,
                        '%': lambda x, y: x % y, '<': lambda x, y: x < y,
                        '<=': lambda x, y: x <= y, '>': lambda x, y: x > y,
                        '>=': lambda x, y: x >= y}[e.op](a, b)
            except TypeError:
                raise MiError('E310', e.line,
                              f'{e.op} indefini entre {type(a).__name__} et {type(b).__name__}')
        if k == 'IfExpr':
            return s.eval(e.a, env) if truthy(s.eval(e.cond, env)) else s.eval(e.b, env)
        if k == 'Cast':
            v = s.eval(e.e, env)
            if e.type.startswith(('i', 'u')): return int(v)
            if e.type.startswith('f'): return float(v)
            return v
        if k == 'Wrap':
            inner = s.eval(e.e, env) if e.e is not None else UNIT
            return {'ok': Ok, 'err': Err}[e.tag](inner) if e.tag != 'some' else inner
        if k == 'Try':
            v = s.eval(e.e, env)
            if isinstance(v, Ok): return v.v
            if isinstance(v, Err) or v is NONE: raise PropSig(v)
            return v
        if k == 'TupleGet': return s.eval(e.obj, env)[int(e.idx)]
        if k == 'Index':
            o, i = s.eval(e.obj, env), s.eval(e.idx, env)
            if isinstance(o, dict) and i not in o:
                raise MiError('E204', e.line, f'cle absente {show(i)}', 'upsert | get_or')
            return o[i]
        if k == 'Attr':
            o = s.eval(e.obj, env)
            if isinstance(o, Mod):    return o.env.look(e.name, e.line)
            if isinstance(o, Record): return o.f[e.name]
            return s.method(o, e.name, [], e.line)
        if k == 'Record':
            return Record(e.name, {k2: s.eval(v, env) for k2, v in e.fields})
        if k == 'RegionNew': return s.eval(e.e, env)
        if k == 'Call':
            f = s.eval(e.fn, env)
            return s.call(f, [s.eval(a, env) for a in e.args], e.line)
        if k == 'Method':
            o = s.eval(e.obj, env)
            args = [s.eval(a, env) for a in e.args]
            if isinstance(o, Mod): return s.call(o.env.look(e.name, e.line), args, e.line)
            return s.method(o, e.name, args, e.line)
        raise MiError('E324', e.line, f'expression non geree {k}')

    # ── methodes : la bibliotheque de base, ambiante (SPEC §13)
    def method(s, o, nm, a, line):
        def need(n):
            if len(a) < n: raise MiError('E325', line, f'{nm} attend {n} argument(s)')
        F = lambda f, x: s.call(f, [x], line)

        if isinstance(o, str):
            if nm == 'lower':  return o.lower()
            if nm == 'upper':  return o.upper()
            if nm == 'trim':   return o.strip()
            if nm == 'len':    return len(o)
            if nm == 'split':  return o.split() if not a else o.split(a[0])
            if nm == 'lines':  return o.splitlines()
            if nm == 'split_any':
                need(1); return [x for x in re.split('[' + re.escape(a[0]) + ']', o) if x]
            if nm == 'split_once':
                need(1)
                return tuple(o.split(a[0], 1)) if a[0] in o else NONE
            if nm == 'is_lower':    return o.isalpha() and o.islower()
            if nm == 'starts_with': return o.startswith(a[0])
            if nm == 'contains':    return a[0] in o
            if nm == 'replace':     return o.replace(a[0], a[1])
            if nm == 'stem':        return os.path.splitext(os.path.basename(o))[0]
            if nm == 'join':        return a[0].join(show(x) for x in a[0]) if False else o
        if isinstance(o, (list, tuple)):
            L = list(o)
            if nm == 'len':     return len(L)
            if nm == 'get':     return L[a[0]] if 0 <= a[0] < len(L) else NONE
            if nm == 'push':    o.append(a[0]); return UNIT
            if nm == 'pop':     return o.pop() if o else NONE
            if nm in ('map', 'par_map'): return [F(a[0], x) for x in L]
            if nm == 'filter':  return [x for x in L if truthy(F(a[0], x))]
            if nm == 'sort_by': return sorted(L, key=lambda x: F(a[0], x))
            if nm == 'take':    return L[:a[0]]
            if nm == 'sum':     return sum(L)
            if nm == 'join':    return a[0].join(show(x) for x in L)
            if nm == 'zip':     return list(zip(L, a[0]))
            if nm == 'collect': return L
            if nm == 'pairs':   return L
            if nm == 'enum':    return list(enumerate(L))
            if nm == 'find':    return L.index(a[0]) if a[0] in L else NONE
            if nm == 'from':    return L[a[0]:]
            if nm == 'dedup':
                seen, out = set(), []
                for x in L:
                    if x not in seen: seen.add(x); out.append(x)
                return out
        if isinstance(o, dict):
            if nm == 'len':    return len(o)
            if nm == 'get':    return o.get(a[0], NONE)
            if nm == 'set':    o[a[0]] = a[1]; return UNIT
            if nm == 'has':    return a[0] in o
            if nm == 'keys':   return list(o.keys())
            if nm == 'values': return list(o.values())
            if nm == 'pairs':  return list(o.items())
            if nm == 'to_map': return o
            if nm == 'upsert':
                need(3)
                o[a[0]] = F(a[2], o.get(a[0], a[1])); return UNIT
            if nm == 'drain':
                out = list(o.items()); o.clear(); return out
        if isinstance(o, (int, float)) and not isinstance(o, bool):
            if nm == 'clamp': return max(a[0], min(a[1], o))
            if nm == 'min':   return min(o, a[0])
            if nm == 'max':   return max(o, a[0])
            if nm == 'abs':   return abs(o)
        if isinstance(o, (list, tuple)) and nm == 'to_map': return dict(o)
        if isinstance(o, Ok) and nm == 'is_err':  return False
        if isinstance(o, Err) and nm == 'is_err': return True
        raise MiError('E326', line,
                      f'methode {nm!r} inconnue sur {type(o).__name__}', 'api')

# ═══════════════════════════════════════════════════════ chargement (SPEC §3.5)

def natives(out):
    g = Env()
    def mk(name, **fns):
        e = Env()
        for k, f in fns.items(): e[k] = Native(k, f)
        g[name] = Mod(name, e)
    mk('io',  print=lambda *x: (out.append(' '.join(show(v) for v in x)), UNIT)[1],
              eprint=lambda *x: (out.append('! ' + ' '.join(show(v) for v in x)), UNIT)[1])
    mk('proc', exit=lambda c=0: (_ for _ in ()).throw(SystemExit(int(c))))
    mk('log', warn=lambda *x: (out.append('warn: ' + ' '.join(show(v) for v in x)), UNIT)[1])
    g['env'] = Mod('env', Env())
    def _read(p):
        try:    return Ok(open(p, encoding='utf-8').read())
        except Exception: return Err(Variant('IoErr', p))
    def _glob(root, pat):
        import glob as G
        return sorted(G.glob(os.path.join(root, pat.replace('**/', '**/')), recursive=True))
    mk('fs', read_str=_read, read=_read, glob=_glob,
             exists=lambda p: os.path.exists(p))
    return g

def load(path, argv=()):
    out = []
    g = natives(out)
    g['env'].env['args'] = [os.path.basename(path), *argv]
    d = os.path.dirname(os.path.abspath(path))
    asts = {}
    for f in sorted(os.listdir(d)):
        if f.endswith('.mi'):
            asts[f[:-3]] = parse(open(os.path.join(d, f), encoding='utf-8').read(), f[:-3])
    envs = {}
    for name, m in asts.items():
        envs[name] = Env(g)
        if name != 'main': g[name] = Mod(name, envs[name], m)
    for name, m in asts.items():
        e = envs[name]
        for dcl in m.decls:
            if dcl.kind == 'Fn': e[dcl.name] = Fn(dcl, e)
            elif dcl.kind in ('Type', 'Err') and dcl.variants:
                for vn, payload in dcl.variants:
                    if payload: e[vn] = Native(vn, (lambda n: lambda x: Variant(n, x))(vn))
                    else:       e[vn] = Variant(vn)
    root = os.path.basename(path)[:-3]
    return asts, envs, g, out, root

def check_effects(asts, allow):
    if allow is None: return
    used = sorted({e for m in asts.values() for d in m.decls
                   if d.kind == 'Fn' for e in d.effects})
    bad = [e for e in used if e not in allow]
    if bad:
        raise MiError('E520', 0,
                      'module declare ' + ' '.join(bad) + ', non autorises',
                      '--allow ' + ' '.join(bad))

# ═══════════════════════════════════════════════════════ commandes

def cmd_run(path, argv, allow):
    asts, envs, g, out, root = load(path, argv)
    check_effects(asts, allow)
    it = Interp(asts, allow); it.out = out
    env = envs.get(root) or next(iter(envs.values()))
    if 'main' not in env:
        raise MiError('E410', 0, 'aucune fn main dans ' + root, 'add-main')
    code = 0
    try:
        r = it.call(env['main'], [])
        if isinstance(r, Err):
            out.append(f'! {show(r.v)}'); code = 1
    except PropSig as p:
        out.append(f'! {show(p.v)}'); code = 1
    except SystemExit as e:
        code = e.code or 0
    for l in out: print(l)
    return code

def gen(ty, rnd):
    t = (ty or 'i32').split('[')[0]
    if t == 'str':
        return ''.join(rnd.choice('ab c') for _ in range(rnd.randint(0, 12)))
    if t.startswith(('u', 'i')): return rnd.randint(0, 200)
    if t.startswith('f'):        return rnd.uniform(-100, 100)
    if t == 'Vec': return [rnd.randint(0, 50) for _ in range(rnd.randint(0, 6))]
    return rnd.randint(0, 100)

def cmd_test(path, seed=8821, cases=100, quiet=False):
    asts, envs, g, out, root = load(path)
    it = Interp(asts); it.out = out
    total = fails = 0
    for name, m in asts.items():
        env = envs[name]
        for d in m.decls:
            if d.kind != 'Test': continue
            import seal as _s
            if _s.is_waiver(d):
                if not quiet:
                    print(f'⊘ {d.name} · non teste : {_s.waiver_reason(d)}')
                continue
            total += 1
            nasrt = nprop = ncase = 0
            bad = None
            for st in d.body:
                if st.kind == 'Prop':
                    nprop += 1
                    rnd = random.Random(seed)
                    f = Fn(N('Lambda', params=[st.name], body=st.expr), env)
                    for _ in range(cases):
                        v = gen(st.type, rnd); ncase += 1
                        try:
                            if not truthy(it.call(f, [v])):
                                bad = (st.line, f'propriete fausse pour {show(v)!r}'); break
                        except RecursionError:
                            bad = (st.line, f'pile epuisee sur {show(v)!r} — '
                                            'limite de l\'amorce, pas du langage'); break
                        except (MiError, PropSig) as ex:
                            bad = (st.line, f'{ex} sur {show(v)!r}'); break
                    if bad: break
                else:
                    nasrt += 1
                    try:
                        if not truthy(it.stmt(st, Env(env))):
                            bad = (st.line, 'assertion fausse'); break
                    except (MiError, PropSig) as ex:
                        bad = (st.line, str(ex)); break
            if bad:
                fails += 1
                if not quiet: print(f'✗ {d.name}  ligne {bad[0]} : {bad[1]}')
            elif not quiet:
                bits = [f'{nasrt} assertions'] if nasrt else []
                if nprop: bits.append(f'{nprop} proprietes · {ncase} cas · graine {seed}')
                print(f'✓ {d.name} · ' + ' · '.join(bits))
    if not quiet: print(f'{total - fails}/{total} · graine {seed}')
    return (total, fails) if quiet else (1 if fails else 0)

def cmd_seal(path, budget=2000):
    """SPEC §5.1 : la porte. N'imprime rien d'autre que la liste d'obligations."""
    asts, envs, g, out, root = load(path)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import seal
    obs = seal.Sealer(asts, root).run()

    shown, spent, elided = [], 0, 0
    for o in obs:                       # budget plafonne, racines d'abord (§6.1)
        cost = len(str(o)) // 3
        if spent + cost > budget: elided += 1; continue
        shown.append(o); spent += cost
    for o in shown: print(o)
    if elided: print(f'… {elided} de plus, budget {budget} tokens atteint')

    total, fails = cmd_test(path, quiet=True)
    if fails: print(f'E420 {root}.mi  tests-rouges  {fails}/{total}  fix:mi test')

    errs = sum(1 for o in obs if o.sev == 'E') + (1 if fails else 0)
    obls = len(obs) - sum(1 for o in obs if o.sev == 'E')
    ok = not obs and not fails
    print(f'{obls} obligations · {errs} erreurs · sealed={"ok" if ok else "no"}')
    return 0 if ok else 1


def cmd_blind():
    import seal
    print('Ce que `mi seal` ne verifie PAS :')
    for b in seal.BLIND_SPOTS: print('  · ' + b)
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip()); return 2
    cmd = argv[1]
    rest = argv[2:]
    allow = None
    if '--allow' in rest:
        k = rest.index('--allow'); allow = []
        j = k + 1
        while j < len(rest) and not rest[j].startswith('-') and rest[j] != '--':
            allow.append(rest[j]); j += 1
        rest = rest[:k] + rest[j:]
    args = []
    if '--' in rest:
        k = rest.index('--'); args = rest[k+1:]; rest = rest[:k]
    path = rest[0] if rest else 'src/main.mi'
    try:
        if cmd == 'run':  return cmd_run(path, args, allow)
        if cmd == 'test': return cmd_test(path)
        if cmd == 'seal':
            b = 2000
            for a in rest[1:]:
                if a.startswith('--budget='): b = int(a.split('=')[1].rstrip('k')) * (
                    1000 if a.endswith('k') else 1)
            return cmd_seal(path, b)
        if cmd == 'blind':
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            return cmd_blind()
        if cmd == 'api':
            print(api(parse(open(path, encoding='utf-8').read(),
                            os.path.basename(path)[:-3]))); return 0
        if cmd == 'lex':
            for t in lex(open(path, encoding='utf-8').read()): print(t)
            return 0
        print(f'commande inconnue {cmd!r}'); return 2
    except MiError as e:
        loc = f'{os.path.basename(path)}:{e.line}' if e.line else os.path.basename(path)
        print(f'{e.code} {loc}  {e.msg}' + (f'  fix:{e.fix}' if e.fix else ''))
        return 1

def _boot(argv):
    """Un interprete a parcours d'arbre consomme ~15 trames Python par appel
    Mira. La VM a registres de la phase 1 n'aura pas cette contrainte."""
    import threading
    sys.setrecursionlimit(200_000)
    threading.stack_size(512 * 1024 * 1024)
    box = []
    t = threading.Thread(target=lambda: box.append(main(argv)))
    t.start(); t.join()
    return box[0] if box else 1

if __name__ == '__main__':
    # Lance comme script, ce fichier serait le module `__main__`, et seal.py
    # importerait un SECOND exemplaire sous le nom `mi` : deux classes N
    # distinctes, donc tous les isinstance du verificateur echouent en
    # silence. On repasse par le module pour n'en avoir qu'une.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mi as _mi
    sys.exit(_mi._boot(sys.argv))
