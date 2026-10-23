# -*- coding: utf-8 -*-
"""
Claude娘 立绘本地重绘（RTX 50 系 / 任何 12GB+ 显存 N 卡）

只重新上色、细化线条，不改动作和角度：
  A. img2img      —— 以原图为底，低重绘强度（0.35 / 0.45 / 0.55）
  B. 线稿锁定      —— 先用 Canny 抽出原图线稿当 ControlNet，再以较高强度重新上色
每张再做一次 1.5 倍高清放大（1536×1536，低强度 0.3，只补细节）。

输出：04_Claude娘桌宠/art/本地重绘/（另附 总览.jpg）
改参数：直接编辑下面的 JOBS / PROMPT。
"""
import os, sys, time, json
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
SRC  = ROOT / "art" / "AI试图" / "候选B_d1_侧脸看镜头.png"
ROUND = "第2轮"                                # 每轮输出到单独子文件夹，方便对比
OUT  = ROOT / "art" / "本地重绘" / ROUND
if len(sys.argv) > 1:
    SRC = Path(sys.argv[1])

MODEL = "cagliostrolab/animagine-xl-4.0"
VAE   = "madebyollin/sdxl-vae-fp16-fix"
CN    = "xinsir/controlnet-canny-sdxl-1.0"

# CLIP 只读前 77 个 token，超出部分会被丢掉：画质/上色词放最前，必须保留的服装词紧随其后
PROMPT = (
    "masterpiece, high score, absurdres, anime coloring, soft shading, glossy hair, hair highlights, detailed eyes, "
    "1girl, white gloves, orange hair, red eyes, expressionless, hands on book, orange hair flower, frilled collar, "
    "black ascot, orange brooch, white capelet, orange trim, orange sash"
)   # 构图/姿势交给线稿锁定，这里只留画质、上色和容易画错的服装词
NEG = (
    "bare hands, yellow trim, lowres, bad anatomy, bad hands, worst quality, low quality, low score, bad score, "
    "flat color, monochrome, sketch, rough lines, blurry, text, signature, watermark, logo, emblem, chibi, child"
)

# (名字, 模式, 重绘强度, ControlNet 权重, seed)；第 1 轮结论：B_065 最接近，围绕它细调
JOBS = [
    ("B_060_cn60_s303",  "cn", 0.60, 0.60, 303),
    ("B_065_cn60_s303",  "cn", 0.65, 0.60, 303),
    ("B_070_cn60_s303",  "cn", 0.70, 0.60, 303),
    ("B_065_cn70_s303",  "cn", 0.65, 0.70, 303),
    ("B_075_cn70_s303",  "cn", 0.75, 0.70, 303),
    ("B_065_cn60_s808",  "cn", 0.65, 0.60, 808),
    ("B_065_cn60_s1234", "cn", 0.65, 0.60, 1234),
    ("B_070_cn65_s2024", "cn", 0.70, 0.65, 2024),
]
STEPS, CFG = 30, 5.0
HIRES_SCALE, HIRES_STRENGTH = 1.5, 0.30
VRAM_FRACTION = 0.85   # 显存最多用 85%（16GB 卡约 13.5GB），留余量、绝不溢出到内存


def main():
    import torch, numpy as np, cv2
    from PIL import Image
    from diffusers import (StableDiffusionXLImg2ImgPipeline, StableDiffusionXLControlNetImg2ImgPipeline,
                           ControlNetModel, AutoencoderKL, EulerAncestralDiscreteScheduler)

    if not torch.cuda.is_available():
        print("[错误] 没检测到 CUDA 显卡。请确认装的是 cu128 版 PyTorch、显卡驱动是最新的。")
        sys.exit(1)
    print("显卡：", torch.cuda.get_device_name(0), " PyTorch：", torch.__version__)
    OUT.mkdir(parents=True, exist_ok=True)

    src = Image.open(SRC).convert("RGB").resize((1024, 1024), Image.LANCZOS)
    edges = cv2.Canny(np.array(src), 80, 180)
    canny = Image.fromarray(np.stack([edges] * 3, -1))
    canny.save(OUT / "_线稿_canny.png")

    print("加载模型（第一次会下载约 7GB，之后走缓存）…")
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    base = StableDiffusionXLImg2ImgPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=torch.float16)
    base.scheduler = EulerAncestralDiscreteScheduler.from_config(base.scheduler.config)
    # 显存上限：超出直接报错，而不是让 Windows 偷偷借内存当显存（会慢几百倍）
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    base.vae.enable_tiling()   # 1536 解码分块（不分块时解码峰值会把 16GB 撑爆）
    base.to("cuda")            # 权重约 6.5GB，加 ControlNet 共 8.8GB，常驻显卡
    cn_pipe = None

    results = []
    for name, mode, strength, cn_w, seed in JOBS:
        t = time.time()
        if (OUT / f"{name}_1536.png").exists():   # 已出过的跳过，方便中断后续跑
            results.append((name, Image.open(OUT / f"{name}_1536.png").convert("RGB")))
            print(f"  {name}  已存在，跳过")
            continue
        g = torch.Generator("cuda").manual_seed(seed)
        if mode == "cn":
            if cn_pipe is None:
                cn = ControlNetModel.from_pretrained(CN, torch_dtype=torch.float16).to("cuda")
                # 直接复用底模组件；from_pipe 会在显卡上再复制一份底模（+6.5GB）
                c = base.components
                cn_pipe = StableDiffusionXLControlNetImg2ImgPipeline(
                    vae=c["vae"], text_encoder=c["text_encoder"], text_encoder_2=c["text_encoder_2"],
                    tokenizer=c["tokenizer"], tokenizer_2=c["tokenizer_2"], unet=c["unet"],
                    controlnet=cn, scheduler=c["scheduler"])
            img = cn_pipe(prompt=PROMPT, negative_prompt=NEG, image=src, control_image=canny,
                          strength=strength, controlnet_conditioning_scale=cn_w,
                          num_inference_steps=STEPS, guidance_scale=CFG, generator=g).images[0]
        else:
            img = base(prompt=PROMPT, negative_prompt=NEG, image=src, strength=strength,
                       num_inference_steps=STEPS, guidance_scale=CFG, generator=g).images[0]
        img.save(OUT / f"{name}_1024.png")

        # 高清放大：先 Lanczos 放大，再低强度重绘补细节（构图不会变）
        big = img.resize((int(1024 * HIRES_SCALE), int(1024 * HIRES_SCALE)), Image.LANCZOS)
        g2 = torch.Generator("cuda").manual_seed(seed)
        hi = base(prompt=PROMPT, negative_prompt=NEG, image=big, strength=HIRES_STRENGTH,
                  num_inference_steps=STEPS, guidance_scale=CFG, generator=g2).images[0]
        hi.save(OUT / f"{name}_1536.png")
        results.append((name, hi))
        print(f"  {name}  完成  {time.time() - t:.1f}s")

    # 总览：原图 + 每张结果
    tiles = [("原图", src)] + results
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 512, rows * 512), "white")
    for i, (_, im) in enumerate(tiles):
        sheet.paste(im.resize((512, 512), Image.LANCZOS), ((i % cols) * 512, (i // cols) * 512))
    sheet.save(OUT / "总览.jpg", quality=90)
    json.dump({"src": str(SRC), "prompt": PROMPT, "neg": NEG, "jobs": JOBS, "steps": STEPS, "cfg": CFG},
              open(OUT / "参数.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("全部完成，结果在：", OUT)


if __name__ == "__main__":
    main()
