# LVM: Операции Управления

## Определения

**Операции управления** — практические задачи по обслуживанию LVM: создание, изменение размеров, мониторинг, замена компонентов и удаление.

---

## Базовые операции

### Сводная таблица

| Операция | Файл | Описание |
| :--- | :--- | :--- |
| Создание PV, VG, LV | [pv_vg_creation.md](./operations/pv_vg_creation.md) | Инициализация дисков, создание структуры LVM |
| Изменение размеров | [lvm_resize.md](./operations/lvm_resize.md) | Расширение/уменьшение LV и ФС |
| Замена диска | [lvm_disk_replacement.md](./operations/lvm_disk_replacement.md) | Миграция данных через `pvmove` |
| Просмотр информации | [lvm_view_info.md](./operations/lvm_view_info.md) | Диагностика и мониторинг (`pvs`, `vgs`, `lvs`) |
| Полный жизненный цикл | [lvm_lifecycle.md](./operations/lvm_lifecycle.md) | End-to-end сценарий от создания до удаления |

---

## Быстрые команды

### Создание (минимальный набор)

```bash
pvcreate /dev/sdb1                    # Инициализация PV
vgcreate my_vg /dev/sdb1              # Создание VG
lvcreate -L 10G -n my_lv my_vg        # Создание LV
mkfs.ext4 /dev/my_vg/my_lv            # Форматирование
mount /dev/my_vg/my_lv /mnt/data      # Монтирование
```

### Просмотр состояния

```bash
pvs           # Кратко: PV, VG, размер, свободно
vgs           # Кратко: VG, #PV, #LV, размер, свободно
lvs           # Кратко: LV, VG, размер, % использовано

pvdisplay     # Подробно о PV
vgdisplay     # Подробно о VG (включая размер PE)
lvdisplay     # Подробно о LV (включая маппинг LE→PE)
```

### Расширение

```bash
# Расширение LV + ФС одной командой (ext4/xfs)
lvextend -L +5G -r /dev/my_vg/my_lv

# Расширение на всё свободное место в VG
lvextend -l 100%FREE -r /dev/my_vg/my_lv
```

### Замена диска

```bash
vgextend my_vg /dev/sdd1              # Добавить новый диск
pvmove /dev/sdc1                      # Миграция данных (долго!)
vgreduce my_vg /dev/sdc1              # Удалить старый диск из VG
pvremove /dev/sdc1                    # Очистить LVM-метки
```

---

## Практические сценарии

### Сценарий 1: Разметка нового диска

Полный процесс от подключения диска до монтирования: [pv_vg_creation.md](./operations/pv_vg_creation.md#практический-сценарий-разметка-нового-диска-с-помощью-lvm)

### Сценарий 2: Расширение тома на лету

Без остановки сервисов: [lvm_resize.md](./operations/lvm_resize.md#расширение-логического-тома-lv)

### Сценарий 3: Замена физического диска

Без простоя системы: [lvm_disk_replacement.md](./operations/lvm_disk_replacement.md)

### Сценарий 4: Резервное копирование через снимок

Консистентная копия без остановки: [snapshots.md](./snapshots.md)

### Сценарий 5: Восстановление после потери метаданных

Аварийное восстановление: [advanced_topics.md](./advanced_topics.md#восстановление-lvm-после-потери-метаданных)

---

## Диагностика и troubleshooting

### Проверка структуры

```bash
lsblk                         # Иерархия: диск → раздел → PV → LV → ФС
lvs -o+thin_pool,data_percent # Для тонких томов: состояние пула
```

### Частые проблемы

| Проблема | Команда проверки | Решение |
| :--- | :--- | :--- |
| Нет места в VG | `vgs` | Добавить PV через `vgextend` |
| LV не расширяется | `vgs`, `lvs` | Проверить свободное место в VG |
| Снимок переполнен | `lvs -o+snap_percent` | Удалить снимок или расширить |
| Пул тонких томов заполнен | `lvs -o+data_percent` | Расширить пул (`lvextend`) |
| Устройство не активируется | `vgscan`, `vgchange -ay` | Проверить наличие всех PV |

---

## Дополнительные темы

| Тема | Файл |
| :--- | :--- |
| Снимки (Snapshots) | [snapshots.md](./snapshots.md) |
| Тонкое провизионирование | [thin_provisioning.md](./thin_provisioning.md) |
| Расширенные темы | [advanced_topics.md](./advanced_topics.md) |
| Базовые концепции | [overview_concepts.md](./overview_concepts.md) |

---

## Внешние ресурсы

- [LVM HOWTO (Linux Foundation)](https://wiki.linuxfoundation.org/lvm/start)
- [Red Hat: LVM Administration](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_logical_volumes/)
