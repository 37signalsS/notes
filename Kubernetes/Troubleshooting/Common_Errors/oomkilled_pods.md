# Поды, завершенные из-за нехватки памяти (OOMKilled)

## Определения

**OOMKilled (Out of Memory Killed)** — причина (`Reason`) завершения контейнера, означающая, что процесс был принудительно завершен ядром ОС узла из-за превышения выделенного лимита памяти контрольной группы (cgroup) или критической нехватки ресурсов на всем узле.

*   **Код выхода:** `137` (128 + SIGKILL/9).
*   **SIGKILL:** Процесс убивается немедленно, без возможности выполнить обработчики завершения или сохранить данные.
*   **Тихий OOM (Silent OOM):** Специфичное для cgroups v2 поведение, при котором ядро завершает только один ресурсоемкий дочерний процесс внутри контейнера. Если PID 1 (основной процесс) остается жив, контейнер не перезапускается, но приложение начинает работать некорректно.

**Ключевое отличие от ограничений CPU:**
- **CPU Limit**: При превышении контейнер **дросселируется** (замедляется), но продолжает работать.
- **Memory Limit**: При превышении контейнер **уничтожается** немедленно.

## Основные концепции

### Механизм OOM Killer в Kubernetes

OOMKilled происходит на уровне ядра ОС через контрольные группы (**cgroups**). 

**Взаимодействие компонентов:**
1. **Container**: Пытается выделить память сверх лимита, установленного в `cgroups` (v1: `memory.limit_in_bytes`, v2: `memory.max`).
2. **Linux Kernel**: Обнаруживает нарушение, выбирает процесс внутри этой cgroup (обычно с самым высоким потреблением) и отправляет ему `SIGKILL`.
3. **Kubelet**: Замечает завершение контейнера через рантайм (containerd/docker), считывает причину из ядра и обновляет статус Pod на `OOMKilled`.

**Схема процесса:**
```text
Приложение потребляет память (аллокация в Heap/Stack)
    ↓
Достижение лимита limits.memory (cgroups v1/v2)
    ↓
Ядро вызывает групповой OOM Killer
    ↓
Процесс завершается (SIGKILL, код выхода 137)
    ↓
Kubelet фиксирует событие и причину через API рантайма
    ↓
Статус пода обновляется: Reason: OOMKilled
    ↓
Контейнер перезапускается согласно RestartPolicy (RestartCount++)
```

### Различия: OOMKilled vs Eviction (Выселение)

| Признак | OOMKilled | Eviction (Выселение) |
|:---|:---|:---|
| **Инициатор** | Ядро Linux (Kernel) | Kubelet |
| **Причина** | Превышен лимит *контейнера* или критический дефицит на *узле*. | Нехватка ресурсов (Memory/Disk/PIDs) на *всем узле*. |
| **Сигнал** | `SIGKILL` (мгновенно) | `SIGTERM` (мягко) -> `SIGKILL` (по таймауту) |
| **Статус** | `Reason: OOMKilled` | `Status: Failed`, `Reason: Evicted` |
| **Место перезапуска** | На том же узле | На другом узле (Scheduler выбирает новую ноду) |

### Связь с классами QoS и oom_score_adj

Kubernetes управляет приоритетом выживания процессов при **системном OOM** (когда память кончилась на всей ноде) через параметр ядра `/proc/self/oom_score_adj`.

| Класс QoS | Условия | oom_score_adj | Описание |
|:---|:---|:---|:---|
| **Guaranteed** | `requests` == `limits` | **-997** | Практически не убивается ядром при системном OOM, пока не превысит свои лимиты. |
| **Burstable** | `requests` < `limits` | **2 – 999** | Может быть завершен, если узлу нужна память. Значение рассчитывается: чем больше `requests`, тем ниже score. |
| **BestEffort** | Нет лимитов/запросов | **1000** | Первый кандидат на OOM при нехватке памяти на узле. |

Подробнее о расчетах: [Выселение подов и oom_score_adj](./PodEvicted/qos_and_eviction.md).

## Практические сценарии

### Алгоритм диагностики

#### Шаг 1: Проверка статуса пода
```bash
kubectl describe pod <pod-name>
```
Ищите в секции `Containers` -> `Last State`:
```text
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
  Started:      Mon, 01 Jan 2024 10:00:00 +0000
  Finished At:  Mon, 01 Jan 2024 10:15:00 +0000
```
Также проверьте `Restart Count` — если он растет, проблема носит системный характер.

