# Pod в состоянии `Pending`: Реальные кейсы (Postmortem)

---

## Определения

**Postmortem Pending-кейсы** — реалистичные сценарии из продакшена, иллюстрирующие типичные причины зависания Pod в состоянии Pending и методы их устранения. Кейсы основаны на типичных инцидентах в Kubernetes-кластерах и могут использоваться для подготовки к собеседованиям и настройки мониторинга.

---

## Кейс 1: Фрагментация ресурсов в multi-AZ кластере

### Ситуация
Кластер из 15 узлов (5 узлов в каждой из 3 зон: `zone-a`, `zone-b`, `zone-c`). Приложение требует `requests: cpu=2, memory=4Gi`. Все узлы заняты на 70-80%, Pod в Pending с сообщением `0/15 nodes are available: 15 Insufficient cpu`.

### Корневая причина
Ресурсная фрагментация: на каждом узле оставалось ~1.5Gi RAM, но Pod требовал 4Gi. Суммарно ресурсов было достаточно (15 × 1.5Gi = 22.5Gi), но ни один узел не подходил.

### Диагностика
```bash
# Проверка распределения ресурсов
kubectl describe nodes | grep -A 5 "Allocated resources"
# → CPU (cores)   120m / 8000m    (на каждом узле ~100m свободно)
# → Memory (Gi)   14Gi / 32Gi     (на каждом узле ~2Gi свободно)

# Проверка requests Pod
kubectl describe pod <pod> | grep -A 3 "Requests:"
# → Requests: cpu=2, memory=4Gi
```

### Решение
1. **Right-sizing:** Снизить `requests` до `cpu=1, memory=2Gi` (реальное потребление)
2. **Bin-packing:** Настроить `MostRequestedPriority` в планировщике для уплотнения Pod
3. **VPA:** Рекомендовать оптимальные `requests` на основе历史 потребления

### Предотвращение
- Мониторинг `kube_pod_status_phase{phase="Pending"}` с алертами
- Регулярный аудит `requests` через VPA в mode `Off` (только рекомендации)
- Настройка Descheduler для перемещения Pod с низким utilization

---

## Кейс 2: ResourceQuota исчерпана в Namespace

### Ситуация
После массового деплоя (CI/CD pipeline запустил 30 job одновременно) 20 Pod остались в Pending. `kubectl describe pod` не показывает событий `FailedScheduling`.

### Корневая причина
ResourceQuota в Namespace установлена `hard.pods=25`. После создания 25 Pod (включая.running и Pending) новые Pod не доходят до планировщика — они блокируются на уровне API-сервера.

### Диагностика
```bash
# Проверка квот
kubectl describe quota -n <namespace>
# → Name: my-quota
# → Resource    Used  Hard
# → pods        25    25    ← лимит исчерпан

# Проверка Pending Pod
kubectl get pods -n <namespace> --field-selector status.phase=Pending
# → 20 Pod в Pending
```

### Решение
1. **Увеличить лимит:** `kubectl patch resourcequota my-quota -n <ns> -p '{"spec":{"hard":{"pods":"50"}}}'`
2. **Очистить завершённые Pod:** `kubectl delete pods --field-selector status.phase=Succeeded -n <ns>`
3. **Очередь деплоя:** Ограничить параллелизм в CI/CD pipeline

### Предотвращение
- ResourceQuota с `scope: NotBestEffort` для критических Pod
- Лимиты на job (Kubernetes batch/v1) отдельно от deployment
- Мониторинг `kube_resourcequota{type="used"}` → `kube_resourcequota{type="hard"}` ratio > 80%

---

## Кейс 3: PVC не привязывается из-за WaitForFirstConsumer

### Ситуация
StatefulSet с 3 репликами. 2 Pod запущены, 3-й Pending. `kubectl describe pvc` показывает `Status: Pending` и `Events: Waiting for a volume to be created`.

### Корневая причина
StorageClass имеет `volumeBindingMode: WaitForFirstConsumer`. Pod 3 требует `nodeSelector: topology.kubernetes.io/zone=zone-c`, но в `zone-c` нет узлов с достаточными ресурсами. PVC не привязывается, пока Pod не будет запланирован.

### Диагностика
```bash
# Проверка StorageClass
kubectl get sc standard -o jsonpath='{.volumeBindingMode}'
# → WaitForFirstConsumer

# Проверка PVC
kubectl describe pvc data-pvc-2 -n <ns>
# → Status: Pending
# → Events: WaitForFirstConsumer

# Проверка zone-c узлов
kubectl get nodes -l topology.kubernetes.io/zone=zone-c
# → NAME     STATUS     AGE
# → node-5   NotReady   10d   ← узел в zone-c не готов!
```

### Решение
1. **Исправить узел:** Восстановить `node-5` в Ready
2. **Изменить zone:** Убрать или изменить `nodeSelector` в StatefulSet
3. **Временно:** Использовать `volumeBindingMode: Immediate` (риск zonal mismatch)

