# web/rig — Anime2.5DRig 运行时（第三方，MIT）

来源：https://github.com/852wa/Anime2.5DRig （v2.0.0，Copyright (c) 2026 hakoniwa，MIT，见 LICENSE）
只复制了运行需要的 index.html、lib/*.js、lib/app.css；没带示例 PSD、测试、OBS 中继，
也没带 lib/vendor/face_mesh（只有开摄像头追踪才用到，桌宠不用）。

claude.psd 由 tools/本地生图/make_rig_psd.py 生成（See-through 拆层 + 修复 + 我们的闭眼/张嘴差分）。
桌宠用它的 OBS 透明显示模式（?obs=1&model=claude.psd），由 ../rig-driver.js 经 BroadcastChannel 发 face 消息控制表情。
