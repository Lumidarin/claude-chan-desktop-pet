# -*- coding: utf-8 -*-
"""
书桌和书：整理成两件完整、轮廓正常的道具，放在人物下面（用户定的层序：剪影深色底 → 桌子 → 书 → 人物）。
手抬起来露出的是完整书页；以后做“拿起书”，书是独立一层，下面是完整桌面。

桌子：原图桌面的左边缘 + 后沿两条线围出整块桌面（延伸到画面右边和底边、身体后面也有）。
      原图露出的木纹保留，其余（书下、手下、身体后）用 Animagine 补成木纹桌面。
书：  原图里桌面区域中“不是木色”的像素 = 看得见的书（书页、封面、书口）。
      它们的凸包 − 原图明确露出木纹的地方（书脊上方的 V 形缺口）= 书的形状；
      形状里被手挡住的部分补成书页，边缘平滑。

坐标都是 See-through 画布（1280）。输出：art/书桌/desk.png、book.png、_桌子.jpg、_书.jpg
"""
import os
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ST_PSD = ROOT / "art" / "Claude娘_seethrough拆层.psd"
ORIG = ROOT / "art" / "定稿底图_v3_本地精修1536.png"
OUT = ROOT / "art" / "书桌"
MODEL = "cagliostrolab/animagine-xl-4.0"
VAE = "madebyollin/sdxl-vae-fp16-fix"

# 桌面轮廓（1280 坐标，从原图量的）：左边缘 (0,1024)→(170,940) 是桌角，后沿从桌角往右几乎水平
# （上面那只手正搭在后沿上；后沿抬太高会超出原图桌面，被前景裁成手背形状的缺口）
DESK_POLY = [(0, 1024), (170, 940), (1280, 905), (1280, 1280), (0, 1280)]
HAND_MARGIN = 9          # 手周围这么宽的一圈书桌像素不保留，交给 AI 补（去掉手的描边和阴影）
FG_CLIP_FROM = 0.5      # 画面这个比例以右的桌面按原图前景裁（防止从发丝缝透出）
DESK_MAX_CX = 0.45      # desk 层里重心在画面左边这么多以内的块才是书桌（右边的是杂碎）
SEED = 808
DESK_HARMONIZE = 0.6     # 补完后整块桌面再重绘的强度（统一木纹走向）
BOOK_HARMONIZE = 0.5     # 整本书再重绘的强度
BOOK_OPEN = 21           # 书轮廓开运算核大小：去掉页角卷起那类小突起
VRAM_FRACTION = 0.85     # 显存最多用 85%，绝不溢出到内存
NEG_COMMON = ("hand, hands, glove, fingers, arm, sleeve, 1girl, person, lowres, worst quality, low quality, "
              "blurry, signature, watermark, logo")
DESK_PROMPT = ("masterpiece, high score, absurdres, anime coloring, clean lineart, still life, no humans, "
               "empty wooden desk surface, wood grain, warm brown wood")
BOOK_PROMPT = ("masterpiece, high score, absurdres, anime coloring, clean lineart, still life, no humans, "
               "open book, two cream paper pages, faint text lines, page edges, hardcover")


def is_wood(rgb):
    """木桌色（偏橙棕、蓝通道低），书页（米白）、书口（偏粉）、封面（深色/红）都不算。闭运算吞掉木纹细线"""
    import numpy as np, cv2
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    wood = (r > 140) & (g > 90) & (g < 200) & (b < 150) & (r - b > 55)
    return cv2.morphologyEx(wood.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)).astype(bool)


