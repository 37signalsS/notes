# Grafana: Оповещения (Unified Alerting)

> **Навигация:**
>
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

---

### Сценарий 3: Алерты для Kubernetes-приложений

Этот сценарий описывает настройку критически важных алертов для мониторинга здоровья приложения в Kubernetes.

#### Алерт на падение контейнера

```yaml
# provisioning/alerting/kubernetes-container-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: kubernetes-container-health
    folder: Kubernetes
    interval: 30s
    rules:
      - uid: container_restarted
        title: Container restarted
        condition: A
        for: 1m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.container }} в поде {{ $labels.pod }} перезапустился"
          description: "Причина: {{ $labels.reason }}, Exit code: {{ $labels.exit_code }}"
          runbook: "Проверьте логи: kubectl logs -n {{ $labels.namespace }} {{ $labels.pod }} -c {{ $labels.container }}"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'increase(kube_pod_container_status_restarts_total{namespace=~".+"}[5m]) > 0'
              instant: true
              format: table
```

#### Алерт на OOM Killed

```yaml
      - uid: container_oom_killed
        title: Container OOM Killed
        condition: A
        for: 0m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.container }} убит по OOM в поде {{ $labels.pod }}"
          description: "Namespace: {{ $labels.namespace }}, Причина: OOMKilled"
          runbook: "Увеличьте memory limits или оптимизируйте потребление памяти"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1'
              instant: true
              format: table
```

#### Алерт на недоступность реплик

```yaml
      - uid: deployment_replicas_unavailable
        title: Deployment replicas unavailable
        condition: B
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: warning
        annotations:
          summary: "Недоступны реплики в deployment {{ $labels.deployment }}"
          description: "Доступно: {{ $value }}%, Ожидалось: 100%"
          runbook: "Проверьте события: kubectl describe deployment -n {{ $labels.namespace }} {{ $labels.deployment }}"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_deployment_status_replicas_available{namespace=~".+"} / kube_deployment_status_replicas{namespace=~".+"} * 100'
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: lt, params: [90] }
                  query: { params: [A] }
```

#### Алерт на высокое потребление CPU

```yaml
      - uid: container_cpu_high
        title: Container CPU usage high
        condition: B
        for: 10m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: warning
        annotations:
          summary: "Высокое потребление CPU контейнером {{ $labels.container }}"
          description: "Потребление: {{ $value }}% от limits"
          runbook: "Проанализируйте нагрузку на приложение"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: |
                rate(container_cpu_usage_seconds_total{namespace=~".+", container!=""}[5m])
                /
                kube_pod_container_resource_limits{resource="cpu", namespace=~".+"}
                * 100
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [80] }
                  query: { params: [A] }
```

#### Алерт на высокое потребление памяти

```yaml
      - uid: container_memory_high
        title: Container Memory usage high
        condition: B
        for: 10m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: warning
        annotations:
          summary: "Высокое потребление памяти контейнером {{ $labels.container }}"
          description: "Потребление: {{ $value }}% от limits"
          runbook: "Проверьте на наличие утечек памяти"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: |
                container_memory_usage_bytes{namespace=~".+", container!=""}
                /
                kube_pod_container_resource_limits{resource="memory", namespace=~".+"}
                * 100
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [85] }
                  query: { params: [A] }
```

---

### Сценарий 4: Настройка уведомлений в Telegram

Telegram — популярный канал для оперативных уведомлений благодаря мобильности и поддержке форматирования.

#### Контакт-пойнт для Telegram

```yaml
# provisioning/alerting/contact-points-telegram.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-telegram
    receivers:
      - uid: telegram-receiver
        type: telegram
        settings:
          botToken: "<YOUR_BOT_TOKEN>"  # Получите от @BotFather
          chatId: "<YOUR_CHAT_ID>"      # ID чата (канал или группа)
          message: |
            {{ define "telegram.default.message" }}
            🚨 *{{ .CommonAnnotations.summary }}*
            
            {{ if .CommonAnnotations.description }}
            {{ .CommonAnnotations.description }}
            {{ end }}
            
            *Детали:*
            - Алерт: {{ .CommonLabels.alertname }}
            - Сервис: {{ .CommonLabels.service }}
            - Критичность: {{ .CommonLabels.severity }}
            - Время: {{ .StartsAt.Format "2006-01-02 15:04:05" }}
            
            {{ if .CommonAnnotations.runbook }}
            *Runbook:* {{ .CommonAnnotations.runbook }}
            {{ end }}
            
            [Перейти в Grafana]({{ .ExternalURL }})
            {{ end }}
```

#### Политики уведомлений для Telegram

```yaml
policies:
  - orgId: 1
    receiver: team-devops-telegram
    group_by: ["alertname", "namespace", "service"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: team-devops-telegram
        object_matchers:
          - ["severity", "=", "critical"]
        group_wait: 10s  # Быстрая доставка для критичных алертов
        repeat_interval: 1h
      - receiver: team-devops-telegram
        object_matchers:
          - ["severity", "=", "warning"]
        group_wait: 1m
        repeat_interval: 4h
```

> **Важно:** Для работы Telegram-уведомлений требуется Grafana 9.0+. В более ранних версиях используйте webhook с Telegram Bot API.

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
