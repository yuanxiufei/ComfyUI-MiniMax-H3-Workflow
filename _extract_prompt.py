# -*- coding: utf-8 -*-
import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

path = r'D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\09_video_FL2VA_镜01_1280x736.json'
d = json.load(open(path, encoding='utf-8'))
nodes = {n['id']: n for n in d['nodes']}

def dump(nid):
    nd = nodes.get(nid)
    print('='*72)
    print('Node', nid, nd.get('type'))
    wv = nd.get('widgets_values')
    if isinstance(wv, list):
        for i, v in enumerate(wv):
            if isinstance(v, str) and len(v) > 200:
                print('  [%d] (len=%d) >>>' % (i, len(v)))
                print(v)
                print('  <<<')
            else:
                print('  [%d] = %s' % (i, json.dumps(v, ensure_ascii=False)[:300]))
    else:
        print('  widgets_values =', json.dumps(wv, ensure_ascii=False)[:2000])

for nid in [5, 40]:
    dump(nid)
