# AlertmanagerConfig — Концепции (CRD)

## Определения

**`kind: AlertmanagerConfig`** — Custom Resource Definition в Prometheus Operator для декларативного описания маршрутизации и получателей алертов. Позволяет управлять подмножествами конфигурации Alertmanager (receivers, routes, inhibit rules, time intervals) через отдельные Kubernetes-объекты, без редактирования основного файла `alertmanager.yml` или Secret.

> **Концепции Alertmanager:** [Alertmanager](../../../alertmanager.md) — архитектура, конвейер обработки, ключи запуска.

## Базовые концепции

### Архитектура управления конфигурацией AlertmanagerConfig

AlertmanagerConfig CRD является декларативным описанием желаемого состояния маршрутизации и получателей алертов. Оператор отслеживает изменения ресурсов и автоматически агрегирует их в единую конфигурацию Alertmanager:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `AlertmanagerConfig` в кластере через Kubernetes API Watch.
2.  **Выборка (Selection):** Ресурс `Alertmanager` через `alertmanagerConfigSelector` и `alertmanagerConfigNamespaceSelector` определяет, какие конфигурации должны быть включены в конкретный инстанс.
3.  **Агрегация (Aggregation):** Оператор собирает все выбранные `AlertmanagerConfig`, объединяя их `route`-деревья, `receivers`, `inhibitRules` и `timeIntervals` в единый `alertmanager.yaml`.
4.  **Генерация (Generation):** Агрегированная конфигурация записывается в Kubernetes Secret (по умолчанию `<alertmanager-name>-generated`).
5.  **Синхронизация (Sync):** Sidecar-контейнер `config-reloader` в поде Alertmanager обнаруживает изменения в Secret и инициирует HTTP-запрос `/-/reload` к API Alertmanager для горячей перезагрузки без рестарта пода.
6.  **Верификация (Status):** Через подресурс `status` можно проверить, был ли ресурс успешно принят оператором и применен к целевому инстансу Alertmanager.

### Селекторы и изоляция конфигурации

Для того чтобы Alertmanager загрузил `AlertmanagerConfig`, в спецификации ресурса `Alertmanager` должны быть настроены селекторы:

| Селектор | Тип ресурса | Назначение |
| :--- | :--- | :--- |
| **`alertmanagerConfigSelector`** | `AlertmanagerConfig` | Фильтрует конфигурации по меткам (labels). |
| **`alertmanagerConfigNamespaceSelector`** | `AlertmanagerConfig` | Определяет, в каких namespace искать конфигурации. |
| **`alertmanagerConfigMatcherStrategy`** | `AlertmanagerConfig` | Стратегия применения matcher'ов (опционально). |

> **Ловушка «Пустого селектора»:** В Helm-чарте `kube-prometheus-stack` параметр `alertmanagerConfigSelector` по умолчанию часто пуст `{}`. Это означает, что Alertmanager **не будет подхватывать** никакие `AlertmanagerConfig`. Для активации необходимо обновить `values.yaml`:
> ```yaml
> alertmanager:
>   alertmanagerSpec:
>     alertmanagerConfigSelector:
>       matchLabels:
>         resource: prometheus # Любая метка на ваш выбор
> ```

В глобальном режиме (когда `AlertmanagerConfig` используется как корневая конфигурация инстанса) оператор **не добавляет** автоматический матчер по namespace, что позволяет создавать общекластерные маршруты.

### Взаимосвязь ресурсов

| Ресурс | Роль | Описание |
| :--- | :--- | :--- |
| **AlertmanagerConfig** | Маршрутизация | Декларативное описание того, "кому" и "как" отправлять алерты (receivers, routes, inhibit rules). |
| **Alertmanager** | Агрегатор и доставка | Выбирает `AlertmanagerConfig` через селекторы, агрегирует конфигурацию и доставляет алерты. |
| **Prometheus** | Генератор алертов | Отправляет алерты в инстанс Alertmanager согласно `spec.alertmanager` в Prometheus CRD. |
| **PrometheusRule** | Правила | Генерирует алерты на основе метрик Prometheus. |
| **Secret** | Конфигурация | Сгенерированный Operator файл `alertmanager.yaml` с агрегированной конфигурацией. |

