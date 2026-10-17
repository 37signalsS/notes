# Высокая доступность (High Availability) в Kubernetes

**Актуально для:** Kubernetes 1.30–1.35 (Bare-Metal / On-Premise)

## Определения

Для проектирования и эксплуатации отказоустойчивой инфраструктуры Kubernetes системным инженерам и SRE необходимо четко разграничивать базовые понятия надежности:

*   **Высокая доступность (High Availability, HA)**: Архитектурное свойство системы, гарантирующее непрерывность предоставления сервиса и минимизацию времени простоя при отказе отдельных аппаратных или программных компонентов (серверов, сетевых интерфейсов, дисков, PDU). Достигается устранением единых точек отказа за счет избыточности (redundancy), автоматического обнаружения сбоев и переключения (failover).
*   **Надежность (Reliability)**: Способность системы безошибочно и предсказуемо выполнять требуемые функции в течение заданного интервала времени при соблюдении эксплуатационных требований (соответствие SLI/SLO по latency, отсутствие всплесков кодов 5xx).
*   **Устойчивость (Resilience / Fault Tolerance)**: Способность системы выдерживать непредвиденные сбои (катастрофический отказ питания, расщепление сети), автоматически адаптироваться и продолжать функционирование в режиме контролируемой деградации (Graceful Degradation) с последующим самоисцелением.
*   **Единая точка отказа (Single Point of Failure, SPOF)**: Компонент архитектуры (физический сервер, коммутатор, единственный экземпляр пода, нереплицируемая база данных), отказ которого влечет за собой полный останов системы или потерю управляемости.
*   **Кворум (Quorum)**: Минимальное количество голосующих членов в распределенной системе с консенсусом (в Kubernetes — кластер `etcd` на базе алгоритма Raft), необходимое для принятия решения о фиксации изменений состояния. Для кластера из $N$ узлов кворум строго равен $\lfloor N/2 \rfloor + 1$.
*   **Домен отказа (Failure Domain / Fault Domain)**: Физический или логический сегмент инфраструктуры, компоненты которого подвержены общему риску одновременного выхода из строя. В On-Premise / Bare-Metal окружениях доменами отказа выступают: процесс → операционная система (хост) → серверная стойка (Rack) → ввод электропитания (PDU / UPS) → сетевой ToR-коммутатор → машинный зал / датацентр.
*   **Изоляция узла (Fencing)**: Принудительное отключение или изоляция сбойного узла от общих ресурсов (сети, хранилища SAN/NAS/Ceph, питания через IPMI/STONITH) для предотвращения одновременного доступа к данным и разрушения файловой системы.
*   **Расщепление сети (Split-Brain)**: Критическое состояние распределенной системы, при котором из-за потери связности кластер разделяется на изолированные сегменты, каждый из которых ошибочно считает себя единственным выжившим и пытается параллельно управлять ресурсами или фиксировать данные.
*   **Цикл согласования (Reconciliation Loop)**: Фундаментальный принцип работы контроллеров Kubernetes: непрерывное сопоставление фактического состояния кластера (Actual State) с желаемым состоянием (Desired State), зафиксированным в `etcd`, и выполнение корректирующих действий при обнаружении расхождений.
*   **Бюджет прерывания подов (PodDisruptionBudget, PDB)**: Объект API Kubernetes (`policy/v1`), устанавливающий защитный лимит на допустимое количество одновременно недоступных реплик при добровольных (плановых) операциях обслуживания кластера (`kubectl drain`, обновление узлов).
*   **Плавное завершение (Graceful Shutdown)**: Контролируемый процесс остановки контейнеров, включающий перехват сигнала `SIGTERM`, завершение активных клиентских соединений (connection draining) и сброс внутренних буферов до принудительного уничтожения процессом `SIGKILL`.

Общие архитектурные модели надежности (расчет доступности, RTO, RPO, MTTR) подробно разобраны в **[Обзоре High Availability](../../Concepts/High_Availability/ha_overview.md)**.

---

## Основные концепции

Высокая доступность в Kubernetes строится по двухуровневой модели:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       УРОВЕНЬ 1: CONTROL PLANE HA                           │
│  [ Keepalived / kube-vip (VIP) + HAProxy / BGP ECMP (L4 Балансировщик) ]    │
│            │                             │                             │    │
│     ┌──────▼──────┐               ┌──────▼──────┐               ┌──────▼───┐│
│     │ kube-apiserver              │ kube-apiserver              │ kube-api ││
│     │ (Stateless) │               │ (Stateless) │               │ (State)  ││
│     ├─────────────┤               ├─────────────┤               ├──────────┤│
│     │ Lease Leader│               │ Lease Standby│              │ Lease St.││
│     │ (KCM / Sched)               │ (KCM / Sched)│              │ (KCM/Sch)││
│     ├─────────────┤               ├─────────────┤               ├──────────┤│
│     │ etcd member │ ◄── Raft ───► │ etcd member │ ◄── Raft ───► │ etcd mem ││
│     │ (Node 1)    │               │ (Node 2)    │               │ (Node 3) ││
│     └─────────────┘               └─────────────┘               └──────────┘│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Сеть кластера (CNI)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                    УРОВЕНЬ 2: WORKLOAD & DATA PLANE HA                      │
│                                                                             │
│   Стойка A (Rack 1)               Стойка B (Rack 2)                         │
│  ┌───────────────────────┐       ┌───────────────────────┐                  │
│  │ Worker Node 1         │       │ Worker Node 2         │                  │
│  │ ┌───────────────────┐ │       │ ┌───────────────────┐ │  PDB:            │
│  │ │ Pod Реплика 1     │ │       │ │ Pod Реплика 2     │ │  minAvailable: 2 │
│  │ └───────────────────┘ │       │ └───────────────────┘ │                  │
│  │ topologySpread:       │       │ topologySpread:       │  Service /       │
│  │ zone=rack-1           │       │ zone=rack-2           │  EndpointSlice   │
│  └───────────────────────┘       └───────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### Архитектура высокой доступности Control Plane

