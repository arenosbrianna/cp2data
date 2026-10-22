p = 'v6/opt_policy.py'
t = open(p, encoding='utf8').read()
a = "return dict(k=k, B=B, W=W, Dl=Dl, cu=float(e.pen[k]) * self.cu_mult,"
assert t.count(a) == 1
t = t.replace(a, "return dict(k=k, code=str(e.code[k]), B=B, W=W, Dl=Dl, cu=float(e.pen[k]) * self.cu_mult,")
b = "        if self.par_alpha is not None:\n            iq = min(len(self.z) - 1, int(math.ceil((1 - self.par_alpha) * len(self.z))) - 1)"
assert t.count(b) == 1
c = """        if self.par_alpha is not None:
            pa = self.par_alpha
            for kv in filter(None, _os.environ.get('PAR_ALPHA_ITEM', '').split(',')):      # 2026-10-22: a lower service level for walk-in items with a 3-day life and lumpy use (env PAR_ALPHA_ITEM=TAM:0.5,TOG:0.5)
                if kv.split(':')[0] == p.get('code'): pa = float(kv.split(':')[1])
            iq = min(len(self.z) - 1, int(math.ceil((1 - pa) * len(self.z))) - 1)"""
t = t.replace(b, c)
open(p, 'w', encoding='utf8').write(t)
print('patched')
