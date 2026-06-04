# Обзор Grafana Alerting

## Определения

**Unified Alerting** — централизованная система оповещений Grafana, отделённая от дашбордов и работающая поверх различных источников данных (Prometheus, Loki, MySQL, PostgreSQL и др.).

**Текущая версия (февраль 2026):** Grafana 12.x

## Базовые концепции

### Ключевые понятия

| Понятие | Описание |
| :--- | :--- |
| **Правило (Alert rule)** | Запросы, выражения, порог, интервал оценки, `for`, `NoData`, `Error`, метки, аннотации |
| **Группа правил** | Логическое объединение с единым интервалом оценки |
| **Контакт-пойнт** | Канал уведомлений (Email, Slack, Webhook, PagerDuty, Telegram) |
| **Политика уведомлений** | Дерево маршрутизации по меткам (`group_by`, `group_wait`, `repeat_interval`) |
| **Глушения (Silences)** | Временное подавление по селекторам меток |
| **Окна тишины** | Подавление по расписанию (плановые работы) |
| **Шаблоны** | Go-шаблоны для форматирования сообщений |

### Состояния правил

| Состояние | Описание | Когда переходит |
| :--- | :--- | :--- |
| **Normal / OK** | Условие не выполняется | После срабатывания `for` без нарушений |
| **Pending** | Условие выполняется, но меньше времени `for` | При первом нарушении порога |
| **Alerting** | Условие выполняется дольше `for` | После истечения `for`, уведомления отправляются |
| **NoData** | Запросы не вернули данных | Настройка: `Alerting`, `NoData`, `OK` |
| **Error** | Ошибка оценки правила | Настройка: `Alerting`, `OK` |

### Диаграмма состояний

```
Normal → Pending → Alerting → Normal
           ↓          ↓
        NoData     Error
```

### Жизненный цикл оповещения

1. **Оценка** — Grafana выполняет запросы по расписанию (интервал оценки).
2. **Формирование событий** — условие применяется к каждой серии метрик.
3. **Переход состояния** — `Normal` → `Pending` → `Alerting`.
4. **Маршрутизация** — события направляются к контакт-пойнтам по меткам.
5. **Группировка** — агрегация по меткам для уменьшения шума.
6. **Доставка** — уведомления доставляются по маршрутам.

### Рендеринг изображений (Image Renderer)

**Image Renderer** — компонент для создания снимков графиков в уведомлениях.

- **Назначение:** Показывает тренд и контекст метрики в момент алерта.
- **Установка:** [Установка через Helm](../Installation/grafana_helm_installation.md) или отдельный контейнер `grafana-image-renderer`.
- **Требования:** Headless-браузер (Chromium), 512MB+ RAM (Random Access Memory).

## Практические сценарии

### Пример: Создание правила алертинга

**Шаг 1: Выбор метрики**

```promql
sum(rate(http_requests_total{job="api",status=~"5.."}[5m])) 
/ 
sum(rate(http_requests_total{job="api"}[5m])) * 100
```

**Шаг 2: Настройка параметров**

| Параметр | Значение |
| :--- | :--- |
| Интервал оценки | 1m |
| `for` | 5m |
| `NoData` | NoData |
| `Error` | Error |

**Шаг 3: Метки для маршрутизации**

```yaml
labels:
  service: api
  severity: critical
  team: backend
```

**Шаг 4: Аннотации с контекстом**

```yaml
annotations:
  summary: "Высокая доля ошибок API (Application Programming Interface): {{ $value | humanizePercentage }}"
  description: "Доля 5xx ошибок превышает 5% в течение 5 минут"
  runbook: "https://wiki.example.com/runbooks/api-error-rate"
```

### Пример: Настройка контакт-пойнта

**Email:**

```yaml
receivers:
  - name: team-devops
    email_configs:
      - to: devops@example.com
        send_resolved: true
```

**Telegram:**

```yaml
receivers:
  - name: telegram-alerts
    telegram_configs:
      - bot_token: <token>
        chat_id: <chat_id>
        send_resolved: true
```

### Пример: Маршрутизация по критичности

```yaml
route:
  receiver: default
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - receiver: critical-channel
      match:
        severity: critical
    - receiver: warning-channel
      match:
        severity: warning
```

### Пример: Глушение на время работ

```yaml
silences:
  - matchers:
      - name: service
        value: api
        isRegex: false
    startsAt: "2026-03-31T10:00:00Z"
    endsAt: "2026-03-31T12:00:00Z"
    createdBy: "admin"
    comment: "Плановые работы на API"
```

## Дополнительная информация

**См. также:**

- [Provisioning алертов](./provisioning.md) — настройка правил и политик через YAML
- [Best practices](./best_practices.md) — рекомендации и сравнение с Alertmanager
- [Установка Grafana](../Installation/grafana_helm_installation.md) — базовое развёртывание системы