Control Plane координирует все действия в кластере. Отказ плоскости управления блокирует возможность создания, изменения и автовосстановления ресурсов, хотя существующие рабочие поды на Data Plane продолжают обслуживать входящий трафик.

#### 1. Распределенное хранилище etcd и математика кворума

`etcd` — единственное хранилище состояния Kubernetes. Надежность etcd опирается на алгоритм консенсуса Raft:

*   **Требование нечетного числа узлов**: Допустимое число отказавших узлов рассчитывается как $F = \frac{N - 1}{2}$.
    *   Кластер из 3 узлов: кворум = 2, допустимый отказ = 1 узел.
    *   Кластер из 4 узлов: кворум = 3, допустимый отказ = 1 узел (добавление 4-го узла не повышает отказоустойчивость, но увеличивает накладные расходы на сетевую репликацию и повышает вероятность отказа).
    *   Кластер из 5 узлов: кворум = 3, допустимый отказ = 2 узла.
*   **Stacked Control Plane vs External etcd**:
    *   *Stacked etcd*: Экземпляры etcd запускаются в виде статических подов на тех же физических серверах, где работают компоненты Control Plane (`kubeadm` по умолчанию). Это снижает затраты на серверы, но создает конкуренцию за память и дисковый ввод-вывод между `etcd` и `kube-apiserver`.
    *   *External etcd*: etcd вынесен на отдельный выделенный пул серверов. Рекомендуется для высоконагруженных промышленных кластеров (более 500 узлов / 10 000 подов) для полной аппаратной изоляции I/O.
*   **Требования к дисковой подсистеме**: `etcd` выполняет вызов `fsync` при фиксации каждой транзакции в Write-Ahead Log (WAL). Задержка записи на диск (`wal_fsync_duration_seconds`) не должна превышать **10 миллисекунд** (в идеале < 2–5 мс). Использование медленных HDD или сетевых дисков с высоким latency гарантированно приводит к тайм-аутам Raft-heartbeat, частым перевыборам лидера и дестабилизации кластера.

#### 2. Балансировка нагрузки API-серверов (Control Plane Endpoint)

Компонент `kube-apiserver` является **stateless**: он не хранит локального состояния и взаимодействует только с `etcd`. Экземпляры API-сервера работают в режиме **Active-Active** за L4-балансировщиком нагрузки.

В Bare-Metal / On-Premise окружениях SPOF на входе устраняется следующими архитектурными решениями:
*   **Keepalived + HAProxy**: На каждом мастере развертывается демон Keepalived (организующий Virtual IP по протоколу VRRP с режимом `nopreempt`) и локальный HAProxy, выполняющий TCP-балансировку на порт `6443` всех мастеров.
*   **kube-vip**: Cloud-native решение, запускаемое как Static Pod на управляющих узлах. Поддерживает режимы ARP (для простых L2-сегментов) и BGP (анонсирует маршрут к VIP на Top-of-Rack коммутаторы с поддержкой ECMP).
*   **BGP Anycast / ECMP**: Корпоративный сетевой подход, при котором один и тот же IP-адрес анонсируется всеми мастерами напрямую ToR-маршрутизаторам по протоколу BGP. Аппаратный коммутатор распределяет TCP-сессии по узлам через Equal-Cost Multi-Path.

#### 3. Активно-пассивные компоненты: Leader Election

В отличие от API-сервера, контроллеры `kube-controller-manager` и `kube-scheduler` изменяют состояние кластера. Чтобы исключить гонки и конфликты (Race Conditions), они функционируют по схеме **Active-Passive**:
*   В любой момент времени активен только **один** экземпляр (Leader). Остальные узлы находятся в режиме ожидания (Standby).
*   Выбор лидера выполняется через координационные объекты **Lease** (`coordination.k8s.io/v1`) в пространстве имен `kube-system`.
*   Активный лидер периодически обновляет метку времени в объекте Lease (`renewInterval: 2s`). Если лидер не продлил аренду в течение времени `leaseDuration: 15s`, резервный узел перехватывает лидерство.

#### 4. Защита API-сервера: API Priority and Fairness (APF)

