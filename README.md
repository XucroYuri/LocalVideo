# LocalVideo

<p align="center">
  <img src="./assets/banner.jpg" alt="LocalVideo Banner" width="800px" />
</p>

<p align="center">
  <b>面向内容创作者的 AI 视频全流程迭代流水线</b>
</p>

<p align="center">
  <a href="./README.md">中文</a> | <a href="./README_EN.md">English</a>
</p>

---

## ✨ 项目特色
LocalVideo 不仅是一个“生视频”的工具，而是一个**可迭代的创作工作台**。AI 视频创作不应是“单次调模型出结果”的博弈，而是一个**从想法到成片的工业化过程**。

LocalVideo 强调项目式编排：你可以把素材库、角色设定、语音配置和各阶段输出保存在同一个项目里，按阶段重跑、替换、复用，实现真正的“精修”与“生产”。

LocalVideo 既具备视频编排能力，也拥有区别于传统工具的独特设计。

### 1. 全链路视频编排 (通用能力)
这些是构建一条高质量视频的基础，LocalVideo 已经将其串联成自动化流水线：
*   **文案与结构化提取：** 自动生成文案，并智能提取角色、场景等结构化信息。
*   **智能分镜描述：** 自动生成细化分镜头 Prompt，精准把控画面节奏。
*   **多角色语音合成：** 支持多角色对白，自定义角色声线。
*   **主线视频引擎 + 本地回退：** 默认使用 Seedance 2.0（`kwjm.com` 兼容火山方案）完成视频生成；当 API 不可用时，可自动切换到本地 Wan2GP。
*   **视觉一致性维护：** 生成风格一致的首帧图与视频，减少角色“飘移”。
*   **自动化合成：** 一键完成音画对齐、字幕生成与视频渲染。

### 2. LocalVideo 特色 (Why LocalVideo?)
*   **独有的创作分类法：** 针对不同创作逻辑，划分了 **“口播文案驱动”** 与 **“声画驱动”**（开发中） 两种模式，深度优化文案类视频的产出效率。
*   **全栈本地模型支持：** 深度适配本地 GPU 环境。音频、图片与本地视频回退能力均可离线运行，可实现 **零 API 成本** 与保障隐私。
*   **联网搜索与 DeepResearch 上下文：** 支持联网搜索、DeepResearch、网页链接解析，并将结果沉淀为项目上下文，方便后续文案生成。
*   **外部内容闭环：** 内置视频链接解析与下载功能，支持将外部视频素材转化为可编辑的创作输入，实现“外部内容 -> 素材提取 -> 二次创作”的闭环。
*   **项目级素材积累：** 参考图库、语音库、文本库在项目间通用，让每一次创作都在沉淀数字资产，而非从零开始。

---

## 🎬 演示预览

<details>
<summary>点击展开界面预览</summary>

### 首页展示
![首页展示预览](./assets/home_page.png)

### 分镜编辑
![分镜编辑预览](./assets/shot_edit.png)

### 分镜展示
![分镜展示预览](./assets/shot_show.png)
</details>

---

## 🛠️ 快速上手

推荐使用 **Docker** 快速体验完整功能。

### 方式 A：Docker 部署 (推荐)

```bash
# CPU 模式 (主要使用 Seedance 2.0 API)
docker compose --profile cpu up --build

# GPU 模式 (启用 Wan2GP 本地生成模型能力)
docker compose --profile gpu up --build
```
> 访问地址：前端 `http://localhost:3000` | 后端 `http://localhost:8000`

### 方式 B：本地开发环境

**要求：** Python 3.11+, Node.js 22+, `uv`, `pnpm`

1. **后端：**
   ```bash
   cd backend
   uv sync && uv run alembic upgrade head
   uv run uvicorn app.main:app --reload --port 8000 # CPU 模式
   DEPLOYMENT_PROFILE=gpu uv run uvicorn app.main:app --reload --port 8000 # GPU 模式, 需自行配置 Wan2GP 启动环境
   ```
2. **前端：**
   ```bash
   cd frontend
   pnpm install && pnpm dev
   ```

---

## 🧠 本地模型

LocalVideo 当前的视频主引擎为 **Seedance 2.0**，并通过 **Wan2GP** 提供本地音频、图片与视频回退能力；本地视频最高支持 1080p 分辨率。

使用 Flux 2 Klein 4B + LTX-2 2.3 Distilled 22B 的组合，在使用 RTX 4070 (12GB) 显卡的情况下，1小时即可生成约 60s 1080P 分辨率的视频。

<details>
<summary>点击展开模型列表</summary>

### 音频生成

| 模型名 | 参数规模 | 音色能力 |
| --- | --- | --- |
| Qwen3 Base (12Hz) | 1.7B | 参考音频克隆 |
| Qwen3 Custom Voice (12Hz) | 1.7B | 预置音色 |
| Qwen3 Voice Design (12Hz) | 1.7B | 文本指定音色 |

### 图片生成