def main():
    import numpy as np, cv2, torch
    from PIL import Image
    from psd_tools import PSDImage
    from diffusers import StableDiffusionXLInpaintPipeline, AutoencoderKL, EulerAncestralDiscreteScheduler

    psd = PSDImage.open(ST_PSD)
    W, H = psd.size
    orig = np.array(Image.open(ORIG).convert("RGB").resize((W, H), Image.LANCZOS))

    # 原图里书桌（含书）露在外面的像素
    l = [x for x in psd.descendants() if x.name == "desk"][0]
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); c.paste(l.topil(), (l.left, l.top))
    a = np.array(c)[..., 3] > 128
    n, lab, st, cen = cv2.connectedComponentsWithStats(a.astype(np.uint8), 8)
    vis = np.zeros((H, W), bool)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 200 and cen[i][0] < W * DESK_MAX_CX:
            vis |= lab == i
    # 手边一圈不算“看得见”：原图手的黑描边、阴影贴着书桌，留在这里的话，手一抬它们会留在原地
    hl = [x for x in psd.descendants() if x.name == "handwear"][0]
    hc = Image.new("RGBA", (W, H), (0, 0, 0, 0)); hc.paste(hl.topil(), (hl.left, hl.top))
    near_hand = cv2.dilate((np.array(hc)[..., 3] > 40).astype(np.uint8),
                           np.ones((HAND_MARGIN * 2 + 1,) * 2, np.uint8)).astype(bool)
    # 书的形状用完整的可见区算（去掉手边后可见的书变少，外轮廓会缩、被斜着切掉一角）；
    # 去掉手边那圈只影响“保留哪些原图像素”
    wood_all = vis & is_wood(orig.astype(int))
    book_all = vis & ~wood_all
    vis = vis & ~near_hand
    wood_vis = wood_all & ~near_hand
    book_vis = book_all & ~near_hand
    n, lab, st, _ = cv2.connectedComponentsWithStats(book_all.astype(np.uint8), 8)
    book_all = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 800])
    book_vis = book_all & ~near_hand

    # 书的形状：凸包 − 原图露出木纹的地方，再平滑（都用挖手之前的完整可见区）
    hull = cv2.convexHull(np.argwhere(book_all)[:, ::-1].astype(np.int32))
    book = np.zeros((H, W), np.uint8); cv2.fillConvexPoly(book, hull, 1)
    book = book.astype(bool) & ~cv2.dilate(wood_all.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    n, lab, st, _ = cv2.connectedComponentsWithStats(book.astype(np.uint8), 8)
    book = lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    book = cv2.morphologyEx(book.astype(np.uint8), cv2.MORPH_OPEN, np.ones((BOOK_OPEN, BOOK_OPEN), np.uint8))   # 去掉卷角之类的小突起
    book = cv2.GaussianBlur(book.astype(np.float32), (0, 0), 2.0) > 0.5          # 轮廓平滑

    desk = np.zeros((H, W), np.uint8); cv2.fillPoly(desk, [np.array(DESK_POLY, np.int32)], 1)
    # 只铺在原图本来就是角色/书桌的地方：桌子在人物下面，铺到背景处会从发丝缝里透出来
    import sys
    sys.path.insert(0, str(HERE))
    from make_sprite import foreground_alpha
    fg = np.array(foreground_alpha(Image.open(ORIG).convert("RGB")).resize((W, H), Image.LANCZOS)) > 128
    fg = cv2.dilate(fg.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    fg[:, :int(W * FG_CLIP_FROM)] = True          # 只在右边（长发那侧）按前景裁，左边桌面保持完整的桌沿
    desk = desk.astype(bool) & fg

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    pipe = StableDiffusionXLInpaintPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16)
    pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    pipe.to("cuda")

    def paint(region, known, prompt, neg, strength=0.99, grow=11, harmonize=0.5):
        """region 里 known 以外的像素用 AI 补：先按周围颜色粗填，再在外接框里放大到 1024 宽局部重绘"""
        hole = cv2.dilate((region & ~known).astype(np.uint8), np.ones((grow, grow), np.uint8)).astype(bool) & region
        base = orig.copy(); base[~(known & ~hole)] = 0
        filled = cv2.inpaint(base, (hole | ~known).astype(np.uint8) * 255, 9, cv2.INPAINT_TELEA)
        ys, xs = np.nonzero(region)
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        cw = 1024; ch = max(8, int(round((y1 - y0) * cw / (x1 - x0) / 8)) * 8)
        g = torch.Generator("cuda").manual_seed(SEED)
        out = pipe(prompt=prompt, negative_prompt=neg,
                   image=Image.fromarray(filled[y0:y1, x0:x1]).resize((cw, ch), Image.LANCZOS),
                   mask_image=Image.fromarray(hole[y0:y1, x0:x1].astype(np.uint8) * 255).resize((cw, ch), Image.LANCZOS),
                   strength=strength, num_inference_steps=30, guidance_scale=5.0, generator=g).images[0]
        painted = np.array(out.resize((x1 - x0, y1 - y0), Image.LANCZOS))
        res = filled.copy()
        sub = res[y0:y1, x0:x1]; h = hole[y0:y1, x0:x1]; sub[h] = painted[h]
        # 整体统一：保留原图那几块 + AI 补的部分，纹理走向对不上（像贴了补丁）。
        # 再对整块区域低强度重绘一遍，颜色和大轮廓不变，表面由同一次生成画出来
        g = torch.Generator("cuda").manual_seed(SEED + 1)
        out = pipe(prompt=prompt, negative_prompt=neg,
                   image=Image.fromarray(res[y0:y1, x0:x1]).resize((cw, ch), Image.LANCZOS),
                   mask_image=Image.fromarray(region[y0:y1, x0:x1].astype(np.uint8) * 255).resize((cw, ch), Image.LANCZOS),
                   strength=harmonize, num_inference_steps=30, guidance_scale=5.0, generator=g).images[0]
        unified = np.array(out.resize((x1 - x0, y1 - y0), Image.LANCZOS))
        sub = res[y0:y1, x0:x1]; r = region[y0:y1, x0:x1]; sub[r] = unified[r]
        return res, hole

    # 桌子：已知 = 原图露出的木纹；书下面也补成桌面
    desk_rgb, desk_hole = paint(desk, wood_vis, DESK_PROMPT, NEG_COMMON + ", book, paper, pages, objects",
                                harmonize=DESK_HARMONIZE)
    # AI 画的木纹颜色偏艳：整块桌面按原图露出的木纹做颜色匹配（Lab 各通道均值、标准差对齐）
    lab_all = cv2.cvtColor(desk_rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    ref = cv2.cvtColor(orig, cv2.COLOR_RGB2LAB).astype(np.float32)[wood_vis]
    src = lab_all[desk]
    src = (src - src.mean(0)) / (src.std(0) + 1e-3) * ref.std(0) + ref.mean(0)
    lab_all[desk] = src
    desk_rgb = cv2.cvtColor(np.clip(lab_all, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    # 书：已知 = 原图露出的书；形状里其余部分补书页
    book_rgb, book_hole = paint(book, book_vis, BOOK_PROMPT, NEG_COMMON + ", loose paper, extra page, scratches",
                                harmonize=BOOK_HARMONIZE)
    print(f"  桌面 {desk.sum()} px（补 {desk_hole.sum()}），书 {book.sum()} px（补 {book_hole.sum()}）")

    OUT.mkdir(parents=True, exist_ok=True)
    def save(rgb, mask, name):
        out = np.zeros((H, W, 4), np.uint8); out[..., :3] = rgb
        out[..., 3] = cv2.GaussianBlur((mask * 255).astype(np.uint8), (0, 0), 0.7)
        Image.fromarray(out).save(OUT / f"{name}.png")
        return out
    d = save(desk_rgb, desk, "desk")
    b = save(book_rgb, book, "book")
    for name, arr in [("_桌子", d), ("_书", b)]:
        ys, xs = np.nonzero(arr[..., 3])
        box = (max(xs.min() - 10, 0), max(ys.min() - 10, 0), min(xs.max() + 10, W), min(ys.max() + 10, H))
        bgc = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (60, 60, 90, 255))
        bgc.alpha_composite(Image.fromarray(arr).crop(box)); bgc.convert("RGB").save(OUT / f"{name}.jpg", quality=90)
    both = Image.new("RGBA", (W, H), (60, 60, 90, 255))
    both.alpha_composite(Image.fromarray(d)); both.alpha_composite(Image.fromarray(b))
    both.crop((0, 800, 900, 1280)).convert("RGB").save(OUT / "_桌子加书.jpg", quality=90)
    print("  →", OUT)


if __name__ == "__main__":
    main()
