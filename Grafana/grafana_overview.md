# Grafana: Обзор

> **Навигация:**
>
> - [Установка через Docker Compose](./Installation/docker_compose_setup.md)
> - [Установка через Helm](./Installation/grafana_helm_installation.md)
> - [Источники данных](./grafana_datasources.md)
> - [Дашборды](./dashboards/definitions_and_concepts.md)
> - [Алертинг](./grafana_alerting.md)
> - [Провиженинг](./grafana_provisioning.md)
> - [Аутентификация](./grafana_user_management_and_authentication.md)
> - [Высокая доступность](./high_availability.md)
> - [Grafana Alloy](./grafana_alloy_overview.md)

## Определения

**Grafana** — open-source платформа для аналитики и интерактивной визуализации данных из различных источников (Prometheus, Loki, PostgreSQL и др.). Ключевой принцип: Grafana **не хранит данные**, а только запрашивает и визуализирует их из подключенных систем-хранилищ.

**Текущая версия (февраль 2026):** Grafana 12.x (стабильная 11.6.x — LTS)

### Grafana Stack

**Grafana Stack** (ранее LGTM: Loki, Grafana, Tempo, Mimir) — набор инструментов для реализации концепции [наблюдаемости (observability)](../Concepts/Observability_and_Monitoring/observability_overview.md). Grafana — центральный компонент, предоставляющий единый интерфейс для анализа:

- **Метрики** (Mimir/Prometheus)
- **Логи** (Loki)
- **Трассировки** (Tempo)

## Базовые концепции

### Архитектура, история и лицензирование

- **Технологии:** Бэкенд — **Go**, фронтенд — **TypeScript/React**.
- **История:** Запущен в 2014 году как форк Kibana 3, стал стандартом для визуализации в мониторинге.
- **Лицензия:** Основные компоненты (Grafana, Mimir, Loki, Tempo) — **AGPLv3** (copyleft).

### Основные возможности

| Возможность | Описание | Файл |
| :--- | :--- | :--- |
| **Визуализация** | Интерактивные дашборды, графики, таблицы | [Дашборды](./dashboards/definitions_and_concepts.md) |
| **Источники данных** | Prometheus, Loki, PostgreSQL, MySQL и др. | [Источники данных](./grafana_datasources.md) |
| **Алертинг** | Unified Alerting с уведомлениями | [Алертинг](./grafana_alerting.md) |
| **Провиженинг** | Управление конфигурацией как код | [Провиженинг](./grafana_provisioning.md) |
| **Плагины** | Расширение функциональности | [Плагины](./grafana_plugins.md) |
| **Аутентификация** | OAuth, LDAP, сервисные аккаунты | [Аутентификация](./grafana_user_management_and_authentication.md) |
| **Высокая доступность** | HA-кластеры с балансировкой | [HA](./high_availability.md) |
| **Сбор данных** | Grafana Alloy (унифицированный агент) | [Alloy](./grafana_alloy_overview.md) |

## Практические сценарии

### Интеграция с Prometheus

Prometheus имеет собственный UI для отладки, но Grafana используется для полноценных дашбордов.

- **Совместимость:** Встроенный плагин для Prometheus, полная поддержка PromQL.
- **Готовые дашборды:** Тысячи дашбордов в [библиотеке Grafana](https://grafana.com/grafana/dashboards/) (например, Node Exporter Full — ID 1860).
- **Kubernetes:** Для развёртывания полного стека см. [kube-prometheus-stack](../Prometheus/Kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios.md).

### Отладка с использованием Grafana Stack

1. **Метрики:** Всплеск HTTP 5xx на дашборде (Mimir/Prometheus).
2. **Логи:** Переход к логам за тот же период (Loki) по меткам сервиса.
3. **Трассировка:** Клик по `TraceID` в логах открывает трассировку (Tempo).
4. **Анализ:** Полный путь запроса через микросервисы для поиска узкого места.

**Настройка:** Через **Derived Fields** в конфигурации Loki (извлечение `TraceID` регулярным выражением, внутренняя ссылка на Tempo).

## Дополнительная информация

### Компоненты экосистемы Grafana Labs

| Компонент | Область | Описание | Ссылка |
| :--- | :--- | :--- | :--- |
| **Grafana** | **Визуализация** | Единый интерфейс для метрик, логов, трассировок | [Обзор](./grafana_overview.md) |
| **Mimir** | **Метрики** | Масштабируемое хранилище для метрик Prometheus | [Mimir](../Mimir/mimir_overview.md) |
| **Loki** | **Логи** | Агрегация логов, оптимизированная по стоимости | [Loki](../Loki/loki_overview.md) |
| **Tempo** | **Трассировки** | Хранилище распределённых трассировок | [Tempo](../Tempo/tempo_overview.md) |
| **Alloy** | **Сбор данных** | Унифицированный агент (метрики, логи, трейсы) | [Alloy](./grafana_alloy_overview.md) |
| **Prometheus** | **Метрики** | Система мониторинга и оповещения | [Prometheus](../Prometheus/overview.md) |
| **OpenTelemetry** | **Телеметрия** | Стандарт сбора и экспорта телеметрии | [OTel](../OpenTelemetry/opentelemetry_overview.md) |
| **k6** | **Нагрузочное тестирование** | Тестирование на JavaScript | — |
| **Faro** | **Real User Monitoring** | Телеметрия фронтенда | — |
| **OnCall** | **Управление инцидентами** | Дежурства и эскалации | ⚠️ Self-hosted не обновляется с весны 2026 |

### Ссылки

- [Официальная документация](https://grafana.com/docs/grafana/latest/)
- [Библиотека дашбордов](https://grafana.com/grafana/dashboards/)
- [Плагины](https://grafana.com/grafana/plugins/)
- [Миграция Helm-репозитория (30.01.2026)](https://iits-consulting.de/blog/grafana-helm-charts-moved-what-do)
