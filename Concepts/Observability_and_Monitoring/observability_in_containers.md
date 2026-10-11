# Наблюдаемость в контейнерах

**Актуально для:** Kubernetes 1.29+, cgroups v2, Linux 5.14+

## Определения

**Наблюдаемость в контейнерах (Container Observability)** -- практика обеспечения видимости состояния контейнеризированных приложений и оркестраторов (Docker, Kubernetes), учитывающая их специфические характеристики: изоляцию, динамичность жизненного цикла и распределённую природу. В отличие от традиционных серверов, контейнеры эфемерны, изолированы через namespaces и ограничены через cgroups, что делает классические методы диагностики (SSH, локальные логи) непригодными.

**Нативный сайдкар (Native Sidecar)** -- механизм Kubernetes (1.29+, стабилен с 1.33), позволяющий определять вспомогательные контейнеры (логи, прокси, метрики) внутри блока `initContainers` с параметром `restartPolicy: Always`. Гарантирует запуск агентов *до* основного приложения и их корректное завершение *после* получения `SIGTERM` основными контейнерами. Решает проблему гонки состояний (Race Condition) при старте и корректно завершает Job.

**Эфемерный контейнер (Ephemeral Container)** -- временный контейнер, запускаемый внутри существующего пода для отладки ("живая" диагностика) без перезапуска основного приложения. Позволяет использовать инструменты (tcpdump, gdb, curl) в `distroless` образах, где отсутствует shell и стандартные утилиты.

**Обогащение метаданными (Metadata Enrichment)** -- процесс добавления контекстных меток (Pod Name, Namespace, Node, Container Name, Image) к телеметрии. В Kubernetes автоматизируется через Service Discovery и подстановку переменных окружения (`DOWNWARD_API`). Критично для корректной фильтрации и агрегации метрик.

**Взрыв кардинальности (Cardinality Explosion)** -- неконтролируемый рост количества уникальных временных рядов из-за добавления высококардинальных меток (например, Pod Name, User ID, Request ID). Является основной причиной деградации TSDB и роста стоимости хранения. Решается через агрегацию на уровне агентов и carefully label design.

**Ротация логов (Log Rotation)** -- механизм предотвращения переполнения диска за счёт периодической очистки старых логов. В Kubernetes управляется kubelet: `--container-log-max-size` (по умолчанию 10Mi) и `--container-log-max-files` (по умолчанию 5). При превышении лимита контейнер может быть перезапущен.

**Graceful Shutdown** -- корректное завершение процесса с обработкой незавершённых запросов и освобождением ресурсов. В Kubernetes включает: обработку `SIGTERM`, выполнение `preStop` хука, ожидание в течение `terminationGracePeriodSeconds` (по умолчанию 30с). Критичен для StatefulSet и долгоживущих соединений.

**Ключевая особенность:** В отличие от традиционных систем, контейнеры требуют автоматизированного сбора телеметрии через механизмы оркестратора, так как доступ к внутреннему состоянию процесса ограничен границами изоляции (namespaces, cgroups).

---

## Предварительные требования

Эффективная наблюдаемость в контейнерах требует подготовленной среды на уровне кластера и нод:

- **ОС и ядро:** Linux-хост с поддержкой cgroups v2 (Ubuntu 22.04+, RHEL 9+, Debian 12+). Ядро 5.14+ необходимо для работы CPU Burst (`cpu.max.burst`) и расширенной PSI-статистики.
- **Контейнерный рантайм:** Docker 20.10+, containerd 1.6+ или CRI-O, корректно пробрасывающие cgroupfs в контейнеры.
- **Оркестратор:** Kubernetes 1.29+ для поддержки Native Sidecar Containers (GA с 1.33).
- **Сбор метрик:** Prometheus-совместимый экспортер или OTel Collector, настроенный на прием метрик с префиксами `container_*`, `kubelet_*`, `cadvisor_*`.
- **Сбор логов:** Агент на уровне ноды (DaemonSet) или native sidecar, с возможностью централизованной доставки во внешнее хранилище.
- **Хранилище и алертинг:** Prometheus + Alertmanager или VictoriaMetrics/Mimir для временных рядов; Loki или ClickHouse для логов.
- **Доступ:** Права на чтение cgroupfs (`/sys/fs/cgroup/`) и RBAC-разрешения для `kubectl debug`, `kubectl top`, `kubectl get events`.

