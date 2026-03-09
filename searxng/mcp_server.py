#!/usr/bin/env python3
"""MCP Server for SearXNG integration with Qwen Code"""
import os
import json
import requests
from mcp.server.fastmcp import FastMCP

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080")
mcp = FastMCP("SearXNG Search")

@mcp.tool()
def searxng_search(query: str, categories: str = None, engines: str = None, num_results: int = 5) -> str:
    """
    Поиск в интернете через SearXNG.
    
    Args:
        query: Поисковый запрос
        categories: Категории через запятую (general, images, videos, news, it)
        engines: Поисковые движки через запятую (google, bing, duckduckgo, wikipedia, github)
        num_results: Максимальное количество результатов (по умолчанию 5)
    
    Returns:
        Форматированные результаты поиска
    """
    params = {"q": query, "format": "json"}
    if categories:
        params["categories"] = categories
    if engines:
        params["engines"] = engines
    
    try:
        resp = requests.get(f"{SEARXNG_URL}/search", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        return f"❌ Ошибка подключения к SearXNG: {e}"
    
    results = data.get("results", [])[:num_results]
    if not results:
        return "📭 Ничего не найдено"
    
    output = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        content = r.get("content", "")
        url = r.get("url", "")
        engine = r.get("engine", "unknown")
        
        output.append(f"{i}. 📌 {title}")
        if content:
            output.append(f"   {content}")
        output.append(f"   🔗 {url}")
        output.append(f"   [via: {engine}]")
    
    return "\n\n".join(output)

@mcp.tool()
def searxng_autocomplete(query: str) -> list:
    """
    Автодополнение поискового запроса.
    
    Args:
        query: Начало поискового запроса
    
    Returns:
        Список подсказок для автодополнения
    """
    try:
        resp = requests.get(f"{SEARXNG_URL}/autocomplete", params={"q": query}, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        return []

if __name__ == "__main__":
    mcp.run()
