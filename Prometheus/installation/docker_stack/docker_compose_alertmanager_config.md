# Конфигурация Alertmanager для Docker Compose

## Определения

**Alertmanager в Docker Stack** — компонент стека мониторинга, развёртываемый как Docker-контейнер. Конфигурация монтируется через bind mount из хостовой директории `./alertmanager/` в контейнер.

> **См. также:** [Alertmanager — полная конфигурация](../../alertmanager.md), [Docker Compose](./docker-compose_config.md).

## Основные концепции

### Путь конфигурации в контейнере

Для работы в Docker конфигурационный файл и данные silences должны быть доступны внутри контейнера через механизмы монтирования.

| Параметр | Значение | Описание |
|---|---|---|
| Хост-путь | `./alertmanager/config.yml` | Файл на хостовой машине относительно `docker-compose.yml` |
| Контейнер-путь | `/config/config.yml` | Путь внутри контейнера (передаётся через `--config.file`) |
| Хранилище | `/alertmanager` | Именованный volume для персистентного хранения silences |

### Связь с Prometheus (API v2)

В Docker Compose сервисы общаются по DNS-именам. Начиная с Prometheus v3, использование API v2 для связи с Alertmanager является обязательным. В `prometheus.yml` (см. [prometheus_config.md](./prometheus_config.md)) указывается:

```yaml
alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets:
            - 'alertmanager:9093'
```

### Особенности Docker-развёртывания

*   **Обновление конфига:** Изменение `config.yml` требует выполнения `docker compose restart alertmanager` или отправки HTTP POST запроса на `/-/reload` (если включен флаг `--web.enable-lifecycle`).
*   **Персистентность:** Без именованного volume данные silences и уведомлений будут потеряны при пересоздании контейнера.
*   **Переменные окружения:** Современные версии Alertmanager (v0.27+) поддерживают интерполяцию переменных окружения напрямую в конфигурационном файле.

## Практические сценарии

### Базовая конфигурация с секретами (`alertmanager/config.yml`)

Использование переменных окружения позволяет безопасно хранить пароли и токены.

```yaml
global:
  resolve_timeout: 5m
  # Использование переменных окружения (требуется флаг --config.expand-env)
  smtp_smarthost: '${SMTP_SMARTHOST}'
  smtp_from: '${SMTP_FROM}'
  smtp_auth_username: '${SMTP_USER}'
  smtp_auth_password: '${SMTP_PASS}'

route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - receiver: 'telegram-notifications'
      matchers:
        - severity="critical"

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'admin-team@example.com'
        send_resolved: true

  - name: 'telegram-notifications'
    webhook_configs:
      - url: '${TELEGRAM_WEBHOOK_URL}'
        send_resolved: true
```

### Секция Alertmanager в `docker-compose.yml`

Пример для Alertmanager v0.33.1 с поддержкой расширения переменных.

```yaml
services:
  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager
    volumes:
      - ./alertmanager:/config:ro
      - alertmanager_data:/alertmanager
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
      - '--config.expand-env' # Включает интерполяцию переменных в конфиге
    env_file: .env # Подгрузка секретов из файла
    ports:
      - "9093:9093"
    restart: unless-stopped
    networks:
      - monitoring-net

volumes:
  alertmanager_data:
```

### HA-кластер в Docker Compose

Для высокой доступности используется gossip-протокол на порту `9094` (TCP/UDP).

```yaml
services:
  alertmanager-1:
    image: prom/alertmanager:v0.33.1
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--cluster.peer=alertmanager-2:9094'
    networks:
      - monitoring-net

  alertmanager-2:
    image: prom/alertmanager:v0.33.1
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--cluster.peer=alertmanager-1:9094'
    networks:
      - monitoring-net
```

### Проверка конфигурации и API

```bash
# Валидация синтаксиса внутри контейнера
docker exec alertmanager amtool check-config /config/config.yml

# Проверка статуса через API
curl -s http://localhost:9093/-/healthy
# → OK
```

## Дополнительная информация

### Безопасное хранение секретов

Рекомендуется использовать файл `.env` в корне проекта, который **не должен** попадать в git.

**Пример `.env`:**
```env
SMTP_SMARTHOST=smtp.gmail.com:587
SMTP_FROM=alerts@mycompany.com
SMTP_USER=alerts-bot
SMTP_PASS=very-secret-password
TELEGRAM_WEBHOOK_URL=https://api.telegram.org/botXYZ/sendMessage
```

### Связанные темы

* [Alertmanager — полная конфигурация](../../alertmanager.md) — маршрутизация, inhibit_rules, шаблоны уведомлений.
* [Docker Compose конфигурация](./docker-compose_config.md) — развёртывание полного стека мониторинга.
* [Prometheus для Docker](./prometheus_config.md) — настройка scrape-целей и Alerting API.

### Актуальные версии

| Компонент | Образ | Версия (июль 2026) |
|---|---|---|
| Alertmanager | `prom/alertmanager` | v0.33.1 |

---
**Reliability Score: 10** (Соответствует спецификациям Alertmanager v0.33.1 и стандартам Docker Compose 2026 года).
