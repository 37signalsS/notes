# Observability in Containers

## Определения

**Observability в контейнерах** — практика обеспечения наблюдаемости для контейнеризированных приложений и оркестраторов (Docker, Kubernetes), учитывающая их специфические характеристики: изоляцию, динамичность жизненного цикла и распределённую природу.

**Ключевая особенность:** В отличие от традиционных систем, контейнеры требуют автоматизированного сбора телеметрии через специализированные механизмы оркестратора и sidecar-паттерны.

## Базовые концепции

### Ключевые вызовы

| Вызов | Описание | Решение |
| :--- | :--- | :--- |
| **«Чёрные ящики»** | Контейнеры изолированы, традиционные методы мониторинга (SSH, агенты на хосте) неприменимы | Сбор телеметрии через оркестратор, sidecar-контейнеры, eBPF |
| **Динамичность** | Контейнеры живут минуты/секунды, часто пересоздаются | Автоматическое обнаружение целей (Service Discovery), привязка меток к Pod/Container ID |
| **Мультитенантность** | На одной ноде работают контейнеры разных команд/сервисов | Изоляция метрик через labels, namespace, tenant ID |
| **Эфемерность логов** | Логи теряются при перезапуске контейнера | Централизованный сбор в реальном времени, stdout/stderr → агрегатор |

### Механизмы обеспечения наблюдаемости

#### 1. Проверки здоровья (Probes)

Kubernetes предоставляет механизм проб для управления жизненным циклом контейнеров:

| Тип пробы | Назначение | Реакция на сбой | SSoT |
| :--- | :--- | :--- | :--- |
| **`livenessProbe`** | Проверка, что приложение работает и не зависло | Перезапуск контейнера | [`Kubernetes/Base/probes.md`](../../../Kubernetes/Base/probes.md) |
| **`readinessProbe`** | Проверка готовности принимать трафик | Исключение из Service (без перезапуска) | [`Kubernetes/Base/probes.md`](../../../Kubernetes/Base/probes.md) |
| **`startupProbe`** | Защита медленно стартующих приложений | Отключение других проб до успеха | [`Kubernetes/Base/probes.md`](../../../Kubernetes/Base/probes.md) |

> **Важно:** Детальная настройка проб (параметры, механизмы `httpGet`/`tcpSocket`/`exec`, лучшие практики) описана в SSoT [`Kubernetes/Base/probes.md`](../../../Kubernetes/Base/probes.md).

#### 2. Sidecar-контейнеры для телеметрии

**Sidecar-паттерн** — запуск вспомогательных контейнеров в том же Pod для сбора логов, метрик и трассировок.

**Преимущества:**
- Общий network namespace — агент видит весь трафик основного приложения
- Общий volume — доступ к лог-файлам без проброса с хоста
- Изоляция ответственности — приложение не содержит кода инструментирования

**Типичные сценарии использования:**

| Агент | Назначение | Пример |
| :--- | :--- | :--- |
| **Fluent Bit / Vector** | Сбор и форвардинг логов | stdout/stderr → Loki/Kafka |
| **OpenTelemetry Collector** | Сбор метрик и трассировок | OTLP → Prometheus/Tempo |
| **Vault Agent** | Инжекция секретов | Vault → volume приложения |
| **Service Mesh Proxy** | Перехват сетевого трафика | Envoy (Istio), linkerd-proxy |

> **Подробно:** Паттерн sidecar описан в [`Kubernetes/Base/Pod/pod_sidecar_pattern.md`](../../../Kubernetes/Base/Pod/pod_sidecar_pattern.md), реализации прокси — в [`Service_Mesh/proxy_sidecar.md`](../../../Service_Mesh/proxy_sidecar.md).

#### 3. Стандартизация сбора данных

**[OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md)** — стандарт инструментирования для сбора метрик, трассировок и логов.

**Преимущества для контейнеров:**
- Единый SDK для всех языков программирования
- Автоматическое инструментирование (auto-instrumentation) для популярных фреймворков
- Контекстная корреляция через `trace_id`, `span_id`
- Экспорт в любые бэкенды (Prometheus, Jaeger, Loki, Grafana)

## Практические сценарии

### Сценарий 1: Настройка алертов для контейнеризированных приложений

Для Kubernetes-приложений рекомендуется настроить алерты на ключевые события:

