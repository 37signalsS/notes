# Образы ВМ — Развертывание в продакшен

В данном файле описывается развёртывание образов виртуальных машин в продакшен-среды: настройка сети, CPU/памяти, высокая доступность и мониторинг. Основы форматов и хранилища образов — в [Основных концепциях](./basic_concepts.md), инструменты — в [Практических сценариях](./practical_scenarios.md).

## Определения

**Production Deployment** — процесс развёртывания виртуальной машины из готового образа в рабочую среду с настройкой сети, ресурсов, безопасности и мониторинга.

**Live Migration** — перемещение работающей ВМ между физическими хостами без остановки гостевой ОС. Требует общего хранилища и низкой задержки сети между хостами.

**CPU Pinning (vcpupin)** — привязка виртуальных CPU к физическим ядрам хоста для обеспечения предсказуемой производительности и исключения конкуренции за ресурсы.

**NUMA (Non-Uniform Memory Access)** — архитектура, при которой доступ к памяти через локальный контроллер быстрее, чем через удалённый. Критично для производительности баз данных и высоконагруженных сервисов.

**Memory Ballooning** — механизм динамического перераспределения RAM между ВМ через virtio-balloon. Позволяет делать overcommit памяти без остановки ВМ.

**Huge Pages** — страницы памяти увеличенного размера (2 МБ или 1 ГБ) для снижения оверхеда TLB и улучшения производительности работающих с большими объёмами данных приложений.

**KSM (Kernel Samepage Merging)** — механизм ядра для объединения неизменных страниц памяти между ВМ. Экономит RAM при однотипных образах ОС.

**HA (High Availability)** — отказоустойчивость. Автоматическое переключение ВМ на резервный хост при отказе основного.

**Steal Time** — время, в течение которого vCPU ВМ ожидал физический CPU из-за перегрузки хоста. Высокий steal time указывает на необходимость тюнинга или миграции.

## Базовые концепции

### Архитектура развёртывания

Развёртывание образа в продакшен включает несколько уровней настройки.

**Уровни конфигурации:**
```
┌─────────────────────────────────────────────────┐
│  1. Образ (qcow2/raw)                          │
│     - ОС, пакеты, конфигурация                  │
│     - cloud-init для первого запуска            │
├─────────────────────────────────────────────────┤
│  2. Конфигурация ВМ (libvirt XML)               │
│     - CPU: vcpupin, emulatorpin, iothreads      │
│     - RAM: size, hugepages, numatune            │
│     - Диск: bus, cache, io, queues              │
│     - Сеть: bridge, model, driver               │
├─────────────────────────────────────────────────┤
│  3. Хост (KVM hypervisor)                       │
│     - IOMMU, CPU isolation, sysctl              │
│     - Сеть: bridge, VLAN, firewall              │
│     - Хранилище: pool, thin provisioning        │
├─────────────────────────────────────────────────┤
│  4. Инфраструктура                              │
│     - HA: Pacemaker/Corosync, shared storage    │
│     - Мониторинг: Prometheus, libvirt_exporter  │
│     - Автоматизация: Ansible, Terraform         │
└─────────────────────────────────────────────────┘
```

### Сетевая конфигурация для продакшена

Сеть — критичный компонент. Основные режимы подключения ВМ.

**Таблица выбора сетевого режима:**

| Режим | Производительность | Изоляция | Миграция | Сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **NAT (virbr0)** | Средняя | Полная | Да | Девелопмент, изолированные среды |
| **Bridge (br0)** | Высокая | Зависит от VLAN | Да | Продакшен, общая сеть |
| **macvtap (bridge)** | Высокая | Полная | Да | Высоконагруженные сервисы |
| **SR-IOV VF** | Максимальная | Ограниченная | Ограниченная* | Низкозадержечные БД, HFT |
| **OVS + VXLAN** | Высокая | Полная | Да | Кластеры, microservices |

*SR-IOV VF требует net_failover для live migration (см. [SR-IOV](../../../Networking/Concepts/dpdk/sriov.md)).

