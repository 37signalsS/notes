# Вложенная виртуализация — Практические сценарии

В данном файле приведены практические инструкции по настройке вложенной виртуализации для архитектур x86_64 и ARM64, платформ управления (Libvirt, Proxmox, Vagrant, VMware, VirtualBox) и типовых задач DevOps/SRE/sysadmin в on-premises-средах.

## Определения

**Nested VT-x / SVM** — параметры модулей ядра KVM (`kvm_intel` и `kvm_amd`), активирующие проброс аппаратных инструкций виртуализации в гостевую систему.

**host-passthrough** — режим работы CPU, при котором ВМ получает все флаги и инструкции физического процессора. Обязательное условие для работы вложенной виртуализации с минимальными потерями производительности.

**Enlightened VMCS** — технология оптимизации для гипервизоров Microsoft (Hyper-V), снижающая накладные расходы на переключение контекста во вложенных средах за счёт прямого взаимодействия гипервизоров L0 и L1. Критична для работы Windows в качестве L1.

## Базовые концепции

### Порядок настройки (Workflow)

Реализация вложенности всегда требует двух последовательных шагов:
1.  **Уровень L0 (Хост):** Активация поддержки вложенности в параметрах модуля ядра или загрузчика ОС.
2.  **Уровень L1 (ВМ):** Настройка конфигурации виртуальной машины для проброса функций CPU (режим `host` или `passthrough`).

### Проверка аппаратной готовности
Перед началом настройки убедитесь, что на физическом хосте установлена утилита `virt-host-validate` (пакет `libvirt-clients`).

```bash
virt-host-validate
# → QEMU: Checking for device assignment IOMMU support : PASS
```

## Теоретические основы для практической настройки

### Почему host-passthrough обязателен для L1

Режим `host-passthrough` не просто «пробрасывает флаги» — он передаёт L1 полный аппаратный контекст физического CPU, включая структуры VMCS (Virtual Machine Control Structure). Без этого:

- **Отсутствие VMCS Shadowing:** L1 не может управлять собственными L2-гостями, потому что L0 не знает о структурах управления L2. Каждая привилегированная инструкция L2 вызывает VM-Exit в L0, а не в L1, что разрушает иерархию и снижает производительность в 2–5 раз.
- **Нет Extended Page Tables (EPT/RVI):** Эмуляция трансляции адресов (Shadow Page Tables) в L1 имеет накладные расходы до 30% на операцию памяти. Современные CPU (5th gen+ Intel, Zen 2+ AMD) требуют аппаратного Nested EPT для приемлемой производительности.
- **Потеря enlightenments:** Для Windows L1 теряются Hyper-V enlightenments (`evmcs`, `vapic`), без которых Hyper-V в L1 работает крайне медленно или не запускается вообще.

### Взаимодействие NUMA и вложенной виртуализации

При настройке L1 учитывайте два уровня NUMA:

1. **NUMA L0 → L1:** Если L1 размещена на NUMA-узле 0, а её vCPU привязаны к ядрам узла 1, каждый доступ к памяти добавляет 30–50 нс задержки через межъузловой интерconnect (UPI/QPI/Infinity Fabric).
2. **NUMA L1 → L2:** Гипервизор L1 видит только виртуальную топологию. Поэтому `virsh cpu-baseline` и `lscpu` внутри L1 покажут виртуальные ядра, а не физические pCPU L0. Для корректного пиннинга L2 используйте `<cputune>` в XML L1 с привязкой к конкретным vCPU L1.

**Практическое правило:** Размещайте L1 и её L2 на одном NUMA-узле L0. Используйте `numactl --hardware` на L0 для построения карты топологии перед размещением.

### Взаимодействие cgroups и планировщика

На L0 libvirt использует cgroups для ограничения ресурсов L1. Важно понимать каскадный эффект:

- **cpu_shares:** Относительный вес. Если L1 имеет `shares=2048`, а соседняя ВМ — `1024`, L1 получит в 2 раза больше CPU при контенции. Это напрямую влияет на доступность CPU для L2.
- **cpu_quota:** Абсолютный лимит. `vcpu_quota=80000` (80% одного ядра за 100ms) означает, что суммарное время CPU для L1 (включая все L2) не превысит 80%. Если L1 перегружена L2, она начнёт делить время с другими ВМ на хосте.
- **blkio weight:** Влияет на приоритет дискового I/O. Низкий вес для L1 может привести к starvation всех L2 при высокой активности других ВМ.

