#!/usr/bin/env python3
"""Suite du verificateur. Chaque cas declare ses codes attendus en premiere
ligne : `# expect: E211 O410`, ou `# expect: sealed` pour un module propre."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mi, seal

def run(path):
    src = open(path, encoding='utf-8').read()
    want = src.split('\n', 1)[0].replace('# expect:', '').split()
    name = os.path.basename(path)[:-3]
    try:
        ast = mi.parse(src, name)
    except mi.MiError as e:
        return want, [f'PARSE:{e.code}@{e.line}'], str(e)
    obs = seal.Sealer({name: ast}, name).run()
    got = sorted(o.code for o in obs)
    if not got: got = ['sealed']
    return sorted(want), got, '\n'.join('      ' + str(o) for o in obs)

def main():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tests')
    files = sorted(glob.glob(os.path.join(d, '*.mi')))
    bad = 0
    for f in files:
        want, got, detail = run(f)
        name = os.path.basename(f)
        if want == got:
            print(f'  ✓ {name:22} {" ".join(got)}')
        else:
            bad += 1
            print(f'  ✗ {name:22} attendu {" ".join(want)} · obtenu {" ".join(got)}')
            if detail: print(detail)
    print(f'{len(files) - bad}/{len(files)} cas')
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