#### Шаг 2: Анализ текущего потребления памяти
```bash
# Текущее использование vs limits
kubectl top pod <pod-name> --containers

# Пример вывода:
# CONTAINER   CPU(cores)   MEMORY(bytes)
# app         150m         489Mi
# sidecar     25m          64Mi
```
Сравните с `resources.limits.memory` в манифесте. Если потребление приближается к лимиту — проблема в insufficient limits или утечке памяти.

#### Шаг 3: Проверка метрик: Working Set vs RSS
При настройке мониторинга в Prometheus/Grafana важно использовать правильную метрику. Лимит в Kubernetes проверяется по **Working Set**.
*   **RSS (Resident Set Size)**: Память, реально занимаемая данными процесса в RAM.
*   **Working Set**: RSS + кэш страниц (file cache), который ядро **не может** освободить в данный момент. Именно эта метрика сравнивается с `limits.memory`.
*   **PromQL для алертинга**:
    ```promql
    # Заполнение лимита памяти в %
    container_memory_working_set_bytes{container!=""} / container_spec_memory_limit_bytes > 0.85
    ```
*   **Детальный разбор памяти контейнера**:
    ```promql
    # Статистика по типам памяти
    container_memory_rss{pod="<pod>"}          # Процесс + heap
    container_memory_cache{pod="<pod>"}        # Файловый кэш (перезаписываемый)
    container_memory_mapped_file{pod="<pod>"}  # memory-mapped файлы
    container_memory_swap{pod="<pod>"}         # Swap (если включен)
    ```

#### Шаг 4: Проверка логов ядра (Node Level)
Если в `describe` причина неясна (например, "Error" при коде 137), необходимо проверить сообщения OOM Killer напрямую:
```bash
# Логи ядра на узле
ssh <node-name> "dmesg -T | grep -iE 'oom-killer|killed process' -C 5"
```
**Признак Container OOM**: в логе будет указано `Memory cgroup out of memory: Killed process ...`.

**Признак системного OOM**: в логе будет `Out of memory: Kill process` без упоминания `Memory cgroup` — это означает, что убит процесс на уровне хоста (не контейнера).

#### Шаг 5: Проверка событий (Events)
```bash
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i "oom\|kill\|memory"
```
Ищите события типа `Killing` или `OOMKilling` с указанием имени пода.

#### Шаг 6: Анализ PIDs и процессов внутри контейнера
Для-live диагностики (если контейнер еще работает, но потребляет много памяти):
```bash
# Через ephemeral container (K8s 1.23+)
kubectl debug -it <pod-name> --image=busybox --target=<container-name> -- sh

# Или через kubectl exec (если в контейнере есть shell)
kubectl exec -it <pod-name> -c <container-name> -- /bin/sh
```
Внутри контейнера:
```sh
# Процессы и их потребление памяти
ps aux --sort=-%mem | head -10

# Или через /proc (точнее)
cat /proc/1/status | grep -i vm
# → VmRSS:  491520 kB   (resident set size)
# → VmSize: 1048576 kB  (total virtual memory)
```

#### Шаг 7: Проверка LimitRange и ResourceQuota
OOMKilled может быть вызван не только явными limits в поде, но и настройками кластера:
```bash
# Проверка LimitRange в namespace
kubectl get limitrange -n <namespace> -o yaml

# Проверка ResourceQuota
kubectl describe resourcequota -n <namespace>
```
Если `LimitRange` задает `default` или `defaultRequest` для памяти, поды без явных limits получают значения по умолчанию, которые могут оказаться недостаточными.

### Настройка рантаймов и языковых сред

Чтобы избежать OOMKilled, рантайм приложения должен "видеть" лимиты контейнера.

#### Java (JDK 17+)
Используйте процентное управление кучей.
```yaml
env:
- name: JAVA_TOOL_OPTIONS
  value: "-XX:MaxRAMPercentage=75.0" # Рекомендуется 75-80% для запаса под Metaspace и стек
```

#### Go (1.19+)
Установите `GOMEMLIMIT`, чтобы сборщик мусора (GC) срабатывал до достижения лимита cgroup.
```yaml
env:
- name: GOMEMLIMIT
  value: "900MiB" # Для лимита контейнера в 1GiB
```

#### Node.js
V8 требует явного указания лимита кучи.
```yaml
env:
- name: NODE_OPTIONS
  value: "--max-old-space-size=800" # В МБ, примерно 80% от лимита
```

#### .NET (8/9+)
Рантайм .NET хорошо адаптирован к cgroups v2, но для стабильности можно использовать:
```yaml
env:
- name: DOTNET_GCHeapHardLimit
  value: "0x38400000" # Значение в байтах (900MiB)
```

