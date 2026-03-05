# LVM: Расширенные темы — Практические сценарии

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

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — загрузка с LVM, файловые системы
- [Дополнительная информация](./advanced_topics.md) — диагностика, troubleshooting