При каскадных сбоях (например, массовый рестарт сотен узлов) API-сервер подвергается лавине запросов (Thundering Herd). Механизм **API Priority and Fairness (APF)** разделяет входящий поток запросов на логические очереди по объектам `FlowSchema` и распределяет вычислительные ресурсы сервера через `PriorityLevelConfiguration`, гарантируя, что системные контроллеры (`kubelet`, `kube-controller-manager`, `kube-scheduler`) не будут заблокированы тяжелыми запросами пользователей или систем мониторинга.

#### 5. Детектирование сбоев узлов (Node Lifecycle Controller)

Жизненный цикл рабочих узлов непрерывно отслеживается контроллером `NodeLifecycleController`:
1.  Каждый агент `kubelet` периодически обновляет свой объект аренды в неймспейсе `kube-node-lease` (по умолчанию каждые 10 секунд).
2.  Если контроллер не получает обновлений от узла в течение `node-monitor-grace-period` (по умолчанию **40 секунд**), узел переводится в статус `NotReady` или `Unknown`.
3.  На узел накладываются системные таинты:
    *   `node.kubernetes.io/not-ready:NoExecute`
    *   `node.kubernetes.io/unreachable:NoExecute`
4.  По умолчанию поды имеют допуск (`toleration`) к этим таинтам на срок `tolerationSeconds: 300` (5 минут). Если узел не восстановился за это время, запускается выселение (Eviction), и поды пересоздаются контроллерами на других серверах.

---

### Отказоустойчивость рабочих нагрузок (Workloads HA)

Отказоустойчивость прикладного слоя требует согласованной настройки контроллеров, планировщика, сетевого стека и хранилища.

#### 1. Контроллеры репликации (Stateless vs Stateful)

*   **Stateless (Deployment / ReplicaSet)**: Экземпляры взаимозаменяемы. При падении узла контроллер не дожидается гарантированной остановки старого пода и сразу инициирует создание нового экземпляра на здоровом узле.
*   **Stateful (StatefulSet)**: Экземпляры имеют уникальную сетевую идентичность и персональные PersistentVolumeClaim (RWO). При недоступности узла Kubernetes **не имеет права** автоматически пересоздавать под StatefulSet на другом сервере без подтверждения изоляции старого узла, иначе два экземпляра одновременно обратятся к одному и тому же разделу диска (Split-Brain на уровне хранилища, ведущий к порче данных).

#### 2. Пробы наблюдаемости (Probes)

Корректная конфигурация проб предотвращает каскадные сбои и ложные перезапуски:

| Проба | Назначение | Реакция на ошибку | Типичная ошибка проектирования |
| :--- | :--- | :--- | :--- |
| **`startupProbe`** | Защита медленно стартующих сервисов | Повторные проверки до достижения `failureThreshold`, затем убийство | Отсутствие пробы, из-за чего агрессивная `livenessProbe` убивает под во время прогрева кэшей или миграции БД |
| **`livenessProbe`** | Детектирование зависаний процесса (deadlock) | Перезапуск контейнера через Container Runtime | Проверка внешней зависимости (например, доступности БД). При падении БД ляжет весь пул подов приложения |
| **`readinessProbe`** | Проверка готовности обрабатывать клиентский трафик | Исключение IP пода из `EndpointSlice` сервиса (под не убивается) | Слишком агрессивный таймаут, вызывающий отключение трафика при кратковременном всплеске CPU |

#### 3. Управление доменами отказа (Scheduling & Spread)

Чтобы реплики одного приложения не оказались на одном физическом сервере или в одной стойке, применяются три взаимодополняющих инструмента:

1.  **`podAntiAffinity`**: Запрещает запуск подов с одинаковыми метками на одном хосте.
2.  **`topologySpreadConstraints` (GA v1.24+)**: Обеспечивает равномерное распределение реплик по физическим доменам (стойкам, серверам, датацентрам).
3.  **`PodDisruptionBudget` (PDB)**: Защищает сервис от превышения порога недоступности при административных действиях.

**Эталонная конфигурация распределения по физическим стойкам с PDB:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-api
  namespace: prod
  labels:
    app: billing-api
spec:
  replicas: 4
  selector:
    matchLabels:
      app: billing-api
  template:
    metadata:
      labels:
        app: billing-api
    spec:
      topologySpreadConstraints:
      # Равномерное распределение по серверным стойкам (Bare-Metal Rack)
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/rack
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: billing-api
      # Равномерное распределение по отдельным серверам внутри стоек
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: billing-api
      containers:
      - name: app
        image: internal-registry.corp/apps/billing:v2.4.1
        resources:
          limits:
            cpu: "2"
            memory: 2Gi
          requests:
            cpu: "1"
            memory: 2Gi
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /livez
            port: 8080
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: billing-api-pdb
  namespace: prod
spec:
  minAvailable: 3
  selector:
    matchLabels:
      app: billing-api
