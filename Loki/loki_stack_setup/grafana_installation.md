# Настройка Grafana для визуализации логов Loki

## Определения

**Grafana** — универсальная платформа для визуализации и анализа данных телеметрии (метрик, логов, трассировок). Для Loki она является основным интерфейсом, позволяющим выполнять запросы на языке LogQL, строить дашборды и настраивать алертинг на основе содержимого логов.

**Loki Data Source** — специализированный коннектор, оптимизированный для работы с моделью данных Loki. Поддерживает динамический парсинг (JSON, logfmt), генерацию временных рядов из логов и глубокую корреляцию с трассировками Tempo через `TraceID`.

**Explore Logs** — упрощенный интерфейс в Grafana 11+, ориентированный на быстрый поиск и фильтрацию логов без глубокого знания синтаксиса LogQL.

**Structured Metadata (Loki 3.x)** — механизм индексации, при котором метаданные лога (например, `trace_id`, `user_id`, severity) хранятся отдельно от строки и участвуют в фильтрации без парсинга тела лога. В Grafana это влияет на выбор полей в интерфейсе Explore и на производительность автодополнения лейблов.

**Correlation / Data Links** — механизм, преобразующий значение лейбла или поля внутри лога в кликабельную ссылку на внешнюю систему (Tempo, Mimir, внешний дашборд) или на другой запрос в самой Grafana.

**Подробнее:** [Обзор Grafana](../../Grafana/grafana_overview.md), [Обзор Grafana Loki](../loki_overview.md)

## Основные концепции

### Интеграция Grafana и Loki

| Компонент | Назначение | Примечание |
| :--- | :--- | :--- |
| **Loki Gateway** | Единая точка входа для запросов | Балансирует нагрузку между Querier и Frontend компонентами. |
| **Explore Mode** | Оперативная диагностика | Позволяет использовать Log Browser для визуального выбора лейблов. |
| **Bloom Filters UI** | Ускорение поиска | Grafana автоматически использует Bloom-фильтры (Loki 3.x), если они включены на бэкенде. |
| **Alerting (LogQL)** | Оповещения по логам | Возможность создания алертов на основе частоты событий (например, > 10 ошибок за 1 минуту). |

### Жизненный цикл лог-запроса в Grafana

1. **Compose:** Пользователь формирует LogQL-запрос в Explore или дашборде; переменные подставляются фронтендом.
2. **Auth:** Бэкенд проверяет права пользователя на источник данных Loki.
3. **Proxy/Query:** Grafana отправляет запрос к Loki Gateway (режим `proxy`) или напрямую к Querier/Frontend.
4. **Parse/Render:** Loki возвращает строки логов с метаданными; Grafana применяет парсинг (`json`, `logfmt`) и форматирование (`line_format`) для панелей.
5. **Correlation:** При наличии Data Links и Derived Fields Grafana генерирует кликабельные ссылки на основе Regex-матчеров и шаблонов URL.

### Механизмы корреляции и навигации

1.  **Derived Fields / Correlations:** Автоматическое создание ссылок на другие системы (Tempo, Mimir, Sentry) на основе данных внутри лога (TraceID, RequestID).
2.  **Data Links:** Преобразование лейблов (например, `container_id`) в ссылки на специфичные дашборды или внешние системы логирования.
3.  **Ad-hoc Filters:** Глобальные переменные на дашбордах, которые автоматически фильтруют и графики Prometheus, и таблицы логов Loki.

### Structured Metadata и Loki 3.x

Loki 3.x вводит structured metadata вместо необработанных лейблов для высококардинальных полей. Grafana отображает такие поля во вкладке "Structured metadata" в Explore. Для источников данных Grafana 13.x требуется параметр `allow_structured_metadata: true` в `jsonData`, иначе дополнительные поля могут игнорироваться интерфейсом.

## Практические сценарии

### Сценарий 1: Конфигурация через Provisioning (Helm)

Декларативная настройка источника данных в `values.yaml` чарта Grafana.

```yaml
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        uid: loki
        access: proxy
        url: http://loki-gateway.logging.svc.cluster.local:80
        isDefault: true
        jsonData:
          maxLines: 1000
          # Включение поддержки новых функций Loki 3.x
          allow_structured_metadata: true
          # Настройка связи с Tempo (Correlations)
          derivedFields:
            - name: TraceID
              matcherRegex: "trace_id=(\\w+)"
              url: "$${__value.raw}"
              datasourceUid: tempo
              matcherType: Label
          # Настройка лимитов и таймаутов
          queryTimeout: 60s
          httpMethod: POST
```

**Вариант с `additionalDataSources` (Helm values) и интеграция с Jaeger:**

Для Flux CD GitOps или упрощённой настройки через Helm `additionalDataSources`. Подходит для JSON-логов, где `traceId` встраивается в тело строки, и трейсы хранятся в Jaeger.

