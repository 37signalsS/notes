# Pod Evicted: Реальные кейсы инцидентов (Postmortem)

## Определения

**Postmortem инцидента** — структурированный разбор произошедшего сбою: хронология, первопричина, принятые меры и предотвращение повторения. В контексте Pod Eviction постмортемы позволяют выявить системные проблемы конфигурации кластера, а не просто исправить симптом.

**Цели анализа инцидента:**
1. **Root Cause Analysis (RCA):** Определение первопричины, а не симптома.
2. **Blast Radius:** Оценка масштаба затронутых сервисов.
3. **Action Items:** Конкретные меры по предотвращению повторения.
4. **Lessons Learned:** Архитектурные выводы для будущих инцидентов.

## Основные концепции

### Структура постмортема

Каждый кейс описывается по единой структуре:

| Поле | Описание |
|:---|:---|
| **Симптом** | Что увидели операторы/мониторинг |
| **Время инцидента** | Когда произошло (часы простоя) |
| **Затронутые компоненты** | Какие сервисы и узлы пострадали |
| **Хронология** | Последовательность событий |
| **Первопричина** | Что реально вызвало инцидент |
| **Корректирующие меры** | Что сделали немедленно |
| **Превентивные меры** | Что сделали для предотвращения повторения |
| **Метрики для мониторинга** | Какие алерты настроили |

## Практические сценарии

### Кейс 1: Циклический DiskPressure из-за логов

**Симптом:** Ночью сработал алерт на DiskPressure. К утру узел потерял 3 Worker-ноды. Поды мигрировали, но часть API-запросов вернула 503.

**Время инцидента:** 4 часа простоя, 12% запросов API получили 503.

**Затронутые компоненты:** 3 Worker-ноды, 47 подов (API Gateway, Order Service, Notification Service).

**Хронология:**
```
02:00 — Приложение Order Service начало писать debug-логи (из-за случайного флага)
02:30 — Логи заполнили /var/log/pods/ (размер логов вырос с 2Gi до 40Gi)
03:00 — kubelet обнаружил DiskPressure, начал Garbage Collection образов
03:05 — GC удалил все неиспользуемые образы (включая образ Order Service)
03:10 — Поды Order Service не могут перезапуститься (ImagePullBackOff)
03:15 — HPA пытается масштабировать, но поды не стартуют
03:20 — API Gateway возвращает 503 (нет бэкенда)
04:00 — Оператор заметил алерт, начал диагностику
04:30 — Остановил debug-логирование в Order Service
04:45 — Очистил неиспользуемые образы (crictl rmi --prune)
05:00 — Поды Order Service пересоздались, сервис восстановлен
```

**Первопричина:** Отсутствие `ephemeral-storage` limits для Order Service + отсутствие `sizeLimit` для `emptyDir` + агрессивный debug-level в production.

**Корректирующие меры:**
1. Добавлен `resources.limits.ephemeral-storage: "2Gi"` для Order Service.
2. Добавлен `emptyDir.sizeLimit: "1Gi"` для временных данных.
3. Отключен debug-level в production (настроен через Feature Flag).
4. Настроен алерт: `(1 - node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100 > 85`.

**Превентивные меры:**
1. Внедрение LimitRange с `default` для `ephemeral-storage` во все namespace.
2. Регулярная очистка образов через CronJob (`crictl rmi --prune`).
3. Мониторинг `containerLogMaxSize` и `containerLogMaxFiles`.

**Метрики для мониторинга:**
```promql
# DiskPressure на узлах
kube_node_status_condition{condition="DiskPressure", status="true"} == 1

# Прогноз исчерпания диска
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 3600 * 24) < 0

# Количество выселенных подов за час
increase(kube_pod_status_reason{reason="Evicted"}[1h])
```

> Связанные темы: **[Выселение по диску](./disk_eviction.md)**, **[Профилактика выселения](./prevention.md)**.

---

### Кейс 2: Cascade Eviction при нехватке RAM

**Симптом:** Массовое выселение подов на 5 узлах одновременно. Все BestEffort и Burstable поды были удалены. Guaranted поды выжили, но их производительность упала.

**Время инцидента:** 45 минут простоя, частичная деградация.

