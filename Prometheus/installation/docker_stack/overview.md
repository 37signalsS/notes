# Установка стека мониторинга в Docker с Docker Compose

Это руководство описывает практический сценарий развертывания полноценного стека мониторинга с использованием [Docker](../../../Docker/docker_overview.md) и [Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md).

> **См. также:** [Установка в Docker](../with_docker.md), [Docker metrics](../../../Docker/Docker_metrics/docker_prometheus_integration.md).

Весь процесс декомпозирован на следующие шаги:

1. [Конфигурация Docker Compose](./docker-compose_config.md)
2. [Конфигурация Prometheus](./prometheus_config.md)
3. [Конфигурация Alertmanager](./alertmanager_config.md)
4. [Запуск и проверка](./deployment_and_verification.md)
5. [Мониторинг удаленных хостов](./remote_hosts_monitoring.md)

## Определения

* **Prometheus**: Основной компонент для сбора, хранения и обработки метрик в виде временных рядов.
* **Grafana**: Платформа для визуализации и анализа метрик, позволяющая создавать интерактивные дашборды.
* **Alertmanager**: Компонент для обработки оповещений, отвечающий за их дедупликацию, группировку и маршрутизацию.
* **cAdvisor**: Инструмент для сбора, агрегации и экспорта метрик о производительности и ресурсах работающих контейнеров.
* **Node Exporter**: Экспортер для сбора метрик с хост-машины (ОС и аппаратное обеспечение).

## Основные концепции

### Принцип развертывания с Docker Compose

[Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md) используется для определения и запуска многоконтейнерных Docker-приложений. Это позволяет легко оркестрировать весь стек мониторинга как единое целое, управлять его жизненным циклом и конфигурацией.

### Структура проекта

Для удобства управления конфигурационные файлы каждого компонента размещаются в отдельных поддиректориях:

```
monitoring/
├── docker-compose.yml
├── prometheus/
│   ├── prometheus.yml
│   └── rules.yml
└── alertmanager/
    └── config.yml
```

### Использование DNS в Docker Compose

В сети, созданной Docker Compose, сервисы могут обращаться друг к другу по своим именам, указанным в файле `docker-compose.yml` (например, `prometheus`, `alertmanager`, `node-exporter`). Docker автоматически обеспечивает разрешение этих имен в IP-адреса контейнеров.

### Персистентность данных

Для сохранения данных Prometheus (метрики) и Grafana (дашборды, источники данных, пользователи) при перезапуске или удалении контейнеров используются именованные [Docker-тома (volumes)](../../../Docker/Docker_fs/docker_volumes.md): `prometheus_data` и `grafana_data`.

## Практические сценарии

### Быстрый старт

```bash
# Клонирование или создание структуры
mkdir -p monitoring/{prometheus,alertmanager,grafana}
cd monitoring

# Запуск всего стека
docker-compose up -d

# Проверка
docker-compose ps
curl http://localhost:9090/graph  # Prometheus
curl http://localhost:3000       # Grafana
```

### Остановка и удаление

```bash
# Остановка
docker-compose down

# Остановка с удалением томов
docker-compose down -v
```

## Дополнительная информация

### Актуальные версии образов

| Компонент | Образ | Версия |
|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.10.0 |
| **Grafana** | `grafana/grafana` | latest |
| **Alertmanager** | `prom/alertmanager` | v0.31.0 |
| **Node Exporter** | `prom/node-exporter` | v1.10.2 |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.56.2 |

> **Важно:** Проверяйте [Docker Hub](https://hub.docker.com/u/prom) для получения последних версий.

### Связанные темы

* [Установка в Docker](../with_docker.md) — базовая конфигурация
* [Prometheus Server](../prometheus_server_installation.md) — установка на хост
* [Docker metrics](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — мониторинг контейнеров
* [Grafana](../../../Grafana/grafana_overview.md) — визуализация
* [Alertmanager](../../alertmanager.md) — обработка оповещений
* [PromQL](../../concepts/promql.md) — язык запросов
* [Configuration](../../configuration.md) — настройка Prometheus