## Практические сценарии

### Сценарий 1: Настройка физического хоста (L0)

#### Архитектура x86_64 (Intel и AMD)
1. **Проверка статуса:**
   ```bash
   # Intel
   cat /sys/module/kvm_intel/parameters/nested
   # AMD
   cat /sys/module/kvm_amd/parameters/nested
   # → 'Y' или '1' — включено, 'N' или '0' — выключено.
   ```
2. **Активация (если выключено):**
   Создайте файл `/etc/modprobe.d/kvm-nested.conf`:
   ```text
   # Для систем Intel
   options kvm_intel nested=1
   # Для систем AMD (обычно включено по умолчанию в ядрах 5.15+)
   options kvm_amd nested=1
   ```
3. **Перезагрузка модулей:**
   ```bash
   sudo modprobe -r kvm_intel && sudo modprobe kvm_intel
   ```

#### Архитектура ARM64 (Apple Silicon, Ampere)
Требуется ядро версии **6.16+** (введена полная поддержка FEAT_NV2) и QEMU **10.1+**.
1. **Параметры загрузки:**
   Отредактируйте `/etc/default/grub` (или конфиг вашего загрузчика):
   ```text
   GRUB_CMDLINE_LINUX_DEFAULT="... kvm-arm.mode=nested"
   ```
2. **Проверка в dmesg:**
   ```bash
   dmesg | grep -i "kvm.*nested"
   # → kvm [1]: VHE+NV2 mode initialized successfully
   ```

### Сценарий 2: Настройка ВМ первого уровня (L1) в различных гипервизорах

#### Libvirt / virsh
Отредактируйте XML конфигурацию (`virsh edit <vm_name>`):
```xml
<cpu mode='host-passthrough' check='none'>
  <feature policy='require' name='vmx'/> <!-- Для Intel -->
  <feature policy='require' name='svm'/> <!-- Для AMD -->
</cpu>
```

#### Proxmox VE
Установите тип процессора `host`:
```bash
qm set <vmid> --cpu host
```

#### Vagrant
В `Vagrantfile` для провайдера `libvirt`:
```ruby
config.vm.provider :libvirt do |lv|
  lv.nested = true
  lv.cpu_mode = 'host-passthrough'
end
```

#### VMware Workstation / Player
В настройках ВМ: `Settings` → `Processors` → установите галочку **"Virtualize Intel VT-x/EPT or AMD-V/RVI"**.

#### VirtualBox
Через CLI (графический интерфейс часто блокирует эту опцию):
```bash
VBoxManage modifyvm "<vm_name>" --nested-hw-virt on
```

### Сценарий 3: Оптимизация для Windows (Hyper-V) в L1
Для работы Hyper-V внутри KVM необходимо включить «улучшения» (enlightenments) в XML libvirt:
```xml
<features>
  <hyperv>
    <relaxed state='on'/>
    <vapic state='on'/>
    <spinlocks state='on' retries='8191'/>
    <evmcs state='on'/> <!-- Critical for Intel performance -->
  </hyperv>
</features>
```

### Сценарий 4: Проверка внутри гостевой системы (L1)
Внутри ВМ L1 должны быть видны флаги аппаратного ускорения:
```bash
grep -Eoc '(vmx|svm)' /proc/cpuinfo
# → Результат > 0 означает успех. На ARM64 проверяйте 'virt' или 'el2'.
```

### Сценарий 5: Привязка vCPU и планирование CPU для вложенных сред

Правильный пиннинг vCPU критически важен для производительности вложенных сред. Неправильная привязка вызывает межъузловой трафик и contention.

**Алгоритм планирования:**

1. **Определите топологию L0:**
   ```bash
   lscpu -e
   # → список физических ядер, NUMA-узлов и логических процессоров
   
   numactl --hardware
   # → available: 2 nodes (0-1)
   # → node 0 cpus: 0 1 2 3 4 5 6 7
   # → node 1 cpus: 8 9 10 11 12 13 14 15
   ```

