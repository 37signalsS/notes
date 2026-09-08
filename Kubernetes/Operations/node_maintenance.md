# Обслуживание узлов Kubernetes: Cordon, Drain и NodeMaintenance API

## Определения

**Обслуживание узлов (Node Maintenance)** — процесс безопасного вывода узла из эксплуатации для плановых работ (обновление ядра, перезагрузка, замена оборудования, обновление runtime) с последующим возвратом в кластер. Главная цель — минимизация или полное исключение простоя приложений.

**Cordon** — команда `kubectl cordon`, которая помечает узел как `unschedulable`. Планировщик прекращает размещение новых подов на этом узле. Технически это реализуется через наложение **Taint** `node.kubernetes.io/unschedulable:NoSchedule`. Текущие поды продолжают работу. Статус узла в API: `SchedulingDisabled`.

**Drain** — команда `kubectl drain`, которая инициирует безопасное выселение (eviction) всех подов с узла. Команда автоматически выполняет `cordon` перед началом работы.

**Uncordon** — команда `kubectl uncordon`, которая снимает пометку `unschedulable` (удаляет Taint) и возвращает узел в пул доступных для планирования.

**NodeMaintenance API (Alpha, начиная с Kubernetes 1.31)** — декларативный механизм управления обслуживанием узлов через Custom Resource Definition (CRD). Позволяет автоматизировать отслеживание статуса обслуживания, связывать его с условиями узла и упорядочивать работы через контроллер, вместо использования ad-hoc скриптов и флагов.

## Основные концепции

### Команды управления узлами

| Команда | Назначение | Влияние на поды | Техническая реализация |
| :--- | :--- | :--- | :--- |
| `kubectl cordon <node>` | Запрет планирования новых подов | Существующие поды продолжают работу | Накладывает Taint `unschedulable:NoSchedule` |
| `kubectl drain <node>` | Выселение всех подов с узла | Поды пересоздаются контроллерами на других узлах | Использует Eviction API |
| `kubectl uncordon <node>` | Возврат узла в работу | Новые поды могут быть размещены на узле | Удаляет Taint `unschedulable` |

### Взаимодействие с Taints и Tolerations

Когда выполняется `cordon`, узел получает Taint `node.kubernetes.io/unschedulable:NoSchedule`. 
* **Прикладные поды:** По умолчанию не имеют Toleration для этого Taint, поэтому планировщик не ставит их на узел.
* **DaemonSets:** Контроллер DaemonSet автоматически добавляет `toleration` для `unschedulable:NoSchedule` всем подам. Это позволяет системным компонентам (например, `kube-proxy`, CNI) запускаться или продолжать работу на узле, даже если он изолирован для обслуживания.

### Отличие планового обслуживания от автоматического выселения (Eviction)

| Характеристика | Maintenance Eviction (Drain) | Node Pressure Eviction |
| :--- | :--- | :--- |
| **Инициатор** | Пользователь или скрипт автоматизации | Eviction Manager (kubelet) |
| **Причина** | Плановое обслуживание | Нехватка ресурсов (Memory/Disk/PID) |
| **Уважение PDB** | Да (drain может заблокироваться) | Нет (kubelet игнорирует PDB) |
| **Порядок выселения** | Все поды одновременно (с учетом Grace Period) | По приоритету QoS (BestEffort → Burstable → Guaranteed) |

### Процесс безопасного обслуживания

Процесс обеспечивает безопасное перенаправление рабочих нагрузок и подготовку узлов к техническим работам или обновлению версии.

