---
name: grid-image-generator
description: 图片提示词生成指南 — 角色、场景、宫格图三类提示词规范
preconditions:
  - 已具备角色外貌 / 场景描述 / 分镜数据等输入
protocol:
  - prompts_count: 生成的提示词数量
---

# 图片提示词生成指南

本 SKILL 对应 `grid_prompt_generator` Agent，支持生成三类图片提示词：

1. **角色图片提示词** — 角色外貌与气质
2. **场景图片提示词** — 场景氛围与光线
3. **宫格图提示词** — 多镜头网格拼图

详细模板见 `reference/` 目录。

---

## 角色图片提示词

参考：`reference/character-prompt.md`

### 模板结构
```
[统一风格约束段], [颜值修饰 / 丑角豁免], [appearance 独有外貌与服装], cinematic portrait, high quality, consistent art style, no text, no watermark
```

### 统一约束前置内嵌（角色库 image_prompt 的标准写法，默认必须带）
- 写实CG融合风格、真实皮肤纹理、耐看颜值这三类约束**直接写进角色库该角色的 `image_prompt` 开头**（唯一风格，不靠下游二次拼接），任何消费 `image_prompt` 的角色图（三视图 / 全景 / 分镜首帧）都自动带约束。
- `image_prompt` 必须以 `stylized 3D Chinese anime character, premium 3D animated film quality, very realistic textured human skin with fine visible skin pores and natural skin grain, realistic non-plastic non-waxy skin material with soft natural highlights, subsurface scattering, expressive detailed anime eyes, cinematic lighting, 4K high-resolution textures, Chinese Guoman 3D style, East Asian anime face` 开头。
- 约束段后紧跟颜值修饰词（男性 `handsome and clean-cut facial features, a well-proportioned attractive face` / 女性 `pretty and lovely facial features, a well-proportioned attractive face`），**丑角豁免不写**。
- 之后接该角色独有的外貌 / 服装 / 道具描写（取自 extractor 的 `appearance`），末尾收 `cinematic portrait, high quality, consistent art style, no text, no watermark`。
- 下游引用时**不要重复堆叠约束词**：构建脚本 `role_look()` 截断到 `cinematic portrait` 之前即得人物主体，角色库已内置约束段就不再前置拼接风格段（幂等）；仅当旧角色库的 `image_prompt` 缺约束段时由 `STYLE_FUSION` 兜底补齐。

### 生成规则
- 以 `appearance`（外貌描述）为核心
- `personality` 决定气质基调（内敛/张扬/神秘等）
- `role` 决定服装和道具风格
- 必须包含 `cinematic portrait` + `consistent art style`
- 避免出现文字、签名、水印
- **下装必写（硬约束）**：服装段写全「上装 + 下装 + 鞋」；凡盖腿款式（`robe`/`gown`/`dress`/`tunic`/长衫/长袍/裙）必须同时写明内着裤装（如 `with matching full-length trousers beneath, fully and modestly dressed from head to toe, footwear included`）。禁止只写单件袍/裙，否则三视图会生成"袍下光腿/没裤子"。男=长裤+鞋，女=长裤（或裙装）+内衬长裤+鞋。`role_look()` 兜底不过关——**角色库 `image_prompt` 必须先写完整**。
- **道具与服装分离（只展示不手持）**：`image_prompt` 中禁止写「手持 X / 握着 X / 携带 X」，道具一律记入 `随身道具` 字段，由三视图道具板单独陈列；`role_look()` 会裁掉手持/携带词。（详见 `reference/character-prompt.md`）

