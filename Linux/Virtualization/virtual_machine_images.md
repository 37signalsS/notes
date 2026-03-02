# Образы Виртуальных Машин

## Определения

| Термин | Описание |
| :--- | :--- |
| **Образ ВМ** | Файл/блочное устройство с полной копией ОС и данных ВМ |
| **Гипервизор** | ПО для создания/управления ВМ, см. [Виртуализация overview](./virtualization_overview.md) |
| **Block Device Passthrough** | Прямой доступ ВМ к физическому устройству хоста |
| **Disk Image** | Диск ВМ в виде файла файловой системы хоста |
| **Thin Provisioning** | Выделение места по мере записи |
| **Снапшот** | Снимок состояния диска на момент времени |
| **CoW** | Copy-on-Write: запись изменений в новое место |
| **OVF/OVA** | Стандарт упаковки ВМ (XML + диски + манифест) |

---

## Основные концепции

### Способы организации хранилища

#### 1. Прямой доступ (Block Device Passthrough)

**Описание:** Проброс блочного устройства хоста (диск, раздел, LVM, USB) напрямую в гостевую ОС.

| Преимущества | Недостатки |
| :--- | :--- |
| Максимальная производительность | Сложность миграции |
| Нативные функции хоста (LVM-снапшоты) | Сложность резервного копирования |
| | Риск повреждения данных при одновременном доступе |

**Сценарии использования:**
- Базы данных с высокими требованиями к I/O
- Тестирование систем хранения
- Прямой доступ к аппаратному шифрованию

#### 2. Файлы-образы (Disk Image Files)

**Описание:** Диск ВМ хранится как файл(ы) в файловой системе хоста.

| Преимущества | Недостатки |
| :--- | :--- |
| Простота управления (копирование, перемещение) | Накладные расходы файловой системы |
| Портативность между хостами | Возможное снижение производительности |
| Поддержка снапшотов | |

**Сценарии использования:**
- Разработка и тестирование
- Миграция между хостами
- Быстрое развертывание из шаблонов

---

### Форматы файлов-образов

| Формат | Гипервизор | Особенности |
| :--- | :--- | :--- |
| **`raw`** | Все | Побайтовая копия, максимальная производительность, нет снапшотов |
| **`qcow2`** | KVM/QEMU | Снапшоты, шифрование, сжатие, thin provisioning |
| **`vmdk`** | VMware | Снапшоты, thin provisioning, широкая поддержка |
| **`vhd`/`vhdx`** | Hyper-V | `vhdx` — улучшенная версия (до 64 ТБ) |
| **`vdi`** | VirtualBox | Родной формат VirtualBox |

**Выбор формата:**
- **KVM/QEMU:** `qcow2` (снапшоты) или `raw` (производительность)
- **VirtualBox:** `vdi` (интеграция функций)
- **Мультиплатформенность:** `vmdk` или `raw`

---

### Продвинутые механизмы

#### Thin Provisioning

**Реализации:**
- **LVM:** Thinly-provisioned logical volumes + снапшоты
- **raw:** Разреженные файлы (sparse files)
- **qcow2/vmdk:** Встроенная поддержка

**Преимущества:**
- Экономия места (выделение по факту)
- Возможность создать диск 1 ТБ, занимающий 10 ГБ

**Риски:**
- Исчерпание места на хосте → повреждение ВМ
- Требуется мониторинг свободного пространства

#### Снапшоты

**Типы:**
- **Внутренние:** Хранятся внутри файла образа (qcow2)
- **Внешние (backing files):** Отдельный файл с изменениями

**Сценарии:**
- Тестирование обновлений (откат при проблемах)
- Резервное копирование (консистентная точка)
- Шаблоны ВМ (один базовый образ → множество ВМ)

**Best practices:**
- Регулярно удалять ненужные снапшоты
- Мониторить дисковое пространство (`qemu-img info --backing-chain`)
- Не хранить снапшоты долго (деградация производительности)

---

## Практические сценарии

### Управление образами с `qemu-img`

#### Создание образа

```bash
# raw (разреженный файл, 5 ГБ)
dd if=/dev/zero of=test.raw bs=1 count=0 seek=5G
# или
qemu-img create -f raw test.raw 5G

# qcow2 (10 ГБ, thin provisioning)
qemu-img create -f qcow2 test.qcow2 10G

# qcow2 с указанием размера кластера
qemu-img create -f qcow2 -o cluster_size=2M test.qcow2 10G
```

#### Конвертация

```bash
# Общий синтаксис
qemu-img convert -f <from> -O <to> <src> <dst>

# physical disk → qcow2
qemu-img convert -f raw -O qcow2 /dev/sdb disk.qcow2

# vmdk → qcow2
qemu-img convert -f vmdk -O qcow2 source.vmdk target.qcow2

# vdi → qcow2 (VirtualBox → KVM)
qemu-img convert -f vdi -O qcow2 source.vdi target.qcow2
```

#### Снапшоты (qcow2)

```bash
# Создать внутренний снапшот
qemu-img snapshot -c snap_name image.qcow2

# Список снапшотов
qemu-img snapshot -l image.qcow2

# Откат к снапшоту
qemu-img snapshot -a snap_name image.qcow2

# Удалить снапшот
qemu-img snapshot -d snap_name image.qcow2
```