---

## Базовые концепции

### Ключевые вызовы

| Вызов | Описание | Решение |
| :--- | :--- | :--- |
| **Изоляция ("Чёрные ящики")** | Контейнеры изолированы; традиционные методы (SSH) неудобны или небезопасны. | Сбор телеметрии через stdout/stderr, sidecar-агенты, eBPF-инструментацию. |
| **Динамичность** | Короткий жизненный цикл, частые пересоздания подов. | Автоматический Service Discovery, обогащение метрик метаданными (Pod Name, Namespace). |
| **Эфемерность данных** | Логи и локальные файлы теряются при удалении контейнера. | Централизованный сбор в реальном времени во внешние хранилища (Loki, ClickHouse). |
| **Высокая кардинальность** | Огромное количество эфемерных сущностей порождает взрывной рост временных рядов. | Агрегация на уровне агентов, использование высокопроизводительных TSDB (VictoriaMetrics, Mimir). |
| **Ограничение ресурсов** | Контейнеры ограничены cgroups; приложение может не "видеть" лимиты. | Container awareness рантаймов, мониторинг через cAdvisor/kubelet. |

### Механизмы обеспечения наблюдаемости

#### 1. Проверки состояния (Probes)

В Kubernetes пробы являются механизмом самоисцеления и предоставляют базовый уровень наблюдаемости за "здоровьем" процесса.

| Тип пробы | Назначение | Реакция на сбой | Интервалы по умолчанию |
| :--- | :--- | :--- | :--- |
| **`livenessProbe`** | Проверка, что приложение не "зависло". | Перезапуск контейнера. | `periodSeconds: 10`, `failureThreshold: 3` |
| **`readinessProbe`** | Готовность принимать входящий трафик. | Исключение из Service (Endpoint). | `periodSeconds: 10`, `failureThreshold: 3` |
| **`startupProbe`** | Защита медленно стартующих приложений. | Блокировка остальных проб до первого успеха. | `periodSeconds: 10`, `failureThreshold: 30` |

**Важные нюансы:**
- `livenessProbe` НЕ должен проверять внешние зависимости (БД, Redis) -- это приведёт к массовым перезапускам при сбоях зависимостей.
- `readinessProbe` должен отражать реальную готовность принимать трафик (включая прогрев кэша, подключение к БД).
- `startupProbe` блокирует `liveness` и `readiness` до первого успеха -- критично для JVM-приложений с долгим стартом.

Подробное описание параметров приведено в **[Пробы (Probes)](../../Kubernetes/Base/probes.md)**.

#### 2. Мониторинг ресурсов (Cgroups v2)

В 2026 году мониторинг ресурсов базируется на **Cgroups v2** (единая унифицированная иерархия), что позволяет получать данные о давлении на систему через **[PSI (Pressure Stall Information)](../../Linux/Core/kernel/psi.md)**.

**Ключевые файлы cgroupfs (cgroups v2):**

```bash
# Определение пути cgroup для контейнера
# Docker:
cat /proc/<PID>/cgroup
# → 0::/system.slice/docker-<container-id>.scope

# Kubernetes (containerd):
cat /proc/<PID>/cgroup
# → 0::/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<uid>.slice/containerd-<id>.scope

# Путь к cgroupfs (cgroups v2):
ls /sys/fs/cgroup/system.slice/docker-<id>.scope/
# → cpu.max  memory.max  io.max  pids.current  cpu.stat  memory.stat  io.stat
```

**CPU Throttling:**

CPU Throttling в cgroups v2 управляется через `cpu.max` (квота и период):

```bash
# Просмотр квоты CPU (в контейнере)
cat /sys/fs/cgroup/cpu.max
# → 200000 100000  (200ms CPU за каждый 100ms период = 2 ядра)

# Просмотр статистики троттлинга
cat /sys/fs/cgroup/cpu.stat
# → usage_usec 123456789
# → nr_periods 1000
# → nr_throttled 50
# → throttled_usec 2345678

# Формула интенсивности троттлинга:
# rate(container_cpu_cfs_throttled_seconds_total[5m]) > 0
```

