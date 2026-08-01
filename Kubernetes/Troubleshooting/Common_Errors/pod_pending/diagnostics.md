# Pod в состоянии `Pending`: Диагностика

## Определения

**Диагностика Pending-статуса** — процесс выявления причин, по которым Pod не переходит в фазу `Running`. В зависимости от этапа жизненного цикла объекта диагностика разделяется на два типа:
1.  **Диагностика планирования (Unscheduled):** поиск причин, по которым `kube-scheduler` не может выбрать узел.
2.  **Диагностика запуска (Scheduled):** поиск причин задержки на конкретном узле после назначения (например, при работе Init-контейнеров).

## Основные концепции

### Источники диагностических данных

| Источник | Команда | Что искать |
|:---|:---|:---|
| **События (Events)** | `kubectl describe pod <pod>` | Ошибки `FailedScheduling`, `FailedMount`, `BackOff` |
| **Условия (Conditions)** | `kubectl get pod <pod> -o json` | Статус `PodScheduled`, `Initialized`, `ContainersReady` |
| **Ресурсы узлов** | `kubectl top nodes` | Дефицит CPU/RAM на уровне кластера или конкретного узла |
| **Спецификация (Spec)** | `kubectl get pod <pod> -o yaml` | Наличие `schedulingGates`, `nodeSelector`, `affinity` |
| **Логи планировщика** | `kubectl logs -n kube-system <scheduler-pod>` | Детальная логика отказа в планировании (в сложных случаях) |

### Алгоритм поиска неисправности

1.  **Проверка назначения узла:** если `Node: <none>`, проблема в планировщике. Если узел указан — проблема в инфраструктуре узла или зависимостях.
2.  **Анализ событий (Events):** это ваша первая и самая важная задача. Выполните `kubectl describe pod <имя-пода>` и сфокусируйтесь на разделе **Events** в самом низу. Именно здесь планировщик оставляет сообщение с объяснением своего решения.
3.  **Проверка условий (Conditions):** сопоставление фазы с конкретными флагами готовности.
4.  **Анализ зависимостей:** проверка состояния `PersistentVolumeClaim` (PVC), `ConfigMap`, `Secret` и `Init-контейнеров`.

## Практические сценарии

### Вектор 1: Узел не назначен (Unscheduled)

Если под застрял на этапе планирования, проверьте следующие аспекты:

#### 1. Ресурсы и квоты
Проверьте соответствие `requests` пода доступной емкости узлов:
```bash
# Просмотр причин отказа в планировании
kubectl describe pod <pod-name> | grep -A 5 Events

# Просмотр аллокации ресурсов на узлах
kubectl describe nodes | grep -A 5 "Allocated resources"
```

#### 2. Ограничения размещения (Affinity/Taints)
Проверьте, не блокируют ли правила выбора узлов планирование:
```bash
# Проверка меток узлов
kubectl get nodes --show-labels

# Проверка Taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

#### 3. Врата планирования (Scheduling Gates)
Если событий `FailedScheduling` нет, проверьте, не удерживается ли под внешним контроллером:
```bash
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
```

---

### Вектор 2: Узел назначен (Scheduled)

Если узел выбран, но фаза остается `Pending`, проверьте процессы подготовки:

#### 1. Инициализация (Init Containers)
Под остается в `Pending`, пока не завершатся все Init-контейнеры:
```bash
# Проверка статуса Init-контейнеров
kubectl get pod <pod-name> -o jsonpath='{.status.initContainerStatuses[*].state}'

# Логи зависшего Init-контейнера
kubectl logs <pod-name> -c <init-container-name>
```

#### 2. Подключение томов (Volume Mounting)
Ошибки монтирования часто удерживают под в состоянии подготовки:
```bash
# Проверка событий на предмет FailedMount или FailedAttachVolume
kubectl describe pod <pod-name> | grep -E "MountVolume|AttachVolume"
```

#### 3. Подготовка сети и образов
Если `kubelet` не может создать sandbox или скачать образ:
```bash
# Проверка условий готовности сетевой среды
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodReadyToStartContainers")]}'
```

---

### Полезные команды для мониторинга

| Задача | Команда |
|:---|:---|
| **Все Pending поды** | `kubectl get pods -A --field-selector status.phase=Pending` |
| **Причины по всем подам** | `kubectl get events --field-selector involvedObject.kind=Pod --sort-by='.lastTimestamp'` |
| **Статус PVC для подов** | `kubectl get pvc -n <namespace>` |

## Дополнительная информация

### Связанные ресурсы

- **[Определения и концепции](./definitions_and_concepts.md)** — описание фазы Pending и стадий планирования.
- **[Распространенные случаи и решения](./common_cases_and_solutions.md)** — инструкции по исправлению типовых ошибок.
- **[Advanced Topics](./advanced_topics.md)** — мониторинг, Scheduling Framework и Topology Spread.
