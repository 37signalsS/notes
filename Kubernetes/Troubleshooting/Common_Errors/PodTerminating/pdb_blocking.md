# Pod Terminating — блокировка через PDB

## Определения

**Блокировка удаления через PDB** — состояние, возникающее при использовании Eviction API (например, при выполнении `kubectl drain`), когда API-сервер отклоняет запрос на удаление пода, так как это приведет к падению количества доступных реплик ниже порога, установленного в Pod Disruption Budget.

**Eviction API** — программный интерфейс, предназначенный для «мягкого» удаления подов. В отличие от стандартного `DELETE`, запрос к Eviction API (подзапрос `/eviction`) возвращает ошибку `429 Too Many Requests`, если бюджет PDB нарушен. Это позволяет инструментам автоматизации (drain, autoscaler) уважать SLA приложения.

**`disruptionTarget` (K8s 1.29+)** — поле в `status` PDB, содержащее список имен подов, выселение которых уже было одобрено API-сервером, но которые еще фактически не удалены. Помогает диагностировать «зависшие» выселения, которые продолжают расходовать бюджет.

**`disruptionsAllowed`** — ключевое поле в `status` PDB, показывающее количество подов, которые могут быть выселены прямо сейчас. Если `0` — любая попытка eviction через Eviction API будет отклонена с ошибкой `429`.

**Добровольные прерывания (Voluntary Disruptions)** — плановые действия по удалению подов:
- Выполнение `kubectl drain` для обслуживания узла.
- Масштабирование Deployment/StatefulSet вниз.
- Обновление конфигурации (Rolling Update).
- Вытеснение подов (Eviction) автоскейлером или дескейлером.

**Недобровольные прерывания (Involuntary Disruptions)** — непредвиденные события, которые PDB **не может** предотвратить (так как они не используют Eviction API):
- Отказ оборудования (Hardware failure).
- Kernel Panic или зависание ОС узла.
- Ошибка OOM Killer на уровне узла.
- Удаление виртуальной машины облачным провайдером.

---

## Базовые концепции

### Дерево решений для быстрой диагностики

```
kubectl drain зависает / Cannot evict pod
│
├─ kubectl get pdb -A → ALLOWED DISRUPTIONS: 0
│  │
│  ├─ currentHealthy < desiredHealthy
│  │  └─ Поды в CrashLoopBackOff / NotReady
│  │     └─ Установите unhealthyPodEvictionPolicy: AlwaysAllow
│  │
│  ├─ currentHealthy == desiredHealthy (все здоровы)
│  │  ├─ replicas <= minAvailable → PDB слишком жёсткий
│  │  │  └─ Увеличьте replicas или уменьшите minAvailable
│  │  └─ replicas > minAvailable → Кто-то уже забрал бюджет
│  │     └─ Проверьте disruptionTarget и другие eviction-операции
│  │
│  └─ currentHealthy > desiredHealthy ( лишние реплики)
│     └─ PDB с minAvailable выше текущего count → Синтаксическая ошибка
│
├─ kubectl get pdb -A → ALLOWED DISRUPTIONS > 0, но drain блокируется
│  └─ Drain ожидает завершения предыдущих eviction
│     └─ Проверьте events и disruptionTarget
│
└─ drain работает, но под зависает в Terminating после drain
   └─ Это не PDB-проблема → См. diagnostics.md
```

### Механизм блокировки и взаимодействие с инструментами

PDB защищает приложение только от действий через Eviction API. Прямая команда `kubectl delete pod` игнорирует PDB.

1. **kubectl drain**: Работает итеративно. Получив `429`, он делает паузу и повторяет запрос. Без указания `--timeout` drain может висеть бесконечно, если бюджет не освобождается.
2. **Cluster Autoscaler (CA)**: Если PDB заблокирован, CA помечает узел как `unremovable`. Слишком жесткий PDB (`minAvailable: 100%`) делает узел «бессмертным» для автоскейлера.
3. **Descheduler**: Использует Eviction API для балансировки. Если PDB не позволяет выселить под, дескейлер просто пропускает его.
4. **HPA (scale-down)**: HPA не использует Eviction API — он напрямую уменьшает replicas. PDB **не блокирует** scale-down HPA, но может привести к ситуации, когда PDB нарушается после масштабирования.

