# LVM — снимки

## Предварительные требования

- Установлен пакет `lvm2`.
- Доступна или планируется создание **Volume Group (VG)** с достаточным свободным местом.
- Пользователь имеет права `root` или член группы `disk` (в большинстве дистрибутивов — через `sudo`).
- Файловая система на целевом LV смонтирована или готова к монтированию (для бэкапов — в режиме «только чтение» или с приостановкой записи).
- Для автоматического расширения снимков — запущен демон `dmeventd` (проверка: `systemctl status dmeventd`).

## Определения

**Снимок (Snapshot)** — виртуальная копия логического тома (LV), зафиксированная на определенный момент времени. Использует механизм **Copy-on-Write (COW)**, что позволяет создавать снимки мгновенно, независимо от объема данных. Снимок не содержит собственных данных until первая запись в соответствующий блок origin LV — он лишь ссылается на оригинальные блоки и начинает копировать их при изменении.

**COW (Copy-on-Write — копирование при записи)** — стратегия оптимизации, при которой новые данные записываются в новое место, а старые данные из исходного тома копируются в область снимка только в момент их первого изменения. Реализуется на уровне **device-mapper** — подсистемы ядра Linux, работающей на уровне блочных устройств.

**Thin Snapshot (Тонкий снимок)** — снимок, созданный внутри **Thin Pool**. Не требует фиксированного объема заранее и динамически потребляет пространство пула. Поддерживает рекурсию (снимок со снимка) без дополнительных ограничений.

**External Origin (Внешний источник)** — LV, используемый как read-only основа для тонких снимков. Позволяет создавать тонкие снимки от «толстых» LV, предварительно конвертируя их в read-only inactive.

## Базовые концепции

### Архитектура device-mapper и снимков

При создании первого COW-снимка LVM формирует четыре dm-устройства:

| Устройство | Роль |
| :--- | :--- |
| `-real` | Оригинальная таблица маппинга исходного тома |
| `-cow` | Блочное устройство для хранения скопированных блоков |
| `snapshot` | Комбинация `-real` и `-cow` — видимый снимок для пользователя |
| `snapshot-origin` | Заменяет оригинальный LV; все новые записи проходят через него |

*Структура для LV `vol` с снимком `snap`:*
```
/dev/vg_data/vol-real       — исходные данные
/dev/vg_data/vol_cow        — COW-буфер снимка
/dev/vg_data/snap           — видимый снимок (combinация real + cow)
/dev/vg_data/vol            — теперь это snapshot-origin (направляет записи)
```

### Принцип работы COW

При создании обычного (толстого) снимка выделяется специальная область — COW-буфер.
1.  **Запрос на запись:** Приходит на блок `A` исходного тома через `snapshot-origin`.
2.  **Сохранение оригинала:** Device-mapper считывает блок `A` из `snapshot-origin` и записывает его в COW-буфер (`-cow`).
3.  **Обновление данных:** Новые данные записываются в блок `A` исходного тома.
4.  **Чтение из снимка:** При обращении к снимку device-mapper проверяет таблицу COW — если блок был скопирован, возвращает копию из `-cow`; если нет — читает из `-real`.

*Результат:* Снимок содержит «старое» состояние блока, исходный том — «новое». Чтения и записи в снимок не влияют друг на друга.

### Chunk size (Размер блока COW)

**Chunk size** — размер минимальной единицы данных, копируемой при одной операции COW. Определяется флагом `-c` при создании снимка или параметром `--chunksize` для thin pool.

**Для COW-снимков:** допустимые значения — степень двойки от 4 KiB до 512 KiB (по умолчанию **4 KiB**).

**Влияние на производительность:**

| Chunk Size | Write Overhead | Примечание |
| :--- | :--- | :--- |
| 4 KiB (по умолчанию) | до 78x медленнее | Худший вариант для random writes |
| 64 KiB | ~3x медленнее | Заметное улучшение |
| 256 KiB | ~1.1x (почти нативная) | Хороший баланс |
| 512 KiB | ~1x (без штрафа) | Лучшая пропускная способность, но больше COW-пространства на запись |

