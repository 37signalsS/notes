# eBPF и автоматическая инструментация Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**eBPF и автоматическая инструментация Jaeger** — это методы внедрения телеметрии (трассировки) в приложения без изменения исходного кода или перекомпиляции. В 2026 году стандартом де-факто является **OpenTelemetry eBPF Agent** (наследник проектов Odigos и Pixie), работающий на уровне ядра Linux и автоматически генерирующий спаны для сетевых вызовов. Это особенно ценно для legacy-приложений, third-party сервисов и языков, где OTel SDK еще нестабилен.

Общий обзор инструментации: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Интеграция с Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **eBPF (extended Berkeley Packet Filter)** | Технология выполнения виртуальной машины в пространстве ядра Linux для перехвата системных вызовов и сетевых событий |
| **Auto-instrumentation** | Внедрение телеметрии без изменения исходного кода приложения |
| **OTel eBPF Agent** | OpenTelemetry-агент на базе eBPF, автоматически генерирующий спаны для HTTP/gRPC/DB вызовов |
| **Pixie** | open-source observability платформа, использующая eBPF для автоматической инструментации без агентов |
| **Odigos** | Платформа для автоматической инструментации приложений через eBPF с экспортом в OpenTelemetry |
| **KProbes** | Механизм ядра Linux для перехвата функций в runtime (ядре или модулях) |
| **USDT (User-level Statically Defined Tracing)** | Статические маркеры в коде приложения, видимые eBPF без перекомпиляции |
| **Sidecar-less** | Архитектура без sidecar-контейнера: eBPF-агент работает как DaemonSet на уровне узла |

---

## Базовые концепции

### Архитектура eBPF-инструментации

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Pod A     │     │   Pod B     │     │   Pod C     │
│  (Java App) │     │ (Go App)    │     │(Python App) │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │  eBPF Programs    │  eBPF Programs    │  eBPF Programs
       │  (kprobes/uprobes)│  (kprobes/uprobes)│  (kprobes/uprobes)
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────┐
│              eBPF Agent (DaemonSet)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   eBPF      │  │   eBPF      │  │   eBPF      │  │
│  │   Programs  │  │   Programs  │  │   Programs  │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
│         │                │                │         │
│  ┌──────▼────────────────▼────────────────▼──────┐  │
│  │           OTLP Exporter                        │  │
│  └──────────────────────┬────────────────────────┘  │
│                         │ OTLP                      │
│                         ▼                           │
│              ┌─────────────────────┐                 │
│              │   Jaeger Collector  │                 │
│              └─────────────────────┘                 │
└─────────────────────────────────────────────────────┘
```

### Сравнение методов инструментации

| Метод | Изменение кода | Языки | Производительность | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **Manual OTel SDK** | Да | Go, Java, Python, JS, C++ | Минимальная overhead | Новые проекты, полный контроль |
| **Auto-instrumentation (Javaagent)** | Нет | Java, Node.js | Низкая overhead | Legacy Java, быстрый старт |
| **eBPF Agent** | Нет | Любой (Linux) | Средняя overhead (ядро) | Legacy, third-party, языки без SDK |
| **Service Mesh (Envoy)** | Нет | Любой | Низкая overhead | Только L7 HTTP/gRPC через sidecar |

### Ограничения eBPF

| Ограничение | Описание |
| :--- | :--- |
| **Linux only** | eBPF работает только на ядре Linux 4.14+ (рекомендуется 5.x+) |
| **Версия ядра** | Некоторые пробы требуют 5.8+ (для CO-RE: Compile Once — Run Everywhere) |
| **Языки** | Не все языки имеют USDT-маркеры. Compiled языки (C++, Rust) — проще, чем interpreted (Python) |
| **Контекст приложения** | eBPF видит системные вызовы, но не бизнес-контекст (user_id, feature_flag) без дополнительного обогащения |
| **Совместимость с seccomp** | Настройки безопасности Pod'а могут блокировать eBPF-агент |

---

## Практические сценарии

### Сценарий 1: Развертывание OpenTelemetry eBPF Agent в Kubernetes

**Ситуация:** Нужно автоматически инструментировать все приложения в namespace `production` без изменения их конфигурации.

```yaml
# otel-ebpf-agent.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: otel-ebpf-agent
  namespace: observability
spec:
  selector:
    matchLabels:
      app: otel-ebpf-agent
  template:
    metadata:
      labels:
        app: otel-ebpf-agent
    spec:
      hostPID: true
      hostNetwork: true
      containers:
        - name: otel-ebpf-agent
          image: ghcr.io/open-telemetry/opentelemetry-ebpf-controller:latest
          securityContext:
            privileged: true
            capabilities:
              add:
                - SYS_ADMIN
                - SYS_RESOURCE
                - NET_ADMIN
          env:
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://jaeger-collector.observability.svc:4317"
            - name: OTEL_SERVICE_NAME
              value: "ebpf-agent"
            - name: OTEL_RESOURCE_ATTRIBUTES
              value: "service.namespace=production"
          volumeMounts:
            - name: sys
              mountPath: /sys
              readOnly: true
            - name: proc
              mountPath: /proc
              readOnly: true
            - name: debug
              mountPath: /sys/kernel/debug
              readOnly: true
            - name: bpf
              mountPath: /sys/fs/bpf
              readOnly: false
      volumes:
        - name: sys
          hostPath:
            path: /sys
        - name: proc
          hostPath:
            path: /proc
        - name: debug
          hostPath:
            path: /sys/kernel/debug
        - name: bpf
          hostPath:
            path: /sys/fs/bpf
