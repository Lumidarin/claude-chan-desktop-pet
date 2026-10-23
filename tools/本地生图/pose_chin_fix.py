# -*- coding: utf-8 -*-
"""
托腮姿势第二步：原来那只手挪走后，身体上露出了藏在下面的袖子残片（黑色碎块）。
对“原来那只手覆盖过的身体部分”再局部重绘一次，补成裙身。书和桌那边不动（已经是补全过的完整道具）。

用法：python pose_chin_fix.py <种子>   （对 art/姿势/托腮/候选_s<种子>.png 处理）
输出：art/姿势/托腮/定稿_s<种子>.png、_修复前后.jpg
"""
import os, sys
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ST_PSD = ROOT / "art" / "Claude娘_seethrough拆层.psd"
DIR = ROOT / "art" / "姿势" / "托腮"
MODEL = "cagliostrolab/animagine-xl-4.0"
VAE = "madebyollin/sdxl-vae-fp16-fix"

NEAR_ARM_MIN_CX = 400    # handwear 里重心在此以右的大块 = 前面那只手（同 pose_chin.py）
TORSO_MIN_X = 430        # 只修这条线以右（身体）；以左是书桌和书
PROMPT = ("masterpiece, high score, absurdres, anime coloring, clean lineart, black dress, black corset, "
          "white frilled capelet hem, orange sash, no arms, no hands")
NEG = ("hand, arm, sleeve, glove, fingers, lowres, worst quality, low quality, blurry, text, watermark, logo")
STRENGTH = 0.9
VRAM_FRACTION = 0.85     # 显存最多用 85%，绝不溢出到内存


def main():
    import numpy as np, cv2, torch
    from PIL import Image
    from psd_tools import PSDImage
    from diffusers import (StableDiffusionXLImg2ImgPipeline, StableDiffusionXLInpaintPipeline,
                           AutoencoderKL, EulerAncestralDiscreteScheduler)

    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    src = Image.open(DIR / f"候选_s{seed}.png").convert("RGB")
    W, H = src.size
    psd = PSDImage.open(ST_PSD)
    l = [x for x in psd.descendants() if x.name == "handwear"][0]
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); c.paste(l.topil(), (l.left, l.top))
    a = np.array(c)[..., 3] > 0
    n, lab, st, cen = cv2.connectedComponentsWithStats(a.astype(np.uint8), 8)
    old_arm = np.isin(lab, [i for i in range(1, n) if cen[i][0] > NEAR_ARM_MIN_CX and st[i, 4] > 2000])
    mask = cv2.dilate(old_arm.astype(np.uint8) * 255, np.ones((25, 25), np.uint8))
    mask[:, :TORSO_MIN_X] = 0
    # 新抬起来的手臂别动：pose_chin.py 存的遮罩里那条手臂
    new_arm = np.array(Image.open(DIR / "_遮罩.png").convert("L")) > 128
    mask[new_arm] = 0
    mask = cv2.GaussianBlur(mask, (0, 0), 3)

    ys, xs = np.nonzero(mask > 8)
    x0, y0, x1, y1 = max(xs.min() - 30, 0), max(ys.min() - 30, 0), min(xs.max() + 30, W), min(ys.max() + 30, H)
    cw = 1024; ch = int(round((y1 - y0) * cw / (x1 - x0) / 8)) * 8

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    b = StableDiffusionXLImg2ImgPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16)
    b.scheduler = EulerAncestralDiscreteScheduler.from_config(b.scheduler.config)
    b.to("cuda")
    cc = b.components
    pipe = StableDiffusionXLInpaintPipeline(vae=cc["vae"], text_encoder=cc["text_encoder"], text_encoder_2=cc["text_encoder_2"],
                                            tokenizer=cc["tokenizer"], tokenizer_2=cc["tokenizer_2"], unet=cc["unet"],
                                            scheduler=cc["scheduler"])
    g = torch.Generator("cuda").manual_seed(seed)
    out = pipe(prompt=PROMPT, negative_prompt=NEG,
               image=src.crop((x0, y0, x1, y1)).resize((cw, ch), Image.LANCZOS),
               mask_image=Image.fromarray(mask).crop((x0, y0, x1, y1)).resize((cw, ch), Image.LANCZOS),
               strength=STRENGTH, num_inference_steps=30, guidance_scale=5.0, generator=g).images[0]
    fixed = src.copy()
    fixed.paste(out.resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0), Image.fromarray(mask).crop((x0, y0, x1, y1)))
    fixed.save(DIR / f"定稿_s{seed}.png")
    box = (300, 380, 980, 1280)
    sh = Image.new("RGB", ((box[2] - box[0]) * 2, box[3] - box[1]))
    sh.paste(src.crop(box), (0, 0)); sh.paste(fixed.crop(box), (box[2] - box[0], 0))
    sh.resize((sh.width // 2, sh.height // 2), Image.LANCZOS).save(DIR / "_修复前后.jpg", quality=90)
    print("  →", DIR / f"定稿_s{seed}.png")


if __name__ == "__main__":
    main()
