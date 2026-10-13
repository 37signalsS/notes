# Autoscaling в On-Premise / Bare-Metal средах

**Актуально для:** Kubernetes 1.30+ / Cluster API v1.7+ / Metal3 v1.7+

## Определения

**On-Premise (on-prem)** — модель развёртывания инфраструктуры в собственном дата-центре организации (на физических серверах или локальных платформах виртуализации), без привлечения публичных облачных провайдеров.

**Bare-Metal** — физические серверы без слоя гипервизора. Обеспечивают максимальную производительность без накладных расходов на виртуализацию, но требуют прямого управления жизненным циклом через протоколы Out-of-Band (BMC/IPMI/Redfish) и сетевую загрузку (PXE/iPXE).

**Cluster API (CAPI)** — проект Kubernetes SIG Cluster Lifecycle, предоставляющий декларативные API и инструментарий для автоматизации создания, настройки и обновления кластеров Kubernetes. Для взаимодействия с физической и виртуальной локальной инфраструктурой использует специализированные провайдеры: Metal3 (CAPM3), VMware vSphere (CAPV), OpenStack (CAPO), KubeVirt (CAPK).

**Metal3 (Cluster API Provider Metal3, CAPM3)** — реализация Cluster API для управления физическими bare-metal серверами. Работает в связке с OpenStack Ironic для низкоуровневого управления питанием, инвентаризации аппаратного обеспечения и прошивки ОС.

**OpenStack Ironic** — сервис подготовки и управления физическими машинами (bare-metal provisioning). Выполняет обнаружение оборудования (hardware inspection), настройку RAID/BIOS, очистку дисков (disk cleaning/wiping) и сетевую установку образов операционных систем.

**Headroom (Overprovisioning Buffer)** — архитектурный паттерн поддержания «тёплого» запаса вычислительных мощностей в кластере с помощью низкоприоритетных спящих подов (`PriorityClass` с отрицательным приоритетом). Позволяет рабочим нагрузкам масштабироваться мгновенно за счёт вытеснения буферных подов, пока физический узел проходит длительную процедуру аппаратной загрузки.

**Volcano** — специализированная система пакетного планирования (batch scheduler) для Kubernetes. Предоставляет механизмы All-or-Nothing (gang scheduling), иерархические очереди с контролем квот, механизм возврата ресурсов (reclamation) и fair-share планирование в условиях фиксированной емкости локального дата-центра.

---

## Архитектура и ключевые концепции

### Специфика автомасштабирования в частном ЦОД

В отличие от сред с неограниченным внешним пулом ресурсов, автомасштабирование в On-Premise средах подчиняется жестким физическим ограничениям:

| Параметр | Виртуализация (vSphere / KVM) | Физический Bare-Metal |
|---|---|---|
| **Источник ресурсов** | Пул виртуальных машин на гипервизорах | Физические серверы в стойках |
| **Время ввода узла в строй** | 1–4 минуты (клонирование шаблона VM) | 8–25 минут (POST, инициализация BMC, PXE/iPXE, запись образа на диск) |
| **Управление питанием/загрузкой** | Hypervisor API (vCenter, Proxmox API) | Out-of-Band BMC (IPMI 2.0, Redfish API, Virtual Media) |
| **Фиксированность конфигураций** | Гибкое изменение vCPU/vRAM | Фиксированные аппаратные профили (CPU, RAM, дисковые корзины) |
| **Сетевая связность** | Виртуальные коммутаторы, порт-группы | Физические коммутаторы ToR, статические VLAN, BGP unnumbered |
| **Сетевые сервисы (L4 LB)** | Встроенные балансировщики / NSX | MetalLB (BGP/L2), kube-vip, Cilium BGP Control Plane |
| **Хранилище (CSI)** | vSphere CNS, Ceph RBD, NFS | Ceph RBD/CephFS, Longhorn, Local PV (LVM/OpenEBS) |

