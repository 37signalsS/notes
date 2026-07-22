# Обзор Docker Stack — установка стека мониторинга

## Определения

**Docker Stack мониторинга** — полноценный стек наблюдения (Prometheus + Grafana + Alertmanager + Node Exporter + cAdvisor), развёртываемый через Docker Compose на одном хосте. Предназначен для локального тестирования, demo-сред и небольших production-окружений.

> **См. также:** [Конфигурация Docker Compose](./docker-compose_config.md) — полный YAML-файл, описания сервисов, healthchecks, security.

## Основные концепции

### Компоненты стека

| Компонент | Роль в стеке | Конфигурация |
|---|---|---|
| **Prometheus** | Сбор и хранение метрик (TSDB), вычисление правил алертинга | [prometheus_config.md](./prometheus_config.md) |
| **Grafana** | Визуализация, дашборды, единый UI для всех источников данных | [Grafana docker_compose_setup](../../../Grafana/Installation/docker_compose_setup.md) |
| **Alertmanager** | Дедупликация, группировка, маршрутизация оповещений (Email, Slack, Webhook) | [docker_compose_alertmanager_config.md](./docker_compose_alertmanager_config.md) |
| **Node Exporter** | Экспорт метрик хоста: CPU, память, диск, сеть | Встроен в [docker-compose_config.md](./docker-compose_config.md) |
| **cAdvisor** | Экспорт метрик Docker-контейнеров: CPU, RAM, network, fs | Встроен в [docker-compose_config.md](./docker-compose_config.md) |

### Структура проекта

```
monitoring/
├── docker-compose.yml
├── prometheus/
│   ├── prometheus.yml
│   └── rules.yml
├── alertmanager/
│   └── config.yml
└── grafana/          (опционально, при использовании provisioning)
    └── provisioning/
        └── datasources/
            └── datasources.yaml
```

### Пошаговая настройка

Процесс разбит на независимые шаги:

| Шаг | Файл | Содержание |
|---|---|---|
| **1** | [docker-compose_config.md](./docker-compose_config.md) | YAML-файл стека: сервисы, volumes, networks, healthchecks, resource limits |
| **2** | [prometheus_config.md](./prometheus_config.md) | `prometheus.yml`: scrape-цели, rule_files, alerting-секция |
| **3** | [docker_compose_alertmanager_config.md](./docker_compose_alertmanager_config.md) | `config.yml` Alertmanager: route, receivers, inhibit_rules |
| **4** | — | Запуск и проверка: `docker compose up -d`, health endpoints, UI компонентов |
| **5** | [remote_hosts_monitoring.md](./remote_hosts_monitoring.md) | Node Exporter на удалённых хостах, firewall, static_configs |

### Сравнение с альтернативами

| Подход | Когда использовать | Плюсы | Минусы |
|---|---|---|---|
| **Docker Compose** (этот стек) | Локальная среда, demo, small-scale production | Простота, одна команда запуска | Нет HA, один хост |
| **Kubernetes + kube-prometheus-stack** | Production, кластеры K8s | HA, авто-масштабирование, ServiceDiscovery | Сложность, требуется K8s-кластер |
| **Helm-чарт alertmanager** | Только Alertmanager в K8s | Декларативность, GitOps | Требует Prometheus для отправки алертов |

> Подробности: [Kubernetes overview](../../kubernetes/overview.md), [Helm-чарт Alertmanager](../with_helm_chart.md).

## Практические сценарии

### Быстрый старт

```bash
# Создание структуры каталогов
mkdir -p monitoring/{prometheus,alertmanager,grafana}
cd monitoring

# Запуск стека
docker compose up -d

# Проверка статусов
docker compose ps

# Health endpoints
curl -s http://localhost:9090/-/healthy   # Prometheus
curl -s http://localhost:9093/-/healthy   # Alertmanager
curl -s http://localhost:3000/api/health   # Grafana
```

### Проверка компонентов

| Компонент | URL | Что проверить |
|---|---|---|
| **Prometheus** | `http://localhost:9090` | **Status → Targets**: все цели в статусе `UP` |
| **Grafana** | `http://localhost:3000` | Логин `admin`/`admin`, [Data Source](../../../Grafana/grafana_datasources.md) (`http://prometheus:9090`), дашборды `1860` (Node Exporter), `13981` (cAdvisor) |
| **Alertmanager** | `http://localhost:9093` | Разделы Alerts, Groups, Silences доступны |

### Остановка и удаление

```bash
# Остановка (данные сохраняются в volumes)
docker compose down

# Остановка с удалением данных
docker compose down -v
```

### Расширение стека

| Компонент | Назначение | Ссылка |
|---|---|---|
| **Loki** | Агрегация логов | [Loki Docker Compose](../../../Loki/Docker_Compose/loki_docker_compose_setup.md) |
| **Promtail** | Сбор и отправка логов в Loki | [Loki Docker Compose](../../../Loki/Docker_Compose/loki_docker_compose_setup.md) |
| **Tempo** | Распределённые трассировки | [Tempo overview](../../../Tempo/index.md) |

## Дополнительная информация

### Актуальные версии образов

| Компонент | Образ | Версия |
|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.13.1 |
| **Grafana** | `grafana/grafana` | v13.1.1 |
| **Alertmanager** | `prom/alertmanager` | v0.33.1 |
| **Node Exporter** | `prom/node-exporter` | v1.12.1 |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.60.5 |

> Проверить последние версии: [Docker Hub](https://hub.docker.com/u/prom).

### Связанные темы

* [Конфигурация Docker Compose](./docker-compose_config.md) — полный YAML, healthchecks, security, resource limits
* [Конфигурация Prometheus](./prometheus_config.md) — scrape-цели, rules, alerting
* [Конфигурация Alertmanager](./docker_compose_alertmanager_config.md) — маршрутизация алертов, HA в Compose
* [Установка Alertmanager (binary)](../alertmanager_installation.md) — systemd, бинарная установка
* [Установка Alertmanager (Helm)](../with_helm_chart.md) — Kubernetes
* [Мониторинг Docker-контейнеров](../../../Docker/Docker_metrics/docker_prometheus_integration.md)
* [Prometheus overview](../../overview.md) — общая архитектура Prometheus
* [Grafana overview](../../../Grafana/grafana_overview.md) — визуализация