### Формула расчёта PDB

Расчёт `disruptionsAllowed` производится контроллером PDB каждые ~15 секунд:

```
disruptionsAllowed = currentHealthy - desiredHealthy
```

Где:
- `currentHealthy` — количество подов в статусе `Ready`
- `desiredHealthy` — `min(maxUnavailable, replicas - minAvailable)` или аналогичный расчёт

**Примеры:**

| replicas | minAvailable | maxUnavailable | currentHealthy | disruptionsAllowed |
|----------|-------------|----------------|----------------|-------------------|
| 5 | 3 | — | 5 | 2 |
| 5 | 3 | — | 3 | 0 |
| 5 | — | 1 | 5 | 1 |
| 5 | — | 1 | 4 | 0 |
| 5 | 6 | — | 5 | 0 (всегда 0, т.к. minAvailable > replicas) |

### Статус и условия (PDB Conditions, K8s 1.30+)

В современных версиях K8s статус PDB стал гораздо информативнее благодаря массиву `conditions`:

| Condition | Status | Reason | Описание |
|-----------|--------|--------|----------|
| `DisruptionAllowed` | `True` | — | Выселение разрешено |
| `DisruptionAllowed` | `False` | `InsufficientPods` | Мало здоровых реплик |
| `DisruptionAllowed` | `False` | `CalculateExpectedHealthyFailed` | Ошибка расчёта кворума |

**Просмотр conditions:**
```bash
kubectl get pdb <pdb-name> -o jsonpath='{.status.conditions[*]}' | jq .
# → [{"type":"DisruptionAllowed","status":"True","lastTransitionTime":"..."}]
```

### Политика выселения нездоровых подов (spec.unhealthyPodEvictionPolicy)

Начиная с K8s 1.27 (GA в 1.30), это поле решает проблему «зависания» кластера из-за «сломанных» приложений:
- **`IfHealthyBudget` (по умолчанию)**: Нездоровые поды могут быть выселены, только если бюджет позволяет (есть запас здоровых реплик). Если приложение уже упало (например, 0/3 Ready), drain узла с таким подом заблокируется.
- **`AlwaysAllow`**: Разрешает выселение подов в состоянии `NotReady` всегда, даже если бюджет нарушен. **Рекомендуемый паттерн** для системных сервисов и критических нагрузок, чтобы они не блокировали обслуживание инфраструктуры.

### Ключевые типы PDB-блокировок

| Тип блокировки | Симптом | Команда для выявления | Решение |
|----------------|---------|----------------------|---------|
| **Полная блокировка** | `ALLOWED DISRUPTIONS: 0`, все поды Healthy | `kubectl get pdb -A` | Scale-up или корректировка PDB |
| **Частичная блокировка** | `ALLOWED DISRUPTIONS: 0`, но есть unhealthy | `kubectl get pdb -A` + `kubectl get pods` | `unhealthyPodEvictionPolicy: AlwaysAllow` |
| **Race condition** | Drain блокируется на короткое время | `kubectl get events --field-selector reason=Eviction` | Подождите или увеличьте `--timeout` |
| **PDB mismatch** | PDB селектор не соответствует ни одному поду | `kubectl get pdb -o wide` + `kubectl get pods -l <selector>` | Исправьте селектор |
| **Дублирование PDB** | Два PDB защищают одни поды | `kubectl get pdb -A -o yaml` | Удалите дублирующий PDB |

---

## Практические сценарии

### Быстрый чек-лист диагностики (start here)

```bash
# 1. Все PDB и их статус
kubectl get pdb -A

# 2. Детальный аудит конкретного PDB
kubectl describe pdb <pdb-name>

# 3. Какие поды защищены этим PDB
kubectl get pods -l <selector-of-pdb> -o wide

# 4. Events (быстрый поиск причин блокировки)
kubectl get events --field-selector reason=EvictionFailed --sort-by='.lastTimestamp'

# 5. Проверка disruptionTarget (K8s 1.29+)
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionTarget}' | jq .
```

