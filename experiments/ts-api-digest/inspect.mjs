import fs from 'node:fs'
import { apiDigest, publicSymbols } from './digest.mjs'
const f = process.argv[2]
const src = fs.readFileSync(f, 'utf8')
console.log('=== symboles exportés détectés :', [...publicSymbols(src, f)].join(', '), '===\n')
console.log(apiDigest(src, { file: f }))
