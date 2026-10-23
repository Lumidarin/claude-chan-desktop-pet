# -*- coding: utf-8 -*-
"""
立绘模式素材：4096 定稿图抠背景 + 表情差分图层 → web/sprite/claude/

Live2D 模型绑好之前，桌宠用这套图层直接显示 Claude娘（web/sprite.js 负责叠图、眨眼、动嘴）。
  base.png        抠掉背景的整张立绘（保留书桌和书），裁到人物范围，宽 WIDTH
  <差分>.png       只含改动区域的透明图层，裁到自身范围
  manifest.js     各图层的位置尺寸（file:// 下页面不能 fetch JSON，所以写成 JS）

背景：从四角漫水填充（逐像素比较邻居，容差 3），和 inpaint_local.py 的做法一样。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
SRC = ROOT / "art" / "4096"
OUT = ROOT / "web" / "sprite" / "claude"
LAYERS = ["闭眼", "半闭眼", "微笑", "张嘴a", "张嘴o", "脸红", "星星眼", "爱心眼", "晕圈眼"]
WIDTH = 1024        # 窗口 380 宽 × 屏幕缩放 2 倍也够清楚
WORK = 2048         # 在 2048 上抠背景（4096 漫水填充太慢，边缘差别看不出）
BG_TOL_EDGE = 28    # 和画面边缘连通的背景：每个通道和背景色相差不超过这么多（背景右上角有亮渐变；人物有黑描线围着，放宽也渗不进去）
BG_TOL = 14         # 被发丝围住的背景块（还要求四周大半是橙色头发）
BG_FLAT_TOL = 8     # 围合区颜色中位数离背景色这么近 …
BG_FLAT_AREA = 300  # … 且面积这么大（2048 尺度），不看四周是什么，直接算背景
BG_SPECK = 40      # 比这还小的背景碎点当噪点丢掉（2048 尺度）
BG_MIN_AREA = 150  # 且面积至少这么大（2048 尺度下），免得吃掉高光小点


def foreground_alpha(img):
    """立绘（RGB，带浅色背景）→ 同尺寸的前景 alpha（L）。抠背景规则见下；see-through 后处理也用它。"""
    import numpy as np, cv2
    from PIL import Image

    work = img.resize((WORK, WORK), Image.LANCZOS)
    a = np.array(work).astype(int)
    h, w = a.shape[:2]
    # 不用“逐像素比邻居”的漫水填充：放大后的边缘过渡太平滑，会顺着渐变一路渗进头发。
    # 改成和背景色的固定距离：
    #   1) 距离 ≤ BG_TOL_EDGE 且和画面边缘连通的区域 = 背景（黑描线把人物围住，进不去）
    #   2) 被发丝围住的小块：距离 ≤ BG_TOL 且面积 ≥ BG_MIN_AREA 也算背景
    #      （容差更紧：白披肩偏蓝、书页偏黄，离偏粉灰的背景色够远）
    corners = np.concatenate([a[:40, :40].reshape(-1, 3), a[:40, -40:].reshape(-1, 3), a[:40, w // 2 - 20:w // 2 + 20].reshape(-1, 3)])
    bg_color = np.median(corners, axis=0)
    dist = np.abs(a - bg_color).max(axis=2)
    bg = np.zeros((h, w), bool)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((dist <= BG_TOL_EDGE).astype(np.uint8), connectivity=4)
    # 只从上边、右边、左边上半段找：书桌和书贴着左下和底边，书页颜色又近背景，从那里连通会被整块抠掉
    border = set(np.unique(np.concatenate([lab[0], lab[:, -1], lab[:int(h * 0.55), 0]]))) - {0}
    for i in border:
        bg |= lab == i
    # 被围住的小块只在“四周大半是橙色头发”时才算背景 —— 书页、白披肩的浅色块周围不是橙色，不会被误抠
    orange = (a[..., 0] > 190) & (a[..., 1] > 70) & (a[..., 1] < 200) & (a[..., 2] < 120)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((dist <= BG_TOL).astype(np.uint8), connectivity=4)
    kernel = np.ones((7, 7), np.uint8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < BG_MIN_AREA or i in border:
            continue
        x, y, cw, ch = stats[i, :4]
        # 颜色几乎就是背景色、面积又不小的围合区（如脸左边被一根飘发线圈住的那块）：直接算背景
        comp_full = lab[y:y + ch, x:x + cw] == i
        if stats[i, cv2.CC_STAT_AREA] >= BG_FLAT_AREA and np.median(dist[y:y + ch, x:x + cw][comp_full]) <= BG_FLAT_TOL:
            bg[y:y + ch, x:x + cw] |= comp_full
            continue
        x0, y0, x1, y1 = max(x - 6, 0), max(y - 6, 0), min(x + cw + 6, w), min(y + ch + 6, h)
        comp = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = cv2.dilate(comp, kernel).astype(bool) & ~comp.astype(bool)
        # 描线是黑的，环上先去掉深色像素再算橙色占比
        ring_px = ring & (a[y0:y1, x0:x1].max(axis=2) > 90)
        if ring_px.sum() and orange[y0:y1, x0:x1][ring_px].mean() > 0.45:
            bg[y0:y1, x0:x1] |= comp.astype(bool)
    # 去背景噪点只按面积去，不用开运算：开运算会把发丝之间几像素宽的背景细缝也抹掉，缝就又算回角色、露出白边
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bg.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= BG_SPECK
    bg = keep[lab].astype(np.uint8)
    fg = 1 - bg
    # 去掉背景色残边：前景向内收 1px，再 1px 羽化
    fg = cv2.erode(fg, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur((fg * 255).astype(np.uint8), (0, 0), 0.8)
    return Image.fromarray(alpha).resize(img.size, Image.LANCZOS)


def main():
    from PIL import Image

    base4k = Image.open(SRC / "定稿底图_4096.png").convert("RGB")
    alpha = foreground_alpha(base4k)
    rgba = base4k.convert("RGBA")
    rgba.putalpha(alpha)
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    scale = WIDTH / (bbox[2] - bbox[0])
    size = (WIDTH, round((bbox[3] - bbox[1]) * scale))

    OUT.mkdir(parents=True, exist_ok=True)
    rgba.crop(bbox).resize(size, Image.LANCZOS).save(OUT / "base.png", optimize=True)
    manifest = {"w": size[0], "h": size[1], "base": "base.png", "layers": {}}

    for name in LAYERS:
        p = SRC / f"{name}_图层_4096.png"
        if not p.exists():
            print("  缺少", p.name); continue
        lay = Image.open(p).convert("RGBA").crop(bbox).resize(size, Image.LANCZOS)
        lb = lay.getchannel("A").point(lambda v: 255 if v > 2 else 0).getbbox()
        if not lb:
            continue
        lay.crop(lb).save(OUT / f"{name}.png", optimize=True)
        manifest["layers"][name] = {"src": f"{name}.png", "x": lb[0], "y": lb[1],
                                    "w": lb[2] - lb[0], "h": lb[3] - lb[1]}
        print(f"  {name}: {lb}")

    (OUT / "manifest.js").write_text(
        "// 由 tools/本地生图/make_sprite.py 生成，别手改\n"
        "window.PET_SPRITE = " + json.dumps(manifest, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8")
    print("底图", size, "→", OUT)


if __name__ == "__main__":
    main()
