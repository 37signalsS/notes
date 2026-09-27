# Диагностика и решение проблем KVM

В данном файле рассматриваются методы выявления и устранения типовых проблем при работе с KVM: деградация производительности, ошибки прав доступа (MAC), проблемы управления, сетевые сбои и ошибки живой миграции.

## Определения

**sVirt (Secure Virtualization)** — технология интеграции гипервизора с системами мандатного управления доступом (AppArmor, SELinux) для изоляции процессов ВМ.

**QEMU Guest Agent (QGA)** — демон внутри гостевой ОС, обеспечивающий выполнение команд хоста (заморозка ФС, получение IP) через канал `virtio-serial`.

**VM-Exit** — событие выхода процессора из гостевого режима в режим гипервизора. Аномальное количество выходов указывает на неэффективную эмуляцию.

**CPU Steal Time** — время, в течение которого виртуальный процессор ожидал физический CPU, пока гипервизор обслуживал другие процессы (признак перегрузки хоста).

**CCD/CCX Awareness** — учет внутренней топологии процессоров (особенно AMD EPYC) при привязке vCPU для минимизации задержек межъядерного взаимодействия.

**Hugepages** — механизм использования страниц памяти большого размера (2МБ или 1ГБ), снижающий нагрузку на TLB и ускоряющий работу с RAM.

**virtlogd** — демон управления журналами QEMU. Отвечает за ротацию и безопасное хранение логов ВМ в `/var/log/libvirt/qemu/`.

**virtlockd** — демон блокировки файлов ВМ. Предотвращает одновременный запуск одной ВМ с нескольких хостов при использовании общих хранилищ (NFS, Ceph).

**OOM (Out of Memory)** — состояние, при котором ядро завершает процессы для освобождения памяти. В контексте KVM как хост, так и гость могут быть завершены OOM-killer'ом.

**cgroup blkio** — подсистема cgroup для контроля и ограничения дискового I/O ВМ.

**VFIO (Virtual Function I/O)** — механизм прямого проброса PCI-устройств в ВМ. Требует включенного IOMMU и отвязки устройства от драйвера хоста.

**macvtap** — виртуальный интерфейс, объединяющий мост и прямой доступ к физическому NIC через MAC-адрес. В bridge-режиме имеет ограничение на one-way трафик между хостами.

**Multi-Queue VirtIO (MQ)** — многопоточная обработка очередей VirtIO. Количество очередей должно соответствовать количеству vCPU для максимальной пропускной способности.

**io_uring** — современный интерфейс асинхронного I/O в Linux, который QEMU использует для эффективной работы с дисковыми образами, снижая нагрузку на CPU при интенсивных операциях.

## Основные концепции

### Основные источники диагностической информации

| Ресурс | Путь / Команда | Описание |
| :--- | :--- | :--- |
| **Логи конкретной ВМ** | `/var/log/libvirt/qemu/<имя_вм>.log` | Вывод процесса QEMU, ошибки эмуляции и устройств. |
| **Системный журнал** | `journalctl -u libvirtd` | Ошибки демона управления, проблемы с мостами и хранилищами. |
| **Аудит безопасности** | `dmesg \| grep -iE 'apparmor\|selinux'` | Блокировки доступа к файлам образов или сокетам. |
| **Статистика домена** | `virsh domstats <имя_вм>` | Метрики использования CPU, RAM, I/O и сети. |
| **Статистика ядра KVM** | `sudo kvm_stat` | Реальное время: прерывания, выходы (exits), MSR. |
| **Журналы virtlogd** | `journalctl -u virtlogd` | Ошибки ротации и записи логов ВМ. |
| **Журналы virtlockd** | `journalctl -u virtlockd` | Ошибки блокировки файлов ВМ на shared storage. |
| **Журналы QEMU (QMP)** | `/var/run/libvirt/qemu/<domain>.monitor` | JSON-интерфейс управления QEMU, доступный через socat. |

### Алгоритм системной диагностики

Диагностика KVM строится на стандартной методологии Troubleshooting (Bottom-up), адаптированной под стек виртуализации.

**Шаг 1: Определение симптома**
- ВМ не запускается / зависает / работает медленно / недоступна по сети.
- Определите: проблема на хосте (L0), в конкретной ВМ (L1) или в сети/хранилище.

