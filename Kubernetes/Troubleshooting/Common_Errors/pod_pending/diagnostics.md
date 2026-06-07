# Pod в состоянии `Pending`: Диагностика

## Определения

**Диагностика Pending-статуса** — процесс выявления причин, по которым Kubernetes Scheduler (Планировщик) не может назначить Pod на подходящий узел кластера.

**Ключевые признаки:**

- `Phase: Pending` в статусе объекта.
- События `FailedScheduling` в выводе описания пода.
- Отсутствие назначенного узла (`Node: <none>`).

## Основные концепции

### Источники диагностических данных

| Источник | Команда | Что искать |
|----------|---------|------------|
| **События (Events)** | `kubectl describe pod <pod>` | Ошибки `FailedScheduling`, `Insufficient CPU` |
| **Ресурсы узлов** | `kubectl top nodes` | Дефицит ресурсов на уровне всего кластера |
| **Taints (Изоляция)** | `kubectl describe node <node>` | Метки `Taints`, блокирующие запуск пода |
| **Статус PVC** | `kubectl get pvc` | Ожидание привязки тома (состояние `Pending`) |
| **Квоты (Quotas)** | `kubectl describe resourcequota` | Превышение лимитов ресурсов в Namespace |

### Алгоритм поиска неисправности

1. **Анализ событий**: получение первичной причины от планировщика через `describe`.
2. **Проверка ресурсов**: сопоставление `requests` (запросов) пода с доступной емкостью узлов.
3. **Анализ ограничений**: проверка `nodeSelector`, `affinity` и наличие `taints` на узлах.
4. **Проверка внешних зависимостей**: состояние `PVC` и выполнение условий `ResourceQuota`.

## Практические сценарии

### Пошаговый чек-лист диагностики

#### Шаг 1: Проверка статуса пода и событий

```bash
kubectl describe pod <pod-name>
```

**Ищите в разделе `Events` причины неудачного планирования:**

```text
Type     Reason            Message
----     ------            -------
Warning  FailedScheduling  0/3 nodes are available: 3 Insufficient cpu.
```

#### Шаг 2: Анализ доступных ресурсов

Если причина в `Insufficient cpu/memory`:

```bash
# Текущее потребление ресурсов узлами
kubectl top nodes

# Запрошенные ресурсы (Requests/Limits) на узлах
kubectl describe nodes | grep -A 5 "Allocated resources"

# Общая емкость (Capacity) и доступные ресурсы узлов
kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.capacity.cpu,MEM:.status.capacity.memory
```

#### Шаг 3: Проверка Taints (Изоляция узлов)

Если планировщик сообщает о наличии `taint`, который под не `tolerate`:

```bash
# Список всех Taints на узлах кластера
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Детальная проверка Taints конкретного узла
kubectl describe node <node-name> | grep -A 5 "Taints:"
```

#### Шаг 4: Проверка Affinity и NodeSelector

Если узел не соответствует правилам привязки (`didn't match Pod's node affinity/selector`):

```bash
# Проверка требований пода к узлам
kubectl get pod <pod-name> -o jsonpath='{.spec.nodeSelector}'
kubectl get pod <pod-name> -o jsonpath='{.spec.affinity}'

# Проверка меток (Labels) на узлах
kubectl get nodes --show-labels
```

#### Шаг 5: Проверка зависимостей (PVC)

Если под ожидает привязки хранилища (`unbound immediate PersistentVolumeClaims`):

```bash
# Проверка статуса PVC в namespace
kubectl get pvc -n <namespace>

# Детальная диагностика причины ожидания PVC
kubectl describe pvc <pvc-name>

# Список доступных PV в кластере
kubectl get pv
```

#### Шаг 6: Проверка квот (ResourceQuota)

Если создание пода блокируется квотами (`failed quota`):

```bash
# Проверка текущего использования квот в namespace
kubectl describe resourcequota -n <namespace>

# Проверка лимитов по умолчанию (LimitRange)
kubectl describe limitrange -n <namespace>
```

## Дополнительная информация

### Полезные команды для мониторинга

| Задача | Команда |
|--------|---------|
| **Все Pending поды в кластере** | `kubectl get pods -A --field-selector status.phase=Pending` |
| **Сортировка по времени создания** | `kubectl get pods --field-selector status.phase=Pending --sort-by='.metadata.creationTimestamp'` |
| **Удаление всех зависших подов** | `kubectl delete pods --field-selector status.phase=Pending -A` |

### Смотрите также

- **[Определения и концепции](./definitions_and_concepts.md)** — базовое описание фазы Pending и работы планировщика.
- **[Распространенные случаи и решения](./common_cases_and_solutions.md)** — подробные инструкции по исправлению типовых ошибок.
- **[Advanced Topics](./advanced_topics.md)** — мониторинг, алертинг и сложные сценарии планирования.
