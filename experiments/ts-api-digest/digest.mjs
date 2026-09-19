// `mi api` pour TypeScript — extraction de surface publique via l'AST du
// compilateur TypeScript (pas de regex, pas de comptage d'accolades).
import { createRequire } from 'node:module'
const ts = createRequire(import.meta.url)('typescript')

const has = (n, k) => n.modifiers?.some(m => m.kind === k) ?? false
const isExported = n => has(n, ts.SyntaxKind.ExportKeyword)
const isPrivate  = n => has(n, ts.SyntaxKind.PrivateKeyword)

function jsdoc(node, sf, src, keepDoc) {
  if (!keepDoc) return ''
  const full = node.getFullText(sf)
  const own = src.slice(node.getStart(sf), node.end)
  const lead = full.slice(0, full.length - own.length)
  const m = lead.match(/\/\*\*[\s\S]*?\*\//g)
  return m ? m[m.length - 1] + '\n' : ''
}

function memberText(m, sf, src) {
  if (isPrivate(m)) return null
  if (m.body) return src.slice(m.getStart(sf), m.body.getStart(sf)).replace(/\s*$/, '')
  if (ts.isPropertyDeclaration(m) && m.initializer && !m.type)
    return src.slice(m.getStart(sf), m.initializer.getStart(sf)).replace(/[\s=]*$/, '')
  return m.getText(sf)
}

function declText(node, sf, src) {
  if (ts.isFunctionDeclaration(node))
    return node.body ? src.slice(node.getStart(sf), node.body.getStart(sf)).replace(/\s*$/, '')
                     : node.getText(sf)

  if (ts.isClassDeclaration(node)) {
    const head = src.slice(node.getStart(sf), node.members.pos).replace(/\s*$/, '')
    const body = node.members.map(m => memberText(m, sf, src)).filter(Boolean)
      .map(t => '  ' + t.trim())
    return head + '\n' + body.join('\n') + '\n}'
  }

  if (ts.isVariableStatement(node)) {
    const parts = node.declarationList.declarations.map(d => {
      if (d.type) return src.slice(d.getStart(sf), d.type.end)
      if (d.initializer) {
        const init = d.initializer.getText(sf)
        if (init.length <= 160) return d.getText(sf)
        return src.slice(d.getStart(sf), d.initializer.getStart(sf)) + '/* … */'
      }
      return d.getText(sf)
    })
    const kw = node.declarationList.flags & ts.NodeFlags.Const ? 'const'
             : node.declarationList.flags & ts.NodeFlags.Let ? 'let' : 'var'
    return (isExported(node) ? 'export ' : '') + kw + ' ' + parts.join(', ')
  }

  return node.getText(sf)   // interface, type, enum, module…
}

const NAMED = new Set([
  ts.SyntaxKind.InterfaceDeclaration, ts.SyntaxKind.TypeAliasDeclaration,
  ts.SyntaxKind.EnumDeclaration,
])

export function apiDigest(src, { keepDoc = false, file = 'x.ts' } = {}) {
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true)
  const imports = [], pub = [], internal = []

  for (const st of sf.statements) {
    if (ts.isImportDeclaration(st) || ts.isImportEqualsDeclaration(st)) {
      const m = st.getText(sf).match(/from\s+['"]([^'"]+)['"]/)
      if (m) imports.push(m[1].split('/').pop())
      continue
    }
    if (ts.isExportDeclaration(st)) { pub.push({ text: st.getText(sf), name: null }); continue }

    const name = st.name?.getText(sf)
      ?? st.declarationList?.declarations?.[0]?.name?.getText(sf) ?? null
    const text = jsdoc(st, sf, src, keepDoc) + declText(st, sf, src)
    const entry = { text, name }

    if (isExported(st)) pub.push(entry)
    else if (NAMED.has(st.kind)) internal.push(entry)
    // le reste (helpers privés, constantes internes) est jeté
  }

  // types internes atteignables depuis la surface publique
  let joined = pub.map(e => e.text).join('\n')
  for (let changed = true; changed; ) {
    changed = false
    for (const e of [...internal]) {
      if (e.name && new RegExp(`\\b${e.name}\\b`).test(joined)) {
        pub.push(e); internal.splice(internal.indexOf(e), 1)
        joined += '\n' + e.text; changed = true
      }
    }
  }

  const out = []
  if (imports.length) out.push('// imports: ' + [...new Set(imports)].sort().join(', '))
  out.push(...pub.map(e => e.text))
  return out.join('\n\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}

export function publicSymbols(src, file = 'x.ts') {
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true)
  const out = new Set()
  for (const st of sf.statements) {
    if (!isExported(st)) continue
    if (st.name) out.add(st.name.getText(sf))
    else if (st.declarationList)
      for (const d of st.declarationList.declarations) out.add(d.name.getText(sf))
  }
  return out
}