#### Python
CPython не имеет автоматического контроля потребления памяти через cgroups. Основные инструменты:
*   **tracemalloc**: Встроенный модуль для отслеживания аллокаций. Используйте в development/staging для поиска утечек.
*   **objgraph**: Визуализация графа объектов для обнаружения циклических ссылок.
*   **py-spy**: Сэмплирующий профилировщик (не требует инструментирования кода).

```python
# tracemalloc: снимок аллокаций
import tracemalloc
tracemalloc.start()
# ... код ...
snapshot = tracemalloc.take_snapshot()
for stat in snapshot.statistics('lineno')[:10]:
    print(stat)
```

```yaml
# Если приложение использует gunicorn/uvicorn с воркерами,
# учитывайте: лимит памяти делится между воркерами
env:
- name: MALLOC_MMAP_THRESHOLD_
  value: "65536"  # Оптимизация аллокаций через mmap
```

> **Важно:** Python-приложения с высоким потреблением памяти (ML, data processing) рекомендуется запускать в `Guaranteed` QoS (`requests == limits`), чтобы избежать вытеснения при системном OOM.

#### Ruby
Ruby (MRI) использует GC, который не всегда эффективно работает с cgroups лимитами.
```yaml
env:
- name: RUBY_GC_HEAP_INIT_SLOTS
  value: "1000000"  # Начальный размер heap
- name: RUBY_GC_HEAP_FREE_SLOTS
  value: "500000"   # Свободные слоты для предотвращения частых GC
```
Для приложений на **Rails** рекомендуется также настроить `MALLOC_ARENA_MAX` для ограничения использования памяти аллокатором jemalloc/tcmalloc:
```yaml
env:
- name: MALLOC_ARENA_MAX
  value: "2"  # Ограничение арен (по умолчанию 8 * CPU)
```

### Мини-кейсы из практики

#### Кейс 1: Поиск утечки в кэширующем слое
*   **Симптом**: Микросервис падает по OOM каждые 48 часов. График в Grafana имеет вид «пилы» (Sawtooth pattern).
*   **Анализ**: Снят дамп кучи (Heap Dump) при достижении 85% использования лимита.
*   **Причина**: Объект внутреннего кэша (HashMap) рос бесконтрольно, старые ключи не удалялись.
*   **Решение**: Внедрение политики LRU (Least Recently Used) для кэша и установка `GOMEMLIMIT` для Go-приложения.

#### Кейс 2: Java-сервис и "тихий" OOM
*   **Симптом**: Под в статусе Running, но API не отвечает (Readiness Probe Fail).
*   **Анализ**: `dmesg` показал, что ядро убило `java` процесс, но в контейнере работал вспомогательный bash-скрипт (PID 1), который не завершился.
*   **Решение**: Использование `tini` или `dumb-init` в качестве Entrypoint для корректной проброски сигналов и завершения контейнера при падении основного процесса.

#### Кейс 3: Init-контейнер с OOMKilled
*   **Симптом**: Под застрял в `Init:OOMKilled`. Основной контейнер не запускается.
*   **Анализ**: `kubectl describe pod` показывает `Last State` для init-контейнера с `Reason: OOMKilled`. Init-контейнер выполняет миграцию БД или загрузку конфигов, требующую больше памяти.
*   **Решение**: Увеличить `resources.limits.memory` для init-контейнера. Init-контейнеры имеют **собственные** лимиты, изолированные от основных контейнеров.
```yaml
initContainers:
- name: db-migration
  image: flyway:latest
  resources:
    limits:
      memory: 512Mi  # Увеличить если миграция потребляет много памяти
```

#### Кейс 4: Sidecar "съедает" лимиты основного приложения
*   **Симптом**: Основное приложение падает по OOM, хотя его собственное потребление памяти в норме.
*   **Анализ**: Суммарное потребление всех контейнеров в поде приближается к `node.allocatable`, и срабатывает системный OOM Killer (а не cgroup-уровневый).
*   **Причина**: Sidecar-контейнеры (istio-proxy, fluent-bit, vault-agent) потребляют больше ожидаемого. Хотя у каждого контейнера свои cgroups limits, при **системном** OOM (на уровне ноды) ядро учитывает общее потребление.
*   **Решение**: Явно задать лимиты для sidecar-контейнеров и мониторить их потребление:
```bash
kubectl top pod <pod-name> --containers
# → Проверить, не превышает ли sidecar свои requests
```