2. **Выделите L1 на одном NUMA-узле L0:**
   ```xml
   <domain type='kvm'>
     <name>l1-hypervisor</name>
     <memory unit='GiB'>16</memory>
     <vcpu placement='static'>8</vcpu>
     <numatune>
       <memory mode='strict' nodeset='0'/>
       <cpus cpuset='0-7' nodeset='0'/>
     </numatune>
     <cputune>
       <vcpupin vcpu='0' cpuset='0'/>
       <vcpupin vcpu='1' cpuset='1'/>
       <vcpupin vcpu='2' cpuset='2'/>
       <vcpupin vcpu='3' cpuset='3'/>
       <vcpupin vcpu='4' cpuset='4'/>
       <vcpupin vcpu='5' cpuset='5'/>
       <vcpupin vcpu='6' cpuset='6'/>
       <vcpupin vcpu='7' cpuset='7'/>
       <emulatorpin cpuset='0-7'/>
     </cputune>
   </domain>
   ```

3. **Внутри L1 привяжите vCPU L2 к pCPU L1:**
   ```xml
   <!-- XML L2 внутри L1 -->
   <domain type='kvm'>
     <name>l2-guest</name>
     <vcpu placement='static'>2</vcpu>
     <cputune>
       <vcpupin vcpu='0' cpuset='0'/>
       <vcpupin vcpu='1' cpuset='1'/>
     </cputune>
   </domain>
   ```

**Валидация:**
```bash
# Проверка пиннинга L1 на L0
virsh vcpupin l1-hypervisor
# → vcpu 0: cpuset="0"
# → vcpu 1: cpuset="1"

# Проверка NUMA-расположения
virsh numatune l1-hypervisor
# → memory: mode=strict, nodeset=0
# → cpus: cpuset="0-7", nodeset=0

# Внутри L1: проверка пиннинга L2
virsh -c qemu+ssh://l1-hypervisor/system vcpupin l2-guest
# → vcpu 0: cpuset="0"
# → vcpu 1: cpuset="1"
```

**Типичные ошибки:**
- Не привязали `emulatorpin` — эмулятор может мигрировать по всем ядрам, нарушая изоляцию.
- Привязали L1 к гипертредам (SMT siblings) — производительность снижается на 20–40% из-за contention на кэш L1.
- Забыли про `nodeset` в `<numatune>` — память L1 может разместиться на другом NUMA-узле, чем vCPU.

### Сценарий 6: Живая миграция L1 с учётом вложенности

Live-миграция L1 в production-средах требует учёта наличия запущенных L2:

**Ограничения:**
- Миграция L1 с активными L2 возможна только если L2 поддерживают **incoming migration** (QEMU 8.0+, libvirt 9.0+).
- При миграции L1 все L2 автоматически мигрируют вместе с ней (cow-диски мигрируют как changed blocks).
- Для миграции L1 без останова L2 требуется общий доступ к хранилищу (shared storage: NFS, Ceph, GlusterFS) между узлами L0.

**Пошаговая инструкция:**

1. **Подготовка shared storage:**
   ```bash
   # На L0-узлах смонтируйте общий ресурс
   sudo mount -t nfs nfs-server:/var/lib/libvirt/images /var/lib/libvirt/images
   ```

2. **Настройка миграции в XML L1:**
   ```xml
   <domain type='kvm'>
     <name>l1-hypervisor</name>
     <memory unit='GiB'>16</memory>
     <vcpu>8</vcpu>
     <devices>
       <disk type='file' device='disk'>
         <driver name='qemu' type='qcow2'/>
         <source file='/var/lib/libvirt/images/l1-root.qcow2'/>
         <target dev='vda' bus='virtio'/>
       </disk>
     </devices>
   </domain>
   ```

3. **Выполнение миграции:**
   ```bash
   # Миграция L1 на узел destination
   virsh migrate --live l1-hypervisor qemu+ssh://dest-host/system
   # → Migration status: active
   # → Migration: [100 %]
   ```

4. **Валидация после миграции:**
   ```bash
   # Проверка состояния L1 на целевом узле
   virsh list --all
   # → l1-hypervisor running

   # Проверка состояния L2 внутри L1
   virsh -c qemu+ssh://l1-hypervisor/system list --all
   # → l2-guest running
   ```

### Сценарий 7: Резервное копирование и восстановление L1/L2

Для production-сред обязательно регулярное резервное копирование как L1, так и L2.

**Стратегия бэкапов:**

