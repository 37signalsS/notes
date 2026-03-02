# Установка стека мониторинга в Docker с Docker Compose

Это руководство описывает практический сценарий развертывания полноценного стека мониторинга с использованием [Docker](../../../Docker/docker_overview.md) и [Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md).

Весь процесс декомпозирован на следующие шаги:

1.  [Конфигурация Docker Compose](./docker-compose_config.md)
2.  [Конфигурация Prometheus](./prometheus_config.md)
3.  [Конфигурация Alertmanager](./alertmanager_config.md)
4.  [Запуск и проверка](./deployment_and_verification.md)
5.  [Мониторинг удаленных хостов](./remote_hosts_monitoring.md)

---

### 1. Определения

* **Prometheus**: Основной компонент для сбора, хранения и обработки метрик в виде временных рядов.
* **Grafana**: Платформа для визуализации и анализа метрик, позволяющая создавать интерактивные дашборды.
* **Alertmanager**: Компонент для обработки оповещений, отвечающий за их дедупликацию, группировку и маршрутизацию.
* **cAdvisor**: Инструмент для сбора, агрегации и экспорта метрик о производительности и ресурсах работающих контейнеров.
* **Node Exporter**: Экспортер для сбора метрик с хост-машины (ОС и аппаратное обеспечение).

---

### 2. Основные концепции

#### Принцип развертывания с Docker Compose

[Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md) используется для определения и запуска многоконтейнерных Docker-приложений. Это позволяет легко оркестрировать весь стек мониторинга как единое целое, управлять его жизненным циклом и конфигурацией.

#### Структура проекта

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

#### Использование DNS в Docker Compose

В сети, созданной Docker Compose, сервисы могут обращаться друг к другу по своим именам, указанным в файле `docker-compose.yml` (например, `prometheus`, `alertmanager`, `node-exporter`). Docker автоматически обеспечивает разрешение этих имен в IP-адреса контейнеров.

#### Персистентность данных

Для сохранения данных Prometheus (метрики) и Grafana (дашборды, источники данных, пользователи) при перезапуске или удалении контейнеров используются именованные [Docker-тома (volumes)](../../../Docker/Docker_fs/docker_volumes.md): `prometheus_data` и `grafana_data`.

---

### 3. Дополнительная информация

* **Docker**: Обзор и основные концепции [../../../Docker/docker_overview.md](../../../Docker/docker_overview.md).
* **Docker Compose**: Подробное описание и примеры использования [../../../Docker/Docker_compose/docker_compose_file_example.md](../../../Docker/Docker_compose/docker_compose_file_example.md).
* **Prometheus**: Общий обзор архитектуры и принципов работы [../../overview.md](../../overview.md).
* **Grafana**: Обзор платформы и ее возможностей [../../../Grafana/grafana_overview.md](../../../Grafana/grafana_overview.md).
* **Alertmanager**: Детальное описание и настройка [../../alertmanager.md](../../alertmanager.md).
* **Node Exporter**: Подробности об экспортере для ОС [../../Exporters/overview.md](../../Exporters/overview.md).
* **cAdvisor**: Документация (внешняя ссылка) [Google cAdvisor](https://github.com/google/cadvisor).
* **Конфигурация Prometheus**: Детальное описание директив `prometheus.yml` [../../configuration.md](../../configuration.md).
* **PromQL**: Язык запросов Prometheus [../../concepts/promql.md](../../concepts/promql.md).
* **Правила Prometheus**: Правила записи и оповещений [../../rules.md](../../rules.md).
* **Источники данных Grafana**: Настройка источников данных [../../../Grafana/grafana_datasources.md](../../../Grafana/grafana_datasources.md).
* **Дашборды Grafana**: Создание и импорт дашбордов [../../../Grafana/grafana_dashboards.md](../../../Grafana/grafana_dashboards.md).
* **Service Discovery в Prometheus**: Автоматическое обнаружение целей [../../service_discovery_and_relabeling.md](../../service_discovery_and_relabeling.md).
