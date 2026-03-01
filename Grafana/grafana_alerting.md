# Grafana: Оповещения (Unified Alerting)

> **Навигация:**
> - [Обзор Grafana](./grafana_overview.md)
> - [Провиженинг](./grafana_provisioning.md)
> - [Установка через Helm](./Installation/grafana_helm_installation.md) (Image Renderer)

## Определения

**Unified Alerting** — централизованная система оповещений Grafana, отделённая от дашбордов и работающая поверх различных источников данных.

**Текущая версия (февраль 2026):** Grafana 12.x

### Ключевые понятия

| Понятие | Описание |
| :--- | :--- |
| **Правило (Alert rule)** | Запросы, выражения, порог, интервал оценки, `for`, `NoData`, `Error`, метки, аннотации |
| **Группа правил** | Логическое объединение с единым интервалом оценки |
| **Контакт-пойнт** | Канал уведомлений (Email, Slack, Webhook, PagerDuty) |
| **Политика уведомлений** | Дерево маршрутизации по меткам (`group_by`, `group_wait`, `repeat_interval`) |
| **Глушения (Silences)** | Временное подавление по селекторам меток |
| **Окна тишины** | Подавление по расписанию (плановые работы) |
| **Шаблоны** | Go-шаблоны для форматирования сообщений |

### Состояния правил

| Состояние | Описание |
| :--- | :--- |
| **Normal / OK** | Условие не выполняется |
| **Pending** | Условие выполняется, но меньше времени `for` |
| **Alerting** | Условие выполняется дольше `for`, уведомления отправляются |
| **NoData** | Запросы не вернули данных (настраивается: `Alerting`, `NoData`, `OK`) |
| **Error** | Ошибка оценки правила (настраивается) |

## Основные концепции

### Жизненный цикл оповещения

1. **Оценка** — Grafana выполняет запросы по расписанию.
2. **Формирование событий** — условие применяется к каждой серии метрик.
3. **Маршрутизация** — события направляются к контакт-пойнтам.
4. **Группировка** — агрегация по меткам для уменьшения шума.
5. **Доставка** — уведомления доставляются по маршрутам.

### Image Renderer

**Image Renderer** — компонент для создания снимков графиков в уведомлениях.

- **Назначение:** Показывает тренд и контекст метрики в момент алерта.
- **Установка:** См. [Установка через Helm](./Installation/grafana_helm_installation.md#image-renderer).
- **Docker:** Отдельный контейнер `grafana-image-renderer`.

## Практические сценарии

### Сценарий 1: Настройка оповещений через Provisioning

Это основной подход для реализации Infrastructure as Code.

#### Пример правила

```yaml
# provisioning/alerting/api-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: api-alerts
    folder: Production
    interval: 1m
    rules:
      - uid: api_error_rate_high
        title: API error rate > 5%
        condition: B # Условие, которое триггерит алерт
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          service: api
          severity: critical
        annotations:
          summary: Высокая доля ошибок API
          runbook: Проверьте логи и зависимые сервисы
        data:
          - refId: A # Запрос PromQL
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'sum(rate(http_requests_total{job="api",status=~"5.."}[5m])) / sum(rate(http_requests_total{job="api"}[5m])) * 100'
              instant: false
              format: time_series
          - refId: B # Выражение Threshold
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [5] }
                  query: { params: [A] }
```

#### Пример контакт-пойнтов и политик

```yaml
# provisioning/alerting/contact-points.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-email
    receivers:
      - uid: team-devops-email-receiver
        type: email
        settings:
          addresses: devops@example.com

policies:
  - orgId: 1
    receiver: team-devops-email
    group_by: ["alertname", "service"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: team-devops-email
        object_matchers:
          - ["severity", "=", "critical"]
```

### Сценарий 2: Интеграция с системами эскалации

Для управления инцидентами Grafana интегрируется с **PagerDuty** или **Opsgenie**.

- **Разделение ответственности**: Grafana обнаруживает проблему и отправляет событие. Внешняя система управляет жизненным циклом инцидента: эскалацией, графиками дежурств, группировкой.
- **Пример эскалации**: Если дежурный инженер не реагирует на алерт в течение 5 минут, система автоматически передает его руководителю.

## Дополнительная информация

### Практические нюансы

| Нюанс | Рекомендация |
| :--- | :--- |
| **`for` и интервал оценки** | `for` ≥ 2–3 интервалов оценки |
| **`NoData` vs `Error`** | Для редких метрик: `NoData=OK`; для критичных: `NoData=Alerting` |
| **Метки** | Для маршрутизации и дедупликации |
| **Аннотации** | Для контекста (симптом, предположение, следующий шаг) |
| **Шумные метрики** | Используйте `reduce`/`avg_over_time` для пост-агрегации |

### Сравнение: Grafana Alerting vs Alertmanager

| Критерий | Grafana Alerting | Prometheus Alertmanager |
| :--- | :--- | :--- |
| **Настройка** | Визуальная + YAML | YAML |
| **Сложность правил** | Средняя (выражения, multi-dimension) | Продвинутая (агрегация, корреляция) |
| **Информативность** | Высокая (снимки графиков) | Низкая (текст) |
| **Обработка** | Группировка, глушение, политики | Дедупликация, группировка, inhibition |
| **Зависимости** | Не понимает | Inhibition rules для зависимых алертов |

### Рекомендуемая стратегия

| Сценарий | Решение |
| :--- | :--- |
| **80% случаев** | Grafana Alerting (пороговые алерты, визуальный контекст) |
| **20% случаев** | Alertmanager (сложные бизнес-алерты, inhibition) |

**Эти системы дополняют друг друга:** Alertmanager сообщает *что* "все плохо", Grafana присылает снимок, *как именно* "все плохо".

### Ссылки

- [Документация алертинга](https://grafana.com/docs/grafana/latest/alerting/)
- [Provisioning алертов](./grafana_provisioning.md)
- [Image Renderer](./Installation/grafana_helm_installation.md)