### Подресурс `status` и `conditions`

Начиная с API версии `v1beta1`, ресурс `AlertmanagerConfig` предоставляет подресурс `status`, который позволяет отслеживать состояние применения конфигурации:

```yaml
status:
  conditions:
    - type: Reconciled
      status: "True"
      lastTransitionTime: "2025-09-15T10:00:00Z"
      reason: ReconciliationSucceeded
      message: "Successfully applied AlertmanagerConfig to cluster main"
```

| Поле | Описание |
| :--- | :--- |
| **`type: Reconciled`** | Тип условия. `True` означает успешное применение. |
| **`status`** | Статус условия: `True`, `False` или `Unknown`. |
| **`reason`** | Краткая причина: `ReconciliationSucceeded`, `ReconciliationFailed`. |
| **`message`** | Подробное сообщение об ошибке или успехе. |

> **Диагностика отсутствия подтверждения:** Если условие `Reconciled` отсутствует или имеет статус `False`, проверьте:
> 1. Селекторы `alertmanagerConfigSelector` в ресурсе `Alertmanager`.
> 2. Наличие меток на `AlertmanagerConfig`.
> 3. Логи оператора: `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator -c operator | grep alertmanagerconfig`.

### Назначение

AlertmanagerConfig решает задачу **разделенного управления** конфигурацией: разные команды могут создавать свои маршруты и получатели в своих namespace, не затрагивая глобальную конфигурацию Alertmanager. Prometheus Operator автоматически агрегирует все AlertmanagerConfig, отобранные селекторами в [Alertmanager CRD](./alertmanager.md).

### API версии

| Версия | Статус | С версии Prometheus Operator | Примечание |
| :--- | :--- | :--- | :--- |
| **`v1beta1`** | **Stable** | `v0.57.0+` | Рекомендуемая. Поддерживает **CEL-валидацию** (`x-kubernetes-validations`), **UTF-8 matchers** (Prometheus 3.0) и подресурс **status**. |
| **`v1alpha1`** | Legacy | `v0.40.0+` | Поддерживается для обратной совместимости. Использует `muteTimeIntervals`. |

**Ключевые особенности v1beta1 (2025–2026):**

- **CEL-валидация:** Проверка ресурсов на стороне API-сервера Kubernetes. Позволяет немедленно отклонять некорректные конфигурации (например, при указании нескольких типов авторизации одновременно).
- **Строгая типизация:** Переход от `uint` к `int` с CEL-валидаторами для блокировки отрицательных значений интервалов.
- **Подресурс status:** Позволяет отслеживать `ObservedGeneration` и `Conditions` (успешность применения конфигурации).
- **MatchTypes:** Поле `regex` удалено. Используются явные операторы: `=`, `!=`, `=~`, `!~`.
- **SecretKeySelector:** Поля `name` и `key` строго обязательны.

### Глобальная конфигурация

Начиная с 2025 года, `AlertmanagerConfig` стал основным способом задания **корневой конфигурации** инстанса Alertmanager.

1.  **Назначение:** Ресурс `Alertmanager` ссылается на `AlertmanagerConfig` через `spec.alertmanagerConfiguration.name`.
2.  **Отмена принудительных меток:** В глобальном режиме Оператор **не добавляет** автоматический матчер по namespace, что позволяет создавать общекластерные маршруты.
3.  **Глобальные параметры:** Параметры вроде `smtp_smarthost` или `slack_api_url` теперь можно задавать в блоке `global` самого ресурса `Alertmanager`, который интегрируется с выбранным конфигом.

### Взаимосвязь с Alertmanager CRD

```
Alertmanager CRD (селекторы)
    ↓
  выбирает AlertmanagerConfig по меткам
    ↓
  агрегирует route-дерево и receivers
    ↓
  генерирует alertmanager.yaml в Secret
```

Alertmanager выбирает AlertmanagerConfig через селекторы в Alertmanager CRD:

```yaml
# Alertmanager CRD
spec:
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
```