### Сквозная архитектура автомасштабирования

Автомасштабирование в On-Premise объединяет три уровня: масштабирование рабочих нагрузок (Workload), буферизацию емкости (Headroom) и декларативное управление физическими/виртуальными машинами (Infrastructure).

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Workload Layer                       │
│                                                                        │
│   ┌───────────────┐     ┌───────────────┐     ┌───────────────────┐    │
│   │   HPA / VPA   │     │     KEDA      │     │  Volcano Queues   │    │
│   │  (CPU/Memory) │     │ (Queue/Kafka) │     │  (Batch / Jobs)   │    │
│   └───────┬───────┘     └───────┬───────┘     └─────────┬─────────┘    │
│           │                     │                       │              │
│           ▼                     ▼                       ▼              │
│   ┌───────────────────────────────────────────────────────────────┐    │
│   │               Pending Pods (Workload Scaling)                 │    │
│   └───────────────────────────────┬───────────────────────────────┘    │
└───────────────────────────────────┼────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    │                               │                               │
    ▼ (Есть свободный Headroom)     ▼ (Headroom исчерпан)           │
┌───────────────────────────┐   ┌───────────────────────────────┐   │
│   Priority Preemption     │   │      Cluster Autoscaler       │   │
│   (Вытеснение pause-подов)│   │       (CAPI Provider)         │   │
│   Мгновенный запуск: <1c  │   └───────────────┬───────────────┘   │
└───────────────────────────┘                   │                   │
                                                ▼                   │
                                ┌───────────────────────────────┐   │
                                │    Cluster API (CAPI) Core    │   │
                                │   MachineDeployment Scale     │   │
                                └───────────────┬───────────────┘   │
                                                │                   │
                                ┌───────────────┴───────────────┐   │
                                │                               │   │
                                ▼                               ▼   │
                ┌───────────────────────────────┐ ┌─────────────────┴───┐
                │   CAPM3 (Metal3 Provider)     │ │   CAPV / CAPO / CAPP│
                │   + BareMetalOperator (BMO)   │ │ (vSphere / OpenStack│
                └───────────────┬───────────────┘ │    / Proxmox)       │
                                │                 └─────────────────────┘
                                ▼
                ┌───────────────────────────────┐
                │       OpenStack Ironic        │
                │  (DHCP/TFTP, PXE/iPXE, IPMI)  │
                └───────────────┬───────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │     Physical Server (BMC)     │
                │  Power ON -> PXE -> OS Flash  │
                └───────────────────────────────┘
