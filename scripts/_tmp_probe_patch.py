# -*- coding: utf-8 -*-
"""离线自检 h3_avbank_probe 的补丁认领/让位逻辑（伪造 comfy，不加载 torch）。"""
import importlib.util
import sys
import types

PROBE = (r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes"
         r"\ComfyUI-H3-Multishot\h3_avbank_probe.py")


class Payload:
    def __init__(self):
        self.cond = {}


def _stock_extra_conds(self, **kwargs):
    """模拟 comfy 原版：refs 分支覆盖 cond_video_latents（即本模块要修的 bug）。"""
    payload = Payload()
    kf = kwargs.get("minimax_keyframes") or []
    refs = kwargs.get("minimax_refs") or []
    if kf:
        payload.cond["cond_video_latents"] = [k["latent"] for k in kf]
    if refs:
        payload.cond["cond_video_latents"] = [r["latent"] for r in refs]
    return {"minimax_payload": payload}


def _load():
    mb = types.ModuleType("comfy.model_base")
    mb.MiniMaxH3 = type("MiniMaxH3", (), {"extra_conds": _stock_extra_conds})
    sys.modules["comfy"] = types.ModuleType("comfy")
    sys.modules["comfy.model_base"] = mb
    nh = types.ModuleType("node_helpers")
    nh.conditioning_set_values = lambda c, v: c
    sys.modules["node_helpers"] = nh
    spec = importlib.util.spec_from_file_location("h3_avbank_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mb.MiniMaxH3


def _call(cls, kf=True, refs=True):
    kw = {"minimax_frame_count": 362}
    if kf:
        kw["minimax_keyframes"] = [{"latent": "KF", "resolved_frame_index": 0}]
    if refs:
        kw["minimax_refs"] = [{"latent": "R1", "audio_latent": None},
                              {"latent": "R2", "audio_latent": "A2"}]
    return cls.extra_conds(object(), **kw)["minimax_payload"].cond


def main():
    mod, cls = _load()
    stock = cls.extra_conds
    print("[1] 原版行为（bug 复现）:", _call(cls)["cond_video_latents"])

    mod._apply_merge_patch()
    fn1 = cls.extra_conds
    assert fn1 is not stock, "应已安装补丁"
    for mark in (mod._OWN_MARKER, mod._MC_MARKER, mod._DIRECTOR_PAYLOAD_MARKER):
        assert getattr(fn1, mark, False), "缺标记 %s" % mark
    cond = _call(cls)
    assert cond["cond_video_latents"] == ["KF", "R1", "R2"], cond
    assert cond["cond_audio_latents"] == ["A2"], cond
    assert cond["frame_count"] == 362, cond
    print("[2] 安装后：latents=%s audio=%s" % (
        cond["cond_video_latents"], cond["cond_audio_latents"]))
    # 复刻 Director 的 _classify_payload_owner 判定
    owner = "ours" if getattr(fn1, mod._DIRECTOR_PAYLOAD_MARKER, False) else "refuse"
    assert owner == "ours", "Director 仍会拒绝"
    print("[3] Director 认领判定:", owner)

    mod._apply_merge_patch()
    assert cls.extra_conds is fn1, "二次调用应无操作"
    print("[4] 幂等: OK")

    def _director_extra_conds(self, **kwargs):
        return _stock_extra_conds(self, **kwargs)
    setattr(_director_extra_conds, "_h3_director_continuity_payload_patch", True)
    cls.extra_conds = _director_extra_conds
    mod._apply_merge_patch()
    assert cls.extra_conds is not _director_extra_conds, "Director 先到时应叠加"
    cond2 = _call(cls)
    assert cond2["cond_video_latents"] == ["KF", "R1", "R2"], cond2
    assert cond2["cond_audio_latents"] == ["A2"], cond2
    print("[5] Director 先到 → 叠加后: %s" % cond2["cond_video_latents"])

    def _mc_extra_conds(self, **kwargs):
        return _stock_extra_conds(self, **kwargs)
    setattr(_mc_extra_conds, "_h3_motion_context_payload_patch", True)
    cls.extra_conds = _mc_extra_conds
    mod._apply_merge_patch()
    assert cls.extra_conds is _mc_extra_conds, "Motion-Context 先到时应让位"
    print("[6] Motion-Context 先到 → 让位: OK")
    print("ALL PASS")


main()