```

*Разбор параметров:*
*   `maxSkew: 1`: Разница в числе подов между самой загруженной и наименее загруженной стойкой не превышает 1.
*   `topology.kubernetes.io/rack`: Пользовательская или системная метка узла, обозначающая номер физической стойки в ЦОД.
*   `minAvailable: 3`: При проведении drain или плановых работ Kubernetes запретит выселение более чем одной реплики одновременно.

#### 4. Изоляция томов при аварии: NodeOutOfServiceVolumeDetach

При аппаратном сбое узла (зависание ОС, сбой питания без отправки graceful shutdown) контроллер CSI не может связаться с `kubelet` мертвого узла. В результате операции безопасного отмонтирования (`VolumeDetach`) блокируются.

Начиная с Kubernetes 1.28 (GA), встроен механизм **`NodeOutOfServiceVolumeDetach`**:
Администратор, подтвердив физическую гибель сервера, накладывает таинт `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`. Контроллер CSI принудительно отсоединяет том от упавшего сервера и переносит под StatefulSet на рабочий узел, предотвращая многочасовой простой базы данных.

---

## Практические сценарии

### Сценарий 1: Аварийный сбой рабочего узла с RWO-томами (Safe Volume Detach)

**Контекст:** Сервер `worker-3` с запущенным подом СУБД (StatefulSet `db-0` с томом RWO) внезапно завис на уровне ядра. Узел перешел в статус `NotReady`. Pod завис в состоянии `Terminating`, а новый под на `worker-4` не может запуститься из-за ошибки `Multi-Attach error for volume`.

```bash
# 1. Проверка состояния узлов и подов
kubectl get node worker-3
# → NAME       STATUS     ROLES    AGE   VERSION
# → worker-3   NotReady   <none>   90d   v1.31.2

kubectl get pod db-0 -o wide
# → NAME   READY   STATUS        RESTARTS   AGE   NODE
# → db-0   1/1     Terminating   0          12d   worker-3

# 2. Проверка блокировки тома в событиях
kubectl describe pod db-0 | grep -A 3 -i "FailedAttachVolume"
# → Warning  FailedAttachVolume  2m  attachdetach-controller  
# → Multi-Attach error for volume "pvc-78a1b2c3" Volume is already exclusively attached to one node and can't be attached to another

# 3. ФИЗИЧЕСКИЙ FENCING: убедитесь через IPMI/iLO/BMC, что сервер действительно выключен!
ipmitool -H 192.168.10.33 -U admin -P secret power status
# → Chassis Power is off

# 4. Наложение таинта out-of-service для принудительного освобождения тома
kubectl taint nodes worker-3 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
# → node/worker-3 tainted

# 5. Проверка автоматического пересоздания пода на новом узле
kubectl get pod db-0 -o wide -w
# → db-0   0/1   Pending       0   5s    worker-4
# → db-0   0/1   Init:0/1      0   12s   worker-4
# → db-0   1/1   Running       0   25s   worker-4

# 6. После аппаратного ремонта и включения сервера — обязательно удалите таинт
kubectl taint nodes worker-3 node.kubernetes.io/out-of-service:NoExecute-
# → node/worker-3 untainted
```

Подробный разбор механизма таинтов и выселения — в **[Taints, Tolerations и эвикция](../../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md)**.

---

### Сценарий 2: Плановое обслуживание рабочего узла (Cordon и Drain)

**Контекст:** Требуется обновить версию ядра Linux и пакеты среды выполнения `containerd` на физическом сервере `worker-1` без прерывания обслуживания пользователей.

```bash
# 1. Изоляция узла (запрет размещения новых подов)
kubectl cordon worker-1
# → node/worker-1 cordoned

kubectl get node worker-1
# → NAME       STATUS                     ROLES    AGE   VERSION
# → worker-1   Ready,SchedulingDisabled   <none>   45d   v1.31.2

# 2. Проверка активных PDB перед выселением (убедиться, что есть запас)
kubectl get pdb -A
# → NAMESPACE   NAME             MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → prod        billing-api-pdb  3               N/A               1                     15d

# 3. Выселение рабочих нагрузок с сохранением системных демонов
kubectl drain worker-1 \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --timeout=300s
# → evicting pod prod/billing-api-79b8f6c4d-xk9p2
# → evicting pod prod/auth-svc-65d89f78b-m2z4l
# → pod "billing-api-79b8f6c4d-xk9p2" evicted
# → node/worker-1 drained successfully

# 4. Выполнение административных работ на сервере (SSH)
# ... перезагрузка узла, обновление ядра ...

# 5. Возврат узла в пул планировщика после подтверждения готовности
kubectl uncordon worker-1
# → node/worker-1 uncordoned

kubectl get node worker-1
# → NAME       STATUS   ROLES    AGE   VERSION
# → worker-1   Ready    <none>   45d   v1.31.2
```

Регламент безопасного вывода узлов детально описан в **[Обслуживании узлов (Cordon/Drain)](../Operations/node_maintenance.md)**.

---

### Сценарий 3: Аварийный отказ одного узла Control Plane (3-узловой кластер)

**Контекст:** В кластере из 3 мастер-узлов (`cp-1`, `cp-2`, `cp-3`) физический сервер `cp-1`, владевший в данный момент виртуальным IP (`192.168.10.100`), внезапно отключился по питанию.

```bash
# 1. Проверка доступности API через Control Plane Endpoint
curl -k -s https://192.168.10.100:6443/readyz
# → ok

