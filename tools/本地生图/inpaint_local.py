# -*- coding: utf-8 -*-
"""
Claude娘 精修：脸部保持原样，只重绘头发 / 衣服（局部重绘 + Canny 线稿锁定）

  1. 自动做遮罩：背景（从四角漫水填充）+ 脸部椭圆 = 保护区，其余 = 重绘区
  2. 1024 上用 ControlNet Inpaint 重新上色（加刺绣、布料褶皱、头发光泽）
  3. 放大到 1536 低强度补细节
  4. 用羽化遮罩把保护区的原图像素贴回去 —— 脸和背景一个像素都不变

输入：第 2 轮选定的 B_075_cn70_s303_1536.png（可用命令行参数换）
输出：04_Claude娘桌宠/art/本地重绘/第3轮_局部重绘/
改脸部保护范围：调 FACE（1536 坐标下的椭圆中心与半径）。
"""
import os, sys, time, json
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
BASE = ROOT / "art" / "本地重绘" / "第2轮" / "B_075_cn70_s303_1536.png"
OUT  = ROOT / "art" / "本地重绘" / "第3轮_局部重绘"
if len(sys.argv) > 1:
    BASE = Path(sys.argv[1])

MODEL = "cagliostrolab/animagine-xl-4.0"
VAE   = "madebyollin/sdxl-vae-fp16-fix"
CN    = "xinsir/controlnet-canny-sdxl-1.0"

FACE = (660, 460, 165, 170)   # 1536 坐标：椭圆中心 x, y，半径 rx, ry（含眼睛、鼻、嘴、下巴）
FEATHER = 24                  # 保护区边缘羽化像素

# CLIP 只读前 77 个 token：画质/上色/细节词放最前
PROMPT = (
    "masterpiece, high score, absurdres, anime coloring, cel shading, soft shading, glossy hair, hair highlights, "
    "intricate embroidery, gold embroidery, lace trim, fabric folds, detailed clothes, 1girl, white gloves, "
    "orange hair, orange hair flower, white capelet, orange trim, black ascot, orange brooch, orange sash"
)
NEG = (
    "bare hands, yellow trim, lowres, bad anatomy, bad hands, worst quality, low quality, low score, bad score, "
    "flat color, monochrome, sketch, rough lines, blurry, text, signature, watermark, logo, emblem, chibi, child"
)

# (名字, 重绘强度, ControlNet 权重, seed)
JOBS = [
    ("I_045_cn70_s303", 0.45, 0.70, 303),
    ("I_055_cn70_s303", 0.55, 0.70, 303),
    ("I_065_cn70_s303", 0.65, 0.70, 303),
    ("I_055_cn50_s303", 0.55, 0.50, 303),
    ("I_065_cn50_s303", 0.65, 0.50, 303),
    ("I_055_cn70_s808", 0.55, 0.70, 808),
    ("I_065_cn60_s808", 0.65, 0.60, 808),
    ("I_075_cn60_s303", 0.75, 0.60, 303),
]
STEPS, CFG = 30, 5.0
HIRES_STRENGTH = 0.25
VRAM_FRACTION = 0.85   # 显存最多用 85%（16GB 卡约 13.5GB），留余量、绝不溢出到内存