**Затронутые компоненты:** 5 Worker-нод, 200+ подов, все BestEffort поды (мониторинг, логирование), часть Burstable подов (API).

**Хронология:**
```
14:00 — Запущен тяжелый батч-процесс (Batch Job) на 3 узлах
14:15 — Batch Job потребил 80% RAM на каждом узле (не имел limits)
14:20 — kubelet обнаружил MemoryPressure, начал выселение BestEffort подов
14:25 — Выселены все BestEffort поды (Prometheus, Fluent Bit, Node Exporter)
14:30 — Мониторинг стал невидимым (нет метрик)
14:35 — Batch Job продолжал потреблять RAM, MemoryPressure усилился
14:40 — Началось выселение Burstable подов (API Gateway, User Service)
14:45 — API Gateway выселен, все API-запросы возвращают 503
15:00 — Оператор остановил Batch Job вручную
15:15 — Поды начали пересоздаваться
15:30 — Сервис восстановлен
```

**Первопричина:** Batch Job без `resources.limits.memory` и `resources.requests.memory`. Под имел класс BestEffort и потреблял неограниченное количество RAM.

**Корректирующие меры:**
1. Добавлены `requests` и `limits` для Batch Job (`memory: "4Gi"`, `cpu: "2"`).
2. Batch Job перемещён в отдельный namespace с ResourceQuota.
3. Настроен алерт на mass eviction: `increase(kube_pod_status_reason{reason="Evicted"}[1h]) > 5`.

**Превентивные меры:**
1. LimitRange с `default` для memory во всех namespace.
2. ResourceQuota с `scope: BestEffort` для ограничения BestEffort подов.
3. NetworkPolicy для изоляции batch-рабочих нагрузок от production.
4. Admission Controller (Kyverno/Gatekeeper), блокирующий поды без `requests`/`limits`.

**Метрики для мониторинга:**
```promql
# Mass eviction
increase(kube_pod_status_reason{reason="Evicted"}[1h]) > 5

# BestEffort поды в production
count by (namespace) (kube_pod_status_qos_class{namespace="production", qos="BestEffort"}) > 0

# MemoryPressure на узлах
kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
```

> Связанные темы: **[QoS и выселение](./qos_and_eviction.md)**, **[Выселение по памяти](./memory_eviction.md)**.

---

### Кейс 3: PDB Deadlock при обновлении узлов

**Симптом:** `kubectl drain` зависает на 2 узлах. Оператор не может обновить ОС на узлах. Кластер работает, но обслуживание невозможно.

**Время инцидента:** 8 часов (ожидание), сервис не пострадал.

**Затронутые компоненты:** 2 Control Plane узла, deployment pipeline заблокирован.

**Хронология:**
```
10:00 — Запущен плановый drain для обновления ОС
10:01 — drain завершился ошибкой: "cannot evict pod as it would violate the pod's disruption budget"
10:05 — Оператор проверил PDB: minAvailable: 3, replicas: 3 (все поды в PDB)
10:10 — PDB блокирует выселение любого пода (disruptionsAllowed: 0)
10:15 — Оператор попытался scale deployment до 5 реплик
10:20 — Scale-up сработал, но drain по-прежнему блокируется (PDB minAvailable: 3)
10:25 — HPA начал масштабировать вниз (нет нагрузки), replicas вернулись к 3
10:30 — Ситуация стабилизировалась: drain блокирован, HPA уменьшает replicas
14:00 — Оператор обратился за помощью
14:30 — Увеличены replicas до 6 вручную
14:35 — Drain прошёл успешно (disruptionsAllowed: 3)
14:40 — Узел обновлён, drain второго узла
15:00 — Оба узла обновлены
15:05 — Replicas возвращены к 3
```

**Первопричина:** PDB с `minAvailable: 3` при `replicas: 3` полностью блокирует все выселения. Нет запаса для обслуживания.

**Корректирующие меры:**
1. PDB изменён на `maxUnavailable: 1` (вместо `minAvailable: 3`).
2. Добавлена политика `unhealthyPodEvictionPolicy: AlwaysAllow` (K8s 1.30+).
3. В pipeline обновления узлов добавлен pre-drain check: `kubectl drain --dry-run=client`.

