# Конфигурация Alertmanager для Docker Compose

## Definitions

**Alertmanager в Docker Stack** — компонент стека мониторинга, развёртываемый как Docker-контейнер. Конфигурация монтируется через bind mount из хостовой директории `./alertmanager/` в контейнер.

> **См. также:** [Alertmanager — полная конфигурация](../../alertmanager.md) (SSoT), [Docker Compose](./docker-compose_config.md).

## Basic Concepts

### Путь конфигурации в контейнере

| Параметр | Значение | Описание |
|---|---|---|
| Хост-путь | `./alertmanager/config.yml` | Файл на хостовой машине |
| Контейнер-путь | `/config/config.yml` | Путь внутри контейнера (передаётся через `--config.file`) |
| Хранилище | `/alertmanager` | Именованный volume или bind mount для silences и данных кластера |

### Связь с Prometheus

В Docker Compose сервисы общаются по DNS-именам. В `prometheus.yml` указывается:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093'
```

Имя `alertmanager` соответствует сервису в [`docker-compose.yml`](./docker-compose_config.md).

### Особенности Docker-развёртывания

| Аспект | Описание |
|---|---|
| **Обновление конфига** | Изменение `config.yml` → `docker compose restart alertmanager` или `docker restart alertmanager` |
| **Персистентность** | Без volume данные silences теряются при пересоздании контейнера |
| **HA-кластер** | Требует `--cluster.peer` с IP пиеров; в Docker Compose — имена сервисов |
| **Секреты** | SMTP-пароли, webhook-токены — хранить через Docker secrets или env-файлы |

## Practical Scenarios

### Базовая конфигурация (`monitoring/alertmanager/config.yml`)

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alertmanager@example.com'
  smtp_auth_username: 'your-username'
  smtp_auth_password: 'your-password'

route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - receiver: 'telegram-notifications'
      match:
        severity: 'critical'

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'admin-team@example.com'
        send_resolved: true

  - name: 'telegram-notifications'
    webhook_configs:
      - url: 'http://your-telegram-bot-webhook-url/...'
        send_resolved: true
```

> **Структура конфига:** `global` → `route` → `receivers` — описана в [Alertmanager SSoT](../../alertmanager.md#конфигурация-alertmanageryml).

### Docker Compose-секция Alertmanager

Из [`docker-compose.yml`](./docker-compose_config.md):

```yaml
alertmanager:
  image: prom/alertmanager:v0.31.0
  container_name: alertmanager
  volumes:
    - ./alertmanager:/config
  command:
    - '--config.file=/config/config.yml'
    - '--storage.path=/alertmanager'
  ports:
    - "9093:9093"
  restart: unless-stopped
  networks:
    - monitoring-net
```

| Параметр | Описание |
|---|---|
| `./alertmanager:/config` | Bind mount хостовой директории в контейнер |
| `--config.file=/config/config.yml` | Путь к конфигурации внутри контейнера |
| `--storage.path=/alertmanager` | Путь хранения silences (персистентный volume) |
| `9093:9093` | Проброс порта UI/API |

### Перезагрузка после изменения конфига

```bash
# Вариант 1: restart контейнера
docker compose restart alertmanager

# Вариант 2: пересоздание (если изменён docker-compose.yml)
docker compose up -d alertmanager

# Проверка логов
docker compose logs -f alertmanager
```

### Проверка конфигурации

```bash
# Через amtool внутри контейнера
docker exec alertmanager amtool check-config /config/config.yml

# Через curl — проверка доступности API
curl -s http://localhost:9093/-/healthy
# Ожидаемый ответ: OK
```

### HA-кластер в Docker Compose

Для высокой доступности запускаются 2+ инстанса с gossip-протоколом:

```yaml
alertmanager-1:
  image: prom/alertmanager:v0.31.0
  command:
    - '--config.file=/config/config.yml'
    - '--storage.path=/alertmanager'
    - '--cluster.listen-address=:9094'
    - '--cluster.peer=alertmanager-2:9094'
  ports:
    - "9093:9093"
    - "9094:9094"

alertmanager-2:
  image: prom/alertmanager:v0.31.0
  command:
    - '--config.file=/config/config.yml'
    - '--storage.path=/alertmanager'
    - '--cluster.listen-address=:9094'
    - '--cluster.peer=alertmanager-1:9094'
  ports:
    - "9095:9093"
    - "9096:9094"
```

> **Подробно:** [Alertmanager HA](../../alertmanager.md#высокая-доступность-ha).

### Безопасное хранение секретов

**Через env-файл** (`.env` в корне проекта):

```bash
# .env
SMTP_USERNAME=alerts@example.com
SMTP_PASSWORD=secret_password
TELEGRAM_WEBHOOK_TOKEN=bot123:abc
```

```yaml
# docker-compose.yml
alertmanager:
  image: prom/alertmanager:v0.31.0
  env_file: .env
  environment:
    - SMTP_USERNAME=${SMTP_USERNAME}
    - SMTP_PASSWORD=${SMTP_PASSWORD}
```

> **Примечание:** Alertmanager не поддерживает переменные окружения в конфиге напрямую. Для подстановки используйте init-контейнер или шаблоны (как в [Kubernetes-развёртывании](../../alertmanager.md#развёртывание-в-kubernetes-через-манифесты)).

## Additional Information

### Связанные темы

* [Alertmanager SSoT](../../alertmanager.md) — полная документация: маршрутизация, inhibit_rules, silencing
* [Docker Compose конфигурация](./docker-compose_config.md) — полный стек мониторинга
* [Prometheus для Docker](./prometheus_config.md) — настройка scrape-целей
* [Установка Alertmanager](../alertmanager_installation.md) — бинарная установка, systemd
* [Helm-чарт](../with_helm_chart.md) — развёртывание в Kubernetes

### Версии образов

| Компонент | Образ | Версия (актуальная) |
|---|---|---|
| Alertmanager | `prom/alertmanager` | v0.31.0 |

> Проверить последнюю версию: [Docker Hub](https://hub.docker.com/r/prom/alertmanager/tags).