### Этап 1: Диагностика блокировки выселения

#### 1.1 Проверка состояния бюджета

Если `kubectl drain` выдаёт ошибку `Cannot evict pod`, изучите состояние PDB:

```bash
# Краткий обзор всех PDB
kubectl get pdb -A
# →
# NAMESPACE   NAME      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# default     web-pdb   3               N/A               0                     10d
# default     api-pdb   N/A             1                 0                     5d

# Детальный аудит конкретного PDB
kubectl describe pdb <pdb-name>
# →
# Name:             web-pdb
# Namespace:        default
# Max unknown:      unbounded.
# Min available:    3
# Pod health:       3 Pods healthy out of 5
# Allowed disruption:  0 Pods
# Conditions:
#   Type           Status  Reason
#   ----           ------  ------
#   DisruptionAllowed  False   InsufficientPods
```

**Ключевые поля в выводе:**
- `ALLOWED DISRUPTIONS`: Если 0 — выселение заблокировано.
- `CURRENT HEALTHY`: Количество подов, которые Kubernetes считает «здоровыми» (Ready).
- `EXPECTED HEALTHY`: Количество подов, которое должно быть в идеале (согласно контроллеру).
- `Conditions → DisruptionAllowed: False` — прямое указание на блокировку.

#### 1.2 Поиск причины блокировки

```bash
# Определяем, какие поды защищены PDB
kubectl get pods -l app=web -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'
# →
# web-0    True
# web-1    True
# web-2    True
# web-3    False
# web-4    True

# 4 из 5 подов Ready. PDB требует minAvailable: 3 → disruptionsAllowed = 4-3 = 1
# Но если PDB требует minAvailable: 5 → disruptionsAllowed = 0
```

#### 1.3 Поиск «зависших» выселений (K8s 1.29+)

Если `ALLOWED DISRUPTIONS > 0`, но `drain` все равно не проходит, проверьте, не занят ли бюджет уже одобренными запросами:

```bash
# Проверка disruptionTarget
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionTarget}' | jq .
# → ["pod/web-abc123"]
# Эти поды уже "забронированы" для выселения, но ещё не удалены

# Проверка Events по всем namespace
kubectl get events -A --field-selector reason=EvictionFailed --sort-by='.lastTimestamp'
# →
# default   30s     Warning   EvictionFailed   pod/web-xyz   Cannot evict pod as it would violate the pod's disruption budget.
```

### Этап 2: Методы разрешения ситуации

#### Вариант 1: Увеличение количества реплик (Scale-up)

Самый безопасный путь. Добавьте временную реплику, чтобы `currentHealthy` превысил `minAvailable`:

```bash
# Определяем текущее число реплик
kubectl get deployment <name> -o jsonpath='{.spec.replicas}'
# → 3

# Увеличиваем до N+1 (или больше, если нужно)
kubectl scale deployment <name> --replicas=4

# Проверяем, что disruptionsAllowed > 0
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionsAllowed}'
# → 1

# Выполняем drain
kubectl drain <node> --ignore-daemonsets --timeout=300s

# После drain возвращаем исходное число реплик
kubectl scale deployment <name> --replicas=3
```

**Формула:** `replicas_needed = minAvailable + 1` (минимум для disruptionsAllowed >= 1).

#### Вариант 2: Динамическая корректировка бюджета

Если реплик достаточно, но PDB настроен слишком консервативно:

```bash
# Изменение на maxUnavailable: 1 (разрешить одно прерывание за раз)
kubectl patch pdb <pdb-name> -p '{"spec":{"maxUnavailable":1}}' --type=merge

# Или уменьшение minAvailable
kubectl patch pdb <pdb-name> -p '{"spec":{"minAvailable":2}}' --type=merge
```

**Важно:** Нельзя задать `minAvailable` и `maxUnavailable` одновременно — это ошибка валидации.

#### Вариант 3: Обход через прямое удаление

