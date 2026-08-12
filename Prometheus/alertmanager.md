# Alertmanager — управление оповещениями

## Определения

**Alertmanager** — специализированный компонент стека Prometheus, отвечающий за обработку, агрегацию и доставку оповещений. Он принимает активные алерты от серверов мониторинга и применяет к ним логику группировки, подавления и маршрутизации в конечные каналы уведомлений (Email, Slack, PagerDuty, Webhook).

Начиная с версий **v0.27+ (2024–2025)**, Alertmanager поддерживает расширенные механизмы аутентификации (OAuth2), шифрование трафика внутри кластера (Cluster TLS) и интеграцию с современными Identity Providers.

| Параметр | Значение |
| :--- | :--- |
| **Порт API/UI** | `9093` |
| **Порт кластера (Gossip)** | `9094` (TCP/UDP) |
| **Протокол связи** | HTTP (прием), Mesh/Gossip (кластеризация) |
| **Репозиторий** | [prometheus/alertmanager](https://github.com/prometheus/alertmanager) |

> **См. также:** [Обзор Prometheus](./overview.md), [Правила алертинга](./rules.md), [Установка Alertmanager](./installation/alertmanager_installation.md).

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
    curl -H "Content-Type: application/json" -d '[{"labels":{"alertname":"TestAlert","severity":"critical"}}]' http://localhost:9093/api/v1/alerts
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

### Связанные ресурсы

- **[Методы сбора данных в Prometheus](./overview.md#методы-сбора-данных)** — контекст работы Pull/Push.
- **[Безопасность мониторинга](./security.md)** — защита API и TLS.
- **[Обзор экспортеров](./Exporters/overview.md)** — источники данных для алертинга.
- **[Официальный Routing Tree Editor](https://www.prometheus.io/webtools/alerting/routing-tree-editor/)** — инструмент для отладки YAML-конфигурации.