**Рекомендуемая конфигурация для продакшена:**
```xml
<!-- bridge mode с virtio-net multi-queue -->
<interface type='bridge'>
  <mac address='52:54:00:aa:bb:cc'/>
  <source bridge='br0'/>
  <model type='virtio'/>
  <driver name='vhost' queues='4'/>
  <target dev='vnet0'/>
  <alias name='net0'/>
</interface>
```

**Настройка VLAN на мосте (Linux Bridge):**
```bash
# Создание VLAN-aware bridge
ip link add br0 type bridge vlan_filtering 1
ip link set br0 up

# Добавление VLAN 100
bridge vlan add dev br0 vid 100 pvid untagged

# Настройка интерфейса хоста
ip link set ens1f0 master br0
bridge vlan add dev ens1f0 vid 100

# Проверка
bridge vlan show dev br0
```

**Настройка сети через libvirt:**
```bash
# Создание сети bridge для продакшена
cat > prod-network.xml <<'EOF'
<network>
  <name>production</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
  <virtualport type='openvswitch'/>
</network>
EOF

virsh net-define prod-network.xml
virsh net-start production
virsh net-autostart production
```

### CPU/память для продакшена

Правильная настройка ресурсов критична для производительности.

**CPU Pinning (cputune) в libvirt XML:**
```xml
<!-- Привязка vCPU к конкретным ядрам и эмулятора к отдельному ядру -->
<vcpu placement='static'>4</vcpu>
<cputune>
  <vcpupin vcpu='0' cpuset='2'/>
  <vcpupin vcpu='1' cpuset='3'/>
  <vcpupin vcpu='2' cpuset='4'/>
  <vcpupin vcpu='3' cpuset='5'/>
  <emulatorpin cpuset='6-7'/>
  <iothreadpin iothread='1' cpuset='6'/>
</cputune>
```

**Проверка и настройка NUMA:**
```bash
# Проверка NUMA-топологии хоста
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 4 5 6 7
# → node 1 cpus: 8 9 10 11 12 13 14 15
# → node 0 size: 32768 MB
# → node 1 size: 32768 MB

# Привязка ВМ к NUMA-узлу 0
cat > numa-vm.xml <<'EOF'
<numatune>
  <memory nodeset='0' mode='strict'/>
</numatune>
EOF

# Проверка локальности памяти QEMU
numastat -p $(pgrep -o qemu-system)
# → Per-node process memory usage (in MBs)
# → Node 0   Node 1   Total
# → -------  -------  -------
# → 16384        0    16384  ← хорошо: вся память на локальном NUMA
```

**Huge Pages для ВМ:**
```bash
# Резервирование 1 ГБ страниц в GRUB
# /etc/default/grub:
# GRUB_CMDLINE_LINUX="default_hugepagesz=1G hugepagesz=1G hugepages=64"

# Проверка выделения
grep -i huge /proc/meminfo
# → HugePages_Total:      64
# → HugePages_Free:       32
# → HugePages_Rsvd:       28
# → Hugepagesize:     1048576 kB

# Конфигурация ВМ с Huge Pages
cat > hugepages-vm.xml <<'EOF'
<memoryBacking>
  <hugepages>
    <page size='1' unit='GiB'/>
  </hugepages>
  <locked/>
</memoryBacking>
EOF
```

**Memory Ballooning (динамический overcommit):**
```xml
<!-- Базовая конфигурация balloon -->
<memballoon type='virtio'>
  <model type='virtio'/>
  <stats period='10'/>
</memballoon>

<!-- С выделением памяти -->
<memballoon type='virtio'>
  <alias name='balloon0'/>
  <address type='pci' domain='0x0000' bus='0x00' slot='0x04' function='0x0'/>
</memballoon>
```

**Проверка balloon:**
```bash
# Мониторинг использования balloon
virsh domstats web-server-01 | grep balloon
# → balloon.current=0
# → balloon.maximum=8388608
# → balloon.rss=4194304
# → balloon.usable=4194304
# → balloon.last_update=1726560000000000000
```

