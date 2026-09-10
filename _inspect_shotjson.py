# -*- coding: utf-8 -*-
import json, os
ROOT = r'D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows'
targets = ['06_shotlast_1216x832_Qwen2512_Fusion_01.json',
           '09_video_FL2VA_镜01_1280x736.json']
out = []
for t in targets:
    p = os.path.join(ROOT, t)
    wf = json.load(open(p, encoding='utf-8'))
    out.append('==== ' + t)
    for n in wf.get('nodes', []):
        nt = n.get('type')
        if nt in ('SaveImage', 'LoadImage', 'ETN_LoadVideo', 'LoadVideo', 'KSampler',
                  'EmptySD3LatentImage', 'EmptyLatentImage', 'SaveVideo', 'CreateVideo',
                  'VHS_VideoCombine', 'SaveAnimatedWEBP', 'SaveWEBM', 'SaveAnimatedWEBP'):
            out.append('%s|%s|%s' % (n.get('id'), nt, (n.get('widgets_values') or [])[:6]))
open(r'D:\code\voide\ComfyUI-MiniMax-H3-Workflow\_wf_info.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('done', len(out))
