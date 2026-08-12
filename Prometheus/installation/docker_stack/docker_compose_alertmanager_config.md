# Конфигурация Alertmanager для Docker Compose

## Определения

**Alertmanager в Docker Stack** — это специализированный компонент системы мониторинга, развёрнутый в виде изолированного контейнера, предназначенный для обработки алертов от Prometheus. Он отвечает за дедупликацию, группировку и доставку уведомлений в конечные каналы (Email, Telegram, Slack и др.).

**Персистентность (Persistence)** — механизм сохранения состояния Alertmanager (тишины/silences, данные о разосланных уведомлениях) при перезапуске или пересоздании контейнеров с использованием именованных Docker Volumes.

> **См. также:** [Alertmanager — полная конфигурация](../../alertmanager.md), [Docker Compose — настройка стека](./docker-compose_config.md).

## Основные концепции

### Структура монтирования (Volumes)

Для корректной работы Alertmanager в Docker необходимо обеспечить доступ к конфигурации, шаблонам и хранилищу данных.

| Ресурс | Хост-путь | Контейнер-путь | Режим | Описание |
|---|---|---|---|---|
| Конфигурация | `./alertmanager/config.yml` | `/etc/alertmanager/config.yml` | `ro` | Основной файл настроек |
| Шаблоны | `./alertmanager/templates/` | `/etc/alertmanager/templates/` | `ro` | Кастомные шаблоны сообщений |
| Хранилище | `alertmanager_data` (volume) | `/alertmanager` | `rw` | База данных silences и состояний |

### Связь с Prometheus (API v2)

В Docker Compose сервисы взаимодействуют через внутреннюю сеть по DNS-именам. В Prometheus v3 поддержка Alertmanager API v1 удалена. В файле `prometheus.yml` (см. [prometheus_config.md](./prometheus_config.md)) необходимо указывать:

```yaml
alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets:
            - 'alertmanager:9093'
```

### Особенности Docker-развёртывания

1.  **Интерполяция переменных:** С версии v0.27+ Alertmanager поддерживает флаг `--config.expand-env`, позволяющий использовать конструкции `${VAR}` в `config.yml`.
2.  **Hot Reload:** Конфигурацию можно применить без рестарта контейнера через HTTP POST на `/etc/alertmanager/-/reload` (требуется флаг `--web.enable-lifecycle`).
3.  **Персистентность:** Без использования именованного тома (volume) все созданные в UI «тишины» (silences) будут удалены при обновлении образа.
4.  **Права доступа:** Контейнер работает под пользователем с UID 65534. При использовании bind mounts для данных необходимо выполнить `chown -R 65534:65534 ./alertmanager_data`.

## Практические сценарии

### Конфигурация с секретами и шаблонами (`alertmanager/config.yml`)

Пример использования переменных окружения для безопасной передачи токенов.

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: '${SMTP_SMARTHOST}'
  smtp_from: '${SMTP_FROM}'
  smtp_auth_username: '${SMTP_USER}'
  smtp_auth_password: '${SMTP_PASS}'

templates:
  - '/etc/alertmanager/templates/*.tmpl'

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

### Секция Alertmanager в `compose.yml`

Настройка сервиса для работы в стеке с поддержкой переменных окружения из `.env`.

```yaml
services:
  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: monitoring-alertmanager
    volumes:
      - ./alertmanager:/etc/alertmanager:ro
      - alertmanager_data:/alertmanager
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--config.expand-env'
      - '--web.enable-lifecycle'
    env_file: .env
    ports:
      - "9093:9093"
    restart: unless-stopped
    networks:
      - monitoring-net

volumes:
  alertmanager_data:
```

### HA-кластер в Docker Compose с Gossip TLS

Для обеспечения высокой доступности узлы Alertmanager должны обмениваться данными через gossip-протокол (порт `9094`).

```yaml
services:
  alertmanager-node-1:
    image: prom/alertmanager:v0.33.1
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      # В Docker важно указать advertise-address для корректного поиска узлов
      - '--cluster.advertise-address=alertmanager-node-1:9094'
      - '--cluster.peer=alertmanager-node-2:9094'
      # Опционально: шифрование gossip-трафика
      - '--cluster.tls-config.cert-file=/etc/alertmanager/certs/node1.crt'
      - '--cluster.tls-config.key-file=/etc/alertmanager/certs/node1.key'
    networks:
      - monitoring-net
```

### Диагностика через amtool

Утилита `amtool` предустановлена в образе и позволяет управлять алертингом из терминала.

```bash
# Валидация синтаксиса конфигурации
docker exec alertmanager amtool check-config /etc/alertmanager/config.yml

# Просмотр активных оповещений
docker exec alertmanager amtool alert --alertmanager.url=http://localhost:9093

# Создание тишины (silence) для подавления шума
docker exec alertmanager amtool silence add alertname=NodeDown duration=1h comment="Scheduled maintenance"

# Проверка статуса API
curl -s http://localhost:9093/-/healthy
```

## Устранение неполадок в Docker

| Проблема | Причина | Решение |
|---|---|---|
| **Silences сбрасываются** | Не примонтирован volume `/alertmanager` | Проверьте секцию `volumes` в `compose.yml`. |
| **Переменные не подставляются** | Отсутствует флаг `--config.expand-env` | Добавьте флаг в команду запуска сервиса. |
| **Узлы HA не видят друг друга** | Неверный `advertise-address` | Убедитесь, что узлы используют имена сервисов Docker Compose для связи. |
| **Permission denied на данных** | Несоответствие прав UID | Выполните `chown -R 65534:65534 ./alertmanager_data`. |

## Дополнительная информация

### Связанные темы

* [Alertmanager — архитектура и API](../../alertmanager.md) — детальный разбор маршрутизации и группировки.
* [Шаблонизация уведомлений](../../alertmanager/templates_deep_dive.md) — создание сложных Go-шаблонов для сообщений.
* [Конфигурация Prometheus](./prometheus_config.md) — настройка отправки алертов.
* [Мониторинг Docker Engine](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с демоном Docker.