**Memory Saturation:**

```bash
# Просмотр потребления памяти
cat /sys/fs/cgroup/memory.stat
# → anon 12345678      (анонимная память = heap)
# → file 9876543       (page cache)
# → kernel 1234567     (ядерные структуры)
# → shmem 0            (разделяемая память)

# Жёсткий лимит (триггер OOMKill)
cat /sys/fs/cgroup/memory.max
# → 536870912 (512 MiB)

# Мягкий лимит (триггер reclaim, медленный рост задержки)
cat /sys/fs/cgroup/memory.high
# → 482345984 (460 MiB)

# Мониторинг давления памяти (PSI)
cat /sys/fs/cgroup/memory.pressure
# → some avg10=2.46 avg60=1.82 avg300=1.21 total=748381
# → full avg10=0.91 avg60=0.65 avg300=0.45 total=280381
```

**Ключевое различие:** `container_memory_working_set_bytes` = `anon` + `file` (без eternal caches). Именно `working_set` является триггером для OOMKill, а не RSS.

#### 3. Стратегии сбора логов

| Паттерн | Описание | Плюсы | Минусы | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **DaemonSet (Node-level)** | Агент на каждой ноде читает логи из `/var/log/pods`. | Максимальная эффективность, минимальный оверхед. | Требует `hostPath` доступа (риск безопасности). | Кластеры < 500 нод, стандартная конфигурация. |
| **Sidecar (Pod-level)** | Агент внутри пода (рекомендуется **Native Sidecar**). | Изоляция логов, возможность сложной обработки. | Значительное потребление ресурсов при масштабировании. | Многоязычные среды, требования по изоляции. |
| **Direct Shipping** | Приложение само отправляет логи по сети (OTLP). | Не требует агентов в кластере. | РISK потери логов при сбоях сети; нагрузка на основное приложение. | Простые среды, минимальные требования. |

**Рекомендация:** Для production-сред в 2026 году рекомендуется **DaemonSet + OTel Collector** как баланс между эффективностью и гибкостью. Native Sidecar -- для случаев, когда критична изоляция логов (multi-tenant, compliance).

#### 4. Sidecar-паттерн и нативные контейнеры

Sidecar-паттерн предполагает запуск вспомогательного контейнера в том же поде для сбора телеметрии или проксирования.

- **Классический Sidecar:** Запускается параллельно с основным в `containers`. Есть риск, что приложение начнет писать логи до старта агента.
- **Native Sidecar (K8s 1.29+):** Определяется в `initContainers` с `restartPolicy: Always`. Гарантирует, что агент (например, прокси или лог-коллектор) будет готов *до* запуска приложения. Стабилен с Kubernetes 1.33.

**Жизненный цикл Native Sidecar:**
1. Kubelet запускает все init-контейнеры (включая native sidecar).
2. Native sidecar проходит `readinessProbe`.
3. После готовности native sidecar, Kubelet запускает основные контейнеры.
4. При завершении пода: основные контейнеры получают `SIGTERM` первыми.
5. После завершения основных контейнеров, native sidecar получает `SIGTERM`.

Подробнее: **[Sidecar-паттерн](../../Kubernetes/Base/Pod/pod_sidecar_patterns.md)** и **[Прокси-сайдкары в Service Mesh](../../Service_Mesh/proxy_sidecar.md)**.

#### 5. Наблюдаемость через eBPF (Sidecar-less)

**eBPF** позволяет собирать глубокую телеметрию напрямую из ядра Linux, не изменяя код приложения и не добавляя sidecar-контейнеры.

- **Deep Visibility:** Видимость сетевых потоков L3/L4/L7 (HTTP, gRPC) и системных вызовов без внедрения Service Mesh.
- **Нулевой overhead:** eBPF-программы выполняются в ядре с минимальными накладными расходами.
- **Инструменты:**
  - **Hubble/Cilium** -- сетевая наблюдаемость, визуализация потоков, DROP-аналитика.
  - **Falco** -- обнаружение аномалий безопасности в реальном времени.
  - **Parca/Pyroscope** -- непрерывное профилирование без.instrumentation приложения.
  - **Inspektor Gadget** -- универсальная отладка подов через eBPF (trace, snapshot, top).