def make_mask(img):
    """返回 1536 的重绘遮罩（L 模式，255 = 重绘）"""
    import numpy as np, cv2
    from PIL import Image, ImageDraw, ImageFilter
    a = np.array(img)
    h, w = a.shape[:2]
    # 背景：从四角漫水填充；逐像素比较邻居（容差 3），背景有渐变也能吃进去，黑色描线会挡住
    flood = np.zeros((h + 2, w + 2), np.uint8)
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(a.copy(), flood, seed, 0, (3,) * 3, (3,) * 3, cv2.FLOODFILL_MASK_ONLY | (255 << 8))
    bg = flood[1:-1, 1:-1] > 0
    bg = cv2.morphologyEx(bg.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
    protect = Image.fromarray((bg * 255).astype(np.uint8))
    cx, cy, rx, ry = FACE
    ImageDraw.Draw(protect).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    return Image.fromarray(255 - np.array(protect)).filter(ImageFilter.GaussianBlur(FEATHER / 2))


def main():
    import torch, numpy as np, cv2
    from PIL import Image
    from diffusers import (StableDiffusionXLImg2ImgPipeline, StableDiffusionXLControlNetInpaintPipeline,
                           ControlNetModel, AutoencoderKL, EulerAncestralDiscreteScheduler)

    if not torch.cuda.is_available():
        print("[错误] 没检测到 CUDA 显卡。")
        sys.exit(1)
    print("显卡：", torch.cuda.get_device_name(0), " PyTorch：", torch.__version__)
    OUT.mkdir(parents=True, exist_ok=True)

    base_img = Image.open(BASE).convert("RGB").resize((1536, 1536), Image.LANCZOS)
    mask = make_mask(base_img)
    mask.save(OUT / "_遮罩_白色为重绘.png")
    preview = Image.composite(base_img, Image.new("RGB", base_img.size, (255, 0, 255)), mask.point(lambda v: 255 - v))
    Image.blend(base_img, preview, 0.5).save(OUT / "_遮罩预览.jpg", quality=90)

    src = base_img.resize((1024, 1024), Image.LANCZOS)
    mask_1024 = mask.resize((1024, 1024), Image.LANCZOS)
    edges = cv2.Canny(np.array(src), 80, 180)
    canny = Image.fromarray(np.stack([edges] * 3, -1))

    print("加载模型…")
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    base = StableDiffusionXLImg2ImgPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16)
    base.scheduler = EulerAncestralDiscreteScheduler.from_config(base.scheduler.config)
    # 显存上限：超出直接报错，而不是让 Windows 偷偷借内存当显存（会慢几百倍）
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    base.vae.enable_tiling()   # 1536 解码分块
    base.to("cuda")
    cn = ControlNetModel.from_pretrained(CN, torch_dtype=torch.float16).to("cuda")
    # 直接复用底模组件；from_pipe 会在显卡上再复制一份底模（+6.5GB）
    c = base.components
    inpaint = StableDiffusionXLControlNetInpaintPipeline(
        vae=c["vae"], text_encoder=c["text_encoder"], text_encoder_2=c["text_encoder_2"],
        tokenizer=c["tokenizer"], tokenizer_2=c["tokenizer_2"], unet=c["unet"],
        controlnet=cn, scheduler=c["scheduler"])

    results = []
    for name, strength, cn_w, seed in JOBS:
        t = time.time()
        if (OUT / f"{name}_1536.png").exists():   # 已出过的跳过，方便中断后续跑
            results.append((name, Image.open(OUT / f"{name}_1536.png").convert("RGB")))
            print(f"  {name}  已存在，跳过")
            continue
        g = torch.Generator("cuda").manual_seed(seed)
        img = inpaint(prompt=PROMPT, negative_prompt=NEG, image=src, mask_image=mask_1024, control_image=canny,
                      strength=strength, controlnet_conditioning_scale=cn_w,
                      num_inference_steps=STEPS, guidance_scale=CFG, generator=g).images[0]

        # 放大到 1536 低强度补细节，再把保护区原图像素贴回去
        big = img.resize((1536, 1536), Image.LANCZOS)
        g2 = torch.Generator("cuda").manual_seed(seed)
        hi = base(prompt=PROMPT, negative_prompt=NEG, image=big, strength=HIRES_STRENGTH,
                  num_inference_steps=STEPS, guidance_scale=CFG, generator=g2).images[0]
        final = Image.composite(hi, base_img, mask)
        final.save(OUT / f"{name}_1536.png")
        results.append((name, final))
        print(f"  {name}  完成  {time.time() - t:.1f}s")

    tiles = [("底图", base_img)] + results
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 512, rows * 512), "white")
    for i, (_, im) in enumerate(tiles):
        sheet.paste(im.resize((512, 512), Image.LANCZOS), ((i % cols) * 512, (i // cols) * 512))
    sheet.save(OUT / "总览.jpg", quality=90)
    json.dump({"base": str(BASE), "face": FACE, "feather": FEATHER, "prompt": PROMPT, "neg": NEG, "jobs": JOBS,
               "steps": STEPS, "cfg": CFG, "hires_strength": HIRES_STRENGTH},
              open(OUT / "参数.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("全部完成，结果在：", OUT)


if __name__ == "__main__":
    main()
