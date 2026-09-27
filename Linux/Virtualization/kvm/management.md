# Управление виртуальными машинами KVM

В данном файле рассматриваются инструменты и методы жизненного цикла виртуальных машин (ВМ) в среде KVM: создание, настройка, управление состояниями, снимками, хранилищами и сетями. Архитектура гипервизора и компоненты стека описаны в [KVM — Обзор и архитектура](./overview.md), а требования к системе — в [Установка и настройка KVM](./installation.md).

## Определения

**Домен (Domain)** — термин в экосистеме libvirt, обозначающий экземпляр виртуальной машины, определяемый XML-конфигурацией.

**virsh** — основная CLI-утилита для управления доменами через libvirt. Позволяет изменять состояние ВМ, редактировать конфигурации, управлять сетью и хранилищами.

**virt-install** — утилита для автоматизированного развертывания новых ВМ. Поддерживает установку из ISO, сетевых репозиториев и автоматическую настройку через `cloud-init`.

**virt-xml** — инструмент для изменения XML-конфигурации ВМ с помощью CLI-параметров без необходимости ручного редактирования файлов.

**virt-clone** — утилита для клонирования существующей ВМ с автоматическим созданием нового диска и изменением уникальных идентификаторов (UUID, MAC).

**Storage Pool (Пул хранения)** — логическое пространство (директория, LVM-группа, NFS, iSCSI), в котором размещаются образы дисков.

**Storage Volume (Том)** — виртуальный диск (обычно файл `qcow2` или `raw`, LVM LV или блоковое устройство), расположенный внутри пула.

**Virtual Network** — программный коммутатор (bridge), через который ВМ обмениваются трафиком. Управляется libvirt и может включать NAT, DHCP и firewall.

**Шаблон ВМ (Template)** — "золотой образ" с предварительно установленной ОС, пакетами и базовой конфигурацией, используемый для быстрого развертывания клонов.

## Базовые концепции

### XML-конфигурация домена

Каждая ВМ в libvirt описывается XML-файлом, содержащим все параметры: CPU, память, устройства, сеть и хранилище. Понимание структуры XML необходимо для диагностики, ручного редактирования и автоматизации.

**Основные секции:**
- `<domain>` — корневой элемент, атрибут `type='kvm'`.
- `<name>` — имя домена, используемое в командах `virsh`.
- `<uuid>` — уникальный идентификатор (генерируется автоматически при создании).
- `<memory>` и `<currentMemory>` — выделенная и текущая память (в KiB).
- `<vcpu>` — количество виртуальных процессоров.
- `<os>` — тип гостевой ОС и загрузчик (BIOS/UEFI).
- `<features>` — возможности (ACPI, APIC, PAE,hyperv).
- `<cpu>` — модель процессора и топология (sockets, cores, threads).
- `<cputune>` — привязка vCPU к физическим ядрам хоста (pCPU).
- `<numatune>` — привязка памяти ВМ к NUMA-узлам хоста.
- `<memoryBacking>` — механизм работы с памятью (hugepages, locked, source).
- `<devices>` — устройства ВМ: диски, сетевые интерфейсы, консоли, видео.
- `<on_poweroff>`, `<on_reboot>`, `<on_crash>` — действия при событиях.

**Редактирование XML:**
```bash
# Экспорт текущей конфигурации
virsh dumpxml web-server-01 > web-server-01.xml

# Редактирование в текстовом редакторе
vim web-server-01.xml

# Применение изменений
virsh define web-server-01.xml

# Или атомарное изменение через virt-xml
virt-xml web-server-01 --edit --confirm --boot dev=hd,menu=on
```

### Жизненный цикл ВМ

ВМ в libvirt проходит через четко определенные состояния. Понимание переходов важно для корректного управления в скриптах и системах автоматизации.

| Состояние | Описание | Переходы |
| :--- | :--- | :--- |
| **Defined** | XML-конфигурация существует, но ВМ не запущена. | `start` → Running |
| **Running** | ВМ активна, vCPU выполняют код. | `suspend` → Paused, `shutdown` → Shut off, `destroy` → Shut off |
| **Paused** | Процесс QEMU заморожен, состояние в RAM сохранено. | `resume` → Running |
| **Shut off** | ВМ выключена. | `start` → Running, `undefine` → удаление |
| **Saved** | Состояние ВМ сохранено в файл (вне RAM). | `restore` → Running |