```

### Сравнение механизмов автомасштабирования в On-Premise

| Решение | Уровень | Целевая среда | Задержка реакции | Сложность внедрения |
|---|---|---|---|---|
| **Headroom Buffer (PriorityClass)** | Workload / Capacity | Любая (Bare-Metal / VM) | Мгновенно (<1 сек) | Низкая |
| **Cluster Autoscaler + CAPI (CAPV/CAPO)** | Инфраструктура (VM) | VMware vSphere, OpenStack | 2–5 минут | Средняя |
| **Cluster Autoscaler + Metal3 (CAPM3)** | Инфраструктура (Hardware) | Физические серверы | 10–25 минут | Высокая |
| **Volcano Scheduler** | Workload (Batch/ETL) | Любая | Милисекунды (на уровне очередей) | Средняя |
| **Descheduler** | Дефрагментация | Любая | 1–3 минуты (цикл аудита) | Низкая |

### Cluster Autoscaler с провайдером Cluster API

Cluster Autoscaler (CA) не взаимодействует с физическим оборудованием напрямую. Вместо этого он обращается к контроллерам Cluster API, управляя количеством реплик в объектах `MachineDeployment` или `MachineSet`:

1. **Детекция дефицита:** Планировщик `kube-scheduler` переводит под в состояние `Pending` из-за невозможности удовлетворить `resources.requests`, селекторы `nodeSelector`, правила `affinity` или `taints`.
2. **Симуляция размещения:** CA моделирует создание узла на основе шаблона `MachineDeployment` (анализирует параметры емкости, метки и taints будущего узла).
3. **Запрос на расширение:** CA инкрементирует поле `spec.replicas` в соответствующем ресурсе `MachineDeployment`.
4. **Реализация провайдером:** Контроллер инфраструктурного провайдера (CAPM3 для bare-metal или CAPV для vSphere) создает инфраструктурный ресурс (`Metal3Machine` / `VSphereMachine`), запускает виртуальную машину или передает команду Ironic на загрузку сервера.
5. **Инициализация узла:** Узел загружает ОС, инициализирует `kubelet` через cloud-init/ignition, регистрируется в API-сервере и переходит в статус `Ready`.
6. **Размещение нагрузки:** `kube-scheduler` размещает ожидающие поды на новом узле.

### Volcano для batch-нагрузок

В средах с фиксированным пулом физических серверов добавление новых узлов не всегда возможно или экономически оправдано. Для пакетных задач (обработка логов, ETL-пайплайны, аналитические расчеты, генерация отчетов) стандартный `kube-scheduler` создает риск деградации:
- **Deadlock при частичном запуске:** Если распределенной задаче из 10 воркеров выделилось только 6 узлов, она блокирует ресурсы и не может завершить обработку данных, удерживая мощности от других задач.
- **Отсутствие приоритизации очередей:** Очередь регламентных фоновых задач может занять весь кластер и заблокировать критичный инцидентный анализ.

Volcano решает эту проблему без изменения физического пула узлов:
- **Gang Scheduling:** Запуск всей группы подов («все или ничего») через параметр `minAvailable`.
- **Queues & Reclamation:** Организация очередей с весами и возможность вытеснения низкоприоритетных пакетов при поступлении критичных заданий.
- **Fair-Share:** Пропорциональное разделение фиксированной аппаратной емкости между командами и проектами.

---

## Практические сценарии и конфигурация

### Сценарий 1: Развертывание Cluster Autoscaler с поддержкой Cluster API

При развертывании в On-Premise инфраструктуре Cluster Autoscaler настраивается на работу с провайдером `clusterapi`. CA отслеживает `MachineDeployment` в пространстве имен управления.

#### 1. Deployment для Cluster Autoscaler

```yaml
# cluster-autoscaler-capi.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app.kubernetes.io/name: cluster-autoscaler
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: cluster-autoscaler
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cluster-autoscaler
    spec:
      serviceAccountName: cluster-autoscaler
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      nodeSelector:
        node-role.kubernetes.io/control-plane: ""
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.31.0
          imagePullPolicy: IfNotPresent
          command:
            - ./cluster-autoscaler
            - --cloud-provider=clusterapi
            - --v=4
            - --expander=least-waste
            - --balance-similar-node-groups=true
            - --scale-down-delay-after-add=10m
            - --scale-down-unneeded-time=15m
            - --max-node-provision-time=25m
            - --clusterapi-cloud-config-authoritative=true
          resources:
            requests:
              cpu: 100m
              memory: 300Mi
            limits:
              cpu: 500m
              memory: 1Gi
```

#### 2. Аннотирование MachineDeployment для автоматического обнаружения

Для автоматического обнаружения пулов узлов Cluster Autoscaler использует аннотации минимального и максимального количества реплик:

```bash
# Разрешить автоскейлеру управлять MachineDeployment worker-pool-dc1 (диапазон от 3 до 10 машин)
kubectl annotate machinedeployment worker-pool-dc1 -n default \
  cluster.x-k8s.io/cluster-api-autoscaler-node-group-min-size="3" \
  cluster.x-k8s.io/cluster-api-autoscaler-node-group-max-size="10" --overwrite