**Шаг 2: Сбор данных**
```bash
# Общее состояние хоста
uptime && free -h && df -h /var/lib/libvirt/images

# Состояние libvirt
systemctl status libvirtd virtlogd virtlockd
virsh list --all
virsh pool-list --all
virsh net-list --all

# Логи за последний час
journalctl -u libvirtd --since "1 hour ago" --no-pager
```

**Шаг 3: Изоляция компонента**
- Если `libvirtd` не активен → проблема в сервисе.
- Если ВМ не стартует → проверьте XML (`virsh dumpxml`), лог ВМ, AppArmor/SELinux.
- Если сеть не работает → проверьте bridge/DHCP/firewall.
- Если диск тормозит → проверьте формат (qcow2 vs raw), io_uring, MQ, cgroup blkio.

**Шаг 4: Гипотеза и проверка**
- Сравните конфигурацию рабочей и проблемной ВМ (`virsh dumpxml` diff).
- Проверьте последние изменения: обновление пакетов, kernel, libvirt.

**Шаг 5: Исправление и валидация**
- Примените исправление.
- Проверьте метрики (`virsh domstats`, `kvm_stat`).
- Убедитесь, что проблема не регрессирует.

### Анализ событий через kvm_stat

Инструмент `kvm_stat` позволяет выявить причины деградации производительности без доступа к гостю:
*   **`exits`**: Если > 100 000/сек на ядро — проверьте использование VirtIO (гость делает слишком много "тяжелых" системных вызовов).
*   **`halt_exits`**: Высокое значение при нагрузке внутри гостя говорит о том, что планировщик хоста не дает ВМ достаточно ресурсов.
*   **`mmio_exits`**: Указывает на интенсивный ввод-вывод через эмулируемые устройства.

### Механизм отката на TCG (Fallback)

Если аппаратное ускорение KVM недоступно (BIOS, вложенная виртуализация), QEMU может переключиться в режим эмуляции **TCG**.
**Признак:** Высокая нагрузка на CPU хоста при крайне медленной работе ВМ. В логах: `falling back to tcg`.

### Журналы libvirt: virtlogd и virtlockd

Современные версии libvirt (≥6.0) разделили логику на отдельные демоны.

**virtlogd:**
- Отвечает за запись логов ВМ изолированно от основного демона.
- Логи хранятся в `/var/log/libvirt/qemu/<имя_вм>.log`.
- Если логи не появляются или не ротируются → проверьте `journalctl -u virtlogd`.

**virtlockd:**
- Использует файловые блокировки (`flock`) для предотвращения одновременного запуска ВМ с нескольких узлов.
- Актуален для shared storage (NFS, GlusterFS).
- Если ВМ не стартует с ошибкой `Device or resource busy` → проверьте, нет ли висячих lock-файлов в `/var/run/libvirt/lock/`.

### Отладка QEMU: core dump и GDB

При падениях QEMU или libvirtd можно получить дамп памяти для анализа.

**Включение core dump для QEMU:**
```bash
# В /etc/systemd/system/libvirtd.service.d/override.conf
[Service]
LimitCORE=infinity

# Перезагрузка демона
systemctl daemon-reload
systemctl restart libvirtd
```

**Анализ core dump:**
```bash
# Найти core файл
coredumpctl list | grep qemu
coredumpctl dump <PID> -o /tmp/qemu-core

# Анализ через GDB (требует debug-символы qemu-system-x86-dbg)
gdb /usr/bin/qemu-system-x86_64 /tmp/qemu-core
(gdb) bt
```

## Практические сценарии

### Сценарий 1: Исправление ошибок прав доступа (Permission Denied)

AppArmor или SELinux могут блокировать доступ QEMU к образам дисков вне стандартных путей.

**Решение для AppArmor (Ubuntu/Debian):**
```bash
# Добавление пути в пользовательский конфиг
echo '/mnt/storage/vms/** rwk,' | sudo tee /etc/apparmor.d/abstractions/libvirt-qemu.d/custom-paths
sudo systemctl restart apparmor
```

**Решение для SELinux (RHEL/Fedora):**
```bash
sudo semanage fcontext -a -t virt_image_t "/mnt/storage/vms(/.*)?"
sudo restorecon -Rv /mnt/storage/vms
```

### Сценарий 2: Исправление работы консоли (virsh console)

Если `virsh console` подключается, но не отображает вывод, настройте гостевой Linux для вывода в последовательный порт.