**Ключевые команды управления состоянием:**
```bash
# Запуск
virsh start web-server-01

# Мягкое выключение (через ACPI, требует guest-agent или OS support)
virsh shutdown web-server-01

# Жесткое выключение (аналог выдергивания кабеля)
virsh destroy web-server-01

# Перезагрузка
virsh reboot web-server-01

# Сохранение состояния в файл (hibernate)
virsh save web-server-01 /var/lib/libvirt/images/web-server-01.save

# Восстановление из сохранения
virsh restore /var/lib/libvirt/images/web-server-01.save

# Приостановка / возобновление
virsh suspend web-server-01
virsh resume web-server-01
```

### Сетевая топология libvirt

Libvirt поддерживает несколько типов виртуальных сетей:
- **NAT (Default):** ВМ находятся в изолированной подсети (обычно 192.168.122.0/24), выход во внешний мир осуществляется через NAT хоста.
- **Bridge (Мост):** ВМ подключается напрямую к физическому сетевому сегменту хоста. Позволяет ВМ иметь IP из той же сети, что и хост.
- **Isolated:** Трафик разрешен только между ВМ внутри этой сети и хостом. Нет выхода во внешний мир.
- **macvtap:** Позволяет ВМ напрямую использовать физический интерфейс хоста через MAC-адрес. Поддерживает мостовой (bridge) и приватный (private) режимы.
- **SR-IOV:** Прямой проброс Virtual Function PCI-устройства в ВМ для максимальной производительности.

### Жизненный цикл и состояния домена

| Состояние | Описание | Команда |
| :--- | :--- | :--- |
| **Running** | ВМ активна и выполняет код. | `virsh start` |
| **Paused** | Процесс QEMU заморожен, состояние в RAM сохранено. | `virsh suspend` / `resume` |
| **Shut off** | ВМ полностью выключена. | `virsh shutdown` (мягко) / `destroy` (жестко) |
| **Autostart** | Признак запуска ВМ при загрузке хоста. | `virsh autostart [--disable]` |

### Управление хранилищами

Libvirt предоставляет абстракцию пулов и томов для централизованного управления дисками ВМ.

**Storage Pool типы:**
- **Directory (dir):** Файлы образов в директории (qcow2, raw).
- **LVM:** Тома на логических томах LVM.
- **iSCSI:** LUN на iSCSI-цели.
- **GlusterFS / Ceph RBD:** Распределенные хранилища.

**Основные операции:**
```bash
# Создание пула из директории
virsh pool-define-as vms dir - - - - "/var/lib/libvirt/images/vms"
virsh pool-build vms
virsh pool-start vms
virsh pool-autostart vms

# Создание тома (образа) в пуле
virsh vol-create-as vms web-server-01.qcow2 20G --format qcow2

# Просмотр доступных томов
virsh vol-list vms

# Клонирование тома внутри пула
virsh vol-clone web-server-01.qcow2 web-server-02.qcow2 --pool vms
```

### Шаблоны ВМ и стратегии клонирования

Шаблоны позволяют развертывать однотипные ВМ за секунды вместо минут/часов ручной установки.

**Типы клонирования:**
- **Полное клонирование (Full Clone):** Создание полной копии диска. Изолированно, но занимает место.
- **Связанное клонирование (Linked Clone):** Использует базовый образ только для чтения. Быстро, требует доступности базового образа.
- **Создание шаблона:** Подготовка ВМ с `qemu-guest-agent`, очистка machine-id и SSH-ключей, конвертация в template.

### Планировщик и ресурсы

Libvirt позволяет детально контролировать распределение CPU, памяти и ввода-вывода между ВМ.

- **CPU Pinning:** Жесткое закрепление vCPU за pCPU для исключения миграций контекста.
- **NUMA Tuning:** Привязка ВМ к конкретным NUMA-узлам для минимизации задержек памяти.
- **IOThreads:** Выделенные потоки QEMU для обработки дискового и сетевого I/O.
- **I/O Throttling:** Ограничение скорости чтения/записи дисков и сетевого трафика.

## Практические сценарии

### Сценарий 1: Создание ВМ с использованием Cloud-init

Современный способ развертывания без ручной установки.

```bash
# Развертывание Ubuntu 24.04 из облачного образа
virt-install \
  --name web-server-01 \
  --memory 2048 \
  --vcpus 2 \
  --os-variant ubuntu24.04 \
  --disk path=/var/lib/libvirt/images/web-server-01.qcow2,size=20,backing_store=/path/to/ubuntu-cloud.img \
  --network network=default,model=virtio \
  --cloud-init user-data=./user-config.yaml \
  --graphics none \
  --import
```