> **Ловушка «Пустого селектора»:** В Helm-чарте `kube-prometheus-stack` параметр `alertmanagerConfigSelector` по умолчанию часто пуст `{}`. Это означает, что Alertmanager **не будет подхватывать** никакие `AlertmanagerConfig`. Для активации необходимо обновить `values.yaml`:
> ```yaml
> alertmanager:
>   alertmanagerSpec:
>     alertmanagerConfigSelector:
>       matchLabels:
>         resource: prometheus # Любая метка на ваш выбор
> ```

## Особенности синтаксиса CRD

При переходе от классического `alertmanager.yml` к `AlertmanagerConfig` CRD необходимо учитывать ключевые отличия:

### 1. CamelCase против snake_case
В отличие от нативной конфигурации Prometheus/Alertmanager (где используется `snake_case`), в Kubernetes CRD все параметры пишутся в **`camelCase`**:
*   `group_by` → `groupBy`
*   `group_wait` → `groupWait`
*   `group_interval` → `groupInterval`
*   `repeat_interval` → `repeatInterval`

### 2. Синтаксис матчеров (Matchers)
В CRD матчеры описываются как массив объектов с разделением на имя и значение:
*   **Классика:** `job="kubernetes"`
*   **CRD:**
    ```yaml
    matchers:
      - name: job
        value: kubernetes
    ```

### Структура спецификации (spec)

| Блок | Описание |
| :--- | :--- |
| **`route`** | Дерево маршрутов (обязательный) — определяет группировку и направление алертов |
| **`receivers`** | Именованные получатели (Slack, Email, PagerDuty, Webhook, Telegram и др.) |
| **`inhibitRules`** | Правила подавления алертов (взаимное глушение) |
| **`timeIntervals`** | Временные интервалы (ранее `muteTimeIntervals`) |

## Практические сценарии

### Базовая конфигурация (v1beta1)

```yaml
apiVersion: monitoring.coreos.com/v1beta1
kind: AlertmanagerConfig
metadata:
  name: slack-config
  namespace: monitoring
spec:
  route:
    groupBy: ['alertname', 'job']
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 12h
    receiver: 'slack'
    routes:
      - matchers:
          - name: severity
            value: critical
        receiver: 'slack-critical'
  receivers:
    - name: 'slack'
      slackConfigs:
        - channel: '#monitoring'
          apiURL:
            name: slack-webhook
            key: url
    - name: 'slack-critical'
      slackConfigs:
        - channel: '#alerts-critical'
          apiURL:
            name: slack-webhook-critical
            key: url
```

### Параметры маршрута (route)

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`groupBy`** | Метки для группировки алертов | `['alertname', 'job']` |
| **`groupWait`** | Задержка перед первой отправкой | `30s` |
| **`groupInterval`** | Интервал между уведомлениями группы | `5m` |
| **`repeatInterval`** | Интервал повторных уведомлений | `12h` |
| **`receiver`** | Получатель по умолчанию | `slack` |
| **`routes`** | Дочерние маршруты | Массив вложенных route |
| **`matchers`** | Условия для маршрута | Массив matchers (v1beta1) |
| **`continue`** | Продолжать обработку после совпадения | `true` |
| **`muteTimeIntervals`** | Имена timeIntervals для заглушения | `['maintenance']` |

### Матчеры (Matchers v1beta1)

В версии `v1beta1` вместо флага `regex` используется поле `matchType`:

```yaml
matchers:
  - name: severity
    value: critical          # точное совпадение (=)
  - name: team
    value: "backend|frontend"
    matchType: "=~"          # regex-совпадение
  - name: namespace
    value: production
    matchType: "!="          # отрицание
```

| `matchType` | Поведение | По умолчанию |
| :--- | :--- | :--- |
| **`=`** | Точное совпадение | Да |
| **`!=`** | Отрицание | — |
| **`=~`** | Regex-совпадение | — |
| **`!~`** | Regex-отрицание | — |

### Получатели (Receivers)

#### Slack (с обновлением сообщений)

```yaml
receivers:
  - name: 'slack'
    slackConfigs:
      - channel: '#monitoring'
        updateMessage: true # Обновлять сообщение вместо отправки нового
        apiURL:
          name: slack-webhook
          key: url
        sendResolved: true
        title: '{{ .Status | toUpper }}: {{ .CommonLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

#### Email

```yaml
receivers:
  - name: 'email'
    emailConfigs:
      - to: 'team@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        authUsername: 'alertmanager'
        authPassword:
          name: smtp-secret
          key: password
        sendResolved: true