```yaml
additionalDataSources:
  - name: Loki
    type: loki
    url: http://loki.observability.svc.cluster.local:3100
    jsonData:
      derivedFields:
        - name: TraceID
          matcherRegex: '"traceId":"(\w+)"'
          url: "${__value.raw}"
          datasourceUid: jaeger
```

- `matcherRegex: '"traceId":"(\w+)"'` извлекает 16- или 32-символьный `traceId` из JSON-полей
- `${__value.raw}` формирует URL для Jaeger (например, `http://jaeger:16686/trace/<traceId>`)
- `datasourceUid: jaeger` ссылается на зарегистрированный в Grafana источник Jaeger

### Сценарий 2: Оповещения на основе логов (Alerting)

Создание алерта, который срабатывает при появлении критических ошибок в приложении.

1.  Перейдите в **Alerting → Alert rules**.
2.  Создайте новое правило типа **Grafana managed alert**.
3.  В Query выберите источник **Loki** и введите LogQL запрос:
    `sum by (app) (count_over_time({namespace="prod"} |= "level=error" [1m])) > 5`
4.  Настройте условия (например, `Pending period: 2m`) и уведомления в Slack/Telegram.

### Сценарий 3: Настройка Data Links для связи с дашбордами

Автоматический переход от конкретного пода в логах к дашборду его ресурсов.

1.  В настройках источника **Loki** найдите раздел **Data links**.
2.  Добавьте новую ссылку:
    *   **Label:** `pod` (будет применено ко всем логам, имеющим этот лейбл).
    *   **URL:** `/d/kubernetes-resources-pod?var-pod=${__value.raw}`.
    *   **Title:** «Метрики пода: ${__value.raw}».
3.  Теперь в Explore при нажатии на имя пода появится меню перехода.

### Сценарий 4: Ограничение доступа к данным (RBAC)

Начиная с Grafana 10+, можно ограничивать доступ к источникам данных на уровне пользователей или команд.

1.  Перейдите в **Configuration → Data sources → Loki**.
2.  Вкладка **Permissions**.
3.  Включите **Toggle Permissions**.
4.  Добавьте правила: например, команде `Security` — полный доступ, команде `Developers` — только чтение.

### Сценарий 5: Production Helm-установка Grafana с Loki

Полная конфигурация для развертывания Grafana в кластере Kubernetes через Helm-чарт `grafana-community/grafana` с предустановленным источником Loki, HA, внешней БД и мониторингом.

**Предварительные требования:**
- Кластер Kubernetes 1.28+
- Helm 3.14+
- Namespace `monitoring`
- Внешняя PostgreSQL 15+ (для HA)
- StorageClass с поддержкой `ReadWriteMany` (для HA-режима)
- Ingress-контроллер (nginx/traefik)
- cert-manager (для TLS)

**Шаг 1: Подготовка секретов**

```bash
# Секрет администратора Grafana
kubectl create secret generic grafana-admin-secret \
  --namespace monitoring \
  --from-literal=username=admin \
  --from-literal=password='<STRONG_PASSWORD>'

# Секрет для внешней PostgreSQL
kubectl create secret generic grafana-db-secret \
  --namespace monitoring \
  --from-literal=user=grafana \
  --from-literal=password='<DB_PASSWORD>'

# Секрет для SMTP (опционально)
kubectl create secret generic grafana-smtp-secret \
  --namespace monitoring \
  --from-literal=password='<SMTP_PASSWORD>'
```

**Шаг 2: Конфигурация `values.yaml`**

