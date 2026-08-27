# Интеграция Jaeger с Kubernetes

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)**.

Развертывание Jaeger v2 в Kubernetes базируется на использовании **OpenTelemetry Operator**. Поскольку вторая версия Jaeger построена на базе OpenTelemetry Collector, она нативно управляется через стандартные ресурсы OpenTelemetry. Это позволяет автоматизировать не только развертывание самого Jaeger, но и процесс инструментирования приложений, а также обеспечивать глубокую интеграцию с сетевой инфраструктурой кластера.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **OpenTelemetry Operator** | Kubernetes-контроллер, автоматизирующий жизненный цикл компонентов телеметрии: установку, настройку, инъекцию агентов и управление сертификатами |
| **OpenTelemetryCollector (CR)** | Кастомный ресурс (Custom Resource), описывающий конфигурацию Jaeger v2 (пайплайны OTLP, процессоры, экспортеры в хранилище) |
| **Instrumentation (CR)** | Ресурс для настройки автоматической инструментации приложений (Java, Python, NodeJS, Go) без изменения их исходного кода |
| **Sidecar Injection** | Механизм автоматического внедрения контейнера Collector в под приложения через Mutating Admission Webhook |
| **Downward API** | Механизм Kubernetes для передачи метаданных пода (IP узла, имя пода, неймспейс) внутрь контейнера через переменные окружения или файлы |
| **Service Mesh (Istio/Linkerd)** | Инфраструктурный слой кластера, который может генерировать собственные спаны и требует согласованности заголовков трассировки с приложением |
| **OpenTelemetryCollector modes** | Режимы развертывания CR: `deployment` (централизованный), `daemonset` (на каждый узел), `statefulset` (с персистентным хранилищем) |
| **k8sattributes processor** | Процессор OTel Collector, обогащающий спаны метаданными Kubernetes (имя пода, неймспейс, узел, метки) |
| **Jaeger Operator** | Альтернативный оператор (от jaegertracing), упрощающий развертывание через CRD `Jaeger`. В 2026 году предпочтительнее OpenTelemetry Operator для новых проектов |
| **Auto-instrumentation** | Внедрение OTel SDK в приложение без изменения исходного кода (через Javaagent, Python wrapper, eBPF) |
| **Manual Instrumentaton** | Явное добавление телеметрии в код через OTel API для бизнес-логики |
| **NetworkPolicy** | Kubernetes-ресурс для контроля сетевого трафика между подами и неймспейсами |
| **ServiceAccount** | Идентификатор сервиса в Kubernetes, используемый для RBAC-авторизации подов |
| **PodDisruptionBudget** | Ресурс, ограничивающий количество одновременно недоступных подов при плановых работах (обновление узлов, drain) |

---

## Базовые концепции

### Архитектура OpenTelemetry Operator

OpenTelemetry Operator состоит из нескольких контроллеров, которые управляют разными аспектами жизненного цикла телеметрии:

| Компонент | Назначение |
| :--- | :--- |
| **OpenTelemetryCollector Controller** | Управляет развертыванием и конфигурацией коллекторов на основе CR `OpenTelemetryCollector` |
| **Instrumentation Controller** | Управляет автоматической инструментацией приложений на основе CR `Instrumentation` |
| **Target Allocator** | Распределяет цели сбора (endpoints) между инстансами коллектора в режиме `sharding` для горизонтального масштабирования |
| **Cert-Manager Integration** | Автоматически выдает и ротирует TLS-сертификаты для Collector и вебхуков |

**Поток данных в Kubernetes:**

1. Приложение с автоматической инструментацией (или ручным OTLP-экспортером) отправляет спаны на Collector.
2. Collector (развернутый как Deployment, DaemonSet или Sidecar) обрабатывает спаны через пайплайн OTLP.
3. Экспортер записывает данные в хранилище (ClickHouse, Elasticsearch) или Kafka.
4. Query/UI предоставляет доступ к данным через Service и Ingress.

### Паттерны развертывания коллектора

В Jaeger v2 выбор паттерна развертывания коллектора-агента определяет баланс между потреблением ресурсов и сетевой сложностью.

| Паттерн | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Sidecar** | Collector запускается как второй контейнер в каждом поде приложения | Прямая связь по localhost. Индивидуальная настройка для каждого сервиса | Оверхед по ресурсам на каждый инстанс приложения |
| **DaemonSet** | Один экземпляр Collector на каждом узле кластера | Оптимальное использование ресурсов узла. Удобно для сбора системных метрик | Требует настройки `hostPort` и корректной передачи IP узла из приложений |
| **Deployment** | Централизованный кластер коллекторов за Service | Удобство масштабирования (HPA). Централизованное управление политиками сэмплирования | Дополнительный сетевой переход (Extra Hop), требующий учета задержек |