В файле `/etc/default/grub` (внутри ВМ):
```text
GRUB_CMDLINE_LINUX_DEFAULT="... console=tty0 console=ttyS0,115200n8"
```
Затем выполните `update-grub` и перезагрузитесь.

### Сценарий 3: Оптимизация топологии CPU и NUMA

На современных процессорах (AMD EPYC Turin, Intel Granite Rapids) некорректная привязка ядер ведет к падению производительности на 20-30%.

**Диагностика:**
```bash
# Проверка локальности памяти ВМ относительно NUMA-узлов
numastat -p <PID_QEMU>
```

**Решение (XML):**
Привязывайте vCPU к ядрам внутри одного CCD (Core Complex Die) для AMD или одного сокета для Intel.
```xml
<cputune>
  <vcpupin vcpu='0' cpuset='2'/>
  <vcpupin vcpu='1' cpuset='3'/>
  <emulatorpin cpuset='0-1'/> <!-- Служебные потоки QEMU на отдельные ядра -->
</cputune>
```

### Сценарий 4: Troubleshooting памяти и Hugepages

Если ВМ объемом > 32 ГБ RAM работает медленно, используйте Hugepages 1ГБ.

**Проблема:** Память фрагментирована, и Hugepages не выделяются.
**Диагностика:** `cat /proc/buddyinfo`.
**Решение:** Резервируйте страницы при загрузке хоста через параметры GRUB: `hugepagesz=1G hugepages=64`. Отключите Transparent Hugepages (THP) для баз данных, так как они вызывают фризы при дефрагментации.

### Сценарий 5: Проблемы живой миграции (Live Migration)

**Типичные ошибки:**
1.  **Guest CPU is not compatible**: Хосты имеют разные наборы флагов CPU. Используйте модель `host-model` вместо `host-passthrough`.
2.  **Migration does not converge**: Гость пишет в память быстрее, чем она передается.
    *   *Решение:* Включите `auto-converge` (замедление vCPU) или перейдите в режим `post-copy`.
    ```bash
    virsh migrate --live --postcopy <имя_вм> qemu+ssh://dest-host/system
    ```

### Сценарий 6: Анализ "Noisy Neighbor" и Steal Time

Если ВМ тормозит при низкой нагрузке внутри.
1.  Выполните `top` на госте.
2.  Смотрите на поле `%st` (Steal Time).
3.  Если `%st` > 2-3%, значит другие ВМ или процессы на хосте отбирают процессорное время. Решение — перенос ВМ на менее нагруженный хост или настройка CPU Quotas.

### Сценарий 7: Безопасность и критические ошибки (CVE)

В 2025-2026 годах актуальны уязвимости таймеров и Shadow MMU.
*   **CVE-2025-71104**: Вызывает Hard Lockup хоста при выходе ВМ из глубокого сна. **Решение:** Обновление ядра до 6.12+ или отключение `hyperv` таймеров в XML.
*   **Shadow MMU Panic**: Всегда используйте аппаратную трансляцию (EPT/RVI) и отключайте Shadow MMU для повышения стабильности.

### Сценарий 8: Проблемы QEMU Guest Agent (QGA)

QGA критичен для корректной работы `virsh shutdown`, получения IP (`domifaddr --source agent`) и hotplug ресурсов.

**Диагностика:**
```bash
# Проверка статуса agent
virsh domstate web-server-01 --reason
# → blocked (shutdown) — guest-agent не отвечает

# Проверка канала virtio-serial
virsh dumpxml web-server-01 | grep -A5 channel
# Ожидается: <channel type='unix'> с target type='virtio'
```

**Типичные проблемы:**
*   **QGA не установлен внутри гостя:** Установите `qemu-guest-agent` (Debian/Ubuntu) или `qemu-guest-agent` (RHEL/Rocky).
*   **Сервис не запущен:** `systemctl enable --now qemu-guest-agent` внутри ВМ.
*   **Канал virtio-serial не подключен:** Проверьте XML ВМ на наличие секции `<channel>`.
*   **Время в госте расходится с хостом:** QGA синхронизирует часы. Проверьте, что агент работает.

### Сценарий 9: Сетевая диагностика (VNC, SPICE, Bridge, DHCP)

