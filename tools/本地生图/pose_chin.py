# -*- coding: utf-8 -*-
"""
新姿势“托腮沉思”：前面那只手从书上抬起，手肘悬在胸前，手轻触下巴。

  1. 底图 = 2.5D 模型（art/Claude娘_rig.psd）去掉前面那只手：手下面露出的是补全过的书桌、书，
     身体部分是 See-through 补画过的上衣
  2. 用粗色块摆出手臂：黑袖子从披肩下摆斜向上到下巴，白手套停在下巴处
  3. Animagine 局部重绘把色块画成正式的手臂（遮罩 = 色块向外扩一圈；脸部只有被手盖住的那块会变）
输出：art/姿势/托腮/候选_s<seed>.png（1280 画布整图）、_拼贴底图.png、_遮罩.png、总览.jpg
坐标都在 1280 画布（See-through / rig PSD 的尺寸）。
"""
import os
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RIG_PSD = ROOT / "art" / "Claude娘_rig.psd"
OUT = ROOT / "art" / "姿势" / "托腮"
MODEL = "cagliostrolab/animagine-xl-4.0"
VAE = "madebyollin/sdxl-vae-fp16-fix"

# 前面那只手：handwear 层里重心在这个范围内的那一大块（另一块是后面那只手）
NEAR_ARM_MIN_CX = 400
# 粗色块（1280 坐标）：袖子是一条从手肘到手腕的四边形，手套是下巴下的椭圆
#   两种摆法（命令行参数选）：
#   desk  像《思想者》：大臂从披肩下摆斜向左下，手肘撑在桌上；前臂折回往上托下巴（AI 画弯折手臂很乱）
#   cross 用户给的参考图：托腮那只手手肘在腰前（披肩下摆下），前臂几乎竖直到下巴；
#         后面那只手从书上收回，横在腹前，手垫在手肘下。前臂长 ~390px，和原图一致
VARIANTS = {
    "desk": {
        "sleeves": [[(705, 925), (775, 985), (555, 1062), (495, 1000)],      # 大臂：披肩下摆 → 手肘
                    [(500, 1015), (568, 1040), (630, 618), (566, 630)]],     # 前臂：手肘 → 手腕
        "elbow": (528, 1028, 40, 36), "extra_gloves": [], "remove_far": False,
        "prompt": "hand on own chin, thinking pose, elbow on table, bent arm",
    },
    # 用户第二张参考（3D 侧身图）：手肘要在胸前、身体朝向那侧（画面左），不是身体正下方；
    # 另一只手臂从身体那侧横过来托住手肘，手从手肘左下方露出来
    "cross": {
        "sleeves": [[(505, 1000), (585, 1010), (632, 618), (568, 630)],      # 托腮的前臂：手肘 → 手腕
                    [(470, 972), (725, 982), (725, 1045), (470, 1042)]],     # 横在胸下托手肘的另一只前臂
        "elbow": (545, 1005, 46, 40), "extra_gloves": [(462, 1010, 40, 30)],  # 手肘左下方露出的那只手
        "remove_far": True,
        "prompt": "chin resting on hand, thinking pose, elbow resting on other arm, arms crossed under chest",
    },
}
CUFF = (598, 618, 48, 28)                                        # 袖口荷叶边（椭圆 cx, cy, rx, ry）
GLOVE = (585, 545, 58, 55)                                       # 手套
FAR_ARM_MAX_CX = 400     # handwear 里重心在此以左的块 = 后面那只手（cross 摆法要挪走）
SLEEVE_COLOR, CUFF_COLOR, GLOVE_COLOR = (34, 33, 44), (45, 44, 58), (246, 246, 250)
SIL = (30, 28, 36)       # make_rig_psd.py 的剪影色，用来认出“露出剪影”的地方
GROW = 28                                                       # 重绘遮罩比色块向外扩的像素

PROMPT = ("masterpiece, high score, absurdres, anime coloring, clean lineart, 1girl, orange hair, red eyes, "
          "{pose}, white gloves, black long sleeves, frilled cuffs")
NEG = ("bare hands, extra arms, extra hands, bad hands, missing fingers, extra digits, bracelet, gold trim, jewelry, "
       "red cuff, lowres, bad anatomy, "
       "worst quality, low quality, blurry, text, signature, watermark, logo")
SEEDS = [2024, 808, 303, 1234, 42, 7, 99]
STRENGTH = 0.92
VRAM_FRACTION = 0.85     # 显存最多用 85%，绝不溢出到内存


