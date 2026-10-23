# -*- coding: utf-8 -*-
"""
把 4096 定稿图 + 表情差分图层打包成一个 PSD，作为 Live2D 拆层的起点。

图层（从下到上）：
  定稿底图                      —— 整张立绘
  表情差分/（组，默认全部隐藏）
    闭眼、半闭眼、微笑、张嘴a、张嘴o、脸红、星星眼、爱心眼、晕圈眼
                                —— 只含改动区域的透明图层，和底图逐像素对齐

差分图层只裁到非透明区域再放进去（带偏移），PSD 体积小很多，位置不变。
输入：art/4096/；输出：art/Claude娘_拆层起点_4096.psd
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # 04_Claude娘桌宠
SRC = ROOT / "art" / "4096"
OUT = ROOT / "art" / "Claude娘_拆层起点_4096.psd"
ORDER = ["闭眼", "半闭眼", "微笑", "张嘴a", "张嘴o", "脸红", "星星眼", "爱心眼", "晕圈眼"]


def main():
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer, Group

    from psd_tools.constants import Tag

    def named(layer, name):
        # frompil 只写旧式 Pascal 名字；补上 Unicode 名（luni），CSP / 非中文系统才不乱码
        layer.tagged_blocks.set_data(Tag.UNICODE_LAYER_NAME, name)
        return layer

    base = Image.open(SRC / "定稿底图_4096.png").convert("RGB")
    # 必须 RGBA：RGB 文档里 psd-tools 会把透明度存成图层蒙版，很多解析器（如 ag-psd）不读蒙版 → 透明处变实底
    psd = PSDImage.new("RGBA", base.size)
    psd.append(named(PixelLayer.frompil(base, psd, "定稿底图"), "定稿底图"))

    layers = []
    for name in ORDER:
        p = SRC / f"{name}_图层_4096.png"
        if not p.exists():
            print("  缺少", p.name); continue
        im = Image.open(p).convert("RGBA")
        bbox = im.getchannel("A").getbbox()
        if not bbox:
            continue
        lay = named(PixelLayer.frompil(im.crop(bbox), psd, name, top=bbox[1], left=bbox[0]), name)
        lay.visible = False
        psd.append(lay)
        layers.append(lay)
        print(f"  {name}: {bbox}")
    Group.group_layers(psd, layers, name="表情差分")   # 先挂到 psd 上，再收进组
    # 拼合图像需要 psd-tools[composite]；旧式图层名用 GBK（中文版 PS 读它），Unicode 名另存一份
    psd.save(OUT, encoding="gbk")
    print("已保存：", OUT, f"{OUT.stat().st_size / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