**Рекомендации по выбору паттерна (2026):**
- **Sidecar:** Используйте для микросервисов с высокой cardinality атрибутов или требующих индивидуальной конфигурации пайплайна.
- **DaemonSet:** Используйте для сбора телеметрии с уровня узла (системные метрики, eBPF-данные) или при высокой нагрузке, где overhead sidecar'ов критичен.
- **Deployment:** Используйте для стандартных микросервисных архитектур с возможностью централизованного управления.

### RBAC и безопасность

Для корректной работы Jaeger v2 (особенно в режиме DaemonSet или при использовании процессоров типа `k8sattributes`) требуются специфичные права доступа:

1. **Ресурс `pods`, `nodes`, `namespaces`:** Права на `get`, `watch`, `list` для обогащения спанов метаданными Kubernetes.
2. **Ресурс `events`:** Для сбора событий кластера.
3. **Security Context:** Рекомендуется запускать коллектор от не-привилегированного пользователя, если не требуется доступ к `hostPath` (например, для чтения логов).

**Пример ServiceAccount и RBAC:**

```yaml
# service-account.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jaeger-collector
  namespace: observability

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: jaeger-collector
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes", "namespaces", "events"]
    verbs: ["get", "watch", "list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: jaeger-collector
subjects:
  - kind: ServiceAccount
    name: jaeger-collector
    namespace: observability
roleRef:
  kind: ClusterRole
  name: jaeger-collector
  apiGroup: rbac.authorization.k8s.io
```

### Взаимодействие с Service Mesh

При использовании Istio или Linkerd необходимо обеспечить корректную передачу заголовков:
*   **W3C Trace Context (`traceparent`):** Стандарт по умолчанию для Jaeger v2 и OTel.
*   **B3 Propagation:** Часто используется в Istio. Jaeger v2 может принимать B3 и конвертировать его в W3C для внутреннего хранения.

**Конфигурация Istio для трассировки:**

```yaml
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: mesh-default
  namespace: istio-system
spec:
  tracing:
    - providers:
        - name: otel
      randomSamplingPercentage: 10
```

### Ресурсные требования в Kubernetes

| Роль | CPU (Request/Limit) | RAM (Request/Limit) | Хранилище | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Collector (Deployment)** | 500m / 2000m | 512Mi / 2Gi | Не требуется | Зависит от количества OTLP-соединений |
| **Collector (DaemonSet)** | 200m / 1000m | 256Mi / 1Gi | Не требуется | На каждый узел; меньше overhead |
| **Query** | 250m / 1000m | 256Mi / 1Gi | Не требуется | Зависит от числа пользователей UI |
| **ClickHouse** | 2 / 4 | 4Gi / 8Gi | PVC 100Gi+ | Минимум 3 узла для HA |
| **Elasticsearch** | 2 / 4 | 4Gi / 8Gi | PVC 100Gi+ | Минимум 3 узла для HA |

### PersistentVolume и хранилище

Для production-развертываний с ClickHouse или Elasticsearch требуется настройка персистентного хранилища:

```yaml
# storage-class.yaml (пример для ClickHouse)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: kubernetes.io/aws-ebs
parameters:
  type: gp3
  iops: "10000"
  throughput: "500"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true

---
# persistent-volume-claim.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jaeger-clickhouse-data
  namespace: observability
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 200Gi
```

### HorizontalPodAutoscaler для Collector

При изменяющейся нагрузке настройте HPA для автоматического масштабирования коллектора:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: jaeger-collector
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: otelcol_receiver_accepted_spans
        target:
          type: AverageValue
          averageValue: "5000"
```

### NetworkPolicy для изоляции трафика

Рекомендуется ограничить сетевой доступ к компонентам Jaeger:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jaeger-allow-ingress
  namespace: observability
spec:
  podSelector:
    matchLabels:
      app: jaeger
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: default
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
        - protocol: TCP
          port: 16686
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 9000  # ClickHouse
        - protocol: TCP
          port: 9092  # Kafka
```

---

## Практические сценарии

### Сценарий 1: Развертывание Jaeger v2 через OpenTelemetry Operator

В Jaeger v2 рекомендуется использовать `kind: OpenTelemetryCollector` с образом Jaeger.

#### Предварительные требования

