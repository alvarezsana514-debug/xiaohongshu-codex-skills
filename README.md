# Xiaohongshu Codex Skills

可公开、免 GitHub 登录安装的 Codex skills，采用 MIT 许可证。

## 固定版本安装链接

- [xiaohongshu-ai-comic-images v1.0.0](https://github.com/alvarezsana514-debug/xiaohongshu-codex-skills/tree/v1.0.0/xiaohongshu-ai-comic-images)
- [gpt-image-2-http v1.0.0](https://github.com/alvarezsana514-debug/xiaohongshu-codex-skills/tree/v1.0.0/gpt-image-2-http)

公开仓库和上述链接无需登录 GitHub 即可访问。

## 使用 Codex skill-installer 安装

在 Codex 中调用系统自带的 `skill-installer`，指定仓库、固定版本和要安装的目录：

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo alvarezsana514-debug/xiaohongshu-codex-skills \
  --ref v1.0.0 \
  --path xiaohongshu-ai-comic-images gpt-image-2-http
```

安装后重启 Codex，使新 skills 生效。

## Python 依赖

```bash
python3 -m pip install -r requirements.txt
```

依赖包括 `python-docx` 和 `pypdf`。

## 图片生成配置与风险说明

`gpt-image-2-http` 通过 `https://globalai.vip` 的 OpenAI 兼容接口生成或编辑图片。使用前需自行设置环境变量 `GLOBALAI_API_KEY`，请勿把密钥写入仓库、skill 文件、命令历史或公开截图。

调用该服务时，你的提示词、生成参数、所选参考图片，以及用于鉴权的 API 密钥会发送给 `globalai.vip`。这是第三方服务，并非 GitHub 或本仓库托管方；使用前请自行确认其隐私政策、数据留存规则、服务条款与可信度。不要发送无权披露的个人信息、机密资料或受限制图像。

脚本可进行文生图、参考图编辑，并把服务返回的图片保存到你指定的本地输出路径。生成效果、可用性、费用和内容合规由所使用的第三方接口及账户配置决定。

## 许可证

[MIT License](LICENSE)：允许复制、修改、商用和再发布，但必须保留版权及许可证文本。