**VNC/SPICE не подключаются:**
```bash
# Проверка адреса прослушивания
virsh vncdisplay web-server-01
# → 127.0.0.1:5901 (только локальный доступ)

# Для удаленного доступа измените listen address в XML:
# <graphics type='vnc' listen='0.0.0.0' port='5901'/>
```

**ВМ имеет IP, но нет доступа в интернет:**
1. Проверьте bridge на хосте: `brctl show` или `ip link show br0`.
2. Проверьте, что физический интерфейс добавлен в мост.
3. Проверьте NAT/forwarding: `sysctl net.ipv4.ip_forward`.
4. Проверьте DHCP-аренды: `virsh net-dhcp-leases default`.

**DNS не работает внутри гостя:**
1. Проверьте, что libvirt сеть активна: `virsh net-list --all`.
2. Проверьте, что dnsmasq запущен (порт 53): `ss -tlnp | grep :53`.
3. Проверьте `/etc/resolv.conf` внутри гостя — он должен указывать на шлюз libvirt (обычно 192.168.122.1).

**macvtap: one-way трафик:**
В bridge-режиме macvtap ВМ на одном хосте не могут общаться между собой напрямую. Используйте обычный Linux bridge или OVS.

### Сценарий 10: Диагностика хранилищ (qcow2, Pools, iSCSI, NFS)

**Образ qcow2 поврежден или не открывается:**
```bash
# Проверка целостности
qemu-img check /var/lib/libvirt/images/web-server-01.qcow2

# Восстановление (если возможно)
qemu-img check -r all /var/lib/libvirt/images/web-server-01.qcow2
```

**Пул хранения неактивен:**
```bash
# Проверка пулов
virsh pool-list --all
# → default   inactive

# Причины: права доступа, путь не смонтирован, SELinux
# Проверка прав: ls -la /var/lib/libvirt/images
# Проверка монтирования: mount | grep /var/lib/libvirt/images
```

**iSCSI/NFS недоступен:**
```bash
# Проверка сессии iSCSI
iscsiadm -m session

# Проверка экспорта NFS
showmount -e nfs-server
mount -t nfs nfs-server:/export /mnt/test
```

**Дисковый I/O медленный:**
```bash
# Проверка планировщика I/O хоста
cat /sys/block/sda/queue/scheduler

# Проверка квот blkio ВМ
virsh blkiotune web-server-01

# Проверка io_uring и очередей
virsh dumpxml web-server-01 | grep -E 'io=|queues='
```

### Сценарий 11: Диагностика сервисов libvirt (virtlogd, virtlockd)

**Логи ВМ не пишутся:**
```bash
# Проверка virtlogd
systemctl status virtlogd
journalctl -u virtlogd --since "10 minutes ago"

# Проверка прав на директорию логов
ls -la /var/log/libvirt/qemu/
# → drwxr-xr-x root root
```

**ВМ не стартует с "Device or resource busy":**
```bash
# Проверка lock-файлов
ls -la /var/run/libvirt/lock/
# Если есть stale lock от умершего процесса:
fuser -v /var/run/libvirt/lock/domain-<UUID>.lock
# Удалите lock после подтверждения, что ВМ не запущена elsewhere:
rm -f /var/run/libvirt/lock/domain-<UUID>.lock
```

### Сценарий 12: Ограничения ресурсов и cgroup (OOM, blkio, memory)

**Хост убивает ВМ (OOM):**
```bash
# Проверка логов ядра
dmesg | grep -i "out of memory"
# → qemu-system-x86_64 invoked oom-killer

# Проверка utilization памяти
free -h
vmstat 1

# Решение: уменьшить maxmemory ВМ или добавить swap/oom_score_adj
virsh setmem web-server-01 2G --config
```

**ВМ получает insufficient memory внутри гостя:**
```bash
# Проверка balloon driver
virsh dommemstat web-server-01
# → actual 2048, swap_in 0, rss 1024

# Если balloon не работает — проверьте XML:
virsh dumpxml web-server-01 | grep -A5 memBalloon
```

**Дисковый I/O ограничен cgroup:**
```bash
# Проверка текущих лимитов
virsh blkiotune web-server-01

# Удаление лимитов
virsh blkiotune web-server-01 --weight 0 --io_weight 0
```

### Сценарий 13: Проблемы прошивок и загрузки (UEFI, OVMF, Secure Boot, TPM)