### Сценарий 2: Управление снимками (Snapshots)

Снимки сохраняют состояние диска и RAM. Работают наиболее эффективно с форматом `qcow2`.

```bash
# Создание снимка с описанием
virsh snapshot-create-as web-server-01 "pre-patch-v1" "Before kernel update" --pause

# Список всех снимков домена
virsh snapshot-list web-server-01

# Откат к снимку и запуск
virsh snapshot-revert web-server-01 "pre-patch-v1" --running

# Удаление снимка (данные объединяются с основным диском)
virsh snapshot-delete web-server-01 "pre-patch-v1"
```

### Сценарий 3: Динамическое изменение ресурсов (Hotplug)

Изменение параметров без перезагрузки (требует наличия `qemu-guest-agent`).

```bash
# Увеличение RAM "на лету" (в пределах maxMemory)
virsh setmem web-server-01 4G --live

# Добавление vCPU
virsh setvcpus web-server-01 4 --live

# Подключение нового диска
virsh attach-disk web-server-01 /path/to/disk.qcow2 vdb --targetbus virtio --persistent

# Отключение диска
virsh detach-disk web-server-01 vdb
```

### Сценарий 4: Работа с виртуальными сетями

```bash
# Просмотр активных сетей
virsh net-list --all

# Выгрузка конфигурации сети в файл
virsh net-dumpxml default > default-net.xml

# Создание сети из XML
virsh net-define isolated-net.xml
virsh net-start isolated-net
virsh net-autostart isolated-net

# Просмотр DHCP-аренд
virsh net-dhcp-leases default
```

### Сценарий 5: Управление конфигурацией XML и клонирование

```bash
# Создание резервной копии конфигурации ВМ
virsh dumpxml web-server-01 > web-server-01-bak.xml

# Клонирование ВМ (создает новый диск и меняет MAC-адрес)
virt-clone --original web-server-01 --name web-server-02 --file /var/lib/libvirt/images/web-server-02.qcow2

# Быстрое изменение параметров через virt-xml
virt-xml web-server-01 --edit --confirm --boot dev=hd,menu=on

# Изменение количества vCPU
virt-xml web-server-01 --edit --confirm --vcpus vcpu=4,maxvcpus=8

# Изменение объема RAM
virt-xml web-server-01 --edit --confirm --memory 4096,maxmemory=8192
```

### Сценарий 6: Мониторинг и диагностика

```bash
# Сводная статистика по ресурсам всех запущенных ВМ
virsh domstats

# Просмотр IP-адресов гостевой ОС (требует guest-agent)
virsh domifaddr web-server-01 --source agent

# Информация о топологии CPU хоста
virsh nodeinfo

# Статистика по конкретной ВМ
virsh dominfo web-server-01

# Процесс и потребление ресурсов
ps aux | grep qemu
```

### Сценарий 7: Живая миграция ВМ между хостами

Миграция позволяет перемещать работающую ВМ между физическими серверами без простоев.

**Требования:**
- Одинаковая версия libvirt и QEMU на обоих хостах.
- Общий доступ к хранилищу (NFS, Ceph, GlusterFS) или идентичные пути к дискам.
- Открытый порт 16509 (libvirt TLS) или 22 (SSH для туннелирования).
- Сеть с низкой задержкой между хостами.

```bash
# На целевом хосте (dest):
# Убедитесь, что пул доступен и libvirtd запущен
virsh list --all
virsh pool-list --all

# Миграция (по SSH, с автоматическим подтверждением)
virsh migrate --live --persistent --verbose web-server-01 qemu+ssh://dest-host/system

# Миграция с auto-converge (для активных ВМ с высоким rate memory change)
virsh migrate --live --auto-converge --bandwidth 500 web-server-01 qemu+ssh://dest-host/system

# Миграция в режим post-copy (минимальное downtime)
virsh migrate --live --postcopy --verbose web-server-01 qemu+ssh://dest-host/system

# Проверка миграции (на целевом хосте)
virsh list --all
virsh dominfo web-server-01
```

**Типичные ошибки:**
- `Migration: TCP: missing port in URI` — неверный URI, проверьте протокол (`qemu+ssh://`).
- `Guest CPU is not compatible` — разные CPU модели, используйте `<cpu mode='host-model'>`.

### Сценарий 8: Создание шаблона ВМ (Template)

