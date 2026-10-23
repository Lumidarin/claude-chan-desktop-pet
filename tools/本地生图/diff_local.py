# -*- coding: utf-8 -*-
"""
Claude娘 表情 / 手部差分（局部重绘，遮罩外像素保证不动，方便 Live2D 拆层对齐）

做法（“只重绘遮罩区”）：
  1. 从定稿图裁出该部位所在的方块（如脸部 384×384），放大到 1024 再重绘 —— 像素多，细节好
  2. 重绘结果缩回原尺寸，只把遮罩内的像素贴回定稿图
  3. 每张另存一份透明底图层（只含遮罩区），拆层时直接叠上去

输入：art/定稿底图_v3_本地精修1536.png
输出：art/差分/<差分名>_s<seed>.png（整图） + _图层.png（透明底） + 总览.jpg
改位置：调 REGIONS / MASKS（1536 坐标）。
"""
import os, sys, time, json
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
BASE = ROOT / "art" / "定稿底图_v3_本地精修1536.png"
OUT  = ROOT / "art" / "差分"

MODEL = "cagliostrolab/animagine-xl-4.0"
VAE   = "madebyollin/sdxl-vae-fp16-fix"

# 裁剪方块（1536 坐标 x0, y0, 边长）：在这个方块里放大重绘
REGIONS = {
    "face": (480, 280, 384),
    "hand": (100, 1024, 512),
}
# 遮罩椭圆（1536 坐标 cx, cy, rx, ry）
MASKS = {
    "eyes":  [(752, 378, 74, 44), (608, 420, 38, 40)],
    "mouth": [(674, 514, 34, 20)],     # 嘴线在 (665–684, 514)；别往下盖到下巴阴影
    "cheek": [(732, 462, 60, 26), (642, 472, 24, 18)],
    "hand":  [(375, 1395, 125, 95)],   # 只包住手，别碰书页（否则会重画成另一本书）
}
SKIN_AT = (700, 470)   # 取肤色的位置（脸颊）：闭眼/微笑先用肤色涂掉原五官再重绘
FEATHER = 8

FACE_P = "masterpiece, high score, absurdres, anime coloring, 1girl, orange hair, red eyes, face, "
NEG = ("lowres, bad anatomy, worst quality, low quality, low score, bad score, blurry, sketch, monochrome, "
       "text, signature, watermark, logo")

# (差分名, 区域, 遮罩, 提示词尾, 重绘强度, 先用肤色涂掉原五官)
# 脸红不走 AI：由 make_blush() 直接画半透明图层（Live2D 里本来就是单独一层）
DIFFS = [
    ("闭眼",     "face", "eyes",  "closed eyes, eyelashes",                    0.95, True),
    ("半闭眼",   "face", "eyes",  "half-closed eyes, red eyes, sleepy",        0.90, True),
    ("微笑",     "face", "mouth", "light smile, closed mouth, smile",          0.90, True),
    ("张嘴a",    "face", "mouth", "open mouth, talking",                       0.90, False),
    ("张嘴o",    "face", "mouth", ":o, small open mouth, round mouth",         0.90, False),
    ("星星眼",   "face", "eyes",  "star-shaped pupils, sparkling eyes",        0.85, False),
    ("爱心眼",   "face", "eyes",  "heart-shaped pupils, pink hearts in eyes",  0.85, False),
    ("晕圈眼",   "face", "eyes",  "@_@, spiral eyes, dizzy",                   0.90, False),
    ("持羽毛笔", "hand", "hand",
     "masterpiece, high score, absurdres, anime coloring, white gloves, hand holding quill, feather pen, writing",
     0.95, False),
]
SEEDS = [303, 808, 1234, 2024]