# → machinedeployment.cluster.x-k8s.io/worker-pool-dc1 annotated
```

---

### Сценарий 2: Bare-Metal Provisioning через Metal3 и BareMetalHost

В архитектуре Metal3 каждый физический сервер описывается объектом `BareMetalHost` (BMH).

#### 1. Секрет с учетными данными Out-of-Band BMC (IPMI / Redfish)

```yaml
# bmh-credentials.yaml
apiVersion: v1
kind: Secret
metadata:
  name: srv-r640-01-bmc-creds
  namespace: metal3-system
type: Opaque
stringData:
  username: "ipmi_admin"
  password: "SecureProductionBmcPassword123"
```

#### 2. Манифест BareMetalHost

```yaml
# baremetalhost-srv01.yaml
apiVersion: metal3.io/v1alpha1
kind: BareMetalHost
metadata:
  name: srv-r640-01
  namespace: metal3-system
  labels:
    hardware-type: compute-standard
spec:
  online: true
  bootMode: UEFI
  bootMACAddress: "52:54:00:fa:12:34"
  bmc:
    # Использование защищенного интерфейса Redfish (рекомендуется) или ipmi://
    address: "redfish-virtualmedia://192.168.100.21/redfish/v1/Systems/System.Embedded.1"
    credentialsName: srv-r640-01-bmc-creds
    disableCertificateVerification: true
  image:
    url: "http://192.168.10.10:8080/images/ubuntu-22.04-server-cloudimg-amd64.raw"
    checksum: "http://192.168.10.10:8080/images/ubuntu-22.04-server-cloudimg-amd64.raw.sha256"
    checksumType: sha256
    format: raw
```

Применение манифеста и контроль инвентаризации:

```bash
# Применение манифеста хоста
kubectl apply -f baremetalhost-srv01.yaml
# → baremetalhost.metal3.io/srv-r640-01 created

# Проверка статуса инспекции оборудования и готовности хоста
kubectl get baremetalhost -n metal3-system
# → NAME          STATUS      PROVISIONING STATE   CONSUMER   BMC                         ERROR
# → srv-r640-01   OK          available                       redfish-virtualmedia://...
```

---

### Сценарий 3: Настройка упреждающего буфера (Headroom / Overprovisioning)

Поскольку включение физического сервера и прохождение POST/PXE занимает до 20 минут, прямое ожидание нового узла неприемлемо для SLA критичных сервисов. Для компенсации задержки создается «тёплый» буфер на базе низкоприоритетных спящих контейнеров.

#### 1. Создание PriorityClass с отрицательным приоритетом

```yaml
# headroom-priorityclass.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: headroom-buffer
value: -10
globalDefault: false
description: "Низкоприоритетный резерв емкости (headroom) для мгновенного вытеснения рабочими нагрузками"
```

#### 2. Развертывание буферного пула (Headroom Deployment)

```yaml
# headroom-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: capacity-headroom-buffer
  namespace: kube-system
  labels:
    app.kubernetes.io/name: headroom-buffer
spec:
  replicas: 4
  selector:
    matchLabels:
      app.kubernetes.io/name: headroom-buffer
  template:
    metadata:
      labels:
        app.kubernetes.io/name: headroom-buffer
    spec:
      priorityClassName: headroom-buffer
      terminationGracePeriodSeconds: 0
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.10
          resources:
            requests:
              cpu: "4"
              memory: "16Gi"
            limits:
              cpu: "4"
              memory: "16Gi"
```

#### Проверка механики вытеснения

```bash
# 1. Применение PriorityClass и буфера
kubectl apply -f headroom-priorityclass.yaml
kubectl apply -f headroom-deployment.yaml
# → priorityclass.scheduling.k8s.io/headroom-buffer created
# → deployment.apps/capacity-headroom-buffer created