**Пример: захват сетевого трафика через eBPF (без sidecar):**
```bash
# Hubble: мониторинг DROP-пакетов в реальном времени
hubble observe --type drop --namespace production --follow

# Inspektor Gadget: трассировка системных вызовов пода
kubectl gadget trace tcp -n production -p <pod-name>
```

Подробнее: **[eBPF -- виртуальная машина ядра](../../Linux/Core/kernel/ebpf.md)** и **[Cilium: eBPF CNI](../../Kubernetes/Networking/Network/CNI/cilium.md)**.

#### 6. Стандартизация через OpenTelemetry

**[OpenTelemetry (OTel)](../../OpenTelemetry/opentelemetry_overview.md)** -- современный стандарт сбора всех типов данных (метрики, логи, трассировки). В контейнерных средах OTel Collector выступает центральным звеном, агрегируя данные и отправляя их в Tempo, Loki и Prometheus.

**Преимущества OTel в контейнерах:**
- Единый агент для всех типов телеметрии.
- Автоматическое обогащение метаданными (Pod, Namespace, Node).
- Correlation между метриками, логами и трассировками через `trace_id`.
- Множество экспортёров (Prometheus, Loki, Tempo, OTLP).

---

## Мониторинг ресурсов контейнеров

### Метрики cAdvisor (Container Advisor)

**cAdvisor** -- компонент kubelet, собирающий метрики ресурсов по каждому контейнеру. Доступен по API kubelet (`/metrics/cadvisor`) или через Prometheus service discovery.

**Ключевые метрики:**

| Категория | Метрика | Описание | Порог алерта |
| :--- | :--- | :--- | :--- |
| **CPU** | `container_cpu_usage_seconds_total` | Потребление CPU в секундах. | -- |
| **CPU Throttling** | `container_cpu_cfs_throttled_seconds_total` | Время троттлинга. | `rate() > 0` |
| **Memory** | `container_memory_working_set_bytes` | Активная память (триггер OOM). | `> 85% limits` |
| **Memory RSS** | `container_memory_rss` | Резидентный набор памяти. | -- |
| **Memory Cache** | `container_memory_cache` | Page cache (файловые системы). | -- |
| **Network RX/TX** | `container_network_receive_bytes_total` | Сетевой трафик. | -- |
| **I/O Read** | `container_fs_reads_bytes_total` | Чтение с диска. | -- |
| **I/O Write** | `container_fs_writes_bytes_total` | Запись на диск. | -- |
| **Processes** | `container_processes` | Количество процессов в контейнере. | `> 80% pids.limit` |

### PromQL-запросы для мониторинга

**CPU Throttling:**
```promql
# Детекция троттлинга (любой троттлинг = проблема)
sum by (namespace, pod, container) (
  rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m])
) > 0

# Интенсивность троттлинга (процент времени в троттлинге)
sum by (namespace, pod, container) (
  rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m])
)
/
sum by (namespace, pod, container) (
  rate(container_cpu_usage_seconds_total{container!=""}[5m])
) > 0.25
```

**Memory Pressure:**
```promql
# Приближение к лимиту памяти (> 85%)
container_memory_working_set_bytes{container!=""}
/
container_spec_memory_limit_bytes{container!=""} > 0.85

# Прогноз OOMKill через 1 час
predict_linear(
  container_memory_working_set_bytes{container!=""}[30m], 3600
)
/
container_spec_memory_limit_bytes{container!=""} > 1.0
```

**PSI (Pressure Stall Information):**
```promql
# Давление на память (> 5% = предупреждение)
rate(node_pressure_memory_waiting_seconds_total[5m]) > 0.05

# Давление на I/O (> 10% = критично)
rate(node_pressure_io_waiting_seconds_total[5m]) > 0.1
```

### Диагностика CPU Throttling

