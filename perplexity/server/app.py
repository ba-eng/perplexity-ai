"""
FastMCP application instance and shared utilities.
"""

import os
from typing import Any, Dict, Iterable, List, Optional, Union

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers

from .client_pool import ClientPool
from ..config import SEARCH_LANGUAGES
from ..exceptions import ValidationError

from .utils import (
    sanitize_query, validate_file_data, validate_query_limits, validate_search_params,
)

# API 密钥配置（从环境变量读取，默认为 sk-123456）
MCP_TOKEN = os.getenv("MCP_TOKEN", "sk-123456")


class AuthMiddleware(Middleware):
    """Bearer Token 认证中间件"""

    def __init__(self, token: str):
        self.token = token

    async def on_request(self, context: MiddlewareContext, call_next):
        """验证请求的 Authorization header"""
        headers = get_http_headers()
        if headers:  # HTTP 模式下才有 headers
            auth = headers.get("authorization") or headers.get("Authorization")
            if auth != f"Bearer {self.token}":
                raise PermissionError("Unauthorized: Invalid or missing Bearer token")
        return await call_next(context)


# Create FastMCP instance
mcp = FastMCP("perplexity-mcp")

# 添加认证中间件
mcp.add_middleware(AuthMiddleware(MCP_TOKEN))

# 全局 ClientPool 实例
_pool: Optional[ClientPool] = None


def get_pool() -> ClientPool:
    """Get or create the singleton ClientPool instance."""
    global _pool
    if _pool is None:
        _pool = ClientPool()
    return _pool


def normalize_files(files: Optional[Union[Dict[str, Any], Iterable[str]]]) -> Dict[str, Any]:
    """
    Accept either a dict of filename->data or an iterable of file paths,
    and normalize to the dict format expected by Client.search.
    """
    if not files:
        return {}

    if isinstance(files, dict):
        normalized = files
    else:
        normalized = {}
        for path in files:
            filename = os.path.basename(path)
            with open(path, "rb") as fh:
                normalized[filename] = fh.read()

    validate_file_data(normalized)
    return normalized


def extract_clean_result(response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the final answer and source links from the search response."""
    result = {}

    # 提取最终答案
    if "answer" in response:
        result["answer"] = response["answer"]

    # 提取来源链接
    sources = []

    # 方法1: 从 text 字段的 SEARCH_RESULTS 步骤中提取 web_results
    if "text" in response and isinstance(response["text"], list):
        for step in response["text"]:
            if isinstance(step, dict) and step.get("step_type") == "SEARCH_RESULTS":
                content = step.get("content", {})
                web_results = content.get("web_results", [])
                for web_result in web_results:
                    if isinstance(web_result, dict) and "url" in web_result:
                        source = {"url": web_result["url"]}
                        if "name" in web_result:
                            source["title"] = web_result["name"]
                        sources.append(source)

    # 方法2: 备用 - 从 chunks 字段提取（如果 chunks 包含 URL）
    if not sources and "chunks" in response and isinstance(response["chunks"], list):
        for chunk in response["chunks"]:
            if isinstance(chunk, dict):
                source = {}
                if "url" in chunk:
                    source["url"] = chunk["url"]
                if "title" in chunk:
                    source["title"] = chunk["title"]
                if "name" in chunk and "title" not in source:
                    source["title"] = chunk["name"]
                if "url" in source:
                    sources.append(source)

    result["sources"] = sources

    return result


def run_query(
    query: str,
    mode: str,
    model: Optional[str] = None,
    sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
    files: Optional[Union[Dict[str, Any], Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Execute a Perplexity query (non-streaming) and return the final response."""
    pool = get_pool()
    client_id, client = pool.get_client()

    if client is None:
        # All clients are in backoff
        earliest = pool.get_earliest_available_time()
        return {
            "status": "error",
            "error_type": "NoAvailableClients",
            "message": f"All clients are currently unavailable. Earliest available at: {earliest}",
        }

    try:
        clean_query = sanitize_query(query)
        chosen_sources = sources or ["web"]

        # Ensure SEARCH_LANGUAGES is not None before using 'in'
        if SEARCH_LANGUAGES is None or language not in SEARCH_LANGUAGES:
            valid_langs = ', '.join(SEARCH_LANGUAGES) if SEARCH_LANGUAGES else "en-US"
            raise ValidationError(
                f"Invalid language '{language}'. Choose from: {valid_langs}"
            )

        validate_search_params(mode, model, chosen_sources, own_account=client.own)
        normalized_files = normalize_files(files)
        validate_query_limits(client.copilot, client.file_upload, mode, len(normalized_files))

        response = client.search(
            clean_query,
            mode=mode,
            model=model,
            sources=chosen_sources,
            files=normalized_files,
            stream=False,
            language=language,
            incognito=incognito,
        )

        # Mark success
        pool.mark_client_success(client_id)

        # 只返回精简的最终结果
        clean_result = extract_clean_result(response)
        return {"status": "ok", "data": clean_result}
    except ValidationError as exc:
        # Pro mode specific failures (like quota exhausted) - reduce weight
        if mode == "pro" and "pro" in str(exc).lower():
            pool.mark_client_pro_failure(client_id)
        else:
            pool.mark_client_failure(client_id)
        return {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "message": str(exc),
        }
    except Exception as exc:
        # Check if it's a pro-related failure
        error_msg = str(exc).lower()
        if mode == "pro" and any(kw in error_msg for kw in ["pro", "quota", "limit", "remaining"]):
            pool.mark_client_pro_failure(client_id)
        else:
            # Mark general failure for exponential backoff
            pool.mark_client_failure(client_id)
        return {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "message": str(exc),
        }