**Внешние снапшоты (backing files):**
```bash
# Создать delta-диск на основе базового образа
qemu-img create -f qcow2 -b base_image.qcow2 -F qcow2 vm_delta.qcow2

# Запуск ВМ с delta-диском (базовый образ read-only)
```

**Преимущества external snapshots:**
- Один "золотой образ" → множество ВМ
- Экономия места (общие блоки не дублируются)

#### Изменение размера

**1. На хосте:**
```bash
# Увеличить на 10 ГБ
qemu-img resize disk.qcow2 +10G

# Установить размер 50 ГБ
qemu-img resize disk.qcow2 50G
```

**2. Внутри гостевой ОС (Linux):**
```bash
# Пересканирование диска (без перезагрузки)
echo 1 > /sys/class/block/sda/device/rescan

# Расширение раздела (fdisk/parted/growpart)
growpart /dev/sda 1  # раздел 1

# Расширение ФС
resize2fs /dev/sda1      # ext4
xfs_growfs /mount/point  # XFS

# Или LVM
pvresize /dev/sda1
lvextend -l +100%FREE -r /dev/vg/lv
```

---

### Восстановление доступа к ВМ

**Сценарий:** Утерян SSH-доступ или пароль root.

#### 1. Монтирование образа

```bash
# Загрузить модуль nbd
sudo modprobe nbd max_part=8

# Подключить qcow2
sudo qemu-nbd --connect=/dev/nbd0 disk.qcow2

# Просмотреть разделы
fdisk -l /dev/nbd0

# Смонтировать раздел
sudo mount /dev/nbd0p1 /mnt
```

#### 2. Сброс пароля/ключа

```bash
# SSH-ключ
echo "ssh-rsa AAAA..." >> /mnt/root/.ssh/authorized_keys

# Или смена пароля (chroot)
mount --bind /dev /mnt/dev
mount --bind /proc /mnt/proc
mount --bind /sys /mnt/sys
chroot /mnt passwd root

# Или ручная правка /etc/shadow
```

#### 3. Размонтирование

```bash
sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
sudo modprobe -r nbd
```

---

### Расширение диска ВМ: полный процесс

**Алгоритм:**

```
Гипервизор → Диск ВМ → Раздел → PV (LVM) → VG → LV → ФС
     ↓          ↓         ↓       ↓        ↓     ↓     ↓
  Увеличить  Увидеть  Изменить  pvresize  auto  lvextend  resize2fs
```

#### 1. Гипервизор

| Гипервизор | Команда |
| :--- | :--- |
| **KVM/QEMU** | `qemu-img resize disk.qcow2 +10G` |
| **VirtualBox** | `VBoxManage modifymedium --resize <MB> disk.vdi` (ВМ выключена!) |
| **VMware** | `vmware-vdiskmanager -x <size> disk.vmdk` |

#### 2. Гостевая ОС

```bash
# 1. Пересканирование (если ВМ не перезагружалась)
echo 1 > /sys/class/block/sda/device/rescan
# или
partprobe

# 2. Проверка видимости
lsblk

# 3. Расширение раздела
fdisk /dev/sda  # d → удалить раздел, n → создать с тем же start
# или
growpart /dev/sda 1

# 4. Расширение ФС/LVM
# Без LVM:
resize2fs /dev/sda1

# С LVM:
pvresize /dev/sda1
lvextend -l +100%FREE -r /dev/vg/lv
```

---

## Дополнительная информация

### OVF/OVA

**OVF (Open Virtualization Format):**
- Стандарт DMTF (Distributed Management Task Force)
- Файлы: `.ovf` (описание), `.vmdk`/`.raw` (диски), `.mf` (манифест)

**OVA (Open Virtualization Appliance):**
- TAR-архив с OVF внутри
- Удобнее для распространения

**Несовместимость:** Реализации VMware и VirtualBox часто несовместимы.

**Конвертация:**
```bash
# OVA → qcow2
tar xvf appliance.ova  # извлечь .vmdk
qemu-img convert -f vmdk -O qcow2 disk.vmdk disk.qcow2
```

### Автоматизация сборки образов

| Инструмент | Назначение |
| :--- | :--- |
| **Packer** | Создание идентичных образов для разных платформ из одного конфига |
| **Vagrant** | Управление ВМ для разработки, см. [Vagrant workflow](../../Vagrant/vagrant_basic_workflow.md) |
| **virt-builder** | Быстрая сборка образов для KVM (из репозиториев) |
| **cloud-init** | Первоначальная настройка ВМ (пользователи, SSH, сеть) |

### Best practices

1. **Резервное копирование:**
   - Регулярные бэкапы образов
   - Проверка целостности (`qemu-img check`)

2. **Оптимизация:**
   - Очистка от мусора перед созданием образа
   - Zero-fill свободного места (`dd if=/dev/zero of=/zero && rm /zero`)
   - Конвертация в qcow2 для экономии места

3. **Безопасность:**
   - Шифрование образов (LUKS, qcow2 AES)
   - Ограничение прав доступа к файлам образов
   - Удаление чувствительных данных перед распространением

4. **Мониторинг:**
   - Отслеживание свободного пространства
   - Проверка цепочки снапшотов
   - Своевременное удаление старых снапшотов