```text
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Cordon    │ →  │    Drain    │ →  │   Работы /  │ →  │  Uncordon   │
│ (изоляция)  │    │ (выселение) │    │   Upgrade   │    │  (возврат)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **Cordon:** Изоляция узла. API помечает узел как `SchedulingDisabled`, что предотвращает планирование новых подов, сохраняя стабильность системы.
2. **Drain:** Безопасное выселение через Eviction API. Контроллеры пересоздают поды на других доступных узлах. Использование `--ignore-daemonsets` критично для того, чтобы системные компоненты (CNI, логирование) продолжали работать.
3. **Проведение работ / Upgrade:** Непосредственные действия на хосте. При обновлении версии Kubernetes здесь выполняется обновление `kubelet` и других бинарных файлов (например, с v1.30 на v1.31). Узел остается в статусе `SchedulingDisabled`.
4. **Uncordon:** Возврат узла в планировщик. Узел снова готов принимать новые нагрузки с обновленным ПО.

### Детальный разбор флагов kubectl drain

Команда `kubectl drain` по умолчанию защищает администратора от потери данных или нарушения работы системных компонентов, поэтому часто требует дополнительных флагов:

| Флаг | Назначение | Технический нюанс |
| :--- | :--- | :--- |
| `--ignore-daemonsets` | Игнорировать поды DaemonSet | **Критически важно:** поды DS управляются собственным контроллером. Их игнорирование позволяет очистить узел от прикладных подов, не прерывая работу базовой инфраструктуры узла. |
| `--delete-emptydir-data` | Удалять данные `emptyDir` | Флаг пришел на замену устаревшему `--delete-local-data`. Если под использует локальное хранилище в памяти или на диске узла, drain потребует подтверждений, так как эти данные будут безвозвратно удалены. **Внимание (v1.31+): Флаг `--delete-local-data` был окончательно удален из CLI, поэтому использование `--delete-emptydir-data` теперь строго обязательно.** |
| `--force` | Принудительное удаление | Позволяет выселять "голые" поды (Bare Pods), которые созданы вручную и не управляются контроллерами (Deployment/SS/RS). Такие поды НЕ будут пересозданы после удаления. |
| `--grace-period=<sec>` | Период завершения | Переопределяет `terminationGracePeriodSeconds`, указанный в спеке пода. Позволяет ускорить выселение или дать больше времени на сохранение состояния. |
| `--timeout=<duration>` | Максимальное время | Ограничивает общую длительность работы команды (например, `5m`). Полезно для CI/CD, чтобы избежать бесконечного ожидания из-за нарушенного PDB. |
| `--dry-run=client` | Пробный запуск | Позволяет увидеть список подов, которые будут выселены, и возможные ошибки (например, блокировка из-за PDB) без выполнения действий. |
| `--disable-eviction` | Отказ от Eviction API | Принудительно использует `delete` вместо `evict`. Игнорирует `PodDisruptionBudget`. Использовать только в экстренных случаях, когда узел "застрял" в drain. |

### NodeMaintenance API (Alpha, начиная с Kubernetes 1.31)

Новый декларативный механизм управления обслуживанием узлов через Custom Resource `NodeMaintenance`. В отличие от `kubectl drain`, API позволяет системе автоматически отслеживать состояние узла, применять политики и связывать работы с жизненным циклом узла.

**Пример CR `NodeMaintenance`:**

```yaml
apiVersion: maintenance.k8s.io/v1alpha1
kind: NodeMaintenance
metadata:
  name: worker-01-maintenance
spec:
  nodeName: worker-01
  reason: "Kernel upgrade to 6.8"
  startTime: "2025-01-15T10:00:00Z"
  endTime: "2025-01-15T11:00:00Z"
  taint:
    key: node.kubernetes.io/out-of-service
    effect: NoSchedule
```

**Политика автоматического drain:**

```yaml
apiVersion: maintenance.k8s.io/v1alpha1
kind: NodeMaintenancePolicy
metadata:
  name: auto-drain-policy
spec:
  matchLabels:
    maintenance-window: scheduled
  drain:
    ignoreDaemonsets: true
    deleteLocalData: true
    gracePeriod: 300
  uncordonAfterMaintenance: true
