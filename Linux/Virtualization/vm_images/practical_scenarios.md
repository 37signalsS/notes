# Образы ВМ: Практические сценарии

## Управление образами с `qemu-img`

### Создание образа

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

### Конвертация

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

### Снапшоты (qcow2)

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

### Изменение размера

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

## Восстановление доступа к ВМ

**Сценарий:** Утерян SSH-доступ или пароль root.

### 1. Монтирование образа

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

### 2. Сброс пароля/ключа

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

### 3. Размонтирование

```bash
sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
sudo modprobe -r nbd
```

## Расширение диска ВМ: полный процесс

**Алгоритм:**

```
Гипервизор → Диск ВМ → Раздел → PV (LVM) → VG → LV → ФС
     ↓          ↓         ↓       ↓        ↓     ↓     ↓
  Увеличить  Увидеть  Изменить  pvresize  auto  lvextend  resize2fs
```

### 1. Гипервизор

| Гипервизор | Команда |
| :--- | :--- |
| **KVM/QEMU** | `qemu-img resize disk.qcow2 +10G` |
| **VirtualBox** | `VBoxManage modifymedium --resize <MB> disk.vdi` (ВМ выключена!) |
| **VMware** | `vmware-vdiskmanager -x <size> disk.vmdk` |

### 2. Гостевая ОС

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

## Связанные документы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные концепции](./basic_concepts.md)** — способы организации хранилища, форматы образов
- **[Дополнительная информация](./additional_info.md)** — OVF/OVA, автоматизация, best practices

---

*Этот файл является частью декомпозированной документации. Исходный файл: [virtual_machine_images.md](../virtual_machine_images.md)*