Команда `delete` не проверяет PDB. Если обслуживание узла критично, удалите под вручную:

```bash
# Стандартное удаление (учитывает terminationGracePeriodSeconds)
kubectl delete pod <pod-name> --grace-period=30

# Принудительное удаление (SIGKILL без ожидания)
kubectl delete pod <pod-name> --force --grace-period=0
```

*Внимание:* Это нарушает гарантии доступности, установленные владельцем приложения. Используйте только в экстренных случаях.

#### Вариант 4: Очистка зависших нездоровых подов

Если поды застряли в `CrashLoopBackOff`, переведите PDB в режим `AlwaysAllow`:

```bash
kubectl patch pdb <pdb-name> -p '{"spec":{"unhealthyPodEvictionPolicy":"AlwaysAllow"}}' --type=merge

# Теперь drain может выселить нездоровые поды даже при нарушении бюджета
kubectl drain <node> --ignore-daemonsets --timeout=300s
```

#### Вариант 5: Удаление PDB (крайний случай)

Если PDB настроен некорректно и обслуживание критично:

```bash
# Удаление PDB (разрешит все выселения)
kubectl delete pdb <pdb-name>

# Выполнение drain
kubectl drain <node> --ignore-daemonsets

# Восстановление PDB (после обслуживания)
kubectl apply -f pdb.yaml
```

#### Вариант 6: Использование --disable-eviction (K8s 1.27+)

Флаг `--disable-eviction` заставляет drain использовать `delete` вместо `evict`:

```bash
kubectl drain <node> --ignore-daemonsets --disable-eviction --timeout=300s
```

*Внимание:* Это полный обход PDB. Используйте только при «зависшем» узле, где drain не может завершиться.

---

## Типовые ошибки и «антипаттерны»

- **Пересекающиеся селекторы**: Если один Pod попадает под действие двух PDB, Eviction API потребует разрешения от **обоих**. Если один разрешает, а второй нет — выселение будет отклонено.
- **PDB для DaemonSet**: Не имеет смысла. DaemonSet по определению привязан к узлу. Если узел уходит в drain, под DaemonSet просто удаляется (если не используется `--ignore-daemonsets`).
- **Блокировка пустых узлов**: Если на почти пустом узле остался один под с `minAvailable: 100%`, Cluster Autoscaler не сможет его удалить, и вы будете платить за лишний узел.
- **PDB и Rolling Update**: PDB **не блокирует** процесс обновления Deployment. Однако, если Rolling Update уже уменьшил количество реплик до минимума, другие операции (например, drain другого узла) будут заблокированы до завершения обновления.
- **PDB с `minAvailable` больше текущего count реплик**: Если Deployment имеет 3 реплики, а PDB требует `minAvailable: 5`, `disruptionsAllowed` всегда будет 0. Drain застрянет навсегда.
- **PDB без селектора**: PDB без `selector` защищает **все** поды в namespace. Это может заблокировать drain всех подов в namespace одновременно.

---

## Связанные сценарии

### PDB + HPA: конфликт при масштабировании

HPA уменьшает replicas напрямую (не через Eviction API), поэтому PDB **не блокирует** scale-down. Но после масштабирования PDB может оказаться нарушенным:

```bash
# Сценарий: HPA уменьшил replicas с 5 до 3, PDB minAvailable: 4
# disruptionsAllowed = 0, drain заблокирован

# Решение: временно остановить HPA перед drain
kubectl delete hpa <name>
kubectl drain <node> --ignore-daemonsets
kubectl apply -f hpa.yaml  # восстановить HPA
```

### PDB + StatefulSet: кворумные системы

Для StatefulSet с кворумом (etcd, Kafka, ZooKeeper) PDB должен быть настроен так, чтобы не допустить потери кворума:

```bash
# Формула для кворума: minAvailable = ⌈N/2⌉
# Для 3 реплик: minAvailable = 2
# Для 5 реплик: minAvailable = 3

# Проверка кворума перед drain
kubectl get pdb <pdb-name> -o jsonpath='{.status.currentHealthy} / {.status.desiredHealthy}'
# → 3 / 3 → кворум сохраняется
```