# 2. Проверка состояния подов буфера
kubectl get pods -n kube-system -l app.kubernetes.io/name: headroom-buffer -o wide
# → NAME                                        READY   STATUS    RESTARTS   AGE   NODE
# → capacity-headroom-buffer-789cf94d8f-1abc    1/1     Running   0          45s   worker-01
# → capacity-headroom-buffer-789cf94d8f-2def    1/1     Running   0          45s   worker-02
# → capacity-headroom-buffer-789cf94d8f-3ghi    1/1     Running   0          45s   worker-03
# → capacity-headroom-buffer-789cf94d8f-4jkl    1/1     Running   0          45s   worker-03

# 3. При масштабировании боевого сервиса kube-scheduler мгновенно вытесняет pause-поды
kubectl scale deployment api-gateway --replicas=8
# → deployment.apps/api-gateway scaled

# 4. События планировщика подтверждают мгновенный Preemption
kubectl get events --field-selector reason=Preempted -n kube-system
# → Normal Preempted pod/capacity-headroom-buffer-789cf94d8f-1abc Preempted by default/api-gateway-695bb84-x9z21
```

Вытесненный под `capacity-headroom-buffer` переходит в состояние `Pending`, что служит триггером для фонового запуска нового физического узла через Cluster Autoscaler без деградации продуктивной нагрузки.

---

### Сценарий 4: Настройка Volcano для пакетной обработки данных

Для очередей пакетной обработки больших объемов данных (пакетный парсинг логов, сжатие архивов, периодическая генерация отчетов) используется связка `Queue` и `Job` контроллера Volcano.

#### 1. Очередь пакетной обработки

```yaml
# volcano-queue.yaml
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata:
  name: analytics-batch-queue
spec:
  weight: 2
  reclaimable: true
  deserved:
    cpu: "32"
    memory: "64Gi"
```

#### 2. Пакетная задача с All-or-Nothing Gang Scheduling

```yaml
# volcano-batch-job.yaml
apiVersion: batch.volcano.sh/v1beta1
kind: Job
metadata:
  name: log-archival-processing
  namespace: default
spec:
  minAvailable: 4
  schedulerName: volcano
  queue: analytics-batch-queue
  policies:
    - event: PodEvicted
      action: RestartJob
  tasks:
    - replicas: 4
      name: log-worker
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: worker
              image: alpine:3.20
              command:
                - /bin/sh
                - -c
                - "echo Processing logs partition... && sleep 120"
              resources:
                requests:
                  cpu: "2"
                  memory: "4Gi"
                limits:
                  cpu: "2"
                  memory: "4Gi"
```

```bash
# Применение очереди и задания Volcano
kubectl apply -f volcano-queue.yaml
kubectl apply -f volcano-batch-job.yaml
# → queue.scheduling.volcano.sh/analytics-batch-queue created
# → job.batch.volcano.sh/log-archival-processing created

# Проверка состояния очереди и запущенных задач
kubectl get queues.scheduling.volcano.sh
# → NAME                    WEIGHT   STATUS   RECLAIMABLE
# → analytics-batch-queue   2        Open     true