| 模型名 | 参数规模 | 支持模式 | 推理步数 | 中英文 Prompt 支持度 |
| --- | --- | --- | --- | --- |
| Flux 1 Dev | 12B | T2I | 30 | 英文优先，中文较弱 |
| Flux Schnell | 12B | T2I | 10 | 英文优先，中文较弱 |
| Z-Image Turbo | 6B | T2I | 8 | 中英均衡 |
| Z-Image Base | 6B | T2I | 30 | 中英均衡 |
| Qwen Image | 20B | T2I | 30 | 中文强，英文可用 |
| Qwen Image 2512 Release | 20B | T2I | 30 | 中文强，英文可用 |
| Flux 2 Dev | 32B | T2I / I2I | 30 | 英文优先，中文可用 |
| Flux 2 Dev NVFP4 | 32B | T2I / I2I | 30 | 英文优先，中文可用 |
| pi-FLUX.2 Dev | 32B | T2I / I2I | 4 | 英文优先，中文可用 |
| pi-FLUX.2 Dev NVFP4 | 32B | T2I / I2I | 4 | 英文优先，中文可用 |
| Flux 2 Klein | 4B / 9B | T2I / I2I | 4 | 中英均衡 |
| Flux 2 Klein Base | 4B / 9B | T2I / I2I | 30 | 中英均衡 |
| Flux Dev Kontext | 12B | I2I | 30 | 英文优先，中文较弱 |
| Flux DreamOmni2 | 12B | I2I | 30 | 英文优先，中文较弱 |
| Qwen Image Edit | 20B | T2I / I2I | 30 | 中文强，英文可用 |
| Qwen Image Edit Plus | 20B | T2I / I2I | 30 | 中文强，英文可用 |
| Qwen Image Edit Plus (2509) | 20B | T2I / I2I | 30 | 中文强，英文可用 |
| Qwen Image Edit Plus (2509) Nunchaku FP4 | 20B | T2I / I2I | 4 | 中文强，英文可用 |
| Qwen Image Edit Plus (2511) | 20B | T2I / I2I | 30 | 中文强，英文可用 |

### 视频生成

| 模型名 | 参数规模 | 支持模式 | 默认帧率 | 推理步数 | 中英文 Prompt 支持度 |
| --- | --- | --- | --- | --- | --- |
| Wan 2.1 | 1.3B / 14B | T2V / I2V | 16 fps | 30 | 中英均衡 |
| Wan 2.2 | 14B | T2V / I2V | 16 fps | 30 | 中英均衡 |
| Hunyuan 1.5 720p | 8B | T2V / I2V | 24 fps | 30 | 中英均衡 |
| Hunyuan 1.5 480p | 8B | T2V / I2V | 24 fps | 30 | 中英均衡 |
| Fun InP | 1.3B / 14B | I2V | 16 fps | 30 | 中英均衡 |
| LTX-2 2.3 Dev | 22B | T2V / I2V | 24 fps | 30 | 英文优先，中文较弱 |
| LTX-2 2.3 Distilled | 22B | T2V / I2V | 24 fps | 8 | 英文优先，中文较弱 |

说明：部分 Wan2GP 视频模型的名字里会带 `480p`、`720p` 这类字样，例如 `Hunyuan 1.5 T2V 480p` 和 `Hunyuan 1.5 T2V 720p`。这里的 `480p/720p` 更接近该模型的默认或原生分辨率，实际能生成的分辨率更加广泛。但不同模型在不同分辨率下的画质、显存占用和稳定性仍会有差异。
</details>

---

## 🔄 典型创作流程

1. **创建项目：** 选择模版（单人叙述/双人播客/台词剧本）。
2. **内容输入：** 导入上下文，生成文案。
3. **角色分配：** 从素材库挑选语音和形象参考。
4. **迭代生成：** 拆解分镜 -> 音频 -> 画面 -> 视频。
5. **合成导出：** 一键生成带字幕的完整成片。

---

## 🎯 适合谁？

*   ✅ **专业创作者：** 需要制作口播、播客、短剧，且对内容有精细控制要求。
*   ✅ **本地玩家：** 拥有强力 GPU，希望在本地运行全套 AI 视频工作流。
*   ✅ **效率专家：** 厌倦了在多个 AI 工具间切换，需要一个统一的创作管理平台。

---

## 🙏 致谢

LocalVideo 的部分能力依赖接入优秀的开源项目，感谢这些项目的工作：

### 本地模型能力

- [Wan2GP](https://github.com/deepbeepmeep/Wan2GP)

### 视频链接解析与下载

- [XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)
- [TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader)
- [KS-Downloader](https://github.com/JoeanAmier/KS-Downloader)

### 网页链接解析
- [Jina Reader](https://github.com/jina-ai/reader)
- [Crawl4AI](https://github.com/unclecode/crawl4ai)

---

## Star History

<a href="https://www.star-history.com/?repos=XucroYuri%2FLocalVideo&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=XucroYuri/LocalVideo&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=XucroYuri/LocalVideo&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=XucroYuri/LocalVideo&type=date&legend=top-left" />
 </picture>
</a>
