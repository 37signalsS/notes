# Высокая доступность KVM: Pacemaker, DRBD, Fencing

В данном файле описывается построение отказоустойчивых кластеров KVM с использованием Pacemaker, Corosync и DRBD. Теория HA и механизмов failover представлена в [High Availability: Обзор](../../Concepts/High_Availability/ha_overview.md), а стек Pacemaker/DRBD — в [Linux HA Stack: Pacemaker + DRBD](../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md).

## Определения

**Pacemaker** — менеджер ресурсов (CRM) для Linux-кластеров. Управляет жизненным циклом ресурсов (ВМ, IP, сервисы) и выполняет автоматический failover при отказе узла.

**Corosync** — транспортная инфраструктура кластера. Обеспечивает的心跳-мониторинг, кворум и доставку сообщений между узлами. Поддерживает knet (unicast) и multicast.

**DRBD (Distributed Replicated Block Device)** — блочный драйвер ядра для синхронной/асинхронной репликации данных между узлами. Аналог "сетевого RAID 1".

**STONITH (Shoot The Other Node In The Head)** — механизм принудительного отключения сбойного узла через IPMI/BMC/iDRAC. Обязателен для предотвращения Split-Brain.

**Fencing** — процесс гарантированного отключения узла, который не отвечает на heartbeat. Типы: Power Fencing (IPMI), Storage Fencing (SCSI-3 PR).

**Split-Brain** — состояние, при котором кластер разделяется на две изолированные части, каждая из которых считает себя активной. Ведет к гонке за общие ресурсы и потере данных.

**Resource Agent (RA)** — скрипт, управляющий конкретным ресурсом в Pacemaker. Типы: systemd, ocf:heartbeat, ocf:linbit.

**Colocation Constraint** — ограничение, определяющее, какие ресурсы должны работать на одном узле.

**Order Constraint** — ограничение порядка запуска ресурсов (например, сначала DRBD, затем ВМ).

**Location Constraint** — ограничение, определяющее предпочтительный узел для ресурса.

## Базовые концепции

### Архитектура HA-кластера для KVM

Кластер состоит из 2-5 узлов с общим хранилищем (или репликацией через DRBD) и менеджером ресурсов.

**Компоненты:**
- **Corosync:** Каждый узел обменивается heartbeat-сообщениями. Если узел не отвечает > threshold, он объявляется offline.
- **Pacemaker:** Принимает решение о failover на основе quorum и resource constraints.
- **DRBD:** Реплицирует диски ВМ между узлами (primary/secondary).
- **STONITH/Fencing:** Гарантированно отключает сбойный узел через IPMI/iDRAC перед failover.
- **Virtual Domain RA:** Управляет生命周期 ВМ в libvirt (start, stop, migrate).

**Схема кластера:**
```
        [Pacemaker + Corosync]
              /          \
    [KVM Host A]      [KVM Host B]
    (Primary)          (Secondary)
         |                  |
    [DRBD Primary]    [DRBD Secondary]
         |                  |
    [VM Web-01]        [VM DB-01]
         |                  |
    [IPMI/BMC]         [IPMI/BMC]
```

### Режимы DRBD

DRBD поддерживает несколько протоколов репликации, различающихся по производительности и консистентности.

| Протокол | Описание | Потеря данных | Use Case |
| :--- | :--- | :--- | :--- |
| **Protocol A** | Асинхронная репликация. Данные записаны на local disk, ACK отправлен. | Возможна при аварии обоих узлов. | Максимальная производительность. |
| **Protocol B** | Полу-синхронная. Данные записаны на remote disk, но не на local. | Нет при аварии одного узла. | Баланс производительности и безопасности. |
| **Protocol C** | Синхронная. Данные записаны на оба узла до ACK. | Нет при аварии одного узла. | Максимальная безопасность ( notes: Stock), но выше latency. |

