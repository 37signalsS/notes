# Обслуживание узлов Kubernetes: Cordon и Drain

## Определения

**Обслуживание узлов** — процесс безопасного вывода узла из эксплуатации для плановых работ (обновление ядра, перезагрузка, замена оборудования) с последующим возвратом в кластер.

**Cordon** — команда `kubectl cordon`, которая помечает узел как `unschedulable`. Планировщик прекращает размещение новых подов на этом узле. Статус узла: `SchedulingDisabled`.

**Drain** — команда `kubectl drain`, которая безопасно выселяет (evict) все поды с узла. Неявно выполняет `cordon` перед началом работы.

**Uncordon** — команда `kubectl uncordon`, которая снимает пометку `unschedulable` и возвращает узел в пул доступных для планирования.

## Основные концепции

### Команды управления узлами

| Команда | Назначение | Влияние на поды |
| :--- | :--- | :--- |
| `kubectl cordon <node>` | Запрет планирования новых подов | Существующие поды продолжают работу |
| `kubectl drain <node>` | Выселение всех подов с узла | Поды пересоздаются на других узлах |
| `kubectl uncordon <node>` | Возврат узла в работу | Новые поды могут быть размещены |

### Отличие обслуживания от автоматического выселения (Eviction)

| Характеристика | Maintenance Eviction (Drain) | Node Pressure Eviction |
| :--- | :--- | :--- |
| **Инициатор** | Пользователь (`kubectl drain`) | Eviction Manager (kubelet) |
| **Причина** | Плановое обслуживание | Нехватка ресурсов (Memory/Disk) |
| **Уважение PDB** | Да (drain остановится) | Нет (kubelet игнорирует PDB) |
| **Порядок выселения** | Все поды одновременно | По приоритету QoS |

### Процесс безопасного обслуживания

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Cordon    │ →  │    Drain    │ →  │   Работы    │ →  │  Uncordon   │
│ (запрет)    │    │ (выселение) │    │  на узле    │    │  (возврат)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **Cordon:** Изоляция узла от новых размещений.
2. **Drain:** Безопасное выселение существующих подов через Eviction API.
3. **Проведение работ:** Обслуживание самого узла (Update, Reboot).
4. **Uncordon:** Возврат узла в кластер.

### Нюансы команды drain

`kubectl drain` останавливается при обнаружении определённых условий. Требуются флаги:

| Флаг | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `--ignore-daemonsets` | Игнорировать поды DaemonSet | Почти всегда (CNI, logging, monitoring) |
| `--delete-emptydir-data` | Удалять temporary данные | Если поды используют `emptyDir` |
| `--force` | Принудительное удаление | Для "голых" подов без контроллера |
| `--grace-period=<sec>` | Таймаут завершения подов | Контроль времени shutdown |
| `--timeout=<duration>` | Максимальное время drain | Ограничение общей длительности |

**Ограничения drain:**

* **DaemonSet:** Поды не переносятся (должны работать на всех узлах).
* **Static Pods:** Управляются kubelet, не через API.
* **PodDisruptionBudget:** Drain уважает PDB и не нарушит доступность.
* **Голые поды:** Без контроллера (ReplicaSet/Deployment) не будут пересозданы.

### Мониторинг и алертинг

Пример Prometheus алертов для отслеживания состояния узлов:

```yaml
# Prometheus alerts
- alert: NodeNotReady
  expr: kube_node_status_condition{condition="Ready",status="true"} == 0
  for: 5m
  labels:
    severity: critical

- alert: NodeSchedulingDisabled
  expr: kube_node_spec_unschedulable == 1
  for: 30m
  labels:
    severity: warning

- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
```

## Практические сценарии

### Стандартный вывод узла

**Шаг 1: Cordon**

```bash
kubectl cordon node-1
# → node/node-1 cordoned
```

**Шаг 2: Drain**

```bash
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data
# → node/node-1 cordoned
# → evicting pod default/app-1
# → pod/app-1 evicted
# → node/node-1 drained
```

