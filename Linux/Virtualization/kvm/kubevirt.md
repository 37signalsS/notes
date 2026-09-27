# KubeVirt: KVM в Kubernetes

В данном файле описывается интеграция KVM/QEMU с Kubernetes через KubeVirt — запуск виртуальных машин как нативных ресурсов Kubernetes. Базовые концепции KVM и архитектура гипервизора представлены в [KVM — Обзор и архитектура](./overview.md).

## Определения

**KubeVirt** — оператор Kubernetes, позволяющий запускать виртуальные машины (ВМ) рядом с контейнерами в одном кластере, используя KVM как backend виртуализации. Интегрируется с нативными Kubernetes API (PV, PVC, Service, NetworkPolicy).

**VirtualMachine (VM)** — Custom Resource Definition (CRD) в KubeVirt, описывающий конфигурацию ВМ: CPU, память, диски, сети, профиль загрузки. Является шаблоном для создания VirtualMachineInstance.

**VirtualMachineInstance (VMI)** — запущенный экземпляр ВМ, управляемый kubevirt-controller. Аналог Pod для контейнеров — базовая исполняемая единица.

**VirtualMachineInstanceReplicaSet (VMIRS)** — контроллер, поддерживающий заданное количество идентичных VMI (аналог ReplicaSet для Pod). Используется для horizontal scaling.

**VirtualMachineMigration** — CRD для управления live migration ВМ между нодами кластера без даунтайма.

**CDI (Containerized Data Importer)** — оператор для импорта, клонирования и создания PVC из образов дисков (qcow2, raw, iso). Использует backing image для эффективного provisioning.

**NetworkAttachmentDefinition (NAD)** — CRD из Multus CNI, определяющий дополнительные сети для Pod/VMI. Позволяет подключать ВМ к OVS, SR-IOV или macvtap интерфейсам.

**CNAO (Cluster Network-addons Operator)** — оператор для автоматического развертывания сетевых компонентов в кластере: Multus, OVS-CNI, Linux Bridge, SR-IOV Device Plugin.

## Базовые концепции

### Архитектура KubeVirt

KubeVirt работает как контроллер Kubernetes, управляющий жизненным циклом ВМ через стандартные CRD и оператор.

**Компоненты:**
- **virt-controller:** Watcher ресурсов VMI/VM, создаёт Pod-лончер для каждой ВМ. Управляет scheduling и lifecycle.
- **virt-launcher:** Init-контейнер в Pod, запускающий процесс QEMU. После старта QEMU превращается в main-контейнер. Содержит libvirtd и qemu-guest-agent.
- **virt-handler:** DaemonSet на каждой ноде. Отвечает за on-node операции: создание/удаление domain в libvirt, настройка сети, hotplug ресурсов, управление состоянием (start/stop/pause).
- **virt-api:** API-сервер KubeVirt, обрабатывающий запросы к виртуальным машинам (console, vnc, guestfs).

**Жизненный цикл VMI:**
1. Пользователь создаёт VirtualMachine или VirtualMachineInstance.
2. virt-controller создаёт Pod с virt-launcher.
3. kubelet запускает Pod на выделенной ноде.
4. virt-launcher стартует libvirtd и QEMU.
5. virt-handler мониторит состояние domain и обновляет статус VMI.

### Конфигурация VirtualMachine

VirtualMachine описывает все параметры ВМ в YAML, аналогично Pod для контейнеров.

**Основные секции:**
- `spec.template.spec.domain.cpu` — количество vCPU и модель.
- `spec.template.spec.domain.memory` — объём RAM.
- `spec.template.spec.domain.devices.disks` — список дисков (disk, cdrom, floppy).
- `spec.template.spec.domain.devices.interfaces` — сетевые интерфейсы.
- `spec.template.spec.volumes` — тома (PersistentVolumeClaim, ContainerDisk, DataVolume, CloudInitNoCloud).
- `spec.running` — флаг запуска (true/false).
- `spec.runStrategy` — стратегия запуска (Always, RerunOnFailure, Manual, Halted).