```

#### PagerDuty

```yaml
receivers:
  - name: 'pagerduty'
    pagerdutyConfigs:
      - routingKey:
          name: pagerduty-secret
          key: routing-key
        severity: 'critical'
        description: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

#### Webhook (с кастомными заголовками)

```yaml
receivers:
  - name: 'webhook'
    webhookConfigs:
      - url: 'https://hooks.example.com/alerts'
        sendResolved: true
        httpConfig:
          httpHeaders:
            - name: "X-API-Key"
              valueFrom:
                secret:
                  name: webhook-secret
                  key: api-key
          authorization:
            type: Bearer
            credentials:
              name: webhook-secret
              key: token
```

#### Telegram (нативная поддержка)

```yaml
receivers:
  - name: 'telegram'
    telegramConfigs:
      - botToken:
          name: telegram-secret
          key: token
        chatID: 123456789
        apiURL: 'https://api.telegram.org'
        message: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

#### Jira (нативная интеграция 2026)

```yaml
receivers:
  - name: 'jira'
    jiraConfigs:
      - apiURL: 'https://jira.corp.local'
        project: 'MON'
        issueType: 'Incident'
        auth:
          password:
            name: jira-auth
            key: api-token
```

#### OpsGenie

```yaml
receivers:
  - name: 'opsgenie'
    opsgenieConfigs:
      - apiKey:
          name: opsgenie-secret
          key: api-key
        apiURL: 'https://api.opsgenie.com/v2/alerts'
        priority: 'P1'
        message: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

### Сложная маршрутизация

```yaml
spec:
  route:
    groupBy: ['alertname', 'namespace']
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 12h
    receiver: 'default-receiver'
    routes:
      # Критические алерты → PagerDuty
      - matchers:
          - name: severity
            value: critical
        receiver: 'pagerduty'
        groupWait: 10s
        repeatInterval: 1h

      # Алерты от базы данных → DBA team
      - matchers:
          - name: team
            value: database
        receiver: 'dba-team'

      # Алерты из production → приоритет выше
      - matchers:
          - name: namespace
            value: production
        receiver: 'production-oncall'
        groupWait: 10s
```

### Правила подавления (inhibitRules)

Подавление позволяет заглушить менее значимые алерты при наличии более критичных:

```yaml
spec:
  inhibitRules:
    - sourceMatchers:
        - name: severity
          value: critical
      targetMatchers:
        - name: severity
          value: warning
      equal:
        - alertname
        - namespace
```

### Временные интервалы (timeIntervals)

Определение периодов, в которые уведомления заглушены (окна обслуживания):

```yaml
spec:
  timeIntervals:
    - name: maintenance-window
      timeIntervals:
        - times:
            - startTime: '02:00'
              endTime: '06:00'
          weekdays: ['monday:friday']
          location: 'Europe/Moscow'
```

Использование в маршруте:

```yaml
route:
  receiver: 'slack'
  muteTimeIntervals:
    - maintenance-window
```

### Секреты для получателей

Все чувствительные данные должны храниться в Kubernetes Secrets:

```bash
# Создание секрета для Slack
kubectl create secret generic slack-auth \
  --from-literal=webhook-url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring
```

Ссылка на секрет в AlertmanagerConfig:

```yaml
apiURL:
  name: slack-auth    # имя Secret
  key: webhook-url    # ключ в Secret
```

### Тестирование маршрутизации через amtool

Перед применением конфигурации в Production протестируйте маршрутизацию локально:

```bash
# Загрузите тестовый alertmanager.yml
amtool config routes test --config.file=alertmanager.yml \
  --alert.label.test="severity=critical"
```

Или через API Alertmanager:

```bash
# Отправка тестового алерта
curl -X POST http://localhost:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d '[{
    "labels": {"alertname": "TestAlert", "severity": "critical"},
    "annotations": {"summary": "Test alert"},
    "generatorURL": "http://prometheus:9090"
  }]'

# Проверка получателей
amtool alert --alert.label.test="severity=critical" receiver
```