# 2. Проверка миграции VIP на резервный мастер (например, на cp-2)
ssh admin@192.168.10.12 "ip -brief addr show | grep 192.168.10.100"
# → eth0   UP   192.168.10.100/24

# 3. Проверка статуса узлов кластера
kubectl get nodes -l node-role.kubernetes.io/control-plane
# → NAME   STATUS     ROLES           AGE   VERSION
# → cp-1   NotReady   control-plane   60d   v1.31.2
# → cp-2   Ready      control-plane   60d   v1.31.2
# → cp-3   Ready      control-plane   60d   v1.31.2

# 4. Проверка здоровья кворума etcd с выжившего узла cp-2
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health -w table
# → +------------------------+--------+-------------+-------+
# → |        ENDPOINT        | HEALTH |    TOOK     | ERROR |
# → +------------------------+--------+-------------+-------+
# → | https://127.0.0.1:2379 |   true | 11.234123ms |       |
# → +------------------------+--------+-------------+-------+

# 5. Проверка перехвата лидерства компонентов Control Plane
kubectl get lease -n kube-system kube-controller-manager kube-scheduler
# → NAME                      HOLDER   AGE
# → kube-controller-manager   cp-2     60d
# → kube-scheduler            cp-2     60d
```

Кластер сохранил полную работоспособность: кворум etcd составляет 2 из 3, Keepalived/kube-vip перевел трафик на `cp-2`, а резервные экземпляры контроллеров перехватили Lease.

---

### Сценарий 4: Катастрофический сбой — потеря кворума etcd (2 узла из 3 потеряны)

**Контекст:** Авария в электропитании стойки уничтожила серверы `cp-2` и `cp-3`. Выжил только `cp-1`. Кворум etcd потерян (1 < 2). Кластер перешел в аварийный режим **Read-Only**: `kubectl get` частично читает из локального кэша API-сервера, любые операции создания или изменения завершаются ошибкой `etcdserver: no leader`.

#### Поведение компонентов при потере кворума

| Компонент | Состояние | Последствия для инфраструктуры |
| :--- | :--- | :--- |
| **`etcd`** | **Read-Only / No Leader** | Raft-протокол не может выбрать лидера и отклоняет все записи |
| **`kube-apiserver`** | **Read-Only** | `GET/LIST` частично доступны; запросы `POST/PUT/PATCH/DELETE` падают с ошибкой `InternalError` |
| **`kube-scheduler`** | **Standby** | Потерял Lease — новые поды не назначаются на узлы и зависают в статусе `Pending` |
| **`kube-controller-manager`**| **Standby** | Потерял Lease — реплики не масштабируются, упавшие поды не пересоздаются |
| **`Data Plane (Workers)`** | **Автономная работа** | Существующие контейнеры продолжают работу и пропускают клиентский трафик |

#### Алгоритм восстановления кластера из снапшота на выжившем узле

```bash
# На выжившем мастере (cp-1: 192.168.10.11):

# 1. Временная изоляция локальных управляющих манифестов (остановка API и etcd)
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
sudo mv /etc/kubernetes/manifests/etcd.yaml /tmp/

# Ожидание остановки контейнеров kubelet'ом (проверка через crictl)
sudo crictl ps --name "kube-apiserver|etcd"
# → вывод должен быть пустым

# 2. Создание резервной копии старой поврежденной базы
sudo cp -r /var/lib/etcd /var/lib/etcd-corrupted-backup

# 3. Восстановление etcd из актуального ночного снапшота в новый кластер из 1 узла
sudo ETCDCTL_API=3 etcdctl snapshot restore /var/backups/etcd-snapshot-latest.db \
  --data-dir=/var/lib/etcd-restored \
  --name=cp-1 \
  --initial-cluster="cp-1=https://192.168.10.11:2380" \
  --initial-cluster-token="k8s-recovery-cluster" \
  --initial-advertise-peer-urls="https://192.168.10.11:2380"
# → 2026-10-17 21:30:00.123456 I | etcdserver: restored snapshot to /var/lib/etcd-restored

# 4. Замена рабочей директории базы etcd
sudo rm -rf /var/lib/etcd
sudo mv /var/lib/etcd-restored /var/lib/etcd
sudo chown -R root:root /var/lib/etcd

# 5. Возврат манифестов статических подов
sudo mv /tmp/etcd.yaml /etc/kubernetes/manifests/
sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/

# 6. Ожидание запуска и проверка локального здоровья etcd
sleep 15
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
# → ENDPOINT               ID                 VERSION   DB SIZE   IS LEADER   RAFT TERM
# → https://127.0.0.1:2379 8e9a3b4c5d6e7f8a   3.5.15    42 MB     true        2

# 7. Проверка восстановления функциональности API
kubectl get nodes
# → NAME       STATUS     ROLES           AGE   VERSION
# → cp-1       Ready      control-plane   60d   v1.31.2
# → cp-2       NotReady   control-plane   60d   v1.31.2
# → cp-3       NotReady   control-plane   60d   v1.31.2

