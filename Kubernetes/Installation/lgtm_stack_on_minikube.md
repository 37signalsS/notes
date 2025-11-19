# Развертывание стека LGTM и OpenTelemetry на Minikube

Это пошаговое руководство описывает процесс развертывания полного стека Observability (Loki, Grafana, Tempo, Mimir) и OpenTelemetry на локальном кластере Kubernetes, запущенном с помощью Minikube. Руководство основано на практической части вебинара "DevOps by Rebrain: Знакомство с Observability".

## 1. Предварительные требования

Убедитесь, что у вас установлены следующие инструменты:

*   **Docker**: Для запуска Minikube.
*   **Git**: Для клонирования репозиториев.
*   **Minikube**: Локальный кластер Kubernetes.
*   **kubectl**: Утилита командной строки для управления кластерами Kubernetes.
*   **Helm**: Менеджер пакетов для Kubernetes.
*   **OpenLens (опционально)**: Для удобного просмотра состояния кластера.

## 2. Подготовка окружения

### 2.1. Клонирование репозиториев

Клонируйте репозиторий с примерами OpenTelemetry и репозиторий с практикой LGTM:

```bash
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git
git clone https://github.com/memori-dev/observability-practice.git
```

### 2.2. Добавление Helm репозиториев

Добавьте необходимые Helm репозитории:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://helm.twun.io
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

### 2.3. Запуск Minikube

Запустите Minikube с необходимыми опциями:

```bash
minikube start --cpus 4 --memory 8192mb --addons ingress --insecure-registry "10.0.0.0/24" --driver=docker
```

*   `--cpus 4 --memory 8192mb`: Рекомендуемые ресурсы для стабильной работы стека.
*   `--addons ingress`: Включает Ingress-контроллер.
*   `--insecure-registry "10.0.0.0/24"`: Позволяет использовать локальный Docker Registry без HTTPS.
*   `--driver=docker`: Использует Docker в качестве драйвера.

### 2.4. Настройка OpenLens (опционально)

Для удобства работы с Minikube и просмотра логов/подов, установите расширение `OpenLens not pod menu`:

1.  В OpenLens перейдите в `File -> Extensions`.
2.  Добавьте URL `https://github.com/AliBK/openlens-not-pod-menu`.
3.  Нажмите `Install`.

## 3. Развертывание вспомогательных компонентов

### 3.1. Cert-Manager

Установите Cert-Manager для управления TLS-сертификатами:

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.14.0 \
  --set installCRDs=true
```

Примените конфигурацию ClusterIssuer для автоматического выпуска сертификатов:

```bash
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: minikube-ca
spec:
  ca:
    secretName: minikube-ca-secret
EOF

kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: minikube-ca-secret
  namespace: cert-manager
spec:
  isCA: true
  duration: 8760h # 1y
  secretName: minikube-ca-secret
  privateKey:
    algorithm: RSA
    size: 2048
  commonName: "minikube-ca"
  issuerRef:
    name: minikube-ca
    kind: ClusterIssuer
    group: cert-manager.io
EOF
```

### 3.2. Локальный Docker Registry

Разверните локальный Docker Registry в Minikube:

```bash
helm upgrade --install docker-registry twuni/docker-registry \
  --namespace docker-registry \
  --create-namespace \
  --set service.type=NodePort \
  --set service.nodePort=30000 \
  --set ingress.enabled=true \
  --set ingress.host=registry.test \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=registry-tls \
  --set ingress.tls.issuerName=minikube-ca \
  --set ingress.tls.issuerKind=ClusterIssuer
```

Добавьте запись в `/etc/hosts` для разрешения имени `registry.test`:

```bash
echo "$(minikube ip) registry.test" | sudo tee -a /etc/hosts
```

Настройте Docker Daemon для работы с insecure registry (может потребоваться перезапуск Docker и Minikube):

```bash
minikube ssh "sudo tee /etc/docker/daemon.json <<EOF
{
  \"insecure-registries\": [\"registry.test:30000\"]
}
EOF"
minikube ssh "sudo systemctl restart docker"
minikube stop && minikube start
```

Создайте секрет для доступа к Registry из кластера и пропатчите `default` ServiceAccount:

```bash
kubectl create secret docker-registry regcred \
  --docker-server=registry.test:30000 \
  --docker-username=admin \
  --docker-password=admin \
  --namespace default

kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

## 4. Развертывание стека LGTM (Grafana, Loki, Tempo, Mimir)