```bash
# Шаг 1: Проверка потребления CPU контейнером
docker stats --no-stream <container>
# → %CPU > 100% при limits.cpu: "1" = троттлинг

# Шаг 2: Проверка cgroup CPU статистики (в контейнере)
cat /sys/fs/cgroup/cpu.stat
# → nr_throttled: 42  ← проблема
# → nr_throttled: 0   ← норма

# Шаг 3: Проверка квоты
cat /sys/fs/cgroup/cpu.max
# → 200000 100000  (2 ядра)

# Шаг 4: Анализ через Prometheus
# → rate(container_cpu_cfs_throttled_seconds_total[5m]) > 0
```

**Решение троттлинга:**
1. Увеличить `limits.cpu` (не `requests.cpu` -- это другая метрика).
2. Использовать **CPU Burst** (если поддерживается ядром 5.14+): `cpu.max.burst`.
3. Оптимизировать CPU-intensive код (параллелизация, алгоритмы).
4. Для Go -- проверить `GOMAXPROCS` (автоматическое определение в Go 1.25+).

---

## Сетевая наблюдаемость в контейнерах

### Проблема DNS в контейнерах

DNS -- одна из самых частых причин "скрытых" проблем с сетью в Kubernetes. Контейнеры используют кластерный DNS (`coredns`), и ошибки резолвинга приводят к таймаутам и падениям приложений.

**Диагностика DNS:**
```bash
# Проверка DNS-резолвера внутри пода
kubectl exec -it <pod> -- cat /etc/resolv.conf
# → nameserver 10.96.0.10 (CoreDNS ClusterIP)

# Проверка DNS-резолвинга
kubectl exec -it <pod> -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# Проверка через netshoot (если в образе нет утилит)
kubectl debug -it <pod> --image=nicolaka/netshoot --target=<container> -- dig kubernetes.default
```

**Типичные ошибки DNS:**
- `SERVFAIL` -- Coredns не может резолвить (проблема с upstream DNS).
- `NXDOMAIN` -- имя не существует (опечатка в имени сервиса).
- `connection refused` -- Coredns недоступен (проверить Pod STATUS и NetworkPolicy).

### NetworkPolicy и наблюдаемость

NetworkPolicy ограничивает сетевой трафик между подами. Некорректная политика может блокировать легитимный трафик.

**Диагностика NetworkPolicy:**
```bash
# Проверка применённых политик
kubectl get networkpolicy -n <namespace>

# Проверка DROP-пакетов через Cilium/Hubble
hubble observe --type drop --namespace <namespace> --pod <pod-name>

# Проверка через tcpdump (ephemeral container)
kubectl debug -it <pod> --image=nicolaka/netshoot -- tcpdump -i eth0 -nn

# Проверка доступности сервиса из пода
kubectl exec -it <pod> -- curl -v http://<service-name>:<port>
```

**Промежуточные результаты:**
- `hubble observe --type drop` покажет, какая именно политика блокирует трафик.
- `tcpdump` покажет, доходит ли пакет до интерфейса пода.
- `curl -v` покажет, на каком этапе (DNS, TCP connect, HTTP) происходит сбой.

---

## Graceful Shutdown в Kubernetes

### Механизм завершения

Kubernetes обеспечивает корректное завершение подов через последовательность событий:

1. Pod помечается как `Terminating` (удаляется из Endpoints).
2. Основные контейнеры получают `SIGTERM`.
3. Параллельно выполняется `preStop` хук (если определён).
4. После `terminationGracePeriodSeconds` (по умолчанию 30с) -- `SIGKILL`.

**Важно:** `preStop` хук выполняется ПЕРЕД `SIGTERM`. Это позволяет выполнить подготовительные действия (от.flush буферов, отмена транзакций) до получения сигнала завершения.

### Конфигурация

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: graceful-app
spec:
  terminationGracePeriodSeconds: 60  # Общий таймаут завершения
  containers:
  - name: app
    image: my-app:1.0
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 5 && kill -SIGTERM 1"]
          # Или http-хук:
          # httpGet:
          #   path: /shutdown
          #   port: 8080
    ports:
    - containerPort: 8080
