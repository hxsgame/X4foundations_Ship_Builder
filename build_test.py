# -*- coding: utf-8 -*-
def build(s):
    parts = s.split('/')
    def v(i): return parts[i].strip() if i < len(parts) else ''
    m0,m1,m2,m3 = v(0),v(1),v(2),v(3); tag = ''
    if m0: tag += ' missile="%s"' % m0
    if m1: tag += ' unit="%s"' % m1
    if m2: tag += ' deployable="%s"' % m2
    if m3: tag += ' countermeasure="%s"' % m3
    return tag
for s in ('100/20//','///','100/20/50/','300/40/60/70','320/20'):
    print('%-14r -> %r' % (s, build(s)))