Шаблон — ВМ с очищенными уникальными данными, из которого быстро создаются клоны.

**1. Подготовка базовой ВМ:**
```bash
# Установите qemu-guest-agent
sudo apt install -y qemu-guest-agent

# Очистка идентификаторов
sudo cloud-init clean --logs --seed
sudo truncate -s 0 /etc/machine-id
sudo rm /var/lib/dbus/machine-id
sudo ln -s /etc/machine-id /var/lib/dbus/machine-id

# Удаление SSH-ключей хоста
sudo rm /etc/ssh/ssh_host_*

# Очистка истории и кэшей
sudo rm -rf /var/log/*.gz /var/log/journal/*
```

**2. Создание шаблона:**
```bash
# Выключите ВМ
virsh shutdown template-ubuntu

# Удалите диск snapshot (если есть)
virsh snapshot-delete template-ubuntu --metadata

# Создайте шаблон (immutable disk)
virt-sysprep -d template-ubuntu --operations defaults -v
```

**3. Развертывание из шаблона (Linked Clone):**
```bash
virt-clone --original template-ubuntu --name new-vm-01 --file /var/lib/libvirt/images/new-vm-01.qcow2
```

### Сценарий 9: Управление хранилищами (Pools и Volumes)

```bash
# Создание пула LVM
virsh pool-define-as vms_lvm logical - - - - "vg0"
virsh pool-build vms_lvm
virsh pool-start vms_lvm
virsh pool-autostart vms_lvm

# Создание тома 40GB в пуле
virsh vol-create-as vms_lvm db-server.qcow2 40G --format qcow2

# Создание тома из XML (с продвинутыми параметрами)
cat > /tmp/vol.xml << 'EOF'
<volume>
  <name>db-server.qcow2</name>
  <capacity unit='GiB'>40</capacity>
  <allocation unit='GiB'>0</allocation>
  <target>
    <format type='qcow2'/>
    <permissions>
      <mode>0644</mode>
    </permissions>
  </target>
</volume>
EOF
virsh vol-create vms_lvm /tmp/vol.xml

# Клонирование тома
virsh vol-clone template.qcow2 new-vm.qcow2 --pool vms_lvm

# Удаление тома
virsh vol-delete old-vm.qcow2 --pool vms_lvm

# Информация о томе
virsh vol-info web-server-01.qcow2 --pool default
```

### Сценарий 10: Массовое развертывание ВМ

Автоматизация создания нескольких однотипных ВМ через цикл.

```bash
#!/bin/bash
# bulk-create.sh — массовое развертывание ВМ

TEMPLATE="/path/to/ubuntu-cloud.img"
POOL="default"
NETWORK="default"
BASE_NAME="worker"
COUNT=5
RAM=4096
VCPUS=2
DISK_SIZE=20

for i in $(seq 1 $COUNT); do
  VM_NAME="${BASE_NAME}-$(printf '%02d' $i)"
  DISK_PATH="/var/lib/libvirt/images/${VM_NAME}.qcow2"

  virt-install \
    --name "$VM_NAME" \
    --memory "$RAM" \
    --vcpus "$VCPUS" \
    --os-variant ubuntu24.04 \
    --disk path="$DISK_PATH",size="$DISK_SIZE",backing_store="$TEMPLATE" \
    --network network="$NETWORK",model=virtio \
    --cloud-init user-data=./worker-userdata.yaml \
    --graphics none \
    --import \
    --noautoconsole

  echo "Created $VM_NAME"
done
```

### Сценарий 11: Резервное копирование и восстановление ВМ

Стратегия 3-2-1: 3 копии данных, 2 разных носителя, 1 копия вне площадки.

**1. Резервное копирование через снапшоты (Online Backup):**
```bash
# Создание снапшота
virsh snapshot-create-as web-server-01 "backup-$(date +%Y%m%d)" "Daily backup" --disk-only --atomic

# Резервное копирование базового диска
virsh vol-dumpxml web-server-01.qcow2 --pool default | grep path
DISK_PATH=$(virsh vol-path web-server-01.qcow2 --pool default)
rsync -av "$DISK_PATH" /backup/vms/

# Экспорт XML-конфигурации
virsh dumpxml web-server-01 > /backup/vms/web-server-01.xml

# Удаление снапшота после бэкапа
virsh snapshot-delete web-server-01 "backup-$(date +%Y%m%d)"
```

