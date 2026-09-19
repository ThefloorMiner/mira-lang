import fs from 'node:fs'
import path from 'node:path'
import { apiDigest, publicSymbols } from './digest.mjs'

const THRESHOLD = 8192, HEAD = 4096, TAIL = 1024
const MARKER = '\n\n[... tool result middle pruned ...]\n\n'
const dshPrune = s => s.length <= THRESHOLD ? s : s.slice(0, HEAD) + MARKER + s.slice(-TAIL)

const dir = process.argv[2]
const files = fs.readdirSync(dir).filter(f => f.endsWith('.ts')).sort()
const rows = []; let T = [0,0,0,0,0,0,0]

for (const f of files) {
  const src = fs.readFileSync(path.join(dir, f), 'utf8')
  if (src.length <= THRESHOLD) continue
  const p = dshPrune(src)
  const d = apiDigest(src, { file: f })
  const dd = apiDigest(src, { file: f, keepDoc: true })
  const syms = publicSymbols(src, f)
  const kp = [...syms].filter(s => new RegExp(`\\b${s}\\b`).test(p)).length
  const kd = [...syms].filter(s => new RegExp(`\\b${s}\\b`).test(d)).length
  const name = f.replace(/^core_/, '').replace('_src_', '/').replace(/^packages_\S*?__/, '')
  const r = [src.length, p.length, d.length, dd.length, syms.size, kp, kd]
  rows.push([name, ...r]); r.forEach((v, i) => T[i] += v)
}

const n = x => x.toLocaleString('en-US')
const pad = (s, w, r = true) => r ? String(s).padStart(w) : String(s).padEnd(w)
console.log(pad('fichier', 24, false) + pad('source', 9) + pad('head/tail', 10) + pad('digest', 8) + pad('+doc', 8) + pad('sym', 5) + pad('h/t', 5) + pad('dig', 5))
console.log('-'.repeat(74))
for (const r of rows) console.log(pad(r[0], 24, false) + pad(n(r[1]), 9) + pad(n(r[2]), 10) + pad(n(r[3]), 8) + pad(n(r[4]), 8) + pad(r[5], 5) + pad(r[6], 5) + pad(r[7], 5))
console.log('-'.repeat(74))
console.log(pad('TOTAL', 24, false) + pad(n(T[0]), 9) + pad(n(T[1]), 10) + pad(n(T[2]), 8) + pad(n(T[3]), 8) + pad(T[4], 5) + pad(T[5], 5) + pad(T[6], 5))
console.log()
const pc = (a, b) => (a / b * 100).toFixed(1).padStart(5)
console.log(`head/tail   : ${pc(T[1],T[0])} % des caracteres · ${pc(T[5],T[4])} % des symboles publics`)
console.log(`digest      : ${pc(T[2],T[0])} % des caracteres · ${pc(T[6],T[4])} % des symboles publics`)
console.log(`digest +doc : ${pc(T[3],T[0])} % des caracteres · ${pc(T[6],T[4])} % des symboles publics`)