```

**Ключевые преимущества перед `kubectl drain`:**
* **Отслеживание состояния:** CR хранит историю работ (начало, окончание, причина), доступную через `kubectl get nodemaintenance`.
* **Автоматизация:** Контроллер может автоматически выполнять `drain` при появлении CR, и `uncordon` после истечения `endTime`.
* **Согласованность:** Политики применяются централизованно, что исключает ошибки человеческого фактора при массовом обслуживании.

### Ограничения и особенности

* **DaemonSet:** Поды не переносятся (должны работать на всех узлах). Если им нужны локальные данные, они должны быть в PersistentVolumes или HostPath (с осторожностью).
* **Static Pods:** Управляются kubelet напрямую через манифесты в `/etc/kubernetes/manifests`. API-сервер о них знает, но управлять ими не может (они зеркалируются как Read-Only объекты). `drain` их игнорирует. Для их удаления нужно физически удалить или переместить манифест из директории на хосте.
* **PodDisruptionBudget:** Drain строго соблюдает PDB. Если выселение нарушит минимально доступное количество реплик, drain будет ждать, пока бюджет не станет доступен. Это частая причина "зависания" автоматизации. **Начиная с Kubernetes 1.30, в PDB добавлено поле `spec.unhealthyPodEvictionPolicy`. Оно позволяет разрешить выселение "нездоровых" подов (например, в состоянии `CrashLoopBackOff`), чтобы они не блокировали процесс обслуживания узла.**
* **Storage (RWO vs RWX):** 
    * **ReadWriteOnce (RWO):** При выселении пода с RWO томом (например, на базе блочных устройств iSCSI, FC), новый под на другом узле сможет примонтировать том только после того, как старый узел выполнит `detach`. В локальных и корпоративных средах это может занимать до 2–5 минут.
    * **ReadWriteMany (RWX):** Поды с NFS/CephFS переезжают мгновенно, так как том может быть примонтирован к нескольким узлам одновременно.
* **Kube-proxy Connection Draining (Stable в v1.31):** Реализована нативная поддержка Graceful Draining для LoadBalancers. При изоляции узла `kube-proxy` сигнализирует внешнему балансировщику об остановке подачи новых запросов, но позволяет текущим соединениям штатно завершиться. Это критически важно для предотвращения потери трафика у сервисов с `externalTrafficPolicy: Cluster`.

### Graceful Node Shutdown

Начиная с Kubernetes 1.21, kubelet поддерживает корректное завершение работы подов при выключении самого хоста. Kubelet использует **Inhibit Locks** через `systemd-logind`, чтобы задержать выключение системы до тех пор, пока поды не завершатся.

* **shutdownGracePeriod:** Общее время, выделяемое на завершение всех подов (например, 30s).
* **shutdownGracePeriodCriticalPods:** Время в конце общего периода, выделяемое специально для критических подов (PriorityClass: `system-node-critical` или `system-cluster-critical`). Это гарантирует, что системные компоненты (например, логирование или мониторинг) завершатся последними.

Пример настройки в `KubeletConfiguration` (`/var/lib/kubelet/config.yaml`):
```yaml
shutdownGracePeriod: 30s
shutdownGracePeriodCriticalPods: 10s
```
**Важно:** Для работы этой функции на Linux должен быть запущен сервис `systemd-logind`.

### Мониторинг и алертинг

Пример Prometheus алертов для контроля состояния узлов:

```yaml
# Оповещение о неготовности узла (узел упал или потерял связь)
- alert: NodeNotReady
  expr: kube_node_status_condition{condition="Ready",status="true"} == 0
  for: 5m
  labels:
    severity: critical

# Узел помечен как unschedulable (SchedulingDisabled) более 2 часов
- alert: NodeSchedulingDisabledLongPeriod
  expr: kube_node_spec_unschedulable == 1
  for: 2h
  labels:
    severity: warning

# Нехватка ресурсов на узле (вызывает Eviction)
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: warning
```

## Операционные процедуры (SRE / Sysadmin)

### Ранбук обслуживания узлов

Стандартизированная процедура вывода узла в обслуживание:

1. **Создание окна обслуживания (Change Window):** Согласуйте время работ с командой, убедитесь, что PDB настроены, а количество одновременно обслуживаемых узлов не превышает допустимый порог.
2. **Предварительная проверка (Pre-drain Checks):** Выполните `kubectl drain <node> --dry-run=client` и проверьте PDB.
3. **Изоляция (Cordon):** Запретите планирование новых подов.
4. **Выселение (Drain):** Выселите существующие поды с учетом флагов `--ignore-daemonsets --delete-emptydir-data`.
5. **Проведение работ:** Выполните обновление ОС, ядра, runtime или замену оборудования.
6. **Валидация хоста:** Проверьте запуск kubelet, CNI, наличие модулей ядра, отсутствие свопа.
7. **Возврат (Uncordon):** Верните узел в пул планирования.
8. **Пост-проверка:** Убедитесь, что все поды вернулись на узел (если это ожидаемо) или что балансировка нагрузки восстановлена.

### Последовательное обслуживание (Serial Maintenance)

**Правило:** Обслуживайте узлы строго по одному. Параллельный drain нескольких узлов может привести к нарушению PDB и полной деградации сервиса.

**Исключение:** Для StatefulSet с кворумом (etcd, Kafka) обслуживание двух узлов одновременно возможно только если это не нарушает кворум и PDB разрешает одновременные разрывы. Всегда проверяйте `ALLOWED DISRUPTIONS` перед массовыми работами.

**Автоматизация:** Используйте скрипты с явным списком узлов и блокировкой, чтобы предотвратить параллельный запуск:

```bash
#!/bin/bash
NODES=("worker-01" "worker-02" "worker-03")
for node in "${NODES[@]}"; do
  echo "Maintenance: $node"
  kubectl cordon "$node"
  kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --timeout=5m
  # ... работы на хосте ...
  kubectl uncordon "$node"
  echo "Completed: $node"
