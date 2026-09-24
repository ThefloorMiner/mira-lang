#!/usr/bin/env python3
"""Suite d'execution. Chaque programme de bootstrap/exec/ declare en premiere
ligne ce que son execution doit produire : `# expect: E330 assertion fausse`.

Un garde d'execution doit etre une erreur Mira nommee, pas un accident de
l'interprete : un ZeroDivisionError Python qui `s'arrete aussi` est un echec —
c'est exactement ce qu'`assert` doit empecher (§10.3)."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mi

def run(path):
    src = open(path, encoding='utf-8').read()
    want = src.split('\n', 1)[0].replace('# expect:', '').strip()
    try:
        mi.cmd_run(path, [], None)
        got = 'aucune erreur'
    except mi.MiError as e:
        got = f'{e.code} {e.msg}'
    except ZeroDivisionError:
        got = 'ZeroDivisionError (python)'
    except Exception as e:                   # tout accident reste un echec nomme
        got = type(e).__name__
    return want, got

def main():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exec')
    files = sorted(glob.glob(os.path.join(d, '*.mi')))
    bad = 0
    for f in files:
        want, got = run(f)
        name = os.path.basename(f)
        if want == got:
            print(f'  ✓ {name:22} {got}')
        else:
            bad += 1
            print(f'  ✗ {name:22} attendu {want} · obtenu {got}')
    print(f'{len(files) - bad}/{len(files)} programmes')
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
