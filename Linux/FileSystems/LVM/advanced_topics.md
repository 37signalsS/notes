# LVM: Расширенные темы

## LVM и процесс загрузки Linux

### Загрузка с LVM

Если корневая файловая система (`/`) находится на LVM-томе, для загрузки используется `initramfs` (initial RAM file system).

**Процесс загрузки:**

1. **BIOS/UEFI** → загрузчик (GRUB)
2. **GRUB** → загружает ядро + `initramfs`
3. **initramfs** → содержит утилиты LVM (`lvm`, `pvscan`, `vgscan`, `lvscan`)
4. **Активация LVM** → `vgchange -ay` активирует VG и LV
5. **Монтирование корня** → ядро монтирует корневую ФС с LV
6. **Продолжение загрузки** → переход к `/sbin/init`

### Ограничение: `/boot` на LVM

**Важно:** Каталог `/boot` **не должен** находиться на LVM.

**Причина:**
- GRUB должен прочитать ядро и `initramfs` **до** активации LVM
- Загрузчик не имеет доступа к утилитам LVM
- Исключение: GRUB2 с поддержкой LVM (не рекомендуется для production)

**Рекомендуемая схема:**

| Раздел | Размер | Тип | Описание |
| :--- | :--- | :--- | :--- |
| `/dev/sda1` | 512 МБ – 1 ГБ | ext4/xfs | `/boot` (обычный раздел) |
| `/dev/sda2` | Остальное место | LVM PV | Все остальные разделы через LVM |

**Альтернатива:** Использовать шифрованный `/boot` с GRUB2 (требует дополнительной настройки).

---

## LVM и файловые системы

### Взаимодействие LVM и ФС

LVM управляет блочными устройствами, но **не отменяет ограничений файловых систем**.

### Точность размеров

**Проблема:** Утилиты LVM и ФС могут по-разному интерпретировать единицы:

| Единица | LVM | Файловые системы |
| :--- | :--- | :--- |
| `GB` | 10^9 (1 000 000 000 байт) | 10^9 |
| `GiB` | 2^30 (1 073 741 824 байт) | 2^30 |

**Рекомендация при уменьшении:**

1. Сначала сжимайте ФС до размера **меньшего**, чем целевой размер LV
2. Затем уменьшайте LV
3. Затем расширяйте ФС до максимального размера LV

**Пример для ext4:**

```bash
# 1. Отмонтировать том
umount /dev/my_vg/my_lv

# 2. Проверить ФС
e2fsck -f /dev/my_vg/my_lv

# 3. Сжать ФС (до 14 ГБ, хотя целевой LV будет 15 ГБ)
resize2fs /dev/my_vg/my_lv 14G

# 4. Уменьшить LV (до 15 ГБ)
lvreduce -L 15G /dev/my_vg/my_lv

# 5. Расширить ФС на весь LV
resize2fs /dev/my_vg/my_lv

# 6. Смонтировать
mount /dev/my_vg/my_lv /data
```

### partprobe и перечитывание таблицы разделов

**Проблема:** После изменения таблицы разделов (`fdisk`, `parted`) ядро может не увидеть изменения без перезагрузки.

**Решение:**

```bash
# Перечитать таблицу разделов
sudo partprobe /dev/sdb

# Проверить
lsblk
```

**Если `partprobe` не работает:**
- Размонтируйте все разделы на диске
- Используйте `partx -u /dev/sdb`
- В крайнем случае — перезагрузка

---

## Передача пространства между Volume Groups

> **Внимание:** Прямого механизма переноса пространства между VG **не существует**. Описанный ниже метод — обходной путь.

### Сценарий

Передать 500 МБ из `VG_SOURCE` в `VG_DEST`.

### Процедура

**1. Создать временный LV в `VG_SOURCE`:**

```bash
lvcreate -L 500M -n temp_transport_lv VG_SOURCE
```

**2. Инициализировать LV как PV:**

```bash
pvcreate /dev/VG_SOURCE/temp_transport_lv
```

**3. Добавить "виртуальный" PV в `VG_DEST`:**

```bash
vgextend VG_DEST /dev/VG_SOURCE/temp_transport_lv
```

**4. Использовать пространство в `VG_DEST`:**

Теперь в `VG_DEST` доступно 500 МБ для расширения томов.

**5. Очистка (после использования):**

```bash
# 1. Убедиться, что пространство не используется в VG_DEST
vgreduce VG_DEST /dev/VG_SOURCE/temp_transport_lv

# 2. Удалить PV-метки
pvremove /dev/VG_SOURCE/temp_transport_lv

# 3. Удалить временный LV
lvremove VG_SOURCE/temp_transport_lv
```

### Предупреждения

- **Не используйте для production** без тестирования
- **Риск потери данных** при ошибках
- **Сложность отката** — планируйте заранее

---

## Восстановление LVM после потери метаданных

> **Внимание:** Операции восстановления требуют точности. Ошибки могут привести к полной потере данных.

### Сценарий

Метаданные LVM на физическом томе (PV) удалены или повреждены. Требуется восстановить информацию о VG и LV.

