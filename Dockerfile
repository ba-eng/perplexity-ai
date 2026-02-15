# 多阶段构建：第一步构建前端WebUI静态资源
FROM node:18-alpine AS frontend-builder
WORKDIR /app
# 复制前端依赖文件，利用Docker缓存
COPY ./perplexity/server/web/package*.json ./
RUN npm install
# 复制前端源码并构建
COPY ./perplexity/server/web/ ./
# 适配Render免费实例内存限制，避免构建溢出
RUN NODE_OPTIONS=--max-old-space-size=512 npm run build

# 第二步：构建后端Python运行镜像（和原项目环境完全兼容）
FROM python:3.11-slim
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目完整代码
COPY . .

# 把前端构建好的静态资源，复制到项目正确目录（解决WebUI 404）
COPY --from=frontend-builder /app/dist /app/perplexity/server/web/dist

# 暴露服务端口
EXPOSE 8000

# 原项目原生启动命令（100%兼容，彻底解决app找不到的报错）
CMD ["python", "-m", "perplexity.server"]
