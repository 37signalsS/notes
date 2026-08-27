# Интеграция с системами эскалации — Incident Management

## Определения

**Системы эскалации (Escalation Systems)** — платформы для управления инцидентами (PagerDuty, Opsgenie, Splunk On-Call, GoAlert), обеспечивающие автоматизацию дежурств (on-call), многоуровневое оповещение и контроль жизненного цикла критических событий.

**Incident Response & Management (IRM)** — комплексный подход к обработке инцидентов, включающий обнаружение, оповещение, совместную работу инженеров и последующий анализ (post-mortem).

**Grafana Cloud IRM** — современный стек инструментов Grafana Labs для управления инцидентами, включающий:
*   **Grafana OnCall:** Централизованное управление дежурствами, эскалациями и расписаниями (приоритетное решение в 2026 году).
*   **Grafana Incident:** Инструмент для координации действий во время активного сбоя (автоматическое создание Slack-каналов, Zoom-конференций и ведение таймлайна инцидента).

**Grafana OnCall OSS** — Open-source версия, официально **архивирована 24 марта 2026 года**. Рекомендуется миграция на Grafana Cloud IRM или использование GoAlert.

**On-call schedule (График дежурств)** — ротационная таблица, определяющая, кто является текущим дежурным в заданный интервал времени. В IRM-системе график привязан к эскалационной политике и может содержать несколько уровней (L1, L2, L3).

**Escalation policy (Эскалационная политика)** — набор правил в IRM-системе, которые определяют последовательность оповещения: если дежурный L1 не ответил за N минут, автоматически вызывается L2, затем L3 и т.д.

**Deduplication key (Ключ дедупликации)** — уникальный идентификатор, по которому IRM-система определяет, является ли входящее событие новым инцидентом или продолжением уже открытого. В Grafana ключ обычно формируется из меток `alertname`, `cluster`, `service`.

**Auto-resolve (Авторазрешение)** — механизм, при котором IRM-система автоматически закрывает инцидент при получении сигнала восстановления (resolved) от Grafana. Настраивается отдельно в контакт-пойнте (`autoResolve: true`).

## Базовые концепции

### Разделение ответственности

| Система | Сфера ответственности |
| :--- | :--- |
| **Grafana** | Мониторинг, оценка правил, генерация алерта, обогащение контекстом (Runbooks, Dashboard links). |
| **IRM (PagerDuty/OnCall)** | Маршрутизация по графикам дежурств, эскалация при отсутствии реакции, агрегация алертов в инциденты. |

### Архитектура интеграции

Grafana взаимодействует с IRM-системами через два механизма:

1.  **Нативные интеграции:** Grafana имеет встроенные контакт-пойнты для PagerDuty, Opsgenie и Splunk On-Call (VictorOps). В этом случае Grafana напрямую отправляет событие в API IRM-системы, используя ключ интеграции. Преимущество — автоматическая дедупликация, тишины и разрешение инцидентов на стороне IRM.
2.  **Webhook:** Универсальный механизм для любых IRM-систем (GoAlert, Custom). Grafana отправляет HTTP POST с JSON-телом. Получатель отвечает за дедупликацию, эскалацию и закрытие инцидента. Преимущество — гибкость формата и полный контроль над обработкой.

**Поток события:**
1.  Алерт переходит в `Alerting` в Grafana.
2.  Alertmanager применяет политику маршрутизации и выбирает контакт-пойнт.
3.  Grafana формирует HTTP-запрос к IRM-системе (нативный или webhook).
4.  IRM создаёт/обновляет инцидент, направляет уведомление дежурному.
5.  При восстановлении Grafana отправляет сигнал `[RESOLVED]`, IRM закрывает инцидент (при включённом `autoResolve`).

### Сравнение систем управления инцидентами (2026)

| Критерий | PagerDuty | Opsgenie | Splunk On-Call | GoAlert (OSS) | Grafana Cloud IRM |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Тип** | SaaS | SaaS | SaaS | Самостоятельная | SaaS |
| **Эскалация** | Экстремальная | Высокая | Высокая | Средняя | Средняя |
| **Интеграция** | Нативная | Нативная | VictorOps | Webhook | Нативная |
| **Статус 2026** | Лидер рынка | Стабильно | Enterprise | Рекомендованный OSS | Приоритет Grafana |
| **Ограничения API** | Rate limit по тарифу | Rate limit по тарифу | Rate limit по тарифу | Self-hosted, без ограничений | Зависит от Cloud-плана |

### Жизненный цикл инцидента