**KSM (Kernel Samepage Merging):**
```bash
# Включение KSM
echo 1 > /sys/kernel/mm/ksm/run

# Настройка параметров
echo 100 > /sys/kernel/mm/ksm/pages_to_scan
echo 20 > /sys/kernel/mm/ksm/sleep_millisecs
echo 1 > /sys/kernel/mm/ksm/merge_across_nodes

# Проверка эффективности
grep -i ksm /proc/meminfo
# → KsmShared:     1048576  ← объединённые страницы
# → KsmShared_Uss:  524288  ← экономия
# → Ksmpages_sharing: 262144

# Постоянная настройка через systemd
systemctl enable --now ksm.service
```

### I/O конфигурация для продакшена

**Рекомендуемые настройки для разных рабочих нагрузок:**

| Рабочая нагрузка | Шина | Cache | IO | Queues | Планировщик |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **База данных** | virtio-blk | none | io_uring | 4 | none |
| **Веб-сервер** | virtio-scsi | none | io_uring | 2 | mq-deadline |
| **Файловый сервер** | virtio-scsi | none | io_uring | 4 | mq-deadline |
| **Разработка** | virtio-blk | none | native | 1 | mq-deadline |

**Конфигурация диска для БД (MySQL/PostgreSQL):**
```xml
<disk type='file' device='disk'>
  <driver name='qemu' type='qcow2' cache='none' io='io_uring' discard='unmap' detect_zeroes='unmap'/>
  <source file='/var/lib/libvirt/images/db-server.qcow2'/>
  <target dev='vda' bus='virtio'/>
  <alias name='drive-virtio-disk0'/>
  <address type='pci' domain='0x0000' bus='0x00' slot='0x03' function='0x0'/>
</disk>
```

### Live Migration

Перемещение работающей ВМ между хостами без даунтайма.

**Требования:**
- Общее хранилище (NFS, Ceph, GlusterFS) или storage migration
- Однотипные libvirt/QEMU версии на обоих хостах
- Низкая задержка сети (<1 мс)
- Открытый порт 16509 (TLS) или 22 (SSH)

**Простая миграция:**
```bash
# Pre-copy миграция (по умолчанию)
virsh migrate --live --persistent --verbose \
  web-server-01 qemu+ssh://dest-host/system
```

**Миграция с auto-converge (для активных ВМ):**
```bash
# Автоматическое замедление vCPU при медленной миграции
virsh migrate --live --auto-converge --bandwidth 500 \
  web-server-01 qemu+ssh://dest-host/system
```

**Post-copy миграция (минимальный даунтайм):**
```bash
# Включить postcopy в XML (на обоих хостах):
# <migration>
#   <postcopy enable='yes'/>
# </migration>

virsh migrate --live --postcopy --verbose \
  web-server-01 qemu+ssh://dest-host/system
```

**Мониторинг миграции:**
```bash
# Прогресс миграции в реальном времени
virsh domjobinfo web-server-01
# → Job type:         Unbounded
# → Job time elapsed: 12543 ms
# → Data processed:   1073741824 bytes
# → Data remaining:   524288000 bytes
# → Memory processed: 524288000 bytes
# → Memory remaining: 134217728 bytes
# → Memory dirty rate: 100 MB/s
# → Iteration:        12
# → Iteration remaining: 5
```

**Ограничение миграции через XML:**
```xml
<migration>
  <bandwidth unit='M' value='1000'/>
  <autoconverge toggle='on'/>
  <compression>
    <xbzrle toggle='on'/>
    <zstd toggle='on'/>
  </compression>
  <postcopy enable='yes'/>
</migration>
```

### Высокая доступность (HA)

Автоматическое восстановление ВМ при отказе хоста.