**Шаг 3: Uncordon**

```bash
kubectl uncordon node-1
# → node/node-1 uncordoned
```

### Замена узла (Hardware Failure)

Если узел требует полной замены:

```bash
# 1. Выселение подов (если узел ещё доступен по сети)
kubectl drain node-old --ignore-daemonsets --delete-emptydir-data --force

# 2. Удаление объекта узла из API
kubectl delete node node-old
# → node "node-old" deleted

# 3. Добавление нового узла в кластер (kubeadm join или облачный autoscaler)
```

### Перенос подов на конкретный узел

`kubectl drain` не позволяет указать целевой узел напрямую. Рекомендуемый способ — использование Node Affinity:

```bash
# 1. Добавить метку на целевой узел
kubectl label node node-target target=true

# 2. Обновить Deployment, добавив nodeAffinity к узлу с меткой target=true
kubectl patch deployment app-1 --patch-file affinity-patch.yaml

# 3. Выполнить drain исходного узла
kubectl drain node-source --ignore-daemonsets --delete-emptydir-data
```

### Перенос данных рантайма на другой раздел

Когда корневой раздел `/` заполняется, можно перенести `/var/lib/kubelet` и `/var/lib/containerd` на другой раздел (например, `/storage`).

1. **Остановка компонентов:**
   ```bash
   systemctl stop kubelet containerd
   ```

2. **Копирование данных:**
   ```bash
   rsync -av /var/lib/kubelet/ /storage/kubelet/
   rsync -av /var/lib/containerd/ /storage/containerd/
   ```

3. **Конфигурация:**
   - `containerd`: в `/etc/containerd/config.toml` установить `root = "/storage/containerd"`.
   - `kubelet`: в `/etc/default/kubelet` добавить `KUBELET_EXTRA_ARGS="--root-dir=/storage/kubelet"`.

4. **Запуск:**
   ```bash
   systemctl daemon-reload
   systemctl start containerd kubelet
   ```

## Дополнительная информация

### Диагностика и устранение проблем

#### Drain завис из-за PDB
**Проблема:** `error: cannot evict pod as it would violate the pod's disruption budget`.
**Решение:** временно увеличить число реплик Deployment или изменить PDB.

#### Поды застряли в состоянии Terminating
**Проблема:** Поды не удаляются из-за наличия Finalizers.
**Решение:** `kubectl patch pod <pod-name> -p '{"metadata":{"finalizers":null}}'`.

#### Проверка истории обслуживания
```bash
kubectl get events --field-selector reason=SuccessfulDrain
# → 5m  Normal  SuccessfulDrain  node/node-1  Node node-1 successfully drained
```

### Лучшие практики

| Практика | Описание |
| :--- | :--- |
| **Проверка PDB** | Всегда проверяйте `kubectl get pdb` перед началом drain. |
| **Таймауты** | Используйте `--timeout=5m`, чтобы избежать бесконечного ожидания. |
| **Очередность** | Выводите узлы по одному. |
| **Graceful Shutdown** | Настраивайте `terminationGracePeriodSeconds`. |

### Автоматизация обслуживания

* **Kured (Kubernetes Reboot Daemon):** Автоматизирует reboot узлов после обновления ядра.
* **Draino:** Автоматически выполняет drain узлов на основе Taints или условий.
* **Cluster Autoscaler:** Выполняет drain перед удалением неиспользуемых узлов в облаке.

### Связанные темы

* [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — защита доступности при выселении.
* [Обновление кластера](upgrading_clusters.md) — использование drain при обновлении компонентов.
* [Высокая доступность](../Base/high_availability.md) — планирование мощностей с учетом обслуживания.
* [Affinity и Anti-Affinity](../Scheduling/affinity.md) — управление размещением подов.
* [Troubleshooting: Node Unavailability](../Troubleshooting/Common_Errors/NodeUnavailability/maintenance.md) — диагностика проблем узлов.