- Kubernetes кластер версии 1.24+
- Helm 3.10+ или kubectl с поддержкой CRD
- 4 CPU и 8GB RAM на узле для production-компонентов

#### Полная конфигурация Production-ready Collector (Deployment mode)

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  mode: deployment
  replicas: 3
  image: jaegertracing/jaeger:2.0.0
  serviceAccount: jaeger-collector
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
          http:
    processors:
      k8sattributes:
        extract:
          metadata: [k8s.pod.name, k8s.namespace.name, k8s.node.name]
      batch:
      memory_limiter:
        check_interval: 1s
        limit_mib: 1536
        spike_limit_mib: 512
    exporters:
      jaeger_storage_exporter:
        trace_storage:
          type: clickhouse
          options:
            clickhouse:
              endpoint: "tcp://clickhouse-server.observability.svc:9000"
              database: jaeger_v2
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [k8sattributes, memory_limiter, batch]
          exporters: [jaeger_storage_exporter]
```

**Валидация:**

1. Применить конфигурацию: `kubectl apply -f otel-collector.yaml`.
2. Проверить статус подов: `kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-collector`.
3. Проверить логи: `kubectl logs -n observability -l app.kubernetes.io/name=jaeger-collector --tail=50`.
4. Отправить тестовый спан и убедиться, что он появился в UI через `http://localhost:16686`.
5. Проверить метрики: `curl http://jaeger-collector.observability.svc:8888/metrics | grep otelcol_receiver_accepted_spans` — количество отправленных спанов должно расти.

### Сценарий 2: Автоматическая инструментация (Instrumentation CR)

OpenTelemetry Operator позволяет автоматически внедрять SDK в приложения.

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: java-instrumentation
  namespace: my-app
spec:
  exporter:
    endpoint: http://jaeger-collector.observability.svc:4317
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_traceidratio
    argument: "0.1" # 10% сэмплирования
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:latest
```

Для активации добавьте аннотацию в под приложения:
`instrumentation.opentelemetry.io/inject-java: "true"`

**Валидация:**

1. Применить Instrumentation: `kubectl apply -f instrumentation.yaml`.
2. Добавить аннотацию в Deployment приложения.
3. Перезапустить под: `kubectl rollout restart deployment/my-app -n my-app`.
4. Проверить, что в поде появился init-контейнер: `kubectl describe pod -n my-app -l app=my-app`.
5. Отправить тестовый запрос: `curl http://my-app.my-app.svc:8080/api`.
6. Проверить метрики Collector: `curl http://jaeger-collector.observability.svc:8888/metrics | grep otelcol_receiver_accepted_spans`.

### Сценарий 3: DaemonSet режим для сбора телеметрии с узлов

Для сбора данных с каждого узла кластера (системные метрики, eBPF-данные) разверните Collector как DaemonSet:

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-agent
  namespace: observability
spec:
  mode: daemonset
  image: jaegertracing/jaeger:2.0.0
  serviceAccount: jaeger-collector
  hostPID: true  # Требуется для eBPF и чтения системных процессов
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  config: |
    receivers:
      hostmetrics:
        collection_interval: 10s
      otlp:
        protocols:
          grpc:
          http:
    processors:
      k8sattributes:
        auth_type: serviceAccount
        passthrough: false
        extract:
          metadata: [k8s.pod.name, k8s.namespace.name, k8s.node.name]
      batch:
    exporters:
      jaeger_storage_exporter:
        trace_storage:
          type: clickhouse
          options:
            clickhouse:
              endpoint: "tcp://clickhouse-server.observability.svc:9000"
              database: jaeger_v2
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [k8sattributes, batch]
          exporters: [jaeger_storage_exporter]
        metrics:
          receivers: [hostmetrics]
          processors: [batch]
          exporters: [jaeger_storage_exporter]
```

**Валидация:**

1. Применить DaemonSet: `kubectl apply -f daemonset.yaml`.
2. Проверить, что поды запущены на всех узлах: `kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-agent -o wide`.
3. Проверить права: `kubectl auth can-i get pods --as=system:serviceaccount:observability:jaeger-collector`.
4. Проверить метрики узла: `curl http://<node-ip>:8888/metrics | grep hostmetrics_cpu`.

### Сценарий 4: Настройка HPA для горизонтального масштабирования Collector

При изменяющейся нагрузке HPA автоматически регулирует количество реплик коллектора:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: jaeger-collector
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: otelcol_receiver_accepted_spans
        target:
          type: AverageValue
          averageValue: "5000"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