### Предотвращение
- Мониторинг Conditions узлов: `kube_node_status_condition{condition="Ready",status="true"}`
- Проверка доступности зон перед созданием StatefulSet
- Использование `topologySpreadConstraints` вместо жесткого `nodeSelector`

---

## Кейс 4: Admission Webhook блокирует Pod

### Ситуация
После установки Kyverno все Pod в Namespace `production` остаются в Pending. `kubectl describe pod` не показывает событий `FailedScheduling`. Kyverno работает в режиме `enforce`.

### Корневая причина
Kyverno ClusterPolicy требует `securityContext.runAsNonRoot=true` для всех Pod. Приложение не настроено с `runAsNonRoot`, и Kyverno отклоняет его на уровне admission.

### Диагностика
```bash
# Проверка ошибок Kyverno
kubectl get events -n production --field-selector reason=PolicyViolation
# → Warning  PolicyViolation  ... validation error: runAsNonRoot must be true

# Проверка policies
kubectl get clusterpolicies
# → NAME              VALIDATION-ACTION   ACTION
# → require-runasroot enforce             enforce

# Проверка admission webhook
kubectl get validatingwebhookconfigurations
# → kyverno-resource-validating-webhook
```

### Решение
1. **Исправить Pod:** Добавить `securityContext.runAsNonRoot: true`
2. **Временно:** Перевести Kyverno в режим `warn` для namespace
3. **Исключение:** Добавить exclude для конкретных Pod через `spec.exclude`

### Предотвращение
- Тестирование политик в режиме `warn` перед `enforce`
- CI/CD проверка манифестов через `kyverno apply --policy-report`
- Документирование требований PSA/Kyverno для разработчиков

---

## Кейс 5: Spot-инстансы и каскадная эвикция

### Ситуация
Кластер на spot-инстансах (80% spot, 20% on-demand). Провайдер отозвал 5 spot-узлов одновременно. CA добавил 3 on-demand узла, но 15 Pod остались в Pending из-за PDB.

### Корневая причина
PDB для Deployment `api-gateway` установлен `minAvailable: 3`. После эвикции 5 spot-узлов доступных реплик осталось 2 (меньше PDB). CA не может удалить Pod для перераспределения, PDB блокирует.

### Диагностика
```bash
# Проверка PDB
kubectl get pdb -A
# → NAME           MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
# → api-gateway    3               <none>            0

# Проверка Pending Pod
kubectl get pods -l app=api-gateway --field-selector status.phase=Pending
# → 15 Pod в Pending

# Проверка ready реплик
kubectl get deployment api-gateway
# → READY   2/3   ← меньше minAvailable
```

### Решение
1. **Временно:** Снизить `minAvailable` до 1 для восстановления
2. **Добавить on-demand узлы:** Увеличить минимальный размер on-demand группы
3. **Разделить PDB:** Отдельный PDB для on-demand и spot узлов

### Предотвращение
- `topologySpreadConstraints` с `whenUnsatisfiable: ScheduleAnyway`
- Разделение workload по priority: критические сервисы на on-demand
- Мониторинг `kube_pod_status_ready` и PDB `allowedDisruptions`

---

## Кейс 6: Scheduling Gate завис навсегда

### Ситуация
Custom-контроллер создавал Pod с `schedulingGates` для ожидания подготовки данных. Контроллер упал, gate не был удалён. Pod висит в Pending уже 3 дня.

### Корневая причина
Внешний контроллер установил `schedulingGates: [{"gateName":"data-pipeline/prepared"}]`, но при падении контроллера gate не был удалён. Планировщик полностью игнорирует Pod.

### Диагностика
```bash
# Проверка gates
kubectl get pod <pod> -o jsonpath='{.spec.schedulingGates}'
# → [{"gateName":"data-pipeline/prepared"}]

# Проверка ownerReferences
kubectl get pod <pod> -o jsonpath='{.metadata.ownerReferences[*].name}'
# → (пусто — Pod без owner, gate установлен вручную или кастомным контроллером)

# Проверка состояния контроллера
kubectl get pods -n data-pipeline | grep controller
# → controller-xxx   0/1     CrashLoopBackOff
```

### Решение
1. **Удалить gate вручную:**
```bash
kubectl patch pod <pod> --type='json' -p='[{"op": "remove", "path": "/spec/schedulingGates"}]'
```
2. **Восстановить контроллер:** Исправить CrashLoopBackOff
3. **Пересоздать Pod:** Если gate критичен для логики

### Предотвращение
- Timeout на gates (>10 минут → алерт)
- Контроллер с leader election для отказоустойчивости
- Deadlock detection в кастомном контроллере

---

## Кейс 7: etcd перегружен, планировщик медленный

### Ситуация
После роста кластера до 500 узлов и 10000 Pod планирование занимает 30-60 секунд (норма: 1-2 сек). Pod "висят" в Pending по 1-2 минуты перед запуском.

### Корневая причина
etcd перегружен: 10000+ объектов, высокий write load. kube-apiserver не может обработать запросы планировщика вовремя. `scheduler_pending_pods{queue="active"}` растёт.