**"No bootable device":**
1. Проверьте `<boot dev='hd'/>` в XML.
2. Проверьте порядок загрузки: `virsh dumpxml | grep -A10 boot`.
3. Убедитесь, что диск подключен и содержит загрузчик: `virt-customize -a disk.qcow2 --run-command 'update-grub'`.

**ВМ зависает на UEFI shell:**
1. Проверьте, что путь к OVMF корректный: `/usr/share/OVMF/OVMF_CODE.fd`.
2. Проверьте, что Secure Boot отключен для не-Ubuntu/RHEL гостевых ОС.
3. Проверьте наличие переменных UEFI (NVRAM): `virsh dumpxml | grep nvram`.

**TPM не инициализируется:**
```bash
# Проверка состояния TPM в XML
virsh dumpxml web-server-01 | grep -A10 tpm
# Убедитесь, что backend='emulator' и версия='2.0'
```

### Сценарий 14: VFIO и проброс PCI-устройств

**"Operation not supported" при attach-interface:**
```bash
# 1. Проверка IOMMU
dmesg | grep -iE 'intel.*iommu|amd.*iommu'
# → DMAR: IOMMU enabled

# 2. Проверка драйвера устройства
lspci -k -s 01:00.0
# Если driver=vfio-pci — ок. Если нет:
echo "vfio-pci" | sudo tee /sys/bus/pci/devices/0000:01:00.0/driver_override
echo "0000:01:00.0" | sudo tee /sys/bus/pci/drivers/vfio-pci/bind
```

**Устройство не сбрасывается после отключения ВМ:**
```bash
# Проверка, не занято ли устройство
lspci -k -s 01:00.0
# Если driver=vfio-pci, но ВМ выключена:
echo "0000:01:00.0" | sudo tee /sys/bus/pci/drivers/vfio-pci/unbind
echo "0000:01:00.0" | sudo tee /sys/bus/pci/rescan
```

**ROM BIOS не загружается для видеокарты:**
```xml
<hostdev mode='passthrough' managed='yes' type='pci'>
  <source>
    <address domain='0x0000' bus='0x01' slot='0x00' function='0x0'/>
  </source>
  <rom bar='on' file='/usr/share/vgabios/ROM.bin'/>
</hostdev>
```

### Сценарий 15: Проблемы снимков (Snapshots)

**Создание снимка падает:**
```bash
# Формат диска должен быть qcow2
qemu-img info /var/lib/libvirt/images/web-server-01.qcow2
# → file format: qcow2

# Проверка целостности перед снимком
qemu-img check /var/lib/libvirt/images/web-server-01.qcow2
```

**Откат к снимку не работает:**
```bash
# Список снимков
virsh snapshot-list web-server-01

# Принудительный откат (если внутренняя ошибка)
virsh snapshot-revert web-server-01 "snapshot-name" --running --force
```

**Диск заполняется из-за цепочки снимков:**
qcow2 snapshot chain растет со временем. Для контроля:
```bash
qemu-img info /var/lib/libvirt/images/web-server-01.qcow2
# Проверьте backing file chain. Для очистки — commit снимка в базовый диск:
qemu-img commit -b base.qcow2 -d snapshot.qcow2 base.qcow2
```

### Сценарий 16: Идемпотентный скрипт проверки здоровья (DevOps/SRE)

Скрипт для автоматизированных систем мониторинга (Prometheus node_exporter, Ansible, SaltStack). Возвращает 0, если все проверки пройдены.

```bash
#!/bin/bash
# kvm-healthcheck.sh — проверка здоровья KVM-хоста
set -euo pipefail

ERRORS=0

check() {
  local name="$1"
  local cmd="$2"
  local expected="$3"
  if eval "$cmd" | grep -qE "$expected"; then
    echo "[OK]   $name"
  else
    echo "[FAIL] $name"
    ERRORS=$((ERRORS + 1))
  fi
}

check "KVM module loaded" "lsmod | grep -E 'kvm_(intel|amd)'" "kvm_(intel|amd)"
check "/dev/kvm exists" "ls -la /dev/kvm" "crw-rw----"
check "libvirtd active" "systemctl is-active libvirtd" "active"
check "virtlogd active" "systemctl is-active virtlogd" "active"
check "virtlockd active" "systemctl is-active virtlockd" "active"
check "libvirt URI" "virsh uri" "qemu:///system"
check "default pool active" "virsh pool-list --all" "default.*active"
check "default network active" "virsh net-list --all" "default.*active"
check "User in kvm/libvirt groups" "groups" "(kvm|libvirt)"

# Проверка OOM за последний час
if dmesg | grep -qi "out of memory"; then
  echo "[WARN] OOM events detected in dmesg"
  ERRORS=$((ERRORS + 1))
fi

# Проверка места на пуле хранилища
POOL_USAGE=$(df -h /var/lib/libvirt/images | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$POOL_USAGE" -gt 90 ]; then
  echo "[WARN] Storage pool usage critical: ${POOL_USAGE}%"
  ERRORS=$((ERRORS + 1))
fi

if [ "$ERRORS" -gt 0 ]; then
  echo "Health check FAILED: $ERRORS issues found"
  exit 1
else
  echo "Health check PASSED"
  exit 0
fi
```

