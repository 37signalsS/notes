# Обзор Docker Stack — установка стека мониторинга

## Определения

**Стек мониторинга (Monitoring Stack)** — это логическая группа взаимосвязанных сервисов (Prometheus, Grafana, Alertmanager и экспортеры), работающих совместно для обеспечения полной наблюдаемости системы.

**Docker Compose** — основной инструмент оркестрации для развёртывания стека мониторинга на одном хосте. Позволяет декларативно описать всю инфраструктуру в одном YAML-файле.

**Docker Stack (в контексте мониторинга)** — часто используемый термин для обозначения набора сервисов мониторинга. Важно отличать его от *Docker Swarm Stack*, который используется для оркестрации в кластере. Данное руководство сфокусировано на **Docker Compose**.

> **См. также:** [Конфигурация Docker Compose](./docker-compose_config.md) — полный YAML-файл, описания сервисов, healthchecks, security.

## Основные концепции

### Компоненты стека

| Компонент | Роль в стеке | Конфигурация |
|---|---|---|
| **Prometheus** | Сбор и хранение метрик (TSDB), вычисление правил алертинга | [prometheus_config.md](./prometheus_config.md) |
| **Grafana** | Визуализация, дашборды, единый UI для всех источников данных | [Grafana docker_compose_setup](../../../Grafana/Installation/docker_compose_setup.md) |
| **Alertmanager** | Дедупликация, группировка, маршрутизация оповещений | [docker_compose_alertmanager_config.md](./docker_compose_alertmanager_config.md) |
| **Node Exporter** | Экспорт метрик хоста: CPU, память, диск, сеть | Встроен в [docker-compose_config.md](./docker-compose_config.md) |
| **cAdvisor** | Экспорт детальных метрик Docker-контейнеров (ресурсы, I/O) | [cAdvisor SSoT](../../Exporters/cadvisor.md) |
| **Grafana Alloy** | (Опционально) Современный универсальный агент, заменяющий экспортеры | [Grafana Alloy overview](../../../Grafana/Installation/docker_compose_setup.md) |

### Хранение данных и персистентность

Для обеспечения сохранности данных при перезапуске контейнеров используются **Docker Volumes**:
*   **Named Volumes (Именованные тома):** Рекомендуются для баз данных (Prometheus TSDB, Grafana DB). Управляются Docker, обеспечивают высокую производительность.
*   **Bind Mounts (Привязки директорий):** Используются для конфигурационных файлов (`prometheus.yml`, `config.yml`). Позволяют легко редактировать конфиги на хосте без входа в контейнер.

### Сетевое взаимодействие (DNS)

Внутри Docker Compose создаётся изолированная сеть (обычно `bridge`). 
*   **Service Discovery:** Сервисы обращаются друг к другу по именам, указанным в `compose.yml` (например, `http://prometheus:9090`).
*   **Изоляция:** Стек защищён от внешнего мира; наружу пробрасываются только необходимые порты (Grafana — 3000, Prometheus — 9090).

### Структура проекта

```text
monitoring/
├── compose.yml           # Основной файл конфигурации
├── .env                  # Переменные окружения и секреты
├── prometheus/
│   ├── prometheus.yml    # Основной конфиг Prometheus
│   └── rules.yml         # Правила алертинга
├── alertmanager/
│   └── config.yml        # Настройки уведомлений
└── grafana/              # Настройки визуализации (provisioning)
    └── provisioning/
        ├── datasources/
        └── dashboards/
```

### Пошаговая настройка

Процесс разбит на независимые шаги:

| Шаг | Файл | Содержание |
|---|---|---|
| **1** | [docker-compose_config.md](./docker-compose_config.md) | YAML-файл стека: сервисы, тома, сети, лимиты ресурсов |
| **2** | [prometheus_config.md](./prometheus_config.md) | `prometheus.yml`: scrape-цели, rule_files, alerting-секция |
| **3** | [docker_compose_alertmanager_config.md](./docker_compose_alertmanager_config.md) | `config.yml` Alertmanager: маршруты, получатели (Slack, Email) |
| **4** | — | Запуск и проверка: `docker compose up -d`, health-эндопоинты |
| **5** | [remote_hosts_monitoring.md](./remote_hosts_monitoring.md) | Мониторинг внешних серверов через Node Exporter |

