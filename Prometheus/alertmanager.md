# Alertmanager — управление оповещениями

## Определения

**Alertmanager** — специализированный компонент стека Prometheus, отвечающий за обработку, агрегацию и доставку оповещений. Он принимает активные алерты от серверов мониторинга и применяет к ним логику группировки, подавления и маршрутизации в конечные каналы уведомлений (Email, Slack, PagerDuty, Webhook).

Начиная с версий **v0.27+ (2024–2025)**, Alertmanager поддерживает расширенные механизмы аутентификации (OAuth2), шифрование трафика внутри кластера (Cluster TLS) и интеграцию с современными Identity Providers.

| **Актуальная версия** | `v0.33.1` (на момент написания) |
| **Порт API/UI** | `9093` (TCP) |
| **Порт кластера (Gossip)** | `9094` (TCP/UDP) |
| **Протокол связи** | HTTP (прием), Mesh/Gossip (кластеризация) |
| **Репозиторий** | [prometheus/alertmanager](https://github.com/prometheus/alertmanager) |
| **Минимальная память** | 128 MiB (рекомендуется 256 MiB для production) |
| **Минимальный диск** | 100 MiB + объем для persistence |
| **Форматы приема** | Prometheus Text, OpenMetrics, Protobuf |
| **Встроенная аутентификация** | Нет (требуется `--web.config.file` или внешний прокси) |
| **Поддержка UTF-8** | Да (v1.9.0+, имена меток в UTF-8) |

> **Важно:** Alertmanager предназначен для централизованной обработки алертов от одного или нескольких Prometheus Server. Для кратковременных batch-заданий используйте Pushgateway, а не Alertmanager.

> **См. также:** [Обзор Prometheus](./overview.md), [Правила алертинга](./rules.md), [Установка Alertmanager](./installation/alertmanager_installation.md).

## Предварительные требования

| Компонент | Минимальная версия / Требование | Проверка |
| :--- | :--- | :--- |
| **ОС** | Linux 2.6.32+ (x86_64, arm64) | `uname -r` |
| **Память** | 128 MiB RAM (рекомендуется 256 MiB для production) | `free -h` |
| **Диск** | 100 MiB для бинарных файлов + объем для persistence | `df -h /var/lib/alertmanager` |
| **curl** | Любая версия с поддержкой HTTP POST/PUT | `curl --version` |
| **systemd** | v219+ (для unit-файлов) | `systemctl --version` |
| **Docker/Podman** | 20.10+ (для контейнеризации) | `docker --version` |
| **Helm** | v3.8+ (для Kubernetes) | `helm version` |
| **Kubernetes** | >= 1.28 (для kube-prometheus-stack) | `kubectl version --short` |
| **Prometheus Operator** | >= v0.57.0 (для AlertmanagerConfig CRD) | `kubectl get pods -n monitoring -l app=prometheus-operator` |

### Сравнение методов развертывания

| Метод | Уровень контроля | Сложность | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Бинарные файлы + systemd** | Максимальный | Средняя | Production bare-metal/VM, требование hardening |
| **Docker / Podman** | Высокий | Низкая | Контейнеризированные среды, быстрый старт |
| **APT (Debian/Ubuntu)** | Средний | Низкая | Стандартные серверы Debian/Ubuntu |
| **Helm (Kubernetes)** | Высокий | Средняя | Kubernetes, GitOps, kube-prometheus-stack |
| **Ansible** | Высокий | Средняя | Парк серверов, IaC |

> **Рекомендация:** Для Production bare-metal/VM используйте бинарные файлы — максимальный контроль над версиями и hardening. Для Kubernetes используйте Helm-чарт `kube-prometheus-stack`. Для быстрого старта в контейнерах — Docker/Podman. Подробно: **[Установка Alertmanager](./installation/alertmanager_installation.md)**.

## Основные концепции

### Архитектура и роль в стеке

В экосистеме Prometheus алертинг разделен на два независимых этапа:
1.  **Детектирование (Prometheus):** Вычисляет PromQL-выражения из [правил алертинга](./rules.md). Если условие истинно дольше времени `for`, Prometheus отправляет HTTP-запрос (webhook) в Alertmanager.
2.  **Обработка (Alertmanager):** Выполняет дедупликацию (если несколько Prometheus прислали один алерт), группировку и доставку. Один Alertmanager может обслуживать сотни серверов мониторинга.

### Конвейер обработки (Alert Pipeline)

1.  **Дедупликация (Deduplication):** Удаление повторяющихся сигналов от разных реплик Prometheus в HA-парах.
2.  **Группировка (Grouping):** Объединение алертов в одно сообщение по общим меткам (например, `cluster` или `service`). Предотвращает лавинообразную рассылку уведомлений.
3.  **Подавление (Inhibition):** Взаимное исключение алертов. Если активен «родительский» алерт (например, падение всего кластера), «дочерние» (падение подов в этом кластере) будут подавлены.
4.  **Замалчивание (Silencing):** Временное отключение уведомлений вручную (плановые работы).
5.  **Маршрутизация (Routing):** Древовидная структура правил, определяющая, куда именно (Slack, Email, Webhook) отправится группа алертов.

### Высокая доступность и кластеризация (HA)

Alertmanager использует **Mesh-архитектуру** на базе gossip-протокола.
*   **Cluster TLS (v0.24+):** Поддержка шифрования трафика между узлами кластера (порт 9094). Это критично для Zero Trust сред.
*   **Дедупликация уведомлений:** Узлы кластера обмениваются информацией о том, кто и когда отправил уведомление, чтобы избежать повторов.
*   **CAP-теорема:** Alertmanager выбирает **Availability (A)** и **Partition tolerance (P)**. В случае разделения сети (Split-brain) каждый сегмент будет отправлять уведомления самостоятельно, что может привести к дублям, но гарантирует доставку сигнала.


## Структура конфигурации (alertmanager.yml)

### Глобальные настройки (global)

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| **`resolve_timeout`** | Время, через которое алерт помечается как решенный, если Prometheus перестал его слать. | По умолчанию `5m`. |
| **`smtp_smarthost`** | Адрес SMTP-сервера с портом. | Например, `smtp.gmail.com:587`. |
| **`smtp_from`** | Адрес отправителя email. | Обязателен для email-уведомлений. |
| **`http_config`** | Глобальные настройки HTTP-клиента (прокси, TLS, авторизация). | Наследуется всеми receivers. |
| **`slack_api_url`** | Глобальный URL для Slack Webhook. | Можно переопределить в конкретном роуте. |

### Маршрутизация (route)

Правила маршрутизации представляют собой дерево, где каждый алерт проходит сверху вниз до первого совпадения (или продолжает путь, если `continue: true`).

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| **`receiver`** | Имя получателя из секции `receivers`. | Обязателен для корневого правила. |
| **`group_by`** | Список меток для объединения алертов в группы. | Обычно `[alertname, cluster, job]`. |
| **`group_wait`** | Сколько ждать появления новых алертов в группе до первой отправки. | Рекомендуется `30s-1m`. |
| **`group_interval`** | Как часто слать уведомления о новых алертах в уже активной группе. | Обычно `5m`. |
| **`repeat_interval`** | Интервал повторной отправки уведомления для неисправленной проблемы. | Для критичных: `1h-3h`, для Info: `24h`. |
| **`matchers`** | Условия совпадения меток. | Формат `{label="value"}` или `{label=~"regex"}`. |

### Настройка получателей (receivers)

Современные версии поддерживают расширенную авторизацию.

**Пример с OAuth2 и Webhook:**
```yaml
receivers:
  - name: 'custom-webhook'
    webhook_configs:
      - url: 'https://api.internal.tool/alerts'
        http_config:
          oauth2:
            client_id: 'alertmanager-client'
            client_secret_file: '/etc/alertmanager/secrets/oauth-secret'
            token_url: 'https://auth.example.com/token'
            scopes: ['alerts:write']
```

## Практические сценарии

### Структура Payload вебхука (Data Contract)

При разработке собственных обработчиков важно знать структуру JSON, которую отправляет Alertmanager.

```json
{
  "receiver": "webhook-receiver",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": { "alertname": "HighCpuUsage", "severity": "critical", "instance": "node-1" },
      "annotations": { "summary": "CPU usage is high", "runbook_url": "http://docs/cpu" },
      "startsAt": "2026-08-11T10:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph?..."
    }
  ],
  "groupLabels": { "alertname": "HighCpuUsage" },
  "commonLabels": { "alertname": "HighCpuUsage", "severity": "critical" },
  "commonAnnotations": { "summary": "CPU usage is high" },
  "externalURL": "http://alertmanager:9093"
}
```

### Комплексный пример конфигурации с Inhibition и Time Intervals

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alertmanager@example.com'

time_intervals:
  - name: maintenance-window
    time_intervals:
      - weekdays: ['saturday', 'sunday']
        times:
        - start_time: '00:00'
          end_time: '23:59'

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default-receiver'

  routes:
    # Критичные алерты — мгновенная отправка в PagerDuty
    - matchers:
        - severity="critical"
      receiver: 'pagerduty-critical'
      group_wait: 0s
      
    # Отключение уведомлений в выходные (кроме критичных)
    - matchers:
        - severity="warning"
      receiver: 'slack-warnings'
      mute_time_intervals:
        - maintenance-window

inhibit_rules:
  # Если лежит целый кластер, не слать алерты о подах в нем
  - source_matchers: [alertname="ClusterDown"]
    target_matchers: [alertname=~"Pod.*"]
    equal: [cluster]

receivers:
  - name: 'default-receiver'
    email_configs: [{ to: 'ops@example.com' }]
  - name: 'pagerduty-critical'
    pagerduty_configs: [{ service_key: 'XYZ' }]
  - name: 'slack-warnings'
    slack_configs: [{ channel: '#alerts-warning' }]
```


### Управление через CLI (amtool)

Инструмент `amtool` входит в состав дистрибутива Alertmanager и позволяет автоматизировать работу.

**Настройка конфига (`~/.config/amtool/config.yml`):**
```yaml
alertmanager.url: "http://alertmanager.example.com:9093"
```

**Основные команды:**
- `amtool alert` — список активных алертов с их метками.
- `amtool silence add alertname=NodeDown --comment="Patching" --duration=2h` — создать сайленс.
- `amtool config routes show` — визуализировать дерево маршрутизации для отладки.
- `amtool check-config alertmanager.yml` — валидация синтаксиса.

### Паттерн развертывания в Kubernetes (HA с секретами)

Для безопасного управления паролями и токенами рекомендуется следующий паттерн:

| Шаг | Компонент | Действие |
| :--- | :--- | :--- |
| **1** | **ConfigMap** | Содержит `alertmanager.yml` с плейсхолдерами (например, `{{SLACK_URL}}`). |
| **2** | **Secret** | Содержит реальные значения секретов. |
| **3** | **Init Container** | Под на базе `busybox` берет `ConfigMap`, делает `envsubst` из переменных окружения (подтянутых из Secret) и пишет результат в `emptyDir`. |
| **4** | **Alertmanager** | Запускается и монтирует готовый конфиг из `emptyDir`. |

Это позволяет хранить логику маршрутизации в Git, а секреты — в защищенном хранилище.

### Сценарии тестирования и отладки

1.  **Проверка маршрутизации:** Используйте [Routing Tree Editor](https://www.prometheus.io/webtools/alerting/routing-tree-editor/), вставив туда свой YAML и набор меток.
2.  **Эмуляция алерта:**
    ```bash
    curl -H "Content-Type: application/json" -d '[{"labels":{"alertname":"TestAlert","severity":"critical"}}]' http://localhost:9093/api/v2/alerts
    ```
3.  **Горячая перезагрузка:** Alertmanager перечитывает конфиг при получении сигнала SIGHUP или POST-запроса на `/-/reload`.
    ```bash
    curl -X POST http://alertmanager:9093/-/reload
    ```

## Дополнительная информация

### Безопасность (web-config.yml)

Начиная с **v0.22.0**, поддерживается нативный TLS и Basic Auth (ранее требовался Nginx/Auth-proxy).

```yaml
# web-config.yml
tls_server_config:
  cert_file: /etc/alertmanager/certs/tls.crt
  key_file: /etc/alertmanager/certs/tls.key
basic_auth_users:
  admin: "$2y$12$..." # Bcrypt хеш
```
Запуск: `--web.config.file=web-config.yml`.

### Сравнение: Alertmanager vs Grafana Alerting

| Критерий | Alertmanager | Grafana Alerting |
| :--- | :--- | :--- |
| **Сложность** | Высокая (Inhibition, Mesh HA) | Средняя (Visual UI) |
| **Источники** | Только Prometheus API | Любые БД (SQL, Cloud) |
| **Назначение** | Инфраструктурный мониторинг | Бизнес-метрики, визуализация |
| **HA** | Встроенный Gossip | Требует БД (Postgres/MySQL) |

### Отправка уведомлений в Telegram

Alertmanager не имеет встроенного receiver для Telegram. Для отправки алертов в Telegram используется промежуточный webhook-сервис.

**Архитектура решения:**

```
Alertmanager → Webhook (telegram-bot/prometheus-telegram-bot) → Telegram API
```

**Варианты реализации:**

1.  **prometheus-alertmanager-bot (Go):**
    - Легковесный сервер, принимающий webhook от Alertmanager и отправляющий сообщения в Telegram.
    - Поддерживает шаблонизацию сообщений (Go templates).
    - Репозиторий: [metalmatze/alertmanager-bot](https://github.com/metalmatze/alertmanager-bot).

2.  **self-written proxy:**
    - Написание собственного микросервиса на Python/Go для трансформации webhook Alertmanager в Telegram Bot API.

**Пример конфигурации Alertmanager:**

```yaml
receivers:
  - name: 'telegram-critical'
    webhook_configs:
      - url: 'http://alertmanager-bot:9090/alert'
        send_resolved: true
```

**Проблема с Telegram в России:**
Telegram API может быть недоступен из-за блокировок. Решение — использование прокси:

- **HTTP/SOCKS5-прокси:** Настройка прокси на уровне приложения (alertmanager-bot) или через переменные окружения `HTTP_PROXY`, `HTTPS_PROXY`.
- **Outbound proxy в Kubernetes:** Использование Service Mesh (Istio) или sidecar-контейнера (envoy/squid) для маршрутизации трафика к Telegram API через внешний прокси-сервер.

**Пример настройки прокси для alertmanager-bot:**

```yaml
# Kubernetes Deployment
env:
  - name: HTTPS_PROXY
    value: "http://proxy-server:3128"
  - name: HTTP_PROXY
    value: "http://proxy-server:3128"
  - name: NO_PROXY
    value: "localhost,127.0.0.1,10.0.0.0/8"
```

**Альтернативный подход:** Использование Grafana Alerting с встроенным контакт-пойнтом Telegram (Grafana 9+), который также поддерживает настройку прокси через конфигурацию datasource.
### Рекомендации SRE по алертингу

1.  **Actionable Alerts:** Каждый алерт должен иметь аннотацию `runbook_url`. Если на алерт нельзя отреагировать действием — это не алерт, а шум на дашборде.
2.  **Symptom-based Alerting:** Алертите на симптомы (ошибки, задержки), а не на причины (высокий CPU сам по себе не всегда проблема).
3.  **NoData — это алерт:** Всегда настраивайте алерты на отсутствие данных (`absent()`) от критических систем.
4.  **Дедупликация и группировка:** Никогда не слать алерты по одному. Группировка по `cluster` или `service` позволяет видеть масштаб проблемы (например, падение всей базы, а не 50 отдельных инстансов).

### Ключевые флаги запуска

- `--cluster.listen-address`: Адрес для gossip-протокола (порт `9094`). Пустое значение отключает HA.
- `--cluster.peer`: Адреса других узлов кластера для формирования mesh-сети.
- `--data.retention`: Время хранения состояния алертов и сайленсов (по умолчанию `120h`).
- `--web.external-url`: Публичный URL Alertmanager (критично для корректных ссылок в Slack/Email).
- `--config.expand-env`: Интерполяция переменных окружения в `alertmanager.yml` (например, `${SMTP_PASS}`).
- `--web.enable-lifecycle`: Включение `/-/reload` и `/-/healthy` для горячей перезагрузки.
- `--web.enable-api`: Включение HTTP API v2 (по умолчанию `true`).
- `--cluster.advertise-address`: Адрес для анонса другим узлам; в Docker Compose — имя сервиса.
- `--cluster.tls-config.cert-file`, `--cluster.tls-config.key-file`, `--cluster.tls-config.ca-file`: Сертификаты для TLS gossip-трафика.

### Валидация конфигурации и тестирование

Перед применением конфигурации всегда выполняйте валидацию:

```bash
# Проверка синтаксиса YAML
amtool check-config /etc/alertmanager/alertmanager.yml
# → SUCCESS

# Валидация без запуска (Docker)
docker run --rm -v ./alertmanager:/etc/alertmanager:ro prom/alertmanager:v0.33.1 \
  amtool check-config /etc/alertmanager/alertmanager.yml

# Проверка доступности
curl -s http://localhost:9093/-/healthy
# → OK

# Проверка readiness (запущены ли все receivers)
curl -s http://localhost:9093/-/ready
# → OK

# Проверка версии через API
curl -s http://localhost:9093/api/v2/status/buildinfo | jq .version
# → "0.33.1"

# Проверка активных алертов
curl -s http://localhost:9093/api/v2/alerts | jq length
# → 0

# Проверка силенсов
curl -s http://localhost:9093/api/v2/silences | jq length
# → 5
```

### HTTP API (v2)

Alertmanager предоставляет REST API v2 для интеграции с внешними системами.

| Эндпоинт | Метод | Описание |
| :--- | :--- | :--- |
| `/-/healthy` | GET | Проверка работоспособности процесса. |
| `-/ready` | GET | Проверка готовности receivers. |
| `/-/reload` | POST | Горячая перезагрузка конфигурации. |
| `/api/v2/status` | GET | Статус кластера и версия. |
| `/api/v2/alerts` | GET/POST | Получение/создание алертов. |
| `/api/v2/silences` | GET/POST | Получение/создание силенсов. |
| `/api/v2/silences/{silenceID}` | GET/DELETE | Получение/удаление силенса по ID. |
| `/api/v2/receivers` | GET | Список receivers и их статус. |

**Пример: получение активных алертов:**
```bash
curl -s http://localhost:9093/api/v2/alerts | jq .
```

**Пример: создание силенса через API:**
```bash
curl -X POST http://localhost:9093/api/v2/silences \
  -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "NodeDown", "isRegex": false}],
    "startsAt": "2026-09-17T10:00:00Z",
    "endsAt": "2026-09-17T12:00:00Z",
    "comment": "Planned maintenance",
    "createdBy": "sre-team"
  }'
