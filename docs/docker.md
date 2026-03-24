# Docker 使用说明

## 概览

当前仓库提供 CPU / GPU 两套 Docker 交付，统一通过 `docker-compose.yml` 的 profile 切换：

- CPU 版：后端主环境内置 `faster-whisper`、`crawl4ai` 和 3 个 Downloader，不包含 `Wan2GP`
- GPU 版：在 CPU 版基础上额外内置共享本地模型运行时，用于 `Wan2GP` 与 GPU `faster-whisper`
- 前端镜像单独构建；浏览器默认访问前端 `http://localhost:3000`，前端默认通过 `http://localhost:8000/api/v1` 请求后端 API

## 设计说明

- 后端主应用使用仓库自带 `uv.lock`
- `faster-whisper` 在 CPU 版运行于后端主 `uv` 环境，GPU 版运行于 `LOCAL_MODEL_PYTHON_PATH` 指向的共享本地模型 Python 环境
- `crawl4ai` 除了包安装，还需要执行一次 `crawl4ai-setup` 完成 Playwright / 浏览器资源准备；Docker 镜像构建阶段已自动执行，无需容器使用者手动处理
- 3 个 Downloader 继续保留各自独立 `uv` 环境
- 只有 GPU 版保留共享本地模型 Python runtime，供 `Wan2GP` 与 GPU `faster-whisper` 共用
- 模型权重与运行时缓存不烘进镜像，而是落到 Docker 卷中持久化
- 后端容器启动时会自动执行 `uv run alembic upgrade head`，确保数据库 schema 与当前版本一致
- GPU 版会额外挂载 `Wan2GP` 的 `ckpts` 目录，避免删除并重建容器后重复下载本地模型文件

## 前置要求

- 已安装 Docker 与 Docker Compose Plugin
- CPU 版：无需 NVIDIA 依赖
- GPU 版：宿主机已安装 NVIDIA Container Toolkit，且 GPU 可被 Docker 访问

## 启动方式

启动 CPU 版：

```bash
docker compose --profile cpu up --build
```

启动 GPU 版：

```bash
docker compose --profile gpu up --build
```

可选环境变量：

- `BACKEND_PORT`：宿主机后端端口，默认 `8000`
- `FRONTEND_PORT`：宿主机前端端口，默认 `3000`
- `NEXT_PUBLIC_API_URL`：前端请求的后端 API 地址，默认跟随 `BACKEND_PORT`

例如把前后端改到 `3001/8001`：

```bash
BACKEND_PORT=8001 FRONTEND_PORT=3001 docker compose --profile gpu up --build
```

## Docker 开发模式

如果你希望像本地开发那样，修改前后端代码后立即在容器里看到效果，可以叠加使用开发态 override：

启动 CPU 开发版：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile cpu up --build
```

启动 GPU 开发版：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile gpu up --build
```

开发态行为：

- 前端改为 `next dev`，并挂载 `./frontend`
- 后端通过 `BACKEND_DEV_MODE=true` 切到 `uvicorn --reload`，并挂载 `./backend`
- 额外使用 named volume 保留容器内 `node_modules` / `.venv`，避免源码挂载把依赖目录覆盖掉
- 前端仍复用同一个 `Dockerfile.frontend`，通过 build arg `FRONTEND_MODE=development` 切到开发态

开发态与本地目录的同步关系：

- 与宿主机同步：`./backend -> /app/backend`
- 与宿主机同步：`./frontend -> /app/frontend`
- 与宿主机同步：`./docker/backend-entrypoint.sh -> /app/docker/backend-entrypoint.sh`
- 不与宿主机同步：`/data/app.db`
- 不与宿主机同步：`/data/storage`
- 不与宿主机同步：`/data/credentials`
- 不与宿主机同步：`/app/backend/.venv`
- 不与宿主机同步：`/app/frontend/node_modules`
- 不与宿主机同步：`/app/frontend/.next`
- 不与宿主机同步：`/opt/localvideo/external/Wan2GP/ckpts`

注意：

- 如果你修改了前端 `package.json` / `pnpm-lock.yaml`，容器启动时会自动重新执行一次 `pnpm install`
- 如果你修改了后端 `pyproject.toml` / `uv.lock`，后端容器启动时会自动重新执行一次 `uv sync`
- GPU 开发版仍然要求宿主机具备 NVIDIA Container Toolkit

如果需要通过环境文件覆盖 build args 或在线服务密钥：

```bash
docker compose --env-file .env.docker --profile cpu up -d --build
docker compose --env-file .env.docker --profile gpu up -d --build
```

启动后默认访问：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

## 持久化内容

`backend-cpu` / `backend-gpu` 共用命名卷 `localvideo-data` 持久化以下内容：

- SQLite 数据库：`/data/app.db`
- LocalVideo 存储目录：`/data/storage`
- Google 服务账号目录：`/data/credentials`
- Hugging Face / Transformers / Torch 缓存：`/data/cache/...`

`backend-gpu` 额外使用命名卷 `localvideo-wan2gp-ckpts` 持久化：

- Wan2GP 本地模型目录：`/opt/localvideo/external/Wan2GP/ckpts`

