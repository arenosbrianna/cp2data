p = 'v11/build_v11.py'
t = open(p, encoding='utf8').read()
a = "sim = FullSim(env, OptPolicy("
assert t.count(a) == 1
b = "STAPLES = tuple(c for c in STAPLES if c not in set(filter(None, os.environ.get('NO_STAPLE', '').split(','))))      # 2026-10-22: items bought as needed at the walk-in market (no stock floor): env NO_STAPLE=TAM,TOG\n"
t = t.replace(a, b + a)
open(p, 'w', encoding='utf8').write(t)
print('patched')
