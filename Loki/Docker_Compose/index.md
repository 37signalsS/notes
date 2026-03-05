# Настройка Loki с помощью Docker Compose

Индекс документов по настройке Loki в Docker Compose.

## Документы

| Документ | Описание |
| :--- | :--- |
| **[Основные концепции](./loki_docker_concepts.md)** | Определения, компоненты стека (Loki, Promtail, Grafana, Alloy) |
| **[Настройка Docker Compose](./loki_docker_compose_setup.md)** | Конфигурация сервисов, datasources, Promtail, запуск и проверка |
| **[Дополнительные темы](./loki_docker_advanced.md)** | Grafana Alloy, постоянное хранилище, troubleshooting |

## Связанные документы

- **[loki_overview.md](../loki_overview.md)** — базовые концепции и архитектура Loki
- **[loki_stack_setup_guide.md](../loki_stack_setup_guide.md)** — развертывание в Kubernetes
- **[fluentbit_integration.md](../fluentbit_integration.md)** — интеграция Fluent Bit вместо Promtail
- **[Loki Docker Driver](../../Docker/Docker_logs/loki_logging_driver_setup.md)** — отправка логов напрямую из Docker
- **[Grafana Alloy](../../Grafana/grafana_alloy_overview.md)** — рекомендуемый агент для новых развертываний
