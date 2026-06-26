# Паттерны Sidecar в Kubernetes

## Определения

**Sidecar Pattern** — архитектурный паттерн многоконтейнерного Pod, при котором вспомогательный container запускается рядом с основным приложением для расширения его функциональности (логирование, мониторинг, безопасность), не изменяя код самого приложения.

**Adapter Pattern** — специализированный вид sidecar, который приводит вывод основного приложения (например, метрики или логи) к единому формату, понятному внешним системам мониторинга.

**Ambassador Pattern** — вид sidecar, который выступает в роли прокси-сервера для управления внешними сетевыми соединениями основного приложения (например, для реализации логики ретраев, балансировки или защиты соединений).

**Native Sidecar** — механизм Kubernetes версии 1.29+ (стабилен в 1.33+), позволяющий определять вспомогательные container как Init-container с политикой перезапуска `Always`. Это гарантирует их запуск до основного приложения и работу на протяжении всего жизненного цикла Pod. Подробности описаны в KEP-3839.

---

## Базовые концепции

### Виды паттернов и их применение

| Паттерн | Назначение | Пример реализации |
| :--- | :--- | :--- |
| **Sidecar** | Дополняет и расширяет возможности приложения | Fluentd для сбора логов, Istio для управления трафиком |
| **Adapter** | Унифицирует интерфейс взаимодействия с внешним миром | Конвертер кастомных метрик в формат Prometheus |
| **Ambassador** | Упрощает сетевое взаимодействие для приложения | Проксирование запросов к DB или внешним API |

**Типовые задачи sidecar-container:**

* **Наблюдаемость:** сбор и отправка логов (Fluentbit, Filebeat) и экспорт метрик (metrics exporter) без внедрения агентов в код приложения.
* **Сетевое взаимодействие:** реализация Service Mesh, mTLS и управления трафиком (Envoy в Istio, Linkerd proxy).
* **Конфигурация:** динамическая подгрузка настроек и ротация секретов из внешних источников (Vault Agent Injector — запись в shared Volume).
* **Безопасность:** автоматическое управление TLS сертификатами и аутентификацией.

### Native Sidecar (Kubernetes 1.29+)

До появления нативных sidecar порядок запуска и завершения container в Pod не был гарантирован: обычный sidecar мог завершиться раньше основного приложения, нарушив работу (например, Envoy умирает до того, как приложение закончило отправку запросов). Новый механизм решает эту проблему, позволяя использовать `Init-container` для долгоживущих процессов.

**Ключевые особенности:**

* **Гарантированный порядок:** нативные sidecar запускаются первыми. Основные container не стартуют, пока sidecar не перейдет в состояние `Ready` (после успешного прохождения `startupProbe`).
* **Жизненный цикл:** в отличие от обычных Init-container, нативные sidecar не завершаются перед стартом приложения, а продолжают работать параллельно.
* **Завершение Pod:** основные container завершаются первыми, после чего останавливаются sidecar (последними). Это гарантирует, что вспомогательный сервис (прокси, логирование) жив, пока приложение завершает работу.

---

## Практические сценарии

### Сценарий 1: Sidecar для сбора логов

Классический пример использования Fluentd для чтения логов из общего Volume и их отправки в хранилище:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-logging
spec:
  volumes:
  - name: log-storage
    emptyDir: {}
  containers:
  - name: main-app
    image: my-app:1.2.0
    volumeMounts:
    - name: log-storage
      mountPath: /var/log/app
  - name: log-shipper
    image: fluent/fluentd:v1.16
    volumeMounts:
    - name: log-storage
      mountPath: /var/log/app
      readOnly: true
```

### Сценарий 2: Native Sidecar с гарантированной готовностью

Использование прокси-сервера Envoy, который должен быть полностью готов до того, как приложение начнет отправлять запросы:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-envoy
spec:
  initContainers:
  - name: envoy-proxy
    image: envoyproxy/envoy:v1.28
    restartPolicy: Always  # Делает контейнер нативным сайдкаром
    startupProbe:
      httpGet:
        path: /ready
        port: 9901
      initialDelaySeconds: 5
      periodSeconds: 2
      failureThreshold: 10
  containers:
  - name: app
    image: my-app:1.2.0
```

### Сценарий 3: Ambassador для legacy-приложений

Проксирование трафика для приложения, которое умеет работать только с `localhost`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: legacy-app-proxy
spec:
  containers:
  - name: legacy-app
    image: old-service:1.0 # Слушает только 127.0.0.1:8080
  - name: ambassador-proxy
    image: nginx:alpine
    volumeMounts:
    - name: config
      mountPath: /etc/nginx/conf.d
  volumes:
  - name: config
    configMap:
      name: proxy-config
```

---

## Дополнительная информация

### Особенности эксплуатации

* **Ресурсы:** ресурсы (CPU, RAM), потребляемые sidecar, суммируются с ресурсами основного приложения при расчете общего лимита Pod. Всегда устанавливайте `requests` и `limits` для sidecar-container.
* **Обновление:** изменение образа нативного sidecar в спецификации требует пересоздания Pod.
* **Общие ресурсы:** container в одном Pod разделяют сетевой Namespace (могут слушать на localhost) и Volume (через volumeMounts). **PID-namespace** объединяется опционально через `shareProcessNamespace: true` (требуется для отправки сигналов между container). Подробнее в разделе [Общие ресурсы container в Pod](./pod_overview.md#obshchie-resursy-container-v-pod).

**Связанные темы:**

* [Init-container в Kubernetes](./pod_init_containers.md)
* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md)
* [Обзор Service в Kubernetes](../../Networking/Service/service_overview.md)
* [Прокси Sidecar: реализации и сценарии](../../Service_Mesh/proxy_sidecar.md)