**Превентивные меры:**
1. Рекомендация: всегда использовать `maxUnavailable: 1` вместо `minAvailable` для Deployment.
2. Для StatefulSet: `minAvailable = ⌈N/2⌉` (3 реплики → 2).
3. Добавление в CI/CD проверку: PDB не должен блокировать drain.
4. Документирование процедуры: перед drain → проверить PDB → увеличить replicas → drain → восстановить replicas.

**Метрики для мониторинга:**
```promql
# PDB заблокирован
kube_poddisruptionbudget_status_disruptions_allowed == 0

# PDB близок к лимиту
kube_poddisruptionbudget_status_current_healthy / kube_poddisruptionbudget_status_desired_healthy < 1.2
```

> Связанные темы: **[PDB и Taint Eviction](./pdb_and_taint_eviction.md)**, **[Обслуживание узлов](../../../Operations/node_maintenance.md)**, **[HPA Troubleshooting](../hpa_troubleshooting.md)**.

---

### Кейс 4: Fork-bomба из-за контейнера

**Симптом:** Узел перешёл в PIDPressure. Новые поды не запускаются (`fork: Cannot allocate memory`). SSH-доступ работает.

**Время инцидента:** 30 минут, 1 узел, 15 подов не могут запуститься.

**Затронутые компоненты:** 1 Worker-нод, все поды на этом узле.

**Хронология:**
```
16:00 — Приложение Release Worker запустило дочерний процесс без проверки PID лимита
16:05 — Дочерний процесс начал fork-ать бесконечно (рекурсивный spawn)
16:10 — Количество PID на узле достигло kernel.pid_max (32768)
16:12 — kubelet обнаружил PIDPressure, начал выселение подов с наименьшим приоритетом
16:15 — Выселены BestEffort поды (мониторинг, логирование)
16:20 — Release Worker всё ещё fork-ает (не имеет podPidsLimit)
16:25 — Все поды на узле выселены, Release Worker продолжает потреблять PID
16:30 — Оператор через SSH: kill -9 <initiator-PID>
16:32 — Fork-бомба остановлена
16:35 — PIDPressure снят, поды начали пересоздаваться
```

**Первопричина:** Приложение без проверки PID лимита + отсутствие `podPidsLimit` в kubelet.

**Корректирующие меры:**
1. Добавлен `podPidsLimit: 4096` в KubeletConfiguration.
2. Для Release Worker добавлен `securityContext.linuxOptions.pidsLimit: 2048`.
3. Настроен алерт на PIDPressure.

**Превентивные меры:**
1. `podPidsLimit` на всех узлах (значение по умолчанию `-1` = без лимита).
2. В Admission Policy проверять наличие `pidsLimit` для критических подов.
3. Мониторинг количества процессов на узле.

**Метрики для мониторинга:**
```promql
# PIDPressure на узлах
kube_node_status_condition{condition="PIDPressure", status="true"} == 1

# Количество процессов на узле
process_count{job="node-exporter"} > 30000
```