**Настройка DRBD:**
```bash
# /etc/drbd.d/data.res
resource data {
  protocol C;
  
  disk {
    on-io-error detach;
    c-plan-ahead 20;
    c-fill-target 16M;
    c-max-rate 720M;
  }
  
  on kvm-host-01 {
    device /dev/drbd0;
    disk /dev/vg0/data;
    address 192.168.1.10:7789;
    meta-disk internal;
  }
  
  on kvm-host-02 {
    device /dev/drbd0;
    disk /dev/vg0/data;
    address 192.168.1.11:7789;
    meta-disk internal;
  }
}
```

**Инициализация DRBD:**
```bash
# На обоих узлах
sudo drbdadm create-md data
sudo drbdadm up data

# На primary (Host A)
sudo drbdadm primary --force data

# Проверка
cat /proc/drbd
# → version: 8.4.10 (api:1/proto:86-96)
#   0: cs:Connected ro:Primary/Secondary ds:UpToDate/UpToDate
```

### Pacemaker: ресурсы и ограничения

Pacemaker управляет ресурсами через CIB (Cluster Information Base) и constraints.

**Типы ресурсов:**
- **primitive:** Один экземпляр ресурса (IP, service, VM).
- **group:** Группа ресурсов, запускаемых вместе.
- **clone:** Ресурс, запускаемый на всех узлах (corosync, pacemaker).
- **master/slave:** Ресурс с primary/secondary (DRBD).

**Constraints:**
- **Colocation:** `colocation VM_with_DRBD inf: VM DRBD`
- **Order:** `order DRBD_before_VM inf: DRBD:promote VM:start`
- **Location:** `location prefer_host_A VM 100: kvm-host-01`

**CLI-управление:**
```bash
# Просмотр состояния кластера
sudo crm status
sudo crm_mon -1

# Создание ресурса
sudo crm configure primitive vm-web-01 ocf:heartbeat:VirtualDomain \
  config=/etc/libvirt/qemu/web-server-01.xml \
  hypervisor=qemu:///system \
  migration_transport=ssh

# Настройка constraints
sudo crm configure colocation VM_with_DRBD inf: vm-web-01 DRBD_data:Master
sudo crm configure order DRBD_before_VM inf: DRBD_data:promote vm-web-01:start

# Запуск кластера
sudo crm cluster start
sudo crm resource start vm-web-01
```

### Fencing: STONITH

Fencing обязателен для кластеров с общим хранилищем. Без него возможен Split-Brain.

**Типы fencing:**
- **IPMI/BMC:** Аппаратное отключение питания через management interface.
- **iDRAC/iLO:** Vendor-specific IPMI (Dell, HP).
- **SCSI-3 PR:** Блочная блокировка на SAN-хранилище.
- **Virtual Fencing:** fence_virt / fence_xvm для виртуальных кластеров.

**Настройка IPMI fencing:**
```bash
# Проверка доступности IPMI
ipmitool -I lanplus -H 192.168.1.100 -U admin -P password power status

# Добавление fencing-устройства в Pacemaker
sudo crm configure primitive fence-host-01 fence_ipmilan \
  pcmk_host_list="kvm-host-01" \
  ipaddr="192.168.1.100" \
  login="admin" \
  passwd="password" \
  lanplus=1 \
  power_wait=4

# Настройка fencing-политики
sudo crm configure property stonith-enabled=true
sudo crm configure property stonith-action=reboot
```

**Настройка fence_xvm (для виртуальных кластеров):**
```bash
# На хосте-гипервизоре
sudo apt install fence-virt

# Конфигурация fence_xvm
# /etc/fence_virt.conf
[firewall]
 fencing_method = serial

[serial]
 port = 0
 baud = 115200

[virtual]
 driver = virt
```

### Failover ВМ при отказе узла

Pacemaker автоматически перезапускает ВМ на surviving узле при отказе primary.

**Сценарий failover:**
1. Host A теряет сеть или зависает.
2. Corosync не получает heartbeat > timeout.
3. Pacemaker объявляет Host A offline.
4. STONITH отключает Host A через IPMI (power off).
5. DRBD: Host B становится primary.
6. Pacemaker запускает ВМ на Host B из DRBD-данных.
7. ВМ доступна на VIP, привязанном к Host B.