```

**Валидация:**

1. Применить HPA: `kubectl apply -f hpa.yaml`.
2. Отправить нагрузку: `ab -n 10000 -c 100 -p spans.json -T application/json http://jaeger-collector.observability.svc:4318/v1/traces`.
3. Проверить реакцию HPA: `kubectl get hpa -n observability jaeger-collector -w`.
4. Убедиться, что реплики увеличились: `kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-collector`.
5. После завершения нагрузки убедиться, что реплики уменьшились до минимума.

### Сценарий 5: RBAC и Security Context для Collector

Для безопасного развертывания Collector в Kubernetes требуется минимальный набор прав и hardened Security Context:

```yaml
# service-account.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jaeger-collector
  namespace: observability

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: jaeger-collector
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes", "namespaces", "events"]
    verbs: ["get", "watch", "list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: jaeger-collector
subjects:
  - kind: ServiceAccount
    name: jaeger-collector
    namespace: observability
roleRef:
  kind: ClusterRole
  name: jaeger-collector
  apiGroup: rbac.authorization.k8s.io

---
# pod-security-policy.yaml (через Pod Security Standards)
apiVersion: v1
kind: Pod
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  serviceAccountName: jaeger-collector
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: collector
      image: jaegertracing/jaeger:2.0.0
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: var-run
          mountPath: /var/run
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: 2000m
          memory: 2Gi
  volumes:
    - name: tmp
      emptyDir: {}
    - name: var-run
      emptyDir: {}
```

**Валидация:**

1. Применить RBAC: `kubectl apply -f service-account.yaml`.
2. Применить Pod: `kubectl apply -f pod-security-policy.yaml`.
3. Проверить, что под запустился: `kubectl get pods -n observability`.
4. Проверить Security Context: `kubectl get pod -n observability -o jsonpath='{.spec.securityContext}'`.
5. Проверить права: `kubectl auth can-i get pods --as=system:serviceaccount:observability:jaeger-collector`.

### Сценарий 6: NetworkPolicy для изоляции трафика

Рекомендуется ограничить сетевой доступ к компонентам Jaeger:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: jaeger-allow-ingress
  namespace: observability
spec:
  podSelector:
    matchLabels:
      app: jaeger
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: default
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
        - protocol: TCP
          port: 16686
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 9000  # ClickHouse
        - protocol: TCP
          port: 9092  # Kafka
```

**Валидация:**

1. Применить NetworkPolicy: `kubectl apply -f network-policy.yaml`.
2. Проверить политику: `kubectl describe networkpolicy -n observability jaeger-allow-ingress`.
3. Проверить, что трафик из разрешенного неймспейса проходит: `curl http://jaeger-collector.observability.svc:4317/health`.
4. Проверить, что трафик из запрещенного неймспейса блокируется: `kubectl exec -it <pod-in-other-ns> -- curl --connect-timeout 2 http://jaeger-collector.observability.svc:4317/health` (должен вернуть ошибку timeout).

### Сценарий 7: Развертывание через Helm (Kubernetes)

Для Kubernetes рекомендуется использовать официальные Helm-чарты или OpenTelemetry Operator. Пример установки через Helm:

```bash
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update

# Установка в режиме Production
helm install jaeger jaegertracing/jaeger \
  --namespace observability --create-namespace \
  --set collector.replicas=3 \
  --set query.replicas=2 \
  --set storage.type=clickhouse \
  --set storage.clickhouse.endpoint=http://clickhouse:8123
```

**Валидация:**

1. Проверить поды: `kubectl get pods -n observability -l app.kubernetes.io/name=jaeger`.
2. Открыть порт-forward: `kubectl port-forward -n observability svc/jaeger-query 16686:16686`.
3. Перейти в UI и убедиться, что сервисы регистрируются.

### Сценарий 8: Сквозная трассировка через Ingress-NGINX

Интеграция позволяет видеть путь запроса от момента входа в кластер.

**Настройка в ConfigMap контроллера:**

| Параметр | Значение |
| :--- | :--- |
| `enable-opentelemetry` | `"true"` |
| `otlp-collector-host` | `jaeger-collector.observability.svc` |
| `otlp-collector-port` | `"4317"` |
| `otel-propagation-policy` | `"w3c"` |

```bash
# Применение конфигурации
kubectl edit configmap nginx-configuration -n ingress-nginx

# Перезапуск Ingress Controller
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

**Валидация:**

1. Отправить запрос через Ingress: `curl -X GET http://my-app.example.com/api`.
2. Проверить, что в Jaeger UI появилась трасса с атрибутом `ingress.nginx` или `http.host`.
3. Убедиться, что заголовок `traceparent` корректно передается от Ingress к приложению.