### Миграция с alertmanager.yml на AlertmanagerConfig

Поэтапный перенос конфигурации из единого файла в декларативные ресурсы:

1.  **Аудит:** Получите текущий `alertmanager.yml` из Secret и decomposing его на логические блоки (routes, receivers, inhibit rules).
2.  **Создание ресурсов:** Для каждого блока создайте отдельный `AlertmanagerConfig` в соответствующем namespace.
3.  **Назначение меток:** Добавьте метки, соответствующие `alertmanagerConfigSelector` в Alertmanager CRD.
4.  **Валидация:** Проверьте статус `Reconciled` и сгенерированный Secret.
5.  **Удаление старого:** После подтверждения корректной работы удалите поле `configSecret` из Alertmanager CRD.

```bash
# Получение текущей конфигурации
kubectl get secret alertmanager-main-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d > current-config.yaml

# Проверка селекторов
kubectl get alertmanagerconfig -A --show-labels
```

### Глобальная конфигурация AlertmanagerConfig

Начиная с 2025 года, `AlertmanagerConfig` может использоваться как корневая конфигурация инстанса Alertmanager. Для этого в ресурсе `Alertmanager` указывается ссылка на конфиг:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  alertmanagerConfiguration:
    name: global-config
    global:
      smtp_smarthost: 'smtp.corp.local:587'
      smtp_from: 'alertmanager@corp.local'
      resolveTimeout: 5m
```

При использовании глобального режима оператор **не добавляет** автоматический матчер по namespace к маршрутам, что позволяет создавать общекластерные маршруты.

> **Важно:** Глобальная конфигурация через `alertmanagerConfiguration` экспериментальна. Для Production рекомендуется использовать отдельные `AlertmanagerConfig` ресурсы с селекторами до стабилизации функции.

### Проверка агрегации конфигурации

После применения `AlertmanagerConfig` убедитесь, что Operator корректно агрегировал конфигурацию:

```bash
# Получение сгенерированного alertmanager.yaml
kubectl get secret alertmanager-main-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 5 "route:"

# Проверкаreceivers
kubectl get secret alertmanager-main-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 2 "receivers:"

# Проверка inhibit rules
kubectl get secret alertmanager-main-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 5 "inhibit_rules:"
```

Убедитесь, что в выводе присутствуют маршруты и receivers из ваших `AlertmanagerConfig` ресурсов.

## Дополнительная информация

### Диагностика

1.  **Список ресурсов:** `kubectl get alertmanagerconfig -n monitoring`
2.  **Детали объекта и статус:** `kubectl get alertmanagerconfig slack-config -o yaml` — ищите секцию `status`.
3.  **Проверка генерации конфига:**
    `kubectl get secret alertmanager-main-generated -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d`

### Особенности агрегации

- **Уникальность имен:** Имена `receivers` и `timeIntervals` должны быть уникальны в рамках одного Alertmanager.
- **Изоляция Namespace:** В обычном режиме оператор принудительно добавляет матчер по namespace к каждому маршруту.
- **Порядок:** Маршруты из разных ресурсов добавляются в дерево в алфавитном порядке имен ресурсов.

### Требования RBAC

Для применения `AlertmanagerConfig` ресурсов необходимы следующие права:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: alertmanager-config-editor
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: alertmanagerconfig-editor
  namespace: monitoring
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["alertmanagerconfigs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alertmanagerconfig-editor-binding
  namespace: monitoring
subjects:
  - kind: ServiceAccount
    name: alertmanager-config-editor
    namespace: monitoring
roleRef:
  kind: Role
  name: alertmanagerconfig-editor
  apiGroup: rbac.authorization.k8s.io
```