#### Кейс 5: Рост памяти после обновления приложения
*   **Симптом**: После деплоя новой версии приложения OOMKilled появляются впервые или участились.
*   **Анализ**: Сравнение метрик `container_memory_working_set_bytes` до и после деплоя. График показывает рост baseline потребления на 30-40%.
*   **Причина**: Новая версия引入了новые зависимости (библиотеки, модели) или изменила паттерн потребления памяти.
*   **Диагностика**:
    1. Сравните heap dumps (до/после) через `jmap -dump:live,format=b,file=heap.hprof <pid>` (Java) или `go tool pprof` (Go).
    2. Проверьте changelog на наличие новых компонентов, требующих памяти.
    3. Используйте `git bisect` для определения конкретного коммита, вызвавшего рост.
*   **Решение**: Увеличить лимиты или оптимизировать потребление в новой версии.

#### Кейс 6: OOMKilled при масштабировании (HPA)
*   **Симптом**: При увеличении количества реплик через HPA поды падают по OOM.
*   **Анализ**: Новые поды запускаются на узлах с недостаточным количеством RAM. Scheduler размещает их, но kubelet не может выделить достаточно памяти.
*   **Причина**: `requests.memory` занижены, HPA создает больше реплик, чем физически может поместиться на кластере.
*   **Решение**:
    1. Увеличить `requests.memory` до реального потребления (или использовать VPA для рекомендаций).
    2. Настроить `cluster-autoscaler` для добавления узлов при нехватке ресурсов.
    3. Ограничить максимальное количество реплик в HPA (`maxReplicas`).

## Современные возможности (2025-2026)

### Swap в Kubernetes (v1.31+)
K8s теперь официально поддерживает Swap на узлах.
*   **Плюс**: Контейнер может временно использовать диск вместо немедленного падения по OOM.
*   **Минус**: **Disk Thrashing** — резкий рост I/O Wait и падение производительности CPU. Рекомендуется только для некритичных пакетных (batch) задач.

### In-Place Pod Resize (v1.35+)
Позволяет изменить `limits.memory` без перезагрузки пода.
```bash
# Пример патча для экстренного расширения лимитов
kubectl patch pod <pod-name> --subresource resize --type json \
  -p '[{"op": "replace", "path": "/spec/containers/0/resources/limits/memory", "value": "2Gi"}]'
```

## Профилактика

### Правила установки лимитов

1.  **requests == limits (Guaranteed QoS)**: Для критичных сервисов устанавливайте `requests` равными `limits`. Это гарантирует выделение ресурсов и защиту от вытеснения (eviction).
2.  **Запас на overhead**: Лимит памяти должен быть на **20-30%** выше потребления приложения с учетом overhead рантайма (Metaspace в JVM, thread stacks, native allocations).
3.  **Startup Probes**: Используйте для приложений (Spring, Rails, Go с large init), потребляющих много памяти только при инициализации. Без startup probe liveness probe может убить под до готовности.
4.  **Лимиты для Sidecars**: Не забывайте ограничивать `istio-proxy`, `fluent-bit` и другие вспомогательные контейнеры. Потребление sidecar'ов растет пропорционально нагрузке на основное приложение.
5.  **LimitRange**: Настройте `default` и `defaultRequest` для памяти в namespace, чтобы поды без явных limits не оказались в `BestEffort` QoS.
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
spec:
  limits:
  - default:
      memory: 512Mi
    defaultRequest:
      memory: 256Mi
    type: Container
```

### Vertical Pod Autoscaler (VPA)

VPA в режиме `Auto` автоматически корректирует лимиты на основе истории потребления. Рекомендуется для workloads с переменным потреблением памяти.
```bash
# Проверка рекомендаций VPA
kubectl describe vpa <vpa-name> -n <namespace>
# Ищите секцию "RECOMMENDED VALUES"
```

### Мониторинг и алертинг

Настройте алерты на приближение к лимитам:
```yaml
# Prometheus alert rule
groups:
- name: memory-alerts
  rules:
  - alert: ContainerMemoryNearLimit
    expr: |
      container_memory_working_set_bytes{container!=""}
      / container_spec_memory_limit_bytes > 0.85
      and container_spec_memory_limit_bytes > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Контейнер {{ $labels.container }} в поде {{ $labels.pod }} приближается к лимиту памяти"
      description: "Использование памяти: {{ $value | humanizePercentage }} от лимита"
```

### Профилирование памяти в production

Для глубокого анализа утечек памяти используйте профилировщики:

| Язык | Инструмент | Команда | Описание |
|:---|:---|:---|:---|
| **Go** | pprof | `go tool pprof http://localhost:6060/debug/pprof/heap` | Стандартный профилировщик, встроен в `net/http/pprof` |
| **Java** | async-profiler | `./profiler.sh -d 30 -f heap.html <pid>` | Low-overhead profiling, визуализация flame graphs |
| **Java** | JFR (Java Flight Recorder) | `jcmd <pid> JFR.start duration=60s filename=recording.jfr` | Встроенный в JDK recorder для continuous profiling |
| **Python** | memory_profiler | `python -m memory_profiler app.py` | Пошаговый анализ потребления памяти |
| **Node.js** | `--inspect` + Chrome DevTools | `node --inspect app.js` | Встроенный heap dump через DevTools |