### Сценарий 17: Восстановление после сбоев (Rollback)

**Откат обновления libvirt/QEMU:**
```bash
# Если после обновления ВМ не стартуют, откатите пакеты:
# Debian/Ubuntu
apt install --reinstall -y qemu-system-x86=1:7.2.* libvirt-daemon-system=8.0.*

# RHEL/Rocky
dnf downgrade qemu-kvm libvirt

# После отката проверьте ВМ
virsh list --all
```

**Восстановление из резервной копии:**
```bash
# 1. Остановите проблемную ВМ
virsh destroy web-server-01

# 2. Восстановите диск из бэкапа
virsh vol-delete web-server-01.qcow2 --pool default
virsh vol-create-from default web-server-01.qcow2 /backup/vms/web-server-01.qcow2 --pool default

# 3. Переопределите ВМ (если потеряна конфигурация)
virsh define /backup/vms/web-server-01.xml

# 4. Запустите
virsh start web-server-01
```

**Очистка зависших lock-файлов после сбоя:**
```bash
# Только если Вы уверены, что ВМ не работает на других хостах!
find /var/run/libvirt/lock/ -name "*.lock" -mtime +1 -exec rm -v {} \;
```

### Сценарий 18: CIS Benchmark для KVM-хостов

Проверка соответствия KVM-хоста стандартам безопасности CIS Benchmark Linux.

**Использование Lynis (аудит):**
```bash
# Установка Lynis
sudo apt install -y lynis  # или: sudo dnf install -y lynis

# Запуск аудита
sudo lynis audit system --quick

# Фокус на KVM
sudo lynis audit system --tests-from-group "kernel|virtualization|storage|networking"

# Просмотр Hardening Index
grep "hardening_index" /var/log/lynis.log
```

**Автоматизация через Ansible (devsec.hardening):**
```yaml
---
- name: Harden KVM hosts
  hosts: kvm_hosts
  become: yes
  roles:
    - dev-sec.os-hardening
    - dev-sec.ssh-hardening
    - dev-sec.kernel-hardening
  vars:
    sysctl_conf:
      - name: net.ipv4.ip_forward
        value: "1"  # Требуется для NAT ВМ
      - name: net.bridge.bridge-nf-call-iptables
        value: "1"
      - name: vm.max_map_count
        value: "262144"
```

**Ключевые проверки CIS для KVM:**

| Проверка | Рекомендация | Команда проверки |
| :--- | :--- | :--- |
| Права на /dev/kvm | crw-rw---- root:kvm | `ls -la /dev/kvm` |
| SELinux/AppArmor | Enforcing для libvirt | `aa-status` / `getenforce` |
| Сетевые порты | Только необходимые (16509, 5900-5910) | `ss -tlnp` |
| Группы пользователя | Только libvirt, kvm | `groups <user>` |
| Пароли libvirt | Не по умолчанию | `grep -r libvirt /etc/shadow` |
| Логирование | auditd включен | `systemctl is-active auditd` |
| SSH root login | Disabled | `grep PermitRootLogin /etc/ssh/sshd_config` |

**Проверка через auditd (аудит действий):**
```bash
# Добавление правил аудита для KVM
sudo auditctl -w /usr/sbin/libvirtd -p wa -k libvirt
sudo auditctl -w /etc/libvirt/ -p wa -k libvirt-config
sudo auditctl -w /var/lib/libvirt/ -p wa -k libvirt-storage

# Просмотр аудит-логов
sudo ausearch -k libvirt --start today
sudo aureport --summary
```