def make_blush(size):
    """脸红图层：脸颊遮罩内的粉色柔光 + 每边三道斜线"""
    from PIL import Image, ImageDraw, ImageFilter
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    glow = Image.new("L", size, 0)
    d = ImageDraw.Draw(glow)
    for cx, cy, rx, ry in MASKS["cheek"]:
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    pink = Image.new("RGBA", size, (255, 110, 120, 0))
    pink.putalpha(glow)
    layer = Image.alpha_composite(layer, pink)
    d = ImageDraw.Draw(layer)
    for cx, cy, rx, ry in MASKS["cheek"]:
        step = rx // 3
        for i in (-1, 0, 1):
            x = cx + i * step
            d.line((x + ry // 3, cy - ry // 2, x - ry // 3, cy + ry // 2), fill=(225, 80, 95, 170), width=3)
    return layer
STEPS, CFG = 30, 5.0
VRAM_FRACTION = 0.85   # 显存最多用 85%（16GB 卡约 13.5GB），留余量、绝不溢出到内存


def ellipse_mask(size, ellipses):
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for cx, cy, rx, ry in ellipses:
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    return m.filter(ImageFilter.GaussianBlur(FEATHER / 2))


def main():
    import torch
    from PIL import Image
    from diffusers import (StableDiffusionXLImg2ImgPipeline, StableDiffusionXLInpaintPipeline,
                           AutoencoderKL, EulerAncestralDiscreteScheduler)

    if not torch.cuda.is_available():
        print("[错误] 没检测到 CUDA 显卡。")
        sys.exit(1)
    print("显卡：", torch.cuda.get_device_name(0), " PyTorch：", torch.__version__)
    OUT.mkdir(parents=True, exist_ok=True)
    base_img = Image.open(BASE).convert("RGB")
    assert base_img.size == (1536, 1536), base_img.size

    print("加载模型…")
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    base = StableDiffusionXLImg2ImgPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16)
    base.scheduler = EulerAncestralDiscreteScheduler.from_config(base.scheduler.config)
    # 显存上限：超出直接报错，而不是让 Windows 偷偷借内存当显存（会慢几百倍）
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    base.to("cuda")
    # 直接复用底模组件；from_pipe 会在显卡上再复制一份底模
    c = base.components
    inpaint = StableDiffusionXLInpaintPipeline(
        vae=c["vae"], text_encoder=c["text_encoder"], text_encoder_2=c["text_encoder_2"],
        tokenizer=c["tokenizer"], tokenizer_2=c["tokenizer_2"], unet=c["unet"], scheduler=c["scheduler"])

    results = []
    blush = make_blush(base_img.size)
    blush.save(OUT / "脸红_图层.png")
    blushed = base_img.copy()
    blushed.paste(blush, (0, 0), blush)
    blushed.save(OUT / "脸红.png")
    x0, y0, side = REGIONS["face"]
    results.append(("脸红", 0, blushed, (x0, y0, x0 + side, y0 + side)))

    for name, region, mask_key, tail, strength, prefill in DIFFS:
        x0, y0, side = REGIONS[region]
        box = (x0, y0, x0 + side, y0 + side)
        full_mask = ellipse_mask(base_img.size, MASKS[mask_key])
        src = base_img
        if prefill:   # 用肤色涂掉原五官，否则模型会照着原样画回去；只涂中心 70%，别把压在眼上的刘海涂掉
            src = base_img.copy()
            core = [(cx, cy, rx * 0.7, ry * 0.7) for cx, cy, rx, ry in MASKS[mask_key]]
            src.paste(Image.new("RGB", src.size, base_img.getpixel(SKIN_AT)), (0, 0),
                      ellipse_mask(base_img.size, core))
        crop = src.crop(box).resize((1024, 1024), Image.LANCZOS)
        crop_mask = full_mask.crop(box).resize((1024, 1024), Image.LANCZOS)
        prompt = tail if region == "hand" else FACE_P + tail
        for seed in SEEDS:
            out_path = OUT / f"{name}_s{seed}.png"
            if out_path.exists():   # 已出过的跳过，方便中断后续跑
                results.append((name, seed, Image.open(out_path).convert("RGB"), box))
                continue
            t = time.time()
            g = torch.Generator("cuda").manual_seed(seed)
            img = inpaint(prompt=prompt, negative_prompt=NEG, image=crop, mask_image=crop_mask,
                          strength=strength, num_inference_steps=STEPS, guidance_scale=CFG, generator=g).images[0]
            patch = img.resize((side, side), Image.LANCZOS)
            layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
            layer.paste(patch.convert("RGBA"), box[:2])
            layer.putalpha(full_mask)
            final = base_img.copy()
            final.paste(layer, (0, 0), layer)
            final.save(out_path)
            layer.save(OUT / f"{name}_s{seed}_图层.png")
            results.append((name, seed, final, box))
            print(f"  {name} s{seed}  完成  {time.time() - t:.1f}s")

    # 总览：每行一个差分（原图 + 各 seed），只截该部位
    from PIL import ImageDraw
    tile = 320
    names = ["脸红"] + [d[0] for d in DIFFS]
    sheet = Image.new("RGB", ((len(SEEDS) + 1) * tile, len(names) * tile), "white")
    for r, name in enumerate(names):
        row = [x for x in results if x[0] == name]
        box = row[0][3]
        cells = [("原图", base_img)] + [(f"s{s}", im) for _, s, im, _ in row]
        cells = cells[:len(SEEDS) + 1]
        for col, (lab, im) in enumerate(cells):
            sheet.paste(im.crop(box).resize((tile, tile), Image.LANCZOS), (col * tile, r * tile))
        ImageDraw.Draw(sheet).text((4, r * tile + 4), str(r + 1), fill="black")
    sheet.save(OUT / "总览.jpg", quality=90)
    json.dump({"base": str(BASE), "regions": REGIONS, "masks": MASKS, "diffs": DIFFS, "seeds": SEEDS,
               "neg": NEG, "steps": STEPS, "cfg": CFG}, open(OUT / "参数.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("全部完成，结果在：", OUT)


if __name__ == "__main__":
    main()