kubectl get jobs.batch.volcano.sh -n default
# → NAME                      STATUS    MINAVAILABLE   TOTAL   SLICES   AGE
# → log-archival-processing   Running   4              4       4        15s
```

---

### Сценарий 5: Мониторинг и SRE-алертинг

Мониторинг автомасштабирования в локальном дата-центре требует контроля аппаратного состояния серверов, доступности интерфейсов управления и емкостных лимитов Cluster Autoscaler.

```yaml
# prometheus-rules-onprem-autoscaling.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: onprem-autoscaling-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
    - name: onprem-autoscaling.rules
      rules:
        # Алерт: Зависание физического сервера на этапе провижининга
        - alert: BareMetalHostProvisioningStuck
          expr: |
            (time() - metal3_baremetalhost_provisioning_started_timestamp) > 1500
            and
            metal3_baremetalhost_provisioning_state != "provisioned"
          for: 5m
          labels:
            severity: critical
            team: sre-infra
          annotations:
            summary: "Физический хост {{ $labels.baremetalhost }} завис в провижининге (>25 мин)"
            description: "Хост {{ $labels.baremetalhost }} не может завершить этап загрузки. Проверьте BMC/IPMI, доступность DHCP/TFTP сервера и состояние Ironic conductor."

        # Алерт: Cluster Autoscaler не может добавить узел из-за нехватки свободных машин
        - alert: ClusterAutoscalerScaleUpFailedNoCapacity
          expr: |
            increase(cluster_autoscaler_failed_scale_ups_total{reason="NoSpareHosts"}[10m]) > 0
          for: 3m
          labels:
            severity: critical
            team: sre-infra
          annotations:
            summary: "Cluster Autoscaler не может выполнить Scale-Up: пул физических серверов исчерпан"
            description: "В пространстве имен metal3-system отсутствуют свободные BareMetalHost в статусе available. Требуется выделение аппаратных мощностей в стойках."

        # Алерт: Сбой Out-of-Band управления сервером
        - alert: BareMetalHostBMCUnreachable
          expr: |
            metal3_baremetalhost_power_status{status="error"} == 1
          for: 5m
          labels:
            severity: warning
            team: sysadmins
          annotations:
            summary: "BMC контроллер сервера {{ $labels.baremetalhost }} недоступен"
            description: "Потеряна связь с интерфейсом IPMI/Redfish. Проверьте сетевую связность management VLAN и валидность учетных данных BMC."
```

---

## Эксплуатация и команды

### Управление пулом серверов Metal3 (BareMetalHost)

```bash
# Просмотр списка всех физических хостов и их текущего статуса
kubectl get baremetalhost -n metal3-system -o wide
# → NAME         STATUS   PROVISIONING STATE   CONSUMER               BMC                          BOOTMAC
# → srv-r640-01  OK       provisioned          worker-pool-dc1-7xk2   redfish-virtualmedia://...   52:54:00:fa:12:34
# → srv-r640-02  OK       available                                   redfish-virtualmedia://...   52:54:00:fa:12:35

# Перевод сервера в режим обслуживания (выключение автоматического распределения)
kubectl annotate baremetalhost srv-r640-02 -n metal3-system \
  baremetalhost.metal3.io/paused="true" --overwrite
# → baremetalhost.metal3.io/srv-r640-02 annotated

# Снятие аннотации обслуживания и возврат в пул доступных хостов
kubectl annotate baremetalhost srv-r640-02 -n metal3-system \
  baremetalhost.metal3.io/paused-
# → baremetalhost.metal3.io/srv-r640-02 annotated
```

### Диагностика Cluster Autoscaler

```bash
# Просмотр актуального внутреннего состояния Cluster Autoscaler через ConfigMap
kubectl get configmap cluster-autoscaler-status -n kube-system -o yaml
# → status: |
# →   Cluster-autoscaler status at 2026-10-13 13:40:00:
# →   Cluster-wide:
# →     Health:      Healthy (ready=12 unready=0 kernel-unfit=0)
# →     ScaleUp:     NoActivity
# →     ScaleDown:   NoCandidates

# Просмотр журнатурных сообщений автоскейлера по принятым решениям
kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler --tail=50 | grep -E "ScaleUp|ScaleDown"
# → I1013 13:42:01.123 1 scale_up.go:420] Estimated 1 nodes needed for 3 pending pods
# → I1013 13:42:01.125 1 scale_up.go:530] Final scale-up plan: MachineDeployment worker-pool-dc1 increased from 3 to 4
```

### Ручное удаление или дрейн узла с защитой данных

```bash
# 1. Безопасный перевод узла в режим cordon и эвакуация подов
kubectl cordon worker-pool-dc1-node-03
# → node/worker-pool-dc1-node-03 cordoned