```

**Валидация:**

1. Применить DaemonSet: `kubectl apply -f otel-ebpf-agent.yaml`.
2. Проверить, что поды запущены на всех узлах: `kubectl get pods -n observability -l app=otel-ebpf-agent -o wide`.
3. Отправить HTTP-запрос в приложение: `curl -X GET http://my-app.production.svc:8080/api`.
4. Проверить метрики: `curl http://jaeger-collector.observability.svc:8888/metrics | grep otelcol_receiver_accepted_spans`.
5. В Jaeger UI найти трейс с автоматически сгенерированным спаном.

### Сценарий 2: Автоматическая инструментация через OpenTelemetry Operator (Java)

**Ситуация:** Нужно автоматически внедрить OTel SDK в Java-приложение через Javaagent.

```yaml
# instrumentation-java.yaml
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

**Активация через аннотацию:**

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: my-app
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-java: "true"
    spec:
      containers:
        - name: my-app
          image: my-app:1.0.0
```

**Валидация:**

1. Применить Instrumentation: `kubectl apply -f instrumentation-java.yaml`.
2. Добавить аннотацию в Deployment.
3. Перезапустить под: `kubectl rollout restart deployment/my-app -n my-app`.
4. Проверить наличие init-контейнера: `kubectl describe pod -n my-app -l app=my-app`.
5. Отправить запрос: `curl http://my-app.my-app.svc:8080/api`.
6. Проверить метрики Collector.

### Сценарий 3: Использование Pixie для трассировки без агентов

**Ситуация:** Нужно получить трейсы для приложения, которое нельзя изменить (third-party binary).

```bash
# 1. Установка Pixie
curl -s https://withpixie.ai/install.sh | sh

# 2. Включение Pixie в namespace
pxctl deployment set-deploy-key my-app --namespace=production

# 3. Просмотр трасс в Pixie UI
px ui
```

**Валидация:**

1. Отправить запрос в приложение.
2. В Pixie UI открыть таблицу `pixie.requests` и найти трассы.
3. Экспортировать трейсы в Jaeger через OTLP.

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **eBPF-агент не запускается** | HostPID не включен или ядро не поддерживает eBPF | Проверить `uname -r`, включить `hostPID: true` |
| **Нет спанов от eBPF** | Приложение использует нестандартные порты или протоколы | Добавить кастомные kprobes для нужных функций |
| **Высокий overhead** | Слишком много проб или неоптимальные фильтры | Ограничить `ebpf.probes` только критичными функциями |
| **Секьюрити контекст блокирует eBPF** | Seccomp или AppArmor запрещают `bpf` системные вызовы | Добавить `SYS_ADMIN`, `SYS_RESOURCE` в `securityContext.capabilities` |
| **Дублирование с sidecar** | eBPF и Istio sidecar создают спаны для одного вызова | Отключить один из источников инструментации |

---

## Лучшие практики

1.  **eBPF для legacy:** Используйте eBPF для приложений, которые нельзя изменить, но предпочитайте OTel SDK для новых проектов.
2.  **DaemonSet с privileged:** eBPF-агент требует `hostPID: true` и `privileged: true` или соответствующие capabilities.
3.  **Версия ядра:** Используйте Linux 5.8+ для поддержки CO-RE (Compile Once — Run Everywhere).
4.  **Обогащение атрибутами:** eBPF видит только системные вызовы. Обогатите спаны атрибутами приложения через `attributes` processor в Collector.
5.  **Не дублируйте инструментацию:** Если используется eBPF, отключите sidecar-инъекцию или Javaagent для данного приложения.

---

## Очистка окружения

```bash
# Удаление DaemonSet eBPF-агента
kubectl delete daemonset otel-ebpf-agent -n observability

# Удаление Instrumentation CR
kubectl delete instrumentations -n my-app --all

# Очистка секретов
kubectl delete secret jaeger-certs -n observability
```

---

## Дополнительная информация

**Смежные темы:**

* Автоматическая инструментация: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* OpenTelemetry SDK: **[OpenTelemetry: Инструментация и SDK](../OpenTelemetry/instrumentation_sdk.md)**
* Service Mesh tracing: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* Контекстная пропагация: **[Обзор Jaeger](./jaeger_overview.md)**

### См. также

* [OpenTelemetry eBPF Agent](https://github.com/open-telemetry/opentelemetry-ebpf-controller)
* [Pixie Documentation](https://docs.pixielabs.ai/)
* [Odigos Documentation](https://docs.odigos.io/)
