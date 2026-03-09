#!/usr/bin/env python3
"""SearXNG search client for Qwen Code"""
import requests
import json
import sys

BASE_URL = "http://localhost:8080"

def search(query: str, categories: list = None, engines: list = None, num_results: int = 5) -> str:
    """
    Поиск через SearXNG.
    
    Args:
        query: Поисковый запрос
        categories: Категории (general, images, videos, news, it)
        engines: Движки (google, bing, duckduckgo, wikipedia, github)
        num_results: Максимум результатов
    
    Returns:
        Форматированные результаты поиска
    """
    params = {"q": query, "format": "json"}
    if categories:
        params["categories"] = ",".join(categories)
    if engines:
        params["engines"] = ",".join(engines)
    
    try:
        resp = requests.get(f"{BASE_URL}/search", params=params, timeout=10)
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

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python search.py <запрос> [категории]")
        print("Пример: python search.py 'Python async' general,it")
        sys.exit(1)
    
    query = sys.argv[1]
    categories = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    print(search(query, categories))
