# Интеграция с системами эскалации

## Определения

**Системы эскалации** — специализированные платформы (PagerDuty, Opsgenie) для управления инцидентами, которые обеспечивают организацию дежурств, настройку графиков, автоматическую эскалацию уведомлений и отслеживание жизненного цикла инцидентов.

**Grafana OnCall** — внутреннее решение Grafana для управления дежурствами и процессами эскалации.

**Текущая версия (февраль 2026):** Grafana 12.x

> **Важно:** Версия Grafana OnCall для локальной установки (self-hosted) не получает обновлений с весны 2026 года. Для новых инсталляций рекомендуется использовать PagerDuty или Opsgenie.

## Основные концепции

### Разделение ответственности

| Система | Сфера ответственности |
| :--- | :--- |
| **Grafana** | Обнаружение отклонений, генерация события и отправка уведомления |
| **Внешняя система** | Управление инцидентом: эскалация при отсутствии реакции, графики дежурств инженеров, группировка схожих событий и трекирование |

### Сравнение систем эскалации

| Критерий | PagerDuty | Opsgenie | Grafana OnCall |
| :--- | :--- | :--- | :--- |
| **Интеграция с Grafana** | Нативная (через контакт-пойнт) | Нативная (через контакт-пойнт) | Нативная (через плагин) |
| **Графики дежурств** | Продвинутые возможности | Продвинутые возможности | Базовый функционал |
| **Эскалация** | Многоуровневые правила | Многоуровневые правила | Базовые правила |
| **Трекирование инцидентов** | Полнофункциональное | Полнофункциональное | Ограниченное |
| **Стоимость** | Высокая (проприетарное ПО) | Средняя (проприетарное ПО) | Бесплатно (self-hosted версия) |
| **Статус поддержки** | Активно развивается | Активно развивается | Не обновляется |

### Механизм эскалации

Эскалация — это процесс передачи ответственности за инцидент на следующий уровень, если на текущем уровне реакция отсутствует в течение заданного времени.

**Пример уровней эскалации:**

1. **Уровень 1:** Дежурный инженер (уведомления: мобильное приложение + Email).
2. **Уровень 2:** Ведущий инженер (уведомления: SMS (Short Message Service) + голосовой звонок).
3. **Уровень 3:** Руководитель подразделения (уведомление: голосовой звонок).

## Практические сценарии

### Настройка PagerDuty в Grafana

**Шаг 1: Получение ключа интеграции**

1. В интерфейсе PagerDuty создайте новый сервис.
2. Добавьте интеграцию с типом «Grafana».
3. Скопируйте **Integration Key**.

**Шаг 2: Создание контакт-пойнта**

Для декларативной настройки (Provisioning) используйте YAML-файл (YAML Ain't Markup Language):

```yaml
# provisioning/alerting/contact-points-pagerduty.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: pagerduty-critical
    receivers:
      - uid: pagerduty-receiver # UID (Unique Identifier)
        type: pagerduty
        settings:
          integrationKey: "<YOUR_INTEGRATION_KEY>"
          severity: critical
          class: infrastructure
          component: grafana
          group: production
          summary: "{{ .CommonAnnotations.summary }}"
```

**Шаг 3: Настройка политики уведомлений**

```yaml
policies:
  - orgId: 1
    receiver: pagerduty-critical
    group_by: ["alertname", "service"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 1h
    routes:
      - receiver: pagerduty-critical
        object_matchers:
          - ["severity", "=", "critical"]
```

### Настройка Opsgenie в Grafana

**Шаг 1: Получение API (Application Programming Interface) ключа**

1. В Opsgenie создайте или выберите команду.
2. Добавьте интеграцию типа «Grafana».
3. Скопируйте **API Key**.

**Шаг 2: Создание контакт-пойнта**

```yaml
# provisioning/alerting/contact-points-opsgenie.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: opsgenie-team
    receivers:
      - uid: opsgenie-receiver
        type: opsgenie
        settings:
          apiKey: "<YOUR_API_KEY>"
          apiURL: "https://api.opsgenie.com/v2/alerts"
          message: "{{ .CommonAnnotations.summary }}"
          description: "{{ .CommonAnnotations.description }}"
          priority: "{{ if eq .CommonLabels.severity \"critical\" }}P1{{ else }}P3{{ end }}"
          responders:
            - type: team
              name: DevOps
```

### Настройка многоуровневой эскалации

Алгоритм работы:

1. **Во внешней системе** (PagerDuty/Opsgenie) настраиваются временные интервалы передачи инцидента между уровнями (например, 0–5 мин, 5–15 мин, 15+ мин).
2. **В Grafana** настраивается маршрутизация оповещений в соответствующий контакт-пойнт на основе меток (labels).

**Пример маршрутизации в Grafana:**

```yaml
policies:
  - orgId: 1
    receiver: default
    group_by: ["alertname", "service"]
    routes:
      - receiver: pagerduty-critical
        object_matchers:
          - ["severity", "=", "critical"]
        group_wait: 10s
        repeat_interval: 1h
      - receiver: opsgenie-team
        object_matchers:
          - ["severity", "=", "warning"]
        group_wait: 1m
        repeat_interval: 4h
```

## Дополнительная информация

**См. также:**

- [Основные концепции Grafana Alerting](./concepts.md) — терминология и жизненный цикл оповещений
- [Интеграция с Telegram](./telegram_integration.md) — настройка уведомлений в мессенджер
- [Provisioning алертов](./provisioning.md) — декларативное управление ресурсами через конфигурационные файлы
