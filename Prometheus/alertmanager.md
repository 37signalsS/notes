# Alertmanager — управление оповещениями

## Определения

**Alertmanager** — специализированный компонент стека Prometheus, отвечающий за обработку, агрегацию и доставку оповещений. Он принимает активные алерты от серверов мониторинга и применяет к ним логику группировки, подавления и маршрутизации в конечные каналы уведомлений (Email, Slack, PagerDuty, Webhook).

Alertmanager обеспечивает интеллектуальное управление инцидентами, предотвращая "шторм оповещений" и позволяя инженерам сосредоточиться на критических проблемах.

| Параметр | Значение |
| :--- | :--- |
| **Порт API/UI** | `9093` |
| **Порт кластера (Gossip)** | `9094` |
| **Протокол связи** | HTTP (прием), Gossip/Mesh (кластеризация) |
| **Репозиторий** | [prometheus/alertmanager](https://github.com/prometheus/alertmanager) |

> **См. также:** [Обзор Prometheus](./overview.md), [Правила алертинга](./rules.md), [Установка Alertmanager](./installation/alertmanager_installation.md).

## Основные концепции

### Архитектура и роль в стеке

В экосистеме Prometheus алертинг разделен на два независимых этапа:
1.  **Детектирование (Prometheus):** Вычисляет PromQL-выражения из [правил алертинга](./rules.md). Если условие истинно дольше времени `for`, Prometheus отправляет HTTP-запрос (webhook) со списком алертов в Alertmanager.
2.  **Обработка (Alertmanager):** Обогащает алерты метаданными, применяет фильтры и доставляет их получателям. Один Alertmanager может принимать сигналы от сотен экземпляров Prometheus.

### Конвейер обработки (Alert Pipeline)

1.  **Группировка (Grouping):** Объединение нескольких алертов в одно сообщение по общим меткам. Позволяет не получать 100 уведомлений при падении одной стойки с серверами.
2.  **Подавление (Inhibition):** Автоматическое заглушение алертов при наличии "блокирующего" события. Например, если активен алерт `RackDown`, уведомления `HostDown` для серверов в этой стойке будут подавлены.
3.  **Замалчивание (Silencing):** Временное отключение уведомлений вручную через UI или API (например, на время планового обслуживания).
4.  **Маршрутизация (Routing):** Выбор пути в дереве правил на основе меток (labels) для определения конечного получателя.

### Высокая доступность и кластеризация (HA)

Alertmanager использует архитектуру **Mesh** на базе gossip-протокола для синхронизации состояния между узлами без центрального хранилища.

-   **Дедупликация:** Если алерты приходят на все узлы кластера от разных Prometheus, уведомление будет отправлено только один раз (узлы "договариваются" между собой).
-   **Синхронизация сайленсов:** Созданный на одном узле Silence мгновенно реплицируется на все остальные.
-   **Кворум не требуется:** Система спроектирована по принципу AP (Availability/Partition tolerance) — при разделении сети каждый сегмент будет продолжать отправку уведомлений.

## Структура конфигурации (alertmanager.yml)

### Глобальные настройки (global)

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| **`resolve_timeout`** | Время, через которое алерт помечается как решенный, если Prometheus перестал его слать. | По умолчанию `5m`. |
| **`smtp_smarthost`** | Адрес SMTP-сервера с портом. | Например, `smtp.gmail.com:587`. |
| **`smtp_from`** | Адрес отправителя email. | Обязателен для email-уведомлений. |
| **`smtp_auth_*`** | Параметры аутентификации (user, password, identity). | См. раздел о секретах. |
| **`slack_api_url`** | Глобальный URL для Slack Webhook. | Можно переопределить в receivers. |

### Маршрутизация (route)

Правила маршрутизации представляют собой дерево, где каждый алерт проходит сверху вниз.

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| **`receiver`** | Имя получателя из секции `receivers`. | Обязателен для корневого правила. |
| **`group_by`** | Список меток для объединения алертов в группы. | Обычно `[alertname, cluster, job]`. |
| **`group_wait`** | Сколько ждать появления новых алертов в группе до первой отправки. | Рекомендуется `30s-1m`. |
| **`group_interval`** | Как часто слать уведомления о новых алертах в уже активной группе. | Обычно `5m`. |
| **`repeat_interval`** | Интервал повторной отправки уведомления для неисправленной проблемы. | Для критичных: `1h-3h`, для Info: `24h`. |
| **`continue`** | Позволяет алерту продолжить движение по дереву после совпадения. | По умолчанию `false`. |
| **`matchers`** | Список условий совпадения меток (v0.22+ замена `match`/`match_re`). | Формат `{label="value"}` или `{label=~"regex"}`. |

### Правила подавления (inhibit_rules)

Позволяют блокировать уведомления одних алертов на основе существования других.

| Параметр | Описание |
| :--- | :--- |
| **`source_matchers`** | Признаки "блокирующего" алерта (который должен существовать). |
| **`target_matchers`** | Признаки алертов, которые будут заглушены. |
| **`equal`** | Список меток, значения которых должны полностью совпадать у обоих алертов (например, `node` или `instance`). |

### Временные интервалы (time_intervals)

Появились в **v0.24.0** (заменили `mute_time_intervals` на уровне конфигурации). Позволяют описывать окна обслуживания или рабочее время.

-   **`mute_time_intervals` (в роуте):** Список интервалов, когда уведомления **ЗАПРЕЩЕНЫ**.
-   **`active_time_intervals` (в роуте):** Список интервалов, когда уведомления **РАЗРЕШЕНЫ**.

## Практические сценарии

### Комплексный пример конфигурации

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alertmanager@example.com'

time_intervals:
  - name: work-hours
    time_intervals:
      - weekdays: ['monday:friday']
        times:
        - start_time: '09:00'
          end_time: '18:00'

route:
  group_by: ['alertname', 'cluster']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 3h
  receiver: 'ops-general'

  routes:
    # Критичные инфраструктурные алерты — всегда в Slack + PagerDuty
    - matchers:
        - severity="critical"
        - team="infrastructure"
      receiver: 'pagerduty-urgent'
      group_wait: 0s # Мгновенная реакция
      
    # Предупреждения (Warning) — только в рабочее время
    - matchers:
        - severity="warning"
      receiver: 'slack-warnings'
      active_time_intervals:
        - work-hours

inhibit_rules:
  - source_matchers: [severity="critical", alertname="NodeDown"]
    target_matchers: [severity="warning"]
    equal: [node, cluster]

receivers:
  - name: 'ops-general'
    email_configs: [{ to: 'ops@example.com' }]
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

1.  **Actionable Alerts:** Каждый алерт должен иметь аннотацию `runbook_url`. Если на алерт нельзя отреагировать действием — это не алерт, а метрика на дашборде.
2.  **Symptom-based Alerting:** Алертите на симптомы (ошибки, задержки), а не на причины (CPU, RAM). Причины меняются, симптомы — вечны.
3.  **NoData — это алерт:** Всегда настраивайте алерты на отсутствие данных от критических систем.

### Ключевые флаги запуска

- `--cluster.listen-address`: Адрес для gossip (порт `9094`). Пустое значение отключает HA.
- `--cluster.peer`: Адреса других узлов кластера.
- `--data.retention`: Время хранения данных (по умолчанию `120h`).
- `--web.external-url`: Важен для корректных ссылок на UI в уведомлениях.
