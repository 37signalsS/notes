# Pod в состоянии `Pending`: Диагностика и алгоритмы поиска

## Определения

**Диагностика Pending-статуса** — системный процесс выявления факторов, препятствующих переходу Pod в фазу `Running`. В Kubernetes диагностика разделяется на два критических этапа:
1.  **Диагностика планирования (Unscheduled):** анализ причин, по которым `kube-scheduler` не может назначить Pod на узел (отсутствие `spec.nodeName`).
2.  **Диагностика запуска (Scheduled):** поиск причин задержки на конкретном узле после назначения (например, подготовка окружения, томов или выполнение Init-контейнеров).

---

## Базовые концепции

### Диагностическая матрица (SOP)

| Симптом | Основной источник | Вероятная причина |
| :--- | :--- | :--- |
| **Node: <none>** | `kubectl describe pod` | Дефицит ресурсов, Taints, Affinity, Resource Quotas |
| **Events: FailedScheduling** | `kubectl get events` | Планировщик не нашел подходящий узел |
| **Events: FailedMount** | `kubectl describe pod` | Проблемы с PVC, доступностью дисков или лимитами аттача |
| **Init:0/1** | `kubectl logs -c <init>` | Ошибка в логике Init-контейнера или ожидание зависимости |
| **SchedulingGates: [...]** | `kubectl get pod -o yaml` | Под удерживается внешним контроллером (v1.30+) |
| **No Events & Node: <none>** | `kubectl describe quota` | Исчерпана квота ресурсов в Namespace |

### Современный инструментарий (2025-2026)

*   **K8sGPT:** Автоматизированная диагностика с использованием LLM. Команда `k8sgpt analyze --explain` позволяет мгновенно получить интерпретацию сложных ошибок планирования.
*   **eBPF (Cilium/Hubble):** Позволяет выявить проблемы сетевой связности на этапе `ContainerCreating`, если CNI не может выделить IP-адрес.
*   **Ephemeral Containers:** Использование `kubectl debug` для инспекции состояния узла или томов "рядом" с зависшим подом.

---

## Алгоритм поиска неисправности

Для эффективной диагностики следуйте пошаговому протоколу:

1.  **Локализация этапа:**
    *   Если `Node: <none>` — исследуйте **Вектор 1 (Планирование)**.
    *   Если узел назначен — исследуйте **Вектор 2 (Запуск на узле)**.
2.  **Анализ событий (Events):** Выполните `kubectl describe pod <имя>`. Это приоритетный источник. Обратите внимание на сообщения `FailedScheduling`, так как они содержат точный отчет планировщика (например, `3 Insufficient cpu`).
3.  **Проверка условий (Conditions):** В выводе `describe` проверьте статус `PodScheduled`. Если он `False`, причина в планировщике.
4.  **Анализ зависимостей:** Проверьте состояние PVC (`kubectl get pvc`), Secret и ConfigMap, которые монтируются в Pod.

---

## Практические сценарии

### Вектор 1: Ошибки на этапе планирования (Unscheduled)

#### 1. Дефицит ресурсов и квоты
Проверьте, достаточно ли ресурсов в кластере и не превышены ли лимиты пространства имен.
```bash
# Просмотр аллокации ресурсов на узлах
kubectl describe nodes | grep -A 5 "Allocated resources"

# Проверка Resource Quotas в Namespace
kubectl describe quota -n <namespace>
```
*Белое пятно:* Если ресурсов на узлах достаточно, но под Pending — часто виновата именно `ResourceQuota`, блокирующая создание новых ресурсов сверх лимита.

#### 2. Ограничения размещения (Affinity/Taints/Conditions)
Убедитесь, что правила `nodeSelector`, `nodeAffinity` или `podAntiAffinity` физически выполнимы, а узлы не находятся в состоянии Pressure.
```bash
# Проверка Taints на узлах (блокирующие метки)
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Проверка условий узлов (MemoryPressure, DiskPressure, PIDPressure)
kubectl get nodes -o custom-columns=NAME:.metadata.name,CONDITIONS:.status.conditions[*].type
```
*Нюанс:* Если все узлы имеют `MemoryPressure`, планировщик не назначит на них новые поды.

#### 3. Приоритеты и вытеснение (Priority & Preemption)
Под может быть в Pending, если его приоритет ниже, чем у других подов, и в кластере нет места.
```bash
# Проверка PriorityClass пода
kubectl get pod <pod-name> -o jsonpath='{.spec.priorityClassName}'
```
Если под ожидает вытеснения других, в событиях появится `PreemptionVictims`.

#### 4. Врата планирования (Scheduling Gates)
Новая механика (v1.30+ GA) для удержания подов.
```bash
# Проверка наличия врат
kubectl get pod <pod-name> -o jsonpath='{.spec.schedulingGates}'
```
Если поле заполнено, планировщик игнорирует под, пока внешний контроллер не удалит врата.

---

### Вектор 2: Ошибки после назначения узла (Scheduled)

#### 1. Инициализация и Sidecars
Под остается в `Pending`, пока не завершатся все `InitContainers` и не станут Ready все `SidecarContainers` (native).
```bash
# Логи зависшего Init-контейнера
kubectl logs <pod-name> -c <init-container-name>

# Проверка статуса нативных сайдкаров (v1.29+)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[?(@.name=="<sidecar-name>")].ready}'
```

#### 2. Проблемы с томами (Volume Mounting)
Самая частая причина "зависания" после назначения узла.
```bash
# Проверка событий на предмет FailedMount или FailedAttachVolume
kubectl describe pod <pod-name> | grep -E "MountVolume|AttachVolume"

# Проверка PVC
kubectl get pvc -n <namespace>
```
*Нюанс:* Если используется `volumeBindingMode: WaitForFirstConsumer`, PVC будет в Pending до момента успешного планирования пода.

#### 3. Подготовка Sandbox и CNI
Если `kubelet` не может создать сетевой стек:
```bash
# Проверка условий готовности сетевой среды
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="PodReadyToStartContainers")]}'
```

---

## Полезные команды для мониторинга

| Задача | Команда |
| :--- | :--- |
| **Список всех Pending подов** | `kubectl get pods -A --field-selector status.phase=Pending` |
| **Анализ через K8sGPT** | `k8sgpt analyze --filter=Pod --explain` |
| **События планирования** | `kubectl get events --field-selector involvedObject.kind=Pod --sort-by='.lastTimestamp'` |
| **Просмотр логов планировщика** | `kubectl logs -n kube-system -l component=kube-scheduler` |

---

## Дополнительная информация

### Связанные ресурсы

*   **[Определения и концепции](./definitions_and_concepts.md)** — теоретическая база фаз и состояний.
*   **[Распространенные случаи и решения](./common_cases_and_solutions.md)** — инструкции по исправлению типовых ошибок (CPU, RAM, Taints).
*   **[Продвинутые темы](./advanced_topics.md)** — Topology Spread, Scheduling Framework и настройка профилей.
*   **[Диагностика PVC](../../../Storage/pv_and_pvc_scenarios.md#диагностика-pending-pvc)** — детальный разбор проблем с хранилищем.
*   **[Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md)** — как фаза Pending соотносится с другими состояниями.
