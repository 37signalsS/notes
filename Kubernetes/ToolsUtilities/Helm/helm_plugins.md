# Плагины Helm

Расширение функциональности Helm CLI через сторонние скрипты и исполняемые файлы.

---

## Definitions

| Термин | Описание |
|--------|----------|
| **Plugin (Плагин)** | Скрипт или исполняемый файл, расширяющий `helm` CLI. Устанавливается через `helm plugin install`. См. [Обзор Helm](./helm_overview.md) для общих концепций |

---

## Basic Concepts

### Управление плагинами

| Команда | Описание |
|---------|----------|
| `helm plugin install <path\|url>` | Установка из локальной директории или URL |
| `helm plugin list` | Просмотр установленных плагинов |
| `helm plugin update <name>` | Обновление плагина |
| `helm plugin uninstall <name>` | Удаление плагина |

---

## Practical Scenarios

### helm-diff: Предпросмотр изменений

Показывает diff между текущим состоянием релиза и тем, что будет применено после `helm upgrade`.

```bash
# Diff для обновления
helm diff upgrade my-release ./my-chart -f values.yaml

# Diff для отката
helm diff rollback my-release 1

# Сравнение двух ревизий
helm diff revision my-release 1 2
```

Рекомендуется использовать перед каждым `helm upgrade` для безопасного развёртывания.

### helm-monitor: Мониторинг и автоматический откат

Отслеживает состояние релиза через Prometheus/Elasticsearch. При обнаружении проблем (рост 5xx) выполняет автоматический rollback.

```bash
helm monitor prometheus \
  --prometheus=http://prometheus:9090 \
  my-release \
  'rate(http_requests_total{code=~"^5.*$"}[5m]) > 0'
```

---

## Additional Information

См. [Helm Commands and Workflow](./helm_commands_and_workflow.md) для использования плагинов в рабочем процессе.

> **helm 2to3 (deprecated):** Плагин для миграции Helm v2 → v3. Helm v2 достиг EOL в ноябре 2020 года. Плагин не поддерживается, актуален только для унаследованных систем.