done
```

### Обслуживание узлов Control Plane и etcd

Узлы Control Plane имеют дополнительные ограничения:

* **Control Plane:** Поды API Server, Scheduler, Controller Manager и etcd обычно развернуты как Static Pods. `kubectl drain` не затрагивает статические поды.
* **Дренаж etcd:** При обслуживании узла etcd убедитесь, что кворум не нарушен. Для многоузлового кластера etcd можно дренировать узел только если оставшиеся узлы формируют большинство.
* **Проверка лидерства:** Перед обслуживанием etcd-узла проверяйте лидера:
    ```bash
    etcdctl endpoint health -w table
    kubectl get lease -n kube-system -o custom-columns=NAME:.metadata.name,HOLDER:.spec.holderIdentity
    ```
* **Возврат:** После возврата узла в кластер убедитесь, что etcd-член снова участвует в голосовании и метрики `etcd_server_has_leader` показывают `1`.

### Валидация после возврата узла

После выполнения `uncordon` и проведения работ обязательно выполните проверку:

```bash
# 1. Статус узла
kubectl get node <node-name> -o wide
# → STATUS должен быть Ready, SchedulingDisabled снят

# 2. Назначение подов
kubectl get pods -o wide --all-namespaces | grep <node-name>
# → Новые поды должны появляться на узле по мере балансировки

# 3. Проверка компонентов
kubectl get pods -n kube-system -o wide | grep <node-name>
# → kube-proxy, CNI, мониторинг должны быть Running

# 4. Проверка kubelet на хосте
systemctl status kubelet containerd
journalctl -u kubelet -f --since "5 minutes ago"

# 5. Проверка модулей ядра
lsmod | grep -E "overlay|br_netfilter"

# 6. Проверка CNI
ls /opt/cni/bin/
kubectl get nodes <node-name> -o jsonpath='{.status.conditions[?(@.type=="NetworkUnavailable")].status}'
# → должно быть "False"
```

## Практические сценарии

### Предварительная верификация (Pre-drain checks)

Перед выполнением `drain` в production-средах всегда рекомендуется выполнять безопасную проверку на возможные блокировки без влияния на реальные поды:

```bash
# 1. Проверка блокировок PDB (Dry Run) — симулирует выселение и выводит возможные ошибки
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --dry-run=client

# 2. Поиск "голых" подов (Bare Pods), которые не управляются контроллерами и исчезнут навсегда (требуют --force)
kubectl get pods --all-namespaces --field-selector=metadata.ownerReferences=null --field-selector=spec.nodeName=node-1
```

### Стандартный вывод узла (Обновление/Перезагрузка)

**Шаг 1: Cordon (Изоляция)**
```bash
kubectl cordon node-1
# → node/node-1 cordoned
```

**Шаг 2: Drain (Выселение)**
```bash
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --timeout=5m
# → evicting pod default/web-app-7d8b...
# → pod/web-app-7d8b... evicted
# → node/node-1 drained
```

**Шаг 3: Проведение работ и возврат (Uncordon)**
```bash
kubectl uncordon node-1
# → node/node-1 uncordoned
```

### Экстренное обслуживание (Emergency Maintenance)

Если узел нестабилен и требуется немедленный drain (например, аппаратная ошибка, kernel panic):

```bash
# Принудительный drain с сокращенным grace period
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --force --grace-period=30 --timeout=2m

