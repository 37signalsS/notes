# Поды, завершенные из-за нехватки памяти (OOMKilled)

## Определения

**OOMKilled (Out of Memory Killed)** — причина (`Reason`) завершения контейнера, означающая, что процесс был принудительно завершен ядром ОС узла из-за превышения выделенного лимита памяти. Это не статус пода, а индикатор состояния конкретного контейнера.

**Код выхода:** `137` (128 + SIGKILL/9)

## Основные концепции

### Механизм OOM Killer в Kubernetes

OOMKilled происходит на уровне ядра ОС (через контрольные группы — cgroups). Когда процесс достигает лимита памяти, ядро вызывает OOM Killer для немедленного завершения процесса.

```
Приложение потребляет память
    ↓
Превышен limits.memory (cgroups v1/v2)
    ↓
Ядро вызывает OOM Killer
    ↓
Процесс завершается (SIGKILL)
    ↓
Контейнер перезапускается (RestartCount++)
```

**Ключевое отличие от выселения (Eviction):**

- **OOMKilled**: Реакция ядра на превышение лимита *конкретным контейнером* или критическую нехватку памяти на узле. Процесс убивается мгновенно.
- **Eviction**: Реакция `kubelet` на нехватку ресурсов *всего узла*. `kubelet` сам выбирает поды для выселения (согласно QoS), выполняет корректное завершение (graceful shutdown) и помечает статус как `Evicted`.

### Связь с классами QoS и oom_score_adj

Kubernetes управляет приоритетом выживания процессов при нехватке памяти через параметр ядра `oom_score_adj` (от -1000 до 1000).

| Класс QoS | Условия | oom_score_adj | Описание |
|:---|:---|:---|:---|
| **Guaranteed** | `requests` == `limits` | **-997** | Почти никогда не убивается ядром при OOM на узле, пока не превысит свои лимиты. |
| **Burstable** | `requests` < `limits` | **2 – 999** | Может быть завершен, если узлу нужна память. Значение зависит от объема `requests`. |
| **BestEffort** | Нет лимитов/запросов | **1000** | Первый кандидат на OOM при нехватке памяти на узле. |

Подробнее о механизмах ядра: [OOM Killer в контейнерах](../../../Linux/Core/processes/oom_killer_containers.md).

### Типы OOM-событий

| Тип | Описание | Основная причина |
|:---|:---|:---|
| **Container OOM** | Контейнер превысил свой `limits.memory` | Недоресурсирование, утечка памяти в приложении. |
| **Node OOM** | Узел исчерпал всю доступную память | Отсутствие лимитов у подов, нехватка ресурсов узла для системных компонентов. |

## Практические сценарии

### Диагностика

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

Ищите в секции `Containers` -> `Last State`:
```text
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
  Finished At:  ...
```

#### Шаг 2: Анализ потребления в реальном времени

```bash
# Текущее потребление ресурсов
kubectl top pod <pod-name> --containers

# Использование kubectl debug для анализа запущенного контейнера
kubectl debug -it <pod-name> --image=busybox --target=<container-name>
```

#### Шаг 3: Проверка логов ядра и событий

Если `describe` не дает полной картины (например, OOM на уровне узла):

```bash
# События на узле
kubectl get events --field-selector involvedObject.kind=Node --sort-by='.lastTimestamp'

# Логи ядра (требуется доступ к узлу)
ssh <node-name> "dmesg -T | grep -i 'oom-killer' -C 5"
```

### Распространенные случаи и решения

#### 1. Превышение лимитов (limits.memory)

**Симптом:** Приложение падает сразу после достижения пиковой нагрузки.

**Решение:** Увеличьте лимиты, основываясь на данных мониторинга.
```yaml
resources:
  requests:
    memory: "512Mi"
  limits:
    memory: "1Gi" # Запас 20-30% над типичным пиком
```

#### 2. Утечка памяти (Memory Leak)

**Симптом:** Постепенный рост потребления памяти (пилообразный график рестартов).

**Диагностика:**
- Для Go: `pprof`.
- Для Python: `tracemalloc`, `objgraph`.
- Для Node.js: `--inspect` и Chrome DevTools.

#### 3. Настройка JVM в контейнерах (Java 11/17/21+)

Современные версии Java (начиная с 8u191, 11+) корректно распознают лимиты контейнера.

**Рекомендация:** Используйте процентное управление кучей (Heap), чтобы оставить место для non-heap памяти (Metaspace, Stack, Direct Buffers).

```yaml
env:
- name: JAVA_TOOL_OPTIONS
  value: "-XX:MaxRAMPercentage=75.0 -XX:InitialRAMPercentage=50.0"
resources:
  limits:
    memory: "1Gi" # JVM увидит 1Gi и выделит ~768Mi под Heap
```

#### 4. OOM при запуске

**Причина:** Высокое потребление при инициализации бинов (Spring) или загрузке кэшей.

**Решение:** Используйте `Startup Probe` для отделения фазы запуска от проверок работоспособности.

### Профилактика

#### 1. Мониторинг и алертинг

Настройте алерты на `container_memory_working_set_bytes` в процентах от лимита.
Инструкции: [Алерты для Kubernetes в Grafana](../../../Grafana/alerting/kubernetes_alerts.md).

#### 2. Изменение ресурсов "на лету" (In-Place Pod Resize)

В Kubernetes 1.35+ (Stable) можно менять ресурсы без перезагрузки пода (если `resizePolicy: NotRequired`).

```bash
# Пример патча через подресурс resize
kubectl patch pod <pod-name> --subresource resize --type json \
  -p '[{"op": "replace", "path": "/spec/containers/0/resources/limits/memory", "value": "2Gi"}]'
```

#### 3. Vertical Pod Autoscaler (VPA)

VPA в режиме `Auto` или `Recommender` поможет подобрать оптимальные лимиты. Подробнее: [Vertical Pod Autoscaler](../../Autoscaling/vpa_detailed.md).

#### 4. Лучшие практики настройки ресурсов

| Практика | Описание |
|:---|:---|
| **Requests ~= Limits** | Для критичных сервисов (QoS Guaranteed), чтобы избежать вытеснения. |
| **Лимиты > Requests** | Для некритичных нагрузок (Burstable), чтобы эффективно использовать узел. |
| **Анализ Working Set** | Ориентируйтесь на `working_set_bytes`, а не на `rss`. |
| **GOMEMLIMIT (Go)** | Для Go 1.19+ всегда задавайте `GOMEMLIMIT` чуть меньше лимита памяти контейнера. |

## Дополнительная информация

### Инструменты анализа

- **Goldilocks**: Рекомендации по ресурсам на основе VPA.
- **Kube-capacity**: Визуализация загрузки кластера.
- **Popeye**: Сканер ресурсов на предмет несоответствий.

### См. также

- [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md)
- [Выселение подов (Eviction)](./PodEvicted/definitions.md)
- [Диагностика проблем Kubernetes](../troubleshooting_overview.md)