**Минимальный HA-кластер (Pacemaker + Corosync):**
```bash
# 1. Установка на обоих хостах
apt-get install -y pacemaker corosync pcs

# 2. Авторизация узлов
pcs host auth kvm-host-01 kvm-host-02 -u hacluster -p password

# 3. Настройка кластера
pcs cluster setup ha-cluster kvm-host-01 kvm-host-02
pcs cluster start --all
pcs cluster enable --all

# 4. Настройка STONITH (IPMI)
pcs stonith create fence-host01 fence_ipmilan \
  ipaddr="192.168.1.100" login="admin" passwd="password" pcmk_host_list="kvm-host-01"

pcs stonith create fence-host02 fence_ipmilan \
  ipaddr="192.168.1.101" login="admin" passwd="password" pcmk_host_list="kvm-host-02"

pcs property set stonith-enabled=true

# 5. Ресурс ВМ
pcs resource create vm-web-01 ocf:heartbeat:VirtualDomain \
  config="/etc/libvirt/qemu/web-server-01.xml" \
  hypervisor="qemu:///system" \
  meta allow-migrate=true target-role=Started

pcs constraint colocation add vm-web-01 with fence-host01
pcs constraint order fence-host01 then vm-web-01
```

**Настройка DRBD для общего хранилища:**
```bash
# /etc/drbd.d/vm-data.res
resource vm-data {
  protocol C;
  disk {
    on-io-error detach;
    c-plan-ahead 20;
    c-fill-target 16M;
    c-max-rate 720M;
  }
  
  on kvm-host-01 {
    device /dev/drbd0;
    disk /dev/vg0/vm-data;
    address 192.168.1.10:7789;
    meta-disk internal;
  }
  
  on kvm-host-02 {
    device /dev/drbd0;
    disk /dev/vg0/vm-data;
    address 192.168.1.11:7789;
    meta-disk internal;
  }
}

# Инициализация
drbdadm create-md vm-data
drbdadm up vm-data
drbdadm primary --force vm-data

# Форматирование и монтирование (только на primary)
mkfs.ext4 /dev/drbd0
mount /dev/drbd0 /var/lib/libvirt/images
```

### Мониторинг развёрнутых ВМ

Мониторинг критичен для обнаружения проблем до их воздействия на пользователей.

**Ключевые метрики для алертинга:**

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| **CPU Steal Time** | >5% (5 мин) | Миграция на менее загруженный хост |
| **Memory Balloon** | balloon.current < 80% balloon.target | Проверка настройки |
| **Disk Usage** | >85% | Расширение или очистка |
| **Network Packet Loss** | >1% (5 мин) | Проверка сети/драйвера |
| **VM Not Running** | != running | Автозапуск или алерт |
| **I/O Latency** | p99 >10ms | Проверка хранилища |

**Prometheus alert rules (min):**
```yaml
groups:
  - name: vm_alerts
    rules:
      - alert: HighStealTime
        expr: rate(libvirt_domain_info_vcpu_time{mode="idle"}[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU steal time on {{ $labels.domain }}"

      - alert: VMNotRunning
        expr: libvirt_domain_info_status{status="running"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "VM {{ $labels.domain }} is not running"

      - alert: StoragePoolFull
        expr: (libvirt_storage_pool_allocation_bytes / libvirt_storage_pool_capacity_bytes) > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Storage pool {{ $labels.pool }} is {{ $value | humanizePercentage }} full"
```

**Мониторинг через virsh:**
```bash
# Список всех ВМ и их состояния
virsh list --all
# →  Id   Name          State
# → ----------------------------
# →  1    web-server-01 running
# →  2    db-server-01  running
# →  -    test-vm       shut off

# Статистика ресурсов
virsh domstats web-server-01
# → web-server-01:
#   cpu.user=123456789
#   cpu.system=987654321
#   balloon.current=0
#   balloon.maximum=8388608
#   block.read.bytes=1048576
#   block.write.bytes=524288

# Проверка производительности в реальном времени
virt-top -d 1
# → ID    NAME   CPU%  MEM%  BLOCK I/O
# → 1     web-01  12.3  45.2  10M/5M
# → 2     db-01   45.1  78.3  50M/20M
```

