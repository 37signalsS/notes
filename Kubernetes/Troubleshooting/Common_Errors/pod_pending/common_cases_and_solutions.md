# Pod в состоянии `Pending`: Распространенные случаи и решения

## Определения

**Сценарии Pending-статуса** — типичные ситуации, при которых планировщик (kube-scheduler) не может назначить Pod на узел из-за ограничений конфигурации или нехватки мощностей кластера.

**Вытеснение (Preemption)** — механизм освобождения ресурсов узла путём удаления низкоприоритетных подов для запуска высокоприоритетного объекта.

> Базовая теория: **[Определения и концепции](./definitions_and_concepts.md)**

## Основные концепции

Для устранения состояния `Pending` необходимо выявить, на какой стадии фильтрации планировщика происходит отказ. Информация об этом содержится в событиях объекта (`Events`).

Типичный процесс исправления:

1. Определение причины через `kubectl describe`.
2. Сопоставление требований Pod (Requests, Affinity, PVC) с состоянием кластера.
3. Корректировка манифеста или инфраструктуры.

## Практические сценарии

### 1. Нехватка ресурсов (`Insufficient cpu/memory`)

**Симптом (Events):**

```text
Warning  FailedScheduling  default-scheduler  0/3 nodes are available: 3 Insufficient cpu.
```

**Решение:**

| Метод | Действие |
|-------|----------|
| **Оптимизация requests** | Уменьшить запрашиваемые ресурсы в `spec.containers[].resources.requests`. |
| **Масштабирование** | Добавить узлы в кластер (вручную или через Cluster Autoscaler). |
| **Очистка ресурсов** | Удалить неиспользуемые поды в кластере. |
| **Вертикальный рост** | Увеличить параметры CPU/RAM на существующих инстансах узлов. |

---

### 2. Несоответствие меток (`nodeSelector` / `nodeAffinity`)

**Симптом (Events):**

```text
Warning  FailedScheduling  default-scheduler  0/3 nodes are available: 3 node(s) didn't match Pod's node affinity/selector.
```

**Решение:**

1. Посмотреть текущие метки узлов:

   ```bash
   kubectl get nodes --show-labels
   ```

2. Если метка отсутствует, добавить её на узел:

   ```bash
   kubectl label node <node-name> disktype=ssd
   ```

3. Или привести `nodeSelector`/`affinity` в манифесте Pod в соответствие с существующими метками.

---

### 3. Изоляция узлов (Taints) без разрешений (Tolerations)

**Симптом (Events):**

```text
Warning  FailedScheduling  default-scheduler  0/3 nodes are available: 3 node(s) had taint {dedicated: master}, that the pod didn't tolerate.
```

**Решение:**
Добавить блок `tolerations` в спецификацию Pod:

```yaml
spec:
  tolerations:
  - key: "dedicated"
    operator: "Equal"
    value: "master"
    effect: "NoSchedule"
```

---

### 4. Ожидание привязки хранилища (PVC)

**Симптом (Events):**

```text
Warning  FailedScheduling  default-scheduler  0/3 nodes are available: 3 pod has unbound immediate PersistentVolumeClaims.
```

**Решение:**

1. Проверить состояние PVC:

   ```bash
   kubectl describe pvc <pvc-name>
   ```

2. Убедиться, что существует подходящий `PersistentVolume` (PV) или работает динамический provisioner (CSI driver).

> Подробная диагностика проблем с хранилищем: **[CreateContainerConfigError: Проблемы с PVC](../CreateContainerConfigError/pvc_issues.md)**.

---

### 5. Превышение квот в Namespace (ResourceQuota)

**Симптом (Events):**

```text
Warning  FailedCreate  replicaset-controller  Error creating: pods "my-app-x" is forbidden: exceeded quota: team-a-quota, requested: requests.cpu=1, used: requests.cpu=10, limited: requests.cpu=10
```

**Решение:**

1. Проверить текущее использование квот:

   ```bash
   kubectl describe resourcequota -n <namespace>
   ```

2. Увеличить лимиты в объекте `ResourceQuota` или уменьшить потребление ресурсов в данном пространстве имен.

---

### 6. Ожидание вытеснения (PriorityClass)

**Сценарий:** Pod с высоким приоритетом остается в `Pending`, пока планировщик инициирует процедуру вытеснения для освобождения ресурсов.

**Диагностика:**

```bash
# Проверка PriorityClass пода
kubectl get pod <pod-name> -o jsonpath='{.spec.priorityClassName}'
```

**Решение:**

- Убедиться, что в кластере есть поды с более низким приоритетом, которые *могут* быть вытеснены.
- Проверить, не установлена ли политика `preemptionPolicy: Never` в объекте `PriorityClass`.

## Дополнительная информация

### Связанные ресурсы

- **[Диагностика](./diagnostics.md)** — пошаговый чек-лист команд.
- **[Advanced Topics](./advanced_topics.md)** — глубокий анализ планирования и мониторинг.
- **[Управление ресурсами](../../Scheduling/qos_limit_and_requests.md)** — подробнее о лимитах, запросах и квотах.
- **[Affinity и Anti-Affinity](../../Scheduling/affinity.md)** — механизмы привязки к узлам и подам.