*Компромисс:* Увеличение chunk size снижает overhead записи, но увеличивает потребление COW-пространства (даже изменение 1 байта приводит к копированию всего чанка). Для короткоживущих бэкап-снимков рекомендуется 256–512 KiB.

**Для Thin Pool:** значения кратны 64 KiB, от 64 KiB до 1 GiB (по умолчанию 64 KiB с масштабированием под размер metadata).

```bash
# Просмотр chunk size существующего снимка
sudo lvs -o lv_name,lv_size,chunk_size,origin vg_data
# → LV        LSize   Chunk   Origin
# → lv_snap   3.00g   512.00k lv_data
```

### Метаданные снимка

Каждый COW-снимок содержит небольшую область метаданных, отслеживающих, какие блоки были скопированы. Этот overhead составляет часть выделенного размера снимка (поэтому полезный COW-объем всегда меньше заявленного).

**Рекомендация по размеру COW-буфера:**
- Минимум: 10–20% от размера origin LV.
- Для бэкапов БД: зависит от write rate. Формула: `размер = (write_rate × время_бэкапа) × 2`. Например, при 500 MB/час записи и 15-минутном бэкапе: `500 × 0.25 × 2 = 250 MiB`.
- Если COW-буфер заполняется — снимок становится невалидным и возвращает I/O ошибки. **Восстановление невозможно** — только удаление и пересоздание.

### Влияние на производительность

Использование снимков создает дополнительную нагрузку на дисковую подсистему:
-   **Задержка при записи (Latency):** Каждая первая запись в блок требует чтения оригинала, записи копии в COW и записи нового значения — 3 операции ввода-вывода вместо 1 (при chunk size 4 KiB). При chunk size 512 KiB overhead минимален.
-   **Множественные снимки:** Если у одного LV есть 5 снимков, одна запись в исходный том может породить до 5 операций копирования (по одной в каждый снимок). Это критично для COW-снимков; тонкие снимки делят pool и не создают множественный overhead.
-   **Чтения из снимка:** Чтение неизмененных блоков идет напрямую из origin (без задержки). Чтение измененных блоков требует дополнительного чтения из COW-области.
-   **Метаданные:** Даже без actual COW-операций, наличие активного снимка добавляет небольшой overhead на каждую запись для проверки таблицы блоков.

### Атрибуты и мониторинг состояния

В выводе команды `lvs` состояние снимка отображается в колонке `Attr` (10 символов). Полная расшифровка:

| Позиция | Символ | Описание |
| :--- | :--- | :--- |
| 1 (Тип) | `s` | Обычный COW-снимок (Snapshot) |
| 1 (Тип) | `S` | Невалидный COW-снимок (Invalid) — переполнен |
| 1 (Тип) | `V` | Тонкий снимок (Thin Snapshot) |
| 2 (Запись) | `w` | Read-write (можно писать) |
| 2 (Запись) | `r` | Read-only |
| 3 (Активность) | `a` | Активен |
| 3 (Активность) | `i` | Неактивен (inactive) |
| 4 (Статус) | `o` | Снимок готов к слиянию (merge started / snapshot-merge) |
| 4 (Статус) | `O` | Снимок ожидает слияния (snapshot merge overflow) |
| 5 (Атрибут) | `p` | Persistent (непрерывный) |
| 5 (Атрибут) | `P` | Temporary (временный) |
| 6 (Выделение) | `a` | Выделен (allocated) |
| 6 (Выделение) | `-` | Не выделен |
| 7 (Непрерывность) | `c` | Contiguous (непрерывное выделение) |
| 8 (Размер) | `l` | Fixed size (фиксированный размер) |
| 8 (Размер) | `L` | May be resized (может быть расширен) |
| 9 (Мониторинг) | `m` | Monitored by dmeventd |
| 10 (Активация) | `k` | Activation skip (пропуск при автоматической активации) |
| 10 (Активация) | `-` | Без пропуска активации |