### PDB + batch drain (массовое обслуживание узлов)

При массовом обновлении пула worker-узлов:

```bash
# Формула: Batch Size = min(узлов_в_пуле, floor((реплик_сервиса - PDB.minAvailable) / реплик_на_узел))
# Пример: 10 узлов, 5 реплик на сервис, PDB minAvailable: 3, по 1 реплике на узел
# Batch Size = min(10, floor((5-3)/1)) = min(10, 2) = 2

# Безопасный batch drain
BATCH_SIZE=2
for node in $(kubectl get nodes -l role=worker -o name | head -$BATCH_SIZE); do
  kubectl drain $node --ignore-daemonsets --timeout=600s &
done
wait
```

### PDB + PriorityClass: вытеснение подов

При вытеснении (preemption) планировщик может нарушить PDB, если других вариантов нет:

```bash
# Проверка pending preemptions
kubectl get events --field-selector reason=PreemptionVictims

# Если preemption блокируется PDB, под останется в Pending
# Решение: создайте PDB с допустимым maxUnavailable или увеличьте replicas
```

### PDB deadlock при одновременных операциях

**Симптом:** PDB блокирует drain, одновременно HPA масштабирует вниз, и ни одна операция не может завершиться.

```bash
# Диагностика
kubectl get pdb -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed,DESIRED:.status.desiredHealthy,CURRENT:.status.currentHealthy"
kubectl get hpa -A
kubectl get events --field-selector reason=EvictionFailed

# Решение
kubectl delete hpa <name>                    # 1. Остановить HPA
kubectl scale deployment <name> --replicas=N+2  # 2. Увеличить replicas
kubectl drain <node> --ignore-daemonsets     # 3. Выполнить drain
kubectl apply -f hpa.yaml                   # 4. Восстановить HPA
```

---

## Мониторинг и алерты

### Проверка PDB через kubectl

```bash
# Все PDB с disruptionsAllowed = 0
kubectl get pdb -A -o json | jq '.items[] | select(.status.disruptionsAllowed == 0) | {name: .metadata.name, namespace: .metadata.namespace, desired: .status.desiredHealthy, current: .status.currentHealthy}'

# PDB и их disruptionsAllowed в табличном виде
kubectl get pdb -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,MIN_AVAIL:.spec.minAvailable,MAX_UNAVAIL:.spec.maxUnavailable,ALLOWED:.status.disruptionsAllowed,DESIRED:.status.desiredHealthy,CURRENT:.status.currentHealthy"

# Поды, защищённые PDB
kubectl get pods -A -o json | jq '[.items[] | select(.metadata.ownerReferences[]? | select(.kind=="ReplicaSet" or .kind=="StatefulSet")) | {name: .metadata.name, namespace: .metadata.namespace, ready: (.status.conditions[] | select(.type=="Ready") | .status)}]'
```

### PromQL для мониторинга

```promql
# PDB заблокирован (disruptionsAllowed = 0)
kube_poddisruptionbudget_status_disruptions_allowed == 0

# PDB близок к лимиту
kube_poddisruptionbudget_status_current_healthy / kube_poddisruptionbudget_status_desired_healthy < 1.2

# Количество PDB в каждом namespace
count by (namespace) (kube_poddisruptionbudget_info)

# PDB, которые могут быть выселены
kube_poddisruptionbudget_status_disruptions_allowed > 0
```

### Алерты Prometheus

```yaml
- alert: PDBBlocked
  expr: kube_poddisruptionbudget_status_disruptions_allowed == 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "PDB {{ $labels.poddisruptionbudget }} заблокирован"

- alert: PDBNearLimit
  expr: kube_poddisruptionbudget_status_current_healthy / kube_poddisruptionbudget_status_desired_healthy < 1.2
  for: 5m
  labels:
    severity: info
  annotations:
    summary: "PDB {{ $labels.poddisruptionbudget }} близок к лимиту"
```

---

## Связанные команды kubectl