kubectl drain worker-pool-dc1-node-03 \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --grace-period=60
# → node/worker-pool-dc1-node-03 drained

# 2. Вызов выключения через IPMI при необходимости аварийного вмешательства
ipmitool -I lanplus -H 192.168.100.21 -U ipmi_admin -P SecureProductionBmcPassword123 power status
# → Chassis Power is on

ipmitool -I lanplus -H 192.168.100.21 -U ipmi_admin -P SecureProductionBmcPassword123 power soft
# → Chassis Power Control: Soft Shutdown/Power Off
```

---

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Команда диагностики | Метод устранения |
|---|---|---|---|
| **BareMetalHost зависает в `inspecting` / `registering`** | Ошибка авторизации BMC, неверный протокол Redfish/IPMI или изоляция Management сети. | `kubectl describe bmh <name> -n metal3-system`<br>`# → Message: IPMI operation failed: Invalid credentials` | 1. Проверить Secret с паролем BMC.<br>2. Проверить сетевой маршрут от pod Ironic до BMC IP.<br>3. Перезагрузить BMC контроллер по сети (`ipmitool mc reset cold`). |
| **Сбой PXE-загрузки (`PXE-E32: TFTP open timeout`)** | Недоступен TFTP сервер Ironic, некорректный Next-Server в DHCP опциях, MTU mismatch. | `tcpdump -nn -i eth0 port 67 or port 68 or port 69`<br>`# → IP 192.168.10.50.68 > 255.255.255.255.67: BOOTP/DHCP` | 1. Проверить работу службы `ironic-tftp` / `dnsmasq`.<br>2. Проверить трансляцию DHCP Relay (IP Helper) на ToR-коммутаторах.<br>3. Убедиться, что bootMACAddress в манифесте BMH совпадает с реальным MAC активного порта PXE. |
| **CA не инициирует Scale-Up при наличии Pending подов** | Достигнут лимит `max-size` в аннотации `MachineDeployment` или отсутствуют свободные BMH. | `kubectl logs -n kube-system -l app.kubernetes.io/name=cluster-autoscaler \| grep -i "failed to scale"` | 1. Проверить аннотации `cluster.x-k8s.io/cluster-api-autoscaler-node-group-max-size`.<br>2. Проверить наличие `BareMetalHost` в статусе `available` (`kubectl get bmh -n metal3-system`).<br>3. Добавить новые физические серверы в стойку и зарегистрировать BMH. |
| **Узел зависает при Scale-Down (не удаляется)** | Нарушение `PodDisruptionBudget` (PDB) или наличие подов с локальным хранилищем (`emptyDir`, Local PV). | `kubectl describe pdb -A`<br>`kubectl get pods -A --field-selector spec.nodeName=<node>` | 1. Проверить PDB приложений на предмет `Allowed disruptions: 0`.<br>2. Убедиться, что на подах с `emptyDir` выставлена аннотация `cluster-autoscaler.kubernetes.io/safe-to-evict="true"`.<br>3. Не масштабировать автоматически узлы, на которых запущены базы данных с Local Persistent Volumes. |
| **Ironic disk cleaning failure (`Cleaning error: disk wipe failed`)** | Аппаратный сбой диска, включенный аппаратный RAID без JBOD pass-through, зависание контроллера. | `kubectl logs -n metal3-system deployment/metal3-ironic \| grep -i clean`<br>`# → Disk /dev/sda wipe timed out` | 1. Перевести контроллер сервера в режим HBA / IT Mode / JBOD.<br>2. Выполнить проверку SMART дисков через Ironic deploy-ramdisk.<br>3. Заменить дефектный диск в корзине сервера. |
| **BGP Route Flapping при вводе нового узла** | Анонс сетевых маршрутов (Cilium/MetalLB/Calico) начинается до завершения прогрева сети или инициализации CNI. | `journalctl -u kubelet -e \| grep -i cni`<br>`# → CNI network not ready` | 1. Настроить graceful restart для BGP сессий на ToR-коммутаторе.<br>2. Увеличить `node-status-update-frequency` и настроить startup probe для CNI агента. |