1.  **Обнаружение (Detect):** Grafana фиксирует нарушение порогового значения и отправляет сигнал в IRM-систему.
2.  **Оповещение (Notify):** IRM определяет текущего дежурного согласно графику и отправляет уведомление (Push, SMS, звонок).
3.  **Квитирование (Acknowledge):** Инженер подтверждает получение через приложение или мессенджер. Таймер эскалации останавливается.
4.  **Анализ и исправление (Fix):** Инженер использует ссылки на Runbook и Дашборд, переданные в теле алерта, для диагностики.
5.  **Разрешение (Resolve):** Grafana отправляет сигнал восстановления (`[RESOLVED]`), IRM автоматически закрывает инцидент.

## Предварительные требования

*   **Версия Grafana:** 12.x или 13.x (проверено август 2026).
*   **Аккаунт IRM:** зарегистрированная инстанция PagerDuty, Opsgenie, Splunk On-Call или GoAlert с правами на создание интеграций.
*   **Сеть:** исходящий HTTPS-трафик из Grafana к эндпоинтам IRM:
    *   PagerDuty: `events.pagerduty.com` (порт 443)
    *   Opsgenie: `api.opsgenie.com` (порт 443)
    *   Splunk On-Call: `alert.victorops.com` (порт 443)
    *   GoAlert: ваш домен (порт 443)
*   **Ключи интеграции:** созданы в IRM-системе (Integration Key для PagerDuty, API Key для Opsgenie, Routing Key для VictorOps, токен для GoAlert).
*   **Права в Grafana:** роль `Admin` или `Editor` с правами `Alerting > Edit rules` и `Alerting > Edit notification policies`.

## Практические сценарии

### Настройка PagerDuty через провиженинг

```yaml
# provisioning/alerting/contact-points-pagerduty.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: pagerduty-critical
    receivers:
      - uid: pd-critical-receiver
        type: pagerduty
        settings:
          # Ключ интеграции из PagerDuty (Events API v2)
          integrationKey: ${PAGERDUTY_INTEGRATION_KEY}
          severity: critical
          class: infrastructure
          component: kubernetes-cluster
          group: backend
          summary: "Критический сбой: {{ .CommonAnnotations.summary }}"
          # Автоматическое разрешение инцидента в PD при восстановлении в Grafana
          autoResolve: true
```

### Настройка PagerDuty через UI

1.  В PagerDuty создайте **Service** (например, `Grafana-Prod`) и выберите Integration Type: **Events API v2**. Скопируйте **Integration Key**.
2.  В Grafana откройте **Alerting → Contact points → New contact point**.
3.  Выберите тип **PagerDuty**.
4.  В поле **Integration key** вставьте ключ из PagerDuty.
5.  Заполните опциональные поля: `Severity` (например, `critical`), `Class`, `Component`, `Group`.
6.  Включите **Auto-resolve** (автоматически закрывать инцидент при resolved).
7.  Нажмите **Test** — в PagerDuty должно появиться тестовое событие.
8.  Назначьте контакт-пойнт политике уведомлений (Alerting → Notification policies).

### Настройка Opsgenie через провиженинг

```yaml
# provisioning/alerting/contact-points-opsgenie.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: opsgenie-critical
    receivers:
      - uid: opsgenie-critical-receiver
        type: opsgenie
        settings:
          apiKey: ${OPSGENIE_API_KEY}
          autoResolve: true
          overridePriority: true
          priority: P1
          responders:
            - id: "USER_ID"
              type: "user"
          note: "Создано через Grafana: {{ .CommonAnnotations.summary }}"
```

### Настройка Splunk On-Call (VictorOps)

Для интеграции используется тип `victorops`. Routing Key позволяет направлять алерты конкретным командам.

```yaml
# provisioning/alerting/contact-points-victorops.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: splunk-oncall-devops
    receivers:
      - uid: vo-devops-receiver
        type: victorops
        settings:
          url: "https://alert.victorops.com/integrations/generic/20131114/alert/${VICTOROPS_API_KEY}/devops"
          autoResolve: true
```

### Настройка GoAlert через Webhook

GoAlert — основная open-source альтернатива для управления дежурствами в 2026 году.

```yaml
# provisioning/alerting/contact-points-goalert.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: goalert-infra
    receivers:
      - uid: goalert-receiver
        type: webhook
        settings:
          url: "https://goalert.example.com/api/v2/webhooks/grafana?token=${GOALERT_TOKEN}"
          httpMethod: POST
```

**Формат webhook-запроса (JSON body), отправляемого в GoAlert:**