```yaml
replicas: 3

admin:
  existingSecret: "grafana-admin-secret"
  adminUserKey: "username"
  adminPasswordKey: "password"

database:
  type: postgres
  host: postgres-service.db-namespace.svc.cluster.local:5432
  name: grafana
  user: grafana
  existingSecret: "grafana-db-secret"
  userKey: "user"
  passwordKey: "password"

envFromSecret: "grafana-smtp-secret"

grafana.ini:
  smtp:
    enabled: true
    host: "smtp.sendgrid.net:587"
    user: "apikey"
    password: "${SMTP_PASSWORD}"
    from_address: "grafana@example.com"
    starttls_policy: MandatoryStartTLS
  server:
    root_url: "https://grafana.example.com/"
    enable_gzip: true
  security:
    cookie_samesite: "strict"
    admin_only_org_create: true
  unified_alerting:
    enabled: true
    execute_alerts: true
  sessions:
    database_type: redis
    database_url: "redis://redis-service.db-namespace:6379"

auth:
  generic_oauth:
    enabled: true
    name: "Keycloak"
    client_id: "${OAUTH_CLIENT_ID}"
    client_secret: "${OAUTH_CLIENT_SECRET}"
    scopes: "openid profile email roles"
    auth_url: "https://auth.example.com/realms/master/protocol/openid-connect/auth"
    token_url: "https://auth.example.com/realms/master/protocol/openid-connect/token"
    api_url: "https://auth.example.com/realms/master/protocol/openid-connect/userinfo"
    role_attribute_path: "contains(roles[*], 'admin') && 'Admin' || contains(roles[*], 'editor') && 'Editor' || 'Viewer'"
    allow_sign_up: false

podSecurityContext:
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472
  fsGroupChangePolicy: "OnRootMismatch"

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL

resources:
  limits:
    cpu: 1000m
    memory: 2Gi
  requests:
    cpu: 500m
    memory: 1Gi

persistence:
  enabled: true
  type: pvc
  size: 5Gi
  storageClassName: ceph-fs
  accessModes:
    - ReadWriteMany

sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
    searchNamespace: ALL
    folderAnnotation: "grafana_folder"
    GZIP: true
    watchInterval: 15s
  datasources:
    enabled: true
    label: grafana_datasource
    labelValue: "1"
    searchNamespace: ALL

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        uid: loki
        access: proxy
        url: http://loki-gateway.logging.svc.cluster.local:80
        isDefault: true
        jsonData:
          maxLines: 1000
          allow_structured_metadata: true
          derivedFields:
            - name: TraceID
              matcherRegex: "trace_id=(\\w+)"
              url: "$${__value.raw}"
              datasourceUid: tempo
              matcherType: Label
          queryTimeout: 60s
          httpMethod: POST

serviceMonitor:
  enabled: true
  namespace: monitoring
  interval: 30s
  labels:
    release: kube-prometheus-stack

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - grafana.example.com
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.example.com
```

**Шаг 3: Установка Helm-релиза**

```bash
helm upgrade --install grafana grafana-community/grafana \
  -f values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic \
  --timeout 10m
# → Release "grafana" has been upgraded. 3 pod(s) are ready
```

**Валидация:**

```bash
# Проверка подов
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
# → NAME                         READY   STATUS    RESTARTS   AGE
# → grafana-xxx-xxxxx            3/3     Running   0          2m

# Проверка PVC
kubectl get pvc -n monitoring
# → NAME                 STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS
# → data-grafana-xxxxx   Bound    pvc-xxxxx-xxxxx-xxxxx                      5Gi        RWX            ceph-fs

# Проверка источника данных Loki через API
GRAFANA_TOKEN=$(kubectl get secret grafana-admin-secret -n monitoring \
  -o jsonpath='{.data.username}' | base64 -d)
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  http://grafana.monitoring.svc.cluster.local/api/datasources/uid/loki | jq '.id, .uid'
# → 1 / "loki"

# Проверка ServiceMonitor
kubectl get servicemonitor -n monitoring
# → NAME        AGE
# → grafana     2m
```

### Сценарий 6: Самомониторинг и масштабирование

Настройка автоматического сбора метрик самой Grafana и горизонтального масштабирования.

```yaml
serviceMonitor:
  enabled: true
  namespace: monitoring
  interval: 30s
  labels:
    release: kube-prometheus-stack

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

**Валидация метрик:**

```bash
# Проверка эндпоинта /metrics
kubectl port-forward svc/grafana -n monitoring 3000:80
curl -s http://localhost:3000/metrics | grep grafana_dashboard_versions_total
# → grafana_dashboard_versions_total{version="1"} 42

# Проверка HPA
kubectl get hpa -n monitoring
# → NAME      REFERENCE               TARGETS   MINPODS   MAXPODS   REPLICAS
# → grafana   Deployment/grafana      70%/80%   2         5         2
```

### Сценарий 7: Сетевая изоляция (NetworkPolicy)

Ограничение сетевого доступа к Grafana в соответствии с принципом наименьших привилегий.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: grafana-netpol
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: grafana
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 3000
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: logging
      ports:
        - protocol: TCP
          port: 80
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: db-namespace
      ports:
        - protocol: TCP
          port: 5432
    - ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

**Валидация:**

```bash
# Проверка применения NetworkPolicy
kubectl describe networkpolicy grafana-netpol -n monitoring
# → Правила отображаются корректно

# Проверка connectivity к Loki из пода Grafana
kubectl exec -n monitoring deploy/grafana -c grafana -- curl -s -o /dev/null -w "%{http_code}" http://loki-gateway.logging.svc.cluster.local:80
# → 200
```

## Безопасность и права доступа

### Least-privilege RBAC

Sidecar-контейнеры должны иметь минимальные права. При `searchNamespace: ALL` создается ClusterRole; для изолированных окружений используйте `searchNamespace` с явным списком неймспейсов.

```yaml
rbac:
  namespaced: true
  extraRoleRules:
    - apiGroups: [""]
      resources: ["configmaps", "secrets"]
      verbs: ["get", "list", "watch"]
