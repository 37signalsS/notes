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

---

## Базовые концепции

### Паттерны развертывания коллектора

В Jaeger v2 выбор паттерна развертывания коллектора-агента определяет баланс между потреблением ресурсов и сетевой сложностью.

| Паттерн | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Sidecar** | Collector запускается как второй контейнер в каждом поде приложения | Прямая связь по localhost. Индивидуальная настройка для каждого сервиса | Оверхед по ресурсам на каждый инстанс приложения |
| **DaemonSet** | Один экземпляр Collector на каждом узле кластера | Оптимальное использование ресурсов узла. Удобно для сбора системных метрик | Требует настройки `hostPort` и корректной передачи IP узла из приложений |
| **Deployment** | Централизованный кластер коллекторов за Service | Удобство масштабирования (HPA). Централизованное управление политиками сэмплирования | Дополнительный сетевой переход (Extra Hop), требующий учета задержек |

### RBAC и безопасность

Для корректной работы Jaeger v2 (особенно в режиме DaemonSet или при использовании процессоров типа `k8sattributes`) требуются специфичные права доступа:
1.  **Ресурс `pods`, `nodes`, `namespaces`:** Права на `get`, `watch`, `list` для обогащения спанов метаданными Kubernetes.
2.  **Ресурс `events`:** Для сбора событий кластера.
3.  **Security Context:** Рекомендуется запускать коллектор от не-привилегированного пользователя, если не требуется доступ к `hostPath` (например, для чтения логов).

### Взаимодействие с Service Mesh

При использовании Istio или Linkerd необходимо обеспечить корректную передачу заголовков:
*   **W3C Trace Context (`traceparent`):** Стандарт по умолчанию для Jaeger v2 и OTel.
*   **B3 Propagation:** Часто используется в Istio. Jaeger v2 может принимать B3 и конвертировать его в W3C для внутреннего хранения.

---

## Практические сценарии

### Сценарий 1: Развертывание Jaeger v2 через OpenTelemetry Operator

В Jaeger v2 рекомендуется использовать `kind: OpenTelemetryCollector` с образом Jaeger.

#### Полная конфигурация Production-ready Collector (Deployment mode)

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-collector
spec:
  mode: deployment
  replicas: 3
  image: jaegertracing/jaeger:2.0.0
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
          http:
    processors:
      batch:
      k8sattributes:
        extract:
          metadata: [k8s.pod.name, k8s.namespace.name, k8s.node.name]
    exporters:
      jaeger_storage_exporter:
        trace_storage:
          type: clickhouse
          options:
            clickhouse:
              endpoint: "tcp://clickhouse-server:9000"
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [k8sattributes, batch]
          exporters: [jaeger_storage_exporter]
```

### Сценарий 2: Автоматическая инструментация (Instrumentation CR)

OpenTelemetry Operator позволяет автоматически внедрять SDK в приложения.

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: java-instrumentation
spec:
  exporter:
    endpoint: http://jaeger-collector:4317
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:latest
  sampler:
    type: parentbased_always_on
```

Для активации добавьте аннотацию в под приложения:
`instrumentation.opentelemetry.io/inject-java: "true"`

### Сценарий 3: Сквозная трассировка через Ingress-NGINX

Интеграция позволяет видеть путь запроса от момента входа в кластер.

**Настройка в ConfigMap контроллера:**

| Параметр | Значение |
| :--- | :--- |
| `enable-opentelemetry` | `"true"` |
| `otlp-collector-host` | `jaeger-collector.monitoring.svc` |
| `otlp-collector-port` | `"4317"` |
| `otel-propagation-policy` | `"w3c"` |

### Сценарий 4: Создание Java TrustStore для безопасного подключения

При использовании внешних хранилищ (OpenSearch/Elasticsearch) с TLS требуется проброс сертификатов.

1.  **Создание TrustStore:**
    ```bash
    kubectl run jdk-helper --image=openjdk:11 --restart=Never -- sleep 3600
    kubectl cp ca.pem jdk-helper:/tmp/ca.pem
    kubectl exec jdk-helper -- keytool -import -alias os-ca -file /tmp/ca.pem -keystore /tmp/truststore.jks -storepass changeit -noprompt
    kubectl cp jdk-helper:/tmp/truststore.jks ./truststore.jks
    kubectl create secret generic jaeger-truststore --from-file=truststore.jks=./truststore.jks
    ```

2.  **Использование в подах:**
    Монтируйте секрет и передавайте переменные: `JAVA_OPTS="-Djavax.net.ssl.trustStore=/etc/trust/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"`.

---

## Дополнительная информация

**Смежные темы:**

* Варианты развертывания и масштабирования: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Архитектура и компоненты v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Работа с SDK и сигналами: **[OpenTelemetry Overview](../OpenTelemetry/opentelemetry_overview.md)**
* Наблюдаемость в Service Mesh: **[Istio Observability](../Service_Mesh/istio_observability_and_tools.md)**

### См. также
* [OpenTelemetry Operator Documentation](https://github.com/open-telemetry/opentelemetry-operator)
* [Jaeger Kubernetes Helm Charts](https://github.com/jaegertracing/helm-charts)
