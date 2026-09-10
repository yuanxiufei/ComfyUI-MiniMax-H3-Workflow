# -*- coding: utf-8 -*-
import json, io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def load(path):
    d = json.load(open(path, encoding='utf-8'))
    if 'nodes' in d and isinstance(d['nodes'], list):
        return ('UI', d['nodes'])
    if 'prompt' in d and isinstance(d['prompt'], dict):
        return ('API', d['prompt'])
    return ('API', d)

def to_nodes(fmt, data):
    out = {}
    if fmt == 'API':
        for k, v in data.items():
            if isinstance(v, dict) and 'class_type' in v:
                out[k] = v
    else:
        for n in data:
            out[n.get('id')] = n
    return out

def texts(nd):
    """gather readable string snippets from a node for both formats"""
    r = []
    def add(x):
        s = json.dumps(x, ensure_ascii=False)
        r.append(s)
    if 'widgets_values' in nd:
        add(nd['widgets_values'])
    if 'inputs' in nd:
        ins = nd['inputs']
        if isinstance(ins, dict):
            for k, v in ins.items():
                add(v)
        elif isinstance(ins, list):
            for it in ins:
                if isinstance(it, dict) and 'name' in it:
                    add(it.get('name'))
    return r

targets = {
 '01_char3view': r'workflows\01_char3view_1216x832_Qwen2512_Fusion.json',
 '05_first':     r'workflows\05_shotfirst_1216x832_Qwen2512_Fusion_02.json',
 '06_last':      r'workflows\06_shotlast_1216x832_Qwen2512_Fusion_01.json',
 '09_video':     r'workflows\09_video_FL2VA_镜01_1280x736.json',
}
for label, rel in targets.items():
    path = os.path.join(r'D:\code\voide\ComfyUI-MiniMax-H3-Workflow', rel)
    print('='*72)
    print(label, '->', rel)
    try:
        fmt, data = load(path)
        nodes = to_nodes(fmt, data)
    except Exception as e:
        print('ERR', e); continue
    print('format: %s, nodes: %d' % (fmt, len(nodes)))
    for nid, nd in nodes.items():
        ct = nd.get('class_type') or nd.get('type')
        print('  [%s] %s' % (nid, ct))
        for t in texts(nd):
            # only print text that looks meaningful (contains CJK, prompt keywords, path, voice/audio)
            if any(k in t for k in ('Voice','voice','speaker','Speaker','audio','Audio','prompt','Prompt','台词','对白','声音','@','.png','.mp3','.mp4','_','分镜','第1集','三视图','master','_c0','c01','c02','linxiao','suwan','陈庆','林萧')):
                print('        |', t[:700])