## Практические сценарии

### Сценарий 1: Развёртывание ВМ из образа с полной настройкой

Создание production-ready ВМ из golden image с настройкой сети, CPU и мониторинга.

```bash
#!/bin/bash
# deploy-vm.sh — развертывание ВМ из golden image
set -euo pipefail

VM_NAME="${1:?Usage: deploy-vm.sh <vm-name>}"
MEMORY="${2:-4096}"
VCPUS="${3:-2}"
GOLDEN_IMAGE="/images/golden-images/ubuntu-24.04-latest.qcow2"
POOL="default"

# 1. Клонирование образа
echo "Cloning golden image..."
virt-clone --original ubuntu-template \
  --name "$VM_NAME" \
  --file "/var/lib/libvirt/images/${VM_NAME}.qcow2"

# 2. Настройка конфигурации
virsh setvcpus "$VM_NAME" "$VCPUS" --config
virsh setmem "$VM_NAME" "$MEMORY" --config

# 3. Настройка CPU pinning ( если ядра выделены)
if [ "$VCPUS" -le 4 ]; then
  virsh vcpupin "$VM_NAME" 0 2 --config
  virsh vcpupin "$VM_NAME" 1 3 --config
  virsh vcpupin "$VM_NAME" 2 4 --config
  virsh vcpupin "$VM_NAME" 3 5 --config
fi

# 4. Настройка cache=none для диска
virsh dumpxml "$VM_NAME" | \
  sed "s/cache='writethrough'/cache='none'/g" | \
  virsh define /dev/stdin

# 5. Запуск
virsh start "$VM_NAME"

# 6. Ожидание IP
echo "Waiting for IP..."
for i in $(seq 1 60); do
  IP=$(virsh domifaddr "$VM_NAME" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
  if [ -n "$IP" ]; then
    echo "VM $VM_NAME deployed: $IP"
    break
  fi
  sleep 2
done

# 7. Проверка qemu-guest-agent
if [ -n "$IP" ]; then
  ssh -o StrictHostKeyChecking=no ubuntu@"$IP" "systemctl is-active qemu-guest-agent" && \
    echo "Guest agent: OK" || echo "Guest agent: NOT RUNNING"
fi
```

### Сценарий 2: Оптимизация ВМ для базы данных

Тюнинг ВМ с PostgreSQL/MySQL для максимальной производительности.

```bash
#!/bin/bash
# optimize-db-vm.sh — оптимизация для БД
set -euo pipefail

VM_NAME="${1:?Usage: optimize-db-vm.sh <vm-name>}"

# 1. Остановка ВМ для изменения конфигурации
virsh shutdown "$VM_NAME"
sleep 10

# 2. Применение XML-конфигурации для БД
cat > /tmp/db-tuning.xml <<'XML'
<domain type='kvm'>
  <memoryBacking>
    <hugepages>
      <page size='1' unit='GiB'/>
    </hugepages>
    <locked/>
    <nosharepages/>
  </memoryBacking>
  
  <cputune>
    <vcpupin vcpu='0' cpuset='2'/>
    <vcpupin vcpu='1' cpuset='3'/>
    <vcpupin vcpu='2' cpuset='4'/>
    <vcpupin vcpu='3' cpuset='5'/>
    <emulatorpin cpuset='6-7'/>
  </cputune>
  
  <numatune>
    <memory nodeset='0' mode='strict'/>
  </numatune>
  
  <cpu mode='host-passthrough' check='none' migratable='off'>
    <topology sockets='1' dies='1' cores='4' threads='1'/>
    <cache mode='passthrough'/>
  </cpu>
</domain>
XML

# 3. Применение настроек
# (В реальном сценарии: virsh edit или patch через xmllint)

# 4. Настройка Huge Pages на хосте
echo "Allocating 4x 1GB Huge Pages..."
echo 4 > /proc/sys/vm/nr_hugepages

# 5. Запуск ВМ
virsh start "$VM_NAME"

# 6. Проверка настроек внутри гостя
echo "Checking NUMA locality..."
ssh ubuntu@"$(virsh domifaddr "$VM_NAME" | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)" \
  "numactl --hardware && cat /proc/meminfo | grep -i huge"
```