Для применения `AlertmanagerConfig` во всех namespace кластера используйте `ClusterRole` и `ClusterRoleBinding`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: alertmanagerconfig-cluster-editor
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["alertmanagerconfigs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: alertmanagerconfig-cluster-editor-binding
subjects:
  - kind: ServiceAccount
    name: alertmanager-config-editor
    namespace: monitoring
roleRef:
  kind: ClusterRole
  name: alertmanagerconfig-cluster-editor
  apiGroup: rbac.authorization.k8s.io
```

### Валидация работоспособности

После применения `AlertmanagerConfig` проверьте следующие группы:

1.  **Статус ресурса:**
    ```bash
    kubectl get alertmanagerconfig -n monitoring
    # Проверьте наличие столбца AGE и отсутствие ошибок
    ```
2.  **Условия (Conditions):**
    ```bash
    kubectl get alertmanagerconfig slack-config -n monitoring -o yaml
    # Ищите status.conditions с type: Reconciled и status: "True"
    ```
3.  **Генерация конфигурации:**
    ```bash
    kubectl get secret alertmanager-main-generated -n monitoring \
      -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 5 "receivers:"
    # Проверьте наличие receivers из AlertmanagerConfig
    ```
4.  **Логи Alertmanager:**
    ```bash
    kubectl logs -n monitoring alertmanager-main-0 -c alertmanager | grep -i "loading configuration"
    # Должно отображаться "Loading configuration file"
    ```
5.  **Логи config-reloader:**
    ```bash
    kubectl logs -n monitoring alertmanager-main-0 -c config-reloader | grep -i "reload"
    # Должно отображаться "Reloading configuration"
    ```
6.  **Проверка через API Prometheus:**
    ```bash
    # Отправка тестового алерта
    curl -X POST http://prometheus:9090/api/v1/alerts \
      -H "Content-Type: application/json" \
      -d '[{
        "labels": {"alertname": "TestAlert", "severity": "critical"},
        "annotations": {"summary": "Test"},
        "generatorURL": "http://prometheus:9090"
      }]'

    # Проверка получения в Alertmanager
    curl http://alertmanager-operated.monitoring:9093/api/v2/alerts | jq .
    ```

### Ограничения и крайние случаи

1.  **Лимит размера Secret (1MB):** Общая конфигурация Alertmanager, включающая все `AlertmanagerConfig`, не должна превышать 1MB. При превышении Оператор не сможет создать/обновить Secret.
2.  **Пустой селектор:** Если `alertmanagerConfigSelector` не указан или пуст, Alertmanager игнорирует все `AlertmanagerConfig`.
3.  **Уникальность имен:** Имена `receivers` и `timeIntervals` должны быть уникальны в рамках одного Alertmanager. Конфликты имен приведут к ошибкам валидации.
4.  **CEL-валидация:** Некорректные `AlertmanagerConfig` (например, несколько типов авторизации одновременно) отклоняются на уровне API-сервера с понятным сообщением.
5.  **Глобальная конфигурация:** При использовании `spec.alertmanagerConfiguration` в Alertmanager CRD ресурсы `AlertmanagerConfig` игнорируются.
6.  **Совместимость версий:** API версия `v1beta1` требует Prometheus Operator v0.57.0+. Использование `v1alpha1` не поддерживает CEL-валидацию и подресурс status.
7.  **Задержка обновления эндпоинтов:** При изменении `AlertmanagerConfig` Operator должен обнаружить изменение, агрегировать конфигурацию, обновить Secret и дождаться перезагрузки Alertmanager. Полный цикл может занять до 1-2 минут.
8.  **Горячая перезагрузка:** При ошибках в конфигурации Alertmanager может отказаться от reload и продолжить работать со старой конфигурацией. Проверяйте логи при отсутствии новых алертов в получателях.

### Типичные проблемы и диагностика

#### Проблема 1: AlertmanagerConfig не подхватывается Alertmanager

**Симптом:** В сгенерированном Secret отсутствуют маршруты и receivers из AlertmanagerConfig.

**Диагностика:**
```bash
# Проверьте селекторы в Alertmanager CRD
kubectl get alertmanager main -n monitoring -o yaml | grep -A 5 alertmanagerConfigSelector

# Проверьте метки на AlertmanagerConfig
kubectl get alertmanagerconfig -A --show-labels

