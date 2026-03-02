# Интеграция Jaeger с Kubernetes

> **Важно:** Документация описывает **Jaeger v2**. Jaeger v1 достиг EOL 31 декабря 2025 года.

Развертывание Jaeger в Kubernetes упрощается с помощью **Jaeger Operator**, который автоматизирует установку, управление и конфигурацию компонентов Jaeger через Custom Resources (CRD). В v2 Operator использует OpenTelemetry Operator под капотом.

---

## Определения

* **Jaeger Operator:** Контроллер Kubernetes, который отслеживает ресурсы `Jaeger` (CRD) и управляет соответствующими объектами (Deployments, Services, DaemonSets и т.д.).
* **Custom Resource (CR):** Объект `kind: Jaeger`, который описывает желаемое состояние инсталляции Jaeger (например, стратегия `allInOne` или `production`).

---

## Основные концепции

### Паттерны развертывания Collector

В Jaeger v2 компонент Agent объединен с Collector в единый **OpenTelemetry Collector**. Существует два основных подхода к развертыванию:

1. **Sidecar:** OTel Collector развертывается как дополнительный контейнер в каждом поде приложения.
    * **Плюсы:** Простота конфигурации для приложения (отправка на `localhost`). Изоляция ресурсов.
    * **Минусы:** Более высокое потребление ресурсов (память, CPU) в масштабе кластера.
    * **Реализация:** Автоматически управляется Jaeger Operator через аннотацию.

2. **DaemonSet:** Один экземпляр Collector развертывается на каждом узле кластера.
    * **Плюсы:** 
        * **Эффективное использование ресурсов** (один Collector на узел).
        * **Упрощение сетевого пути:** Позволяет приложению отправлять данные напрямую на IP-адрес хоста.
    * **Минусы:** 
        * Приложению необходимо знать IP-адрес хоста (`hostIP`) для отправки спанов.
        * Требует использования `hostPort` и `hostNetwork: true`.
    * **Реализация:** Задается в CR `Jaeger` в секции `spec.collector`. Для корректной работы DNS-резолвинга внутри кластера для такого пода требуется `dnsPolicy: ClusterFirstWithHostNet`.

### Подключение приложений

Приложение должно быть сконфигурировано для отправки трассировок в OTel Collector.

*   **При использовании Sidecar:** SDK настраивается на отправку данных на `localhost:4317` (gRPC) или `localhost:4318` (HTTP).

*   **При использовании DaemonSet:** SDK должен использовать `hostIP` пода в качестве адреса. Этого можно достичь, передав `hostIP` в приложение как переменную окружения через **Downward API**.

    ```yaml
    # В манифесте Deployment приложения
    spec:
      template:
        spec:
          containers:
          - name: my-app
            env:
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              valueFrom:
                fieldRef:
                  fieldPath: status.hostIP
              value: ":4317"
    ```

*   **Напрямую в Collector Service:** Приложения могут отправлять данные напрямую в Collector через соответствующий Kubernetes Service (например, `jaeger-collector.observability.svc.cluster.local:4317`).

---

## Практические сценарии

### Сценарий 1: Развертывание через Jaeger Operator

#### 1. Установка Operator

Jaeger Operator можно установить с помощью Helm или из OperatorHub.

#### 2. Создание Jaeger Instance

Создайте YAML-файл, описывающий нужную конфигурацию.

**Для разработки (all-in-one):**

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-dev
spec:
  strategy: allInOne # Все компоненты в одном поде
  storage:
    type: memory
  ingress:
    enabled: true # Автоматически создать Ingress для доступа к UI
```

**Для production:**

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-prod
spec:
  strategy: production # Раздельные, масштабируемые компоненты
  collector:
    replicas: 3
    options:
      otlp:
        enabled: true # Включить прием OTLP данных
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch-client:9200
```

#### 3. Автоматическое внедрение Collector (Sidecar Injection)

