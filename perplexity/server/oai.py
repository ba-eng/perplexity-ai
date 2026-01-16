"""
OpenAI-compatible API endpoints.
Provides /v1/models and /v1/chat/completions routes.
"""

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

try:
    from ..config import SEARCH_LANGUAGES
except ImportError:
    from perplexity.config import SEARCH_LANGUAGES

from .utils import (
    generate_oai_models, parse_oai_model, create_oai_error_response,
    sanitize_query, validate_search_params,
)

from .app import mcp, get_pool, run_query, MCP_TOKEN


def _verify_auth(request: Request) -> Optional[JSONResponse]:
    """Verify Authorization header. Returns error response if invalid, None if valid."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth != f"Bearer {MCP_TOKEN}":
        return _create_error_response(
            "Unauthorized: Invalid or missing Bearer token",
            "authentication_error",
            401
        )
    return None


def _create_error_response(message: str, error_type: str, status_code: int) -> JSONResponse:
    """Create standardized OpenAI-format error response."""
    return JSONResponse(
        create_oai_error_response(message, error_type),
        status_code=status_code
    )


async def _run_query_streaming(
    query: str,
    mode: str,
    model: Optional[str] = None,
    sources: Optional[List[str]] = None,
    language: str = "en-US",
    incognito: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute a Perplexity query with streaming, yielding chunks."""
    pool = get_pool()
    client_id, client = pool.get_client()

    if client is None:
        yield {"error": "No available clients", "done": True}
        return

    try:
        clean_query = sanitize_query(query)
        chosen_sources = sources or ["web"]

        # Validate language
        if SEARCH_LANGUAGES is None or language not in SEARCH_LANGUAGES:
            valid_langs = ', '.join(SEARCH_LANGUAGES) if SEARCH_LANGUAGES else "en-US"
            yield {"error": f"Invalid language '{language}'. Choose from: {valid_langs}", "done": True}
            return

        validate_search_params(mode, model, chosen_sources, own_account=client.own)

        # Run streaming search in thread pool - get the generator
        def start_stream_search():
            return client.search(
                clean_query,
                mode=mode,
                model=model,
                sources=chosen_sources,
                stream=True,
                language=language,
                incognito=incognito,
            )

        response_gen = await asyncio.to_thread(start_stream_search)

        # Iterate through chunks in thread pool
        def get_next_chunk(gen):
            try:
                return next(gen)
            except StopIteration:
                return None

        while True:
            chunk = await asyncio.to_thread(get_next_chunk, response_gen)
            if chunk is None:
                break
            # Extract answer if present
            if "answer" in chunk:
                yield {"content": chunk["answer"], "done": False}

        yield {"content": "", "done": True}
        pool.mark_client_success(client_id)

    except Exception as exc:
        pool.mark_client_failure(client_id)
        yield {"error": str(exc), "done": True}


async def _non_stream_chat_response(
    query: str,
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int
) -> JSONResponse:
    """Generate non-streaming chat completion response."""
    # Call run_query in thread pool
    result = await asyncio.to_thread(run_query, query, mode, model)

    if result.get("status") == "error":
        error_msg = result.get("message", "Unknown error")
        error_type = result.get("error_type", "api_error")
        if error_type == "NoAvailableClients":
            return _create_error_response(error_msg, "service_unavailable", 503)
        return _create_error_response(error_msg, "api_error", 500)

    answer = result.get("data", {}).get("answer", "")

    # Approximate token counts
    prompt_tokens = len(query.split())
    completion_tokens = len(answer.split())

    return JSONResponse({
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": answer
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    })


async def _stream_chat_response(
    query: str,
    mode: str,
    model: Optional[str],
    model_id: str,
    response_id: str,
    created: int
) -> StreamingResponse:
    """Generate streaming SSE response."""

    async def event_generator():
        accumulated_content = ""

        async for chunk in _run_query_streaming(query, mode, model):
            if "error" in chunk:
                # Send error as final chunk
                error_data = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_id,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "error"
                    }]
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                yield "data: [DONE]\n\n"
                return

            if chunk.get("done"):
                # Send final chunk with finish_reason
                final_data = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_id,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }]
                }
                yield f"data: {json.dumps(final_data)}\n\n"
                yield "data: [DONE]\n\n"
                return

            content = chunk.get("content", "")
            if content and content != accumulated_content:
                # Calculate delta (new content since last chunk)
                delta_content = content[len(accumulated_content):]
                accumulated_content = content

                if delta_content:
                    chunk_data = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_id,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": delta_content},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# ==================== OpenAI-Compatible API Endpoints ====================

@mcp.custom_route("/v1/models", methods=["GET"])
async def oai_list_models(request: Request) -> JSONResponse:
    """OpenAI-compatible models list endpoint."""
    # Verify authentication
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    models = generate_oai_models()
    return JSONResponse({
        "object": "list",
        "data": models
    })


@mcp.custom_route("/v1/chat/completions", methods=["POST"])
async def oai_chat_completions(request: Request) -> Union[JSONResponse, StreamingResponse]:
    """OpenAI-compatible chat completions endpoint."""
    # Verify authentication
    auth_error = _verify_auth(request)
    if auth_error:
        return auth_error

    # Parse request body
    try:
        body = await request.json()
    except Exception:
        return _create_error_response("Invalid JSON body", "invalid_request_error", 400)

    # Validate required fields
    model_id = body.get("model")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    if not model_id:
        return _create_error_response("model is required", "invalid_request_error", 400)

    if not messages:
        return _create_error_response("messages is required", "invalid_request_error", 400)

    # Parse model to get mode and internal model
    try:
        mode, model = parse_oai_model(model_id)
    except ValueError as e:
        return _create_error_response(str(e), "invalid_request_error", 400)

    # Extract query from messages (use last user message)
    query = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                query = content
            elif isinstance(content, list):
                # Handle array content (text parts)
                query = " ".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            break

    if not query:
        return _create_error_response("No user message found", "invalid_request_error", 400)

    # Generate response ID and timestamp
    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if stream:
        return await _stream_chat_response(query, mode, model, model_id, response_id, created)
    else:
        return await _non_stream_chat_response(query, mode, model, model_id, response_id, created)
