# Prometheus — Концепции (CRD)

## Определения

**`kind: Prometheus`** — ключевой Custom Resource Definition (CRD) в Prometheus Operator, предназначенный для декларативного описания жизненного цикла и конфигурации экземпляра Prometheus Server. На основе этого ресурса Operator автоматически создает и управляет Kubernetes-объектами: StatefulSet, Service, ConfigMap, Secrets и RBAC.

**Reconciliation Loop в Prometheus CRD** — процесс, при котором Оператор постоянно сравнивает желаемое состояние (описанное в CRD) с реальным состоянием в кластере, обеспечивая актуальность конфигурации скрейпинга, правил алертинга и параметров хранения.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Концепции Prometheus Operator](../concepts.md), [ServiceMonitor](./servicemonitor.md), [PodMonitor](./podmonitor.md), [Probe](./probe.md), [PrometheusRule](./prometheusrule.md).

## Базовые концепции

### Архитектура управления экземпляром

Prometheus CRD является декларативным описанием желаемого состояния. Operator отслеживает изменения ресурса и автоматически управляет инфраструктурными объектами:

1.  **Контроллер (Controller):** Отслеживает ресурс `Prometheus` и вычисляет разницу между желаемым и текущим состоянием.
2.  **Генератор (Generator):** На основе селекторов собирает все `ServiceMonitor`, `PodMonitor`, `Probe`, `ScrapeConfig` и `PrometheusRule`, агрегируя их в единый `prometheus.yaml`.
3.  **Config-Reloader (Sidecar):** Sidecar-контейнер в поде Prometheus обнаруживает изменения в Secret/ConfigMap с конфигурацией и инициирует HTTP-запрос `/-/reload` к API Prometheus для горячей перезагрузки без рестарта пода.
4.  **Инфраструктура:** StatefulSet управляет подами Prometheus, Service обеспечивает доступ, PVC предоставляет персистентное хранилище для TSDB, ServiceAccount и RBAC управляют правами доступа.

### Принцип работы и жизненный цикл

1.  **Watch:** Оператор отслеживает изменения объекта `Prometheus` и связанных с ним ресурсов через Kubernetes API.
2.  **Discovery:** Собираются ссылки на все связанные ресурсы через селекторы (`serviceMonitorSelector`, `podMonitorSelector`, `ruleSelector` и т.д.).
3.  **Generation:** Генерируется итоговый `prometheus.yaml`. В современных версиях (v0.80+) поддерживается автоматическая настройка UTF-8 для Prometheus 3.0.
4.  **Storage Config:** Формируется описание `TSDB` (хранилища). Для Prometheus 3.9+ реализована оптимизация координации с Thanos, позволяющая не отключать локальную компакцию.
5.  **Deployment:** Создается или обновляется `StatefulSet`.
6.  **Reload:** Sidecar-контейнер `config-reloader` (работает в том же поде) обнаруживает изменения в ConfigMap/Secret и инициирует обновление конфигурации через сигнал `/-/reload` без перезагрузки подов.