**Пример конфигурации:**
```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: web-server-01
spec:
  running: true
  template:
    spec:
      domain:
        cpu:
          cores: 4
          sockets: 1
          threads: 1
        memory:
          guest: 8Gi
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
            - name: cloudinitdisk
              cloudInitNoCloud:
                userData: |
                  #cloud-config
                  hostname: web-server-01
                  ssh_authorized_keys:
                    - ssh-rsa AAAA...
          interfaces:
            - name: default
              masquerade: {}
      volumes:
        - name: rootdisk
          persistentVolumeClaim:
            claimName: web-server-01-pvc
        - name: cloudinitdisk
          cloudInitNoCloud:
            userDataBase64: <base64-encoded-data>
```

### Сетевые модели в KubeVirt

KubeVirt поддерживает несколько режимов сетевой connectivity, каждый с уникальными характеристиками.

**Режимы подключения:**

| Режим | Описание | Сценарий |
| :--- | :--- | :--- |
| **masquerade** | NAT через iptables/nftables. ВМ доступна только изнутри кластера. | Развитчика, dev/test среды. |
| **bridge** | L2-мост (linux-bridge). ВМ получает IP из Pod-сети. | Интеграция с существующей сетевой инфраструктурой. |
| **slirp** | Программная эмуляция TCP/IP (QEMU userspace). Медленно, но безопасно. | Debug, изолированные тесты. |
| **SR-IOV** | Прямой проброс VF (Virtual Function). Bare-metal производительность. | High-performance networking, NFV. |
| **OVS** | Open vSwitch-мост с VLAN/Geneve тегированием. | Multi-tenant среды, microsegmentation. |
| **Macvtap** | Прямой доступ к физическому интерфейсу. | Простые сценарии без L2-шаринга. |

**Пример подключения к OVS через NAD:**
```yaml
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: ovs-net
  annotations:
    k8s.v1.cni.cncf.io/resourceName: ovs-cni.b.cni.k8s.io
spec:
  config: '{
    "cniVersion": "0.3.1",
    "type": "ovs-cni",
    "bridge": "br-int",
    "vlan": 100
  }'
```

### Хранилище: CDI и DataVolume

Containerized Data Importer (CDI) упрощает управление образами дисков ВМ в Kubernetes.

**Источники данных:**
- **PVC (PersistentVolumeClaim):** Базовый том из StorageClass (Ceph RBD, NFS, local-path).
- **DataVolume:** CRD, объединяющий PVC с импортом/клонированием образа.
- **ContainerDisk:** Образ ВМ, упакованный в OCI-контейнер. Автоматически загружается при старте VMI.

**Пример DataVolume из qcow2 образа:**
```yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: ubuntu-24.04
spec:
  source:
    http:
      url: "http://cloud-images.ubuntu.com/ubuntu-24.04-server-cloudimg-amd64.qcow2"
  pvc:
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 20Gi
    storageClassName: ceph-block
```

**Типы клонирования:**
- **Full Clone:** Полная копия данных. Зависит от производительности backing store.
- **Copy-on-Write Clone:** Использует backing image, копируя данные только при записи. Экономит место, но добавляет задержку.
- **Smart Clone:** Автоматически выбирает оптимальную стратегию на основе StorageClass.

### Live Migration в Kubernetes

KubeVirt поддерживает live migration ВМ между нодами через CRD VirtualMachineMigration.

**Управление миграцией:**
```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachineInstanceMigration
metadata:
  name: migration-web-server-01
spec:
  vmiName: web-server-01
```

**Политики миграции:**
- **PreCopy (по умолчанию):** Итеративная передача страниц памяти, краткая остановка для финальной синхронизации.
- **PostCopy:** Минимальное время простоя, но высокий риск при потере сети.

