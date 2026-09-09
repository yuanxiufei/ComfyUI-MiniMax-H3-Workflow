# 角色图片提示词模板

角色库（`03_角色场景/角色.json`）中每个角色存一条完整的 `image_prompt`，**统一约束前置内嵌在开头**，格式为一段连续英文（逗号分隔，无换行）。

## 模板结构

```
[统一约束段：stylized 3D Chinese anime character, premium 3D animated film quality, very realistic textured human skin
 with fine visible skin pores and natural skin grain, realistic non-plastic non-waxy skin material with soft natural
 highlights, subsurface scattering, expressive detailed anime eyes, cinematic lighting, 4K high-resolution textures,
 Chinese Guoman 3D style, East Asian anime face],
[颜值修饰词（丑角豁免不写）：handsome and clean-cut facial features, a well-proportioned attractive face 或
 pretty and lovely facial features, a well-proportioned attractive face],
[该角色独有的外貌/身形/服装/道具/状态描写：身份年龄身形 肤色 五官 发型 服装 随身道具],
cinematic portrait, high quality, consistent art style, no text, no watermark
```

- **约束段放最前面**（写实CG融合风格 + 真实皮肤纹理 + 国漫风格），保证任何消费该 `image_prompt` 的图（三视图 / 全景 / 分镜首帧）都自带统一风格，不需要下游二次拼接。
- **颜值词紧跟约束段**：男性 `handsome and clean-cut facial features, a well-proportioned attractive face`；女性 `pretty and lovely facial features, a well-proportioned attractive face`；丑角（剧本明写 ugly/scar/yellow teeth 等）**省略颜值词**，但约束段与独有描写保留。
- 角色独有描写只写该角色特征，**禁止**重复约束段里的皮肤/风格词。

## 示例（角色库实际入库格式）

```
stylized 3D Chinese anime character, premium 3D animated film quality, very realistic textured human skin with fine visible skin pores and natural skin grain, realistic non-plastic non-waxy skin material with soft natural highlights, subsurface scattering, expressive detailed anime eyes, cinematic lighting, 4K high-resolution textures, Chinese Guoman 3D style, East Asian anime face, handsome and clean-cut facial features, a well-proportioned attractive face, a slender 15-year-old Chinese fisherman boy in ragged patched hemp shirt tied with straw rope, barefoot with muddy feet, sun-bronzed skin, calm resolute eyes, short black hair tied with cloth strip, a bamboo fishing rod resting on his shoulder and a conical straw hat slung at his back, standing on an old boat deck, cinematic portrait, high quality, consistent art style, no text, no watermark
```

## 下装必写（硬约束，缺一不可）

- 时装/服装段必须写全「上装 + 下装 + 鞋」三段，尤其**下装/裤装不允许省略**（模型常把角色下半身画成光腿/没裤子/缩成短装/裙下露腿）。
- **盖腿款式必写下装**：凡出现 `robe`（长衫/长袍）、`gown`、`dress`、`tunic`、`long coat`（长衫/长袍/裙装/连衣裙）等盖腿词，**必须同时写明内着裤装**——例如 `wearing an elegant plain white ancient long robe with matching plain white full-length trousers and cloth boots beneath, fully and modestly dressed from head to toe`。
- 禁止只写单件袍/裙（如只写 `wearing an ancient robe` / `wearing an elegant dress`）——那会直接导致"袍下/裙下露腿、没裤子"。
- 男女通用：男=长裤+鞋；女=长裤（或裙装）+**内衬长裤**+鞋。
- 脚部有鞋：`with cloth boots / wearing shoes` 并入下装段；无裸足、无光脚。
- `role_look()`（三视图构建脚本）会对漏写下装的角色兜底注入"内着长裤、从头到脚完整着装"，但**角色库 `image_prompt` 必须先写完整、不依赖脚本兜底**。

## 颜值规则（默认好看，除非剧本写丑）

- **默认加耐看修饰**（年龄中性，少年/中年都适用，年龄感由角色 prompt 自带）：男性 `handsome and clean-cut facial features, a well-proportioned attractive face`；女性 `pretty and lovely facial features, a well-proportioned attractive face`。
- **豁免场景（不加颜值词）**：仅剧本**明确写丑**时才豁免——如 `ugly / hideous / deformed / disfigured / scarred / scar on face / yellow teeth / rotten teeth / missing teeth / snaggletooth / pockmarked / harelip`（丑/畸形/毁容/脸部疤痕/黄牙/龅牙/烂牙/麻子）。此时按剧本原样描写即可。
- **凶悍/阴鸷/狰狞表情不等于丑**：反派、打手等"面露凶相"的角色仍要五官端正耐看，只保留凶悍表情/气质，不生成歪脸。
- **"普通/清瘦/憔悴/沧桑"不是丑**：保留年龄与气质差异（少年的青涩、中年的风霜），但五官必须端正、对称、耐看，禁止歪脸、不对称脸、龅牙、暴牙、过度皱纹、未老先衰。

