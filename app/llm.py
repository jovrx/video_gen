"""Small OpenAI-compatible text client; provider responses never become API errors."""
import asyncio
import json
import math
import re
from urllib.parse import urlsplit

import httpx

from app.config import Settings


class TextModelError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class TextModel:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.settings = settings
        self.http = http

    @property
    def configured(self) -> bool:
        try:
            url = urlsplit(self.settings.llm_base_url)
            return bool(self.settings.llm_api_key.strip() and self.settings.llm_model.strip()
                        and url.scheme in {"http", "https"} and url.hostname
                        and (url.port is None or 0 < url.port <= 65535)
                        and not (url.username or url.password or url.query or url.fragment))
        except ValueError:
            return False

    async def close(self):
        if self.http is not None:
            await self.http.aclose()

    async def stream(self, system: str, user: str):
        """Yield actual provider content deltas; never retry a paid request."""
        if not self.configured:
            raise TextModelError("请在 .env 中配置有效的 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL，并重启服务", 503)
        timeout = self.settings.llm_timeout_seconds
        timeout = max(1, min(600, timeout)) if math.isfinite(timeout) else 120
        if self.http is None:
            self.http = httpx.AsyncClient(follow_redirects=False)
        finished = False
        received = False
        size = 0
        try:
            async with asyncio.timeout(timeout):
                async with self.http.stream(
                    "POST", self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json={"model": self.settings.llm_model, "stream": True, "messages": [
                        {"role": "system", "content": system}, {"role": "user", "content": user}]},
                    timeout=timeout,
                ) as response:
                    if response.status_code in {401, 403}:
                        raise TextModelError("文本模型认证失败，请检查 LLM_API_KEY 和模型访问权限")
                    if response.status_code == 429:
                        raise TextModelError("文本模型请求受限，请稍后再试", 429)
                    if not 200 <= response.status_code < 300:
                        raise TextModelError("文本模型服务暂不可用，请检查服务地址和模型名")
                    if "text/event-stream" not in response.headers.get("content-type", "").lower():
                        raise TextModelError("文本模型服务未返回流式响应，请检查模型是否支持流式输出")
                    data = []
                    async for line in response.aiter_lines():
                        size += len(line.encode("utf-8"))
                        if size > 3 * 1024 * 1024:
                            raise TextModelError("文本模型返回内容过长，请减少分镜数量或缩短剧本")
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip(" "))
                        if line or not data:
                            continue
                        payload = "\n".join(data)
                        data = []
                        if payload == "[DONE]":
                            finished = True
                            break
                        envelope = json.loads(payload)
                        if not isinstance(envelope, dict) or envelope.get("error"):
                            raise ValueError("invalid stream event")
                        choices = envelope.get("choices", [])
                        if not choices:  # Optional usage-only event.
                            continue
                        choice = choices[0]
                        reason = choice.get("finish_reason")
                        if reason in {"length", "content_filter"}:
                            raise TextModelError("文本模型输出未完成，请减少生成内容或调整输入后重试")
                        if reason:
                            finished = True
                        content = choice.get("delta", {}).get("content")
                        if content is not None:
                            if not isinstance(content, str):
                                raise ValueError("invalid content delta")
                            if content:
                                received = True
                                yield content
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise TextModelError("文本模型请求超时，请稍后重试或减少生成内容", 504) from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise TextModelError("无法连接文本模型服务，请检查服务地址和网络") from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError) as exc:
            raise TextModelError("文本模型未返回有效 JSON，请重试或更换文本模型") from exc
        if not finished or not received:
            raise TextModelError("文本模型流式输出中断，请重试；原草稿已保留")

    @staticmethod
    def parse_content(text: str) -> dict:
        try:
            text = text.strip()
            fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if fence:
                text = fence[1].strip()
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except (ValueError, TypeError, RecursionError) as exc:
            raise TextModelError("文本模型未返回有效 JSON，请重试或更换文本模型") from exc

    async def complete(self, system: str, user: str) -> dict:
        if not self.configured:
            raise TextModelError("请在 .env 中配置有效的 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL，并重启服务", 503)
        timeout = self.settings.llm_timeout_seconds
        timeout = max(1, min(600, timeout)) if math.isfinite(timeout) else 120
        if self.http is None:
            self.http = httpx.AsyncClient(follow_redirects=False)
        try:
            async with asyncio.timeout(timeout):
                async with self.http.stream(
                    "POST", self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json={"model": self.settings.llm_model, "messages": [
                        {"role": "system", "content": system}, {"role": "user", "content": user}]},
                    timeout=timeout,
                ) as response:
                    if response.status_code in {401, 403}:
                        raise TextModelError("文本模型认证失败，请检查 LLM_API_KEY 和模型访问权限")
                    if response.status_code == 429:
                        raise TextModelError("文本模型请求受限，请稍后再试", 429)
                    if not 200 <= response.status_code < 300:
                        raise TextModelError("文本模型服务暂不可用，请检查服务地址和模型名")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 3 * 1024 * 1024:
                            raise TextModelError("文本模型返回内容过长，请减少分镜数量或缩短剧本")
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise TextModelError("文本模型请求超时，请稍后重试或减少生成内容", 504) from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise TextModelError("无法连接文本模型服务，请检查服务地址和网络") from exc
        try:
            envelope = json.loads(content)
            choice = envelope["choices"][0]
            if choice.get("finish_reason") in {"length", "content_filter"}:
                raise TextModelError("文本模型输出未完成，请减少生成内容或调整输入后重试")
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty content")
            return self.parse_content(text)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError) as exc:
            raise TextModelError("文本模型未返回有效 JSON，请重试或更换文本模型") from exc