Мы будем использовать `kube-prometheus-stack` для развертывания Grafana, Prometheus и Alertmanager, а Loki и Tempo развернем отдельно.

### 4.1. Grafana, Prometheus, Alertmanager (через kube-prometheus-stack)

Создайте необходимые Namespace:

```bash
kubectl create namespace monitoring
kubectl create namespace grafana
```

Разверните `kube-prometheus-stack` с кастомными значениями, которые включают Ingress для Grafana и преднастроенные Data Sources для Loki, Tempo, Mimir:

```bash
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f - <<EOF
grafana:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - grafana.test
    tls:
      - hosts:
          - grafana.test
        secretName: grafana-tls
    ingressClassName: nginx
  adminPassword: prom-operator
  additionalDataSources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki.loki:3100
      version: 1
      editable: true
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\\w+)"
            name: TraceID
            url: "$${__value.raw}"
    - name: Tempo
      type: tempo
      access: proxy
      url: http://tempo.tempo:3200
      version: 1
      editable: true
      jsonData:
        httpHeaderName: "X-Scope-OrgID"
        httpHeaderValue: "tempo"
        serviceMap:
          datasourceUid: prometheus
        tracesToLogs:
          datasourceUid: loki
          filterByTraceID: true
          filterBySpanID: false
          spanStartTimeShift: 1h
          spanEndTimeShift: 1h
          lokiSearch: true
        tracesToMetrics:
          datasourceUid: prometheus
          tags: "{job=\"agent-example-app\"}"
          map:
            - operationName: "ping"
              spanKind: "server"
              metricQuery: "sum(rate(traces_spanmetrics_latency_bucket{span_kind=\"server\", service_name=\"agent-example-app\", operation=\"ping\", le=\"$bucket\"}[1m])) by (le)"
    - name: Mimir
      type: prometheus
      access: proxy
      url: http://mimir.mimir:8080
      version: 1
      editable: true
EOF
```

Добавьте запись в `/etc/hosts` для разрешения имени `grafana.test`:

```bash
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
```

Получите пароль администратора Grafana:

```bash
kubectl get secret --namespace monitoring prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

### 4.2. Loki

Разверните Loki:

```bash
helm upgrade --install loki grafana/loki \
  --namespace loki \
  --create-namespace \
  --set service.type=ClusterIP \
  --set service.port=3100 \
  --set ingress.enabled=true \
  --set ingress.host=loki.test \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=loki-tls \
  --set ingress.tls.issuerName=minikube-ca \
  --set ingress.tls.issuerKind=ClusterIssuer
```

### 4.3. Tempo

Разверните Tempo:

```bash
helm upgrade --install tempo grafana/tempo \
  --namespace tempo \
  --create-namespace \
  --set service.type=ClusterIP \
  --set service.port=3200 \
  --set ingress.enabled=true \
  --set ingress.host=tempo.test \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=tempo-tls \
  --set ingress.tls.issuerName=minikube-ca \
  --set ingress.tls.issuerKind=ClusterIssuer
```

## 5. Развертывание OpenTelemetry Collector и Operator

### 5.1. OpenTelemetry Operator

Установите OpenTelemetry Operator:

```bash
helm upgrade --install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator \
  --create-namespace
```

### 5.2. OpenTelemetry Collector (управляемый оператором)

Создайте манифест `otel-collector.yaml` для OpenTelemetry Collector:

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: default
  namespace: opentelemetry
spec:
  mode: deployment
  replicas: 1
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
          http:
    processors:
      batch:
      attributes:
        actions:
          - key: service.name
            from_attribute: k8s.pod.name
            action: upsert
      spanmetrics:
        metrics_exporter: prometheus
        dimensions:
          - name: span.name
            default: "unspecified"
          - name: http.method
            default: "unspecified"
          - name: http.url
            default: "unspecified"
          - name: http.status_code
            default: "unspecified"
        histogram:
          explicit_bounds: [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]
    exporters:
      otlp:
        endpoint: "tempo.tempo:4317"
      loki:
        endpoint: "http://loki.loki:3100/loki/api/v1/push"
      prometheus:
        endpoint: "http://prometheus-kube-prometheus-prometheus.monitoring:9090/api/v1/write"
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch, spanmetrics]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [batch]
          exporters: [prometheus]
        logs:
          receivers: [otlp]
          processors: [batch, attributes]
          exporters: [loki]
```

Примените манифест:

```bash
kubectl apply -f otel-collector.yaml
```