**2. Полное резервное копирование (Offline):**
```bash
# Выключение ВМ
virsh shutdown web-server-01
while virsh list --name | grep -q "^web-server-01$"; do sleep 2; done

# Резервное копирование диска и конфигурации
DISK_PATH=$(virsh vol-path web-server-01.qcow2 --pool default)
cp "$DISK_PATH" /backup/vms/web-server-01.qcow2
virsh dumpxml web-server-01 > /backup/vms/web-server-01.xml

# Запуск ВМ
virsh start web-server-01
```

**3. Восстановление ВМ:**
```bash
# Определение ВМ из XML
virsh define /backup/vms/web-server-01.xml

# Восстановление диска
virsh vol-create-as default web-server-01.qcow2 20G --format qcow2 --backing-vol /backup/vms/web-server-01.qcow2 --backing-vol-format qcow2

# Или полная замена диска
virsh vol-delete web-server-01.qcow2 --pool default
virsh vol-create-from default web-server-01.qcow2 /backup/vms/web-server-01.qcow2 --pool default

# Запуск
virsh start web-server-01
```

### Сценарий 12: Доступ к консоли ВМ

Доступ к консоли необходим для диагностики загрузки, восстановления и управления без сети.

```bash
# Последовательная консоль (Serial Console)
virsh console web-server-01

# Выход: Ctrl+]

# Подключение к VNC
virsh vncdisplay web-server-01
# → localhost:5901

# Подключение через SPICE
virsh spice web-server-01

# Просмотр графической конфигурации
virsh domdisplay web-server-01
```

**Настройка Serial Console в гостевой ОС (Ubuntu/Debian):**
```bash
# Внутри ВМ: добавьте в /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="console=tty0 console=ttyS0,115200n8"

# Обновите GRUB
sudo update-grub
```

### Сценарий 13: Автоматизация управления через скрипты

Пример автоматизированного проверки состояния всех ВМ:

```bash
#!/bin/bash
# vm-health.sh — проверка состояния ВМ

for vm in $(virsh list --name --all); do
  state=$(virsh domstate "$vm")
  echo "$vm: $state"

  if [ "$state" = "running" ]; then
    # Проверка agent
    if virsh domifaddr "$vm" --source agent > /dev/null 2>&1; then
      echo "  → Agent: connected"
    else
      echo "  → Agent: not available"
    fi

    # Проверка steal time (Noisy Neighbor)
    steal=$(virsh domstats "$vm" | grep cpu.time | awk '{print $2}')
    echo "  → CPU time: $steal"
  fi
done
```

### Сценарий 14: Удаление ВМ и очистка ресурсов

Безопасное удаление ВМ с очисткой всех связанных ресурсов.

```bash
# Выключение ВМ
virsh destroy web-server-01
virsh undefine web-server-01 --remove-all-storage --snapshots-metadata

# Удаление связанных сетей (если создавались уникальные)
virsh net-destroy vm-private-net
virsh net-undefine vm-private-net

# Удаление из пула
virsh vol-delete web-server-01.qcow2 --pool default

# Проверка, что ВМ удалена
virsh list --all | grep web-server-01
```

### Сценарий 15: Мониторинг ресурсов и алертинг

Сбор метрик для интеграции с Prometheus, Grafana или Nagios.

```bash
# Статистика по CPU, памяти, сети, диску
virsh domstats web-server-01

# Вывод в формате CSV
virsh domstats --cpu-total --net-total --block-total web-server-01

# Проверка доступности ВМ
if virsh list --name | grep -q "^web-server-01$"; then
  echo "OK: web-server-01 is running"
else
  echo "CRITICAL: web-server-01 is not running"
  # Отправка алерта
  curl -X POST "https://hooks.slack.com/services/XXX" -d '{"text":"VM web-server-01 is down"}'
fi
```

### Сценарий 16: Disaster Recovery для KVM-хостов

Построение DR-стратегии с учётом RPO/RTO и типа хранилища.

**Стратегия 3-2-1-1-0:**
- **3** копии данных (основная + 2 резервные)
- **2** разных типа носителей (локальный disk + удалённое хранилище)
- **1** копия вне площадки (offsite)
- **0** ошибок при проверке восстановления

**DR-матрица для KVM:**

| Сценарий | RPO | RTO | Инструменты |
| :--- | :--- | :--- | :--- |
| Потеря ВМ | 0 (снапшот) | 5 мин | virsh snapshot-revert, btrfs/zfs |
| Потеря хоста | 15 мин | 1 час | rsync + virsh define, DRBD |
| Потеря ДЦ | 1 час | 4 часа | Offsite backup + DR-сайт |
| Корruption qcow2 | 0 (снапшот) | 10 мин | qemu-img check -r, btrfs send |