```

**Взаимодействие с Service:**
- При завершении пода, kubelet удаляет его из Endpoints сервиса.
- Однако, существующие соединения (keep-alive) могут всё ещё направлять трафик на завершающийся под.
- **Решение:** Использовать `preStop` хук с `sleep 5-10` для ожидания переключения маршрутизации.

### Диагностика завершения

```bash
# Проверка причин завершения пода
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'
# → Completed  (норма)
# → Error      (приложение упало)
# → OOMKilled  (нехватка памяти)

# Проверка времени завершения
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.finishedAt}'

# Анализ логов завершающегося пода
kubectl logs <pod> --previous
```

---

## Практические сценарии

### Сценарий 1: Расследование инцидента в кластере

Алгоритм действий при получении алерта о деградации сервиса:

1. **Метрики (RED/USE):** Проверка `p99 latency` и `error rate`. Анализ `container_memory_working_set_bytes`.
2. **События (Events):** `kubectl get events -n <namespace> --sort-by='.metadata.creationTimestamp'` -- поиск `OOMKilled` или сбоев проб.
3. **Трассировки (Traces):** Поиск конкретного `trace_id` в Tempo для выявления задержки в цепочке микросервисов.
4. **Логи (Logs):** Поиск детальной ошибки в Loki по `trace_id`.
5. **Профилирование (Profiling):** Если причина в потреблении CPU кодом -- анализ Flame Graphs в Pyroscope.

**Валидация:**
- Убедиться, что `trace_id` присутствует во всех сигналах для корректной корреляции.
- Проверить соответствие меток (labels) между метриками пода и его логами.

### Сценарий 2: Отладка пода через Ephemeral Containers

Используется для диагностики "живых" подов без их перезапуска.

**Команда:**
```bash
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
```
*Внутри контейнера доступны tcpdump, curl, dig, htop для анализа окружения основного процесса.*

**Примеры использования:**
```bash
# Проверка сетевой связности
kubectl exec -it <pod> -- curl -v http://<service>:<port>

# Проверка DNS
kubectl exec -it <pod> -- dig <service>.<namespace>.svc.cluster.local

# Проверка потребления ресурсов
kubectl exec -it <pod> -- top
```

### Сценарий 3: Сбор логов через Native Sidecar

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-native-logging
spec:
  volumes:
  - name: shared-logs
    emptyDir: {}
  initContainers:
  - name: logging-agent
    image: fluent/fluent-bit:3.2.0
    restartPolicy: Always # Делает init-контейнер нативным сайдкаром
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
  containers:
  - name: app
    image: my-app:1.5.0
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
```

### Сценарий 4: Диагностика CPU Throttling

**Симптомы:** Высокий P99 latency при нормальном потреблении CPU.

```bash
# Шаг 1: Проверка троттлинга через Prometheus
sum by (pod, container) (
  rate(container_cpu_cfs_throttled_seconds_total{namespace="production"}[5m])
) > 0
# → pod: api-gateway, container: nginx  (проблемный под)

# Шаг 2: Проверка лимитов
kubectl describe pod <pod> | grep -A 5 "Limits:"
# → Limits:   cpu: 500m  (слишком мало для CPU-intensive приложения)

# Шаг 3: Проверка cgroup статистики
kubectl exec -it <pod> -- cat /sys/fs/cgroup/cpu.stat
# → nr_throttled: 42  (подтверждение)

# Шаг 4: Решение -- увеличить limits.cpu
kubectl patch deployment <deploy> -p '{"spec":{"template":{"spec":{"containers":[{"name":"nginx","resources":{"limits":{"cpu":"1000m"}}}]}}}}'
```

### Сценарий 5: Диагностика OOMKill

**Симптомы:** Контейнер периодически перезапускается с кодом 137.

```bash
# Шаг 1: Проверка причин завершения
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'
# → OOMKilled

# Шаг 2: Проверка потребления памяти
kubectl top pod <pod>
# → MEM USAGE / LIMIT
# → 485MiB / 512MiB  (почти满了)

# Шаг 3: Проверка через Prometheus
container_memory_working_set_bytes{pod="<pod>"} / container_spec_memory_limit_bytes{pod="<pod>"}
# → 0.95  (95% от лимита -- критично)

# Шаг 4: Решение -- увеличить limits.memory ИЛИ исправить утечку памяти
kubectl patch deployment <deploy> -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"limits":{"memory":"768Mi"}}}]}}}}'
```

