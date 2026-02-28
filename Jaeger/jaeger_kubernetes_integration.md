# Интеграция Jaeger с Kubernetes

Развертывание Jaeger в Kubernetes упрощается с помощью **Jaeger Operator**, который автоматизирует установку, управление и конфигурацию компонентов Jaeger через Custom Resources (CRD). Это предпочтительный метод для production-окружений.

---

## Определения

* **Jaeger Operator:** Контроллер Kubernetes, который отслеживает ресурсы `Jaeger` (CRD) и управляет соответствующими объектами (Deployments, Services, DaemonSets и т.д.).
* **Custom Resource (CR):** Объект `kind: Jaeger`, который описывает желаемое состояние инсталляции Jaeger (например, стратегия `allInOne` или `production`).

---

## Основные концепции

### Паттерны развертывания агента

Существует два основных подхода к развертыванию Jaeger Agent для сбора трассировок с приложений:

1. **Sidecar:** Агент развертывается как дополнительный контейнер в каждом поде приложения.
    * **Плюсы:** Простота конфигурации для приложения (всегда отправляет спаны на `localhost`). Изоляция ресурсов.
    * **Минусы:** Более высокое потребление ресурсов (память, CPU) в масштабе кластера.
    * **Реализация:** Автоматически управляется Jaeger Operator через аннотацию.

2. **DaemonSet:** Один экземпляр агента развертывается на каждом узле кластера.
    * **Плюсы:** 
        *   **Эффективное использование ресурсов** (один агент на узел).
        *   **Упрощение сетевого пути:** Позволяет приложению отправлять UDP-пакеты напрямую агенту на IP-адрес хоста, минуя оверхед и сложности сети Kubernetes (Service, NAT).
    * **Минусы:** 
        *   Приложению необходимо знать IP-адрес хоста (`hostIP`) для отправки спанов.
        *   Требует использования `hostPort` и `hostNetwork: true`.
    * **Реализация:** Задается в CR `Jaeger` в секции `spec.agent.strategy` или настраивается вручную в Helm-чарте. Для корректной работы DNS-резолвинга внутри кластера для такого пода требуется `dnsPolicy: ClusterFirstWithHostNet`.

### Подключение приложений

Приложение должно быть сконфигурировано для отправки трассировок агенту или коллектору.

*   **При использовании Sidecar:** SDK настраивается на отправку данных на `localhost:6831`.

*   **При использовании DaemonSet:** SDK должен использовать `hostIP` пода в качестве адреса. Этого можно достичь, передав `hostIP` в приложение как переменную окружения через **Downward API**.

    ```yaml
    # В манифесте Deployment приложения
    spec:
      template:
        spec:
          containers:
          - name: my-app
            env:
            - name: OTEL_EXPORTER_JAEGER_AGENT_HOST
              valueFrom:
                fieldRef:
                  fieldPath: status.hostIP # Инъекция IP адреса хоста
            - name: OTEL_EXPORTER_JAEGER_AGENT_PORT
              value: "6831"
    ```

*   **Напрямую в Collector:** Как альтернатива, приложения могут отправлять данные напрямую в Collector через соответствующий Kubernetes Service (например, `jaeger-collector.observability.svc.cluster.local`).

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
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch-client:9200
  collector:
    replicas: 3
  agent:
    strategy: DaemonSet # Использовать DaemonSet для агентов
```

#### 3. Автоматическое внедрение агента (Sidecar Injection)

Чтобы Operator автоматически добавил sidecar-контейнер с агентом в под вашего приложения, добавьте аннотацию в `metadata` вашего Deployment:

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
        # SDK будет отправлять спаны на localhost, где их перехватит sidecar-агент
        - name: JAEGER_AGENT_HOST
          value: "localhost"
```

### Сценарий 2: Интеграция с Ingress-NGINX для сквозной трассировки

NGINX Ingress Controller может автоматически создавать корневой спан для каждого входящего запроса, что позволяет получить полную трассировку от точки входа в кластер.

#### Конфигурация

Трассировка включается через параметры конфигурации контроллера (в `ConfigMap` или `values.yaml` для Helm-чарта):

- **`enable-opentracing: "true"`**: Глобально включает модуль трассировки.
- **`jaeger-collector-host`: "jaeger-agent.observability.svc.cluster.local"**: Адрес сервиса, указывающего на агенты Jaeger.
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
