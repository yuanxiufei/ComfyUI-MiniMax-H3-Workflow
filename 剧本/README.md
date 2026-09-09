# 剧本数据层（全片单一可信来源 / SSOT）

> 本目录是短剧生产的**数据层**，9 步流水线（`scripts/pipeline.py`）的前 6 步确定性环节
> 只读写这里的 JSON / 文本，不消耗算力。**字段契约一律以 `00_项目配置/全局硬约束（全片宪法）.md` 为准**——
> 本文只做目录索引与产物流向说明，不重复定义字段（避免双源漂移）。

---

## 一、目录结构与职责

| 目录 | 内容 | 写入方（流水线环节） | 备注 |
|---|---|---|---|
| `00_项目配置/` | 全片硬约束（宪法） | 人工 / 每剧一次性 | 唯一权威；字段与画幅/时长/分级/命名等硬约束集中在此 |
| `00_小说原文/` | 小说源文本 | 人工导入 | `script_rewriter` 的输入 |
| `01_剧本/` | 格式化剧本（`第X集_剧本.md`） | `script_rewriter` | `## S01` 场景头 + 逐角色分行对白 + 旁白单独成行 |
| `02_分镜/` | 分镜表（`第X集_分镜.json`） | `storyboard_breaker` | `shot_id` = `S1…`；下游 `qc`/`build`/`video` 的输入 |
| `03_角色场景/` | 角色 / 场景 / 道具 / 时代谱 | `extractor` | `角色.json`/`场景.json`/`道具.json`/`全书角色时代谱.md` |
| `04_音色/` | 音色库（`音色库.json`） | `voice_assigner` | `speaker_id` ↔ `voice_id` ↔ `voice_desc` |

## 二、产物流向（9 步流水线）

```
00_小说原文 ──(script_rewriter)──▶ 01_剧本 ──(extractor)──▶ 03_角色场景
      │                                            │
      └────────────(storyboard_breaker)────────────┘
                                    │
                         02_分镜 ──(voice_assigner)──▶ 04_音色
                                    │
                        (grid_prompt_generator / qc / build / submit / video)
```

- 前 6 步（`script_rewriter → extractor → storyboard_breaker → voice_assigner →
  grid_prompt_generator → qc`）纯读写本目录。
- `qc` 是分镜质量门禁（`qc_storyboard.py`，P0/P1/P2），默认只报告；`--qc-block` 时 P0 致命项硬阻断。
- `build → submit → video` 走向 `workflows/` 与 ComfyUI，本目录不再是输入源。

## 三、字段契约归属（SSOT）

| 数据 | 唯一权威定义处 | 校验脚本 |
|---|---|---|
| 角色 / 场景 / 道具 / 分镜字段 | 宪法 §17（`验证对象`） | `scripts/validate_db.py` |
| 数据引用 / id 唯一性 / speaker_id 归属 | 宪法 §17.5 | `validate_db.py`（`*-UNKNOWN`/`*-DUP`/`P1-SPK-*`） |
| 分镜质量门禁（时长 / 台词 / 场景类型） | 宪法 §18 | `scripts/qc_storyboard.py` |
| 命名 / 目录规范 | 宪法 §19 | — |

> **改字段必须先改宪法 §17**，再同步 `validate_db.py`，最后更新本文示例；
> 三者不得各自为政，否则出现"字段口径"与"校验器"不一致的穿帮。

## 四、当前数据集（《剑噬天下》）

| 子目录 | 文件 |
|---|---|
| `00_小说原文` | `《剑噬天下》（精校全本）.txt` |
| `01_剧本` | `第1集_剧本.md` |
| `02_分镜` | `第1集_分镜.json` |
| `03_角色场景` | `角色.json` / `场景.json` / `道具.json` / `全书角色时代谱.md` |
| `04_音色` | `音色库.json` |