**Важно:** Не публикуйте pprof-эндпоинты в публичный контур. Используйте ephemeral containers или kubectl port-forward для безопасного доступа:
```bash
kubectl port-forward <pod-name> 6060:6060
# Затем: go tool pprof http://localhost:6060/debug/pprof/heap
```

## Дополнительная информация

### Инструменты анализа
- **Goldilocks**: Рекомендации по ресурсам на основе истории потребления (использует VPA Recommender).
- **Kube-capacity**: Визуализация загрузки кластера по узлам и подам.
- **Popeye**: Сканер ресурсов на предмет несоответствий и отсутствия лимитов.
- **Kubecost**: Анализ стоимости ресурсов и выявление неиспользуемых лимитов.

### Механизмы cgroups v2 для защиты от OOM

На узлах с **cgroups v2** (стандарт для ядер 5.x+ и современных дистрибутивов) доступны дополнительные механизмы контроля памяти:

| Параметр | Тип | Описание |
|:---|:---|:---|
| `memory.min` | Hard guarantee | Память, которая **никогда** не будет отобрана ядром. Соответствует `requests.memory`. |
| `memory.low` | Best-effort guarantee | Ядро пытается не отбирать эту память, пока это возможно. |
| `memory.high` | Soft limit (throttle) | При достижении ядро начинает замедлять процессы, заставляя их освобождать память. |
| `memory.max` | Hard limit | Абсолютный потолок. Превышение ведет к OOM Killer. Соответствует `limits.memory`. |

**Рекомендация:** Устанавливайте `memory.high` на уровне **80%** от `memory.max`. Это позволяет приложению получить сигнал о давлении памяти и самостоятельно освободить ресурсы до принудительного убийства.

```bash
# Проверка текущих значений на узле
cat /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/memory.max
cat /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/memory.high

# Проверка событий OOM в cgroups v2
cat /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/memory.events
# → oom: 0, oom_kill: 0, oom_group_kill: 0
```

### PSI (Pressure Stall Information)

Метрики PSI показывают, какой процент времени процессы проводят в ожидании освобождения памяти:
```bash
# Проверка давления памяти на узле
cat /proc/pressure/memory
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```
*   **some**: Процент времени, когда хотя бы один процесс был заблокирован из-за нехватки памяти.
*   **full**: Процент времени, когда **все** процессы были заблокированы.

### Восстановление после OOMKilled

1.  **Проверьте RestartCount**: Если контейнер перезапускается бесконечно (CrashLoopBackOff), значит проблема сохраняется.
2.  **Проанализируйте логи до падения**: `kubectl logs <pod-name> --previous` — покажет логи предыдущего контейнера.
3.  **Снимите heap dump** (если возможно) перед следующим падением для анализа утечки.
4.  **Увеличьте лимиты** или оптимизируйте потребление памяти в приложении.
5.  **Проверьте邻居-поды**: Убедитесь, что другие поды на том же узле не забирают чрезмерное количество ресурсов.

### Типичные ошибки при диагностике

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Путаница `OOMKilled` и `Eviction` | OOMKilled — ядро убивает контейнер (exit code 137). Eviction — kubelet удаляет под (Reason: Evicted). | Проверяйте `status.lastState.terminated.reason` и `status.reason` |
| Использование RSS вместо Working Set | Лимиты в K8s проверяются по Working Set, а не RSS | Используйте `container_memory_working_set_bytes` в PromQL |
| Игнорирование sidecar-контейнеров | Суммарное потребление всех контейнеров влияет на системный OOM | Мониторьте `kubectl top pod --containers` |
| Отсутствие LimitRange | Поды без limits попадают в BestEffort QoS и убиваются первыми | Настройте LimitRange в namespace |
| Занижение requests | Вызывает Burstable QoS и повышает oom_score_adj | Используйте VPA для рекомендаций |

### См. также
- [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md)
- [Выселение подов (Eviction)](./PodEvicted/definitions.md)
- [Диагностика проблем Kubernetes](../troubleshooting_overview.md)
- [OOM Killer в контейнерах (Ядро Linux)](../../../Linux/Core/processes/oom_killer_containers.md)
- [Тюнинг Java (JVM)](../../../Linux/Development/java_management.md)