*Пример вывода с разными состояниями:*
```bash
lvs -a -o lv_name,vg_name,attr,lsize,snap_percent,origin
# → LV              VG       Attr       LSize   Snap%  Origin
# → lv_data_snap    vg_data  Swi-a----  2.00g   45.12  lv_data     # Нормальный COW-снимок
# → lv_data_snap2   vg_data  Swi-I-p--- 2.00g   100.00 lv_data     # Переполнен (невалиден)
# → thin_snap       vg_data  Vwi---tz-k 5.00g          thin_vol    # Thin-снимок (activation skip)
```

**Важные комбинации:**
- `Swi-I-p---` — COW-снимок переполнен, невалиден, необходимо удалить.
- `Vwi-a-tz-k` — тонкий снимок активен, но с activation skip; требует `lvchange -ay -K` для включения.
- `Swi-a----` — здоровый COW-снимок, готов к использованию.

### Автоматическое расширение

LVM поддерживает автоматическое расширение снимков при достижении порога заполнения. Настраивается в `/etc/lvm/lvm.conf` в секции `activation`.

```conf
# /etc/lvm/lvm.conf
activation {
    snapshot_autoextend_threshold = 100   # Порог заполнения (%, по умолчанию 100 = выключен)
    snapshot_autoextend_percent = 20      # Процент расширения от текущего размера
}
```

*Логика:* При заполнении снимка на `threshold`% он будет расширен на `percent`% от текущего размера.
**Требования:**
1.  В системе должен быть запущен демон `dmeventd` (мониторит снимки через polling).
2.  В VG должно быть достаточно свободного места.
3.  По умолчанию порог = 100% (автоматическое расширение **выключено**). Для включения установите значение, например, 70–80.

```bash
# Проверка статуса dmeventd
systemctl status dmeventd
# → active (running) ...

# Проверка текущих настроек
sudo lvm dumpconfig activation/snapshot_autoextend_threshold
# → 100
```

## Практические сценарии

### Сценарий 1: Создание снимка

**Базовое создание COW-снимка:**
```bash
sudo lvcreate -L 2G -s -n lv_root_snap /dev/vg_system/lv_root
# → Logical volume "lv_root_snap" created.
```

**Создание с оптимальным chunk size (для бэкапов):**
```bash
# 256 KiB — хороший баланс для большинства сценариев
sudo lvcreate -c 256K -L 3G -s -n lv_backup_snap /dev/vg_data/lv_data
```

**Создание с пропуском активации (Activation Skip):**
Полезно для бэкапов, чтобы устройство не появлялось в `/dev/mapper` сразу и не было автоматически смонтировано.
```bash
sudo lvcreate -L 5G -s -n lv_backup_snap -ky /dev/vg_data/lv_data
```
*Для активации такого снимка вручную:*
```bash
sudo lvchange -ay -K /dev/vg_data/lv_backup_snap
# → Logical volume "lv_backup_snap" changed.
```

**Создание тонкого снимка (Thin Snapshot):**
Тонкие снимки создаются от thin LV и не требуют указания размера — они потребляют space из thin pool динамически.
```bash
# Если lv_data — thin LV:
sudo lvcreate -s -n thin_snap /dev/vg_data/lv_data
# → Logical volume "thin_snap" created.
```
*Важно:* Не указывайте `-L`/`--size` — иначе LVM создаст COW-снимок вместо thin.

**Создание thin-снимка от внешнего источника (External Origin):**
Позволяет создать тонкий снимок от «толстого» LV:
```bash
# 1. Конвертируем LV в read-only inactive
sudo lvchange -an /dev/vg_data/lv_external
sudo lvchange -permission r /dev/vg_data/lv_external

# 2. Создаем thin-снимок, указывая thin pool
sudo lvcreate -s -n thin_snap_ext --thinpool vg_data/thin_pool /dev/vg_data/lv_external
```

### Сценарий 2: Восстановление данных (Слияние)

Используется утилита `lvconvert --merge` для возврата состояния тома.