**Таймауты:**
```bash
# Время ожидания heartbeat ( Corosync)
sudo crm configure property token=5000

# Таймаут для запуска ресурса
sudo crm configure rsc_defaults migration-threshold=3

# Таймаут для fencing
sudo crm configure property stonith-timeout=60
```

## Практические сценарии

### Сценарий 1: Установка стека HA

Полная установка Corosync + Pacemaker + DRBD на двух узлах.

**1. Установка пакетов (на обоих узлах):**
```bash
# Ubuntu/Debian
sudo apt install -y corosync pacemaker fence-agents resource-agents \
  drbd-utils linux-modules-extra-$(uname -r)

# RHEL/Rocky
sudo dnf install -y corosync pacemaker fence-agents resource-agents \
  kmod-drbd
```

**2. Настройка /etc/hosts:**
```bash
echo "192.168.1.10 kvm-host-01" | sudo tee -a /etc/hosts
echo "192.168.1.11 kvm-host-02" | sudo tee -a /etc/hosts
```

**3. Конфигурация Corosync:**
```bash
# Генерация конфигурации
sudo corosync-cfgtool -s
sudo corosync-cmapctl | grep members

# /etc/corosync/corosync.conf
totem {
  version: 2
  cluster_name: kvm-cluster
  transport: knet
  secauth: on
  
  interface {
    ringnumber: 0
    bindnetaddr: 192.168.1.0
    mcastport: 5405
    ttl: 1
  }
}

nodelist {
  node {
    ring0_addr: kvm-host-01
    nodeid: 1
  }
  node {
    ring0_addr: kvm-host-02
    nodeid: 2
  }
}

quorum {
  provider: corosync.votequorum
  two_node: 1
}

logging {
  to_logfile: yes
  logfile: /var/log/corosync/corosync.log
}
```

**4. Запуск кластера:**
```bash
# На обоих узлах
sudo systemctl enable --now corosync
sudo systemctl enable --now pacemaker

# Проверка
sudo corosync-cfgtool -s
sudo crm status
```

### Сценарий 2: Настройка DRBD для ВМ

Настройка репликации дисков для хранения образов ВМ.

**1. Подготовка LVM (на обоих узлах):**
```bash
sudo lvcreate -L 100G -n data vg0
```

**2. Конфигурация DRBD:**
```bash
# /etc/drbd.d/data.res
resource data {
  protocol C;
  
  disk {
    on-io-error detach;
    c-plan-ahead 20;
  }
  
  on kvm-host-01 {
    device /dev/drbd0;
    disk /dev/vg0/data;
    address 192.168.1.10:7789;
    meta-disk internal;
  }
  
  on kvm-host-02 {
    device /dev/drbd0;
    disk /dev/vg0/data;
    address 192.168.1.11:7789;
    meta-disk internal;
  }
}
```

**3. Инициализация:**
```bash
# На обоих узлах
sudo drbdadm create-md data
sudo drbdadm up data

# На Host A (primary)
sudo drbdadm primary --force data

# Форматирование
sudo mkfs.ext4 /dev/drbd0

# Монтирование
sudo mkdir -p /var/lib/libvirt/images
sudo mount /dev/drbd0 /var/lib/libvirt/images
```

**4. Настройка Pacemaker:**
```bash
sudo crm configure primitive DRBD_data ocf:linbit:drbd \
  drbd_resource="data"

sudo crm configure ms DRBD_data_clone DRBD_data \
  master-max=1 \
  master-node-max=1 \
  clone-max=2 \
  clone-node-max=1 \
  notify=true
```

### Сценарий 3: Полная конфигурация HA-кластера

Объединение всех компонентов: DRBD + fencing + VM.