# 8. После ввода в строй новых физических серверов взамен сгоревших:
#    удалите старые записи из etcd: etcdctl member remove <id>
#    и подключите новые узлы через kubeadm join --control-plane
```

Аварийное восстановление и нюансы флага `--force-new-cluster` подробно описаны в **[Аварийном восстановлении etcd](../../etcd/emergency_recovery.md)**.

---

### Сценарий 5: Валидация отказоустойчивости (Chaos Engineering / GameDay на On-Premise)

Регулярная валидация отказоустойчивости позволяет подтвердить расчетные значения RTO и исключить скрытые дефекты конфигурации.

```bash
# ТЕСТ 1: Имитация падения физического сетевого интерфейса с VIP (Keepalived Failover)
# На активном узле-мастере:
sudo ip link set dev eth0 down

# Наблюдение со стороны клиента (непрерывный опрос API):
while true; do
  curl -k -s -o /dev/null -w "%{http_code} (%{time_total}s)\n" https://192.168.10.100:6443/readyz
  sleep 0.2
done
# → 200 (0.005s)
# → 200 (0.004s)
# → 000 (0.412s)   ← момент переключения VRRP и отправки Gratuitous ARP
# → 200 (0.006s)   ← трафик успешно подхвачен вторым узлом
# Вывод: Перерыв обслуживания составил менее 500 мс, TCP-сессии восстановлены.

# Восстановление интерфейса
sudo ip link set dev eth0 up

# ТЕСТ 2: Аварийная остановка активного лидера etcd (Raft Election)
# Определение текущего лидера etcd:
LEADER_ID=$(sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w json | jq -r '.[0].Status.leader')

# Жесткий kill процесса etcd на узле-лидере:
sudo kill -9 $(pgrep etcd)

# Проверка времени выбора нового лидера в оставшихся узлах:
sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
# → Новый лидер выбран за время < 1.5 с (стандартный Raft Election Timeout).
```

---

### Сценарий 6: Мультидатацентровая отказоустойчивость (On-Premise Multi-DC HA)

При проектировании катастрофоустойчивой инфраструктуры на базе двух и более удаленных серверных площадок (ЦОД-1 и ЦОД-2) организация единого растянутого кластера (Stretched Cluster) сопряжена с высокими рисками: если сетевая задержка между датацентрами превышает 10 мс или возникают сетевые потери, etcd теряет консенсус.

**Рекомендуемый корпоративный паттерн: Независимые кластеры + Межкластерная связность (ClusterMesh / GSLB)**:

```text
       ┌────────────────────────┐
       │     GSLB (DNS Anycast) │
       │ (PowerDNS / Keepalived)│
       └───────────┬────────────┘
                   │ Запросы клиентов
          ┌────────┴────────┐
          ▼                 ▼
   ┌─────────────┐   ┌─────────────┐
   │    ЦОД 1    │   │    ЦОД 2    │
   │  Кластер A  │   │  Кластер B  │
   │  (3 Master) │   │  (3 Master) │
   └──────┬──────┘   └──────┬──────┘
          │                 │
          └─ Cilium Mesh ───┘
            (WireGuard/IPSec)
```

1.  **Катастрофоустойчивость Control Plane**: В каждом датацентре развернут свой независимый 3-узловой Control Plane. Падение связи между ЦОД не влияет на кворум и управляемость каждого кластера локально.
2.  **Глобальная балансировка (GSLB)**: Внешние DNS-серверы (PowerDNS / BIND с модулями GeoDNS / HealthCheck) контролируют доступность внешних точек входа и направляют трафик на живой ЦОД.
3.  **Сетевая связность Data Plane**: Сетевой плагин CNI (например, Cilium ClusterMesh) объединяет пространство IP-адресов подов двух кластеров через защищенный туннель, позволяя реплицировать данные баз (PostgreSQL Patroni / Cassandra) без публикации портов наружу.

---

## Операции и команды

Сводная таблица регламентных команд оперативной проверки высокой доступности для дежурного инженера и SRE:

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка доступности API через VIP** | `curl -k -s https://<VIP>:6443/readyz?verbose` | Вывод `[+]readyz check passed` для всех проверок |
| **Проверка внутреннего здоровья API** | `kubectl get --raw='/livez?verbose'` | Ответ `[+]livez check passed`, отсутствие исключений |
| **Проверка статуса кворума etcd** | `etcdctl endpoint health -w table` | Статус `HEALTH: true` для всех доступных узлов |
| **Проверка ревизий и лидера etcd** | `etcdctl endpoint status -w table` | Единственный лидер (`IS LEADER: true`), расхождение `RAFT APPLIED INDEX` не превышает сотен единиц |
| **Аудит Lease-лидеров компонентов** | `kubectl get lease -n kube-system` | Заполненные поля `HOLDER`, возраст обновления (`AGE`) соответствует текущему времени |
| **Проверка состояния PDB в кластере** | `kubectl get pdb -A` | `ALLOWED DISRUPTIONS >= 1` для всех критичных приложений |
| **Поиск узлов в статусе NotReady** | `kubectl get nodes -o wide \| grep -v "Ready"` | Только заголовок (отсутствие нездоровых узлов) |
| **Поиск сбойных подов в кластере** | `kubectl get pods -A \| grep -Ev "Running\|Completed"` | Отсутствие подов в состояниях `CrashLoopBackOff`, `Pending`, `Terminating` |
| **Создание снапшота etcd** | `etcdctl snapshot save /var/backups/etcd-$(date +%s).db` | `Snapshot saved at ...` |
| **Проверка срока сертификатов Control Plane** | `kubeadm certs check-expiration` | Остаточный срок действия сертификатов > 30 дней |

