# LVM — Операции управления

## Определения

**Операции управления LVM** — совокупность административных задач по поддержке, мониторингу и изменению конфигурации системы логических томов на протяжении всего их жизненного цикла.

**LVM CLI Toolkit** — набор утилит пользовательского пространства (`pvs`, `vgs`, `lvs` и др.), взаимодействующих с Device Mapper в ядре для управления блочными устройствами.

**Фильтры LVM** — параметры конфигурации в `/etc/lvm/lvm.conf`, ограничивающие список блочных устройств, которые система должна сканировать при поиске метаданных LVM.

**Теги LVM (Tags)** — строковые метки (до 1024 символов), назначаемые объектам LVM (PV, VG, LV) для их группировки, массового управления или фильтрации.

## Базовые концепции

### Иерархия инструментов управления

Инструментарий LVM разделен по функциональному назначению:
1.  **Reporting (Отчеты):** `pvs`, `vgs`, `lvs`. Компактный табличный вывод.
2.  **Display (Детализация):** `pvdisplay`, `vgdisplay`, `lvdisplay`. Подробная многострочная информация.
3.  **Action (Действие):** `pvcreate`, `vgextend`, `lvchange`, `lvremove`. Команды, изменяющие структуру или атрибуты.
4.  **Maintenance (Обслуживание):** `vgscan`, `vgck`, `vgexport`, `vgimport`. Проверка и подготовка к миграции.

### Классификация задач по SSoT-файлам

| Категория | Основной документ | Описание задачи |
| :--- | :--- | :--- |
| **Инициализация** | [Создание PV, VG, LV](./operations/pv_vg_creation.md) | Первичная подготовка носителей и пулов. |
| **Масштабирование** | [Изменение размеров](./operations/lvm_resize.md) | Онлайн-расширение и уменьшение томов. |
| **Снимки** | [Снимки (Snapshots)](./snapshots.md) | Резервное копирование и точки отката (COW). |
| **Тонкие пулы** | [Thin Provisioning](./thin-provisioning.md) | Динамическое выделение места и переподписка. |
| **Миграция** | [Замена диска](./operations/lvm_disk_replacement.md) | Замена физических носителей через `pvmove`. |
| **Мониторинг** | [Просмотр информации](./operations/lvm_view_info.md) | Анализ состояния и атрибутов томов. |

## Практические сценарии

### Сценарий 1: Оперативная проверка здоровья (SRE Cheat Sheet)

```bash
# 1. Проверка физических дисков
sudo pvs
# → PV         VG      Fmt  Attr PSize   PFree
# → /dev/sdb   data_vg lvm2 a--  <20.00g <5.00g

# 2. Проверка свободного места в группах
sudo vgs
# → VG      #PV #LV #SN Attr   VSize   VFree
# → data_vg   1   2   0 wz--n- <20.00g <5.00g

# 3. Поиск переполненных томов или снимков
sudo lvs -o lv_name,data_percent,snap_percent
```

### Сценарий 2: Перенос группы томов на другой сервер

Используется при физическом перемещении дисков между хостами.

**На исходном сервере:**
```bash
# 1. Отмонтирование и деактивация
sudo umount /mnt/data
sudo vgchange -an vg_data
# → 0 logical volume(s) in volume group "vg_data" now active

# 2. Экспорт (пометка метаданных)
sudo vgexport vg_data
# → Volume group "vg_data" successfully exported
```

**На целевом сервере:**
```bash
# 1. Сканирование и импорт
sudo pvscan
# → PV /dev/sdc    is in exported VG vg_data [20.00 GiB / 5.00 GiB free]
sudo vgimport vg_data
# → Volume group "vg_data" successfully imported

# 2. Активация и монтирование
sudo vgchange -ay vg_data
sudo mount /dev/vg_data/lv_data /mnt/data
```

### Сценарий 3: Массовое управление через теги

Позволяет выполнять действия над группой объектов одновременно.

```bash
# 1. Назначение тегов
sudo vgchange --addtag production vg_data
sudo lvchange --addtag database vg_data/lv_db_01
sudo lvchange --addtag database vg_data/lv_db_02

# 2. Просмотр объектов с определенным тегом
sudo lvs @database

# 3. Массовая активация/деактивация по тегу
sudo lvchange -an @database
# → 2 logical volume(s) in volume group "vg_data" now inactive
```

### Управление метаданными и бэкапами

LVM автоматически сохраняет конфигурацию при каждом изменении.

-   **/etc/lvm/backup/** — содержит актуальную копию каждой VG.
-   **/etc/lvm/archive/** — история изменений метаданных (позволяет откатиться назад).

Подробные сценарии восстановления описаны в:
- **[LVM — Расширенные темы (Диагностика)](./advanced_topics/advanced_topics.md#сценарий-5-диагностика-целостности-метаданных)**
- **[LVM — Практические сценарии восстановления](./advanced_topics/practical_scenarios.md)**

## Дополнительная информация

### Диагностика и устранение неисправностей

| Проблема | Признак | Решение |
| :--- | :--- | :--- |
| **VG Not Found** | Группа не видна после подключения диска | Выполнить `vgscan` и проверить `global_filter` в **[lvm.conf](./advanced_topics/advanced_topics.md#фильтрация-устройств-lvmconf)**. |
| **Duplicate PV UUID** | Ошибка при клонировании дисков | Использовать `vgimportclone` для переименования VG и смены UUID. |
| **I/O Error (Thin)** | ФС перешла в Read-Only | Пул переполнен. Расширить пул или удалить снимки. Подробнее — в [Устранение неполадок: ФС в режиме read-only](../read_only_filesystem_troubleshooting.md). |

### См. также
- **[LVM — Обзор и концепции](./overview_concepts.md)** — архитектура и экстенты.
- **[LVM — Расширенные темы](./advanced_topics/advanced_topics.md)** — глубокая диагностика и `lvm.conf`.
- **[LVM — Просмотр информации](./operations/lvm_view_info.md)** — детальный разбор команд `lvs`, `vgs`.