**Ограничения:**
- VMI не может быть мигрирована, если她использует HostDisk или PersistentVolume на Local Storage.
- SR-IOV и GPU passthrough не поддерживают live migration.
- Миграция требует, чтобы StorageClass был доступен на обеих нодах.

### Ограничения ресурсов и QoS

KubeVirt интегрируется с системой лимитов Kubernetes для контроля ресурсов ВМ.

**requests vs limits:**
- `spec.template.spec.domain.resources.requests` — гарантированные ресурсы (guaranteed QoS).
- `spec.template.spec.domain.resources.limits` — максимальные ресурсы (burstable/best-effort).

**Dedicated CPU (Полная изоляция):**
```yaml
spec:
  template:
    spec:
      domain:
        cpu:
          dedicatedCpuPlacement: true  # Изолирует vCPU от host scheduling
          isolateEmulatorThread: true  # Эмулятор на отдельном ядре
```

**Guaranteed QoS:** Если requests == limits, ВМ получает класс Guaranteed и не будет выброшена OOM-killer'ом до реального исчерпания памяти.

### Управление состоянием: RunStrategy

RunStrategy определяет, как kubevirt-controller управляет жизненным циклом ВМ.

| Стратегия | Поведение |
| :--- | :--- |
| **Always** | ВМ всегда запущена. Перезапуск при падении. |
| **RerunOnFailure** | Перезапуск при аварийном завершении (crash loop). |
| **Manual** | Ручное управление через `virtctl start/stop`. |
| **Halted** | ВМ всегда остановлена. Для шаблонов и бэкапов. |

**Пример:**
```yaml
spec:
  runStrategy: Always  # Автоматический restart при падении
  # runStrategy: Manual  # Ручное управление состоянием
```

### virtctl — CLI-управление ВМ

`virtctl` — командный инструмент для управления ВМ в KubeVirt, аналог `kubectl` для Pod.

**Основные команды:**
```bash
# Управление состоянием
virtctl start web-server-01
virtctl stop web-server-01
virtctl restart web-server-01
virtctl pause web-server-01
virtctl unpause web-server-01

# Доступ к консоли
virtctl console web-server-01          # Последовательная консоль
virtctl vnc web-server-01              # VNC-подключение
virtctl expose web-server-01 --port=22 --type=NodePort  # Порт в()]

# Hotplug ресурсов
virtctl addvolume web-server-01 --name=new-disk --size=10Gi
virtctl removevolume web-server-01 --name=new-disk

# Миграция
virtctl migrate web-server-01
virtctl migrate-cancel web-server-01
virtctl migrate-list

# Изменение ресурсов
virtctl resize web-server-01 --cpu=8 --memory=16Gi
```

## Практические сценарии

### Сценарий 1: Установка KubeVirt в Kubernetes

**1. Установка через Quick Start:**
```bash
# Установка CDI (для работы с образами дисков)
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/download/v1.60.0/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/download/v1.60.0/cdi-cr.yaml

# Установка KubeVirt
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.1.0/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.1.0/kubevirt-cr.yaml

# Ожидание готовности
kubectl wait --for=condition=Available deployment/virt-controller -n kubevirt --timeout=300s
kubectl wait --for=condition=Available deployment/virt-api -n kubevirt --timeout=300s

# Установка virtctl
curl -L https://github.com/kubevirt/kubevirt/releases/download/v1.1.0/virtctl-v1.1.0-linux-amd64 -o /usr/local/bin/virtctl
chmod +x /usr/local/bin/virtctl
```

**2. Проверка работоспособности:**
```bash
# Проверка компонентов
kubectl get pods -n kubevirt
# → virt-controller-xxxxx   1/1     Running
# → virt-handler-xxxxx      1/1     Running
# → virt-api-xxxxx          1/1     Running

# Проверка CRD
kubectl get crd | grep kubevirt
# → virtualmachines.kubevirt.io
# → virtualmachineinstances.kubevirt.io
# → virtualmachineinstancemigrations.kubevirt.io
```

