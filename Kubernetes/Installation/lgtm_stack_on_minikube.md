# Развертывание стека LGTM и OpenTelemetry на Minikube

## Определения

- **Стек LGTM (Loki, Grafana, Tempo, Mimir)**: Современный, полностью интегрированный стек наблюдаемости с открытым исходным кодом от Grafana Labs. Он включает в себя:
    - **[Loki](../Loki/loki_overview.md)**: Система для сбора и агрегации логов, оптимизированная для экономичного хранения.
    - **[Grafana](../Grafana/grafana_overview.md)**: Платформа для визуализации и анализа данных, позволяющая объединять метрики, логи и трейсы в едином интерфейсе.
    - **[Tempo](../Tempo/tempo_overview.md)**: Высокомасштабируемое хранилище для распределенных трассировок.
    - **[Mimir](../Mimir/mimir_overview.md)**: Горизонтально масштабируемое хранилище временных рядов для метрик Prometheus.
    Более подробно концепция описана в [обзоре наблюдаемости](../Concepts/Observability_and_Monitoring/observability_overview.md).

- **[OpenTelemetry (OTel)](../OpenTelemetry/opentelemetry_overview.md)**: Открытый стандарт и набор инструментов для сбора, обработки и экспорта телеметрических данных (логов, метрик и трассировок). Он позволяет унифицировать инструментирование приложений независимо от используемого бэкенда для анализа.