删除并重建容器后，数据库、素材、Wan2GP 已下载模型与模型缓存仍会保留。

## 可覆盖的构建参数

CPU / GPU 共用：

- `TIKTOK_DOWNLOADER_REF`
- `XHS_DOWNLOADER_REF`
- `KS_DOWNLOADER_REF`
- `NEXT_PUBLIC_API_URL`
- `INTERNAL_API_URL`
- `TZ`

GPU 专用：

- `WAN2GP_REF`
- `WAN2GP_PYTHON_VERSION`
- `TORCH_CUDA_INDEX_URL`
- `TORCH_VERSION`
- `TORCHVISION_VERSION`
- `TORCHAUDIO_VERSION`

仓库内提供了示例文件 [`.env.docker.example`](../.env.docker.example)。

## 运行时关键环境变量

CPU / GPU 共用：

- `DEPLOYMENT_PROFILE`
- `XHS_DOWNLOADER_PATH`
- `TIKTOK_DOWNLOADER_PATH`
- `KS_DOWNLOADER_PATH`
- `DATABASE_URL`
- `STORAGE_PATH`
- `NEXT_PUBLIC_API_URL`
- `INTERNAL_API_URL`
- `TZ`

GPU 版额外提供：

- `WAN2GP_PATH=/opt/localvideo/external/Wan2GP`
- `LOCAL_MODEL_PYTHON_PATH=/opt/localvideo/runtime310/bin/python`

在线服务密钥仍需用户自行提供，例如：

- `TEXT_OPENAI_API_KEY`
- `IMAGE_OPENAI_API_KEY`
- `IMAGE_GEMINI_API_KEY`
- `SEARCH_TAVILY_API_KEY`
- `JINA_READER_API_KEY`

## 构建差异

- CPU 版构建更快，镜像体积更小，适合开发和无 GPU 机器
- GPU 版会额外拉取 CUDA 基础镜像并安装 `Wan2GP` runtime，构建时间明显更长
- 两个版本都会在首次运行或首次校验时下载对应模型并写入缓存；其中 GPU 版的 Wan2GP 还可能在首次校验、预览或生成时初始化一批通用共享模型（例如 `pose`、`depth`、`flow`、`scribble` 等），这些文件会保存在 `localvideo-wan2gp-ckpts` 卷中

## 构建缓存行为

- `Dockerfile.backend` 已按“外部仓库 -> Python 依赖 -> 运行时代码”分层；仅修改 `backend/app`、`backend/scripts`、`backend/alembic` 等业务代码后重新 `--build`，通常不会重跑 `apt-get install`、`crawl4ai-setup`、Downloader 依赖安装、GPU `torch` / Wan2GP runtime 安装
- `crawl4ai` 的浏览器资源改为单独缓存并烘进镜像；在同一个 BuildKit builder 上重复构建时，通常不会再次完整下载 Playwright / Patchright 的 Chromium 资源
- 修改 `backend/pyproject.toml` 或 `backend/uv.lock` 后，后端 Python 依赖层会失效并重新执行 `uv sync`
- 修改 `Dockerfile.backend` 里系统包列表、基础镜像、`uv` 安装逻辑时，系统依赖层会失效并重新构建
- 修改 `WAN2GP_REF`、`TIKTOK_DOWNLOADER_REF`、`XHS_DOWNLOADER_REF`、`KS_DOWNLOADER_REF` 等 build args 时，只会让外部源码层及其下游层失效
- 上述缓存优化依赖 BuildKit。当前 Docker/Compose 的默认行为通常已启用；如果你的环境显式关闭了 BuildKit，缓存收益会变差
- 首次 GPU 构建仍然会较慢，因为 CUDA 基础镜像上的系统包、Chromium 浏览器资源、GPU `torch` 与 Wan2GP runtime 本身就很大；优化重点是减少后续重复构建时的重新下载

## 何时需要 `--build`

- 仅重启已有容器：`docker compose --profile cpu up -d` / `docker compose --profile gpu up -d`
- 修改了后端或前端源码，并且当前使用的是生产式镜像启动：需要带 `--build`
- 修改了依赖文件、Dockerfile、Compose build args：需要带 `--build`
- 叠加 `docker-compose.dev.yml` 时，前后端源码会以挂载目录方式进入容器；这时日常改业务代码通常不需要重新 build，但改依赖文件后容器启动时仍会重新执行 `uv sync` / `pnpm install`

## 常见命令

查看最终 Compose 配置：

```bash
docker compose config
docker compose --profile cpu config
docker compose --profile gpu config
```

停止服务并删除容器（保留数据卷）：

```bash
docker compose --profile cpu down
docker compose --profile gpu down
```

删除容器并清理数据卷：

```bash
docker compose --profile cpu down -v
docker compose --profile gpu down -v
```

注意：

- `docker compose config` 在不带 profile 时只会展示未绑定 profile 的服务；当前仓库里通常只会看到 `frontend`
- `docker compose down` / `docker compose down -v` 也建议带上与启动时相同的 profile；否则 CPU/GPU 后端容器可能不会被移除，对应的数据卷也可能继续处于占用状态