---

## Диагностика и устранение неполадок

| Проблема | Причина по метрикам | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **Скрытый троттлинг** | Рост `throttled_seconds` при CPU < 100% | `cat /sys/fs/cgroup/cpu.stat`; `rate(container_cpu_cfs_throttled_seconds_total[5m])` | Увеличить CPU Limits, использовать CPU Burst, оптимизировать код. |
| **OOMKilled** | `working_set_bytes` достигает лимита | `kubectl top pod`; `container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.85` | Увеличить лимиты RAM, исправить утечку памяти, настроить `GOMEMLIMIT`/`MaxRAMPercentage`. |
| **Пропуски в логах** | Переполнение буфера `stdout` | `kubectl logs --previous`; проверка `container-log-max-size` в kubelet config | Увеличить ресурсы агента сбора, использовать дисковую буферизацию. |
| **Высокая латентность сети** | Высокий `drop` пакетов в метриках CNI | `hubble observe --type drop`; `tcpdump` через ephemeral container | Проверить NetworkPolicy, использовать eBPF (Cilium/Hubble) для визуализации. |
| **DNS Resolution Failure** | `SERVFAIL` или `NXDOMAIN` в логах | `kubectl exec -- dig <service>`; `kubectl get pods -n kube-system -l k8s-app=coredns` | Проверить CoreDNS, NetworkPolicy (порты 53/UDP/TCP), upstream DNS. |
| **CrashLoopBackOff** | Повторяющиеся падения контейнера | `kubectl logs --previous`; `kubectl describe pod <pod>` | Анализ логов, проверка зависимостей, корректность образа. |
| **Под не проходит readinessProbe** | Приложение не готово принимать трафик | `kubectl describe pod <pod>` (Events); проверка логов приложения | Увеличить `initialDelaySeconds`, оптимизировать старт приложения. |
| **Зависание при завершении** | Приложение не обрабатывает `SIGTERM` | `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'` | Добавить обработку `SIGTERM`, настроить `preStop` хук, уменьшить `terminationGracePeriodSeconds`. |

---

## Рекомендации

### Архитектура сбора

- **DaemonSet + OTel Collector:** Для production-сред в 2026 году рекомендуется DaemonSet на каждой ноде с OTel Collector как баланс между эффективностью и гибкостью. Native Sidecar -- для случаев, когда критична изоляция логов (multi-tenant, compliance).
- **Единый агент:** Используйте OTel Collector для всех типов телеметрии (метрики, логи, трассировки) с автоматическим обогащением метаданными (Pod, Namespace, Node) через `DOWNWARD_API`.
- **Correlation:** Включайте `trace_id` в логи и метрики для корреляции сигналов. Exemplars в OTel SDK сокращают время диагностики с часов до минут.

### Мониторинг ресурсов

- **PSI в приоритете:** Добавляйте `container_memory_pressure` и `container_cpu_pressure` в дашборды. PSI выявляет проблемы proactively, до возникновения OOM Kill или throttling.
- **CPU Burst:** Для ядер 5.14+ используйте `cpu.max.burst` для временного превышения квоты CPU при кратковсплесковых нагрузках. Троттлинг при этом не наступает, но общий бюджет периода сохраняется.
- **Container awareness:** Убедитесь, что рантаймы приложений корректно читают лимиты cgroups (`memory.max`, `cpu.max`). Без container awareness приложение может игнорировать лимиты и вызывать OOM Kill хоста.

### Сетевая наблюдаемость

- **eBPF по умолчанию:** Для глубокой сетевой наблюдаемости без sidecar используйте Cilium/Hubble. Это даёт видимость L3/L4/L7 без внедрения Service Mesh.
- **DNS-мониторинг:** Добавьте в дашборды метрики CoreDNS (`coredns_dns_request_duration_seconds`, `coredns_dns_responses_total`) для раннего обнаружения `SERVFAIL`/`NXDOMAIN`.
- **NetworkPolicy:** Тестируйте политики через `kubectl exec` + `curl` из пода-жертвы, а не только через `hubble observe` после факта блокировки.

### Жизненный цикл