# Если drain зависает из-за PDB и требуется немедленный возврат узла:
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --disable-eviction --timeout=1m
```

**Важно:** После `--disable-eviction` поды удаляются напрямую, без graceful shutdown. Используйте только если узел угрожает стабильности кластера.

### Замена узла (Hardware Failure)

Если узел требует полной замены и не вернется в кластер:

1. **Выселение подов (если узел доступен по сети):**
    ```bash
    kubectl drain node-old --ignore-daemonsets --delete-emptydir-data --force
    ```

2. **Удаление объекта узла из API:**
    ```bash
    kubectl delete node node-old
    # → node "node-old" deleted
    ```

3. **Добавление нового узла:** Выполняется через `kubeadm join` или механизмы автоматического масштабирования кластера.

### Перенос подов на конкретный целевой узел

По умолчанию `drain` позволяет планировщику самому выбирать новые узлы. Если нужно перенести нагрузку на конкретный узел:

1. **Маркировка целевого узла:**
    ```bash
    kubectl label node node-target migration-target=true
    ```

2. **Обновление Deployment (Node Affinity):**
    ```bash
    kubectl patch deployment my-app --patch '{"spec": {"template": {"spec": {"nodeSelector": {"migration-target": "true"}}}}}'
    ```

3. **Выполнение drain на исходном узле:**
    ```bash
    kubectl drain node-source --ignore-daemonsets --delete-emptydir-data
    ```

### Перенос данных рантайма на другой раздел (Maintenance)

Сценарий: корневой раздел `/` переполнен, нужно перенести `/var/lib/kubelet` и `/var/lib/containerd` на выделенный диск `/mnt/data`.

1. **Изоляция и дренаж узла:**
    ```bash
    kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data
    ```

2. **Остановка сервисов на хосте:**
    ```bash
    systemctl stop kubelet containerd
    ```

3. **Синхронизация данных:**
    ```bash
    rsync -avPH /var/lib/kubelet/ /mnt/data/kubelet/
    rsync -avPH /var/lib/containerd/ /mnt/data/containerd/
    ```

4. **Конфигурация:**
    * **Containerd:** В `/etc/containerd/config.toml` изменить:
      ```toml
      root = "/mnt/data/containerd"
      ```
    * **Kubelet:** В `/etc/default/kubelet` (или аналогичном файле флагов) добавить:
      ```bash
      KUBELET_EXTRA_ARGS="--root-dir=/mnt/data/kubelet"
      ```

5. **Запуск и проверка:**
    ```bash
    systemctl daemon-reload
    systemctl start containerd kubelet
    kubectl uncordon node-1
    ```

### Пакетное обслуживание пула узлов (Rolling Node Pool Maintenance)

Сценарий: необходимо обновить ОС на всех узлах пула worker без нарушения работы сервисов.

**Алгоритм:**
1. Определите размер пула и PDB для критических сервисов.
2. Рассчитайте безопасный размер партии (Batch Size): количество одновременно обслуживаемых узлов должно быть меньше `maxUnavailable` в PDB.
3. Запустите цикл по пакетам:

```bash
WORKERS=("worker-01" "worker-02" "worker-03" "worker-04")
BATCH_SIZE=1  # или 2, если PDB позволяет