**Wazuh SCA для непрерывного мониторинга:**
```yaml
# /var/ossec/etc/rules/local_rules.xml
<rule id="100100" level="7">
  <if_sid>26101</if_sid>
  <field name="check">CIS Benchmark</field>
  <description>KVM host: CIS Benchmark deviation detected</description>
</rule>
```

### Сценарий 19: Централизованное логирование KVM

Настройка сбора логов KVM/libvirt в централизованную систему (ELK/Loki).

**Вариант 1: journald → remote syslog → Loki/ELK**

На KVM-хосте:
```bash
# Настройка journald для удалённой отправки
# /etc/systemd/journald.conf
[Journal]
Storage=persistent
MaxRetentionSec=30day
ForwardToSyslog=yes
ForwardToSocket=yes

# /etc/rsyslog.d/remote.conf
*.* @@logserver:514  # TCP
# *.* @@logserver:514  # UDP
```

**Вариант 2: Прямая отправка через Promtail (для Loki)**
```yaml
# /etc/promtail/config.yml
scrape_configs:
  - job_name: libvirt-logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: libvirt
          host: kvm-host-01
          __path__: /var/log/libvirt/qemu/*.log

  - job_name: libvirtd
    static_configs:
      - targets:
          - localhost
        labels:
          job: libvirtd
          host: kvm-host-01
          __path__: /var/log/libvirt/libvirtd.log
```

**Вариант 3: Fluent Bit → Elasticsearch**
```yaml
# /etc/fluent-bit/fluent-bit.conf
[INPUT]
  Name   tail
  Path   /var/log/libvirt/qemu/*.log
  Tag    libvirt.*

[FILTER]
  Name   parser
  Match  libvirt.*
  Key_Name log
  Parser libvirt

[OUTPUT]
  Name   es
  Match  libvirt.*
  Host   elasticsearch.example.com
  Port   9200
  Index  libvirt-logs
```

**Аудит-логи libvirt через auditd:**
```bash
# Просмотр всех действий с libvirt
sudo ausearch -k libvirt --interpret-avc -i

# Отчёт по аудиту
sudo aureport --auth --summary
sudo aureport -k --summary
```

**Grafana Loki: запросы к логам KVM:**
```promql
# Все ошибки libvirt
{job="libvirtd"} |= "error"

# Ошибки конкретной ВМ
{job="libvirt", filename=~".*web-server-01.*"} |~ "error|fail"

# Ошибки запуска ВМ
{job="libvirtd"} | json | level="error" | msg=~ "failed to start"
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — основы работы гипервизора.
- [Управление виртуальными машинами](./management.md) — создание ВМ и работа с `virsh`.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — глубокий тюнинг производительности.
- [Мониторинг KVM](./kvm_monitoring.md) — Prometheus, libvirt_exporter, Grafana.
- [CIS Benchmark Linux](../../Ansible/ansible-os-hardening.md) — автоматизация через Ansible.
- [Lynis: Аудит безопасности](../../Security/Tools/lynis.md) — аудит системы.
- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — dnsmasq, nwfilter, port forwarding, диагностика сети.
- [Сетевая диагностика ВМ](./vm_network_troubleshooting.md) — MTU, conntrack, macvtap, packet loss.
- [Безопасность KVM](./kvm_security_hardening.md) — sVirt, polkit, LUKS, CIS Benchmark.
- [UEFI, Secure Boot и vTPM](./kvm_uefi_secure_boot.md) — настройка UEFI, Secure Boot, vTPM.
- [Sysctl чек-лист для KVM-хостов](./kvm_host_sysctl_checklist.md) — параметры ядра, память, сеть.
- [Резервное копирование и восстановление ВМ](./vm_backup_dr.md) — стратегии бэкапа, DR.
- [Проброс GPU и PCI-устройств (VFIO)](./gpu_pci_passthrough.md) — GPU/NVMe passthrough.
- [auditd](../../Linux/SystemAdministration/Logging/auditd.md) — аудит событий ядра.
- [Loki: Обзор](../../Loki/loki_overview.md) — централизованное логирование.
- [ELK Stack](../../ELK_Stack/elk_stack_overview.md) — Elastic Stack для логов.
- [Официальная документация по отладке Libvirt](https://libvirt.org/kbase/debuglog.html) — расширенное логирование.