**Внимание:** Для корневой ФС потребуется перезагрузка. Для обычных томов — размонтирование.

**Обычное слияние (без активного LV):**
```bash
# 1. Размонтирование (если возможно)
sudo umount /dev/vg_data/lv_data

# 2. Деактивация целевого LV (если активен)
sudo lvchange -an /dev/vg_data/lv_data

# 3. Запуск слияния
sudo lvconvert --merge /dev/vg_data/lv_data_snap
# → Merging of volume vg_data/lv_data_snap started.

# 4. Активация тома после слияния
sudo lvchange -ay /dev/vg_data/lv_data

# 5. Монтирование
sudo mount /dev/vg_data/lv_data /mnt/data
```

**Слияние активного LV (approximate merge):**
Слияние может выполняться «в фоне» для активного LV — новые записи идут в origin, пока COW-данные копируются обратно. Во время слияния снимок возвращает I/O ошибки при обращении.
```bash
sudo lvconvert --merge /dev/vg_data/lv_data_snap
# → Merging of volume vg_data/lv_data_snap started.

# Проверка прогресса слияния:
sudo lvs -o lv_name,attr,lsize,snap_percent,origin
# → LV            Attr       LSize   Snap%  Origin
# → lv_data_snap  Swi-a----  2.00g   5.23   lv_data    # Snap% уменьшается при слиянии
```

**Слияние для корневой ФС (с перезагрузкой):**
```bash
# 1. Запуск слияния (LV remains active)
sudo lvconvert --merge /dev/vg_system/lv_root_snap
# → Merging of volume vg_system/lv_root_snap started.

# 2. Перезагрузка — merge завершится при неактивном LV
sudo reboot

# 3. После перезагрузки проверить
mount | grep vg_system
sudo lvs -o lv_name,attr,lsize,origin vg_system
```

**Важно:** После успешного слияния снимок автоматически удаляется.

### Сценарий 3: Мониторинг и ручное расширение

Критически важно для предотвращения выхода снимка из строя (`Snap%` не должен достигать 100%).

```bash
# Просмотр всех снимков с процентом заполнения
sudo lvs -o lv_name,vg_name,lv_size,snap_percent,origin,attr
# → LV            VG      LSize   Snap%  Origin   Attr
# → lv_root_snap  vg_sys   2.00g  45.12  lv_root  Swi-a----
# → lv_data_snap  vg_data  5.00g  12.34  lv_data  Swi-a----

# Просмотр chunk size
sudo lvs -o lv_name,chunk_size,origin vg_data
# → LV           Chunk   Origin
# → lv_data_snap 256.00k lv_data
```

**Ручное расширение COW-снимка:**
```bash
sudo lvextend -L +1G /dev/vg_system/lv_root_snap
# → Logical volume vg_system/lv_root_snap successfully resized.
```

**Расширение на процент от текущего размера:**
```bash
# Расширить на 50% от текущего размера
sudo lvextend -l +50%L /dev/vg_data/lv_data_snap
```

**Проверка свободного места в VG (для расширения):**
```bash
sudo vgs
# → VG       #PV #LV #SN Attr   VSize   VFree
# → vg_data    1   3   2 wz--n- 500.00g 200.00g
```

**Настройка мониторинга через dmeventd:**
```bash
# Включить мониторинг для конкретного снимка
sudo lvchange -my y /dev/vg_data/lv_data_snap

# Отключить мониторинг
sudo lvchange -my n /dev/vg_data/lv_data_snap
```

### Сценарий 4: Традиционные (Thick) vs Тонкие (Thin) снимки