1. **L1 (гипервизор):**
   - Бэкап XML-конфигурации: `virsh dumpxml l1-hypervisor > l1-hypervisor.xml`
   - Бэкап дисков L1: `qemu-img convert -p /var/lib/libvirt/images/l1-root.qcow2 /backup/l1-root-$(date +%F).qcow2`
   - Для production используйте **incremental backup** (QEMU dirty bitmap), чтобы не останавливать L1:
     ```bash
     # Создание bitmap
     qemu-img bitmap --add /var/lib/libvirt/images/l1-root.qcow2 backup-bitmap
     
     # Инкрементальный экспорт
     qemu-img convert -p -r l1-root.qcow2 -F qcow2 -B backup-base.qcow2 /backup/l1-incremental.qcow2
     ```

2. **L2 (вложенный гость):**
   - Бэкап изнутри L1: `virsh dumpxml l2-guest > l2-guest.xml`
   - Бэкап диска L2: `qemu-img convert -p /var/lib/libvirt/images/l2-disk.qcow2 /backup/l2-disk.qcow2`
   - Используйте **snapshots** для быстрых бэкапов без останова:
     ```xml
     <domain type='kvm'>
       <name>l2-guest</name>
       <devices>
         <disk type='file' device='disk'>
           <source file='/var/lib/libvirt/images/l2-disk.qcow2'/>
           <target dev='vda' bus='virtio'/>
           <snapshot>
             <name>snap-2026-09-11</name>
           </snapshot>
         </disk>
       </devices>
     </domain>
     ```

3. **Восстановление:**
   ```bash
   # Остановите L1
   virsh destroy l1-hypervisor
   
   # Восстановите диск
   qemu-img convert -p /backup/l1-root-2026-09-11.qcow2 /var/lib/libvirt/images/l1-root.qcow2
   
   # Переопределите XML
   virsh define l1-hypervisor.xml
   
   # Запустите L1
   virsh start l1-hypervisor
   ```

### Сценарий 8: Мониторинг и наблюдаемость вложенных сред

Для SRE критически важно отслеживать состояние не только L0 и L1, но и влияние L2 на общую производительность.

**Метрики для мониторинга:**

1. **L0 (хост):**
   ```bash
   # VM-Exits — индикатор накладных расходов вложенности
   sudo kvm_stat -1 | grep -E 'exit|mmio|pio'
   
   # Статистика L1
   virsh domstats l1-hypervisor --cpu-total --memory --balloon
   # → cpu.time: 1234567890123
   # → balloon.actual: 8589934592
   
   # Проверка steal_time — признак контенции CPU
   vmstat 1 5
   # → st (steal) > 5% означает, что L1 не хватает allocated CPU
   ```

2. **L1 (гипервизор):**
   ```bash
   # Внутри L1: нагрузка от L2
   top -b -n1 | head -20
   
   # Статистика KVM в L1
   sudo kvm_stat
   ```

3. **L2 (гость):**
   ```bash
   # Внутри L2: стандартные метрики ОС
   uptime
   iostat -x 1 5
   ```

**Prometheus + node_exporter:**
- Экспортируйте `node_cpu_seconds_total` с labels `mode` для отслеживания `steal` времени.
- Используйте `libvirt_exporter` для сбора метрик `libvirt_domain_info` и `libvirt_domain_state`.

**Alerter на key scenarios:**
- `steal_time > 10%` на L0 → возможен overcommit CPU
- `kvm_stat exits > 100k/s` → высокая нагрузка VM-Exits, проверьте CPU mode L1
- `balloon.actual < balloon.current * 0.8` → L1 испытывает дефицит памяти

### Сценарий 9: Автоматизированное развертывание вложенных сред

Для DevOps-сред используйте IaC-инструменты:

**Ansible Playbook для подготовки L0:**
```yaml
- name: Enable nested virtualization
  hosts: kvm-hosts
  tasks:
    - name: Enable nested for Intel
      lineinfile:
        path: /etc/modprobe.d/kvm-nested.conf
        line: "options kvm_intel nested=1"
      when: ansible_processor_vendor == "GenuineIntel"

    - name: Enable nested for AMD
      lineinfile:
        path: /etc/modprobe.d/kvm-nested.conf
        line: "options kvm_amd nested=1"
      when: ansible_processor_vendor == "AuthenticAMD"

    - name: Reload kvm modules
      modprobe:
        name: "{{ item }}"
        state: reloaded
      loop: "{{ ['kvm_intel', 'kvm_amd'] | select('match', ansible_processor_vendor | regex_search('Intel|AMD')) | list }}"
```