for ((i=0; i<${#WORKERS[@]}; i+=BATCH_SIZE)); do
  batch=("${WORKERS[@]:i:BATCH_SIZE}")
  for node in "${batch[@]}"; do
    kubectl cordon "$node"
    kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --timeout=5m
    # ... работы ...
    kubectl uncordon "$node"
  done
  # Пауза для стабилизации балансировки и прогрева кэшей
  sleep 60
done
```

**Валидация:** После каждого пакета проверяйте метрики availability и error rate сервисов.

### Обслуживание StatefulSet с локальным хранилищем (Local PV)

Если под использует **Local Persistent Volume** (связанный с конкретным диском на узле), `drain` не сможет перенести под на другой узел, так как данные доступны только здесь.

1. **Если данные не критичны (репликация на уровне приложения):**
    * Drain выселит под, он перейдет в статус `Pending` на других узлах (из-за несоответствия Node Affinity).
    * После возврата узла (`uncordon`) под вернется на исходное место.

2. **Если нужно заменить диск/узел:**
    * Сделайте бекап данных.
    * Удалите PVC и PV, связанные с этим узлом.
    * Удалите под вручную.
    * StatefulSet создаст новый под, который выберет новый доступный Local PV на другом узле.

## Дополнительная информация

### Диагностика и устранение проблем

Наиболее частые причины "зависания" drain:
* **PDB Violations:** Слишком жесткие правила (например, `minAvailable: 100%` для 1 реплики).
* **Finalizers:** Поды не могут удалиться из-за зависших финализаторов (например, в Helm или операторах). Используйте `kubectl patch pod <name> -p '{"metadata":{"finalizers":null}}' --type=merge` в экстренных случаях.
* **Storage Detach:** Система хранения не может отмонтировать блокировку от удаленного узла.
* **Забытый узел (Stale SchedulingDisabled):** Узел остался в `SchedulingDisabled`. Используйте `kubectl get nodes` для обнаружения и `kubectl uncordon` для возврата.
* **Host-level блокеры:** Swap включен, модули ядра не загружены, CNI отсутствует. Проверяйте логи kubelet на хосте.

Подробное руководство: **[Диагностика проблем обслуживания узла](../Troubleshooting/Common_Errors/NodeUnavailability/maintenance.md)**

### Диагностика на уровне хоста (Sysadmin)

После перезагрузки или технического обслуживания проверяйте:

```bash
# 1. Swap (блокирует kubelet по умолчанию)
swapon --show
# Если есть своп — отключите
swapoff -a

# 2. Модули ядра (обязательны для контейнеров и сети)
lsmod | grep -E "overlay|br_netfilter|nf_conntrack"

# 3. CNI-плагины
ls /opt/cni/bin/
# Проверка NetworkUnavailable
kubectl get node <node> -o jsonpath='{.status.conditions[?(@.type=="NetworkUnavailable")].status}'

# 4. Логи kubelet
journalctl -u kubelet -f --since "10 minutes ago"
journalctl -u kubelet -g "Shutdown manager"

# 5. Статус контейнерного runtime
systemctl status containerd
crictl info
```

### Лучшие практики

| Практика | Описание |
| :--- | :--- |
| **Проверка PDB** | Всегда делайте `kubectl get pdb -A` перед массовым обслуживанием. |
| **Таймауты** | Используйте флаг `--timeout`, чтобы не заблокировать конвейер автоматизации. |
| **Поочередность** | Обслуживайте узлы строго по одному (Serial Maintenance). |
| **Graceful Shutdown** | Настраивайте `terminationGracePeriodSeconds` в соответствии с логикой приложения. |
| **PreStop Hooks** | Используйте их для корректного завершения соединений (например, в Nginx), так как `drain` инициирует `SIGTERM`. |
| **Dry-run** | Всегда проверяйте `--dry-run=client` перед production drain. |
| **Изменения по Change Management** | Фиксируйте все окна обслуживания в ITSM/Change Management системе. |
| **Кворум etcd** | Никогда не обслуживайте более одного etcd-узла одновременно, если это приведет к потере кворума. |

### Автоматизация обслуживания

* **Kured (Kubernetes Reboot Daemon):** Следит за наличием файла `/var/run/reboot-required` на узлах и выполняет безопасный drain/reboot.
* **Draino:** Автоматически дренирует узлы при совпадении определенных условий (Taints, Node Conditions).
* **Cluster Autoscaler:** Включает логику drain перед удалением неиспользуемых узлов для экономии средств.
* **NodeMaintenance Controller:** При появлении CR `NodeMaintenance` автоматически изолирует и дренирует узел, возвращает его после окончания работ.

### Связанные темы

* [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — защита доступности при выселении.
* [Обновление кластера](upgrading_clusters.md) — процедура обновления компонентов через drain.
* [Высокая доступность](../Base/high_availability.md) — планирование ресурсов с учетом планового простоя.
* [Affinity и Anti-Affinity](../Scheduling/affinity.md) — управление распределением подов.
* [Troubleshooting: Node Unavailability](../Troubleshooting/Common_Errors/NodeUnavailability/maintenance.md) — решение проблем с доступностью.
* [Kubelet: Graceful Shutdown](../Concepts/kubelet.md) — корректное завершение работы узла.