Чтобы Operator автоматически добавил sidecar-контейнер с OTel Collector в под вашего приложения, добавьте аннотацию в `metadata` вашего Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        "sidecar.jaegertracing.io/inject": "true"
    spec:
      containers:
      - name: my-app
        image: my-app-image:1.0
        env:
        # SDK будет отправлять спаны на localhost, где их перехватит sidecar-collector
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://localhost:4317"
```

### Сценарий 2: Интеграция с Ingress-NGINX для сквозной трассировки

NGINX Ingress Controller может автоматически создавать корневой спан для каждого входящего запроса, что позволяет получить полную трассировку от точки входа в кластер.

#### Конфигурация

Трассировка включается через параметры конфигурации контроллера (в `ConfigMap` или `values.yaml` для Helm-чарта):

- **`enable-opentracing: "true"`**: Глобально включает модуль трассировки.
- **`jaeger-collector-host`**: Адрес OTel Collector. В v2 используется формат `opentelemetry-collector.<namespace>.svc.cluster.local`.
- **`jaeger-propagation-format: "w3c"`**: Устанавливает формат заголовков для передачи контекста трассировки. `w3c` является современным стандартом и использует заголовок `traceparent`.

Также трассировку можно включить для конкретного Ingress-ресурса с помощью аннотации:
```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/enable-opentracing: "true"
```

> **Важно:** Модуль трассировки в NGINX Ingress Controller чувствителен к доступности агента. Если `jaeger-collector-host` указан, но агент недоступен, **контроллер может перестать работать или не сможет обновить конфигурацию**. Для production-сред рекомендуется использовать отдельный Ingress-контроллер для трассируемых приложений, чтобы изолировать возможные сбои.

### Сценарий 3: Конфигурация Java TrustStore для подключения к OpenSearch

Если ваш OpenSearch использует TLS с сертификатами, подписанными собственным CA, Java-приложениям (таким как `jaeger-spark-dependencies`) для подключения потребуется `TrustStore`.

Процесс создания и использования TrustStore в Kubernetes:

1.  **Получить CA сертификат OpenSearch.**
2.  **Создать TrustStore:** Используется утилита `keytool` из JDK. Это можно сделать внутри временного контейнера.
    ```bash
    # Запускаем контейнер с JDK, пробрасывая в него CA сертификат
    kubectl run -it --rm jdk-helper --image=openjdk:11 -- /bin/bash

    # Внутри контейнера:
    keytool -import -alias opensearch-ca -file /path/to/ca.pem -keystore truststore.jks -storepass password -noprompt
    ```
3.  **Сохранить TrustStore в `ConfigMap`:**
    Так как `TrustStore` является бинарным файлом, его необходимо закодировать в Base64.
    ```bash
    # Копируем TrustStore из контейнера
    kubectl cp jdk-helper:truststore.jks ./truststore.jks

    # Кодируем и создаем ConfigMap
    kubectl create configmap jaeger-truststore --from-file=truststore.jks.b64=$(base64 -w 0 truststore.jks)
    ```
4.  **Смонтировать `ConfigMap` в под:**
    Далее этот `ConfigMap` монтируется в под с приложением (например, `CronJob` для `jaeger-spark-dependencies`), где init-контейнер декодирует его из Base64 обратно в бинарный файл.

### Сценарий 4: Интеграция с OpenTelemetry Collector

Вместо Jaeger Agent можно использовать OpenTelemetry Collector. Приложение отправляет данные в OTel Collector, который, в свою очередь, экспортирует их в Jaeger Collector.

**Конфигурация приложения:**

```yaml
env:
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector-service:4318" # Адрес сервиса OTel Collector
- name: OTEL_TRACES_EXPORTER
  value: "otlp"
```

Это позволяет использовать единый коллектор для всех сигналов телеметрии (трассировок, метрик, логов).

---

## Дополнительная информация

* **Сравнение моделей развертывания:** Подробнее см. в [**Вариантах развертывания Jaeger**](./jaeger_deployment_options.md).
* **Архитектура:** Обзор компонентов Jaeger доступен в [**Архитектуре Jaeger**](./jaeger_architecture.md).