---

### Метрики и алертинг высокой доступности (Prometheus)

Отказоустойчивость требует проактивного оповещения до того, как сбой привел к отказу сервиса:

```yaml
groups:
- name: kubernetes-high-availability
  rules:
  # 1. Потеря лидера etcd — критический алерт (кворум нарушен или идет split-brain)
  - alert: EtcdNoLeader
    expr: etcd_server_has_leader == 0
    for: 30s
    labels:
      severity: disaster
    annotations:
      summary: "Критический сбой: в etcd отсутствует лидер"
      description: "Raft-кворум нарушен. Кластер перешел в режим Read-Only. Немедленно проверьте доступность узлов Control Plane."

  # 2. Высокая задержка записи WAL на диск etcd (предвестник потери консенсуса)
  - alert: EtcdHighFsyncDuration
    expr: histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.01
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Высокая задержка fsync в etcd на узле {{ $labels.instance }}"
      description: "99-й перцентиль задержки fsync превышает 10 мс. Риск выпадения узла из кворума из-за медленного диска."

  # 3. Узел Control Plane недоступен
  - alert: ControlPlaneNodeNotReady
    expr: kube_node_status_condition{condition="Ready",status="true",node=~".*master.*|.*cp.*"} == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Мастер-узел {{ $labels.node }} не готов"
      description: "Один из управляющих серверов недоступен. Избыточность кворума снижена."

  # 4. Нарушение бюджета прерываний (PDB exhausted)
  - alert: PodDisruptionBudgetAtRisk
    expr: kube_poddisruptionbudget_status_pod_disruptions_allowed == 0
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "PDB {{ $labels.poddisruptionbudget }} в пространстве {{ $labels.namespace }} не допускает прерываний"
      description: "Плановые работы (drain узлов) для данного сервиса заблокированы из-за нехватки здоровых реплик."
```

Архитектура системы мониторинга детально раскрыта в **[Архитектуре мониторинга и логирования](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md)**.

---

## Диагностика и устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`kubectl` зависает, ошибки `etcdserver: no leader`** | Потерян кворум etcd (упало большинство мастеров или деградация сети) | `etcdctl endpoint health -w table`; пинг между мастерами | Поднять упавшие серверы etcd. Если серверы утеряны безвозвратно — восстановить кластер из снапшота (Сценарий 4). |
| **Pod StatefulSet завис в `ContainerCreating` (`Multi-Attach error`)** | Старый узел завис без graceful shutdown; том RWO заблокирован контроллером CSI | `kubectl describe pod <name>`: предупреждение `Volume is already exclusively attached` | Убедиться через IPMI, что старый сервер выключен, затем наложить таинт `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` (Сценарий 1). |
| **`kubectl drain` блокируется и падает по таймауту** | Защита PDB (`ALLOWED DISRUPTIONS: 0`) или наличие подов с локальным хранилищем `emptyDir` | `kubectl get pdb -A`; анализ блокирующего пода в выводе команды `drain` | Увеличить число реплик Deployment, использовать флаг `--delete-emptydir-data`. Если под завис в `Terminating` — расследовать причину до принудительного удаления. |
| **Мерцание / Flapping виртуального IP (VIP)** | Конфликт VRRP Router ID в L2-домене или блокировка multicast/unicast пакетов межсетевым экраном | Логи `journalctl -u keepalived -f`; `tcpdump -nn -i eth0 vrrp` | Установить уникальный `virtual_router_id` в `keepalived.conf`; включить режим `nopreempt`; настроить unicast-пиринг. |
| **API-сервер возвращает `HTTP 429 Too Many Requests`** | Срабатывание механизма API Priority and Fairness (APF) из-за всплеска запросов | Проверить метрику `apiserver_flow_control_rejected_requests_total` | Найти источник неконтролируемых запросов (зациклившийся оператор или скрипт CI/CD); перенастроить лимиты в `FlowSchema`. |
| **Частые перевыборы Raft-лидера etcd** | Высокая задержка записи на диск (`fsync > 10ms`) или потеря пакетов между мастерами | Метрика `etcd_disk_wal_fsync_duration_seconds`; утилита `fio` для теста диска | Перенести каталог `/var/lib/etcd` на выделенный накопитель NVMe; настроить приоритеты дискового I/O через ionice. |
| **Рассинхронизация времени узлов (Clock Drift)** | Отказ службы `systemd-timesyncd` / `chrony` | `timedatectl status`; расхождение времени > 500 мс | Восстановить синхронизацию NTP; расхождение времени свыше 1 с разрушает mTLS-аутентификацию и Lease-таймауты. |

