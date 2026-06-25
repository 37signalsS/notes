# Alertmanager

## Определение

**Alertmanager** — компонент стека Prometheus, отвечающий за обработку оповещений: дедупликация, группировка, подавление (silencing/inhibition) и маршрутизация в каналы уведомлений (Email, Slack, PagerDuty, Webhook).

> **См. также:** [Обзор Prometheus](./overview.md), [Правила алертинга](./rules.md)

## Основные концепции

### Архитектура: Prometheus — Alertmanager

| Компонент | Роль |
|---|---|
| **Prometheus** | Вычисляет [правила алертинга](./rules.md), при срабатывании отправляет webhook в Alertmanager |
| **Alertmanager** | Получает алерты, обрабатывает (группировка, подавление, маршрутизация), отправляет уведомления получателям |

Один Alertmanager может обслуживать несколько экземпляров Prometheus.

### Конвейер обработки оповещений

1. **Группировка (Grouping)** — объединение схожих алертов в одно уведомление по меткам (`group_by`).
2. **Подавление (Inhibition)** — автоматическое заглушение алертов при наличии более общих (например, `DataCenterDown` подавляет `ServerDown`).
3. **Замалчивание (Silencing)** — ручное отключение уведомлений на период Maintenance-работ.
4. **Маршрутизация (Routing)** — направление алертов разным командам через метки (`match`/`match_re`).
5. **Троттлинг** — задержка первой отправки (`group_wait`) и повторные уведомления (`repeat_interval`).
6. **Отправка (Notification)** — доставка в Email, Slack, PagerDuty, Webhook.

### Конфигурация — alertmanager.yml

#### Блок global

Глобальные параметры по умолчанию:

| Параметр | По умолчанию | Описание |
|---|---|---|
| `resolve_timeout` | `5m` | Время до пометки алерта как resolved |
| `smtp_*` | — | Настройки SMTP для email-уведомлений |

#### Блок route

Древовидная маршрутизация оповещений:

| Параметр | По умолчанию | Описание |
|---|---|---|
| `receiver` | — | Получатель по умолчанию |
| `group_by` | `['...']` | Метки для группировки алертов |
| `continue` | `false` | Продолжать обработку при совпадении |
| `match` / `match_re` | — | Точное/regex-совпадение по меткам |
| `group_wait` | — | Задержка перед первой отправкой |
| `group_interval` | — | Интервал между уведомлениями одной группы |
| `repeat_interval` | — | Интервал повторных уведомлений |
| `routes` | — | Вложенные маршруты |

```yaml
route:
  receiver: 'default-receiver'
  group_by: [cluster, alertname]
  routes:
  - receiver: 'db-team'
    match_re:
      service: mysql|postgres
  - receiver: 'frontend-team'
    match:
      team: frontend
```

#### Блок receivers

Именованные получатели (Email, Slack, PagerDuty, Webhook и другие).

#### Блок inhibit_rules

Подавление алертов по условиям:

| Параметр | Описание |
|---|---|
| `source_match` / `source_match_re` | Метки алерта-источника (подавляющего) |
| `target_match` / `target_match_re` | Метки подавляемого алерта |
| `equal` | Метки, которые должны совпадать в обоих алертах |

### Высокая доступность — HA

#### Архитектура HA

Alertmanager использует **gossip-протокол** для кластеризации. Экземпляры обмениваются данными об алертах, замалчиваниях (silences) и уведомлениях.

**Ключевое свойство:** дедупликация — при получении одинакового алерта от нескольких экземпляров Prometheus уведомление отправляется один раз.

#### Настройка кластера

| Метод | Описание |
|---|---|
| **Вручную** | Запуск двух и более экземпляров с `--cluster.peer=<peer_IP>:9094` (порт gossip — `9094`) |
| **Kubernetes** | Helm-чарт `kube-prometheus-stack` с `replicaCount: 3` — автоматическое обнаружение пиров (peer discovery) |

### Веб-интерфейс и ключи запуска

**Веб-интерфейс:** порт `9093` — разделы Alerts, Groups, Silences, Status (включая состояние кластера).

| Ключ | По умолчанию | Описание |
|---|---|---|
| `--config.file` | `alertmanager.yml` | Путь к конфигурации |
| `--storage.path` | `data/` | Путь хранения данных (silences и другие) |
| `--data.retention" | `120h` | Срок хранения данных |
| `--web.listen-address` | `:9093` | Адрес UI и API |
| `--cluster.listen-address` | `0.0.0.0:9094` | Адрес gossip (пустое значение отключает HA) |
| `--cluster.peer` | — | Адреса пиров HA-кластера |

## Практические сценарии

### Пример конфигурации — alertmanager.yml

```yaml
global:
  smtp_smarthost: smtp.yandex.ru:465
  smtp_from: 'alerts@edu-prom.example.com'
  smtp_auth_username: 'alerts@edu-prom.example.com'
  smtp_auth_password: '<Password>'

route:
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 1h
  receiver: team-monitoring

  routes:
  - match:
      service: prom
    receiver: team-ops
  - match:
      severity: warnings|error|critical
    receiver: team-monitoring

inhibit_rules:
- source_match:
    severity: 'critical'
    alertname: PrometheusConfigurationReload
  target_match:
    severity: 'critical'

receivers:
- name: 'team-ops'
  email_configs:
    - to: 'ops-team@example.com'
      send_resolved: true
      require_tls: false
- name: 'team-monitoring'
  email_configs:
    - to: 'monitoring-team@example.com'
      send_resolved: true
- name: 'webhook'
  webhook_configs:
    - url: 'https://hooks.example.com/alert'
      send_resolved: true
```

**Логика маршрутизации:**

- `service: prom` → `team-ops`
- `severity: warnings|error|critical` → `team-monitoring`
- Активный `PrometheusConfigurationReload` подавляет алерты с `severity: critical`

> Для отладки маршрутизации: [официальный редактор](https://www.prometheus.io/webtools/alerting/routing-tree-editor/).

### Перезагрузка и тестирование

```bash
systemctl reload alertmanager.service
```

**Сценарии тестирования:**

| Действие | Ожидаемый результат |
|---|---|
| Сломать конфигурацию [Prometheus](./configuration.md) | Алерт об ошибке конфигурации |
| Остановить `node_exporter` на нескольких хостах | Уведомление подавлено `inhibit_rules`, пока активен алерт конфигурации |
| Исправить конфигурацию Prometheus | Уведомление о решении и алерты экспортеров |

### Развёртывание в Kubernetes через манифесты

**Паттерн безопасного управления конфигурацией:**

| Шаг | Описание |
|---|---|
| 1. Шаблон ConfigMap | `alertmanager.yml` с плейсхолдерами для секретов (хранится в Git) |
| 2. Kubernetes Secret | Секреты (токены, пароли) в отдельном объекте `Secret` |
| 3. Init Container | `busybox` через `sed` или `envsubst` подставляет секреты и записывает в `emptyDir` |
| 4. Основной контейнер | Монтирует готовый `alertmanager.yml` из `emptyDir` |

> Подробное руководство с манифестами (включая Telegram): [Alertmanager + Karma в Kubernetes](./kubernetes/examples/alertmanager-karma-manifests-tutorial/intro.md)

## Дополнительная информация

- **Руководство по установке**: Инструкции по ручной установке Alertmanager находятся в заметке [Установка Alertmanager](./installation/alertmanager_installation.md).
