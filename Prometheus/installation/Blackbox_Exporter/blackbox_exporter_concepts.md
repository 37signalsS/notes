# Blackbox Exporter: Основные концепции

## 1. Определения

**Blackbox Exporter** — экспортер для проверки доступности эндпоинтов по различным протоколам:

| Протокол | Описание |
| :--- | :--- |
| **HTTP/HTTPS** | Проверка веб-сервисов |
| **TCP** | Проверка сетевых сервисов |
| **ICMP** | Проверка доступности хостов (ping) |
| **DNS** | Проверка DNS-серверов |
| **gRPC** | Проверка gRPC-сервисов (v0.28.0+) |
| **HTTP/3 (QUIC)** | Проверка HTTP/3 (v0.28.0+) |

> **См. также:** [Blackbox Exporter](../Exporters/blackbox_exporter.md).

## 2. Актуальная версия

| Параметр | Значение |
| :--- | :--- |
| **Последняя стабильная версия** | `0.28.0` |
| **Репозиторий** | [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) |

## 3. Новые возможности v0.28.0

- **HTTP/3 (QUIC) prober:** Проверка сервисов по протоколу HTTP/3
- **gRPC metadata:** Поддержка метаданных для gRPC проверок
- **Byte matching в TCP:** Проверка содержимого TCP-ответов
- **Автоматическая перезагрузка конфига:** При изменении конфигурации

## Связанные документы

- **[Установка и настройка](./blackbox_exporter_installation.md)** — установка, конфигурация, интеграция с Prometheus
- **[Дополнительные темы](./blackbox_exporter_advanced.md)** — безопасность, Docker, troubleshooting
- **[Blackbox Exporter](../Exporters/blackbox_exporter.md)** — полное руководство
- **[Prometheus Server](../prometheus_server_installation.md)** — интеграция