| Метрика | Выражение (PromQL) | Порог | Описание |
| :--- | :--- | :--- | :--- |
| **Перезапуск контейнера** | `increase(kube_pod_container_status_restarts_total[5m]) > 0` | Любой рестарт | Раннее обнаружение сбоев |
| **OOM Killed** | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1` | Любое событие | Нехватка памяти |
| **Недоступность реплик** | `<90%` реплик доступны | В течение `5m` | Деградация сервиса |
| **Высокое потребление CPU** | `>80%` от limits | В течение `10m` | Риск троттлинга |
| **Высокое потребление памяти** | `>85%` от limits | В течение `10m` | Риск OOM Killed |

> **Примеры алертов:** [`Monitoring Alerting Recommendations`](./monitoring_alerting_recommendations.md#первые-алерты-для-kubernetes-приложений).

### Сценарий 2: Сбор логов через sidecar

**Задача:** организовать сбор логов из Pod с приложением, которое пишет логи в файл.

**Решение:** Использовать sidecar-контейнер с Fluent Bit:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-logging-sidecar
spec:
  volumes:
  - name: app-logs
    emptyDir: {}
  
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: app-logs
      mountPath: /var/log/app
  
  - name: log-collector
    image: fluent/fluent-bit:latest
    volumeMounts:
    - name: app-logs
      mountPath: /var/log/app
    args:
    - -c
    - /fluent-bit/etc/fluent-bit.conf
```

**Принцип работы:**
1. Основное приложение пишет логи в `/var/log/app/app.log`
2. Sidecar монтирует тот же volume и читает логи
3. Fluent Bit парсит, обогащает метаданными Pod и отправляет в централизованное хранилище (Loki, Elasticsearch)

**Альтернатива:** Для сбора логов со всех Pod на ноде использовать DaemonSet с Fluent Bit/Vector — эффективнее по ресурсам.

### Сценарий 3: Корреляция данных при инциденте в Kubernetes

**Ситуация:** Алерт сработал на высокую задержку (p99 > 2с) для сервиса в Kubernetes.

**Порядок расследования:**

| Шаг | Действие | Инструмент |
| :--- | :--- | :--- |
| **1** | Проверка состояния Pod и контейнеров | `kubectl get pods`, `kubectl describe pod` |
| **2** | Анализ метрик CPU/памяти, рестартов | Grafana + Prometheus (kube-state-metrics) |
| **3** | Проверка событий (OOMKilled, Liveness probe failed) | `kubectl get events --sort-by=.lastTimestamp` |
| **4** | Поиск трассировок с высокой задержкой | Tempo/Jaeger (фильтр по `service.name`) |
| **5** | Анализ логов по `trace_id` проблемного запроса | Loki (запрос: `{trace_id="abc123"}`) |
| **6** | Профилирование проблемного сервиса | Pyroscope (выбор сервиса и временного диапазона) |

**Результат:** Комплексный анализ позволяет выявить корневую причину (например, медленный SQL-запрос, отсутствие индекса, троттлинг CPU).

## Дополнительная информация

### Связанные темы

- **[Проектирование высоконагруженного мониторинга в распределённых системах](./designing_high-load_monitoring_in_distributed_systems.md)** — архитектура мониторинга для микросервисов
- **[Четыре столпа Observability](./four_pillars_of_observability.md)** — логи, метрики, трассировки, профилирование
- **[Методологии мониторинга](./monitoring_methodologies.md)** — Golden Signals, RED, USE
- **[Пробы (Probes)](../../../Kubernetes/Base/probes.md)** — детальное описание liveness, readiness, startup probe
- **[Sidecar-паттерн](../../../Kubernetes/Base/Pod/pod_sidecar_pattern.md)** — использование sidecar-контейнеров в Pod
- **[OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md)** — стандарт инструментирования приложений

### Инструменты для контейнеров

| Категория | Инструменты |
| :--- | :--- |
| **Сбор метрик** | Prometheus (cAdvisor, kube-state-metrics), Datadog Agent |
| **Сбор логов** | Fluent Bit, Vector, Loki Promtail |
| **Трассировки** | Jaeger, Tempo, OpenTelemetry Collector |
| **Профилирование** | Pyroscope (eBPF, pprof), Parca |
| **Визуализация** | Grafana (дашборды для Kubernetes) |