```

### Метрики самомониторинга

Alertmanager экспортирует метрики на эндпоинте `/metrics` для самомониторинга.

| Метрика | Описание |
| :--- | :--- |
| `up{job="alertmanager"}` | Доступность инстанса (1 = OK). |
| `alertmanager_notifications_total` | Общее количество отправленных уведомлений по receiver и integration. |
| `alertmanager_notifications_failed_total` | Количество failed уведомлений (нужно алертировать). |
| `alertmanager_notification_latency_seconds` | Гистограмма задержки доставки. |
| `alertmanager_cluster_members` | Количество активных узлов в Gossip-сети. |
| `alertmanager_alerts` | Количество активных алертов. |
| `alertmanager_not_firing` | Количество решенных алертов. |
| `alertmanager_silenced_alerts` | Количество подавленных алертов. |
| `alertmanager_inhibited_alerts` | Количество подавленных inhibition-правилами алертов. |
| `prometheus_notifications_alertmanagers_discovered` | Количество обнаруженных Alertmanager Prometheus-ом. |
| `alertmanager_config_last_reload_success_timestamp_seconds` | Время последней успешной перезагрузки конфигурации. |

### Алерты на Alertmanager (Self-Monitoring)

Добавьте в Prometheus алерты на состояние самого Alertmanager:

```yaml
groups:
  - name: alertmanager_self_monitoring
    rules:
      - alert: AlertmanagerDown
        expr: up{job="alertmanager"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Alertmanager {{ $labels.instance }} недоступен"
          runbook_url: "https://wiki.example.com/runbooks/alertmanager-down"

      - alert: AlertmanagerNotificationsFailing
        expr: rate(alertmanager_notifications_failed_total[5m]) > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Ошибки доставки уведомлений в {{ $labels.receiver }}"
          runbook_url: "https://wiki.example.com/runbooks/notification-failing"

      - alert: AlertmanagerClusterNotReady
        expr: alertmanager_cluster_members != 3
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Gossip-кластер Alertmanager не готов ({{ $value }} из 3 узлов)"
          runbook_url: "https://wiki.example.com/runbooks/am-cluster"

      - alert: AlertmanagerNotificationLatencyHigh
        expr: histogram_quantile(0.99, sum(rate(alertmanager_notification_latency_seconds_bucket[5m])) by (le)) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка доставки уведомлений (>30s)"

      - alert: AlertmanagerConfigReloadFailure
        expr: alertmanager_config_last_reload_successful == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Alertmanager не может применить конфигурацию"
```

### Ограничения и крайние случаи

1.  **No Replication:** Нет встроенной репликации silences между инстансами без gossip-кластера. Для HA требуется gossip mesh (минимум 3 узла).
2.  **No Sharding:** Alertmanager не поддерживает автоматическое шардирование алертов. При очень высоком объеме (>10k alerts/s) требуется несколько независимых инстансов за балансировщиком.
3.  **Race Condition:** Параллельные задачи с одинаковым `grouping key` могут перезаписывать метрики друг друга.
4.  **Large Payloads:** Очень большие payload (>10 MB) могут вызвать таймауты или утечки памяти.
5.  **Secret Size Limit (Kubernetes):** Общая конфигурация Alertmanager, включая все `AlertmanagerConfig`, не должна превышать 1MB в Kubernetes Secret.
6.  **No Built-in Receiver for Telegram:** Требуется промежуточный webhook-сервис.
7.  **Split-brain возможен:** При разделении сети (split-brain) каждый сегмент кластера будет отправлять уведомления самостоятельно, что может привести к дублям.
8.  **Empty `alertmanagerConfigSelector`:** В Helm-чарте `kube-prometheus-stack` параметр по умолчанию часто пуст `{}`, что означает, что Alertmanager не подхватывает никакие `AlertmanagerConfig`.

### Устранение неполадок (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Алерты не доставляются | Ошибка в receiver (неверный URL, токен) | Проверьте `alertmanager_notifications_failed_total` и логи. |
| Дублирующиеся уведомления | Неправильная HA-конфигурация | Проверьте `cluster.listen-address` и открытый порт 9094. |
| Пустые алерты в receivers | Отсутствуют аннотации | Добавьте `summary` и `description` в PrometheusRule. |
| Алерты не группируются | Неправильные `group_by` | Убедитесь, что метки существуют в алертах. |
| Потеря силенсов после рестарта | Отсутствует persistence | Настройте `--storage.path` или PVC в Kubernetes. |
| `Connection refused` на 9093 | Сервис не запущен | `systemctl status alertmanager` / `docker ps` / `kubectl get pods` |
| `401 Unauthorized` от Prometheus | Отсутствует `basicAuth` | Добавьте учетные данные в `alerting.alertmanagers`. |
| AlertmanagerConfig не применяется | Пустой `alertmanagerConfigSelector` | Добавьте `matchLabels` в `values.yaml`. |
| Gossip-кластер не образуется | Порт 9094 заблокирован | Откройте порт 9094 между репликами (NetworkPolicy). |
| Inhibition не работает | Неправильные `equal` или `source_match`/`target_match` | Проверьте, что алерты содержат нужные метки и severity. |
| Mute timing не применяется | Неверный формат `time_range` или часовой пояс | Alertmanager использует UTC; проверьте `time_range` и `weekdays`. |
| Config reload не работает | Отсутствует `--web.enable-lifecycle` | Добавьте флаг в команду запуска и перезапустите. |
| `/-/reload` возвращает 404 | Флаг `--web.enable-lifecycle` не активен | Проверьте запущенный процесс: `docker exec alertmanager ps aux`. |
| High memory usage | Слишком много активных silences или алертов | Ограничьте retention (`--data.retention=48h`) и добавьте purge cron. |
| SMTP доставка падает | TLS handshake failed, спам-фильтр, неверный from | Проверьте `require_tls`, сертификаты и SPF/DKIM для домена. |
| Webhook таймаут | Целевой сервис недоступен или медленный | Увеличьте `timeout` в `webhook_configs` и проверьте сетевую доступность. |

### Best Practices

1.  **Actionable Alerts:** Каждый алерт должен иметь аннотацию `runbook_url`. Если на алерт нельзя отреагировать действием — это не алерт, а шум.
2.  **Symptom-based Alerting:** Алертите на симптомы (ошибки, задержки), а не на причины.
3.  **NoData — это алерт:** Всегда настраивайте алерты на отсутствие данных (`absent()`) от критических систем.
4.  **Группировка:** Используйте `group_by` на `cluster` или `service`, чтобы видеть масштаб проблемы, а не отдельные инстансы.
5.  **Мета-мониторинг:** Добавьте алерт на `rate(alertmanager_notifications_failed_total[5m]) > 0` — «тихий» сбой доставки остаётся незамеченным без мониторинга самого алертинга.
6.  **Дедупликация:** В HA-режиме всегда включайте gossip (порт 9094), иначе при рестарте одного из Prometheus вы получите дубли уведомлений.
7.  **Inhibition:** Используйте inhibition для подавления зависимых алертов, но регулярно пересматривайте правила, чтобы не замаскировать проблему.
8.  **Mute Timings vs Silences:** Используйте Mute Timings для плановых окон (ночные смены), а Silences — для инцидентов и работ. Удаляйте временные Silences после инцидентов.
9.  **Бэкап silences:** Регулярно экспортируйте silences через API (`curl -s http://localhost:9093/api/v2/silences > backup.json`) перед массовыми изменениями.
10. **Безопасность:** Никогда не открывайте порт 9093 наружу без reverse proxy с Basic Auth/TLS. Портом 9094 вообще не должен быть доступен с хоста.
11. **Размер силенсов:** Для production используйте persistent storage для silences; без persistence все тишины теряются при рестарте.
12. **Версии:** Используйте одинаковые версии Alertmanager во всех узлах кластера для предотвращения проблем с сериализацией gossip-протокола.

### Шаблоны уведомлений (Go Templates)

Alertmanager использует Go templates для форматирования сообщений. Шаблоны определяются в секции `templates:` и подключаются в receiver.

```yaml
global:
  templates:
    - '/etc/alertmanager/templates/*.tmpl'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - channel: '#monitoring-alerts'
        send_resolved: true
        title: '{{ .Status | toUpper }}: {{ .GroupLabels.alertname }}'
        text: >-
          {{ range .Alerts }}
            *Alert:* {{ .Labels.alertname }}
            *Severity:* {{ .Labels.severity }}
            *Summary:* {{ .Annotations.summary }}
            *Runbook:* {{ .Annotations.runbook_url }}
          {{ end }}
        color: >-
          {{ if eq .Status "firing" }}danger{{ else }}good{{ end }}
```

**Доступные переменные в шаблонах:**
- `.Status` — `firing` или `resolved`.
- `.GroupLabels` — метки группы.
- `.CommonLabels` — общие метки всех алертов в группе.
- `.CommonAnnotations` — общие аннотации.
- `.ExternalURL` — публичный URL Alertmanager.
- `.Alerts` — список алертов в группе.

### Mute Timings и Maintenance Windows

Mute Timings позволяют автоматически подавлять уведомления в определенные временные окна (ночные смены, выходные).

```yaml
mute_time_intervals:
  maintenance-window:
    time_intervals:
      - weekdays: ['saturday', 'sunday']
        times:
          - start_time: '00:00'
            end_time: '23:59'
  night-shift:
    time_intervals:
      - times:
          - start_time: '22:00'
            end_time: '08:00'
        weekdays: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

route:
  routes:
    - receiver: 'slack-warnings'
      matchers:
        - severity="warning"
      mute_time_intervals:
        - maintenance-window
        - night-shift
```

> **Примечание:** Alertmanager использует UTC для всех временных меток. Убедитесь, что `start_time` и `end_time` указаны в UTC.

### Управление данными (Резервное копирование и восстановление)

**Резервное копирование:**
```bash
# Экспорт конфигурации
sudo cp /etc/alertmanager/alertmanager.yml /etc/alertmanager/alertmanager.yml.bak

# Экспорт состояния силенсов (silences) и данных
curl -s http://localhost:9093/api/v2/silences > alertmanager-silences-$(date +%Y%m%d).json
curl -s http://localhost:9093/metrics > alertmanager-metrics-$(date +%Y%m%d).txt

# Экспорт файла персистентности
sudo cp /var/lib/alertmanager/*.db /var/lib/alertmanager/alertmanager.db.bak
```

**Восстановление:**
```bash
# Остановка сервиса
sudo systemctl stop alertmanager

# Восстановление конфигурации
sudo cp /etc/alertmanager/alertmanager.yml.bak /etc/alertmanager/alertmanager.yml

# Восстановление данных
sudo cp /var/lib/alertmanager/alertmanager.db.bak /var/lib/alertmanager/

# Запуск
sudo systemctl start alertmanager
```

**Очистка всех данных:**
```bash
# Внимание: удаляет все силенсы!
curl -X PUT http://localhost:9093/-/wipe
```

### Обновление и откат

#### Бинарные файлы

```bash
# 1. Остановка сервиса
sudo systemctl stop alertmanager

# 2. Загрузка и замена бинарных файлов
ALERTMANAGER_VERSION="0.33.2"
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
tar xvfz alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
sudo mv alertmanager-${ALERTMANAGER_VERSION}/alertmanager /usr/local/bin/

# 3. Валидация конфигурации (критично перед запуском)
amtool check-config /etc/alertmanager/alertmanager.yml

# 4. Запуск
sudo systemctl start alertmanager
```

**Откат:** Верните предыдущие бинарные файлы из резервной копии и перезапустите сервис.

#### APT

```bash
# Обновление
sudo apt update && sudo apt upgrade alertmanager

# Проверка версии
alertmanager --version

# Фиксация версии (предотвращение автоматического обновления)
sudo apt-mark hold alertmanager
```

**Откат:**
```bash
sudo apt-mark unhold alertmanager
sudo apt install alertmanager=0.33.1
```

#### Helm (Kubernetes)

Подробно: **[Конфигурация Alertmanager в kube-prometheus-stack](./kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md)**.

```bash
# 1. Создание резервной копии текущих значений
helm get values monitoring -n monitoring > values-backup.yaml

# 2. Применение изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values-backup.yaml \
  -f values.yaml

# 3. Проверка rollout
kubectl rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager -n monitoring --timeout=5m

# 4. В случае проблем — откат
helm rollback monitoring -n monitoring --timeout=5m
```

> **Важно:** Helm не обновляет CRD автоматически при обновлении чарта. При мажорных обновлениях примените CRD вручную.

### Связанные ресурсы

- **[Обзор Prometheus](./overview.md)** — контекст работы Pull/Push.
- **[Безопасность мониторинга](./security.md)** — защита API и TLS.
- **[Обзор экспортеров](./Exporters/overview.md)** — источники данных для алертинга.
- **[Официальный Routing Tree Editor](https://www.prometheus.io/webtools/alerting/routing-tree-editor/)** — инструмент для отладки YAML-конфигурации.

