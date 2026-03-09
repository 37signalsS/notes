# Qwen Code MCP + SearXNG

## Проблема

Команда `/mcp list` показывала "Не настроено MCP-серверов", хотя файл `~/.qwen/mcp.json` существовал с конфигурацией SearXNG.

## Причина

Qwen Code **не читает** отдельный файл `mcp.json`. MCP-конфигурация должна находиться в `settings.json` в секции `mcpServers`.

## Решение

Добавить MCP-конфигурацию в `~/.qwen/settings.json`:

```json
{
  "mcpServers": {
    "searxng": {
      "command": "/home/q/searxng/venv/bin/python",
      "args": ["-u", "/home/q/searxng/mcp_server.py"],
      "env": {
        "SEARXNG_URL": "http://localhost:8080"
      }
    }
  }
}
```

## Проверка

```bash
/mcp list
```

Должен отобразиться сервер `searxng` с доступными инструментами:

- `searxng_search` — поиск в интернете
- `searxng_autocomplete` — автодополнение запросов

## Расположение конфигурации

| Тип | Путь | Область действия |
|-----|------|-----------------|
| Проект | `.qwen/settings.json` в проекте | Только текущий проект |
| Пользователь | `~/.qwen/settings.json` | Все сессии пользователя |
| Система | `/etc/qwen-code/settings.json` | Все пользователи |

## Требования

- SearXNG должен быть запущен на `http://localhost:8080`
- Пакет `mcp` установлен в venv: `/home/q/searxng/venv/bin/pip install mcp`