> Связанные темы: **[PID-защита](./prevention.md#pid-защита-и-предотвращение-fork-бомб)**, **[Resource Pressure](../NodeUnavailability/resource_pressure.md)**.

---

### Кейс 5: MemoryPressure из-за swap death spiral

**Симптом:** Узел периодически входил в MemoryPressure и выходил из него (flip-flopping). Поды постоянно пересоздавались. Мониторинг показывал потребление RAM на уровне 85%, но swap был заполнен на 100%.

**Время инцидента:** 2 часа прерывистой деградации.

**Затронутые компоненты:** 2 Worker-нода, все поды с Burst负载 (API, Worker).

**Хронология:**
```
09:00 — Нагрузка выросла, RAM потребление достигло 80%
09:05 — Ядро начало выгружать неактивные страницы в swap
09:10 — Swap заполнен на 100%, ядро не может выгружать страницы
09:15 — kubelet обнаружил MemoryPressure, начал выселение BestEffort подов
09:20 — Выселены BestEffort поды, RAM освободилась до 70%
09:25 — MemoryPressure снят, поды начали пересоздаваться
09:30 — Новые поды потребили RAM, swap снова заполнен
09:35 — Цикл повторяется (flip-flopping)
10:00 — Оператор увеличил evictionHard.memory.available с 100Mi до 500Mi
10:05 — Flip-flopping прекратился, но часть подов всё ещё выселялась
10:15 — Оператор добавил RAM на узлы (виртуально)
11:00 — Ситуация стабилизировалась
```

**Первопричина:** Недостаточный `evictionHard.memory.available` (100Mi) + включённый swap + Burst负载 без правильных requests/limits.

**Корректирующие меры:**
1. `evictionHard.memory.available` увеличен до `500Mi`.
2. `evictionSoft.memory.available` установлен в `1Gi`.
3. `evictionSoftGracePeriod` увеличен до `2m`.
4. Добавлен `evictionMinimumReclaim: "200Mi"`.

**Превентивные меры:**
1. На больших узлах (64+ ГБ RAM) использовать абсолютные значения вместо процентов.
2. Для production подов использовать Guaranteed QoS (requests == limits).
3. Настроить PSI мониторинг для раннего обнаружения давления на память.
4. Рассмотреть отключение swap или использование `LimitedSwap` (K8s 1.31+).

**Метрики для мониторинга:**
```promql
# MemoryPressure flip-flopping (частые изменения состояния)
changes(kube_node_status_condition{condition="MemoryPressure"}[1h]) > 5

# PSI: процессы теряют время из-за нехватки памяти
node_memory_pressure_stall_info{resource="memory", state="some"} > 0.05

# Swap использование
node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes > 0
```

> Связанные темы: **[Выселение по памяти](./memory_eviction.md)**, **[PSI (Pressure Stall Information)](../../../../Linux/Core/kernel/psi.md)**, **[Управление Swap](../../../../Linux/Core/memory/swap_management.md)**.

---

## Дополнительная информация

### Чеклист постмортема

Перед撰写 постмортема убедитесь, что у вас есть:

1. **Метрики:** Графики из Prometheus/Grafana за период инцидента.
2. **Логи:** kubelet, dmesg, audit log, логи приложений.
3. **События:** `kubectl get events --sort-by='.lastTimestamp'`.
4. **Состояние узлов:** Conditions, Taints, Allocatable resources.
5. **Конфигурация:** KubeletConfiguration, PDB, ResourceQuota, LimitRange.
6. **Связи:** Какие сервисы依赖ились от затронутых подов.

### Типичные антипаттерны

| Антипаттерн | Последствие | Решение |
|:---|:---|:---|
| "Исправим симптом" (увеличим RAM/диск) | Проблема повторится при росте нагрузки | Ищи root cause |
| "Это был единичный случай" | Без метрик невозможно подтвердить | Настрой мониторинг и алерты |
| "Приложение виновато" | Часто проблема в конфигурации кластера | Проверь kubelet, PDB, quotas |
| "Мы не можем менять приложение" | Ограничение через Admission Controller | Используй Kyverno/Gatekeeper |

### Матрица эскалации

| Масштаб инцидента | Кто реагирует | Время реакции |
|:---|:---|:---|
| 1 под, 1 узел | Автоматическое (ReplicaSet пересоздаёт) | 0 минут |
| Несколько подов, 1 узел | SRE on-call | 15 минут |
| Всё приложение, 1 узел | SRE team | 5 минут |
| Каскадное выселение, несколько узлов | Incident Commander | Немедленно |

## Смотрите также

- **[Диагностика выселения подов](./diagnostics.md)** — общий алгоритм поиска первопричин.
- **[Выселение по памяти](./memory_eviction.md)** — расчет Working Set и метрики.
- **[Выселение по диску](./disk_eviction.md)** — nodefs vs imagefs, GC, пороги.
- **[QoS и выселение](./qos_and_eviction.md)** — классы ресурсов и очередность удаления.
- **[PDB и Taint Eviction](./pdb_and_taint_eviction.md)** — блокировка drain и Taint-based eviction.
- **[Профилактика выселения](./prevention.md)** — как настроить кластер, чтобы избежать выселений.
- **[Обслуживание узлов](../../../Operations/node_maintenance.md)** — kubectl cordon/drain.
- **[Разбор ошибки OOMKilled](../oomkilled_pods.md)** — когда контейнер убит OOM Killer.