### Сценарий 2: Развертывание ВМ из DataVolume

**1. Создание DataVolume с Ubuntu:**
```yaml
# ubuntu-dv.yaml
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: ubuntu-24.04
spec:
  source:
    http:
      url: "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
  pvc:
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 25Gi
    storageClassName: ceph-block
```

```bash
kubectl apply -f ubuntu-dv.yaml
kubectl get dv ubuntu-24.04 -w
# → Ожидание until phase=Succeeded
```

**2. Создание ВМ из DataVolume:**
```yaml
# ubuntu-vm.yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: ubuntu-vm-01
spec:
  running: true
  dataVolumeTemplates:
    - metadata:
        name: ubuntu-vm-01-rootdisk
      spec:
        source:
          pvc:
            name: ubuntu-24.04
            namespace: default
        pvc:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 25Gi
  template:
    spec:
      domain:
        cpu:
          cores: 2
          sockets: 1
        memory:
          guest: 4Gi
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
            - name: cloudinitdisk
              cloudInitNoCloud:
                secretRef:
                  name: cloud-init-secret
          interfaces:
            - name: default
              masquerade: {}
      volumes:
        - name: cloudinitdisk
          cloudInitNoCloud:
            secretRef:
              name: cloud-init-secret
      networks:
        - name: default
          pod: {}
```

```bash
kubectl apply -f ubuntu-vm.yaml
virtctl console ubuntu-vm-01  # Проверка доступа
```

### Сценарий 3: Подключение к OVS-сети

**1. Установка CNAO:**
```bash
kubectl apply -f https://github.com/cluster-network-addons-operator/releases/download/v0.90.0/manifests/release.yaml
```

**2. Создание OVS-моста (на нодах):**
```bash
# На каждой ноде с OVS
sudo ovs-vsctl add-br br-int
sudo ovs-vsctl set open_vswitch . other-config:datapath-id=...
```

**3. Создание NetworkAttachmentDefinition:**
```yaml
# ovs-nad.yaml
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: ovs-net
  annotations:
    k8s.v1.cni.cncf.io/resourceName: ovs-cni.b.cni.k8s.io
spec:
  config: '{
    "cniVersion": "0.3.1",
    "type": "ovs-cni",
    "bridge": "br-int",
    "vlan": 100
  }'
```

**4. Подключение ВМ к OVS:**
```yaml
spec:
  template:
    spec:
      domain:
        devices:
          interfaces:
            - name: ovs-if
              bridge: {}
      networks:
        - name: ovs-if
          multus:
            networkName: ovs-net
```

### Сценарий 4: Live Migration между нодами

**1. Запуск миграции:**
```bash
# Через virtctl
virtctl migrate web-server-01

# Или через kubectl
cat <<EOF | kubectl apply -f -
apiVersion: kubevirt.io/v1
kind: VirtualMachineInstanceMigration
metadata:
  name: migration-web-server-01
spec:
  vmiName: web-server-01
EOF
```

**2. Мониторинг прогресса:**
```bash
kubectl get vmim migration-web-server-01 -w
# → PHASE    STATUS
# → Pending  WaitingForTargetVirt
# → Running  Migrating
# → Succeeded

# Детали миграции
kubectl describe vmim migration-web-server-01
```

**3. Автоматическая миграция при обновлении нод:**
```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: web-server-01
spec:
  running: true
  runStrategy: Always
  template:
    metadata:
      annotations:
        kubevirt.io/keep-launcher-alive-after-upgrade: "true"
    spec:
      evictionStrategy: LiveMigrate  # Автоматическая миграция при eviction
```

### Сценарий 5: Шаблон ВМ и массовое развертывание

