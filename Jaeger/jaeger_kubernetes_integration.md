# Интеграция Jaeger с Kubernetes

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)**.

Развертывание Jaeger v2 в Kubernetes базируется на использовании **OpenTelemetry Operator**. Поскольку вторая версия Jaeger построена на базе OpenTelemetry Collector, она нативно управляется через стандартные ресурсы OpenTelemetry, что обеспечивает глубокую интеграцию с экосистемой облачного мониторинга. Это позволяет автоматизировать не только развертывание самого Jaeger, но и процесс инструментирования приложений.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **OpenTelemetry Operator** | Основной контроллер для управления жизненным циклом Jaeger v2, автоматизирующий установку, настройку и масштабирование |
| **OpenTelemetryCollector (CR)** | Ресурс Kubernetes, описывающий конфигурацию Jaeger v2 (приемники, процессоры, экспортеры) |
| **Sidecar Injection** | Автоматическое внедрение контейнера Collector в под приложения для локального сбора телеметрии |
| **Downward API** | Механизм Kubernetes для передачи метаданных пода (например, IP узла, имя пода) внутрь контейнера через переменные окружения |
| **TrustStore** | Хранилище сертификатов (JKS или PKCS12), используемое Java-приложениями для проверки доверия к SSL-сертификатам бэкендов |

---

## Базовые концепции

### Паттерны развертывания коллектора

В Jaeger v2 устаревший агент заменен на **OpenTelemetry Collector** (или сам бинарный файл Jaeger в роли агента). Выбор паттерна зависит от масштаба кластера и требований к изоляции.

| Паттерн | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Sidecar** | Collector запускается как второй контейнер в каждом поде приложения | Минимальная сетевая задержка. Изоляция трафика. Не требует знания IP узла | Повышенное потребление RAM/CPU (по ~50-100MB на каждый под) |
| **DaemonSet** | Один экземпляр Collector на каждом узле кластера | Эффективное использование ресурсов. Упрощенное агрегирование | Требует настройки `hostPort` и передачи `status.hostIP` через Downward API |
| **Deployment** | Централизованный кластер коллекторов за Service | Удобство масштабирования независимо от количества узлов. Централизованная фильтрация | Дополнительные сетевые переходы (hop). Потенциальное узкое место при пиковых нагрузках |

### Подключение приложений через Downward API

При использовании **DaemonSet** SDK приложения должен знать IP-адрес узла, на котором запущен коллектор.

```yaml
# Пример в манифесте Deployment приложения
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        - name: HOST_IP
          valueFrom:
            fieldRef:
              fieldPath: status.hostIP
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://$(HOST_IP):4317"
```

---

## Практические сценарии

### Сценарий 1: Развертывание Jaeger v2 через OpenTelemetry Operator

В Jaeger v2 рекомендуется использовать `kind: OpenTelemetryCollector` с образом Jaeger.

#### Сравнение Operator и Helm-чартов

*   **Operator:** Рекомендуется для большинства сред. Автоматизирует инъекцию sidecar, управляет сертификатами (через Cert-Manager), обновляет конфигурацию на лету. Позволяет использовать **CRD (Custom Resource Definitions)** для декларативного описания.
*   **Helm-чарты:** Обеспечивают "прозрачное" развертывание без фоновых контроллеров. Полезны в средах с жесткими ограничениями безопасности, где запрещено создание `MutatingWebhookConfiguration` или использование кастомных операторов.

#### Создание экземпляра Jaeger v2 (all-in-one для разработки)

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-v2-dev
spec:
  mode: deployment
  image: jaegertracing/jaeger:2.0.0
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
          http:
    processors:
      batch:
    exporters:
      # В v2 используется специализированный экспортер для памяти (тестирование)
      logging:
        verbosity: detailed
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch]
          exporters: [logging]
```

#### Автоматическое внедрение Sidecar (Sidecar Injection)

Чтобы Operator автоматически добавил sidecar-контейнер в ваши поды, добавьте аннотацию в Deployment приложения:
`sidecar.opentelemetry.io/inject: "true"`

### Сценарий 2: Сквозная трассировка через Ingress-NGINX

NGINX Ingress Controller версии 1.9+ поддерживает нативную интеграцию с OpenTelemetry, заменяя устаревший модуль OpenTracing.

**Настройка в ConfigMap контроллера:**

| Параметр | Значение | Пояснение |
| :--- | :--- | :--- |
| `enable-opentelemetry` | `"true"` | Включает поддержку OpenTelemetry |
| `otlp-collector-host` | `jaeger-collector.monitoring.svc` | Адрес gRPC-сервиса коллектора |
| `otlp-collector-port` | `"4317"` | Порт для приема OTLP данных |
| `otel-propagation-policy` | `"w3c"` | Использование стандарта W3C Trace Context (header `traceparent`) |

**Пример аннотации для ресурса Ingress:**
`nginx.ingress.kubernetes.io/enable-opentelemetry: "true"`

### Сценарий 3: Создание Java TrustStore для безопасного подключения

При использовании OpenSearch с TLS и самоподписанным CA компонентам Jaeger (например, Spark Dependencies) требуется TrustStore.

**Пошаговый технический процесс:**

1.  **Генерация JKS файла:**
    Запустите временный под с JDK, передав в него ваш CA-сертификат:
    ```bash
    # Создаем под и копируем сертификат
    kubectl run jdk-helper --image=openjdk:11 --restart=Never -- sleep 3600
    kubectl cp ca.pem jdk-helper:/tmp/ca.pem

    # Генерируем TrustStore внутри пода
    kubectl exec jdk-helper -- keytool -import -alias os-ca -file /tmp/ca.pem -keystore /tmp/truststore.jks -storepass changeit -noprompt

    # Копируем результат обратно
    kubectl cp jdk-helper:/tmp/truststore.jks ./truststore.jks
    ```

2.  **Создание Secret в Kubernetes:**
    Рекомендуется использовать Secret для хранения бинарных данных:
    ```bash
    kubectl create secret generic jaeger-truststore --from-file=truststore.jks=./truststore.jks
    ```

3.  **Использование в Spark Dependencies (CronJob):**
    Монтируйте Secret как volume и передайте параметры через системные свойства Java:
    ```yaml
    spec:
      containers:
      - name: spark-job
        env:
        - name: JAVA_OPTS
          value: "-Djavax.net.ssl.trustStore=/etc/trust/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"
        volumeMounts:
        - name: truststore-vol
          mountPath: /etc/trust
          readOnly: true
      volumes:
      - name: truststore-vol
        secret:
          secretName: jaeger-truststore
    ```

### Сценарий 4: Миграция с Jaeger Operator (v1) на OTel Operator (v2)

Для корректного перехода на вторую версию необходимо:
1.  **Установить Cert-Manager:** Обязательное условие для работы вебхуков OpenTelemetry Operator.
2.  **Преобразовать ресурсы:** Заменить `kind: Jaeger` на `kind: OpenTelemetryCollector`.
3.  **Обновить конфигурацию:** Перевести флаги командной строки (CLI flags) в формат YAML-пайплайнов OTel.
4.  **Обновить аннотации:** Заменить `sidecar.jaegertracing.io/inject` на `sidecar.opentelemetry.io/inject`.

---

## Дополнительная информация

**Смежные темы:**

* Варианты развертывания и масштабирования: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Архитектура и компоненты v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Работа с SDK и сигналами: **[OpenTelemetry Overview](../OpenTelemetry/opentelemetry_overview.md)**