### 颜值默认好看（除非剧本写丑）
- **默认给所有角色加"耐看"修饰词**：男性 `handsome and clean-cut facial features, a well-proportioned attractive face`，女性 `pretty and lovely facial features, a well-proportioned attractive face`（年龄中性，少年/中年都适用，年龄感由角色 prompt 自带）。
- **只有剧本"明确写丑"才豁免**：剧本原文用 `ugly / hideous / deformed / disfigured / scarred / scar on face / yellow teeth / rotten teeth / missing teeth / snaggletooth / pockmarked / harelip` 等描述角色（丑/畸形/毁容/脸部疤痕/黄牙/龅牙/烂牙/麻子）时，才不加颜值修饰，按剧本如实写。
- **凶悍/阴鸷/狰狞表情不等于丑**：写"面露凶相""凶悍""阴狠""狞笑"等**气质描写**的角色，仍要保证五官端正耐看（凶可以，脸不能歪）——如反派、打手只需保留凶悍表情/气质，不生成歪脸。
- 剧本写"五官普通""清瘦""憔悴""饱经风霜"等**不等于丑**，仍需保证五官端正、耐看，只保留年龄/气质差异（如少年的青涩、中年人的沧桑），不要生成歪脸/不对称脸/龅牙/暴牙/满脸皱纹未老先衰。
- **负面词必须加丑抑制**：`丑陋，畸形五官，歪斜五官，不对称脸，歪嘴，暴牙，龅牙，皱纹过多，未老先衰`。

### 写实CG融合风格（默认必须带，唯一风格）
角色图统一用**写实与CG融合的完美动漫人物**：3D 国漫动画电影质感——人物是"动漫造型"（动漫脸/发/设计），渲染走"写实质感"（真实皮肤纹理优先：细毛孔、自然皮纹、皮肤细节高分辨率、非塑料材质、柔和自然高光、次表面散射、自然光影、电影级布光）。**不做纯真人写实照片，也不做塑料卡通 CG**。
- **正向词**：`stylized 3D Chinese anime character, perfect fusion of realistic rendering and CG animation, premium 3D animated film quality, very realistic textured human skin, fine visible skin pores, natural skin grain and subtle realistic skin details, natural skin tones, realistic non-plastic non-waxy skin material with soft natural highlights, subsurface scattering, expressive detailed anime eyes with realistic iris depth, subtle natural facial micro-expressions` + `电影感氛围, 电影级布光, 浅景深, 4K高清纹理, 高精度3D模型, PBR材质, Chinese Guoman 3D style`。
  > 这组正向词即角色库 `image_prompt` 的**统一约束段**，必须**前置内嵌**到每个角色的 `image_prompt` 开头（入库时用英文化段落、并可保留中文氛围词），角色工作流/宫格图引用时**自带约束、不再重复拼接**；只有旧角色库缺约束段时才由构建脚本 `STYLE_FUSION` 兜底拼接。
- **负面词（双向抑制三个极端）**：抑制塑料感/光滑无毛孔 `塑料感，橡胶皮肤，蜡像质感，雕塑质感，玩具感，光洁塑料，陶瓷娃娃皮肤，光滑无毛孔，磨皮过度，滤镜磨皮，无皮肤纹理`；抑制纯2D动漫 `纯2D动漫，扁平卡通，二次元平面，日系动漫，厚涂，赛璐璐，漫画线稿，漫画脸`；抑制真人实拍 `真人实拍，真实人物照片，电影剧照，写实照片`（**不要**把"真人皮肤特写/毛孔"当负面——那会压掉真实皮肤纹理，得到塑料娃娃脸）。
- 加载角色 LoRA（国漫3D CG质感角色）强度 0.8 左右，保持"动漫造型+CG渲染"的融合风格。

---

## 场景图片提示词

参考：`reference/scene-prompt.md`

### 模板结构
```
[location], [time period], [lighting atmosphere], [scene description], [cinematic scene], [high quality], [consistent art style], [no text, no watermark]
```

### 生成规则
- 以 `location`（地点）为基础
- `time` 决定光线色调（白天/夜晚/黄昏）
- 场景氛围词：atmospheric, moody, warm, cold 等
- 必须包含 `cinematic scene` + `consistent art style`
- 避免出现文字、签名、水印

---

## 宫格图提示词

参考：`reference/shot-prompt.md`

### 四种模式

#### 首帧模式 (first_frame)
每个格子 = 一个镜头的起始画面，但必须严格生成用户指定的 `rows x cols` 总格数。