**Terraform + libvirt provider для создания L1:**
```hcl
resource "libvirt_domain" "l1_hypervisor" {
  name   = "l1-hypervisor"
  memory = "16384"
  vcpu   = 8

  cpu {
    mode = "host-passthrough"
  }

  disk {
    volume_id = libvirt_volume.l1_root.id
  }

  network_interface {
    network_name = "default"
    wait_for_lease = true
  }
}
```

**Валидация:**
```bash
# Проверка, что L1 создана
virsh list --all
# → l1-hypervisor running

# Проверка вложенности
virsh console l1-hypervisor
# → inside L1: egrep -c '(vmx|svm)' /proc/cpuinfo → > 0
```

### Сценарий 10: Отказоустойчивость и аварийное восстановление

**Рекомендации:**
1. **Избегайте L3:** Глубина вложенности больше L2 экспоненциально увеличивает накладные расходы и время восстановления. Используйте L2 только когда изоляция гипервизора обязательна.
2. **Резервное копирование конфигураций:** Храните XML всех L1 в Git-репозитории. Это позволяет восстановить ВМ за минуты:
   ```bash
   git add l1-hypervisor.xml l2-guest.xml
   git commit -m "Add nested configs"
   ```
3. **HA для L1:** Используйте кластер libvirt ( Pacemaker/Corosync ) для автоматического перезапуска L1 на другом узле L0 при отказе. L2 будут автоматически перезапущены вместе с L1.
4. **Тестирование восстановления:** Раз в квартал выполняйте drill-down восстановление L1+L2 на тестовом стенде.

## Диагностика и решение проблем

### Типичные проблемы при настройке

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `modprobe -r` выдает ошибку | Модуль занят активными ВМ | Остановите все ВМ на хосте перед перезагрузкой модуля. |
| Флаги в L1 не появились | CPU mode не `host` | Проверьте, что в конфиге не указана модель (например, `qemu64`). |
| Ошибка `VMX disabled by BIOS` | Заблокировано в прошивке | Включите VT-x/AMD-V в BIOS/UEFI физического сервера L0. |
| Сеть в L2 недоступна | Блокировка MAC-адресов | Включите `promisc` mode или разрешите MAC Spoofing на уровне L1. |
| Крайне низкая производительность L2 | Отсутствие аппаратного ускорения | Убедитесь, что в L1 загружен модуль `kvm_intel` или `kvm_amd`. |
| L2 не запускается, L1 имеет флаги VT | CPU mode L1 не `host-passthrough` | Измените `<cpu mode='host-passthrough'>` в XML L1. |
| Производительность L2 в 2–3 раза ниже L1 | Отсутствует VMCS Shadowing или Virtual EPT | Проверьте поддержку в ядре L0 (6.12+), обновите прошивку L0. |
| L2 видит меньше vCPU, чем выделено | L1 не имеет достаточного количества pCPU | Увеличьте vCPU L1 или улучшите пиннинг на L0. |
| OOM-kill L2 при наличии свободной памяти | Ballooning в L1 уменьшил доступную память | Отключите ballooning в L1 или увеличьте maxmem. |
| `kvm: Nested Virtualization disabled` в логах | Вложенность выключена в BIOS/UEFI L0 | Включите VT-x/AMD-V в прошивке. |
| Высокий `halt_exits` на L0 | L1 активно потребляет CPU, starving L2 | Проверьте `virsh domstats` L1, уменьшите overcommit. |
| `VMX disabled by BIOS` в логах L1 | BIOS L0 блокирует VT-x | Включите virtualization extensions в BIOS. |
| L1 мигрирует, но L2 останавливаются | Отсутствует shared storage для L2 | Используйте NFS/Ceph для дисков L2 или выполните cold migration. |
| Потеря пакетов в L2 при высокой нагрузке | Нет Multi-queue VirtIO или Posted Interrupts | Включите `queues='4'` в драйвере и проверьте IOMMU на L0. |

### Сценарий 11: Мониторинг вложенных сред (L0 → L1 → L2)

Для production-сред необходим иерархический мониторинг: метрики собираются на каждом уровне и коррелируются.

**Настройка на L0 (хост):**

