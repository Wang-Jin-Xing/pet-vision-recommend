# ===== 阶段 1：Node 编译 React + Vite 静态产物 =====
# 基础镜像可通过构建参数覆盖（国内网络可用加速地址）
# 注意：供 FROM 使用的 ARG 必须声明在第一个 FROM 之前（全局 ARG）
ARG NODE_BASE=node:20-alpine
ARG NGINX_BASE=nginx:alpine
FROM ${NODE_BASE} AS builder

WORKDIR /app

# npm 源可通过 NPM_REGISTRY 覆盖（国内可用 https://registry.npmmirror.com）
ARG NPM_REGISTRY=https://registry.npmjs.org/

# 先复制依赖清单并安装（含 lockfile，npm ci 可复现安装），利用分层缓存
COPY package.json package-lock.json ./
RUN npm config set registry ${NPM_REGISTRY} && npm ci --no-audit --no-fund

# 复制源码并构建，产物输出到 /app/dist
COPY . .
RUN npm run build

# ===== 阶段 2：Nginx 托管静态文件并反向代理 /api =====
FROM ${NGINX_BASE}

# 自定义站点配置（SPA 回退 + /api 反代后端）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 仅拷贝构建产物，镜像中不含 node 源码与 node_modules
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