```json
{
  "id": "grafana-uid",
  "alertRule": "CPUHigh-prod",
  "labels": {
    "severity": "critical",
    "cluster": "prod"
  },
  "state": "alerting",
  "message": "High CPU on node-01",
  "description": "CPU > 90% for 5m",
  "runbook": "https://wiki.example.com/cpu",
  "dashboard": "https://grafana.example.com/d/api-overview"
}
```

GoAlert ожидает поля `id` (для дедупликации) и `message`. При получении состояния `resolved` GoAlert автоматически закрывает инцидент, если включён соответствующий режим в вебхуке.

### Многоканальная доставка

Используйте дерево политик уведомлений для отправки одного алерта в несколько систем:

```yaml
# provisioning/alerting/policies/multi-channel-routing.yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: "default-slack"
    group_by: ["alertname", "cluster"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: "critical-pagerduty"
        object_matchers:
          - ["severity", "=", "critical"]
        continue: true
      - receiver: "team-slack"
        object_matchers:
          - ["team", "=~", "backend|frontend"]
```

При `continue: true` алерт с `severity=critical` и `team=backend` попадёт и в PagerDuty, и в Slack. Без `continue` — только в самую глубокую совпавшую политику (PagerDuty).

### Обогащение алертов контекстом (Enrichment)

Для минимизации времени реакции (MTTR) алерты должны содержать ссылки на документацию и инструменты диагностики.

```yaml
# Пример аннотаций в YAML-описании правила (Rule)
annotations:
  summary: "Высокая задержка API на {{ .Labels.instance }}"
  runbook_url: "https://wiki.example.com/runbooks/api-latency"
  dashboard_url: "https://grafana.example.com/d/api-overview?var-cluster={{ .Labels.cluster }}"
```

### Периоды тишины (Mute Timings)

Позволяют подавлять уведомления и эскалацию в нерабочее время (для некритичных систем) или во время плановых работ.

```yaml
# provisioning/alerting/mute-timings.yaml
apiVersion: 1

muteTimings:
  - name: maintenance-weekends
    timeIntervals:
      - weekdays: ["saturday", "sunday"]
        times:
          - start: "00:00"
            end: "23:59"
```

## Безопасность и секреты

1.  **Интерполяция переменных:** Всегда используйте `${VARIABLE_NAME}` в конфигурации Grafana. Никогда не фиксируйте API-ключи в Git-репозиториях.
2.  **Принцип минимизации привилегий:** В PagerDuty/Opsgenie используйте ключи с ограниченными правами (только на создание событий), а не глобальные токены администратора.
3.  **Сетевая изоляция:** Убедитесь, что разрешен исходящий HTTPS-трафик к эндпоинтам `events.pagerduty.com`, `api.opsgenie.com` или `alert.victorops.com`.
4.  **TLS и верификация:** Для webhook-интеграций используйте HTTPS с валидным сертификатом. В корпоративных сетях с самоподписанными сертификатами настройте `skip_verify` в контакт-пойнте или импортируйте CA в trust store Grafana.
5.  **Ротация секретов:** Планируйте регулярную ротацию ключей интеграции (например, раз в 90 дней). При смене ключа обновите переменную окружения и выполните Hot Reload.
6.  **IP-allowlisting:** На стороне IRM-системы ограничьте прием запросов только IP-адресами инстансов Grafana (при статичных IP). В GoAlert/PagerDuty это настраивается в фаерволе сервиса.

## Проверка корректности (Validation)

*   **Тест контакт-пойнта:** на странице Contact point нажмите **Test** — должно прийти тестовое событие/инцидент в IRM-систему.
*   **Список правил:** `Alerting → Alert rules` показывает состояние (`Normal`/`Pending`/`Alerting`) и время последней оценки.
*   **State history:** `Alerting → History` (или «Show state history» внутри правила) — видны все переходы состояний, **включая те, что подавлены тишиной/mute**.
*   **Интерфейс IRM:** проверьте, что в PagerDuty/Opsgenie появился инцидент с корректным `summary`, `severity` и ссылками на Grafana. Убедитесь, что квитирование (Acknowledge) и разрешение (Resolve) работают в обе стороны.
*   **Доставка:** во время `Alerting` проверьте канал (PagerDuty/Opsgenie/Slack) и `Alerting → Silences/Notifications` (в Cloud/Enterprise — лог доставки).

## Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Инцидент не создаётся в IRM | Неверный ключ интеграции / блокировка сетью | Проверьте ключ в конфигурации контакт-пойнта; выполните `curl` из хоста Grafana к эндпоинту IRM |
| Инцидент создаётся, но без severity | В контакт-пойнте не задано поле `severity` | Задайте `severity` в `settings` или в labels правила |
| Дублирующиеся инциденты | Неверный dedup key или его отсутствие | Убедитесь, что `integrationKey` статичен; проверьте `uid` ресивера |
| Инцидент не закрывается при resolved | `autoResolve: false` или отсутствие поддержки в IRM | Включите `autoResolve: true`; в GoAlert проверьте настройки вебхука |
| Уведомление не доходит до дежурного | Ошибка в графике дежурств / отключённый канал | Проверьте on-call schedule в IRM; проверьте escalation policy |
| `400 Bad Request` от PagerDuty | Невалидный JSON или превышен лимит длины | Проверьте шаблон сообщения; PagerDuty ограничивает `summary` 1024 символами |
| Webhook не принимается GoAlert | Неверный URL / токен / метод | Проверьте URL вебхука в GoAlert; убедитесь, что Grafana отправляет POST |

## Граничные случаи (Edge Cases)

*   **Дребезг инцидентов (Flapping):** метрика колеблется у порога → каскад `Alerting`/`Resolved` в IRM. Лечится параметром `for` в Grafana и `keep_firing_for`. Некоторые IRM-системы (PagerDuty) имеют встроенную дедупликацию по dedup key, но не склеивают каскад fire/resolve — это остаётся ответственностью Grafana.
*   **Взрыв экземпляров:** многомерный запрос без Reduce порождает сотни инцидентов в IRM → шум и нагрузку. Используйте `group_by`, осмысленный Reduce и не создавайте алерт на высокой кардинальности без необходимости.
*   **Наследование в дереве политик:** дочерняя политика наследует контакт-пойнт и тайминги родителя — неочевидное поведение при каскадных политиках.
*   **Временные зоны:** Mute Timings и Time Intervals учитывают `location`; несовпадение с локальным временем команды — частый источник «почему ночью пришло уведомление».
*   **Несколько Alertmanager:** каждый Alertmanager хранит **собственные** независимые ресурсы (contact points, policies, silences) — они не шерятся между собой.
*   **Auto-resolve и инциденты вручную:** если инженер вручную закрыл инцидент в IRM, а алерт в Grafana ещё `Alerting`, следующее событие может переоткрыть инцидент. Согласуйте поведение с командой.
*   **Ограничения API IRM:** PagerDuty и Opsgenie имеют rate limits (зависит от тарифного плана). При всплеске сотен алертов возможен `429 Too Many Requests`. На стороне Grafana это выглядит как ошибка доставки. Используйте группировку (`group_by`) и `group_interval` для снижения частоты.
*   **Webhook и время ожидания:** Grafana ожидает ответ от webhook-эндпоинта в течение таймаута (по умолчанию ~30s). Если IRM-система отвечает медленно, доставка упадёт с `context deadline exceeded`. Настройте асинхронную обработку в GoAlert или увеличьте таймаут на стороне Grafana, если возможно.

## Лучшие практики и очистка (Best Practices & Cleanup)

*   **Используйте отдельные контакт-пойнты по критичности:** critical → PagerDuty/Opsgenie (звонок), warning → Slack/Telegram, info → лог.
*   **Всегда включайте `autoResolve`** для нативных интеграций, чтобы не накапливать «призрачные» инциденты в IRM.
*   **Формируйте стабильный dedup key:** используйте комбинацию `alertname` + `cluster` + `service`. Не включайте в ключ быстро меняющиеся метки (`instance`, `pod`), иначе каждый всплеск создаст новый инцидент.
*   **Тестируйте контакт-пойнт кнопкой **Test** перед продакшеном и после каждой смены ключа.
*   **Ограничивайте права ключей:** Integration Key в PagerDuty должен относиться к сервису, а не быть global API key.
*   **Настраивайте escalation policy:** даже при автоматическом квитировании должен быть план «если никто не ответил за 15 минут».
*   **Очистка:** удаляйте временные Silences после инцидентов; регулярно пересматривайте Mute Timings; удаляйте неиспользуемые контакт-пойнты и политики из файлов провиженинга.
*   **Мета-мониторинг:** добавьте алерт на `rate(alertmanager_notifications_failed_total[5m]) > 0` — «тихий» сбой доставки в IRM остаётся незамеченным, если не мониторить сам алертинг.

## Дополнительная информация

**См. также:**

*   [Обзор Grafana Alerting](./concepts.md) — терминология и жизненный цикл оповещений.
*   [Декларативное управление оповещениями](./provisioning.md) — управление ресурсами через YAML.
*   [Лучшие практики алертинга](./best_practices.md) — рекомендации по настройке `for`, группировке, борьбе с шумом.
