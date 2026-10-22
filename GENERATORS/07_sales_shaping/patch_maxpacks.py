p = 'v6/opt_policy.py'
t = open(p, encoding='utf8').read()
a = "        mmax = int(min(500, math.ceil(W.max() / pack) + math.ceil(mp) + 1))\n"
assert t.count(a) == 1
b = a + """        for kv in filter(None, _os.environ.get('MAX_PACKS_ITEM', '').split(',')):      # 2026-10-22 (user): small-pack items are bought a few packs at a time, never in big lots (env MAX_PACKS_ITEM=TAM:4,TOG:4)
            if kv.split(':')[0] == str(e.code[k]): mmax = max(int(math.ceil(mp)), min(mmax, int(kv.split(':')[1])))
"""
t = t.replace(a, b)
open(p, 'w', encoding='utf8').write(t)
print('patched')