### Сценарий 9: Создание Java TrustStore для безопасного подключения

При использовании внешних хранилищ (OpenSearch/Elasticsearch) с TLS требуется проброс сертификатов.

1. **Создание TrustStore:**
    ```bash
    kubectl run jdk-helper --image=openjdk:11 --restart=Never -- sleep 3600
    kubectl cp ca.pem jdk-helper:/tmp/ca.pem
    kubectl exec jdk-helper -- keytool -import -alias os-ca -file /tmp/ca.pem -keystore /tmp/truststore.jks -storepass changeit -noprompt
    kubectl cp jdk-helper:/tmp/truststore.jks ./truststore.jks
    kubectl create secret generic jaeger-truststore --from-file=truststore.jks=./truststore.jks
    ```

2. **Использование в подах:**
    Монтируйте секрет и передавайте переменные: `JAVA_OPTS="-Djavax.net.ssl.trustStore=/etc/trust/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"`.

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Поды Collector не запускаются** | Отсутствуют права RBAC или неверный ServiceAccount | `kubectl describe pod -n observability -l app=jaeger-collector` — ошибка `Forbidden` или `Unauthorized` | Создать ServiceAccount, ClusterRole и ClusterRoleBinding. Проверить `kubectl auth can-i` |
| **Instrumentation не работает** | Отсутствует аннотация или версия CRD несовместима | `kubectl get instrumentation`, `kubectl describe pod` — нет init-контейнера | Проверить версию CRD (`kubectl get crd instrumentations.opentelemetry.io`), добавить аннотацию `instrumentation.opentelemetry.io/inject-java: "true"` |
| **Спаны не поступают в Collector** | NetworkPolicy блокирует трафик или неверный endpoint OTLP | `kubectl exec -it <app-pod> -- curl -v http://jaeger-collector:4317/health` | Открыть порт 4317/4318 в NetworkPolicy, проверить переменную `OTEL_EXPORTER_OTLP_ENDPOINT` |
| **Collector падает с OOM** | Отсутствует `memory_limiter` processor или недостаточно лимитов в pod | `kubectl top pods -n observability`, `kubectl logs -n observability <collector-pod>` | Добавить `memory_limiter` в конфигурацию, увеличить `limits.memory` в Deployment |
| **k8sattributes не обогащает спаны** | ServiceAccount не имеет прав на ресурсы pods/nodes | Метрики `otelcol_processor_k8sattributes_errors_total` растут | Добавить права `get`, `watch`, `list` на `pods`, `nodes`, `namespaces` в ClusterRole |
| **Clock Skew искажает Timeline** | Рассинхронизация NTP между серверами | Спаны отображаются в будущем или с отрицательной длительностью | Настроить `chrony` или `systemd-timesyncd` на всех узлах, проверить `clock_skew` в Jaeger UI |
| **HPA не масштабирует Collector** | Отсутствуют метрики или неверный `metric` в HPA | `kubectl describe hpa -n observability jaeger-collector` — `unknown metric` | Убедиться, что Collector экспортирует метрики на порт 8888, добавить `external.metrics.k8s.io` API (через Metrics Server или Prometheus Adapter) |
| **Ингресс теряет заголовки трассировки** | NGINX не настроен на пропуск `traceparent`/`tracestate` | В Jaeger UI трассы не связаны между собой | Установить `enable-opentelemetry: "true"` и `otel-propagation-policy: "w3c"` в ConfigMap ingress-nginx |
| **Downward API не передает метаданные** | Неверный `fieldRef` или `resourceFieldRef` | Переменные окружения пустые или содержат `none` | Проверить `fieldPath: metadata.name`, `fieldPath: metadata.namespace` в конфигурации пода |
| **TrustStore не подгружается** | Неверный путь к секрету или права на чтение | Приложение падает с `SSLHandshakeException` | Проверить `volumeMounts` и `volumes` в Deployment, убедиться что секрет существует в том же неймспейсе |

---

## Лучшие практики

