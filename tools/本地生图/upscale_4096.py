# -*- coding: utf-8 -*-
"""
定稿图 + 精选差分 → 4096×4096（Live2D 贴图用）

Real-ESRGAN x4 动漫模型（RealESRGAN_x4plus_anime_6B）放大 4 倍到 6144，再 Lanczos 缩到 4096。
差分图层：放大整张差分图，再把原图层的透明度放大后套上去 —— 和底图仍然逐像素对齐。

输入：art/定稿底图_v3_本地精修1536.png、art/差分/精选/*.png
输出：art/4096/
"""
import sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
BASE = ROOT / "art" / "定稿底图_v3_本地精修1536.png"
PICKS = ROOT / "art" / "差分" / "精选"
OUT = ROOT / "art" / "4096"
WEIGHTS = HERE / "models" / "RealESRGAN_x4plus_anime_6B.pth"
WEIGHTS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
TARGET = 4096
TILE, PAD = 512, 32                            # 分块放大，显存占用小
VRAM_FRACTION = 0.85   # 显存最多用 85%（16GB 卡约 13.5GB），留余量、绝不溢出到内存


def main():
    import torch, numpy as np
    from PIL import Image
    from spandrel import ModelLoader

    if not WEIGHTS.exists():
        WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        print("下载 Real-ESRGAN 动漫模型…")
        urllib.request.urlretrieve(WEIGHTS_URL, WEIGHTS)
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION, 0)
    model = ModelLoader().load_from_file(str(WEIGHTS)).eval().cuda().half()
    scale = model.scale

    @torch.no_grad()
    def upscale(img):
        x = torch.from_numpy(np.array(img.convert("RGB"))).permute(2, 0, 1).float().div(255)
        _, h, w = x.shape
        out = torch.zeros(3, h * scale, w * scale)
        for y0 in range(0, h, TILE):
            for x0 in range(0, w, TILE):
                ya, xa = max(y0 - PAD, 0), max(x0 - PAD, 0)
                yb, xb = min(y0 + TILE + PAD, h), min(x0 + TILE + PAD, w)
                t = model(x[:, ya:yb, xa:xb][None].cuda().half())[0].float().cpu()
                oy, ox = (y0 - ya) * scale, (x0 - xa) * scale
                th, tw = (min(y0 + TILE, h) - y0) * scale, (min(x0 + TILE, w) - x0) * scale
                out[:, y0 * scale:y0 * scale + th, x0 * scale:x0 * scale + tw] = t[:, oy:oy + th, ox:ox + tw]
        arr = out.clamp(0, 1).mul(255).round().byte().permute(1, 2, 0).numpy()
        return Image.fromarray(arr).resize((TARGET, TARGET), Image.LANCZOS)

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("定稿底图", BASE, None)]
    for p in sorted(PICKS.glob("*.png")):
        if not p.stem.endswith("_图层"):
            jobs.append((p.stem, p, PICKS / f"{p.stem}_图层.png"))
    for name, src, layer in jobs:
        t = time.time()
        big = upscale(Image.open(src))
        big.save(OUT / f"{name}_4096.png")
        if layer is not None and layer.exists():
            alpha = Image.open(layer).getchannel("A").resize((TARGET, TARGET), Image.LANCZOS)
            lay = big.convert("RGBA")
            lay.putalpha(alpha)
            lay.save(OUT / f"{name}_图层_4096.png")
        print(f"  {name}  完成  {time.time() - t:.1f}s", flush=True)
    print("全部完成，结果在：", OUT)


if __name__ == "__main__":
    main()