Диагностика проблем синхронизации времени подробно разобрана в **[Синхронизации времени и доступности узлов](../../Troubleshooting/Common_Errors/NodeUnavailability/time_sync.md)**.

---

## Рекомендации (Best Practices)

1.  **Строго нечетное количество узлов Control Plane (3 или 5)**:
    *   Для большинства промышленных кластеров оптимально **3 узла**.
    *   Для особо критичных инфраструктур — **5 узлов** (допускается отказ 2 серверов).
    *   Никогда не используйте четное число узлов (4 или 6) — это не добавляет отказоустойчивости, но увеличивает вероятность раскола кворума. Не создавайте кластеры etcd более чем из 5 узлов: накладные расходы на сетевой консенсус Raft снижают общую производительность API.
2.  **Выделенные скоростные накопители NVMe для etcd**:
    *   Каталог `/var/lib/etcd` должен размещаться на физическом NVMe/SSD с гарантированным latency `fsync < 10ms` (рекомендуется < 2 мс).
    *   Категорически запрещено размещать `etcd` на медленных SATA HDD, сетевых файловых системах NFS или общих с тяжелыми рабочими нагрузками дисках.
3.  **Отказоустойчивая точка входа API без единой точки отказа**:
    *   Никогда не направляйте `kubelet` и агентов на IP-адрес одного конкретного мастера.
    *   Используйте Keepalived в связке с HAProxy (обязательно с параметрами `nopreempt` и `unicast`) либо `kube-vip` с BGP Anycast на физические коммутаторы.
4.  **Обязательное проектирование прикладного слоя под HA**:
    *   Все stateless-приложения в production должны иметь минимум **2 (лучше 3) реплики**.
    *   Каждый сервис с числом реплик $\ge 2$ должен сопровождаться манифестом **`PodDisruptionBudget`** (`minAvailable: 1` или `maxUnavailable: 1`).
    *   Используйте **`topologySpreadConstraints`** по меткам `kubernetes.io/hostname` и стойкам (`topology.kubernetes.io/rack`), чтобы поды одного сервиса не концентрировались на одном «железе».
5.  **Корректная настройка Graceful Shutdown и проб**:
    *   Всегда реализуйте обработку сигнала `SIGTERM` в приложении. Задавайте задержку в хуке `preStop: exec: command: ["/bin/sleep", "5"]`, чтобы дать время контроллеру `kube-proxy` исключить IP пода из iptables/IPVS до остановки процесса.
    *   Никогда не проверяйте внешние сетевые сервисы (БД, кэш) внутри `livenessProbe`.
6.  **Настройка таймаутов эвикции под требования бизнеса**:
    *   Стандартный таймаут выселения подов с упавшего узла (5 минут) может быть слишком велик для критичных систем. При необходимости сокращайте его через параметры `tolerationSeconds` для таинтов `not-ready` и `unreachable` в шаблонах подов (например, до 60 секунд), но учитывайте риск «дребезга» при кратковременных сетевых сбоях.
7.  **Регулярное автоматизированное резервное копирование etcd**:
    *   Настройте создание снапшотов etcd через Cron / Systemd-таймер с интервалом от 15 минут до 1 часа.
    *   Копии должны немедленно копироваться на изолированное внешнее хранилище (S3/MinIO/бэкап-сервер), расположенное вне восстанавливаемого кластера.
    *   Минимум раз в квартал проводите практическую отработку сценария Disaster Recovery на тестовом стенде.

---

## Дополнительная информация

### См. также

*   **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)** — теоретические основы HA, модели надежности, кворум и расчет RTO/RPO.
*   **[Архитектура Control Plane](../Concepts/control_plane_architecture.md)** — детальный разбор бинарных компонентов Kubernetes и их взаимодействия.
*   **[etcd — практические операции](../Concepts/etcd_operations.md)** — команды обслуживания, дефрагментация, создание и восстановление снапшотов.
*   **[Аварийное восстановление etcd](../../etcd/emergency_recovery.md)** — глубокий разбор процедур DR, восстановление при повреждении данных и специфика `--force-new-cluster`.
*   **[HA API-сервера с Keepalived и HAProxy](../Installation/kubeadm/ha_concepts.md)** — пошаговая конфигурация L4-балансировки Control Plane на Bare-Metal.
*   **[Проверка отказоустойчивости HA-кластера](../Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)** — методология комплексного тестирования кластера после установки.
*   **[Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md)** — регламент безопасного вывода узлов из эксплуатации.
*   **[Под бюджет прерываний (PDB)](../Autoscaling/pod_disruption_budget.md)** — проектирование политик защиты доступности при плановых работах.
*   **[Taints, Tolerations и эвикция](../../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md)** — механизмы изоляции сбойных узлов и работа с `NodeOutOfServiceVolumeDetach`.
*   **[Синхронизация времени в кластере](../../Troubleshooting/Common_Errors/NodeUnavailability/time_sync.md)** — влияние рассинхронизации NTP на кворум etcd и сертификаты.
