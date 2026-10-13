# Шаблоны ВМ и Cloud-Init в Proxmox VE

## Определения

**Шаблон (Template)** — эталонный образ виртуальной машины с предустановленной ОС и базовыми настройками, предназначенный для быстрого развертывания новых инстансов через клонирование. После конвертации в шаблон ВМ становится доступной только для чтения.

**Cloud-Init** — кроссплатформенный инструмент для автоматизации первичной настройки гостевой ОС (создание пользователей, установка SSH-ключей, конфигурация сети, выполнение скриптов) при первом запуске из шаблона.

**VirtIO** — семейство паравиртуализированных драйверов (блок, сеть, balloon, RNG), обеспечивающих производительность near-native для дисков и сети в ВМ. В PVE используется по умолчанию; в Windows гостях подключается через ISO `virtio-win.iso`.

**virtio-scsi-pci** — контроллер шины SCSI поверх VirtIO, рекомендуемый для подключения дисков современных ВМ (вместо устаревшего IDE). Поддерживает больше дисков на одну шину, discard/TRIM и native 4K.

**qcow2 (QEMU Copy On Write version 2)** — формат диска с поддержкой тонкого выделения, снапшотов и шифрования. В PVE используется как основной формат для импорта cloud-image. Преимущество: диски занимают на хранилище только реально записанные блоки. Минус: фрагментация при длительной записи.

**raw** — физическое байт-в-байт копирование образа без метаданных. Производительность выше, чем у qcow2, но нет тонкого выделения и снапшотов на уровне образа. В PVE импортируемые raw-диски сразу занимают полный размер на LVM-Thin или Directory.

**QEMU Guest Agent** — сервис, устанавливаемый внутри гостевой ОС (`qemu-guest-agent` пакет). Обеспечивает корректное завершение работы ВМ, передачу IP-адреса в PVE, заморозку ФС при резервном копировании и передачу метрик (файл подкачки, load average).

**Machine-ID** — уникальный идентификатор гостевой ОС, хранящийся в `/etc/machine-id` (systemd) или `/var/lib/dbus/machine-id`. При клонировании без очистки все клоны получают одинаковый machine-id, что приводит к конфликтам в сетевых сервисах (DHCP, D-Bus, journald).

**Cloud-Init Datasource** — модуль, определяющий среду развертывания. В Proxmox это NoCloud (config drive на CD-ROM или IDE disk), который считывает метаданные с cloud-init drive и применяет их при первом запуске. Определяется по наличию специфических файлов или устройств в ранних загрузочных стадиях.

**Sysprep** — аналог Cloud-Init для Windows ОС. Утилита `sysprep /generalize /oobe /shutdown` удаляет уникальные идентификаторы (SID, компьютерное имя, драйверы) из образа, чтобы клоны могли проходить первичную настройку независимо.

## Основные концепции

### Жизненный цикл шаблона
1. **Подготовка базовой ВМ**: Настройка виртуального оборудования (CPU, RAM, Network) без диска.
2. **Импорт образа**: Использование Cloud-Ready образов (Ubuntu, Debian, AltLinux) вместо ручной установки из ISO.
3. **Кастомизация и очистка**: Установка необходимых пакетов (например, `qemu-guest-agent`) и удаление уникальных идентификаторов.
4. **Конвертация**: Перевод ВМ в состояние `Template`.
5. **Развертывание**: Создание клонов с применением настроек Cloud-Init.

### Типы клонирования
- **Full Clone (Полный клон)**: Полная копия диска шаблона. Занимает больше места, но полностью независима.
- **Linked Clone (Связанный клон)**: Использует диск шаблона как основу (Read-Only) и записывает изменения в новый слой. Экономит место, но требует доступности шаблона для работы.

### Задачи, решаемые с помощью Cloud-Init образов

1. **Автоматизация**. Убирает необходимость ручной настройки каждой новой ВМ.
2. **Унификация**. Все машины разворачиваются из одного шаблона по стандарту.
3. **Безопасность**. Можно сразу задать SSH-ключи и отключить root-пароль.
4. **Масштабируемость**. Идеально для развёртывания десятков ВМ в кластере.
5. **Совместимость с CI/CD**. Можно использовать образы для автоматического тестирования и доставки инфраструктуры.
6. **Тестовые среды**. Шаблоны и linked clones особенно эффективны для dev/test окружений, где требуется быстрое развертывание однотипных ВМ без избыточного потребления дискового пространства.

### Оптимизация для Cloud-Init
- **Serial Terminal**: Использование последовательной консоли (`serial0`) позволяет управлять ВМ через CLI Proxmox (`qm terminal`) без графического интерфейса.
- **QEMU Guest Agent**: Обязателен для корректного завершения работы ВМ, мониторинга IP-адресов и заморозки ФС при резервном копировании.
- **SSD Emulation**: Рекомендуется включать опции `discard=on` и `ssd=1` для дисков на SSD/NVMe хранилищах для поддержки команды TRIM.

### Архитектура Cloud-Init в Proxmox
Cloud-Init работает по стадийной модели. При первом запуске ВМ выполняются стадии в порядке:
1. **local** — локальная конфигурация (hostname, locale, timezone).
2. **network** — настройка сетевых интерфейсов (статический IP, маршруты, DNS).
3. **config** — создание пользователей, установка SSH-ключей, groups, пакетов.
4. **final** — выполнение пользовательских скриптов (`runcmd`, `bootcmd`), настройка resolv.conf.

Механизм обнаружения datasource в Proxmox: cloud-init ищет устройство с метаданными NoCloud. В PVE это:
- IDE диск с меткой `cidata` (legacy) или
- специальный cloud-init drive (рекомендуемый способ).