### Сценарий 3: Массовое развёртывание ВМ

Создание кластера из нескольких ВМ с общей конфигурацией.

```bash
#!/bin/bash
# deploy-cluster.sh — развёртывание кластера ВМ
set -euo pipefail

CLUSTER_NAME="${1:?Usage: deploy-cluster.sh <cluster-name>}"
NODE_COUNT="${2:-3}"
MEMORY="8192"
VCPUS="4"
DISK="50G"

for i in $(seq 1 "$NODE_COUNT"); do
  VM_NAME="${CLUSTER_NAME}-node-${i}"
  echo "=== Deploying: $VM_NAME ==="
  
  # 1. Клонирование
  virt-clone --original ubuntu-template \
    --name "$VM_NAME" \
    --file "/var/lib/libvirt/images/${VM_NAME}.qcow2"
  
  # 2. Расширение диска
  qemu-img resize "/var/lib/libvirt/images/${VM_NAME}.qcow2" "$DISK"
  
  # 3. Конфигурация
  virsh setvcpus "$VM_NAME" "$VCPUS" --config
  virsh setmem "$VM_NAME" "$MEMORY" --config
  
  # 4. Cloud-init для уникальной настройки
  cat > "/tmp/cloud-init-${VM_NAME}.yaml" <<EOF
#cloud-config
hostname: ${VM_NAME}
manage_etc_hosts: true
users:
  - name: devops
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...
runcmd:
  - echo "Node $i of $NODE_COUNT in cluster $CLUSTER_NAME" > /etc/motd
EOF
  
  # 5. Запуск
  virsh start "$VM_NAME"
  
  # 6. Ожидание IP
  for j in $(seq 1 30); do
    IP=$(virsh domifaddr "$VM_NAME" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
    if [ -n "$IP" ]; then
      echo "  $VM_NAME: $IP"
      break
    fi
    sleep 2
  done
done

echo "=== Cluster $CLUSTER_NAME deployed: $NODE_COUNT nodes ==="
```

### Сценарий 4: Диагностика проблем с ВМ в продакшене

Чек-лист быстрой диагностики при проблемах.

```bash
#!/bin/bash
# diagnose-vm.sh — быстрая диагностика ВМ
set -euo pipefail

VM_NAME="${1:?Usage: diagnose-vm.sh <vm-name>}"

echo "=== Diagnosing: $VM_NAME ==="

# 1. Состояние ВМ
echo "--- VM State ---"
virsh domstate "$VM_NAME"

# 2. Ресурсы
echo "--- Resources ---"
virsh domstats "$VM_NAME" | grep -E "(cpu|balloon|block)"

# 3. Логи
echo "--- Last 20 libvirt logs ---"
journalctl -u libvirtd --since "1 hour ago" | tail -20

# 4. QEMU process
echo "--- QEMU process ---"
ps aux | grep qemu-system | grep "$VM_NAME"

# 5. Кэш диска
echo "--- Disk cache mode ---"
virsh dumpxml "$VM_NAME" | grep -E "cache|io="

# 6. Сеть
echo "--- Network interfaces ---"
virsh domifaddr "$VM_NAME"

# 7. Проверка на ошибки образа
echo "--- Image check ---"
DISK_PATH=$(virsh dumpxml "$VM_NAME" | grep -oP "file='[^']+'" | head -1 | cut -d"'" -f2)
if [ -n "$DISK_PATH" ]; then
  qemu-img check "$DISK_PATH" 2>&1 | tail -5
fi

# 8. Проверка Steal Time (изнутри гостя, если доступен)
echo "--- Steal Time ---"
IP=$(virsh domifaddr "$VM_NAME" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
if [ -n "$IP" ]; then
  ssh -o ConnectTimeout=3 ubuntu@"$IP" "top -bn1 | head -5" 2>/dev/null || echo "SSH not available"
fi
```