## 写实CG融合风格（默认必须带，唯一风格）

角色图统一用**写实与CG融合的完美动漫人物**（3D 国漫动画电影质感）——动漫造型 + 写实渲染（真实皮肤纹理优先，细毛孔/皮纹/非塑料材质，避免塑料娃娃脸）：

正向词（即角色库 `image_prompt` 的**统一约束段**，**前置内嵌到每个角色 image_prompt 开头**）：
```
stylized 3D Chinese anime character, perfect fusion of realistic rendering and CG animation, premium 3D animated film quality,
very realistic textured human skin, fine visible skin pores, natural skin grain and subtle realistic skin details, natural skin tones,
realistic non-plastic non-waxy skin material with soft natural highlights, subsurface scattering,
expressive detailed anime eyes with realistic iris depth, subtle natural facial micro-expressions,
电影感氛围, 电影级布光, 浅景深, 4K高清纹理, 高精度3D模型, PBR材质, Chinese Guoman 3D style
```

> 下游工作流引用：构建脚本 `role_look()` 截断到 `cinematic portrait` 之前即得到人物主体段；角色库已内置约束段就不再二次拼接风格词（幂等），仅对旧角色库缺约束段时用 `STYLE_FUSION` 兜底。

负面词（三向抑制，同时加）：
- 防塑料CG / 光滑无毛孔：`塑料感，橡胶皮肤，蜡像质感，雕塑质感，玩具感，光洁塑料，陶瓷娃娃皮肤，光滑无毛孔，磨皮过度，滤镜磨皮，无皮肤纹理`
- 防纯2D动漫：`纯2D动漫，扁平卡通，二次元平面，日系动漫，厚涂，赛璐璐，漫画线稿，漫画脸`
- 防真人照片：`真人实拍，真实人物照片，电影剧照，写实照片`（**不要**把"真人皮肤特写/毛孔"当负面——那会压掉真实皮肤纹理，得到塑料娃娃脸）

LoRA：加载"国漫3D CG质感角色"角色 LoRA，强度约 0.8，固定融合风格。

## 随身道具（谁有谁没有）

- 角色库（`03_角色场景/角色.json`）每条角色带 **`随身道具`** 数组，是道具归属的**唯一来源**：**空数组 = 该角色无随身道具**；非空数组列出该角色持有的道具名（如 `["铁皮灯笼", "短刀"]`）。
- 归属口径：**只认原著/剧本写出的随身物**，禁止凭空给角色补道具；反之角色卡明确写了随身物的（如钱彪腰别短刀、帮众提铁皮灯笼），必须写入该角色 `随身道具`。
- 有随身道具的角色：三视图宫格图右下道具板/道具格**只画该角色自己的道具**（`build_new_workflows.py` 按 `随身道具` 自动带入），且这些道具需同步写进该角色 `image_prompt` 的独有描写，保持角色卡与出图一致。
- **道具板只展示道具（硬约束）**：只要画了道具板/道具格，**必须只展示道具本身**——道具作为孤立物品特写、与角色分离，**禁止出现人物拿着/手持道具**（人物提灯笼、握刀、端筐等）。正向词显式写 `shown alone as isolated standalone objects, detached from and not held by any character, no person holding/grabbing/wielding/carrying or touching the props, no human figure anywhere in the prop board`；负面词加「人物手持道具 / 手拿道具 / 拿着道具 / 人拿道具」。`char_3view_fusion()`（人物三视图）已用 `PROP_BOARD_ONLY` 常量注入，`build_new_workflows.py` 重建即生效；人物只做三视图、不做全景图（全景/写实大图仅由场景三视图/全景工作流承担）。
- 无随身道具的角色：三视图**不设道具板**（表情特写占满右列），`image_prompt` / `appearance` 中不得出现「手持 XX / 腰别 XX」类字样，防止模型乱画道具、道具穿帮。
- 多人共有道具可各持一份（铁皮灯笼 = 金河帮标志道具，对应道具库 p001，钱彪与打手甲都写 `铁皮灯笼`）。
- 增删某角色随身道具时：同步改「角色库 `随身道具` 字段」+「该角色 `image_prompt` 道具描写」，再重跑 `scripts\build_new_workflows.py`。

## 三视图/表情板一致性（宫格图硬约束）

- 同一角色的全部区域（正/侧/背全身 + 8 格表情）必须是**同一张脸**：`same face, same costume, same character in all areas, identical features, same hairstyle`。
- 表情板每格：`all eight faces are the same person with the exact same face, identical features, same hairstyle and same CG skin shading`。
- 表情板风格统一：`unified 3D animated film style in every expression panel`。
- 三视图角度一致性：`same height and build in all three views, well-proportioned natural human body, realistic head-to-body ratio`。
- 角色描述直接取自角色库该角色的 `image_prompt` / `appearance`，**禁止跨角色套用模板**，保证每角色对上剧本设定。