### 5.3. OpenTelemetry Instrumentation (для автоматической инструментации)

Создайте манифест `otel-instrumentation.yaml` для настройки автоматической инструментации:

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: default
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://default.opentelemetry:4317
  java:
    env:
      - name: OTEL_LOGS_EXPORTER
        value: otlp
      - name: OTEL_SERVICE_NAME
        value: "$(OTEL_RESOURCE_ATTRIBUTES_SERVICE_NAME)"
    resources:
      limits:
        cpu: 200m
        memory: 256Mi
      requests:
        cpu: 100m
        memory: 128Mi
```

Примените манифест:

```bash
kubectl apply -f otel-instrumentation.yaml
```

## 6. Запуск тестового приложения с OpenTelemetry

### 6.1. Сборка Docker образа приложения

Перейдите в директорию `opentelemetry-java-examples/agent/agent-example-app` и соберите Docker образ:

```bash
cd opentelemetry-java-examples/agent/agent-example-app
./gradlew clean bootJar
docker build -t registry.test:30000/agent-example-app:latest .
docker push registry.test:30000/agent-example-app:latest
```

### 6.2. Запуск приложения с автоматической инструментацией

Запустите приложение в Minikube, используя аннотацию `instrumentation.opentelemetry.io/inject: "true"` для автоматической инструментации:

```bash
kubectl run agent-example-app \
  --image=registry.test:30000/agent-example-app:latest \
  --port=8080 \
  --labels="app=agent-example-app" \
  --annotations="instrumentation.opentelemetry.io/inject=true"
```

### 6.3. Проверка телеметрии

1.  **Port Forward**: Перенаправьте порт приложения для доступа:
    ```bash
    kubectl port-forward pod/$(kubectl get pods -l app=agent-example-app -o jsonpath='{.items[0].metadata.name}') 8080:8080
    ```
2.  **Генерация нагрузки**: Отправьте несколько запросов:
    ```bash
    curl localhost:8080/ping
    ```
3.  **Просмотр в Grafana**: Откройте Grafana (http://grafana.test) и перейдите в раздел Explore.
    *   **Логи**: Выберите Data Source `Loki`, используйте запрос `{service_name="agent-example-app"}`. Вы увидите логи приложения.
    *   **Трассировки**: В логах найдите `traceID` и перейдите по нему в Tempo. Вы увидите полную трассировку запроса.
    *   **Метрики**: Выберите Data Source `Prometheus`, используйте запрос `traces_spanmetrics_latency_bucket{service_name="agent-example-app"}`. Вы увидите метрики, сгенерированные из спанов.

## 7. Запуск приложения с Java Agent (альтернативный способ)

Этот способ демонстрирует запуск приложения с Java Agent напрямую, без использования OpenTelemetry Operator.

### 7.1. Сборка Docker образа приложения (без встроенного агента)

Убедитесь, что в `opentelemetry-java-examples/agent/agent-example-app/Dockerfile` нет строк, связанных с копированием `opentelemetry-javaagent.jar` и параметром `-javaagent`. Затем соберите и запушьте образ:

```bash
cd opentelemetry-java-examples/agent/agent-example-app
# Убедитесь, что Dockerfile не содержит настроек для Java Agent
docker build -t registry.test:30000/agent-example-app-no-agent:latest .
docker push registry.test:30000/agent-example-app-no-agent:latest
```

### 7.2. Запуск приложения с явным указанием Java Agent

Запустите приложение, явно указав Java Agent и параметры OpenTelemetry через переменные окружения:

```bash
kubectl run agent-example-app-manual \
  --image=registry.test:30000/agent-example-app-no-agent:latest \
  --port=8080 \
  --labels="app=agent-example-app-manual" \
  --env="JAVA_TOOL_OPTIONS=-javaagent:/opt/opentelemetry-javaagent.jar" \
  --env="OTEL_EXPORTER_OTLP_ENDPOINT=http://default.opentelemetry:4317" \
  --env="OTEL_LOGS_EXPORTER=otlp" \
  --env="OTEL_SERVICE_NAME=agent-example-app-manual"
```

**Примечание**: Для этого способа вам потребуется вручную скопировать `opentelemetry-javaagent.jar` в образ или использовать `initContainer` для его доставки. В данном примере предполагается, что агент уже доступен в образе или будет доставлен другим способом.

---
*Источник: Основано на материалах из вебинара [DevOps by Rebrain: Знакомство с Observability](rebrain_observability_introduction.md)*