> **Примечание:** Полное описание архитектуры контроллера и цикла Reconciliation — в [Концепции Prometheus Operator](../concepts.md#архитектура-и-цикл-работы-контроллера).

### Селекторы целей и правил

Ресурс `Prometheus` выступает агрегатором, объединяющим разрозненные описания мониторинга:

| Селектор | Тип ресурса | Назначение |
| :--- | :--- | :--- |
| **`serviceMonitorSelector`** | `ServiceMonitor` | Обнаружение целей через Kubernetes Service. |
| **`podMonitorSelector`** | `PodMonitor` | Прямой скрейпинг IP-адресов подов. |
| **`probeSelector`** | `Probe` | Blackbox-мониторинг внешних целей. |
| **`scrapeConfigSelector`** | `ScrapeConfig` | Нативные и кастомные конфигурации сбора данных. |
| **`ruleSelector`** | `PrometheusRule` | Подключение групп правил алертинга и записи. |

> **Критическая деталь:** Если селектор пуст (`{}`) — выбираются ВСЕ ресурсы соответствующего типа во ВСЕХ namespace. Если селектор имеет жесткий фильтр (например, `release: kube-prometheus-stack`) — ресурсы без этого лейбла игнорируются. Подробнее — в [Diagnostics and Troubleshooting](../troubleshooting.md).

### Выбор между Prometheus и PrometheusAgent

| Критерий | `kind: Prometheus` | `kind: PrometheusAgent` |
| :--- | :--- | :--- |
| **TSDB (локальное хранилище)** | Да | Нет |
| **Query Engine (PromQL)** | Да | Нет |
| **Alerting (`PrometheusRule`)** | Да | Нет |
| **Remote Write** | Да | Да |
| **Потребление ресурсов** | Выше (TSDB + Query) | Ниже на 30-40% |
| **Сценарий использования** | Полноценный сервер мониторинга | Edge-кластеры, IoT, агрегация |

### Поддержка Prometheus 3.0 (2025–2026)

*   **UTF-8 Mode:** Поддержка любых символов в именах метрик и лейблов (требует Prometheus >= v3.0.0).
*   **Remote Write v2.0:** Использование новой версии протокола для повышения эффективности передачи данных.
*   **Native Histograms:** Настройка параметров разреженных гистограмм для сбора высокоточных данных.
*   **OTLP Ingestion:** Возможность приема данных по протоколу OpenTelemetry напрямую.
*   **Scrape Protocols:** Приоритет протоколов сбора (Protobuf, OpenMetrics) для снижения нагрузки на сеть и ускорения парсинга.

## Практические сценарии

### Сценарий 1: Производственная конфигурация (HA + Storage + Security)

Конфигурация с двумя репликами, персистентным хранилищем и настройками безопасности.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.12.0
  serviceAccountName: prometheus
  securityContext:
    fsGroup: 2000
    runAsNonRoot: true
    runAsUser: 1000
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: runtime/default
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  retention: 30d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-storage
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
  resources:
    requests:
      memory: 2Gi
      cpu: 500m
    limits:
      memory: 8Gi
      cpu: 2000m
```

### Сценарий 2: Интеграция с Thanos и оптимизация компакции

Актуально для версий Prometheus >= 3.9.0 и Thanos >= 0.41.0.

```yaml
spec:
  thanos:
    version: v0.41.0
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
  # Примечание: В новых версиях Operator компакция не отключается автоматически,
  # если используется координация через shipper meta file.
```

### Сценарий 3: Кастомный скрейпинг и OTLP

Использование `additionalScrapeConfigs` для целей, которые нельзя описать через CRD.

```yaml
spec:
  version: v3.12.0
  enableFeatures:
    - otlp-write-receiver
    - native-histograms
  additionalScrapeConfigs:
    name: extra-scrape-configs
    key: prometheus-additional.yaml
  remoteWrite:
    - url: "http://remote-storage:8428/api/v1/write"
      remoteTimeout: 30s
  otlp:
    promoteResourceAttributes:
      - service.name
      - service.namespace
```

### Сценарий 4: Security hardening и Pod Security Standards

Ограничение привилегий пода Prometheus в соответствии с PSA (Pod Security Standards) и требованиями политик безопасности.

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 3000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault
  podMetadata:
    annotations:
      seccomp.security.alpha.kubernetes.io/prometheus: runtime/default
      container.apparmor.security.beta.kubernetes.io/prometheus: localhost/k8s-apparmor-prometheus
  podSecurityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL
  containers:
    - name: prometheus
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      volumeMounts:
        - name: config
          mountPath: /etc/prometheus/config
          readOnly: true
        - name: storage
          mountPath: /prometheus
  volumes:
    - name: config
      emptyDir: {}
```

### Сценарий 5: Multi-tenant isolation и namespaceSelector

Конфигурация для сбора метрик из нескольких namespace с разными селекторами и отдельным хранилищем для каждого tenant.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: tenant-a
  namespace: monitoring
spec:
  replicas: 1
  version: v3.12.0
  serviceMonitorSelector:
    matchLabels:
      tenant: a
  podMonitorSelector:
    matchLabels:
      tenant: a
  ruleSelector:
    matchLabels:
      tenant: a
  serviceMonitorNamespaceSelector:
    matchNames:
      - tenant-a-apps
      - tenant-a-platform
  podMonitorNamespaceSelector:
    matchNames:
      - tenant-a-apps
      - tenant-a-platform
  ruleNamespaceSelector:
    matchNames:
      - tenant-a-alerts
  externalLabels:
    tenant: a
    cluster: production-east
  retention: 14d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-storage
        resources:
          requests:
            storage: 50Gi
```

### Сценарий 6: Кастомный DNS и сетевые параметры

Настройка `dnsConfig` и `dnsPolicy` для Prometheus в средах с кастомными DNS-серверами или ограниченной сетевой доступностью.

```yaml
spec:
  dnsPolicy: Custom
  dnsConfig:
    nameservers:
      - 10.0.0.10
      - 10.0.0.11
    searches:
      - monitoring.svc.cluster.local
      - svc.cluster.local
      - cluster.local
    options:
      - name: ndots
        value: "2"
      - name: timeout
        value: "3"
  # Для Prometheus 3.11+ доступен ProxyConfig:
  proxyConfig:
    http: http://proxy.internal:3128
    https: http://proxy.internal:3128
    noProxy:
      - .svc.cluster.local
      - 127.0.0.1
      - ::1
```

### Сценарий 7: Resource management и QoS Guaranteed

Настройка ресурсов для получения QoS класса `Guaranteed`, предотвращения OOMKilled и троттлинга.

```yaml
spec:
  resources:
    requests:
      memory: "4Gi"
      cpu: "1000m"
    limits:
      memory: "4Gi"
      cpu: "1000m"
  # Для крупных инстансов (>1M серий) рекомендуется:
  # - Увеличить limit до 2x от request
  # - Настроить goGC для оптимизации GC пауз:
  goGC: 50  # По умолчанию 100; меньше = чаще GC, меньше RAM usage
```

### Сценарий 8: Отдельный ServiceAccount и внешняя аутентификация

Использование корпоративного ServiceAccount с настроенным IRSA (IAM Roles for Service Accounts) для Remote Write в облачное хранилище или OIDC-аутентификация.

```yaml
spec:
  serviceAccountName: prometheus-external-write
  podMetadata:
    labels:
      # Для AWS IRSA:
      eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/prometheus-remote-write
      # Для GCP Workload Identity:
      # iam.gke.io/gcp-service-account: prometheus@project.iam.gserviceaccount.com
  # Включение базовой аутентификации для веб-интерфейса:
  web:
    tlsConfig: ~
    httpConfig:
      basicAuth:
        username:
          key: username
          name: prometheus-basic-auth
        password:
          key: password
          name: prometheus-basic-auth
```

## Дополнительная информация

### Требования к правам (RBAC)

Для корректной работы Prometheus CRD и связанных функций Prometheus Operator необходимо настроить права доступа:

**ServiceAccount и ClusterRole для Prometheus:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - nodes/proxy
      - services
      - endpoints
      - pods
    verbs: ["get", "list", "watch"]
  - apiGroups: ["discovery.k8s.io"]
    resources:
      - endpointslices
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources:
      - configmaps
    verbs: ["get"]
  - apiGroups: ["monitoring.coreos.com"]
    resources:
      - servicemonitors
      - podmonitors
      - probes
      - prometheusrules
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: monitoring
```

> **Примечание:** При использовании Helm-чарта `kube-prometheus-stack` RBAC создается автоматически. Для ручного деплоя или кастомных манифестов — создавайте объекты явно.

### Ключевые параметры спецификации (v1)

| Параметр | Тип | Описание | Особенности (2026) |
| :--- | :--- | :--- | :--- |
| **`replicas`** | `int32` | Количество реплик Prometheus. | Минимум 2 для HA. Каждая реплика независима. |
| **`shards`** | `int32` | Количество шардов для масштабирования. | Горизонтальное масштабирование скрейпинга. |
| **`version`** | `string` | Версия образа Prometheus (semver). | Рекомендуется фиксировать версию, а не использовать `latest`. |
| **`serviceMonitorSelector`** | `LabelSelector` | Селектор для ServiceMonitor. | Пустой (`{}`) = все ServiceMonitor. |
| **`podMonitorSelector`** | `LabelSelector` | Селектор для PodMonitor. | |
| **`probeSelector`** | `LabelSelector` | Селектор для Probe. | |
| **`ruleSelector`** | `LabelSelector` | Селектор для PrometheusRule. | |
| **`scrapeConfigSelector`** | `LabelSelector` | Селектор для ScrapeConfig. | |
| **`externalLabels`** | `map[string]string` | Глобальные метки экземпляра. | Используются для дедупликации в Thanos/VictoriaMetrics. |
| **`retention`** | `string` | Период хранения данных (TSDB). | Формат: `30d`, `12h`, `720h` (30d = по умолчанию). |
| **`scrapeProtocols`** | `[]string` | Приоритет протоколов (OpenMetrics и др.). | Требует Prometheus >= v2.49. |
| **`enableFeatures`** | `[]string` | Включение экспериментальных фич. | `otlp-write-receiver`, `native-histograms`, `memory-snapshot-on-shutdown`. |
| **`additionalScrapeConfigs`** | `SecretKeySelector` | Ссылка на Secret с классическим конфигом. | Позволяет настраивать сложные SD, не поддерживаемые CRD. |
| **`thanos`** | `ThanosSpec` | Конфигурация Thanos sidecar. | Включается при интеграции с долгосрочным хранилищем. |
| **`storage`** | `StorageSpec` | Конфигурация персистентного хранилища. | `volumeClaimTemplate` для динамического provisioning. |
| **`resources`** | `ResourceRequirements` | Потенциал и лимиты ресурсов. | QoS Guaranteed при равенстве requests/limits. |
| **`securityContext`** | `PodSecurityContext` | Настройки безопасности Pod. | Управление правами пользователя, групп и Linux capabilities. |
| **`podMetadata`** | `ObjectMeta` | Лейблы и аннотации для создаваемых подов. | Критично для интеграции с системами сбора логов и mesh. |
| **`web`** | `WebSpec` | Настройка веб-интерфейса (TLS, Auth). | Позволяет защитить UI через встроенные механизмы. |
| **`dnsConfig` / `dnsPolicy`** | `PodDNSConfig` / `string` | Настройка DNS для подов Prometheus. | Управление разрешением имен внутри кластера. |
| **`goGC`** | `int32` | Настройка Go Garbage Collector. | Оптимизация потребления RAM и пауз GC. |
| **`proxyConfig`** | `ProxyConfig` | Прокси для исходящих соединений. | Доступно в Prometheus >= 3.11. |

### Ограничения и крайние случаи

1.  **Лимит размера Secret (1MB):** Итоговый `prometheus.yaml` сжимается и хранится в Secret. При превышении 1MB Operator вернет ошибку. Решение: шардирование (`spec.shards`) или переход на `ScrapeConfig`.
2.  **Пустой селектор vs жесткий фильтр:** `serviceMonitorSelector: {}` выбирает ВСЕ сервисы, что может привести к взрывному росту количества целей. Жесткий фильтр (`matchLabels`) ограничивает область, но требует маркировки всех ServiceMonitor.
3.  **Имя порта vs номер порта:** В `ServiceMonitor.endpoints.port` можно указать либо имя порта из Service, либо номер. Смешение подходов в одном ресурсе приводит к ошибкам обнаружения.
4.  **NetworkPolicy и DNS:** Прометей должен иметь доступ к API-серверу (для SD) и к целевым эндпоинтам (для скрейпинга). Отсутствующие `NetworkPolicy` или кастомный `dnsPolicy` без корректных `nameservers` приводят к `Connection Refused` или `NXDOMAIN`.
5.  **Stale-метрики при перезапуске StatefulSet:** При rolling update или scale-down часть метрик временно помечается как `stale`. Это нормальное поведение TSDB, но может вызвать ложные срабатывания алертов на `absent()`. Используйте `ignoreStaleMarkers: true` в правилах.
6.  **TSDB corruption при принудительном удалении пода:** Удаление пода Prometheus без graceful shutdown может привести к повреждению блоков TSDB. Используйте `preStop` hook или `podDisruptionBudget` для плановых действий.
7.  **Зависимость от `EndpointSlice`:** С версии v0.80+ Operator использует `EndpointSlice` вместо устаревшего `Endpoints`. Если в кластере отключен `EndpointSlice` API, Service Discovery перестанет работать.
8.  **Ограничения CEL-валидации:** CEL-выражения проверяют только синтаксис, но не семантику. Например, `retention: -30d` будет отклонен, а `retention: "0"` (невалидное значение) — нет. Дополнительная валидация на уровне Operator.

### Валидация работоспособности

После создания или обновления ресурса `Prometheus` выполните проверки:

```bash
# 1. Проверка статуса ресурса и условий
kubectl get prometheus main -n monitoring -o yaml

# 2. Ожидание готовности StatefulSet
kubectl rollout status statefulset/prometheus-main -n monitoring --timeout=5m

# 3. Проверка сгенерированной конфигурации
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | head -50

# 4. Проверка логов Operator на предмет ошибок reconciliation
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=100 | grep -i "prometheus/main" | tail -20

# 5. Проверка логов config-reloader
kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50

# 6. Проверка доступности UI и API
kubectl port-forward -n monitoring svc/prometheus-main 9090:9090
curl -s http://localhost:9090/-/healthy    # → healthy
curl -s http://localhost:9090/-/ready      # → ready
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | length'
```

### Типичные проблемы и устранение неполадок

#### Проблема 1: Цели не появляются в Prometheus

*   **Причина:** Несовпадение лейблов между селектором в `Prometheus` и целевым ресурсом (`ServiceMonitor`, `PodMonitor`, `Probe`).
*   **Диагностика:**
    ```bash
    kubectl get servicemonitor,podmonitor,probe --all-namespaces -o wide | grep release
    kubectl get prometheus -o yaml | grep -A5 selector
    ```
*   **Решение:** Добавьте соответствующий лейбл в целевой ресурс или измените селектор в `Prometheus`.

#### Проблема 2: Secret превысил лимит 1MB

*   **Причина:** Слишком большое количество целей, сложные relabeling или большие правила.
*   **Диагностика:**
    ```bash
    kubectl get secret prometheus-main -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c
    ```
*   **Решение:** Включите шардирование (`spec.shards: 3`), оптимизируйте `relabel_configs` или используйте `ScrapeConfig` для сложных сценариев.

#### Проблема 3: Config-reloader не перезагружает конфигурацию

*   **Причина:** Ошибка в синтаксисе `prometheus.yaml`, упавший sidecar или проблемы с правами доступа к Secret.
*   **Диагностика:**
    ```bash
    kubectl logs -n monitoring prometheus-main-0 -c config-reloader
    # Ищите: "error reloading configuration"
    ```
*   **Решение:** Проверьте валидность YAML (`promtool check config`), убедитесь в наличии прав `get` на Secret.

#### Проблема 4: TSDB corruption или OOMKilled

*   **Причина:** Недостаток памяти для объема метрик, агрессивный `scrape_interval`, или принудительное удаление пода.
*   **Диагностика:**
    ```bash
    kubectl describe pod prometheus-main-0 -n monitoring | grep -A5 "Last State"
    kubectl top pod prometheus-main-0 -n monitoring
    ```
*   **Решение:** Увеличьте `resources.limits.memory`, настройте `goGC`, включите `memory-snapshot-on-shutdown`.

#### Проблема 5: CEL-валидация отклоняет корректный ресурс

*   **Причина:** Использование устаревшего CRD или конфликт версий Operator и CRD.
*   **Диагностика:**
    ```bash
    kubectl describe prometheus main -n monitoring
    # Ищите события от validating webhook
    ```
*   **Решение:** Обновите CRD до версии, соответствующей Operator (`kubectl apply -f crd/`).

#### Проблема 6: Thanos sidecar не стартует или теряет данные

*   **Причина:** Неверный `objectStorageConfig`, проблемы с сетью до объектного хранилища или несовместимые версии.
*   **Диагностика:**
    ```bash
    kubectl logs -n monitoring prometheus-main-0 -c thanos-sidecar
    ```
*   **Решение:** Проверьте корректность секрета `thanos-objstore-config`, доступность S3/GCS/MinIO, версии Prometheus и Thanos.

#### Проблема 7: Прометей не может разрешить имена целей

*   **Причина:** Отсутствующие `EndpointSlice`, неправильный `dnsPolicy` или кастомный DNS не настроен.
*   **Диагностика:**
    ```bash
    kubectl get endpointslices -n <namespace> -l app=<service>
    kubectl exec -n monitoring prometheus-main-0 -- nslookup kubernetes.default
    ```
*   **Решение:** Проверьте `dnsConfig` в спецификации Prometheus, убедитесь в наличии `CoreDNS` или кастомного resolver.

#### Проблема 8: Отсутствуют метрики после обновления версии

*   **Причина:** Смена формата метрик (UTF-8 mode), breaking changes в Prometheus 3.0, или несовместимые правила.
*   **Диагностика:**
    ```bash
    # Проверка формата метрик
    kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics | head -20
    ```
*   **Решение:** Проверьте release notes Prometheus, включите обратную совместимость при необходимости, обновите правила.

### Лучшие практики

1.  **Фиксируйте версии:** Никогда не используйте `version: latest` в production. Фиксируйте конкретную версию Prometheus и Thanos.
2.  **Используйте `replicas: 2` минимум:** Даже в малых кластерах HA предотвращает потерю данных при rolling update.
3.  **Маркируйте селекторы явно:** Используйте `release`, `team`, `environment` для селекторов, избегайте пустых (`{}`) в production без необходимости.
4.  **Настраивайте `retention` по потребностям:** 15d — стандарт для большинства сценариев. Для соответствия compliance может потребоваться 90d+.
5.  **Ограничивайте ресурсы:** Всегда указывайте `resources.requests` и `resources.limits`. Используйте `goGC` для оптимизации RAM при больших объемах метрик.
6.  **Мониторьте сам Prometheus:** Используйте встроенные метрики (`prometheus_engine_*`, `prometheus_remote_storage_*`) и [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts) для self-monitoring.
7.  **Используйте `ScrapeConfig` для сложных случаев:** Вместо `additionalScrapeConfigs` (классический стиль) предпочитайте `ScrapeConfig` CRD для нативного описания внешних целей.
8.  **Планируйте шардирование заранее:** При приближении к 1-2M активных серий — добавляйте шарды. Переход с 1 на 3 шарда проще, чем экстренное масштабирование при переполнении TSDB.
9.  **Security by default:** Включайте `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`. Используйте `seccompProfile: RuntimeDefault`.
10. **Валидируйте перед применением:** Используйте `promtool check config` и `kubectl diff` для проверки изменений перед `kubectl apply`.

### См. также

*   [Prometheus Operator Concepts](../concepts.md) — архитектура контроллера и цикл Reconciliation.
*   [High Availability](../high_availability.md) — HA, шардирование, topology spreading.
*   [Troubleshooting](../troubleshooting.md) — диагностика и устранение неисправностей.
*   [Thanos Overview](../../../scaling/thanos_overview.md) — архитектура долгосрочного хранения.
*   [Prometheus Operator API](https://prometheus-operator.dev/docs/operator/api/) — официальная справочная документация по всем полям CRD.