| Команда | Описание | Когда использовать |
|---------|----------|--------------------|
| `kubectl get pdb -A` | Список всех PDB | Первый шаг диагностики |
| `kubectl describe pdb <name>` | Детали конкретного PDB | Анализ conditions и disruptionTarget |
| `kubectl get pdb <name> -o jsonpath='{.status.disruptionsAllowed}'` | Текущее значение disruptionsAllowed | Проверка, можно ли выселить под |
| `kubectl patch pdb <name> -p '{"spec":{"maxUnavailable":1}}'` | Динамическое изменение PDB | Временное ослабление перед drain |
| `kubectl delete pdb <name>` | Удаление PDB | Крайний случай, аварийное обслуживание |
| `kubectl drain <node> --ignore-daemonsets --timeout=300s` | Безопасное обслуживание узла | С учётом PDB и таймаута |
| `kubectl drain <node> --disable-eviction` | Drain без Eviction API | Полный обход PDB |
| `kubectl get events --field-selector reason=EvictionFailed` | Поиск ошибок eviction | Диагностика блокировок |
| `kubectl get pods -l <selector>` | Поды, защищённые PDB | Проверка селектора |
| `kubectl scale deployment <name> --replicas=N+1` | Временное увеличение реплик | Обход блокировки через scale-up |

---

## Edge Cases

**PDB с пересекающимися селекторами:**
```bash
# Два PDB защищают одни поды
kubectl get pdb -A -o json | jq '.items[] | {name: .metadata.name, selector: .spec.selector}'
# → {"name": "pdb-1", "selector": {"matchLabels": {"app": "web"}}}
# → {"name": "pdb-2", "selector": {"matchLabels": {"app": "web", "tier": "frontend"}}}

# Eviction API проверяет оба PDB. Если хотя бы один запрещает — eviction отклоняется.
# Решение: удалите дублирующий PDB или объедините правила.
```

**PDB без селектора:**
```bash
kubectl get pdb -o json | jq '.items[] | select(.spec.selector == null) | .metadata.name'
# → ["global-pdb"]
# Этот PDB защищает ВСЕ поды в namespace!
```

**PDB с `minAvailable: 0`:**
```bash
# minAvailable: 0 не отключает PDB — он разрешает выселение всех подов,
# но PDB по-прежнему проверяется через Eviction API
# disruptionsAllowed будет равен currentHealthy (все поды могут быть выселены)
```

**PDB и ResourceQuota:**
```bash
# PDB в Terminating считается в ResourceQuota
kubectl get resourcequota -n <namespace> -o jsonpath='{.items[*].status}'
# Ищите: "pods" в "used" vs "hard"
# Если quota исчерпана, новые поды не будут созданы для восстановления PDB
```

**PDB и готовность (readiness):**
```bash
# Если все поды в Terminating, currentHealthy = 0
# PDB не может разрешить выселение, т.к. нет здоровых подов
# Это приводит к deadlock: drain ждёт PDB, а PDB ждёт здоровых подов
# Решение: unhealthyPodEvictionPolicy: AlwaysAllow
```

---

**См. также:**
- [Определения Pod Terminating](./definitions.md) — базовые термины и механизмы.
- [Диагностика Pod Terminating](./diagnostics.md) — общий алгоритм поиска причин зависания.
- [Graceful Shutdown](./graceful_shutdown.md) — настройка периодов завершения и preStop.
- [Ошибки размонтирования томов](./volume_unmount_issues.md) — глубокий анализ проблем ФС.
- [Проблемы финализаторов](./finalizer_issues.md) — ручная очистка и CSI-специфика.
- [Недоступность узла](./node_unavailable_issues.md) — действия при отказе инфраструктуры.
- [Выселение подов: PDB и Taint-based Eviction](../../Troubleshooting/Common_Errors/PodEvicted/pdb_and_taint_eviction.md) — глубокий разбор взаимодействия PDB с taints и out-of-service.
- [Бюджет прерывания подов (PDB)](../../Autoscaling/pod_disruption_budget.md) — подробная архитектура и примеры конфигурации.
- [Обслуживание узлов](../../Operations/node_maintenance.md) — детали работы drain и cordon.