```
[rows x cols grid layout], exactly [rows*cols] visible panels, consistent art style, [style description],
格1: [shot 1 opening scene],
格2: [shot 2 opening scene],
格3: [shot 3 opening scene],
...
格N: [opening scene],
high quality, cinematic lighting, no merged panels, no missing panels, no text, no watermark
```

#### 首尾帧模式 (first_last)
保持首尾帧节奏感，但仍然必须严格生成用户指定的 `rows x cols` 总格数，不允许偷偷改成 `Nx2`。

```
[rows x cols grid layout], exactly [rows*cols] visible panels, consistent art style, [style description],
格1: [opening beat],
格2: [closing beat],
格3: [opening beat],
格4: [closing beat],
...
high quality, cinematic, continuous motion implied, no merged panels, no missing panels, no text
```

#### 多参考模式 (multi_ref)
所有格子都是同一镜头的不同角度/构图参考，但仍然必须严格生成用户指定的 `rows x cols` 总格数。

```
[rows x cols grid layout], exactly [rows*cols] visible panels, same scene different angles, [style description],
[main scene description],
格1: wide shot establishing,
格2: medium shot character focus,
格3: close-up detail,
格4: dramatic angle,
...
consistent lighting and color palette, no merged panels, no missing panels, no text
```

#### 角色三视图组合宫格图模式 (char_sheet)
角色素材包用的组合宫格图：左列 = 全身三视图（正/侧/背），右列 = 表情特写 +（该角色有随身道具时的）道具特写。
一张图同时拿到转身角度、表情、道具三样参考，配合第十三章做角色一致性验收。

```
[rows x cols grid layout], exactly [rows*cols] visible panels, consistent art style, [style description],
[a slim young Chinese fisherman boy in ragged patched hemp shirt, barefoot, sun-bronzed skin, short black hair tied with cloth strip],
Panel 1: full body front view standing, calm resolute expression,
Panel 2: full body side view, standing straight,
Panel 3: full body back view,
Panel 4: close-up bust portrait, calm steady expression,
Panel 5: close-up bust portrait, restrained suppressed expression, slightly furrowed brows and pressed lips,
Panel 6: close-up of the character's handheld prop accessory (仅限该角色「随身道具」字段列出的道具；无随身道具的角色不画道具格，表情特写占满整列), detailed prop,
same face, same costume, same character in all panels, no clone, clean light background, no text, no watermark
```

> **每角色对得上剧本设定**：宫格图里的角色描述必须直接用该角色在角色库中的 `image_prompt` / `appearance`（剧本原文的性别、年龄、身形、肤色、发型、服装、道具），**不能**所有角色套同一个模板、不能凭想象换服装发型。
> **道具按角色归属（谁有谁没有）**：宫格图的道具格/道具板只画该角色在角色库 `随身道具` 字段列出的道具（数组元素 = 有，列出道具名；**空数组 = 无随身道具**）。无道具角色**不画道具格**（表情特写占满右列）、提示词不得凭空写「手持 XX 道具 / 腰间别 XX」，防止模型给空手角色乱画道具导致全剧穿帮。多人可共持同一把（铁皮灯笼 = 金河帮标志，钱彪与打手甲可各提一把）。`build_new_workflows.py` 的 `char_3view_fusion()` 已按 `随身道具` 自动生成道具板、无道具角色自动改为表情板占满右列。
> **道具板只展示道具（硬约束）**：只要画了道具板/道具格，**必须只展示道具本身**——道具作为孤立物品特写、与角色分离，**禁止出现人物拿着/手持道具**（人物提灯笼、握刀、端筐等）。原型 `product display of the character's handheld props only` 会被模型理解成"展示角色手持道具"、常画成人拿道具。正向词改显式写 `shown alone as isolated standalone objects, detached from and not held by any character, no person holding/grabbing/wielding/carrying or touching the props, no human figure anywhere in the prop board`；负面词加「人物手持道具 / 手拿道具 / 拿着道具 / 人拿道具」。`char_3view_fusion()`（人物三视图）已用 `PROP_BOARD_ONLY` 常量注入，`build_new_workflows.py --chars-only` 重建即生效；人物只做三视图、不做全景图（全景/写实大图仅由场景三视图/全景工作流承担）。
> **三视图人脸一致（硬约束）**：同一角色的正面/侧面/背面 + 8 格表情必须是**同一张脸、同一发型、同一服装**，提示词必须显式写 `same face, same costume, same character in all areas` + `identical features, same hairstyle`；表情板每格再补 `all eight faces are the same person with the exact same face, identical features, same hairstyle and same CG skin shading`。三视图三个角度要 `same height and build in all three views, well-proportioned natural human body, realistic head-to-body ratio`，防止正侧背身高/头身比不一致。

