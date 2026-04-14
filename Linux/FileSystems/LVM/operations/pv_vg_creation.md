# Создание PV, VG и LV

## Определения

**Physical Volume (PV)** — физический диск или раздел, инициализированный для использования LVM. Базовый строительный блок.

**Volume Group (VG)** — пул хранения, объединяющий один или несколько PV. Представляет единое адресное пространство.

**Logical Volume (LV)** — логический том, выделенный из пространства VG. Аналог раздела диска, но с гибким управлением.

## Базовые концепции

### Иерархия LVM

```
Физический диск → PV → VG → LV → Файловая система
```

Каждый уровень абстрагирует нижележащую структуру:

- **PV** — добавляет LVM-метаданные к диску/разделу
- **VG** — объединяет PV в единый пул
- **LV** — «нарезается» из пространства VG

### Ключевые принципы

- LV можно создавать, удалять и изменять размер без влияния на соседние тома
- VG может span across несколько физических дисков
- Перед созданием PV рекомендуется очистить старые метаданные (`wipefs`)
- Путь к LV: `/dev/<VG>/<LV>` или `/dev/mapper/<VG>-<LV>`

### Основные команды

| Операция | Команда |
| :--- | :--- |
| Инициализация PV | `pvcreate /dev/sdb1` |
| Создание VG | `vgcreate <имя> /dev/sdb1` |
| Создание LV | `lvcreate -L <размер> -n <имя> <VG>` |
| Создание LV (всё место) | `lvcreate -l 100%FREE -n <имя> <VG>` |

## Практические сценарии

### Сценарий 1: Разметка нового диска с помощью LVM

**Шаг 1: Обнаружение нового диска**

```bash
lsblk
```

```
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
sda      8:0    0   20G  0 disk
├─sda1   8:1    0    1M  0 part
├─sda2   8:2    0    2G  0 part /boot
└─sda3   8:3    0   18G  0 part /
sdb      8:16   0   10G  0 disk  ← новый диск без разделов
```

**Шаг 2: Создание разделов (fdisk)**

```bash
sudo fdisk /dev/sdb
```

Интерактивные команды `fdisk`:

- `n` → `p` → `1` → `Enter` → `+5G` — первый раздел 5 ГБ
- `n` → `p` → `2` → `Enter` → `Enter` — второй, всё оставшееся место
- `t` → `1` → `8e` — тип «Linux LVM» для первого
- `t` → `2` → `8e` — тип «Linux LVM» для второго
- `p` — проверить таблицу
- `w` — записать и выйти

Результат:

```
sdb      8:16   0   10G  0 disk
├─sdb1   8:17   0    5G  0 part
└─sdb2   8:18   0    5G  0 part
```

**Шаг 3: Создание PV**

```bash
# Очистка старых метаданных (обязательно для б/у дисков)
sudo wipefs --all /dev/sdb1
sudo wipefs --all /dev/sdb2

# Инициализация PV
sudo pvcreate /dev/sdb1 /dev/sdb2
```

**Шаг 4: Создание VG**

```bash
sudo vgcreate data_vg /dev/sdb1 /dev/sdb2
```

**Шаг 5: Создание LV**

```bash
# LV фиксированного размера
sudo lvcreate -n logs_lv -L 5G data_vg

# LV на всё оставшееся место
sudo lvcreate -n data_lv -l 100%FREE data_vg
```

**Шаг 6: Форматирование и монтирование**

```bash
sudo mkfs.ext4 /dev/data_vg/logs_lv
sudo mkfs.ext4 /dev/data_vg/data_lv

sudo mount /dev/data_vg/logs_lv /var/log
sudo mount /dev/data_vg/data_lv /mnt/data
```

**Шаг 7: Постоянное монтирование через /etc/fstab**

Узнайте UUID:

```bash
sudo blkid
```

```
/dev/mapper/data_vg-logs_lv: UUID="a1b2c3d4-..." TYPE="ext4"
/dev/mapper/data_vg-data_lv: UUID="e5f6g7h8-..." TYPE="ext4"
```

Добавьте в `/etc/fstab`:

```
UUID=a1b2c3d4-...  /var/log   ext4  defaults  0  2
UUID=e5f6g7h8-...  /mnt/data  ext4  defaults  0  2
```

Проверьте:

```bash
sudo mount -a
```

> **Рекомендация:** В `/etc/fstab` используйте путь `/dev/mapper/<VG>-<LV>` — это стабильная символическая ссылка на `/dev/dm-*`.

### Сценарий 2: Быстрое создание без разметки (весь диск)

Если диск используется целиком без разделов:

```bash
wipefs --all /dev/sdc
pvcreate /dev/sdc
vgcreate my_vg /dev/sdc
lvcreate -L 10G -n my_lv my_vg
mkfs.ext4 /dev/my_vg/my_lv
```

> Подробный энд-ту-энд сценарий с расширением и удалением: [Полный жизненный цикл LVM](./lvm_lifecycle.md)

## Дополнительная информация

См. также: [Просмотр информации LVM](./lvm_view_info.md), [Изменение размеров LVM](./lvm_resize.md), [Замена физического диска](./lvm_disk_replacement.md), [Полный жизненный цикл](./lvm_lifecycle.md), [Управление LVM](../management_operations.md)