```bash
sudo crm configure

# DRBD
primitive DRBD_data ocf:linbit:drbd drbd_resource="data"
ms DRBD_data_clone DRBD_data \
  master-max=1 master-node-max=1 \
  clone-max=2 clone-node-max=1 \
  notify=true

# Filesystem (挂载 DRBD)
primitive FS_data ocf:heartbeat:Filesystem \
  device="/dev/drbd0" \
  directory="/var/lib/libvirt/images" \
  fstype="ext4"

# Virtual Domain
primitive vm-web-01 ocf:heartbeat:VirtualDomain \
  config="/etc/libvirt/qemu/web-server-01.xml" \
  hypervisor="qemu:///system" \
  migration_transport="ssh"

# VIP для доступа к ВМ
primitive VIP_web-01 ocf:heartbeat:IPaddr2 \
  ip="192.168.122.100" \
  cidr_netmask="24" \
  nic="br0"

# Fencing
primitive fence-host-01 fence_ipmilan \
  pcmk_host_list="kvm-host-01" \
  ipaddr="192.168.1.100" \
  login="admin" passwd="password" \
  lanplus=1

primitive fence-host-02 fence_ipmilan \
  pcmk_host_list="kvm-host-02" \
  ipaddr="192.168.1.101" \
  login="admin" passwd="password" \
  lanplus=1

# Constraints
colocation FS_on_DRBD inf: FS_data DRBD_data_clone:Master
colocation VM_on_FS inf: vm-web-01 FS_data
colocation VIP_on_VM inf: VIP_web-01 vm-web-01

order DRBD_before_FS inf: DRBD_data_clone:promote FS_data:start
order FS_before_VM inf: FS_data vm-web-01:start
order VM_before_VIP inf: vm-web-01 VIP_web-01:start

# Properties
property stonith-enabled=true
property stonith-action=reboot
property no-quorum-policy=ignore
property default-resource-stickiness=100

# Fencing topology
fencing topology
  kvm-host-01 fence-host-01
  kvm-host-02 fence-host-02

exit
```

### Сценарий 4: Тестирование failover

Проверка работоспособности кластера.

```bash
# 1. Проверка состояния
sudo crm status
sudo crm_mon -1

# 2. Имитация отказа Host A
sudo corosync-cfgtool -k  # Kill membership
# Или:
sudo reboot -f  # Принудительная перезагрузка Host A

# 3. Мониторинг failover
watch -n 1 sudo crm status
# → Host B: DRBD promoted to primary
# → Host B: VM started
# → Host B: VIP assigned

# 4. Восстановление Host A
sudo systemctl start corosync pacemaker
# → Host A: DRBD becomes secondary
# → Host A: VM не запускается (约束 запрещает)

# 5. Возврат на Host A ( Planned failback)
sudo crm resource migrate vm-web-01 kvm-host-01
# Или:
sudo crm node standby kvm-host-02  # Временный standy
```

### Сценарий 5: Мониторинг кластера

Настройка мониторинга HA через Prometheus.

**Метрики Pacemaker:**
```bash
# Установка pcmk_exporter
# https://github.com/ClusterLabs/pcmk_exporter

# Конфигурация Prometheus
scrape_configs:
  - job_name: 'pacemaker'
    static_configs:
      - targets:
          - 'kvm-host-01:9665'
          - 'kvm-host-02:9665'
```

**Ключевые метрики:**
```promql
# Состояние узлов кластера
pcmk_nodes_online

# Состояние ресурсов
pcmk_resources_state

# Время работы кластера
pcmk_cluster_uptime

# Количество failover за период
rate(pcrm_resources_failed_total[1h])
```

## Дополнительная информация

- [High Availability: Обзор](../../Concepts/High_Availability/ha_overview.md) — RTO, RPO, типы HA.
- [Linux HA Stack: Pacemaker + DRBD](../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md) — полное руководство.
- [Failover Mechanisms](../../Concepts/High_Availability/ha_failover_mechanisms.md) — VRRP, Keepalived, STONITH.
- [KVM — Управление ВМ](./management.md) — virsh, жизненный цикл ВМ.
- [KVM — Миграция](./overview.md#миграция-виртуальных-машин-live-migration) — live migration.
- [DRBD Documentation](https://docs.linbit.com/docs/users-guide-9.0/) — официальная документация.
- [Pacemaker Documentation](https://clusterlabs.org/pacemaker/doc/latest/en-US/) — официальная документация.