1. **Установка node_exporter и libvirt_exporter:**
```bash
# node_exporter (системные метрики L0)
sudo user --no-create-home --shell /bin/false node_exporter
wget https://github.com/prometheus/node_exporter/releases/latest/download/node_exporter-1.8.*.linux-amd64.tar.gz
tar xzf node_exporter-*.tar.gz
sudo cp node_exporter-*/node_exporter /usr/local/bin/

# libvirt_exporter (метрики ВМ)
# См. подробности в kvm/kvm_monitoring.md
```

2. **Ключевые метрики для алертов:**
```promql
# Steal time > 5% — L1 не хватает CPU
100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 5

# VM-Exits > 100k/s — высокая нагрузка на гипервизор
rate(kvm_stat_exits_total[5m]) > 100000

# Balloon deficit — L1 испытывает дефицит памяти
libvirt_domain_info_balloon_actual < libvirt_domain_info_balloon_target * 0.8

# Количество запущенных L1 ВМ
sum(libvirt_domain_state{state="running"}) by (instance)
```

3. **Dashboards в Grafana:**
- Используйте готовый дашборд [Node Exporter Full](https://grafana.com/grafana/dashboards/1860) для L0.
- Для метрик libvirt: [KVM/libvirt Dashboard](https://grafana.com/grafana/dashboards/12145).

**Настройка внутри L1:**

Установите `node_exporter` внутри L1 для мониторинга ресурсов, потребляемых L2:
```bash
# Внутри L1
sudo user --no-create-home --shell /bin/false node_exporter
# ... установка аналогична L0

# Prometheus на L0 должен скрапить L1 по отдельному порту:
# - targets: ["192.168.122.10:9100"]  # L1 host
```

**Валидация:**
```bash
# На L0: проверка сбора метрик
curl -s http://localhost:9090/api/v1/query?query=libvirt_domain_state | jq .

# Проверка scrape targets в Prometheus:
# http://prometheus:9090/targets → все.targets = UP
```

### Сценарий 12: Сетевые настройки для вложенных сред

Вложенные среды требуют особого внимания к сети: трафик проходит через несколько уровней bridge/NAT.

**Архитектура сети:**
```
Физическая сеть (L0)
    │
    ├── bridge br0 (L0)
    │       │
    │       ├── virbr0 (L1 NAT) ──── L2 гости
    │       │
    │       └── macvtap/bridge (L1) ──── L2 гости (production)
    │
    └── physical eth0
```

**Production-режим: bridge на L0 + bridge на L1:**

1. **На L0 настройте bridge:**
```bash
# /etc/netplan/01-bridge.yaml (Ubuntu)
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: false
  bridges:
    br0:
      interfaces: [eth0]
      addresses: [192.168.1.10/24]
      gateway4: 192.168.1.1
      nameservers:
        addresses: [8.8.8.8]
```

2. **XML для L1 с bridge:**
```xml
<interface type='bridge'>
  <source bridge='br0'/>
  <model type='virtio'/>
  <driver name='vhost' queues='4'/>
</interface>
```

3. **Настройка MTU для оверлейных сетей:**
Если L1 использует Geneve/VXLAN, установите MTU в L2 на 1400–1450:
```bash
# Внутри L2
sudo ip link set dev eth0 mtu 1450
```

**Валидация:**
```bash
# Проверка MTU на всех уровнях
ip link show | grep mtu

# Тест сетевой связности L2 → L0
ping -M do -s 1472 192.168.1.1  # 1500 - 28 (headers) = 1472 max payload

# Проверка bridge
brctl show
```

### Сценарий 13: Запуск контейнеров (Docker) внутри L2

Вложенная виртуализация часто используется для запуска контейнеров в изолированной среде (CI/CD, тестирование).

**Требования:**
- L2 с включенным KVM (CPU mode `host-passthrough`)
- Docker/containerd установлены внутри L2

**Установка Docker в L2:**
```bash
# Внутри L2 (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Проверка работы KVM внутри L2 (для Docker с KVM)
egrep -c '(vmx|svm)' /proc/cpuinfo
# → > 0 (если L1 настроен корректно)
```

**Оптимизация Docker в виртуализированной среде:**
```json
// /etc/docker/daemon.json
{
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "default-runtime": "runc",
  "features": {
    "buildkit": true
  }
}
```

**Проблема: Docker-in-Docker (DinD) vs Docker-outside-of-Docker (DooD):**
- **DinD:** Docker daemon внутри L2, изолированный от L1. Требует `--privileged` или `--cap-add SYS_ADMIN`.
- **DooD:** Проброс Docker socket из L1 в L2. Проще, но менее безопасно.

**Пример DooD (рекомендуется для CI/CD):**
```bash
# Запуск L2 с пробросом Docker socket
docker run -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/bin/docker:/usr/bin/docker \
  -it ubuntu:22.04 bash
```

**Валидация:**
```bash
# Внутри L2: проверка Docker
docker run --rm hello-world

# Проверка KVM внутри Docker (если нужен)
docker run --rm --privileged alpine sh -c "ls /dev/kvm"
```

### Сценарий 14: Интеграция с CI/CD (GitLab CI)

Вложенная виртуализация используется для запуска изолированных раннеров CI/CD в on-premises средах.

**Архитектура:**
```
GitLab Server
    │
    └── GitLab Runner (L0)
            │
            └── Эфемерные ВМ (L1) с Docker executor
                    │
                    └── Контейнеры (L2) для сборки
```

**Настройка GitLab Runner на L0:**

1. **Установка runner:**
```bash
# На L0
curl -L --output /usr/local/bin/gitlab-runner \
  https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-amd64
chmod +x /usr/local/bin/gitlab-runner
gitlab-runner install
gitlab-runner start
```

2. **Конфигурация executor (Docker):**
```toml
# /etc/gitlab-runner/config.toml
concurrent = 4
check_interval = 0

[[runners]]
  name = "kvm-nested-runner"
  url = "https://gitlab.example.com/"
  token = "YOUR_TOKEN"
  executor = "docker"
  [runners.docker]
    image = "alpine:latest"
    privileged = false
    volumes = ["/cache"]
    # Для KVM внутри контейнеров:
    # privileged = true
    # devices = ["/dev/kvm"]
```

3. **Пример `.gitlab-ci.yml` для использования KVM:**
```yaml
stages:
  - test

kvm-test:
  stage: test
  image: ubuntu:22.04
  tags:
    - kvm-nested
  script:
    - apt-get update && apt-get install -y qemu-kvm
    - egrep -c '(vmx|svm)' /proc/cpuinfo
    - echo "KVM available inside CI container"
```

**Валидация:**
```bash
# Проверка регистрации runner
gitlab-runner list

# Тест runner
gitlab-runner exec docker test-job
```

### Диагностические команды

```bash
# Быстрая проверка статуса вложенности на L0
cat /sys/module/kvm_intel/parameters/nested && egrep -c '(vmx|svm)' /proc/cpuinfo

# Проверка IOMMU
dmesg | grep -iE 'DMAR|IOMMU'

# Проверка VM-Exits
sudo kvm_stat -1 | head -20

# Проверка balloon и steal time
virsh domstats l1-vm --cpu-total --memory
vmstat 1 5

# Проверка сети (bridge, MTU)
brctl show
ip link show | grep mtu

# Проверка Docker в L2
docker run --rm hello-world

# Проверка GitLab Runner
gitlab-runner list
curl -s http://localhost:9252/metrics | grep gitlab_runner
```

## Дополнительная информация

### Связанные файлы

- [Вложенная виртуализация: Определения и концепции](./definitions_and_concepts.md) — архитектура, аппаратные требования, оптимизации ядра.
- [Вложенная виртуализация: Дополнительная информация](./additional_info.md) — глубкий разбор производительности, NUMA-топологии, безопасности и хранения.
- [KVM — Управление через virsh](../kvm/management.md) — операции жизненного цикла ВМ.
- [Оптимизация KVM (2026)](../kvm/performance_tuning_2026.md) — тюнинг CPU, памяти и дисков.
- [Мониторинг KVM: Prometheus, libvirt_exporter, Grafana](../kvm/kvm_monitoring.md) — построение стека мониторинга.
- [Безопасность KVM-хостов](../kvm/kvm_security_hardening.md) — sVirt, SELinux, AppArmor.
- [Сетевые основы KVM](../kvm/kvm_networking_fundamentals.md) — NAT, bridge, nwfilter.
- [Автоматизация KVM: Ansible, Terraform](../kvm/kvm_automation.md) — IaC для KVM.
- [Резервное копирование ВМ (KVM)](../kvm/vm_backup_dr.md) — стратегии бэкапа.
- [Высокая доступность KVM](../kvm/kvm_ha.md) — Pacemaker, DRBD.