### Диагностика
```bash
# Проверка etcd latency
kubectl get --raw /metrics | grep etcd_disk_wal_fsync_duration_seconds
# → p99 > 200ms (норма: <10ms)

# Проверка очереди планировщика
kubectl get --raw /metrics | grep scheduler_pending_pods
# → scheduler_pending_pods{queue="active"} 50  ← много Pod в очереди

# Проверка durations
kubectl get --raw /metrics | grep scheduler_scheduling_algorithm_duration_seconds
# → p99 > 5s (норма: <0.1s)
```

### Решение
1. **Разделить etcd:** Выделить etcd на отдельный кластер
2. **Оптимизировать:** Compaction + defrag etcd
3. **Масштабировать:** Добавить CPU/RAM для etcd
4. **Очистить:** Удалить неиспользуемые объекты (ConfigMap, Secret)

### Предотвращение
- Мониторинг `etcd_disk_wal_fsync_duration_seconds` → алерт при p99 > 100ms
- Мониторинг `apiserver_current_inflight_requests` → алерт при > 100
- Регулярный compaction etcd (auto-compaction-retention)

---

## Кейс 8: Pod Security Admission блокирует Pod

### Ситуация
Namespace `production` имеет PSA `enforce: restricted`. Приложение требует `hostPath` для монтирования конфигурационного файла. Pod в Pending без событий ошибок.

### Корневая причина
PSA `restricted` профиль запрещает `hostPath`. Pod отклоняется на уровне admission controller. Ошибка не попадает в events Pod,因为她 Pod не создаётся.

### Диагностика
```bash
# Проверка PSA меток
kubectl get ns production -o jsonpath='{.metadata.labels}'
# → pod-security.kubernetes.io/enforce: restricted

# Проверка events на admission errors
kubectl get events --field-selector reason=FailedCreate --sort-by='.lastTimestamp'
# → Warning  FailedCreate  ... pods "app-xxx" is forbidden: violates PodSecurity "restricted:latest"
#   (hostPath is not allowed)

# Проверка манифеста
kubectl apply -f pod.yaml --dry-run=server 2>&1
# → Error from server (Forbidden): ... violates PodSecurity
```

### Решение
1. **Убрать hostPath:** Использовать ConfigMap/Secret для конфигурации
2. **Использовать Volume:** emptyDir + projected volume
3. **Временно:** Ослабить PSA на namespace (warn вместо enforce)

### Предотвращение
- Валидация манифестов в CI/CD: `kubectl apply --dry-run=server`
- Обучение разработчиков требованиям PSA
- Документирование allowed/запрещенных полей в `securityContext`

---

## Сводная таблица: Частота и Severity

| Кейс | Частота | Severity | Время восстановления |
|------|---------|----------|---------------------|
| Фрагментация ресурсов | Очень высокая | Средняя | 5-15 мин |
| ResourceQuota исчерпана | Высокая | Низкая | 1-5 мин |
| PVC WaitForFirstConsumer | Средняя | Высокая | 10-30 мин |
| Admission Webhook блокирует | Средняя | Высокая | 5-15 мин |
| Spot + PDB cascade | Средняя | Критическая | 15-60 мин |
| Scheduling Gate завис | Низкая | Средняя | 1-5 мин |
| etcd перегружен | Низкая | Критическая | 30-120 мин |
| PSA блокирует | Средняя | Средняя | 5-15 мин |

---

## Полезные команды для мониторинга

| Задача | Команда |
|--------|---------|
| **Pending поды** | `kubectl get pods -A --field-selector status.phase=Pending \| wc -l` |
| **Очередь планировщика** | `kubectl get --raw /metrics \| grep scheduler_pending_pods` |
| **Длительность планирования** | `kubectl get --raw /metrics \| grep scheduler_scheduling_algorithm_duration_seconds` |
| **etcd latency** | `kubectl get --raw /metrics \| grep etcd_disk_wal_fsync_duration_seconds` |
| **ResourceQuota** | `kubectl get resourcequota -A -o json \| jq '.items[] \| {ns:.metadata.namespace, used:.status.used, hard:.spec.hard}'` |
| **PDB disruptions** | `kubectl get pdb -A -o json \| jq '.items[] \| {name:.metadata.name, allowed:.status.disruptionsAllowed}'` |

---

## Связанные ресурсы

- **[Распространенные случаи](./common_cases_and_solutions.md)** — типовые решения.
- **[Диагностика](./diagnostics.md)** — алгоритмы поиска.
- **[PodEvicted Postmortem](../PodEvicted/postmortem_cases.md)** — кейсы эвикции.
- **[Resource Pressure](../../NodeUnavailability/resource_pressure.md)** — давление на узел.
- **[etcd Troubleshooting](../../../../etcd/troubleshooting.md)** — проблемы etcd.
- **[Admission Controllers](../../../Concepts/admission_controllers.md)** — вебхуки.