```

### Secret Management

Никогда не храните секреты в `values.yaml`. Используйте:
- Kubernetes Secrets с `existingSecret`
- `helm-secrets` + `sops` для шифрования в Git
- Внешние системы: HashiCorp Vault, AWS Secrets Manager

## Мониторинг и эксплуатация

### ServiceMonitor и ключевые метрики

При включенном `serviceMonitor.enabled: true` Grafana экспортирует метрики на порту `3000` по пути `/metrics`. Ключевые метрики для SRE:

| Метрика | Назначение | Алерт |
| :--- | :--- | :--- |
| `grafana_dashboard_versions_total` | Количество версий дашбордов | Рост без привязки к деплоям |
| `grafana_http_request_duration_seconds_bucket` | Latency HTTP-запросов | p99 > 1s |
| `grafana_active_users` | Активные пользователи | Аномалии (внеплановый доступ) |
| `grafana_db_requests_total` | Запросы к БД конфигурации | Рост при проблемах с PostgreSQL |
| `grafana_up` | Доступность инстанса | `grafana_up == 0` |

### Диагностика

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Data source is not reachable** | Сетевая изоляция или неверный URL | Проверьте NetworkPolicies в K8s. Попробуйте `curl` из пода Grafana к Loki Gateway. |
| **Query timeout** | Слишком тяжелый запрос на большой период | Оптимизируйте LogQL (используйте фильтры по лейблам). Увеличьте `queryTimeout` в настройках. |
| **Too many streams** | Высокая кардинальность лейблов | Убедитесь, что вы не используете ID запросов как лейблы. Используйте structured metadata. |
| **Ссылки в Explore не кликабельны** | Ошибка в Regex для Derived Fields | Проверьте Regex в онлайн-тестерах (Go flavor). Убедитесь, что `datasourceUid` корректен. |

## Базовое масштабирование

### Горизонтальное масштабирование (HPA)

Grafana поддерживает горизонтальное масштабирование только при использовании внешней БД (PostgreSQL/MySQL) и RWX-хранилища. SQLite не поддерживает конкурентный доступ.

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

### Вертикальное масштабирование

Корректировка ресурсов под нагрузкой:

```bash
kubectl edit deployment grafana -n monitoring
# Измените resources.limits.memory с 2Gi на 4Gi при большом количестве дашбордов
```

### Проверка балансировки

```bash
# Проверка распределения подов по нодам
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana -o wide
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.0.1   node-1
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.1.2   node-2
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.2.3   node-3
```

## Ограничения и особые случаи

1.  **SQLite и HA:** SQLite не поддерживает `ReadWriteMany`. Для `replicas > 1` обязательна внешняя БД.
2.  **Session stickiness:** При HA на уровне Ingress требуется настройка sticky sessions для сохранения сессий пользователей.
3.  **Configuration Drift:** Изменения через UI не сохраняются в провиженинговые файлы. После перезапуска Grafana возвращает состояние из Git.
4.  **Sidecar и размер ConfigMap:** Лимит 1 МБ на ConfigMap. Для больших дашбордов включите `GZIP: true` или разбейте на несколько файлов.
5.  **Plugin compatibility:** Плагины имеют собственные версии. После обновления Grafana проверяйте совместимость плагинов; несовместимые блокируются при старте.

## Полезные команды

```bash
# Получение пароля администратора
kubectl get secret grafana-admin-secret -n monitoring \
  -o jsonpath='{.data.password}' | base64 -d; echo

# Проверка состояния подов
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl describe pod <grafana-pod> -n monitoring

# Просмотр логов sidecar (диагностика загрузки дашбордов)
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboards

# Просмотр логов основного контейнера
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana

# Проверка ServiceMonitor
kubectl get servicemonitor -n monitoring
kubectl describe servicemonitor grafana -n monitoring

# Проверка метрик
curl -s http://localhost:3000/metrics | grep grafana_dashboard_versions_total

# Проверка живости
curl -s http://localhost:3000/api/health
# → {"database":"ok","status":"ok","version":"13.2.3"}

# История Helm-релизов
helm history grafana -n monitoring
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор Grafana](../../Grafana/grafana_overview.md) | Архитектура, лицензирование, безопасность, жизненный цикл запроса |
| [Провиженинг Grafana](../../Grafana/grafana_provisioning.md) | File-based provisioning, sidecar, структура директорий |
| [Высокая доступность Grafana](../../Grafana/high_availability.md) | Архитектурные нюансы HA, сессии,RWX-хранилище |
| [Установка Loki](loki_installation.md) | Настройка бэкенда для приема логов от Alloy |
| [Примеры LogQL](logql_examples.md) | Язык запросов для анализа логов, собранных Alloy |
| [Устранение неполадок](../../Grafana/grafana_troubleshooting.md) | Диагностика проблем Grafana |