def main():
    import numpy as np, cv2, torch
    from PIL import Image, ImageDraw
    from psd_tools import PSDImage
    from diffusers import (StableDiffusionXLImg2ImgPipeline, StableDiffusionXLInpaintPipeline,
                           AutoencoderKL, EulerAncestralDiscreteScheduler)

    import sys
    vname = sys.argv[1] if len(sys.argv) > 1 else "cross"
    V = VARIANTS[vname]
    out_dir = OUT / vname
    psd = PSDImage.open(RIG_PSD)
    W, H = psd.size
    # 1. 底图：所有静止时可见的层叠起来，handwear 去掉前面那只手；闭眼 / 张嘴这类差分层不叠
    skip = {"eye_close", "mouth_open"}
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for l in psd.descendants():
        if l.is_group() or l.name in skip:
            continue
        c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); c.paste(l.topil(), (l.left, l.top))
        if l.name == "handwear":
            a = np.array(c)
            n, lab, st, cen = cv2.connectedComponentsWithStats((a[..., 3] > 0).astype(np.uint8), 8)
            near = np.isin(lab, [i for i in range(1, n) if cen[i][0] > NEAR_ARM_MIN_CX and st[i, 4] > 2000])
            a[near, 3] = 0
            if V["remove_far"]:      # 后面那只手也从书上收回（下面是补全过的书和桌）
                far = np.isin(lab, [i for i in range(1, n) if cen[i][0] <= FAR_ARM_MAX_CX and st[i, 4] > 2000])
                a[far, 3] = 0
            c = Image.fromarray(a)
        base.alpha_composite(c)

    # 2. 粗色块
    collage = base.copy()
    d = ImageDraw.Draw(collage)
    shape = Image.new("L", (W, H), 0)
    ds = ImageDraw.Draw(shape)
    for poly in V["sleeves"]:
        d.polygon(poly, fill=SLEEVE_COLOR + (255,)); ds.polygon(poly, fill=255)
    ells = [(V["elbow"], SLEEVE_COLOR), (CUFF, CUFF_COLOR), (GLOVE, GLOVE_COLOR)] + \
           [(gl, GLOVE_COLOR) for gl in V["extra_gloves"]]
    for (cx, cy, rx, ry), col in ells:
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=col + (255,))
        ds.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    mask = cv2.dilate(np.array(shape), np.ones((GROW * 2 + 1,) * 2, np.uint8))
    # 原来那只手挪走后，底下没东西盖住的地方会露出深色剪影：也一起重绘（补成裙身 / 书）
    sil = [l for l in psd.descendants() if l.name == "silhouette"][0]
    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sc.paste(sil.topil(), (sil.left, sil.top))
    sil_a = np.array(sc)[..., 3] > 0
    shows_sil = sil_a & (np.abs(np.array(base)[..., :3].astype(int) - np.array(SIL)).max(axis=2) < 6)
    shows_sil = cv2.morphologyEx(shows_sil.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = np.maximum(mask, cv2.dilate(shows_sil * 255, np.ones((9, 9), np.uint8)))
    mask = cv2.GaussianBlur(mask, (0, 0), 4)

    out_dir.mkdir(parents=True, exist_ok=True)
    collage.save(out_dir / "_拼贴底图.png")
    Image.fromarray(mask).save(out_dir / "_遮罩.png")

    # 3. 局部重绘：裁出手臂周围放大到 1024 高
    ys, xs = np.nonzero(mask > 8)
    pad = 40
    x0, y0 = max(xs.min() - pad, 0), max(ys.min() - pad, 0)
    x1, y1 = min(xs.max() + pad, W), min(ys.max() + pad, H)
    chh = 1024
    cww = int(round((x1 - x0) * chh / (y1 - y0) / 8)) * 8
    bg = Image.new("RGB", (W, H), (240, 234, 238))           # 透明处垫原图背景色
    bg.paste(collage, (0, 0), collage)
    crop = bg.crop((x0, y0, x1, y1)).resize((cww, chh), Image.LANCZOS)
    mcrop = Image.fromarray(mask).crop((x0, y0, x1, y1)).resize((cww, chh), Image.LANCZOS)

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    b = StableDiffusionXLImg2ImgPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16)
    b.scheduler = EulerAncestralDiscreteScheduler.from_config(b.scheduler.config)
    b.to("cuda")
    c = b.components
    pipe = StableDiffusionXLInpaintPipeline(vae=c["vae"], text_encoder=c["text_encoder"], text_encoder_2=c["text_encoder_2"],
                                            tokenizer=c["tokenizer"], tokenizer_2=c["tokenizer_2"], unet=c["unet"],
                                            scheduler=c["scheduler"])
    results = []
    for seed in SEEDS:
        g = torch.Generator("cuda").manual_seed(seed)
        out = pipe(prompt=PROMPT.format(pose=V["prompt"]), negative_prompt=NEG, image=crop, mask_image=mcrop, strength=STRENGTH,
                   num_inference_steps=30, guidance_scale=5.0, generator=g).images[0]
        patch = out.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        full = bg.copy()
        full.paste(patch, (x0, y0), Image.fromarray(mask).crop((x0, y0, x1, y1)))
        full.save(out_dir / f"候选_s{seed}.png")
        results.append((seed, full))
        print(f"  s{seed} 完成", flush=True)

    # 总览：拼贴底图 + 各候选，只截上半身
    box = (300, 300, 980, 1120)
    tw, th = 340, 410
    sheet = Image.new("RGB", (tw * 4, th * 2), "white")
    tiles = [("拼贴", bg)] + [(f"s{s}", im) for s, im in results]
    for i, (_, im) in enumerate(tiles[:8]):
        sheet.paste(im.crop(box).resize((tw, th), Image.LANCZOS), ((i % 4) * tw, (i // 4) * th))
    sheet.save(out_dir / "总览.jpg", quality=90)
    print("  →", out_dir)


if __name__ == "__main__":
    main()
