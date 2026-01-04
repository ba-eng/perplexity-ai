
## 更新记录
2026-01-02：新增多token池支持，支持动态管理号池（列举/新增/删除）
2026-01-02：MCP 响应现在包含 `sources` 字段，返回搜索结果的来源链接
2025-12-31：增加健康检查endpoint， http://127.0.0.1:8000/health

## 启动服务


## docker compose 一键部署

### 1. 准备配置文件

从示例文件复制并编辑 `token_pool_config.json`：

```bash
# 复制示例配置文件
cp token_pool_config-example.json token_pool_config.json
```

编辑 `token_pool_config.json`，填入你的 Perplexity 账户 token：

```json
{
  "tokens": [
    {
      "id": "account1@example.com",
      "csrf_token": "your-csrf-token-1",
      "session_token": "your-session-token-1"
    },
    {
      "id": "account2@example.com",
      "csrf_token": "your-csrf-token-2",
      "session_token": "your-session-token-2"
    }
  ]
}
```

> **获取 Token 的方法：** 打开 perplexity.ai -> F12 开发者工具 -> Application -> Cookies
> - `csrf_token` 对应 `next-auth.csrf-token`
> - `session_token` 对应 `__Secure-next-auth.session-token`

### 2. 启动服务

```bash
# 创建 .env 文件（可选）
cp token_pool_config-example.json token_pool_config.json

cp .env.example .env

# 启动服务
docker compose up -d
```

### docker-compose.yml 配置示例

```yml
services:
  perplexity-mcp:
    image: shancw/perplexity-mcp:latest
    container_name: perplexity-mcp
    ports:
      - "${MCP_PORT:-8000}:8000"
    environment:
      # MCP 认证密钥
      - MCP_TOKEN=${MCP_TOKEN:-sk-123456}
      # 管理员 Token（用于号池管理 API，可选）
      - PPLX_ADMIN_TOKEN=${PPLX_ADMIN_TOKEN:-}
      # SOCKS 代理配置 (可选)
      # 格式: socks5://[user[:pass]@]host[:port][#remark]
      # - SOCKS_PROXY=${SOCKS_PROXY:-}
    volumes:
      # 挂载 token 池配置文件
      - ./token_pool_config.json:/app/token_pool_config.json:ro
    restart: unless-stopped
```

### .env 环境变量

```bash
# Perplexity MCP Server 环境变量配置
# 复制此文件为 .env 并填入实际值

# ============================================
# MCP 服务配置
# ============================================

# MCP 服务端口
MCP_PORT=8000

# MCP API 认证密钥 (客户端需要在 Authorization header 中携带此密钥)
MCP_TOKEN=sk-123456

# 管理员 Token（用于号池管理 API：新增/删除 token 等操作）
PPLX_ADMIN_TOKEN=your-admin-token
```

## 多token池配置（负载均衡）

支持配置多个 Perplexity 账户 token，实现负载均衡和高可用。

### 配置方式

1. 创建 JSON 配置文件 `token_pool_config.json`：
```json
{
  "tokens": [
    {
      "id": "user1",
      "csrf_token": "your-csrf-token-1",
      "session_token": "your-session-token-1"
    },
    {
      "id": "user2",
      "csrf_token": "your-csrf-token-2",
      "session_token": "your-session-token-2"
    }
  ]
}
```


## MCP 配置

```json
{
  "mcpServers": {
    "perplexity": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer sk-123456"
      }
    }
  }
}
```
## 注册为 Claude Code 指令

复制 `.claude/commands/pp/` 目录下创建指令文件：

使用方式：
- `/pp:query 你的问题` - 快速搜索
- `/pp:research 你的问题` - 深度研究