### Сравнение с альтернативами

| Подход | Когда использовать | Плюсы | Минусы |
|---|---|---|---|
| **Docker Compose** | Локальная среда, demo, small-scale production | Простота, скорость развёртывания | Нет встроенного HA |
| **Kubernetes (Helm)** | Enterprise, масштабируемые системы | HA, Auto-scaling, GitOps | Высокая сложность управления |
| **Grafana Alloy Stack** | Современный стандарт (2026+) | Единый агент для метрик, логов и трейсов | Требует изучения Alloy конфигурации |

## Практические сценарии

### Быстрый старт

```bash
# Создание структуры каталогов
mkdir -p monitoring/{prometheus,alertmanager,grafana}
cd monitoring

# Запуск стека
docker compose up -d

# Проверка статусов и логов
docker compose ps
docker compose logs -f prometheus
```

### Безопасность и лимиты

1.  **Секреты:** Используйте `.env` файл для хранения паролей Grafana и токенов Alertmanager. Никогда не коммитьте `.env` в Git.
2.  **Лимиты ресурсов:** Обязательно ограничивайте CPU и RAM для Prometheus, чтобы он не "задушил" хост при всплеске нагрузки.
    ```yaml
    deploy:
      resources:
        limits:
          memory: 2048M
    ```
3.  **User ID:** Запускайте контейнеры от не-root пользователя (UID 472 для Grafana), если используете bind mounts для данных.

### Проверка компонентов

| Компонент | URL | Метод проверки |
|---|---|---|
| **Prometheus** | `http://localhost:9090` | Проверьте **Status → Targets**. Все цели должны быть `UP`. |
| **Grafana** | `http://localhost:3000` | Вход `admin`/`admin`. Проверьте подключение [Data Source](../../../Grafana/grafana_datasources.md). |
| **Alertmanager** | `http://localhost:9093` | Проверьте наличие конфигурации во вкладке **Status**. |

### Обслуживание и отладка

*   **Перезагрузка конфигурации:** Вместо перезапуска контейнера используйте hot reload:
    `curl -X POST http://localhost:9090/-/reload`
*   **Проверка синтаксиса:**
    `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml`
*   **Очистка данных:** Для полного удаления томов при остановке используйте `docker compose down -v`.

### Расширение стека

| Компонент | Назначение | Ссылка |
|---|---|---|
| **Loki** | Агрегация и поиск логов | [Loki Docker Compose](../../../Loki/Docker_Compose/loki_docker_compose_setup.md) |
| **Tempo** | Трассировка запросов (Tracing) | [Tempo overview](../../../Tempo/index.md) |
| **Blackbox Exporter** | Проверка доступности (HTTP, ICMP, TCP) | [Blackbox Exporter](../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md) |

## Дополнительная информация

### Актуальные версии образов (Август 2026)

| Компонент | Образ | Версия |
|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.13.1 |
| **Grafana** | `grafana/grafana` | v13.1.1 |
| **Alertmanager** | `prom/alertmanager` | v0.33.1 |
| **Node Exporter** | `prom/node-exporter` | v1.12.1 |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.60.5 |

### Связанные темы

* [Конфигурация Docker Compose](./docker-compose_config.md) — детализация YAML, healthchecks, security.
* [Конфигурация Prometheus](./prometheus_config.md) — scrape-цели, правила и алертинг.
* [Конфигурация Alertmanager](./docker_compose_alertmanager_config.md) — шаблоны и маршруты.
* [Мониторинг Docker-контейнеров](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с демоном Docker.
* [Prometheus overview](../../overview.md) — архитектура и внутреннее устройство.
* [Grafana overview](../../../Grafana/grafana_overview.md) — возможности визуализации.