# Проверьте namespace selector
kubectl get alertmanager main -n monitoring -o yaml | grep -A 5 alertmanagerConfigNamespaceSelector
```

**Решение:** Убедитесь, что `AlertmanagerConfig` имеет метки, соответствующие `alertmanagerConfigSelector`, и находится в namespace, разрешенном `alertmanagerConfigNamespaceSelector`. Проверьте, что селектор не пуст.

#### Проблема 2: Ошибка «Secret is invalid: data: Too long»

**Симптом:** Оператор не применяет изменения, в событиях Alertmanager отображается ошибка размера Secret.

**Диагностика:**
```bash
kubectl get events -n monitoring --field-selector reason=SyncError
```

**Решение:** Уменьшите размер конфигурации (удалите избыточные receivers/inhibit rules) или используйте несколько Alertmanager инстансов с разными селекторами.

#### Проблема 3: Ресивер не получает алерты

**Симптом:** Алерты поступают в Alertmanager, но не доставляются в Slack/Email/PagerDuty.

**Диагностика:**
```bash
# Проверка статуса алертов в Alertmanager
curl http://alertmanager-operated.monitoring:9093/api/v2/alerts | jq .

# Проверка получателей
curl http://alertmanager-operated.monitoring:9093/api/v2/receiver?receiver=slack | jq .

# Проверка логов Alertmanager
kubectl logs -n monitoring alertmanager-main-0 -c alertmanager | grep -i "error\|failed"
```

**Решение:** Убедитесь, что receiver правильно сконфигурирован (URL, токен), секрет существует, и сетевые политики не блокируют исходящие соединения.

#### Проблема 4: Inhibit rules не работают

**Сиymptom:** Менее критичные алерты не подавляются при наличии критичных.

**Диагностика:**
```bash
# Проверка сгенерированной конфигурации
kubectl get secret alertmanager-main-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 10 "inhibit_rules:"
```

**Решение:** Убедитесь, что `sourceMatchers` и `targetMatchers` корректно сопоставляются, и поля `equal` содержат общие метки (например, `alertname`, `namespace`).

#### Проблема 5: Time intervals не применяются

**Симптом:** Уведомления не заглушаются в указанные временные окна.

**Диагностика:**
```bash
# Проверка time intervals в сгенерированной конфигурации
kubectl get secret alertmanager-main-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 10 "time_intervals:"
```

**Решение:** Убедитесь, что имена `timeIntervals` в `muteTimeIntervals` точно совпадают с именами в блоке `timeIntervals`, и формат временных интервалов корректен.

### Лучшие практики

1.  **API версия:** Используйте `v1beta1` для всех новых ресурсов. Версия `v1alpha1` устарела и не поддерживает CEL-валидацию.
2.  **Изоляция:** Для мультитенантности создавайте отдельные `AlertmanagerConfig` в namespace команд с соответствующими селекторами.
3.  **Имена receivers:** Используйте осмысленные имена receivers, отражающие канал доставки и критичность (например, `slack-critical`, `pagerduty-dba`).
4.  **Тестирование:** Перед применением в Production тестируйте конфигурацию с помощью `amtool config routes test`.
5.  **Секреты:** Храните токены и пароли в Kubernetes Secrets, никогда не в ConfigMap.
6.  **Размер конфигурации:** Держите общий размер конфигурации ниже 1MB. При приближении к лимиту разбейте конфигурацию на несколько Alertmanager инстансов.
7.  **Матчеры:** Используйте явные `matchType` для regex-совпадений (`=~`, `!~`) вместо неявного поведения.
8.  **Глобальная конфигурация:** Используйте `AlertmanagerConfig` для глобальных настроек только после стабилизации функции `alertmanagerConfiguration` в Alertmanager CRD.
9.  **Мониторинг:** Добавьте алерт на корректность применения `AlertmanagerConfig` (проверка условия `Reconciled`).
10. **Документирование:** Добавляйте комментарии в YAML с указанием команды-владельца и purpose каждого receiver/route.
11. **Inhibit rules:** Используйте подавление алертов осторожно — слишком агрессивные правила могут заглушить важные уведомления.
12. **Версионирование:** Храните манифесты `AlertmanagerConfig` в Git с четким владельцем и процессом ревью.

### Связанные темы

- [Alertmanager CRD](./alertmanager.md) — развёртывание инстансов.
- [Alertmanager — концепция](../../../alertmanager.md) — архитектура обработки данных.
- [PrometheusRule CRD](./prometheusrule.md) — генерация алертов.
- [Secrets best practices](../Security/secrets_best_practices.md) — защита учетных данных.