1.  **Используйте OpenTelemetry Operator:** Для новых проектов предпочитайте OpenTelemetry Operator вместо устаревшего Jaeger Operator. Он обеспечивает единый стандарт управления телеметрией в кластере.
2.  **RBAC по принципу наименьших привилегий:** Выдавайте Collector только права на чтение метаданных pods/nodes/namespaces. Не используйте `cluster-admin`.
3.  **Resource Requests и Limits:** Всегда задавайте `requests` и `limits` для CPU и памяти. Collector в Kubernetes чувствителен к OOM — без `memory_limiter` processor всплеск трафика убьет под.
4.  **PodDisruptionBudget:** Для production-компонентов Collector и Query настройте PDB, чтобы плановые работы (drain узлов) не выводили все реплики одновременно:
    ```yaml
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: jaeger-collector-pdb
      namespace: observability
    spec:
      minAvailable: 2
      selector:
        matchLabels:
          app.kubernetes.io/name: jaeger-collector
    ```
5.  **NetworkPolicy:** Изолируйте неймспейс observability. Разрешете только необходимые порты (4317, 4318, 16686) и запретите исходящий трафик в неизвестные неймспейсы.
6.  **Security Context:** Запускайте поды от не-привилегированного пользователя (`runAsNonRoot: true`, `runAsUser: 1000`), отключайте `allowPrivilegeEscalation` и сбрасывайте все capabilities (`drop: ALL`).
7.  **Семантические конвенции OpenTelemetry:** Используйте стандартные атрибуты (`http.method`, `db.system`, `exception.type`). Это обеспечивает совместимость UI, автоматические дашборды и корреляцию с Tempo/Grafana.
8.  **Мониторинг самого Jaeger:** Настройте алерты на метрики Collector'а: `otelcol_receiver_refused_spans_total` (прием данных отклоняется), `otelcol_exporter_send_failed_spans_total` (ошибки записи), `otelcol_processor_memory_limiter_refused_spans_total` (OOM риск). Отсутствие спанов в хранилище чаще всего является результатом падения экспортера, а не проблем в инструментации приложений.
9.  **StorageClass и TTL:** Выбирайте StorageClass с высокой IOPS (gp3, io2) для ClickHouse. Настройте TTL на уровне таблицы для автоматического удаления старых трейсов.
10. **Версионирование:** Фиксируйте версии образов Jaeger и Operator в манифестах. Избегайте тегов `latest` в production.

---

## Очистка окружения

```bash
# Удаление OpenTelemetryCollector и Instrumentation ресурсов
kubectl delete opentelemetrycollectors -n observability --all
kubectl delete instrumentations -n observability --all

# Удаление RBAC ресурсов
kubectl delete serviceaccount,clusterrole,clusterrolebinding -n observability -l app=jaeger

# Удаление HPA
kubectl delete hpa -n observability jaeger-collector

# Удаление DaemonSet/Deployment
kubectl delete deployment -n observability jaeger-collector
kubectl delete daemonset -n observability jaeger-agent

# Удаление Service и Ingress
kubectl delete service,ingress -n observability -l app=jaeger

# Удаление PersistentVolumeClaim (ВНИМАНИЕ: удалит данные!)
kubectl delete pvc -n observability --all

# Удаление NetworkPolicy
kubectl delete networkpolicy -n observability -l app=jaeger

# Удаление ConfigMap и Secret
kubectl delete configmap,secret -n observability -l app=jaeger

# Удаление Helm-релиза (если использовался Helm)
helm uninstall jaeger -n observability

# Удаление неймспейса (полная очистка)
kubectl delete namespace observability

# Проверка отсутствия "подвисших" ресурсов
kubectl get all -n observability
kubectl get pvc -n observability
kubectl get networkpolicy -n observability
```

---

## Дополнительная информация

**Смежные темы:**

* Детальное описание компонентов и потоков данных: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Методы локального и production запуска: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Глубокая диагностика и Query API: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**
* Query API Reference: **[Query API Jaeger](./jaeger_query_api.md)**
* Миграция с v1 на v2: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
* Capacity Planning: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Хранилища и бэкенды: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* HA и Disaster Recovery: **[High Availability и DR](./jaeger_high_availability.md)**
* Интеграция с Grafana: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* Service Mesh Integration: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* OTLP Configuration: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* eBPF и Auto-instrumentation: **[eBPF и автоматическая инструментация](./jaeger_ebpf_auto_instrumentation.md)**
* Multi-tenancy: **[Multi-tenancy и изоляция](./jaeger_multi_tenancy.md)**
* Security Hardening: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Стандарт OTLP: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**

### См. также

* [Official Jaeger Kubernetes Guide](https://www.jaegertracing.io/docs/latest/deployment/kubernetes/)
* [OpenTelemetry Operator Documentation](https://opentelemetry.io/docs/kubernetes/operator/)