| Характеристика | Традиционные (Thick) | Тонкие (Thin) |
| :--- | :--- | :--- |
| **Рекурсия** | Нет (нельзя сделать снимок со снимка) | **Да** (любая глубина вложенности) |
| **Выделение места** | Сразу (фиксированный размер из VG) | Динамически из Thin Pool |
| **Производительность** | Падает с числом снимков (множественные COW-операции) | Почти не зависит от количества (shared pool) |
| **Переполнение** | Умирает конкретный снимок | Может заблокировать весь Thin Pool (все LV become read-only) |
| **Стоимость места** | Каждый снимок = фиксированный объем | Общий пул, динамическое потребление |
| **Внешний источник** | Не поддерживается | Поддерживается (external origin) |
| **Активация** | По умолчанию активен | С activation skip по умолчанию |

**Пример рекурсивного тонкого снимка:**
```bash
# Снимок со снимка
sudo lvcreate -s -n thin_snap_v2 /dev/vg_data/thin_snap_v1

# Цепочка снимков
sudo lvs -a -o lv_name,origin,pool,attr vg_data
# → LV            Origin       Pool     Attr
# → thin_snap_v2  thin_snap_v1 thin_pool Vwi---tz-k
# → thin_snap_v1  thin_vol     thin_pool Vwi---tz-k
# → thin_vol                   thin_pool Vwi-a-tz--
```

**Примечание:** Для thin-снимков нет жесткого лимита на количество. Однако каждый добавляет нагрузку на метаданные thin pool. Рекомендуется не превышать 100–200 активных снимков без оценки размера метаданных.

### Сценарий 5: Бэкап через снимок (базовый workflow)

Самый распространенный use-case. Снимок позволяет получить консистентный бэкап работающей ФС.

```bash
# 1. Создание снимка для бэкапа
sudo lvcreate -L 5G -s -n snap_for_backup -ky /dev/vg_data/lv_data
# → Logical volume "snap_for_backup" created.

# 2. Активация снимка
sudo lvchange -ay -K /dev/vg_data/snap_for_backup

# 3. Монтирование снимка (read-only для целостности)
sudo mkdir -p /mnt/backup_snap
sudo mount -o ro /dev/vg_data/snap_for_backup /mnt/backup_snap

# 4. Выполнение бэкапа (например, tar)
sudo tar czf /backup/data_backup_$(date +%Y%m%d).tar.gz -C /mnt/backup_snap .

# 5. Отмонтирование и удаление снимка
sudo umount /mnt/backup_snap
sudo lvremove -f /dev/vg_data/snap_for_backup
# → Logical volume "snap_for_backup" successfully removed.
```

**Автоматизация (cron):**
```bash
# /etc/cron.d/lvm_backup — ежедневный бэкап в 2:00
0 2 * * * root /usr/local/sbin/lvm_backup.sh
```

### Сценарий 6: Откат после неудачного обновления/деплоя

Снимок позволяет откатить entire LV до состояния до обновления за секунды.

```bash
# 1. Создание снимка ПЕРЕД обновлением
sudo lvcreate -L 3G -s -n snap_before_update -ky /dev/vg_system/lv_app

# 2. Активация снимка
sudo lvchange -ay -K /dev/vg_system/snap_before_update

# 3. Выполнение обновления (например, деплой нового релиза)
sudo systemctl stop myapp
sudo tar xzf /tmp/new_release.tar.gz -C /opt/myapp/
sudo systemctl start myapp

# 4. Если обновление прошло успешно — удаляем снимок
sudo lvremove -f /dev/vg_system/snap_before_update

# 5. Если обновление прошло НЕУДАЧНО — откат
sudo systemctl stop myapp
sudo umount /opt/myapp    # если примонтировано
sudo lvconvert --merge /dev/vg_system/snap_before_update
# → Merging of volume vg_system/snap_before_update started.
sudo reboot    # для LV, требующего перезагрузки
# Или для без перезагрузки (если LV не корневой):
sudo lvchange -an /dev/vg_system/lv_app
sudo lvchange -ay /dev/vg_system/lv_app
sudo mount /dev/vg_system/lv_app /opt/myapp
sudo systemctl start myapp
```

### Сценарий 7: Проверка ФС без простоя (offline fsck)