- **Graceful Shutdown:** Настраивайте `terminationGracePeriodSeconds` (минимум 30с) и `preStop` хук для StatefulSet и приложений с долгими соединениями. `preStop` выполняется ПЕРЕД `SIGTERM` -- используйте это для ожидания переключения маршрутизации.
- **Native Sidecar:** Для новых развёртываний используйте Native Sidecar (K8s 1.29+, GA 1.33) вместо классического sidecar. Это устраняет race condition при старте и корректно завершает Job.

---

## Особенности и ограничения

### Границы применимости

- **WSL2:** cgroups v2 в WSL2 работает в режиме эмуляции, что приводит к неточным лимитам памяти и CPU. Тестируйте container awareness параметры отдельно в WSL2.
- **Вложенные контейнеры:** cgroups не наследуются автоматически. При запуске контейнера внутри контейнера (DinD) необходимо явно пробросить cgroupfs и настроить `--privileged` или соответствующие capabilities.
- **OOM Kill vs throttling:** OOM Kill происходит при превышении `memory.max` (жёсткий лимит), throttling -- при превышении `cpu.max` (процент времени выполнения). Метрики рантайма не отличают эти два состояния; для детерминированной диагностики используйте `memory.events` и `cpu.stat` из cgroupfs.
- **Длинноrunning-сервисы:** JVM-приложения со временем страдают от фрагментации Metaspace и Direct Buffer. Мониторьте `jvm_native_memory_total_bytes` независимо от Heap.
- **Общая память (IPC):** POSIX и System V shared memory не учитывается в стандартных метриках heap/alloc, но влияет на RSS и может вызвать OOM Kill. Учитывайте её при расчете лимитов контейнера.

### Нестандартные сценарии

- **Динамическое изменение лимитов (In-Place Pod Resize):** При изменении `limits.memory` без перезапуска пода Kubernetes 1.31+ (Beta) / 1.35+ (GA) некоторые рантаймы (особенно Go <1.25 и Python <3.14) не перечитывают новые значения. Требуется ручная перезагрузка или использование внешних переменных окружения (`DOTNET_GCHeapHardLimit`).
- **Mixed GOMAXPROCS:** В оркестраторах с динамическим изменением CPU limit (Kubernetes VPA) Go 1.25+ автоматически перечитывает лимиты, но ручные override `GOMAXPROCS` блокируют это поведение.
- **No-GIL Python (3.13+):** В режиме Free-threaded метрики GIL contention теряют смысл. Переключайте алерты на `python_thread_contention_seconds` и обновите дашборды.
- **Ephemeral Container без shell:** В `distroless` образах `kubectl exec` возвращает ошибку. Используйте `kubectl debug --image=nicolaka/netshoot` для инжекции утилит.

---

## Дополнительная информация

### Связанные темы

- **[Четыре столпа Observability](./four_pillars_of_observability.md)** -- база телеметрии.
- **[Архитектура мониторинга в Kubernetes](../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** -- уровни сбора.
- **[Методологии мониторинга](./monitoring_methodologies.md)** -- RED, USE, Golden Signals.

### Инструменты

- **Метрики:** Prometheus, VictoriaMetrics, cAdvisor.
- **Логи:** Fluent Bit, Vector, Loki.
- **Трассировки:** Tempo, Jaeger, OpenTelemetry Collector.
- **Профилирование:** Pyroscope, Parca.
- **Сетевая наблюдаемость:** Cilium/Hubble, Inspektor Gadget.
- **Отладка:** netshoot, kubectl debug, strace.

### См. также

- **[Наблюдаемость (Observability)](./observability_definitions.md)** — фундамент наблюдаемости.
- **[Четыре столпа Observability](./four_pillars_of_observability.md)** — место контейнерной наблюдаемости.
- **[Управление инцидентами](./incident_management.md)** — реагирование на инциденты в контейнерных средах.
- **[Детекция аномалий](./anomaly_detection.md)** — обнаружение аномалий в контейнерных метриках.
- **[Зрелость сервиса и готовность к production](./service_maturity_production_readiness.md)** — production readiness для контейнерных сервисов.
- **[Наблюдаемость баз данных](./database_observability.md)** — наблюдаемость БД в Kubernetes.
