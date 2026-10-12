# ===== PetPals 后端镜像 =====
# Python 3.11 + FastAPI(Uvicorn) + SQLite + ChromaDB
# 基础镜像可通过构建参数 PYTHON_BASE 覆盖（国内网络可用加速地址）
ARG PYTHON_BASE=python:3.11-slim
FROM ${PYTHON_BASE}

WORKDIR /app

# Python 运行环境：
# - PYTHONUNBUFFERED：日志实时输出，便于 docker logs 查看
# - PYTHONDONTWRITEBYTECODE：不生成 .pyc，保持镜像干净
# - PIP_NO_CACHE_DIR：pip 不留缓存，减小镜像层体积
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/app

# 系统依赖：libgomp1 供 ChromaDB 内置嵌入模型的 onnxruntime 使用
# （slim 镜像默认不含，缺失会导致向量检索/写入失败）
# APT_MIRROR 非空时切换为指定 Debian 镜像站根地址（如 https://mirrors.tuna.tsinghua.edu.cn）
ARG APT_MIRROR=""
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian-security|$APT_MIRROR/debian-security|g" \
            -e "s|https://deb.debian.org/debian-security|$APT_MIRROR/debian-security|g" \
            -e "s|http://security.debian.org/debian-security|$APT_MIRROR/debian-security|g" \
            -e "s|http://deb.debian.org/debian|$APT_MIRROR/debian|g" \
            -e "s|https://deb.debian.org/debian|$APT_MIRROR/debian|g" \
            /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 先单独复制并安装依赖，利用 Docker 分层缓存（代码变更不重装依赖）
# PIP_INDEX_URL 可覆盖为国内 PyPI 镜像（如华为云 / 清华 tuna / 阿里云）
# 使用 BuildKit 缓存挂载保存已下载的 wheel：网络抖动导致本层重试时，
# 已下载完成的包直接复用，不必每次从零开始。
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_NO_CACHE_DIR=0 pip install \
        -i ${PIP_INDEX_URL} \
        --retries 8 --timeout 120 \
        -r requirements.txt

# 复制项目源码
COPY . .

# 种子养宠文档复制到不受 uploads 卷覆盖的路径，供启动时自动索引进知识库
# （compose 会把命名卷挂到 /app/uploads，镜像里的 /app/uploads 会被覆盖）
RUN cp -r /app/uploads /app/seed_docs 2>/dev/null || true

# 数据目录（SQLite + Chroma 向量库）、上传目录、嵌入模型缓存目录，
# 运行时由 compose 挂载命名卷覆盖，提前建目录并授权给非 root 用户。
# 注意 /app/.cache 必须在此处建好并 chown：compose 把命名卷挂到该路径，
# 卷首次创建时会继承镜像里该目录的属主；若镜像中没有该目录，
# 卷会以 root 属主创建，非 root 的 appuser 将无法写入 →
# ChromaDB 下载嵌入模型失败（Permission denied: '/app/.cache/chroma'），知识库索引全部跳过。
RUN mkdir -p /app/data /app/uploads /app/.cache/chroma \
    && groupadd --system appuser \
    && useradd --system --gid appuser --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# 容器健康检查：访问根路由（无需额外安装 curl）
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"

# 生产模式启动（不使用 --reload）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