### Процедура восстановления

**1. Создать дамп метаданных PV:**

Метаданные LVM хранятся в начале физического тома (обычно в первом мегабайте).

```bash
dd if=/dev/vdb of=pv_metadata_backup.img bs=1M count=1
```

> **Примечание:** `/dev/vdb` — пример устройства. Замените на ваше.

**2. Очистить дамп от нерелевантной информации:**

Файл содержит бинарные данные. Нужно оставить только текстовые секции LVM.

```bash
# Открыть для редактирования
vi pv_metadata_backup.img
```

**Задача:**
- Удалить бинарный "мусор" в начале файла
- Сохранить секции, начинающиеся с `pv_name`, `vg_name`, `lv_name`
- Найти и сохранить `uuid = "..."` (понадобится позже)

**3. Восстановить физический том (PV):**

```bash
pvcreate --uuid "<UUID_из_файла>" --restorefile pv_metadata_backup.img /dev/vdb
```

**Пример:**
```bash
pvcreate --uuid "XYZabc-1234-..." --restorefile pv_metadata_backup.img /dev/vdb
```

**4. Восстановить конфигурацию VG:**

```bash
vgcfgrestore -f pv_metadata_backup.img <имя_VG>
```

**Пример:**
```bash
vgcfgrestore -f pv_metadata_backup.img my_vg
```

**5. Активировать группу томов:**

```bash
vgchange -ay my_vg
```

**6. Проверить логические тома и монтирование:**

```bash
lvs
mount /dev/my_vg/my_lv /mnt/data
```

### Альтернативный метод: vgcfgrestore без дампа

Если есть резервная копия конфигурации в `/etc/lvm/backup/`:

```bash
# Список доступных конфигураций
ls /etc/lvm/backup/

# Восстановить из резервной копии
vgcfgrestore -f /etc/lvm/backup/my_vg my_vg
```

### Профилактика

**Регулярное резервное копирование метаданных:**

```bash
# Сохранить конфигурацию всех VG
vgcfgbackup

# Расположение резервных копий
ls /etc/lvm/backup/
```

**Настройка автобэкапа в `/etc/lvm/lvm.conf`:**

```ini
backup {
    backup = 1          # Включить автобэкап
    backup_dir = "/etc/lvm/backup"
    archive = 1         # Включить архивирование
    archive_dir = "/etc/lvm/archive"
    retain_min = 10     # Хранить минимум 10 копий
    retain_days = 30    # Хранить минимум 30 дней
}
```

---

## Замена swap-раздела на swap-файл

### Сценарий

Заменить swap-раздел на LVM-томе на swap-файл для упрощения управления.

### Процедура

**1. Создать swap-файл:**

```bash
# Создать файл размером 4 ГБ
dd if=/dev/zero of=/swapfile bs=1M count=4096 status=progress

# Установить права
chmod 600 /swapfile

# Инициализировать как swap
mkswap /swapfile

# Включить
swapon /swapfile
```

**2. Добавить в `/etc/fstab`:**

```
/swapfile none swap sw 0 0
```

**3. Удалить старый swap-LV:**

```bash
# Отключить swap-LV
swapoff /dev/my_vg/swap_lv

# Удалить LV
lvremove my_vg/swap_lv
```

### Преимущества swap-файла

- Не требует выделения LV
- Легко изменить размер
- Упрощает управление LVM-пространством

---

## Диагностика и troubleshooting

### Частые проблемы

| Проблема | Команда проверки | Решение |
| :--- | :--- | :--- |
| VG не активируется | `vgscan`, `vgdisplay` | Проверить наличие всех PV |
| LV не монтируется | `lvdisplay`, `dmesg` | Проверить ФС (`fsck`) |
| `/boot` на LVM | `mount | grep /boot` | Переместить на обычный раздел |
| Миграция зависла | `pvmove --status` | Не прерывать! Дождаться завершения |

### Команды диагностики

```bash
# Полная информация о структуре
pvs -o+pv_mda_size,vgs,lvs
vgs -o+vg_mda_size,pvs,lvs
lvs -o+lv_mda_size,vg,pvs

# Проверка целостности метаданных
pvck /dev/sdb1
vgck my_vg

# Поиск потерянных VG/LV
vgscan
lvscan
```

---

## Дополнительная информация

### Связанные темы

| Тема | Файл |
| :--- | :--- |
| Базовые концепции LVM | [overview_concepts.md](./overview_concepts.md) |
| Операции управления | [management_operations.md](./management_operations.md) |
| Снимки | [snapshots.md](./snapshots.md) |
| Тонкое провизионирование | [thin_provisioning.md](./thin_provisioning.md) |
| Шифрование дисков | ../../Security/encryption.md (dm-crypt/LUKS) |
| Загрузка Linux | ../../Boot/grub.md |

### Внешние ресурсы

- [LVM HOWTO (Linux Foundation)](https://wiki.linuxfoundation.org/lvm/start)
- [Red Hat: LVM Administration](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_logical_volumes/)
- [Arch Wiki: LVM](https://wiki.archlinux.org/title/LVM)
