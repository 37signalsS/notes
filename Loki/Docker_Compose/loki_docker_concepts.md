# Настройка Loki с помощью Docker Compose — Основные концепции

## 1. Определения

**[Loki](loki_overview.md)** — система агрегации логов, разработанная Grafana Labs. Индексирует только метаданные (метки), а не полный текст логов, что делает ее экономичной и быстрой для большинства задач мониторинга.

## 2. Основные концепции

Для полноценного сбора логов в Docker с использованием Loki требуется три компонента:

| Компонент | Назначение | Образ / Примечание |
| :--- | :--- | :--- |
| **Loki** | Сервер для приема, хранения и индексации логов | `grafana/loki` |
| **Promtail** | Агент для сбора логов с хоста и контейнеров | `grafana/promtail` ⚠️ Deprecated |
| **Grafana** | Визуализация и запросы (LogQL) | `grafana/grafana` |
| **Alloy** | Универсальный агент (альтернатива Promtail) | `grafana/alloy` ✅ Рекомендовано |

> **Важно:** Без агента-сборщика (Promtail/Alloy) логи не будут попадать в Loki. Данная заметка описывает настройку сервисов `loki`, `promtail` и `grafana`. Для настройки Alloy см. [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

## Связанные документы

- **[Настройка Docker Compose](./loki_docker_compose_setup.md)** — конфигурация, запуск, проверка
- **[Дополнительные темы](./loki_docker_advanced.md)** — Alloy, troubleshooting, хранение
- **[loki_overview.md](../loki_overview.md)** — базовые концепции и архитектура Loki
- **[loki_stack_setup_guide.md](./loki_stack_setup_guide.md)** — развертывание в Kubernetes
- **[Grafana Alloy](../../Grafana/grafana_alloy_overview.md)** — рекомендуемый агент для новых развертываний
