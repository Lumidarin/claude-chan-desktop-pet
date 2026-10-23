# -*- coding: utf-8 -*-
"""
把修好的 See-through 拆层 PSD 整理成 Anime2.5DRig 认的命名（MIT，https://github.com/852wa/Anime2.5DRig）

按它 README 的建议和命名规约：
  - neck 并进 topwear（分开时转头会在脖子和身体交界处破面）
  - See-through 的 mouth 实际是闭着的嘴 → mouth_close；我们画的“张嘴a”差分 → mouth_open
    （否则 mouth 会被自动当成 mouth_open）
  - 我们画的“闭眼”差分 → eye_close（不用它内置的通用闭眼）
  - flower 并进 headwear（花和缎带都跟头走）
  - handwear_behind 并进 topwear 底下（它不认这个名字）
  - 表情差分组不带进来（隐藏层它也不读，且免得混淆）
输入：art/Claude娘_seethrough拆层.psd；输出：art/Claude娘_rig.psd
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = ROOT / "art" / "Claude娘_seethrough拆层.psd"
DIFFS = ROOT / "art" / "差分" / "精选"
OUT = ROOT / "art" / "Claude娘_rig.psd"
ORIG = ROOT / "art" / "定稿底图_v3_本地精修1536.png"
CHANGED_ONLY = {"张嘴a"}   # 这些差分只取“和定稿图不一样”的像素
CHANGED_TOL = 22           # 每通道差多少以上算改过
SIL_COLOR = (30, 28, 36)   # 剪影深色底的颜色（接近描线色）
SIL_TOP = 0.42             # 剪影只做这条线（画布高度比例）以下的身体：缝出在手臂和身体，头部用不着
SIL_EXCLUDE = {"handwear"}  # 这些层不算进剪影（会动的手和前臂）
SIL_SHRINK = 2            # 剪影向内收几像素，免得露出轮廓外

# 下 → 上；每项 (输出名, [按从下到上合并的源层])
# 用户定的层序：人物剪影的深色底 → 桌子 → 书 → 人物。桌子和书是补全过的完整贴图（desk_layers.py），
# 手臂一抬露出的是完整书页；部件之间有缝时露出深色底，而不是背景（不会“裂开”）。
DESK_DIR = ROOT / "art" / "书桌"
PLAN = [
    ("silhouette",  ["#silhouette"]),
    ("desk",        ["#desk"]),
    ("book",        ["#book"]),
    ("back hair",   ["back hair"]),
    ("topwear",     ["handwear_behind", "topwear", "neck"]),
    ("handwear",    ["handwear"]),
    ("ears",        ["ears"]),
    ("face",        ["face"]),
    ("mouth_close", ["mouth"]),
    ("mouth_open",  ["@张嘴a"]),
    ("nose",        ["nose"]),
    ("facedetail",  ["facedetail"]),
    ("eyebrow",     ["eyebrow"]),
    ("eyewhite",    ["eyewhite"]),
    ("eyelash",     ["eyelash"]),
    ("irides",      ["irides"]),
    ("eye_close",   ["@闭眼"]),
    ("front hair",  ["front hair"]),
    ("headwear",    ["headwear", "flower"]),
]


def main():
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import Tag

    src = PSDImage.open(SRC)
    W, H = src.size
    canvases = {}
    for l in src.descendants():
        if l.is_group() or (l.parent is not src and not l.parent.visible):
            continue
        im = l.topil()
        if im is None:
            continue
        c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        c.paste(im.convert("RGBA"), (l.left, l.top))
        canvases[l.name] = c

    import numpy as np, cv2
    base_full = np.array(Image.open(ORIG).convert("RGB").resize((W, H), Image.LANCZOS)).astype(int)

    # 原图里书桌露在外面的地方：人物各层在这里一律裁掉（书桌现在在人物下面，
    # 人物层补画出来、原本被书桌挡住的部分不能盖住书桌）
    desk_vis = np.zeros((H, W), bool)
    if "desk" in canvases:
        a = np.array(canvases["desk"].getchannel("A")) > 128
        n, lab, st, cen = cv2.connectedComponentsWithStats(a.astype(np.uint8), 8)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] >= 200 and cen[i][0] < W * 0.45:
                desk_vis |= lab == i
    keep_person = Image.fromarray(np.where(desk_vis, 0, 255).astype(np.uint8))
    person = {}                                        # 裁过的人物层，算剪影用

    def get(name):
        if name.startswith("#"):                       # 书桌贴图 / 剪影
            if name == "#silhouette":
                # 只要身体，不要手：手一抬，剪影里手的形状会留在原处成一块黑影
                acc = np.zeros((H, W), np.uint8)
                for nm, im in person.items():
                    if nm not in SIL_EXCLUDE:
                        acc = np.maximum(acc, np.array(im.getchannel("A")))
                sil = cv2.erode((acc > 128).astype(np.uint8), np.ones((SIL_SHRINK * 2 + 1,) * 2, np.uint8))
                sil[:int(H * SIL_TOP)] = 0
                out = np.zeros((H, W, 4), np.uint8); out[..., :3] = SIL_COLOR; out[..., 3] = sil * 255
                return Image.fromarray(out, "RGBA")
            p = DESK_DIR / f"{name[1:]}.png"
            return Image.open(p).convert("RGBA") if p.exists() else None
        if name.startswith("@"):            # 我们自己画的差分（1536 坐标）
            p = DIFFS / f"{name[1:]}_图层.png"
            if not p.exists():
                return None
            im = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
            if name[1:] in CHANGED_ONLY:
                # 只留和定稿图相比真正改了的像素（嘴本身），去掉差分自带的那圈椭圆肤色补丁：
                # 说话时 mouth_open 会被上下拉伸、淡入淡出，补丁跟着变形就成了一块贴片
                arr = np.array(im)
                changed = np.abs(arr[..., :3].astype(int) - base_full).max(axis=2) > CHANGED_TOL
                changed &= arr[..., 3] > 128
                # 只留最大一块（嘴本身），去掉下巴阴影边缘、补丁边缘那些零星的差异
                n, lab, st, _ = cv2.connectedComponentsWithStats(changed.astype(np.uint8), connectivity=8)
                if n > 1:
                    changed = lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
                changed = cv2.dilate(changed.astype(np.uint8), np.ones((3, 3), np.uint8))
                changed = cv2.GaussianBlur(changed.astype(np.float32), (0, 0), 0.8)
                arr[..., 3] = (arr[..., 3].astype(np.float32) * np.clip(changed, 0, 1)).astype(np.uint8)
                im = Image.fromarray(arr, "RGBA")
            return im
        im = canvases.get(name)
        if im is None:
            return None
        im = im.copy()
        im.putalpha(Image.fromarray(np.minimum(np.array(im.getchannel("A")), np.array(keep_person))))
        person[name] = im
        return im

    # 必须 RGBA：RGB 文档里 psd-tools 会把透明度存成图层蒙版，ag-psd 不读蒙版 → 透明处变实底
    psd = PSDImage.new("RGBA", (W, H))

    def build(parts):
        acc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        found = False
        for p in parts:
            im = get(p)
            if im is not None:
                acc.alpha_composite(im); found = True
        return acc if found else None

    # 两遍：剪影要等所有人物层裁完才能算，但它排在最底下
    built = {out_name: build(parts) for out_name, parts in PLAN if parts != ["#silhouette"]}
    for out_name, parts in PLAN:
        acc = built[out_name] if out_name in built else build(parts)
        bb = acc.getchannel("A").getbbox() if acc is not None else None
        if not bb:
            print("  跳过（没有像素）:", out_name); continue
        lay = PixelLayer.frompil(acc.crop(bb), psd, out_name, top=bb[1], left=bb[0])
        lay.tagged_blocks.set_data(Tag.UNICODE_LAYER_NAME, out_name)
        psd.append(lay)
        print(f"  {out_name:12s} ← {parts}")
    psd.save(OUT)
    print("已保存：", OUT)


if __name__ == "__main__":
    main()