**1. Создание шаблона:**
```yaml
# vm-template.yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: ubuntu-template
  labels:
    kubevirt.io/template: ubuntu-24.04
spec:
  running: false  # Шаблон не запущен
  runStrategy: Halted
  dataVolumeTemplates:
    - metadata:
        name: ubuntu-template-rootdisk
      spec:
        source:
          pvc:
            name: ubuntu-24.04
            namespace: default
        pvc:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 25Gi
  template:
    spec:
      domain:
        cpu:
          cores: 2
        memory:
          guest: 4Gi
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
```

**2. Клонирование из шаблона:**
```bash
# Импорт шаблона в CDI
kubectl apply -f https://kubevirt.io/laboratory/images/ubuntu-template.yaml

# Создание 5 копий через loop
for i in $(seq 1 5); do
  cat <<EOF | kubectl apply -f -
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: worker-$(printf '%02d' $i)
spec:
  running: true
  template:
    spec:
      domain:
        cpu:
          cores: 2
        memory:
          guest: 4Gi
      volumes:
        - name: rootdisk
          persistentVolumeClaim:
            claimName: ubuntu-24.04-cloned-$(printf '%02d' $i)
EOF
done
```

### Сценарий 6: Hotplug дисков и сети

**1. Добавление диска к работающей ВМ:**
```bash
# Создание PVC
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: extra-disk-01
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: ceph-block
EOF

# Подключение диска к ВМ
virtctl addvolume web-server-01 \
  --name=extra-disk-01 \
  --persistentvolumeclaim=extra-disk-01 \
  --disk-type=persistentvolumeclaim \
  --bus=virtio
```

**2. Подключение сетевого интерфейса:**
```bash
# Через virtctl
virtctl addinterface web-server-01 \
  --name=ovs-if \
  --network-attachment-definition=ovs-net

# Проверка
virtctl get vm web-server-01 -o yaml | grep -A5 interfaces
```

### Сценарий 7: Мониторинг ВМ в Kubernetes

**1. Метрики через Prometheus:**
```bash
# kubevirt-controller экспортирует метрики:
# kubevirt_vmi_phase          - фаза ВМ (0/1)
# kubevirt_vmi_memory_actual  - фактическое потребление RAM
# kubevirt_vmi_cpu_usage_nanoseconds - потребление CPU
# kubevirt_vmi_network_receive_bytes_total - входящий трафик

# Пример PromQL запросов:
# Активные ВМ:
sum(kubevirt_vmi_phase{phase="running"}) by (namespace)

# Потребление памяти всеми ВМ:
sum(kubevirt_vmi_memory_actual) by (namespace)

# Steal time:
sum(rate(kvm_stat_halt_exits_total[5m])) by (vmi)
```

**2. Dashboard в Grafana:**
```bash
# Импорт дашборда ID 12198 (KubeVirt Overview)
# Или создание кастомного:
# Panel 1: Количество запущенных ВМ
# Panel 2: Суммарное потребление CPU/RAM
# Panel 3: Сетевой трафик по ВМ
# Panel 4: Количество миграций за период
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — базовые принципы KVM/QEMU/libvirt.
- [Управление виртуальными машинами](./management.md) — virsh, жизненный цикл ВМ.
- [Установка и настройка KVM](./installation.md) — параметры ядра, sVirt, firewall.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — тюнинг производительности.
- [Kubernetes: Overview](../../Kubernetes/kubernetes_overview.md) — архитектура Kubernetes.
- [Kubernetes Storage: PV/PVC](../../Kubernetes/Storage/pv_pvc_advanced.md) — управление хранилищем.
- [Ceph RBD](../../Kubernetes/Storage/Ceph/ceph_rbd_usage/advanced_topics.md) — блочное хранилище для ВМ.
- [Multus CNI](../../Kubernetes/Networking/Network/CNI/multus.md) — мульти-сетевые интерфейсы.
- [Open vSwitch](../../Networking/ServicesAndTools/open_vswitch.md) — программный коммутатор.
