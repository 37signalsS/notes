# Просмотр информации LVM

## Определения

**Команды краткого вывода (Reporting commands)** — утилиты `pvs`, `vgs`, `lvs`, выводящие информацию в компактном табличном виде (одна строка на объект). Оптимальны для оперативного мониторинга и автоматизации.

**Команды подробного вывода (Display commands)** — утилиты `pvdisplay`, `vgdisplay`, `lvdisplay`, предоставляющие детальный многострочный отчет о каждом объекте, включая UUID, метаданные и внутренние параметры сегментов.

**Команды сканирования (Scanning commands)** — утилиты `pvscan`, `vgscan`, `lvscan`, предназначенные для поиска LVM-объектов на всех доступных блочных устройствах и обновления системного кэша.

## Базовые концепции

### Иерархия инструментов мониторинга

Инструментарий LVM разделен на уровни, соответствующие архитектуре PV → VG → LV.

| Объект | Краткий отчет | Подробный отчет | Область анализа |
| :--- | :--- | :--- | :--- |
| **Physical Volume (PV)** | `sudo pvs` | `sudo pvdisplay` | Физические диски, разделы, свободные экстенты |
| **Volume Group (VG)** | `sudo vgs` | `sudo vgdisplay` | Группы томов, размер PE, суммарные ресурсы |
| **Logical Volume (LV)** | `sudo lvs` | `sudo lvdisplay` | Логические разделы, точки монтирования, атрибуты |

### Атрибуты в выводе (Attr)

Столбец `Attr` содержит строку из 10 символов, описывающую состояние объекта.

**Расшифровка для Logical Volume (LV):**
1.  **Тип тома:** `v` (virtual), `V` (thin volume), `s` (snapshot), `o` (origin), `m` (mirrored), `r` (raid).
2.  **Права доступа:** `w` (writable), `r` (read-only).
3.  **Политика аллокации:** `a` (anywhere), `i` (inherited), `n` (normal).
4.  **Фиксированный minor:** `m` (fixed minor).
5.  **Состояние:** `a` (active), `s` (suspended), `I` (invalid snapshot), `S` (invalid thin volume).
6.  **Устройство открыто:** `o` (open — примонтировано или используется).
7.  **Тип цели:** `s` (snapshot), `m` (mirror), `t` (thin), `r` (raid).
8.  **Zeroing (для thin):** `z` (zero).
9.  **Здоровье:** `p` (partial — отсутствует часть PV), `r` (refresh needed).
10. **Активация:** `k` (skip activation).

## Практические сценарии

### Сценарий 1: Общая диагностика блочных устройств

Первым шагом рекомендуется использовать `lsblk` для понимания физической топологии.

```bash
lsblk
# → sdb           8:16   0   20G  0 disk
# → └─data_vg-lv_data 253:0    0   10G  0 lvm  /mnt/data
```

### Сценарий 2: Анализ свободного места и PE

Используется для принятия решения о расширении.

```bash
# Просмотр свободных экстентов (PE) в группах
sudo vgs -o vg_name,vg_size,vg_free,vg_free_count
# → VG      VSize   VFree  Free
# → data_vg <20.00g <5.00g 1279
```

### Сценарий 3: Мониторинг тонких пулов (Thin Provisioning)

Для тонких томов критично следить за физическим заполнением пула.

```bash
sudo lvs -o lv_name,data_percent,metadata_percent,lv_attr
# → LV          Data%  Meta%  Attr
# → thin_lv     15.40         Vwi-a-tz--
# → thin_pool   77.00  12.50  twi-aotz--
```
*Если `Data%` достигнет 100%, запись во все тонкие тома этого пула будет заблокирована.*

### Сценарий 4: Кастомизация вывода и фильтрация

LVM предоставляет мощные средства фильтрации через параметр `-S` (Selection).

```bash
# Найти все активные тома размером более 5 ГБ
sudo lvs -S 'lv_size > 5G && lv_active = "active"'

# Вывод в формате JSON для автоматизации
sudo lvs --reportformat json

# Использование специфических единиц измерения (MiB, GiB)
sudo lvs --units g
```

### Сценарий 5: Сортировка и выбор полей

```bash
# Сортировка томов по проценту заполнения (сначала самые полные)
sudo lvs --sort -data_percent

# Показать все доступные поля для формирования отчета
sudo pvs -o help
```

### Сценарий 6: Сканирование и активация

Используется после подключения новых дисков или при восстановлении системы.

```bash
sudo vgscan
# → Reading all physical volumes.  This may take a while...
# → Found volume group "data_vg" using metadata type lvm2

sudo lvscan
# → ACTIVE            '/dev/data_vg/lv_data' [10.00 GiB] inherit
# → INACTIVE          '/dev/data_vg/lv_backup' [5.00 GiB] inherit
```
*Если статус `INACTIVE`, том нужно активировать: `sudo vgchange -ay data_vg`.*

## Дополнительная информация

### См. также
- **[LVM — Управление томами](../management_operations.md)** — общая шпаргалка по операциям.
- **[LVM — Создание PV, VG и LV](./pv_vg_creation.md)** — инициализация структур.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — детальный разбор Data% и Meta%.