После успешного запуска cloud-init создает файл `/var/lib/cloud/instance/` с instance-id. При повторном запуске проверяется этот файл; если он существует — стадии не повторяются. Команда `cloud-init clean --logs --seed` удаляет эту директорию, переводя ВМ в состояние "первый запуск".

### Почему очистка идентификаторов обязательна
При клонировании копируется содержимое диска, включая уникальные идентификаторы ОС. Без очистки:
- **machine-id**: дублируется во всех клонах, нарушает работу D-Bus, systemd-journald, некоторые приложения.
- **SSH host keys**: все клоны имеют одинаковые ключи, что делает уязвимым для MITM.
- **Network interface MAC**: в некоторых дистрибутивах udev правила кэшируют MAC-адрес и имя интерфейса (predictable network interface names), из-за чего интерфейс может получить другое имя (eth1 вместо eth0).
- **Hostname**: если не задан cloud-init, все клоны получат hostname исходной ВМ.

### Форматы дисков и их влияние на шаблоны
| Формат | Преимущества | Недостатки | Применение в шаблонах |
|--------|-------------|-----------|---------------------|
| **qcow2** | Тонкое выделение, снапшоты, меньший размер | Производительность ниже raw, фрагментация | Рекомендуется для templates: экономит место на хранилище, позволяет создавать linked clones |
| **raw** | Максимальная производительность | Нет тонкого выделения, занимает полный размер | Используется для production ВМ с предсказуемой нагрузкой, когда важна максимальная скорость |
| **vmdk** | Совместимость с VMware | Ограниченная поддержка в PVE | Редко; только при миграции из VMware |

На LVM-Thin разница между raw и qcow2 минимальна, так как тонкое выделение обеспечивается на уровне пула. На Directory/NFS преимущество qcow2 в размере значительнее.

### Связь с другими файлами
- Подробнее о хранилищах и форматах: **[Хранилища и Ceph в Proxmox](./proxmox_storage.md)**.
- Общая архитектура PVE и место шаблонов: **[Обзор Proxmox VE](./proxmox_overview.md)**.
- Сети и подключение ВМ: **[Сетевые технологии Proxmox](./proxmox_networking.md)**.
- Импорт готовых образов: **[Образы ВМ — Определения](../Linux/Virtualization/vm_images/definitions.md)**.
- Шаблоны и клонирование LXC-контейнеров: **[Продвинутые возможности LXC в Proxmox VE](./proxmox_lxc_advanced.md)**.

## Практические сценарии

### 1. Создание базового Linux шаблона (Generic Template)

Создание "чистой" заготовки без привязки к конкретному дистрибутиву позволяет стандартизировать настройки оборудования.

**Параметры базовой ВМ:**
- **ID**: 9000 (или любой другой из диапазона для шаблонов)
- **Name**: `LinuxTemplate`
- **OS**: Do not use any media (`--ostype l26`)
- **Graphic card**: Serial terminal 0 (`--serial0 socket --vga serial0`)
- **Qemu Agent**: Включен (`--agent 1`)
- **Disk**: Удалить (будет добавлен при создании конкретного шаблона)
- **CPU Type**: `host` (для максимальной производительности и проброса инструкций)
- **Memory/Cores**: Минимально необходимые значения (например, 1 core, 512 MB)

**Создание через CLI:**
```bash
qm create 9000 --name LinuxTemplate --memory 512 --cores 1 --net0 virtio,bridge=vmbr0 --ostype l26 --agent 1 --serial0 socket --vga serial0 --cpu host
```

> **Serial terminal 0** — рекомендуемый видеоадаптер для Cloud-Init шаблонов. Технология разрабатывалась для headless-серверов, использование последовательной консоли избавляет от накладных расходов на эмуляцию полноценного графического адаптера и упрощает работу через CLI/SSH.

После создания ВМ выполните конвертацию:
`ПКМ по ВМ → Convert to template` или `qm template 9000`.

### Краткий план: шаблон и linked clone за 3 шага

Упрощенный workflow для быстрого развертывания однотипных ВМ:

1. **Подготовка ВМ**: Создайте обычную ВМ, установите нужную ОС, базовый набор пакетов, проведите настройку сети. Обязательно установите `qemu-guest-agent`.
2. **Конвертация в шаблон**: Выключите ВМ и преобразуйте в шаблон (`qm template <vmid>`). После этого ВМ нельзя запускать напрямую.
3. **Создание linked clone**: Используйте `qm clone <template-id> <new-id> --name <name> --full 0`. Linked clone использует диск шаблона как базу (read-only), записывая только изменения в новый слой. Это позволяет мгновенно создавать ВМ и экономить место.

> **Важно**: Linked clones не подходят для production-инфраструктуры. Используйте их только в dev/test средах, где допустима зависимость от шаблона. Для production используйте full clone.

### Применимость к LXC

Тот же подход с шаблонами и клонированием работает и для LXC-контейнеров в Proxmox. Подробнее: **[Продвинутые возможности LXC в Proxmox VE](./proxmox_lxc_advanced.md)**.

### 2. Создание специализированного шаблона ВМ

На базе Generic Template создается конкретный шаблон под определенный дистрибутив.

#### 2.1 Клонирование базового шаблона
- **Mode**: Full Clone
- **Name**: Например, `Alt10Template30GB`
- **Target Storage**: Укажите целевое хранилище для дисков.

**Через CLI:**
```bash
qm clone 9000 9001 --name Alt10Template30GB --full
```