- **[Minikube](https://minikube.sigs.k8s.io/docs/)**: Инструмент для запуска локального однонодового кластера [Kubernetes](../../Kubernetes/kubernetes_overview.md). Идеально подходит для разработки, обучения и тестирования.

- **[Docker Registry](../../Docker/docker_registries.md)**: Сервис для хранения и распространения Docker-образов.

- **[Cert-Manager](../../Kubernetes/ToolsUtilities/cert_manager.md)**: Нативный для Kubernetes инструмент для управления TLS-сертификатами.

## Основные концепции

### Архитектура решения

Данное руководство описывает создание полноценной среды наблюдаемости в локальном кластере Minikube. Архитектура включает следующие ключевые компоненты:

1.  **Приложение**: Тестовое Java-приложение, инструментированное с помощью [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md) для генерации логов, метрик и трассировок.
2.  **OpenTelemetry Collector**: Центральный компонент [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md), который получает телеметрию от приложения по протоколу OTLP. Он обрабатывает данные и экспортирует их в соответствующие бэкенды:
    - Логи → **Loki**
    - Трассировки → **Tempo**
    - Метрики → **Mimir** (через Prometheus)
3.  **Стек LGTM**: Набор инструментов для хранения и визуализации телеметрии. **Grafana** выступает в роли единого интерфейса для анализа всех собранных данных.
4.  **Вспомогательные компоненты**:
    - **[Cert-Manager](../../Kubernetes/ToolsUtilities/cert_manager.md)**: Управляет TLS-сертификатами для защищенного доступа к веб-интерфейсам через [Ingress](../../Kubernetes/Networking/ingress.md).
    - **[Local Docker Registry](../../Docker/docker_registries.md)**: Позволяет хранить и распространять кастомные Docker-образы внутри кластера без необходимости публиковать их в Docker Hub.

## Практические сценарии

### Сценарий: Развертывание стека LGTM и OpenTelemetry на Minikube

Этот практический сценарий демонстрирует пошаговый процесс настройки полного стека наблюдаемости для тестового приложения.

#### 1. Предварительные требования

*   **[Docker](../../Docker/docker_overview.md)**: Для запуска Minikube.
*   **[Git](../../Git/git_basics.md)**: Для клонирования репозиториев.
*   **[Minikube](https://minikube.sigs.k8s.io/docs/)**: Локальный кластер [Kubernetes](../../Kubernetes/kubernetes_overview.md).
*   **[kubectl](../../Kubernetes/kubernetes_overview.md)**: Утилита командной строки для управления кластерами Kubernetes.
*   **[Helm](../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)**: Менеджер пакетов для Kubernetes.

#### 2. Подготовка окружения

##### 2.1. Клонирование репозиториев

```bash
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git
git clone https://github.com/memori-dev/observability-practice.git
```

##### 2.2. Добавление Helm репозиториев

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://helm.twun.io
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

##### 2.3. Запуск Minikube

```bash
minikube start --cpus 4 --memory 8192mb --addons ingress --insecure-registry "10.0.0.0/24" --driver=docker
```
*   `--cpus 4 --memory 8192mb`: Рекомендуемые ресурсы для стабильной работы стека.
*   `--addons ingress`: Включает Ingress-контроллер.
*   `--insecure-registry "10.0.0.0/24"`: Позволяет использовать локальный Docker Registry без HTTPS.
*   `--driver=docker`: Использует Docker в качестве драйвера.

#### 3. Развертывание вспомогательных компонентов

##### 3.1. Cert-Manager

Для управления TLS-сертификатами в кластере используется **[cert-manager](../ToolsUtilities/cert_manager.md)**. Этот компонент необходим для автоматического выпуска сертификатов для Ingress-ресурсов (Grafana, Loki и т.д.).

В данном руководстве мы будем использовать самоподписанные сертификаты.

1.  **Установите cert-manager**, следуя официальной инструкции, или воспользуйтесь нашей заметкой: **[Установка cert-manager](../ToolsUtilities/cert_manager.md#Установка)**.

2.  **Создайте ClusterIssuer** для выпуска самоподписанных сертификатов. Это позволит обеспечить безопасное взаимодействие с веб-интерфейсами внутри кластера.

    ```bash
    # Создание корневого CA
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

##### 3.2. Локальный Docker Registry

Разверните локальный Docker Registry, доступный внутри кластера.

```bash
# Установка Docker Registry
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

# Добавление записи в /etc/hosts
echo "$(minikube ip) registry.test" | sudo tee -a /etc/hosts

# Настройка Docker Daemon для работы с insecure registry
minikube ssh "sudo tee /etc/docker/daemon.json <<< '{\"insecure-registries\": [\"registry.test:30000\"]}'"
minikube ssh "sudo systemctl restart docker"
minikube stop && minikube start

# Создание секрета для доступа к registry
kubectl create secret docker-registry regcred \
  --docker-server=registry.test:30000 \
  --docker-username=admin \
  --docker-password=admin \
  --namespace default

kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

#### 4. Развертывание стека LGTM

##### 4.1. Grafana, Prometheus, Alertmanager

Компоненты разворачиваются с помощью чарта [kube-prometheus-stack](../../Prometheus/kubernetes/overview.md), который включает преднастроенные Data Sources для Loki, Tempo и Mimir.

```bash
# Создание Namespace
kubectl create namespace monitoring
kubectl create namespace grafana

# Установка kube-prometheus-stack
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
            url: '$${__value.raw}'
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

# Добавление записи в /etc/hosts
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
```
Пароль администратора Grafana (`prom-operator`) можно также получить командой:
```bash
kubectl get secret --namespace monitoring prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

##### 4.2. Loki, Tempo и Mimir

Разверните остальные компоненты стека.

```bash
# Установка Loki
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
# Установка Tempo
helm upgrade --install tempo grafana/tempo \
  --namespace tempo \
  --create-namespace \
  --set service.type=ClusterIP \
  --set service.port=3200

# Установка Mimir (в данном примере не устанавливается, т.к. используется Prometheus из стека)
# Для полноценного использования Mimir его нужно развернуть отдельно.
```

#### 5. Развертывание OpenTelemetry

##### 5.1. OpenTelemetry Operator

```bash
helm upgrade --install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator \
  --create-namespace
```

##### 5.2. OpenTelemetry Collector

Создайте файл `otel-collector.yaml` и примените его.

```yaml
# otel-collector.yaml
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
        tls:
          insecure: true
      loki:
        endpoint: "http://loki.loki:3100/loki/api/v1/push"
      prometheus:
        endpoint: "http://prometheus-kube-prometheus-prometheus.monitoring:9090/api/v1/write"
        tls:
          insecure: true
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
```bash
kubectl apply -f otel-collector.yaml
```

##### 5.3. OpenTelemetry Auto-Instrumentation

Создайте файл `otel-instrumentation.yaml` для автоматической инъекции агента.

```yaml
# otel-instrumentation.yaml
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

#### 6. Запуск и проверка тестового приложения

##### 6.1. Сборка и отправка Docker-образа

```bash
cd opentelemetry-java-examples/agent/agent-example-app
./gradlew clean bootJar
docker build -t registry.test:30000/agent-example-app:latest .
docker push registry.test:30000/agent-example-app:latest
```

##### 6.2. Запуск приложения с автоматической инструментацией

Аннотация `instrumentation.opentelemetry.io/inject: "true"` указывает оператору внедрить OTel-агент.

```bash
kubectl run agent-example-app \
  --image=registry.test:30000/agent-example-app:latest \
  --port=8080 \
  --labels="app=agent-example-app" \
  --annotations='instrumentation.opentelemetry.io/inject: "true"' \
  --namespace=default
```

##### 6.3. Проверка телеметрии

1.  **Проброс порта**:
    ```bash
    kubectl port-forward pod/$(kubectl get pods -l app=agent-example-app -o jsonpath='{.items[0].metadata.name}') 8080:8080
    ```
2.  **Генерация нагрузки**:
    ```bash
    curl localhost:8080/ping
    ```
3.  **Просмотр в Grafana**: Откройте Grafana (http://grafana.test) и перейдите в раздел Explore.
    *   **Логи**: Выберите Data Source `Loki`, используйте запрос `{service_name="agent-example-app"}`. Вы увидите логи приложения.
    *   **Трассировки**: В логах найдите `traceID` и перейдите по нему в Tempo. Вы увидите полную трассировку запроса.
    *   **Метрики**: Выберите Data Source `Prometheus`, используйте запрос `traces_spanmetrics_latency_bucket{service_name="agent-example-app"}`. Вы увидите метрики, сгенерированные из спанов.

### Альтернативный сценарий: запуск с Java Agent вручную

Этот способ демонстрирует запуск приложения с Java Agent напрямую, без использования OpenTelemetry Operator.

1.  **Сборка образа (без встроенного агента)**:
    Убедитесь, что Dockerfile не содержит инструкций по копированию и активации `opentelemetry-javaagent.jar`.
    ```bash
    cd opentelemetry-java-examples/agent/agent-example-app
    docker build -t registry.test:30000/agent-example-app-no-agent:latest .
docker push registry.test:30000/agent-example-app-no-agent:latest
    ```
2.  **Запуск пода с явным указанием агента**:
    Этот метод требует, чтобы JAR-файл агента был доступен в контейнере (например, через `initContainer` или путем встраивания в образ).
    ```bash
    kubectl run agent-example-app-manual \
      --image=registry.test:30000/agent-example-app-no-agent:latest \
      --port=8080 \
      --labels="app=agent-example-app-manual" \
      --env="JAVA_TOOL_OPTIONS=-javaagent:/path/to/opentelemetry-javaagent.jar" \
      --env="OTEL_EXPORTER_OTLP_ENDPOINT=http://default.opentelemetry:4317" \
      --env="OTEL_LOGS_EXPORTER=otlp" \
      --env="OTEL_SERVICE_NAME=agent-example-app-manual"
    ```