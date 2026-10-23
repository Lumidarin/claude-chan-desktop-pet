# -*- coding: utf-8 -*-
"""
See-through 拆层结果的后处理 → 可以直接进 Live2D / Anime2.5DRig 的 PSD

See-through 只认身体部位，对这张图有三个问题，这里自动修：
  1. 道具丢了：头上的大橙花、书桌和书不在任何图层里。
     做法：原图前景里、所有图层都没盖到的像素 → 按位置分成 flower（头部）和 desk（下半）两层，像素取自原图。
  2. 层序：handwear（手臂）整层在 topwear（上衣）上面，可它补画出来的“被披肩挡住的那段袖子”也就跑到披肩前面了。
     做法：手臂图层里和原图颜色一致的 = 看得见的部分，留在原位；其余 = 被挡住的部分，单独一层放到 topwear 下面。
  3. 表情差分：把 art/差分/精选 的 9 个图层按比例缩放进来，放进“表情差分”组（默认隐藏）。

图层名沿用 See-through 的英文命名（Anime2.5DRig 等工具按这套名字识别），新加的层也用英文。
输入：tools/see-through/workspace/layerdiff_output/claude_v3.psd + art/定稿底图_v3_本地精修1536.png
输出：art/Claude娘_seethrough拆层.psd、art/_seethrough_修复后对比.jpg
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
ST_PSD = ROOT / "tools" / "see-through" / "workspace" / "layerdiff_output" / "claude_v3.psd"
ORIG = ROOT / "art" / "定稿底图_v3_本地精修1536.png"
DIFFS = ROOT / "art" / "差分" / "精选"
OUT = ROOT / "art" / "Claude娘_seethrough拆层.psd"
CHECK = ROOT / "art" / "_seethrough_修复后对比.jpg"
EXPR = ["闭眼", "半闭眼", "微笑", "张嘴a", "张嘴o", "脸红", "星星眼", "爱心眼", "晕圈眼"]

MISSING_MIN_AREA = 200   # 漏掉的像素块至少这么大才算道具（去掉描边残渣）
VISIBLE_TOL = 35         # 手臂像素和原图每通道差多少以内算“看得见”
FLOWER_FIX_TOL = 45      # 花附近合成结果和原图差多少算“画错了”，从原图取回
FLOWER_PAD = 90          # “花附近”= 花的主体向外扩这么多像素
PETAL_MAX_G = 112        # 花瓣（偏红的深橙，实测约 250,100,10）绿通道上限；头发约 245,120~130,30
PETAL_MAX_B = 22         # 花瓣蓝通道上限
NO_RECOLOUR_NEAR_EYE = {"face", "facedetail", "nose", "ears", "eyebrow"}   # 这些层在眼睛附近不做可见区校色
VISIBLE_SHARE = 0.5     # 某层在这个像素的露出份额超过这个，就把它这里的颜色换成原图的
HOLE_ALPHA = 0.8        # 叠完 alpha 低于这个、原图却是角色的像素算“洞”，垫到后发下面
EYE_NEAR = 18          # 离眼睛图层这么近的漏网碎片算眼睛的一部分

sys.path.insert(0, str(HERE))
from make_sprite import foreground_alpha   # noqa: E402


def main():
    import numpy as np, cv2
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer, Group
    from psd_tools.constants import Tag

    st = PSDImage.open(ST_PSD)
    W, H = st.size
    orig_full = Image.open(ORIG).convert("RGB")
    orig = np.array(orig_full.resize((W, H), Image.LANCZOS)).astype(int)
    fg = np.array(foreground_alpha(orig_full).resize((W, H), Image.LANCZOS)) > 128

    # ---- 读出 See-through 的图层（铺满画布的 RGBA 数组），保持原顺序 ----
    order, layers = [], {}
    for l in st.descendants():
        if l.is_group():
            continue
        im = l.topil()
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if im is not None:
            canvas.paste(im.convert("RGBA"), (l.left, l.top))
        order.append(l.name)
        layers[l.name] = np.array(canvas)
    union = np.zeros((H, W), np.uint8)
    for arr in layers.values():
        union = np.maximum(union, arr[..., 3])

    def from_orig(mask):
        m = cv2.GaussianBlur(mask.astype(np.uint8) * 255, (0, 0), 0.7)
        arr = np.zeros((H, W, 4), np.uint8)
        arr[..., :3] = orig
        arr[..., 3] = m
        return arr

    # ---- 1. 漏掉的道具：花、书桌 ----
    missing = fg & (union < 40)
    missing = cv2.morphologyEx(missing.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(missing, connectivity=8)
    flower = np.zeros((H, W), bool)
    desk = np.zeros((H, W), bool)
    bits = np.zeros((H, W), bool)       # 头部的其他漏网碎片（多是 See-through 漏掉的眼睛描线）
    top = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= MISSING_MIN_AREA and cent[i][1] < H * 0.45]
    flower_id = max(top, key=lambda i: stats[i, cv2.CC_STAT_AREA]) if top else None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < MISSING_MIN_AREA:
            continue
        if i == flower_id:
            flower[lab == i] = True                  # 只有最大的一块是花
        elif cent[i][1] < H * 0.45:
            bits[lab == i] = True
        else:
            desk[lab == i] = True
    print(f"  flower: {flower.sum()} px   desk: {desk.sum()} px   head bits: {bits.sum()} px")

    # 碎片里靠近眼睛的并进睫毛层（闭眼时跟着淡出，否则会留下睁眼残影），其余单独成 facedetail 层
    eye_a = np.zeros((H, W), np.uint8)
    for k in ("eyewhite", "irides", "eyelash"):
        if k in layers:
            eye_a = np.maximum(eye_a, layers[k][..., 3])
    # 阈值别用 > 0：See-through 的图层整张都有极淡的 alpha 噪点，会让“眼睛附近”扩到大半张图
    near_eye = cv2.dilate((eye_a > 96).astype(np.uint8), np.ones((EYE_NEAR * 2 + 1,) * 2, np.uint8)) > 0
    eye_bits, other_bits = bits & near_eye, bits & ~near_eye
    if eye_bits.any() and "eyelash" in layers:
        add = from_orig(eye_bits)
        base = Image.fromarray(layers["eyelash"], "RGBA")
        base.alpha_composite(Image.fromarray(add, "RGBA"))
        layers["eyelash"] = np.array(base)
    print(f"  head bits → eyelash {eye_bits.sum()} px, facedetail {other_bits.sum()} px")

    # ---- 2. 手臂拆成看得见 / 被挡住两层 ----
    hw = layers.get("handwear")
    hw_behind = None
    if hw is not None:
        diff = np.abs(hw[..., :3].astype(int) - orig).max(axis=2)
        vis = (hw[..., 3] > 128) & (diff < VISIBLE_TOL) & fg
        vis = cv2.morphologyEx(vis.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        vis = cv2.GaussianBlur(vis.astype(np.float32), (0, 0), 0.8)
        a = hw[..., 3].astype(np.float32)
        front = hw.copy(); front[..., 3] = (a * vis).astype(np.uint8)
        hw_behind = hw.copy(); hw_behind[..., 3] = (a * (1 - vis)).astype(np.uint8)
        layers["handwear"] = front
        print(f"  handwear: visible {(front[..., 3] > 128).sum()} px, hidden {(hw_behind[..., 3] > 128).sum()} px")

    # ---- 新的层序（下 → 上）----
    final = []
    for name in order:
        if name == "topwear" and hw_behind is not None:
            final.append(("handwear_behind", hw_behind))
        final.append((name, layers[name]))
        if name == "topwear" and desk.any():
            final.append(("desk", from_orig(desk)))    # 书桌在身体前、手后
    if other_bits.any():
        final.append(("facedetail", from_orig(other_bits)))
    if flower.any():
        # 花瓣和头发颜色接近，有一部分被 See-through 拆进了发层（画成了头发）。
        # 在花附近，凡是合成结果和原图差得多的前景像素，也收进花这一层（取原图像素，盖在最上面）
        comp = np.zeros((H, W, 3), np.float32)
        for _, arr in final:
            al = arr[..., 3:4].astype(np.float32) / 255
            comp = comp * (1 - al) + arr[..., :3].astype(np.float32) * al
        wrong = fg & (np.abs(comp - orig).max(axis=2) > FLOWER_FIX_TOL)
        # “花附近”= 花本身向外扩 FLOWER_PAD（按形状扩，不用外接矩形，免得框进眼睛）；
        # 种子 + 附近画错的像素围一个凸包 = 整朵花的轮廓，凸包内的前景全从原图取（花在最上层，原图这里就是花）
        near = cv2.dilate(flower.astype(np.uint8), np.ones((FLOWER_PAD * 2 + 1,) * 2, np.uint8)) > 0
        cand = flower | (wrong & near & ~near_eye)
        hull = cv2.convexHull(np.argwhere(cand)[:, ::-1].astype(np.int32))
        filled = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(filled, hull, 1)
        # 凸包会圈进花旁边的头发和耳朵：只留花瓣色（比头发偏红，绿通道低）的像素，
        # 稍微外扩带上黑描线，再把轮廓里的洞（黄花心、花蕊描线）填满
        petal = (filled > 0) & (orig[..., 0] > 190) & (orig[..., 1] < PETAL_MAX_G) & (orig[..., 2] < PETAL_MAX_B)
        petal = cv2.morphologyEx(petal.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n_p, lab_p, st_p, _ = cv2.connectedComponentsWithStats(petal, connectivity=8)
        if n_p > 1:
            petal = (lab_p == 1 + int(np.argmax(st_p[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)   # 最大一块 = 花
        petal = cv2.dilate(petal, np.ones((7, 7), np.uint8))
        outside = np.zeros((H + 2, W + 2), np.uint8)
        cv2.floodFill(petal.copy(), outside, (0, 0), 1, flags=cv2.FLOODFILL_MASK_ONLY | (1 << 8))
        flower = (outside[1:-1, 1:-1] == 0) & fg & (filled > 0)
        flower = cv2.morphologyEx(flower.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
        final.append(("flower", from_orig(flower)))    # 花在最上面

    # ---- 4. 补洞：原图里有角色、所有图层叠完却还透明的地方（比如头顶：后发层只剩一条轮廓线，
    #         前发又没盖到那么高 → 透出背景）。从原图取像素，垫在最底层后发的下面 ----
    comp_a = np.zeros((H, W), np.float32)
    for _, arr in final:
        al = arr[..., 3].astype(np.float32) / 255
        comp_a = comp_a + al * (1 - comp_a)
    holes = fg & (comp_a < HOLE_ALPHA)
    holes = cv2.dilate(holes.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & fg
    if holes.any() and final and final[0][0] == "back hair":
        under = Image.fromarray(from_orig(holes), "RGBA")
        under.alpha_composite(Image.fromarray(final[0][1], "RGBA"))
        final[0] = ("back hair", np.array(under))
    print(f"  holes filled under back hair: {holes.sum()} px")

    # ---- 5. 可见区校色：See-through 补画的部分颜色常常发灰、偏绿（头顶、缎带下的后发），
    #         静止时露在外面就是色差。从上往下算每个像素实际露出的是哪一层，
    #         把那一层在这里的颜色换成原图的；被挡住的补画部分不动（转头、发丝摆动时才露出来）。
    remaining = np.ones((H, W), np.float32)
    fixed = 0
    for idx in range(len(final) - 1, -1, -1):
        name, arr = final[idx]
        al = arr[..., 3].astype(np.float32) / 255
        vis = (al * remaining > VISIBLE_SHARE) & fg
        if name in NO_RECOLOUR_NEAR_EYE:
            # See-through 的睫毛层有些地方很淡，那里“露出来的”会被算成脸，校色就把睫毛、双眼皮线画进了脸层；
            # 眼睛眨动时睫毛层被压下去，脸上这几段线留在原地 → 重影。眼睛附近的脸不校色
            vis &= ~near_eye
        if vis.any():
            arr = arr.copy()
            arr[vis, :3] = orig[vis]
            final[idx] = (name, arr)
            fixed += int(vis.sum())
        remaining *= (1 - al)
    print(f"  visible pixels recoloured from original: {fixed}")

    # ---- 写 PSD ----
    def named(layer, name):
        layer.tagged_blocks.set_data(Tag.UNICODE_LAYER_NAME, name)
        return layer

    # 必须 RGBA：RGB 文档里 psd-tools 会把透明度存成图层蒙版，很多解析器（如 ag-psd）不读蒙版 → 透明处变实底
    psd = PSDImage.new("RGBA", (W, H))
    for name, arr in final:
        im = Image.fromarray(arr, "RGBA")
        bb = im.getchannel("A").getbbox()
        if not bb:
            continue
        psd.append(named(PixelLayer.frompil(im.crop(bb), psd, name, top=bb[1], left=bb[0]), name))
    expr_layers = []
    for name in EXPR:
        p = DIFFS / f"{name}_图层.png"
        if not p.exists():
            continue
        im = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
        bb = im.getchannel("A").getbbox()
        if not bb:
            continue
        lay = named(PixelLayer.frompil(im.crop(bb), psd, name, top=bb[1], left=bb[0]), name)
        lay.visible = False
        psd.append(lay)
        expr_layers.append(lay)
    if expr_layers:
        Group.group_layers(psd, expr_layers, name="表情差分")
    psd.save(OUT, encoding="gbk")
    print("已保存：", OUT, " 图层：", [n for n, _ in final])

    # ---- 对比图：原图 | 修复后合成 ----
    comp = Image.new("RGBA", (W, H), (40, 44, 60, 255))
    for _, arr in final:
        comp.alpha_composite(Image.fromarray(arr, "RGBA"))
    sheet = Image.new("RGB", (W * 2, H))
    sheet.paste(Image.fromarray(orig.astype(np.uint8)), (0, 0))
    sheet.paste(comp.convert("RGB"), (W, 0))
    sheet.resize((1280, 640), Image.LANCZOS).save(CHECK, quality=88)


if __name__ == "__main__":
    main()