#### 2.2 Подготовка и импорт Cloud-Image
Загрузите официальный облачный образ дистрибутива в Shell ноды Proxmox:
```bash
# Пример для AltLinux
wget https://ftp.altlinux.org/pub/distributions/ALTLinux/p11/images/cloud/x86_64/alt-server-11.1-p11-cloud-x86_64.qcow2

# Пример для Ubuntu (Resolute Raccoon / 26.04 LTS)
wget https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-amd64.img

# Пример для Ubuntu (Noble Numbat / 24.04 LTS)
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

# Пример для Rocky Linux (GenericCloud, x86_64)
wget https://download.rockylinux.org/pub/rocky/10/images/x86_64/Rocky-10-GenericCloud-Base.latest.x86_64.qcow2
```

> Образы по умолчанию скачивают в `/var/lib/vz/template/iso` (local storage). При подключённых сетевых хранилищах образы лежат в директориях соответствующих storage — список см. через `pvesm status`. Cloud-образы Rocky Linux (GenericCloud, qcow2) публикуются для актуальных версий 9 и 10 в `download.rockylinux.org/pub/rocky/<версия>/images/x86_64/`; если для нужного дистрибутива cloud-образа нет — используйте метод создания cloud-init образа из существующей ВМ (см. ниже).

Импортируйте диск в созданную ВМ:
```bash
qm disk import <VM_ID> <Image_Name> <Storage_Name> --format qcow2
# Пример:
# qm disk import 9001 alt-server-11.1-p11-cloud-x86_64.qcow2 local-lvm --format qcow2
```

#### 2.3 Настройка оборудования и расширение диска
После импорта диск появится в разделе `Hardware` как `Unused Disk 0`.
1. Нажмите `Edit` на диске и подключите его (рекомендуется включить `SSD emulation`, если используется SSD-хранилище).
2. Выполните `Disk Action → Resize`.

**CLI-эквивалент:**
```bash
qm set 9001 --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-9001-disk-0
qm disk resize 9001 scsi0 +24G
```

**Формула расширения:**
Размер Cloud-Image обычно минимален. Resize работает только на *увеличение*.
`Значение для Resize = Желаемый размер - Текущий размер (указанный в GUI)`
*Пример: Хотим 30 ГБ, текущий 6 ГБ → вписываем 24 (или +24G в CLI).*

#### 2.4 Подготовка системы (Cleanup) — ВАЖНО
Перед финальной конвертацией необходимо очистить образ от уникальных идентификаторов, чтобы клоны не конфликтовали.

**Внутри ВМ (рекомендуется):**
```bash
# Очистка Cloud-Init (сброс состояния для новой инициализации)
sudo cloud-init clean --logs --seed

# Удаление machine-id (будет сгенерирован при первой загрузке клона)
sudo truncate -s 0 /etc/machine-id
sudo rm /var/lib/dbus/machine-id
sudo ln -s /etc/machine-id /var/lib/dbus/machine-id

# Удаление SSH-ключей хоста (чтобы у каждой ВМ были свои)
sudo rm /etc/ssh/ssh_host_*

# Очистка истории и выключение
history -c && sudo poweroff
```

**С хоста Proxmox (через libguestfs-tools):**
```bash
virt-sysprep -d vm-9001-disk-0 --enable customize --hostname template --network
```

#### 2.5 Настройка Cloud-Init в Proxmox
Для активации функционала необходимо добавить виртуальный диск с метаданными:
`Hardware → Add → CloudInit Drive` (или `qm set 9001 --ide2 local-lvm:cloudinit`).

Во вкладке `Cloud-init` задайте параметры по умолчанию:
- **User**: Основной пользователь системы.
- **Password**: Пароль пользователя.
- **SSH public key**: Публичный ключ для доступа.
- **IP Config (net0)**: Для шаблона рекомендуется выставлять **DHCP**. Статический IP лучше назначать уже на склонированной ВМ.

> **Proxmox VE 8**: используется `systemd-networkd`, поэтому корректное задание сетевых параметров через Cloud-Init (IP Address, Gateway, DNS) гарантирует корректную конфигурацию сети при первом запуске. Для DHCP достаточно оставить поля пустыми — Cloud-Init получит адрес автоматически.

**CLI-настройка:**
```bash
qm set 9001 --sshkey ~/.ssh/id_rsa.pub --ipconfig0 ip=dhcp
```

Полный набор полей Cloud-Init (GUI → CLI): пользователь (`--ciuser`), пароль (`--cipassword`), SSH-ключ (`--sshkey`), сеть (`--ipconfig0`), DNS (`--nameserver`, `--searchdomain`), обновление пакетов при первом запуске (`--ciupgrade 0|1`):
```bash
qm set 9001 --ciuser admin --cipassword '<password>' --sshkey ~/.ssh/id_rsa.pub \
  --ipconfig0 ip=dhcp --nameserver 192.168.1.1 --searchdomain example.com --ciupgrade 0
```

### 3. Использование кастомных конфигураций (Snippets)

Если стандартных полей в GUI недостаточно (например, нужно выполнить скрипты `runcmd`), используйте snippets.

1. Создайте YAML-файл на ноде: `/var/lib/vz/snippets/user-data-ubuntu.yaml`.
2. Подключите его к ВМ:
```bash
qm set 9001 --cicustom "user=local:snippets/user-data-ubuntu.yaml"
```

### 4. Порядок загрузки
В разделе `Options → Boot Order` отключите все устройства, кроме основного диска (`scsi0`), и переместите его на самый верх.
`qm set 9001 --boot c --bootdisk scsi0`

После завершения настроек конвертируйте ВМ в шаблон:
`ПКМ по ВМ → Convert to template`.

### 5. Альтернативный метод: Прямой импорт образа в новую ВМ

Вместо создания Generic Template и клонирования можно создать ВМ напрямую и импортировать cloud-image:

```bash
# 1. Создание ВМ с необходимым оборудованием
qm create 9001 --memory 2048 --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci

# 2. Импорт downloaded образа напрямую в scsi0
qm set 9001 --scsi0 local-lvm:0,import-from=/path/to/noble-server-cloudimg-amd64.img

# 3. Настройка serial консоли
qm set 9001 --serial0 socket --vga serial0

# 4. Увеличение размера диска (опционально)
qemu-img resize /path/to/noble-server-cloudimg-amd64.qcow2 32G
qm disk resize 9001 scsi0 +24G

# 5. Добавление Cloud-Init диска
qm set 9001 --ide2 local-lvm:cloudinit

# 6. Загрузка с диска
qm set 9001 --boot order=scsi0

# 7. Конвертация в шаблон
qm template 9001
```

> **Примечание**: Для Ubuntu cloud-images расширение файла может быть `.img`, тогда команды, ожидающие `.qcow2`, потребуют переименования:
> ```bash
> mv noble-server-cloudimg-amd64.img noble-server-cloudimg-amd64.qcow2
> ```

### Клонирование ВМ из шаблона

При развертывании новой ВМ из шаблона:
1. Выберите `Clone` (Full Clone для независимости, Linked Clone для экономии места).
2. Во вкладке `Cloud-init` склонированной ВМ (до запуска) можно переопределить настройки, например, задать статический IP.
3. Запустите ВМ.

> При смене пользователя cloud-init (`ciuser`) при клонировании новый пользователь **добавляется** к существующим: в `/home` остаются и прежний, и новый пользователь. Удалите ненужных пользователей вручную после первого запуска.

**CLI-полный цикл (Full Clone + Cloud-Init):**
```bash
# 1. Создание клона
qm clone 9001 1001 --name web-server-01 --full

# 2. Настройка сети (статический IP)
qm set 1001 --ipconfig0 ip=192.168.1.50/24,gw=192.168.1.1

# 3. Установка SSH ключа (если не задан в шаблоне)
qm set 1001 --sshkey ~/.ssh/id_rsa.pub

# 4. Запуск
qm start 1001

# 5. Проверка статуса cloud-init внутри ВМ
qm exec 1001 -- cloud-init status --wait
# → status: done
```

**CLI-полный цикл (Linked Clone):**
```bash
# 1. Создание связанного клона
qm clone 9001 1002 --name db-server-01

# 2. Настройка
qm set 1002 --ipconfig0 ip=192.168.1.51/24,gw=192.168.1.1
qm set 1002 --sshkey ~/.ssh/id_rsa.pub

# 3. Запуск
qm start 1002
```

> **Важно**: Linked Clone требует, чтобы исходный шаблон (9001) существовал и был включен или хотя бы доступен на хранилище. Удаление шаблона разорвет зависимость, и клоны станут непригодными для запуска.

> **Ограничение миграции**: Перемещение linked clone между узлами кластера возможно только при использовании shared storage (Ceph, NFS). При локальных хранилищах linked clone придется конвертировать в full clone перед миграцией.

### Создание собственного cloud-init образа из существующей ВМ

Когда подходящего официального cloud-image нет (нужна кастомная ОС, предустановленное ПО или ВМ, установленная с ISO), cloud-init можно включить вручную на существующей ВМ и использовать её как шаблон.

**Prerequisites:** ВМ с Ubuntu/Debian (cloud-init должен быть в репозиториях дистрибутива), root-доступ внутри ВМ.

**Шаг 1 — установка пакетов внутри ВМ:**
```bash
apt update
apt install cloud-init qemu-guest-agent
systemctl is-enabled qemu-guest-agent
# → enabled
cloud-init --version
# → 24.4-... (зависит от версии дистрибутива)
```