---

## Рекомендации и лучшие практики

### SRE-чеклист для On-Premise Autoscaling

1. **Обязательное поддержание пула Warm Standby (Headroom):**
   - Всегда держите в кластере спящий буфер (`PriorityClass` с отрицательным значением) в объеме минимум 15–20% от текущего потребления кластера.
   - Это гарантирует, что пользовательский всплеск нагрузки будет обслужен моментально, а длительный цикл запуска физического узла (10–25 мин) пройдет в фоновом режиме.

2. **Однородность аппаратных пулов (Hardware Homogeneity):**
   - Группируйте серверы в `MachineDeployment` со строго идентичными характеристиками (CPU, RAM, дисковая конфигурация, скорость сетевых карт).
   - Не смешивайте узлы с разным числом сокетов или NUMA-доменов в рамках одной группы автоскейлинга, чтобы алгоритм симуляции Cluster Autoscaler не делал ошибок при расчете bin-packing.

3. **Сетевая изоляция и Out-of-Band безопасность:**
   - Интерфейсы BMC (iLO, iDRAC, IMM) и трафик PXE/TFTP **обязаны** находиться в изолированных VLAN без прямого доступа из пользовательских сегментов.
   - Доступ контроллеров Metal3 к BMC должен осуществляться через выделенный Management сетевой интерфейс.
   - Используйте Redfish API с TLS вместо устаревшего протокола IPMI 2.0 (RMCP+), подверженного атакам перебора хешей.

4. **Защита от каскадного масштабирования (Scale-Down Dampening):**
   - Устанавливайте консервативные параметры задержки удаления узлов: `--scale-down-unneeded-time=15m` и `--scale-down-delay-after-add=10m`.
   - Частые колебания нагрузки («пила») на bare-metal приводят к быстрому износу серверных накопителей и постоянным перезагрузкам оборудования.

5. **Ограничения для Stateful нагрузок и локальных хранилищ:**
   - Узлы, предоставляющие локальные блочные устройства (Local PV, OpenEBS LocalPV, Ceph OSD), **запрещено** включать в пулы автоматического масштабирования.
   - Для таких пулов создавайте статические `MachineDeployment` без аннотаций автоскейлера либо используйте `autoscaling.knative.dev/minScale` и ручное управление жизненным циклом.

---

## Дополнительная информация

### См. также

- [Cluster Autoscaler: Глубокое погружение](cluster_autoscaler_detailed.md) — алгоритмы, симуляция и параметры конфигурации CA
- [Cluster Autoscaler vs Karpenter](cluster_autoscaler_vs_karpenter.md) — архитектурные отличия провайдерных моделей
- [Descheduler](descheduler.md) — дефрагментация и перераспределение подов после масштабирования
- [Обзор концепций автомасштабирования](overview_concepts.md) — базовые принципы и уровни HPA, VPA, CA
- [Решения для планирования нагрузки](../Scheduling/scheduling_solutions_overview.md) — сравнительная матрица планировщиков K8s
- [Apache YuniKorn](../Scheduling/yunikorn.md) — иерархические очереди и управление ресурсами
- [Kueue](../Scheduling/kueue.md) — управление очередями пакетных заданий
- [MetalLB](../Networking/metallb.md) — реализация Service типа LoadBalancer на bare-metal
- [Kubespray: Обзор](../Installation/Kubespray/overview.md) — развертывание базовой инфраструктуры кластера
- [Высокая доступность Kubernetes на Bare-Metal](../Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md) — архитектура отказоустойчивости физического кластера
- [Планирование ёмкости хранилища](../Storage/storage-capacity-planning.md) — capacity planning дискового пространства в частном ЦОД