**Репликация через DRBD (RPO~0):**
```bash
# Синхронная репликация (Protocol C)
# ВМ-диск хранится на DRBD, автоматически реплицируется

# Асинхронная репликация (для удалённых ДЦ)
resource data-wan {
  protocol A;
  disk {
    c-fill-target 4M;  # Ограничение полосы для WAN
    c-max-rate 100M;
  }
  net {
    max-buffers 8000;
    ko-count 4;
  }
}
```

**Offsite backup через rsync:**
```bash
# /etc/cron.d/kvm-backup
0 2 * * * root rsync -avz --delete \
  /var/lib/libvirt/images/ \
  backup-server:/backup/kvm/$(hostname)/

# Бэкап XML-конфигураций
0 1 * * * root for vm in $(virsh list --name --all); do \
  virsh dumpxml $vm > /backup/kvm/xml/${vm}.xml; done
```

**Восстановление ВМ из offsite backup:**
```bash
# 1. Скачивание образа
rsync -avz backup-server:/backup/kvm/images/web-server-01.qcow2 /var/lib/libvirt/images/

# 2. Определение ВМ
virsh define /backup/kvm/xml/web-server-01.xml

# 3. Запуск
virsh start web-server-01
```

### Сценарий 17: Live patching ядра хоста KVM

Обновление ядра KVM-хоста без перезагрузки и простоя ВМ.

**Установка livepatch (Ubuntu):**
```bash
# Установка Canonical Livepatch
sudo snap install canonical-livepatch
sudo canonical-livepatch enable <token>

# Проверка статуса
sudo canonical-livepatch status --verbose
# → kernel: 5.15.0-91-generic
#   CVEs: 3 applied, 0 pending
#   Status: Up to date
```

**Установка livepatch (RHEL):**
```bash
# Установка kpatch
sudo dnf install kpatch kpatch-patch

# Просмотр доступных патчей
sudo kpatch list

# Установка патча (без перезагрузки)
sudo kpatch install kpatch-patch-<version>.rpm

# Проверка
sudo kpatch list
# → /var/lib/kpatch/installed/4.18.0-305.el8.x86_64/
#   kpatch-patch-<version>.rpm
```

**Важно:** Live patching НЕ обновляет модули ядра и не обновляет пользовательское пространство. Используйте его для security patches, а не для major upgrades.

**Проверка ядра после live patching:**
```bash
cat /proc/version
# → 5.15.0-91-generic ... (Ubuntu с live patch)
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — терминология и принципы работы.
- [Установка и настройка KVM](./installation.md) — пошаговое руководство по развертыванию среды.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — диагностика производительности и ошибок.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — современные методы ускорения.
- [Высокая доступность KVM](./kvm_ha.md) — Pacemaker, DRBD, Fencing.
- [Автоматизация KVM](./kvm_automation.md) — Ansible, Terraform, Packer.
- [Мониторинг KVM](./kvm_monitoring.md) — Prometheus, libvirt_exporter, Grafana.
- [Образы ВМ — Форматы и утилиты](../vm_images/definitions.md) — qcow2, CoW, QGA и конвертация.
- [Образы ВМ — Основные концепции](../vm_images/basic_concepts.md) — стратегии хранения, кэширование и TRIM.
- [Вложенная виртуализация (Nested)](../nested_virtualization/definitions_and_concepts.md) — запуск KVM внутри KVM.
- [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md) — архитектура L2-сетей.
- [Live patching ядра](../../Linux/Core/kernel/live_patching.md) — kpatch, canonical-livepatch.
- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — dnsmasq, nwfilter, port forwarding.
- [Безопасность KVM](./kvm_security_hardening.md) — sVirt, polkit, LUKS, CIS Benchmark.
- [UEFI, Secure Boot и vTPM](./kvm_uefi_secure_boot.md) — настройка UEFI, Secure Boot, vTPM.
- [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md) — CPU/RAM overcommit, расчёт ratio.
- [Disaster Recovery](../../Concepts/disaster_recovery.md) — стратегии аварийного восстановления.
- [Выбор конфигурации CPU: NUMA и топология](../../Linux/Core/cpu_selection.md) — NUMA, CCD, CXL и рекомендации для систем 2025–2026.