**Шаг 2 — разрешение datasource NoCloud.** В ВМ, установленной с ISO, файл `/etc/cloud/cloud.cfg.d/99-installer.cfg` создаётся subiquity-инсталлятором и содержит `datasource_list: [ None ]` с захардкоженным `instance-id`, а также `preserve_hostname: true`, `resize_rootfs: false` и `growpart: mode: 'off'`. Это полностью блокирует обнаружение cloud-init drive Proxmox. Отредактируйте файл:
```bash
vim /etc/cloud/cloud.cfg.d/99-installer.cfg
```
Замените `datasource_list: [ None ]` на:
```yaml
datasource_list: [ NoCloud, ConfigDrive ]
```
> Это официальная рекомендация Proxmox ([Cloud-Init FAQ](https://pve.proxmox.com/wiki/Cloud-Init_FAQ)): для шаблонов, используемых только с Proxmox VE, достаточно `NoCloud` и `ConfigDrive` — это ускоряет обнаружение datasource при загрузке. Официальные cloud-images Ubuntu этой проблемы не имеют — `99-installer.cfg` с `datasource_list: [ None ]` создаёт только subiquity-инсталлятор с ISO.

**Шаг 3 — снятие блокировки сетевой конфигурации.** Файл `/etc/cloud/cloud.cfg.d/50-curtin-networking.cfg` (в ISO-установках может называться `subiquity-disable-cloudinit-networking.cfg`) содержит `network: {config: disabled}`, что запрещает cloud-init настраивать сеть. Перенесите его за пределы каталога (не удаляйте — пригодится для отката):
```bash
mkdir -p /root/cloud-init-disabled
mv /etc/cloud/cloud.cfg.d/50-curtin-networking.cfg /root/cloud-init-disabled/
```

**Шаг 4 — удаление конфигурации netplan.** Ubuntu генерирует `/etc/netplan/*.yaml` с DHCP для интерфейса (`ens18` в ВМ Proxmox). Пока файл на месте, cloud-init не применит сетевые настройки из cloud-init drive. Перенесите:
```bash
mv /etc/netplan/50-cloud-init.yaml /root/cloud-init-disabled/
# или все файлы:
mv /etc/netplan/*.yaml /root/cloud-init-disabled/
```

**Шаг 5 — очистка идентификаторов:**
```bash
cloud-init clean
rm -f /etc/machine-id
rm -f /etc/ssh/ssh_host_*
apt clean
# опционально — полностью чистый образ:
rm -rf /var/log/*
```

**Шаг 6 — подключение CloudInit Drive.** Выключите ВМ (`poweroff`), затем в GUI: `Hardware → Add → CloudInit Drive`, выберите storage. CLI-эквивалент: `qm set <VMID> --ide2 <storage>:cloudinit`.

**Шаг 7 — тестирование до конвертации в шаблон.** Проверьте работу cloud-init на клоне (шаблон ещё не создан): клонируйте ВМ, во вкладке `Cloud-Init` задайте пользователя, пароль и сеть (DHCP или статика), запустите. Проверка внутри ВМ:
```bash
cloud-init status
# → status: done
cloud-init status --long
# → подробный вывод по стадиям
```
Смена IP через cloud-init: во вкладке Cloud-Init задайте `IP Config` вида `ip=10.10.10.92/24,gw=10.10.10.1`, перезапустите ВМ — адрес применится при следующем запуске.

**Шаг 8 — финальная очистка и конвертация.** После успешного теста:
```bash
cloud-init clean --logs
rm -f /etc/ssh/ssh_host_*
poweroff
```
Затем `ПКМ по ВМ → Convert to template` (или `qm template <VMID>`).

> **Особенности:**
> - Cloud-init **добавляет** нового пользователя, но не удаляет прежнего: после клонирования с другим `ciuser` в `/home` остаются обе учётные записи. Удалите старого пользователя вручную, если он не нужен.
> - Раскладка клавиатуры в консоли по умолчанию английская — измените её **до** конвертации в шаблон, иначе придётся пересобирать образ.
> - Все настройки (пользователи, раскладка, пакеты) нужно завершить **до** конвертации в шаблон: после конвертации ВМ доступна только для чтения.

### Управление через pvesh

**Статус ВМ/шаблона:**
```bash
pvesh get /nodes/pve1/qemu/9001/status/current
# → {"status":"stopped","template":1,...}
```

**Создание клона через API:**
```bash
pvesh create /nodes/pve1/qemu/9001/clone \
  --newid 1001 \
  --name web-server-01 \
  --full 1 \
  --storage local-lvm
```

**Удаление ВМ:**
```bash
pvesh delete /nodes/pve1/qemu/1001
```

**Экспорт конфигурации ВМ (без диска):**
```bash
pvesh get /nodes/pve1/qemu/1001/config
# → вывод .conf-параметров ВМ
```

### Валидация и откат

**Проверка конфигурации перед конвертацией:**
```bash
# Проверка: нет ли включенных devices, которые могут сломаться при конвертации
qm config 9001 | grep -E 'device|net|scsi|sata|ide'
# → scsi0: local-lvm:vm-9001-disk-0
# → net0: virtio=...
# → ide2: local-lvm:cloudinit
```

**Dry-run клонирования (проверка доступности storage):**
```bash
# Проверка свободного места на целевом хранилище
pvesm list local-lvm | grep free
# → free 45.23G

# Проверка наличия snapshot'ов (для linked clone нужен базовый том)
qm listsnapshot 9001
# → текущий statesnap
```

**Откат: конвертация шаблона обратно в ВМ:**
```bash
# Если нужно снова редактировать шаблон:
qm template 9001 --unused  # или через GUI: Convert back to VM
# В новых версиях PVE:
qm set 9001 --template 0
```

### Резервное копирование шаблонов

Шаблоны бэкапируются стандартным способом через `vzdump`:
```bash
# Одиночный шаблон
vzdump 9001 --mode snapshot --storage pbs --compress zstd

# Все шаблоны на узле (VMID >= 9000 по соглашению)
for vmid in $(qm list | awk 'NR>1 && $1 >= 9000 {print $1}'); do
  vzdump $vmid --mode snapshot --storage pbs --compress zstd
done

# Проверка
vzdump --list
# → /var/lib/vz/dump/vzdump-qemu-9001-2026_09_17-12_00_00.vma.zst
```

> **Важно**: `vzdump` для шаблонов работает так же, как для обычных ВМ. При восстановлении (`vzrestore`) можно восстановить как шаблон (`--unique 0`) или как обычную ВМ.

### Массовое развертывание из шаблона

**Скрипт массового клонирования:**
```bash
#!/bin/bash
# mass-clone.sh — массовое развертывание ВМ из шаблона
set -euo pipefail

TEMPLATE_ID="${1:?Usage: $0 <template-id> <prefix> <count> <ip-start>}"
PREFIX="${2:?Usage: $0 <template-id> <prefix> <count> <ip-start>}"
COUNT="${3:?Usage: $0 <template-id> <prefix> <count> <ip-start>}"
IP_START="${4:?Usage: $0 <template-id> <prefix> <count> <ip-start>}"
NETMASK="24"
GATEWAY="192.168.1.1"
BRIDGE="vmbr0"

for i in $(seq 1 "$COUNT"); do
  VM_ID=$((9000 + i))
  VM_NAME="${PREFIX}-$(printf "%02d" $i)"
  IP_OCTET=$((IP_START + i - 1))
  IP="192.168.1.${IP_OCTET}/${NETMASK}"

  echo "Creating $VM_NAME (ID: $VM_ID, IP: $IP)..."

  # Full clone (для production используйте full)
  qm clone "$TEMPLATE_ID" "$VM_ID" --name "$VM_NAME" --full

  # Cloud-Init сеть
  qm set "$VM_ID" --ipconfig0 ip="$IP",gw="$GATEWAY"
  qm set "$VM_ID" --sshkey ~/.ssh/id_rsa.pub

  # Запуск
  qm start "$VM_ID"

  # Ожидание готовности cloud-init (через guest agent)
  echo "Waiting for cloud-init to finish..."
  for _ in $(seq 1 30); do
    STATUS=$(qm status "$VM_ID" --current | grep status | awk '{print $2}')
    if [ "$STATUS" = "running" ]; then
      sleep 2
      CLOUD_STATUS=$(qm exec "$VM_ID" -- cloud-init status 2>/dev/null | grep status | awk '{print $2}' || echo "unknown")
      if [ "$CLOUD_STATUS" = "done" ]; then
        echo "Cloud-init done for $VM_NAME"
        break
      fi
    fi
    sleep 2
  done
done
```

### Проверка статуса настройки

Cloud-Init может выполнять задачи в фоне после старта системы. Чтобы убедиться в завершении настройки, используйте команду:
```bash
sudo cloud-init status --wait
# → status: done
```

**Через Proxmox CLI (без входа в ВМ):**
```bash
# Проверка вывода cloud-init
qm exec 1001 -- cloud-init status
# → status: done

# Просмотр логов cloud-init
qm exec 1001 -- cat /var/log/cloud-init.log
qm exec 1001 -- cat /var/log/cloud-init-output.log
```

### Управление образами

**Импорт образа через URL (PBS/external storage):**
```bash
# Скачивание образа на ноду PVE
wget -O /tmp/ubuntu-24.04.qcow2 \
  https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

# Импорт в хранилище
qm importdisk 9001 /tmp/ubuntu-24.04.qcow2 local-lvm --format qcow2
```

**Конвертация формата диска:**
```bash
# qcow2 → raw (для повышения производительности)
qemu-img convert -p input.qcow2 output.raw

# raw → qcow2 (для экономии места)
qemu-img convert -p input.raw output.qcow2 -O qcow2
```

### Настройка Windows-шаблона (Sysprep)

Для Windows ОС процесс подготовки аналогичен Linux, но использует `sysprep`:

**Внутри ВМ (от администратора):**
```powershell
# Очистка уникальных идентификаторов
$sysprep = "$env:SystemRoot\System32\Sysprep\sysprep.exe"
& $sysprep /generalize /oobe /shutdown /mode:vm
```

**Особенности Windows-шаблонов:**
- Установите `qemu-guest-agent` и драйверы `virtio-win` (ISO из репозитория PVE) до sysprep.
- В PVE используйте тип машины `q35` (не `i440fx`) для поддержки UEFI и современных устройств.
- Включите `ostype win11` или `win10` при создании ВМ для корректной эмуляции.
- В свойствах диска включите `discard=on`, `ssd=1`, `cache=writeback` (для Windows guest recommended).
- Cloud-Init для Windows требует установленного `cloudbase-init` пакета (скачивается с cloudbase-init.net).

**CLI для Windows template:**
```bash
qm create 9002 --name WinTemplate --memory 4096 --cores 2 \
  --net0 virtio,bridge=vmbr0 --ostype win11 \
  --agent 1 --serial0 socket --vga serial0 --cpu host \
  --machine q35 --bios ovmf
```

## Дополнительная информация

### Рекомендации
- **Консоль ядра**: Для корректной работы Serial Terminal в некоторых образах может потребоваться добавление `console=ttyS0,115200` в параметры загрузки ядра (GRUB).
- **QEMU Agent**: Убедитесь, что пакет `qemu-guest-agent` установлен в образе до конвертации.
- **Образы**: Используйте официальные cloud-image дистрибутивов; они оптимизированы для облачных/виртуальных сред и уже содержат cloud-init.
- **Пакеты**: Установите `open-vm-tools` или `qemu-guest-agent` перед конвертацией для поддержки guest agent в PVE.
- **ОС**: Для Windows шаблонов предпочитайте UEFI (`--bios ovmf`) с `--machine q35`. Для Linux legacy BIOS (`--bios seabios`) достаточно.

## Диагностика и устранение неполадок

### Cloud-Init не выполняется при первом запуске

```bash
# Проверка статуса
qm exec 1001 -- cloud-init status
# → status: disabled

# Проверка наличия cloud-init drive
qm config 1001 | grep ide2
# → ide2: local-lvm:cloudinit

# Проверка загрузочного порядка
qm config 1001 | grep boot
# → boot: order=scsi0

# Решение: убедитесь, что cloud-init drive подключен и загрузка идет с диска, а не с ISO
qm set 1001 --ide2 local-lvm:cloudinit
qm set 1001 --boot c --bootdisk scsi0
```

### Дублирование SSH-ключей после клонирования

```bash
# Симптом: при подключении к клонам warning "remote host identification has changed"
# Причина: SSH host keys не были удалены в шаблоне

# Исправление на существующем клоне
qm exec 1001 -- rm -f /etc/ssh/ssh_host_*
qm exec 1001 -- systemctl restart sshd
```

### Machine-ID конфликт

```bash
# Симптом: одинаковые логи в journald, проблемы с D-Bus, DHCP конфликты
# Проверка machine-id
qm exec 1001 -- cat /etc/machine-id
# → 0123456789abcdef... (такой же как на другом клоне)

# Исправление
qm exec 1001 -- truncate -s 0 /etc/machine-id
qm exec 1001 -- rm -f /var/lib/dbus/machine-id
qm exec 1001 -- ln -s /etc/machine-id /var/lib/dbus/machine-id
qm exec 1001 -- systemctl restart systemd-machine-id-commit.service
```

### Linked Clone не запускается после удаления шаблона

```bash
# Симптом: ошибка "cannot find base volume" при старте ВМ
# Причина: клон использовал том шаблона как базовый (read-only), том удален

# Решение 1: восстановить шаблон из бэкапа
# Решение 2: конвертировать linked clone в full (если есть место)
qm config 1002 | grep scsi0
# → scsi0: local-lvm:vm-9001-disk-0,size=30G

# Конвертация связанного клона в полный (в PVE 7+)
# Через GUI: Hardware → Hard Disk → Move disk → Storage: local-lvm (создает полную копию)
# Через CLI:
qm disk move 1002 scsi0 local-lvm --format qcow2 --delete
```

### Cloud-Init datasource не определяется

```bash
# Проверка устройств в ВМ
qm exec 1001 -- lsblk -f
# → cidata — должен быть смонтирован как cdrom или ide disk

# Проверка логов
qm exec 1001 -- cat /var/log/cloud-init.log | grep -i "no cached"
# → No cached datasource found yet

# Если используется IDE disk:
qm config 1001 | grep ide
# → ide2: local-lvm:cloudinit

# Проверка содержимого cloud-init drive
qm exec 1001 -- cat /var/log/cloud-init.log | grep -i "no cloud"
# → Found cloud-init data in /dev/vdb (NoCloud)

# Если datasource не найден — пересоздайте cloud-init drive
qm set 1001 --ide2 none
qm set 1001 --ide2 local-lvm:cloudinit
```

### Сеть не применяется (Cloud-Init network config)

```bash
# Проверка сгенерированной конфигурации сети
qm exec 1001 -- cat /etc/netplan/*.yaml
# или
qm exec 1001 -- cat /etc/network/interfaces

# Проверка статуса cloud-init network stage
qm exec 1001 -- cloud-init status --long
# → stage: [network-config]

# Если сеть не применена — проверьте формат ipconfig
qm config 1001 | grep ipconfig
# → ipconfig0: ip=dhcp

# Для статики:
qm set 1001 --ipconfig0 ip=192.168.1.100/24,gw=192.168.1.1
```

### Диск не расширяется после resize

```bash
# Проверка размера диска в гостевой ОС
qm exec 1001 -- lsblk
# → sda 29G (если resize был +24G от 6G → должно быть 30G)

# Проверка размера в PVE
qm config 1001 | grep scsi0
# → scsi0: local-lvm:vm-9001-disk-0,size=30G

# Если в гостевой ОС размер меньше — расширить ФС
qm exec 1001 -- growpart /dev/sda 1
qm exec 1001 -- resize2fs /dev/sda1
# Для XFS:
qm exec 1001 -- xfs_growfs /
```

### Windows: Sysprep не завершает обобщение

```bash
# Симптом: ВМ после sysprep зависает на "Preparing Windows..."
# Причины:
# 1. Драйверы virtio не установлены (инсталлируйте virtio-win.iso перед sysprep)
# 2. Включен BitLocker (отключите перед sysprep)
# 3. Приложения блокируют shutdown (закройте все приложения, сохраните данные)

# Проверка: после sysprep в директории C:\Windows\System32\Sysprep\Panther
# должны быть логи с расширением .xml — анализируйте их на ошибки
```

## Лучшие практики

1. **Сегментация шаблонов**: Выделите отдельный диапазон VMID для шаблонов (например, 9000–9999). Это упрощает массовые операции и фильтрацию.
2. **Именование**: Используйте формат `<os>-<version>-<purpose>-<date>`, например `ubuntu-24.04-web-20260917`. Добавляйте дату для версионирования.
3. **Версионирование**: Храните несколько версий шаблонов параллельно. Не изменяйте существующий рабочий шаблон — создайте новый с новой датой.
4. **Иммутабельность**: После конвертации шаблон не должен запускаться. Если нужно изменить — клонируйте, модифицируйте клон, затем конвертируйте в новый шаблон.
5. **Хранение**: Размещайте шаблоны на выделенном storage или pool, защищенном от случайного удаления. Используйте LVM-Thin или ZFS для снапшотов.
6. **Формат дисков**: Используйте qcow2 для шаблонов — экономит место и позволяет создавать linked clones. Для production ВМ, где важна максимальная скорость, используйте raw или discard=on на SSD.
7. **Full vs Linked Clone**: Используйте Full Clone для production ВМ, которые должны работать автономно. Linked Clone — только для dev/test сред, где важна экономия места и допустима зависимость от шаблона. При необходимости миграции linked clone между узлами используйте shared storage (Ceph, NFS); на локальных хранилищах предварительно конвертируйте в full clone.
8. **Guest Agent**: Всегда включайте `--agent 1` в шаблонах и устанавливайте пакет внутрь гостя. Без agent недоступны IP-адрес в GUI и корректное завершение.
9. **Cloud-Init Disk**: Подключайте cloud-init drive через `--ide2 local-lvm:cloudinit`, а не через SATA/SCSI, чтобы избежать проблем с загрузкой.
10. **Резервное копирование**: Регулярно бэкапьте шаблоны через `vzdump`. При обновлении ОС в шаблоне создавайте новый шаблон, а не изменяйте старый.
11. **Безопасность**: Удалите ненужные пользователей, службы и пакеты перед конвертацией. Используйте минимальный набор пакетов (minimal install).
12. **Документирование**: В комментариях к ВМ (`qm config <id> | description`) указывайте версию ОС, дату создания, изменения относительно предыдущей версии.

## Граничные случаи

1. **MTU mismatch в VXLAN**: Если underlay MTU 1500, а VXLAN MTU оставлен 1500, фрагментация пакетов приведет к потере пакетов или снижению производительности. Симптом: `ping` работает, но `scp`/`curl` зависают. Решение: установить MTU 1450 на VM или настроить Path MTU Discovery.
2. **Смешанные скорости в bonding**: При использовании NIC разной скорости (1G + 10G) в LACP-бонде трафик хешируется только по скоростям. Может привести к перегрузке медленного линка. Решение: использовать separate bonds или active-backup.
3. **MAC-адрес conflict при клонировании VM**: При клонировании без Cloud-Init MAC может дублироваться. Симптом: ARP flux, потери пакетов. Решение: `qm set <newid> --net0 virtio,bridge=vmbr0,firewall=1` — назначает новый MAC.
4. **VLAN-aware bridge + legacy VM**: Некоторые старые ОС (Windows Server 2012, старые Linux ядра) не корректно обрабатывают VLAN tagging на уровне guest. Симптом: VM не получает DHCP или нет связи. Решение: использовать традиционные VLAN-под-интерфейсы (`eno1.50` → `vmbr0v5`) или VLAN trunk в VM.
5. **SDN во время обслуживания узла**: При переводе узла в maintenance mode SDN-туннели к этому узлу разрываются. Миграция VM в это время может завершиться ошибкой сети. Решение: сначала мигрировать VM, потом вводить maintenance mode.
6. **Bonding с разными драйверами NIC**: NIC одного производителя, но разные revision могут иметь несовместимые offload параметры, вызывающие падение bond. Решение: единообразная конфигурация `ethtool` на всех slave-интерфейсах.
7. **Conntrack exhaustion при высоких нагрузках**: При >100K соединений в секунду на узел может произойти исчерпание `nf_conntrack_max`. Симптом: `CT table full, dropping packet`. Решение: `sysctl -w net.netfilter.nf_conntrack_max=1048576`.
8. **OVS + Linux Bridge на одном узле**: OVS и Linux Bridge не могут shares physical NIC без VFIO passthrough или macvlan. Приводит к нестабильной работе. Решение: выделить отдельные NIC под OVS и Linux Bridge, или использовать только один backend.
9. **Клонирование между хранилищами с разным форматом**: При клонировании с Directory (raw) на LVM-Thin (qcow2) может потребоваться конвертация. Решение: используйте `qm disk move` с указанием формата.
10. **Cloud-Init при смене MAC/VIF**: Если после клонирования изменить MAC или bridge в настройках сети, cloud-init может не обновить конфигурацию, так как instance-id уже создан. Решение: `qm set <id> --delete ide2` (удаляет cloud-init drive), затем заново подключите и запустите `cloud-init clean --logs --seed` внутри ВМ.
11. **Template с UUID/DMI конфликтами**: Некоторые приложения (Windows, Oracle DB) привязываются к hardware UUID или DMI-информации. При клонировании без sysprep/cloud-init cleanup это вызывает проблемы с активацией. Решение: используйте `--uuid` при создании ВМ для явного задания уникального идентификатора.
12. **Снапшот linked clone без базового шаблона**: Если хранилище не поддерживает dependency tracking (например, NFS без .qcow2 refcount), linked clone может стать full клоном после создания первого снапшота. Решение: используйте LVM-Thin или ZFS для хранилищ, где нужны linked clones.

### Windows: Active Directory и Domain Controller

Для развёртывания Windows Domain Controller в Proxmox:

```bash
# Создание Windows VM с достаточными ресурсами
qm create 300 \
  --name win-dc \
  --memory 8192 \
  --cores 4 \
  --cpu host \
  --scsihw virtio-scsi-pci \
  --scsi0 local-lvm:80 \
  --net0 virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0 \
  --ide2 local:iso/windows-server-2022.iso,media=cdrom \
  --boot order=scsi0;ide2

# Установка Windows Server (через VNC или web GUI)
# После установки:
  # 1. Установите virtio drivers (virtio-win.iso)
  # 2. Установите QEMU Guest Agent
  # 3. Запустите dcpromo для promotion в Domain Controller
```

**Важные замечания для Windows AD:**
- Используйте `cpu: host` для поддержки AES-NI (ускорение шифрования AD).
- Для FSMO-ролей выделите VM с высоким приоритетом (`--shares 2048`).
- Настройте NTP-сервер на DC для синхронизации времени в кластере.
- Используйте отдельный VLAN для AD-трафика (replication, authentication).

### Windows: Hyper-V Migration

Для миграции VM из Hyper-V в Proxmox:

```bash
# 1. Экспорт VM из Hyper-V (PowerShell)
Export-VM -Name "MyVM" -Path "D:\Exports"

# 2. Конвертация VHD/VHDX в qcow2
qemu-img convert -f vmdk -O qcow2 source.vmdk target.qcow2

# 3. Импорт в Proxmox
qm importdisk 301 target.qcow2 local-lvm

# 4. Настройка VM
qm set 301 --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-301-disk-0
qm set 301 --net0 virtio,bridge=vmbr0
qm set 301 --boot order=scsi0
```

**Проблемы при миграции:**
- **Драйверы Hyper-V**: Удалите Integration Services перед миграцией.
- **Activation**: Windows может потребовать реактивацию после смены hardware.
- **Битлопер**: Отключите BitLocker перед миграцией.

### Связанные темы
- [Управление ВМ KVM](../Linux/Virtualization/kvm/management.md)