> 布局注意：三块区域（三视图 / 表情 / 道具）要**自然拼接成一张完整插画**，提示词必须显式加 `seamless single illustration, no dividing lines, no grid lines, no borders, no panel outlines, no frames`，**不要写** "white dividing lines" 之类的分界线描述，否则模型会画出难看的白线格框。
> 表情板注意：仅用逗号罗列情绪词（如 `calm, happy, angry`）时模型常画出笼统/呆滞表情。要**逐格编号**指定，如 `panel 1: calm and composed with steady determined eyes, panel 2: gentle warm smile, ...`，并对每个表情补 1-2 个面部细节（眉/嘴/眼），末尾加 `all emotions clearly visible and exaggerated`；负面词加「面瘫表情 / 面无表情 / 表情呆滞 / 眼神空洞」。
> 风格一致性注意：表情板多格人脸**极易出现真人/纯2D动漫/塑料CG 三者漂移**。除末尾 `same face, same costume, same character in all areas` 外，必须在表情板段落后显式补 `all eight faces are the same person with the exact same face, identical features, same hairstyle and same CG skin shading, unified 3D animated film style in every expression panel`；负面词做**三向抑制**——同时加「塑料感 / 橡胶皮肤 / 蜡像质感 / 玩具感」（防塑料CG）、「纯2D动漫 / 扁平卡通 / 二次元平面 / 日系动漫 / 厚涂 / 赛璐璐 / 漫画线稿 / 漫画脸」（防扁平卡通）、「真人实拍 / 真实人物照片 / 电影剧照 / 写实照片 / 真人皮肤特写」（防真人照片）。统一加载"国漫3D CG质感角色"LoRA（强度约 0.8），固定融合风格。
> 负面词注意：角色宫格图里同一角色多格属于正常布局，**不能加**「人物分身 / 复制人 / 角色增殖 / 多人重叠」这类负面词，否则会抑制网格正常生成；改用「格子重叠 / 格子合并 / 格子缺失 / 人物溢出格子」。

### 通用规则
1. 提示词使用**英文**
2. 必须明确写出用户指定的 `rows x cols grid layout`
3. 必须包含 `consistent art style` 保持风格统一
4. 必须明确要求 `exactly N visible panels`
5. 必须明确要求 `no merged panels, no missing panels`
6. 避免在格子间出现分割线的描述
7. 尺寸建议：每格 960x540，总图 = 960×cols × 540×rows
8. 当存在参考图映射时，统一使用 `图片1/图片2/...` 指代参考图，不要把它和 `格1/格2/...` 混用

### 分镜五要素在提示词中的落地（五要素模板）
宫格图 / 首帧描述不能只写「角色+场景」，要按分镜五要素把镜头语言写进 prompt：
- **主体及环境**：`[who] in [location], [spatial relation]`
- **构图与空间**：`composition: foreground/midground/background, depth of field`
- **光影与色调**：`lighting: key light from [direction], warm/cool color grade, contrast`
- **摄影与成像**：`shot size [close-up/medium/wide], shallow/deep depth, lens [35mm/85mm]`
- **机位与角度**：`angle: [eye-level/high/three-quarter/over-shoulder CAM1]`

示例（`first_frame` 每格）：
```
Panel 1: close-up, eye-level, warm key light from left, frosty dawn harbor,
a 15-year-old fisherman boy ... , shallow depth of field, 3/4 front angle
```

> 竖屏 / 横屏用同一套五要素，仅「每格宽高比」随画幅变（见《全片宪法》画幅铁律）。