### Сценарий 5: Live Migration с проверками

Безопасная миграция с pre-flight проверками.

```bash
#!/bin/bash
# safe-migrate.sh — безопасная live migration
set -euo pipefail

VM_NAME="${1:?Usage: safe-migrate.sh <vm-name>}"
DEST_HOST="${2:?Usage: safe-migrate.sh <vm-name> <dest-host>}"

echo "=== Pre-flight checks ==="

# 1. Проверка состояния ВМ
VM_STATE=$(virsh domstate "$VM_NAME" 2>/dev/null)
if [ "$VM_STATE" != "running" ]; then
  echo "FAIL: VM is not running (state: $VM_STATE)"
  exit 1
fi
echo "  VM state: OK"

# 2. Проверка connectivity до целевого хоста
if ! ssh -o ConnectTimeout=5 "$DEST_HOST" "echo OK" > /dev/null 2>&1; then
  echo "FAIL: Cannot connect to $DEST_HOST"
  exit 1
fi
echo "  Destination connectivity: OK"

# 3. Проверка версий libvirt/QEMU
SRC_VERSION=$(virsh version | head -1)
DST_VERSION=$(ssh "$DEST_HOST" "virsh version" | head -1)
echo "  Source libvirt: $SRC_VERSION"
echo "  Dest libvirt: $DST_VERSION"
if [ "$SRC_VERSION" != "$DST_VERSION" ]; then
  echo "  WARNING: Version mismatch"
fi

# 4. Проверка shared storage
echo "  Checking shared storage..."
virsh vol-list default | grep "$VM_NAME" > /dev/null || echo "  WARNING: Local storage only"

# 5. Миграция
echo "=== Starting migration ==="
virsh migrate --live --persistent --verbose \
  "$VM_NAME" "qemu+ssh://$DEST_HOST/system"

# 6. Проверка после миграции
echo "=== Post-migration check ==="
ssh "$DEST_HOST" "virsh list --all | grep $VM_NAME"
ssh "$DEST_HOST" "virsh domifaddr $VM_NAME"

echo "=== Migration completed ==="
```

## Дополнительная информация

- [Образы ВМ — Определения](./definitions.md) — глоссарий терминов.
- [Образы ВМ — Основные концепции](./basic_concepts.md) — форматы и стратегии хранилища.
- [Резервное копирование и восстановление ВМ](../kvm/vm_backup_dr.md) — стратегии бэкапа, DR, верификация.
- [Сетевая диагностика ВМ](../kvm/vm_network_troubleshooting.md) — диагностика сети, MTU, conntrack.
- [Sysctl чек-лист для KVM-хостов](../kvm/kvm_host_sysctl_checklist.md) — параметры ядра для продакшена.
- [Проброс GPU и PCI-устройств (VFIO)](../kvm/gpu_pci_passthrough.md) — GPU passthrough, NVMe.
- [KVM — Обзор и архитектура](../kvm/overview.md) — контекст гипервизора.
- [KVM — Управление ВМ](../kvm/management.md) — virsh, virt-install.
- [KVM — Оптимизация (2025–2026)](../kvm/performance_tuning_2026.md) — тюнинг CPU, памяти, I/O.
- [KVM — Мониторинг](../kvm/kvm_monitoring.md) — Prometheus, libvirt_exporter, Grafana.
- [KVM — Высокая доступность](../kvm/kvm_ha.md) — Pacemaker, DRBD, STONITH.
- [KVM — Диагностика и решение проблем](../kvm/troubleshooting.md) — troubleshooting.
- [KVM — Автоматизация](../kvm/kvm_automation.md) — Ansible, Terraform, Packer.
- [Автоматизация сборки образов](./image_automation.md) — Packer, CI/CD пайплайн.