Безопасный способ проверить ФС на работающем сервере через LVM-снапшот описан в [Проверка и восстановление ФС (fsck)](../fsck.md#3-проверка-без-простоя-через-lvm-snapshot).

### Сценарий 8: Создание полного бэкапа сервера (LVM + ФС)

Комплексный сценарий для серверов с несколькими LV.

```bash
#!/bin/bash
# /usr/local/sbin/lvm_full_backup.sh
# Требования: lvm2, tar, gzip

BACKUP_DIR="/backup"
DATE=$(date +%Y%m%d_%H%M%S)
VG_NAME="vg_data"

# Список LV для бэкапа
LV_LIST=("lv_data" "lv_logs" "lv_db")

for LV in "${LV_LIST[@]}"; do
    SNAP_NAME="${LV}_snap_${DATE}"
    
    echo "=== Бэкап ${LV} ==="
    
    # Создание снимка (размер = 20% от LV, или минимум 2G)
    LV_SIZE=$(sudo lvs --noheadings --units g -o lv_size ${VG_NAME}/${LV} | tr -d ' .g')
    SNAP_SIZE=$(( LV_SIZE / 5 + 1 ))
    [ ${SNAP_SIZE} -lt 2 ] && SNAP_SIZE=2
    
    sudo lvcreate -L ${SNAP_SIZE}G -s -n ${SNAP_NAME} -ky /dev/${VG_NAME}/${LV}
    sudo lvchange -ay -K /dev/${VG_NAME}/${SNAP_NAME}
    
    # Монтирование и бэкап
    MNT_POINT="/mnt/snap_$$"
    sudo mkdir -p ${MNT_POINT}
    sudo mount -o ro /dev/${VG_NAME}/${SNAP_NAME} ${MNT_POINT}
    
    sudo tar czf ${BACKUP_DIR}/${LV}_${DATE}.tar.gz -C ${MNT_POINT} .
    
    # Очистка
    sudo umount ${MNT_POINT}
    sudo lvremove -f /dev/${VG_NAME}/${SNAP_NAME}
    
    echo "=== ${LV} завершен ==="
done
```

## Типичные ошибки и их решение

### `Can't merge over active LV`

**Причина:** Целевой LV активен и/или смонтирован. Слияние требует неактивного состояния.

**Решение:**
```bash
# 1. Отмонтировать LV (если примонтирован)
sudo umount /dev/vg_data/lv_data

# 2. Деактивировать LV
sudo lvchange -an /dev/vg_data/lv_data

# 3. Запустить слияние
sudo lvconvert --merge /dev/vg_data/lv_data_snap

# 4. Активировать обратно
sudo lvchange -ay /dev/vg_data/lv_data
```

### Snapshot переполнен (Snap% = 100%, Attr содержит `S` или `I`)

**Причина:** COW-буфер исчерпан. Снимок невалиден и не может быть восстановлен.

**Решение:**
```bash
# 1. Удалить невалидный снимок
sudo lvremove -f /dev/vg_data/lv_data_snap

# 2. Создать новый снимок с бОльшим размером
sudo lvcreate -L 5G -s -n lv_data_snap_new /dev/vg_data/lv_data
```

### Снимок не активируется (Activation Skip — `k` в Attr)

**Причина:** Thin-снимки по умолчанию создаются с activation skip.

**Решение:**
```bash
sudo lvchange -ay -K /dev/vg_data/thin_snap
# Или отключить skip навсегда:
sudo lvchange --setactivationskip n /dev/vg_data/thin_snap
```

### `dmeventd` не запущен — автоматическое расширение не работает

**Причина:** Демон мониторинга не активен.

**Решение:**
```bash
sudo systemctl enable --now dmeventd
# Проверка:
systemctl status dmeventd
```

### Thin Pool переполнен — все LV become read-only

**Причина:** Thin pool исчерпал физическое пространство.

**Решение:**
```bash
# 1. Проверить статус пула
sudo lvs -o lv_name,attr,data_percent,metadata_percent vg_data/thin_pool

# 2. Расширить thin pool data
sudo lvextend -L +10G /dev/vg_data/thin_pool

# 3. Расширить thin pool metadata (если нужно)
sudo lvextend -L +1G /dev/vg_data/thin_pool_tmeta

# 4. Принудительно сделать LV доступным для записи
sudo lvchange -ay /dev/vg_data/thin_pool
```

### Ошибка `merge already in progress`

**Причина:** Предыдущее слияние еще не завершено.

**Решение:**
```bash
# Проверить статус слияния
sudo lvs -o lv_name,attr,snap_percent,origin
# → LV           Attr       Snap%  Origin
# → lv_data_snap Swi-a----  12.50  lv_data   # Snap% уменьшается = merge в процессе

# Дождаться завершения (Snap% → 0)
# Или принудительно удалить снимок (потеря данных отката)
sudo lvremove -f /dev/vg_data/lv_data_snap
```

### См. также
- **[LVM — Тонкое провизионирование](./thin-provisioning.md)** — подробнее о работе Thin Pool и рекурсии.
- **[LVM — Просмотр информации](./operations/lvm_view_info.md)** — детальное описание атрибутов и фильтрации.
- **[LVM — Управление томами](./management_operations.md)** — общая шпаргалка по командам.
- **[LVM — Практические сценарии восстановления](./advanced_topics/practical_scenarios.md)** — продвинутые методы восстановления.

## Best Practices

1. **Размер COW-буфера:** 15–20% от size origin LV для общих случаев. Для бэкапов БД — формула `(write_rate × backup_time) × 2`.
2. **Chunk size:** Для бэкапов и краткосрочных снимков — 256–512 KiB. Для long-lived снимков с random writes — 64 KiB (экономия COW-места).
3. **Время жизни:** Удаляйте снимки сразу после завершения операции (бэкапа, обновления). Не храните активные снимки дни без необходимости.
4. **Мониторинг:** Настройте `snapshot_autoextend_threshold = 80` и запустите `dmeventd`. Добавьте алертинг на `Snap% > 80%`.
5. **Именование:** Используйте осмысленные имена с датой: `snap_app_20260913`.
6. **Thin-снимки:** Предпочитайте thin snapshots для частых операций (dev/test, CI/CD). Для короткоживущих бэкапов COW-снимки проще в управлении.
7. **Не смонтированные снимки:** Используйте `-ky` (activation skip) для бэкап-снимков, чтобы избежать автоматического монтирования.
8. **Проверка перед слиянием:** Убедитесь, что LV не примонтирован и не используется процессами. Проверка: `lsof /dev/vg_data/lv_data`.
9. **Резервное копирование метаданных:** Регулярно делайте бэкап VG-структуры: `vgcfgbackup vg_data`.
10. **Не используйте снимки как permanent storage:** Снимки — временный инструмент для бэкапов и откатов, не для хранения данных.

## Ограничения и особые случаи

- **Невозможно восстановить невалидный снимок:** Если Snap% достиг 100% — снимок безвозвратно потерян. Только удаление и пересоздание.
- **Нельзя изменить размер COW-снимка вниз:** `lvreduce` для снимков поддерживается, но не рекомендуется — риск повреждения данных.
- **Merge для root LV требует reboot:** Device-mapper не может заменить таблицу активного корневого устройства без перезагрузки.
- **Thin pool overflow блокирует все LV:** В отличие от COW-снимков (умирает только снимок), переполнение thin pool делает read-only ВСЕ LV в пуле.
- **Рекурсия только для thin:** COW-снимки не поддерживают вложенность. Thin-снимки — да, без ограничений на глубину.
- **Производительность при множественных снимках:** Каждый активный COW-снимок добавляет overhead на каждую запись в origin. 5+ снимков = значительное падение записи.
- **Снимки не копируют данные:** Снимок — это point-in-time указатель. Чтение идет из оригинальных блоков (если не изменены). Нельзя смонтировать снимок и ожидать, что он будет работать как independent копия volume.
- **Metadata overhead:** Полезный COW-объем всегда меньше выделенного размера снимка (часть space = метаданные).
