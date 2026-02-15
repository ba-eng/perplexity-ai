# 多阶段构建：第一步构建前端WebUI静态资源
FROM node:18-alpine AS frontend-builder
WORKDIR /app
COPY ./perplexity/server/web/package*.json ./
RUN npm install
COPY ./perplexity/server/web/ ./
RUN NODE_OPTIONS=--max-old-space-size=512 npm run build

# 第二步：构建后端Python运行镜像
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

# 把前端构建好的静态资源，复制到项目正确目录
COPY --from=frontend-builder /app/dist /app/perplexity/server/web/dist

# 暴露服务端口
EXPOSE 8000

# 项目原生启动命令，完全兼容Render环境
CMD ["python", "-m", "uvicorn", "perplexity.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
