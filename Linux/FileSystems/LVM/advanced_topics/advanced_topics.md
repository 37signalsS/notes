# LVM: Расширенные темы

## Предварительные требования

- Установлен пакет `lvm2`.
- Доступна Volume Group (VG) для экспериментов или выделенный тестовый стенд.
- Пользователь имеет права `root` или член группы `disk`.
- Знакомство с базовыми концепциями LVM (PV/VG/LV) и основными командами.
- Для сценариев с initramfs — доступ к загрузчику GRUB и консольному доступу (или IPMI/iDRAC/iLO для удаленных серверов).

## Определения

**Расширенные темы LVM** — комплексные вопросы эксплуатации системы логических томов, включающие взаимодействие с процессом загрузки ОС, глубокую диагностику метаданных, фильтрацию устройств, использование встроенных механизмов RAID и кэширования, тюнинг производительности и восстановление в нештатных ситуациях.

**initramfs (Initial RAM Filesystem)** — временная файловая система, загружаемая ядром Linux при старте системы. Содержит минимальный набор драйверов и утилит (включая LVM, mdadm, cryptsetup), необходимых для поиска и монтирования корневого раздела. В большинстве современных дистрибутивов форматируется как cpio-архив, распаковываемый в оперативную память.

**LVM RAID** — метод создания отказоустойчивых логических томов, использующий драйверы MD (Multiple Devices) ядра Linux, но управляемый через интерфейс LVM. Поддерживает уровни RAID 0, 1, 4, 5, 6, 10. В отличие от классического mdadm, позволяет создавать RAID-тома внутри VG, используя свободное пространство PV.

**LVM Cache (dm-cache)** — технология, позволяющая использовать быстрый накопитель (NVMe/SSD) в качестве кэширующего слоя для медленного LV (HDD), ускоряя операции чтения и записи. Работает на уровне device-mapper и прозрачна для файловой системы.

**LVM CacheV (dm-writecache / dm-cache с writeback)** — расширение LVM Cache, поддерживающее режим writeback с journal-операциями для обеспечения целостности данных при отказе кэш-устройства.

**MDA (Metadata Area)** — зарезервированная область в начале физического тома (PV), содержащая описание структуры группы томов (VG) в текстовом формате. Каждый PV может содержать до 255 MDA. Стандартный размер — 1 MiB, что позволяет хранить метаданные VG с тысячами LV.

**LVM Filter** — набор правил в конфигурационном файле `lvm.conf`, определяющий, какие блочные устройства LVM должен сканировать, а какие — игнорировать. Фильтры применяются на уровне regex и критичны в средах с Multipath, iSCSI, Docker, NVMe-oF.

**VG Metadata (Метаданные группы томов)** — структура данных, описывающая физические тома, логические тома, сегменты, их расположение и зависимости. Хранится в MDA в текстовом формате и реплицируется на все PV в VG.

## Базовые концепции

### Взаимодействие с процессом загрузки

Для успешной загрузки системы с корнем на LVM необходимы: (1) утилиты LVM в initramfs, (2) корректная конфигурация загрузчика, (3) доступность всех PV на этапе early boot.

#### Ограничение размещения /boot

Рекомендуется выносить каталог `/boot` на отдельный стандартный раздел (не LVM).

**Причины:**
1. **Восстановление:** При повреждении метаданных LVM прямой доступ к `/boot` упрощает восстановление без специальных инструментов.
2. **Загрузчики:** Некоторые загрузчики (в Legacy BIOS) не поддерживают чтение LVM. UEFI обычно поддерживает, но с оговорками.
3. **initramfs:** Если initramfs не содержит LVM-модулей, система не сможет смонтировать корень.

**Стандартная схема:**
```
/dev/sda1  (512 МБ – 1 ГБ, ext4/XFS) — /boot
/dev/sda2  (LVM PV)                   — корень всех LV (/, /home, swap и т.д.)
```

**UEFI/GPT с NVMe:**
```
/dev/nvme0n1p1  (512 МБ, FAT32, esp flag)  — /boot/efi
/dev/nvme0n1p2  (1 ГБ, ext4)               — /boot
/dev/nvme0n1p3  (LVM PV)                   — все LV
```

**Загрузка с LVM без /boot (допустимо):** Если initramfs корректно собран и содержит LVM-модули, `/boot` может находиться внутри LV. Однако это создаёт порочный круг: при повреждении LVM-метаданных вы не сможете ни загрузить систему, ни восстановить метаданные без Live CD.

#### Событийная активация (systemd)

LVM интегрируется с `systemd` через следующие службы:

| Служба | Описание | Важность |
| :--- | :--- | :--- |
| `lvm2-pvscan@.service` | Автоматическое сканирование PV при обнаружении устройства ядром (через udev) | Критическая для hot-plug |
| `lvm2-monitor.service` | Мониторинг состояния томов и снимков через демон `dmeventd` | Авто-расширение Thin Pool |
| `lvm2-activation-early.service` | Ранняя активация LV (до монтирования корня) | Обязательна для root on LVM |
| `lvm2-activation-net.service` | Активация LV с отложенными сетевыми устройствами (iSCSI, FC) | Для SAN-хранилищ |

**Проверка состояния:**
```bash
systemctl status lvm2-pvscan@*.service
systemctl status lvm2-monitor.service
systemctl status dmeventd
```

**Включение/отключение мониторинга:**
```bash
# Включение dmeventd (авто-расширение Thin Pool и снимков)
sudo systemctl enable --now dmeventd

# Отключение (не рекомендуется на production)
sudo systemctl disable --now dmeventd
```

#### Восстановление initramfs

Если система не находит VG при загрузке (ошибка `Volume group not found` или `Cannot activate logical volumes`), необходимо пересобрать initramfs с включением LVM-модулей.

**Диагностика (из Live CD или emergency shell):**
```bash
# Проверка, содержит ли initramfs LVM-модули
lsinitramfs /boot/initrd.img-$(uname -r) | grep lvm
# Или для dracut:
lsinitrd /boot/initramfs-$(uname -r) | grep lvm

# Проверка наличия vgchange в initramfs
lsinitramfs /boot/initrd.img-$(uname -r) | grep vgchange
```

**Для Debian / Ubuntu:**
```bash
# Добавление модуля
echo "lvm2" | sudo tee -a /etc/initramfs-tools/modules

# Обновление образа для текущего ядра
sudo update-initramfs -u

# Обновление для всех ядер
sudo update-initramfs -u -k all

# Проверка результата
lsinitramfs /boot/initrd.img-$(uname -r) | grep lvm
```

**Для RHEL / Rocky / Fedora (dracut):**
```bash
# Принудительное включение модуля
sudo dracut --force --add lvm --regenerate-all

# С определённым ядром
sudo dracut --force --add lvm /boot/initramfs-$(uname -r).img $(uname -r)

# Проверка
lsinitrd /boot/initramfs-$(uname -r) | grep lvm
```

**Для Arch Linux:**
```bash
sudo mkinitcpio -P
```

**Восстановление через emergency shell (без Live CD):**
Если система попала в emergency shell из-за отсутствия LVM в initramfs:
```bash
# 1. Монтирование корня (если VG виден)
sudo vgchange -ay vg_system
sudo mount /dev/vg_system/lv_root /root

# 2. chroot и пересборка initramfs
sudo chroot /root
sudo update-initramfs -u    # Debian/Ubuntu
# Или
sudo dracut --force --add lvm --regenerate-all    # RHEL/Fedora
```

### Фильтрация устройств (lvm.conf)

По умолчанию LVM сканирует все блочные устройства в `/dev/`. В сложных средах (Multipath, iSCSI, Docker, NVMe-oF) это может привести к ошибкам дублирования или существенному замедлению работы.

#### Типы фильтров

| Параметр | Область применения | Рекомендация |
| :--- | :--- | :--- |
| `filter` | Только утилиты LVM (lvcreate, vgextend и т.д.) | Для обычных серверов |
| `global_filter` | Все утилиты, включая pvscan и vgscan | Для Multipath/SAN/сложных сред |

**Синтаксис:** Массив регулярных выражений, применяемых последовательно:
- `a|паттерн|` — принять (accept) устройства, соответствующие паттерну
- `r|паттерн|` — отклонить (reject) устройства, соответствующие паттерну

*Важно:* Фильтры применяются в порядке объявления. Первое совпадение определяет судьбу устройства.

#### Типичные конфигурации

**Multipath (использование только mpath-устройств):**
```ini
devices {
    global_filter = [ "a|/dev/mapper/mpath.*|", "r|.*|" ]
}
```

**Игнорирование CD-ROM и виртуальных устройств:**
```ini
devices {
    filter = [ "a|.*|", "r|/dev/cdrom.*|", "r|/dev/sr.*|" ]
}
```

**Игнорирование Docker loop-устройств:**
```ini
devices {
    filter = [ "a|.*|", "r|/dev/loop.*|" ]
}
```

**NVMe-oF (Remote NVMe) — только локальные устройства:**
```ini
devices {
    global_filter = [ "a|/dev/nvme[0-9]n[0-9]+|", "r|.*|" ]
}
```

**Mixed: Multipath + локальные SSD:**
```ini
devices {
    global_filter = [
        "a|/dev/mapper/mpath.*|",
        "a|/dev/nvme[0-9]n[0-9]+|",
        "r|.*|"
    ]
}
```

#### Тестирование фильтров

Перед применением фильтра необходимо проверить, какие устройства будут распознаны LVM:

```bash
# Просмотр всех устройств, которые LVM видит с текущими фильтрами
sudo pvs

# Просмотр с детализацией (включая отклонённые)
sudo pvscan --listunsupported

# Тестирование конкретного выражения
sudo ls /dev/mapper/ | grep -E "mpath.*"

# Проверка после изменения фильтра
sudo vgscan -vvv    # verbose mode — покажет все устройства и фильтры
```

**Важно:** После изменения фильтров необходимо:
1. Перезапустить `systemd-udevd` (или `udevadm trigger`)
2. Выполнить `sudo vgscan`
3. Проверить доступность всех VG: `sudo vgs`

### LVM RAID и отказоустойчивость

В отличие от классического MDADM, LVM RAID позволяет создавать избыточные тома внутри VG, используя свободное пространство PV. LVM RAID реализован через target `dm-raid` (device-mapper), который взаимодействует с RAID-личностями MD (multiple devices) ядра — задействованы обе подсистемы ядра: device-mapper и MD. Управление осуществляется исключительно через LVM (`lvcreate`/`lvconvert`/`lvchange`), `mdadm` не требуется. mdadm и LVM RAID можно комбинировать: mdadm-массив может использоваться как PV для VG, а LVM-тома — объединяться в mdadm-массив.

#### Уровни RAID

| Уровень | Мин. PV | Отказоустойчивость | Write Performance | Read Performance | Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **raid0** | 2 | Нет | 2x (stripe) | 2x (stripe) | Временные данные, кэш |
| **raid1** | 2 | 1 диск | 1x | 2x (чтение с обоих) | Критичные данные, boot |
| **raid4** | 3 | 1 диск | N-1 (parity) | N (чтение) | Редко используется |
| **raid5** | 3 | 1 диск | N-1 (distributed parity) | N (чтение) | Общие данные, файловые сервера |
| **raid6** | 5 | 2 диска | N-2 (двойная parity) | N (чтение) | Крупные массивы, архивы |
| **raid10** | 4 | N/2 дисков | N/2 (mirror) | N (чтение) | Базы данных, высокая нагрузка |

*Где N — количество дисков в массиве.*

#### Параметры создания RAID-томов

Все RAID-уровни создаются командой `lvcreate` с указанием типа через `--type`:

```bash
sudo lvcreate --type raidN -n <имя_тома> -L <размер> \
    [-i <stripes>] [-m <mirrors>] [-I <stripe_size>] <VG> [PV ...]
```

Если список PV не указан, LVM автоматически подбирает нужное количество устройств из доступных PV указанной VG. Тип тома удобно проверять командой `lvs -o name,segtype` (segtype — это и есть уровень RAID).

**Параметры:**

| Параметр | Значение | Уровни |
| :--- | :--- | :--- |
| `-i`, `--stripes <Number>` | Количество stripe-устройств (устройств данных) | raid0/4/5/6/10 |
| `-m`, `--mirrors <Number>` | Число дополнительных копий; всего копий = `-m` + 1 | raid1, raid10 |
| `-I`, `--stripesize <Size>` | Размер stripe в КБ — объём данных, записываемых на одно устройство перед переходом к следующему | raid0/4/5/6/10 |

Параметры строго привязаны к уровню: raid1 не принимает `-i` и `-I`; raid4/5/6 не принимают `-m`; raid10 принимает `-m` только со значением 1 (только двухкопийное зеркало, `RAID10 currently supports only 2-way mirroring`).

**Значения по умолчанию:**
- `--stripes`: 2 для raid0/4/5/10, 3 для raid6 (минимально допустимое значение)
- `--mirrors`: 1 для raid1/raid10 (итого 2 копии данных)
- `--stripesize`: 64 КБ; допустимый диапазон 4 КБ–512 КБ, обязательно степень двойки

**Число устройств** (параметр `-i` задаёт устройства данных, parity-устройства добавляются сверху):
- raid0: всего = `-i` (минимум 2)
- raid1: всего = `-m` + 1 (минимум 2)
- raid4/5: всего = `-i` + 1 (диск чётности); `-i` ≥ 2
- raid6: всего = `-i` + 2 (два диска чётности); `-i` ≥ 3
- raid10: всего = `-i` × (`-m` + 1); `-i` ≥ 2, `-m` = 1

**Максимальное число устройств** (`DEFAULT_RAID_MAX_IMAGES = 64` в исходниках lvm2):
- raid0: до 64 stripes
- raid4/5: до 63 stripes (64 − 1 parity)
- raid6: до 62 stripes (64 − 2 parity)
- raid10: до 32 stripes (64 / 2, две копии данных)
- raid1: до 64 образов (`DEFAULT_RAID1_MAX_IMAGES`)

**Примеры:**

```bash
# RAID0 из 2 устройств (stripe)
sudo lvcreate --type raid0 -n lvr0 -L 10G -i 2 vg_data

# RAID1, 2 копии данных (-m 1 → original + 1 mirror)
sudo lvcreate --type raid1 -n lvr1 -L 2G -m 1 vg_data

# RAID5: 3 устройства данных + 1 чётность = 4 устройства, stripe 64 КБ (по умолчанию)
sudo lvcreate --type raid5 -n lvr5 -L 3G -i 3 vg_data

# RAID10: 2 stripe-группы × 2 копии = 4 устройства
sudo lvcreate --type raid10 -n lvr10 -L 4G -i 2 -m 1 vg_data
```

**Примечание по RAID10.** Число устройств: `всего = stripes × (mirrors + 1)`. Например, `-i 2 -m 1` даёт 2 × 2 = 4 устройства (две stripe-группы, каждая зеркалирована). Внутренне lvm2 удваивает значение stripes и затем делит на число копий (`stripes *= 2` в `_read_raid_params`, `stripes /= mirrors` в `_check_raid_parameters`), поэтому итоговое число stripe-групп совпадает с `-i`. Проза в `lvmraid(7)` («total number of devices = stripes», «devices per mirror = stripes/(mirrors+1)») противоречит приведённому там же примеру (`--stripes 2 --mirrors 1` → 4 rimage) и исходному коду — это ошибка документации. RAID10 — не «зеркало поверх stripe» (это RAID01, менее устойчивый к отказам), а stripe поверх зеркал: данные доступны, пока в каждой зеркальной паре живёт хотя бы одно устройство.

#### Мониторинг RAID

```bash
# Проверка состояния синхронизации
sudo lvs -o name,copy_percent,devices my_vg
# → lv_protected  100.00  lv_protected_rimage_0(0),lv_protected_rimage_1(0)

# Проверка деградации
sudo lvs -a -o name,attr,copy_percent my_vg
# → [lv_raid_rimage_0]  Unknown device    — сбойный диск

# Статус scrubbing (проверка целостности) и прогресс
sudo lvs -a -o name,raid_sync_action,sync_percent
# → lvr5  idle  100.00

# Число несогласованных блоков после scrub check
sudo lvs -o name,raid_mismatch_count
# → lvr5  0

# Мониторинг через dmeventd
sudo lvchange -my y /dev/vg_data/lv_raid
systemctl status dmeventd
```

**Деградация и восстановление:**
- Если диск в RAID1/5/6 вышел из строя, массив работает в degraded mode.
- При замене диска `lvconvert --repair` запускает rebuild на новый диск.
- Во время rebuild производительность снижается (особенно на RAID5/6).
- RAID10: rebuild одного зеркала не влияет на другие пары.

#### RAID и Thin Provisioning

LVM позволяет комбинировать RAID с Thin Pool:

```bash
# Создание Thin Pool на RAID1 (данные + метаданные)
sudo lvcreate --type raid1 -L 100G -n thin_pool_data vg_data
sudo lvcreate --type raid1 -L 10G -n thin_pool_meta vg_data
sudo lvconvert --thinpool vg_data/thin_pool --poolmetadata vg_data/thin_pool_meta

# Thin LV внутри RAID-backed Thin Pool
sudo lvcreate -V 500G -T vg_data/thin_pool -n thin_lv
```

*Примечание:* RAID1 для метаданных Thin Pool критичен — потеря метаданных = потеря всех данных в Thin Pool.

### Ускорение через LVM Cache

LVM позволяет объединить быстрый LV (кэш) и медленный LV (данные), создавая прозрачный кэширующий слой на уровне device-mapper.

#### Архитектура dm-cache

```
┌─────────────────────────────────────────┐
│              User I/O                    │
├─────────────────────────────────────────┤
│           dm-cache (target)              │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ Cache Block  │  │   Cache Policy   │  │
│  │   Table      │  │   (smq / mq)     │  │
│  └──────┬──────┘  └────────┬─────────┘  │
├─────────┼──────────────────┼────────────┤
│   Cache Data LV            │ Cache Meta LV
│   (NVMe/SSD)               │ (NVMe/SSD)
└────────────────────────────┘
         │
┌────────┴────────┐
│  Origin LV      │
│  (HDD / slower) │
└─────────────────┘
```

**Cache Pool** состоит из двух компонентов:
- **Cache Data:** хранит сами кэшированные блоки
- **Cache Metadata:** индекс (таблица соответствия block ID → cache block)

**Cache Policy (Политика кэширования):**
- `smq` (Stochastic Multi-Queue) — modern policy, автоматический выбор hot-блоков
- `mq` (Multi-Queue) — legacy policy, используется по умолчанию в старых системах
- `random` — тестовая политика, выбирает блоки случайно

#### Режимы работы

| Режим | Write Behavior | Read Behavior | Безопасность | Производительность |
| :--- | :--- | :--- | :--- | :--- |
| **writethrough** | Сразу в кэш + на диск | Из кэша (cache hit) | Высокая | Только чтение |
| **writeback** | Сначала в кэш, потом на диск (flush) | Из кэша (cache hit) | Средняя (риск при отказе SSD) | Чтение + запись |

*Рекомендация:* Используйте `writethrough` для критичных данных. `writeback` допустим только если кэш-устройство защищено (RAID1) или данные восстанавливаемы.

#### Создание LVM Cache (полный workflow)

```bash
# 1. Создание PV на быстром устройстве
sudo pvcreate /dev/nvme0n1p1
sudo vgextend vg_data /dev/nvme0n1p1

# 2. Создание Cache Pool (данные + метаданные)
# Размер метаданных: ~1 байт на каждый блок данных
# Для 100 GiB данных: ~100 MiB метаданных
sudo lvcreate -n cache_pool_data -L 50G vg_data /dev/nvme0n1p1
sudo lvcreate -n cache_pool_meta -L 1G vg_data /dev/nvme0n1p1
sudo lvconvert --type cache-pool --poolmetadata vg_data/cache_pool_meta vg_data/cache_pool_data

# 3. Привязка кэша к основному LV (writethrough)
sudo lvconvert --type cache --cachemode writethrough --cachepool vg_data/cache_pool vg_data/lv_data

# 4. Или с writeback (только для безопасных данных!)
sudo lvconvert --type cache --cachemode writeback --cachepool vg_data/cache_pool vg_data/lv_data

# 5. Проверка
sudo lvs -o name,cache_mode,cache_policy,cache_read_hits,cache_write_hits vg_data
```

#### Мониторинг и управление кэшем

```bash
# Статистика попаданий в кэш
sudo lvs -o name,cache_read_hits,cache_read_misses,cache_write_hits,cache_write_misses vg_data
# → lv_data  85432  1234  45231  876

# Отключение кэша (без удаления)
sudo lvconvert --cachemode off vg_data/lv_data

# Удаление кэша (данные остаются на origin LV)
sudo lvconvert --splitcache vg_data/lv_data

# Добавление второго SSD в кэш (кэширование с нескольких устройств)
sudo lvconvert --type cache --cachepool vg_data/cache_pool2 vg_data/lv_data
```

#### LVM Cache и Thin Provisioning

Thin Pool можно кэшировать аналогично обычному LV:

```bash
# Кэширование Thin Pool
sudo lvconvert --type cache --cachepool vg_data/cache_pool vg_data/thin_pool
```

*Важно:* Кэширование Thin Pool ускоряет все LV внутри него. Однако metadata Thin Pool не кэшируется — для этого нужен отдельный cache pool.

#### Альтернативы: dm-writecache

Для случайной записи (database workloads) dm-writecache может быть эффективнее dm-cache:

```bash
# dm-writecache — simpler, без metadata overhead
sudo lvconvert --type writecache --cachesettings 'writeback_cache=yes' \
    --cachepool vg_data/cache_pool vg_data/lv_data
```

### Диагностика и целостность метаданных (MDA)

Метаданные VG — критически важная структура, описывающая всю топологию LVM. Их повреждение приводит к полной потере доступа к LV.

#### Архитектура MDA

```
Physical Volume (PV)
├── LVM Label (512 bytes)        — идентификатор PV
├── Header Area (1 MiB default)  — MDA#1 (текстовые метаданные VG)
├── Data Area                    — полезные данные LV
└── Могут быть additional MDA    — до 255 MDA на PV
```

**Формат метаданных:**
- Текстовый формат ( Human-readable ), хранящий полную структуру VG
- Создаётся **до** выполнения каждой операции, изменяющей структуру
- Автоматически реплицируется на все PV в VG

#### Резервное копирование метаданных

```bash
# Бэкап текущих метаданных
sudo vgcfgbackup vg_data
# → Volume group "vg_data" successfully backed up.

# Просмотр локации бэкапов
ls -la /etc/lvm/backup/
# → vg_data

# Бэкап всех VG
for vg in $(sudo vgs --noheadings -o vg_name); do
    sudo vgcfgbackup $vg
done
```

**Автоматический бэкап:**
LVM автоматически создаёт бэкап в `/etc/lvm/backup/` перед каждой операцией, изменяющей структуру VG. Архивы хранятся в `/etc/lvm/archive/`.

```bash
# Просмотр истории архивов
sudo vgcfgrestore --list vg_data
# → File: /etc/lvm/archive/vg_data_00001-12345.vg
# → Description: Created before executing 'lvcreate -n lv_test vg_data'
# → 
# → File: /etc/lvm/backup/vg_data
# → Description: Created automatically after converting VG
```

#### Восстановление метаданных

**Восстановление из backup (последнее состояние):**
```bash
# Просмотр текущего состояния
sudo vgcfgrestore --list vg_data

# Восстановление из последнего backup
sudo vgcfgrestore vg_data

# Активация LV
sudo vgchange -ay vg_data
```

**Восстановление из archive (откат к прошлому состоянию):**
```bash
# Найти нужный архив (до удаления/изменения)
sudo vgcfgrestore --list vg_data | grep -B5 "удаленный LV"

# Тестовое восстановление
sudo vgcfgrestore --test -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data

# Фактическое восстановление
sudo vgcfgrestore -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data
sudo vgchange -ay vg_data
```

**Восстановление с помощью pvck:**
```bash
# Проверка целостности MDA на PV
sudo pvck /dev/sdb1
# → PV /dev/sdb1 not found with label lvm2

# Если повреждена метка (Label), восстановление из backup
sudo pvcreate --uuid "XYZ-123-abc-..." --restorefile /etc/lvm/backup/vg_data /dev/sdb1

# Проверка MDA
sudo pvck --dump /dev/sdb1
# → Couldn't find device with uuid XYZ-123-abc-...
```

#### Автоматический мониторинг метаданных

```bash
# Включение vgck при загрузке
# Добавить в /etc/lvm/lvm.conf:
activation {
    monitoring = 1
}

# Ручная проверка всех VG
sudo vgck

# Проверка через systemd (если поддерживается)
sudo systemctl status lvm2-pvscan@*.service
```

#### Защита от случайного удаления VG

```bash
# Включение красивого изменения размера (для безопасного уменьшения)
sudo vgchange -x y vg_data    # Resizeable = yes

# Включение ratios для безопасного удаления
sudo vgchange -x n vg_data    # Resizeable = no (защита от vgreduce/remove)
```

### Взаимодействие LVM с mdadm

На серверах с аппаратным RAID лучше использовать LVM поверх mdadm, а не LVM RAID.

**Схема:**
```
/dev/sda1 ─┐
/dev/sda2 ─┼─ md0 (mdadm RAID1)
/dev/sdb1 ─┤
/dev/sdb2 ─┘
    │
    └─ LVM PV → VG → LV
```

**Преимущества:**
- LVM видит один «диск» (md device), упрощая управление
- Восстановление RAID на уровне mdadm независимо от LVM
- Кэширование работает на уровне LVM (поверх md)

**Создание LVM поверх mdadm:**
```bash
# 1. Создание RAID через mdadm
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/sda1 /dev/sdb1

# 2. Создание PV на RAID-устройстве
sudo pvcreate /dev/md0

# 3. Создание VG
sudo vgcreate vg_data /dev/md0

# 4. Создание LV
sudo lvcreate -L 100G -n lv_data vg_data
```

### LVM и cgroups (Resource Control)

LVM LV можно интегрировать с control groups для ограничения I/O.

```bash
# Ограничение I/O для LV через blkio cgroup
# Ограничение: 10 MB/s чтение, 5 MB/s запись
echo "253:0 10000000" > /sys/fs/cgroup/blkio/blkio.throttle.read_bps_device
echo "253:0 5000000" > /sys/fs/cgroup/blkio/blkio.throttle.write_bps_device

# Где 253:0 — major:minor LV
cat /sys/block/dm-0/dev
# → 253:0
```

**systemd integration:**
```bash
# Ограничение I/O через systemd (для сервиса)
# /etc/systemd/system/myapp.service
[Service]
IOReadBandwidthMax=/dev/vg_data/lv_data 10M
IOWriteBandwidthMax=/dev/vg_data/lv_data 5M
IOWeight=100
```

#### Выравнивание (Alignment)

LVM автоматически выравнивает данные по границам экстентов (PE size, по умолчанию 4 MiB). Однако неправильное выравнивание на уровне диска может привести к существенной потере производительности.

**Проблема:** Если начало PV не соответствует физическому сектору диска, каждая операция чтения/записи затрагивает два физических сектора вместо одного.

**Диагностика:**
```bash
# Проверка физического размера сектора
sudo blockdev --getpbsz /dev/sdb
# → 512    # 512 bytes — traditional

# Для 4K-дисков:
sudo hdparm -I /dev/sdb | grep Logical
# →   Logical/physical sector size: 512 bytes / 4096 bytes

# Проверка текущего выравнивания
sudo pvs -o pv_name,pe_start
# → PV        1.00m    # 1 MiB — правильно для 4K-дисков
```

**Установка правильного выравнивания:**
```bash
# При создании PV — выравнивание по 1 MiB (рекомендуется для SSD/NVMe)
sudo pvcreate --dataalignment 1m /dev/sdb1

# Для аппаратных RAID — выравнивание по stripe size
sudo pvcreate --dataalignment 128k /dev/sdb1

# Проверка
sudo pvs -o pv_name,pe_start,pe_size /dev/sdb1
```

**Рекомендации:**
| Тип устройства | Рекомендуемое выравнивание | Примечание |
| :--- | :--- | :--- |
| SSD/SATA | 1 MiB | Стандарт для большинства SSD |
| NVMe | 1 MiB | Совпадает с blockSize |
| Hardware RAID | Stripe size массива | Проверьте в контроллере |
| Software RAID (mdadm) | Chunk size | Автоматически |
| Hyper-V / VMware | 1 MiB | Виртуальные диски |

#### Read-Ahead (Предсчитывание)

Read-ahead определяет, сколько блоков ядро предварительно считывает при последовательном чтении. Повышает производительность для sequential workloads, но снижает для random I/O.

```bash
# Текущее значение (в KiB)
sudo blockdev --getra /dev/sdb
# → 256    # 256 KiB — default

# Установка для конкретного LV
sudo lvchange -r 4096 /dev/vg_data/lv_data    # 4 MiB read-ahead

# Установка для PV (на всех LV через этот PV)
sudo blockdev --setra 4096 /dev/sdb

# Проверка
sudo blockdev --getra /dev/sdb
```

**Рекомендации по read-ahead:**
| Workload | Read-Ahead | Примечание |
| :--- | :--- | :--- |
| Default | 256 KiB | Хорош для смешанных нагрузок |
| Sequential (видео, архивы) | 2–8 MiB | Максимальная пропускная способность |
| Random I/O (БД, VM) | 128–256 KiB | Минимум предсказуемых чтений |
| Виртуальные машины | 128 KiB | Random I/O преобладает |

#### Stripe (Чередование)

Stripeing распределяет данные по нескольким PV для увеличения пропускной способности.

```bash
# Создание striped LV (аналог RAID0)
sudo lvcreate -L 100G -i 3 -I 256k -n lv_striped vg_data
# -i 3      — количество PV для чередования
# -I 256k   — размер полосы (stripe size)

# Проверка
sudo lvs -o name,stripes,stripe_size
# → lv_striped  3  256.00k
```

**Важно:** Stripeing не обеспечивает отказоустойчивость. Для этого используйте RAID10.

## Практические сценарии

### Сценарий 1: Настройка фильтров устройств

Предотвращение сканирования локальных дисков при использовании Multipath.

**Редактирование `/etc/lvm/lvm.conf`:**
```ini
devices {
    # Игнорировать сырые пути дисков, использовать только пути Multipath (mpath)
    global_filter = [ "a|/dev/mapper/mpath.*|", "r|.*|" ]
}
```

**После изменения фильтра:**
```bash
# Перезапуск udev
sudo udevadm trigger
sudo udevadm settle

# Обновление кэша
sudo vgscan

# Проверка
sudo vgs
# → VG       #PV #LV #SN Attr   VSize   VFree
# → vg_data    2   3   0 wz--n- 500.00g 100.00g
```

**Отладка (если VG не видно):**
```bash
# Просмотр всех устройств (включая отклонённые фильтром)
sudo vgscan -vvv 2>&1 | grep -i "filter"

# Проверка, что mpath-устройства существуют
ls -la /dev/mapper/mpath*
```

### Сценарий 2: Восстановление загрузки (Rebuild initramfs)

Если система не находит VG при загрузке (ошибка `Volume group not found`).

#### Для Debian / Ubuntu
```bash
# Добавление модуля (если он не включен автоматически)
echo "lvm2" | sudo tee -a /etc/initramfs-tools/modules

# Обновление образа для текущего ядра
sudo update-initramfs -u

# Проверка
lsinitramfs /boot/initrd.img-$(uname -r) | grep lvm
```

#### Для RHEL / Rocky / Fedora (dracut)
```bash
# Принудительное включение модуля
sudo dracut --force --add lvm --regenerate-all

# Проверка
lsinitrd /boot/initramfs-$(uname -r) | grep lvm
```

**Восстановление через emergency shell:**
```bash
# Если VG виден
sudo vgchange -ay vg_system
sudo mount /dev/vg_system/lv_root /root
sudo chroot /root
sudo update-initramfs -u    # Debian/Ubuntu
sudo dracut --force --add lvm --regenerate-all    # RHEL/Fedora
```

### Сценарий 3: Создание отказоустойчивого тома (LVM RAID)

Создание томов с защитой от отказа дисков.

**Пример 1: RAID 10 (Зеркалирование + Чередование)**
```bash
# Требует минимум 4 PV. -i 2 (2 полосы чередования), каждое зеркалируется.
sudo lvcreate --type raid10 -L 100G -i 2 -n lv_mirrored my_vg

# Проверка
sudo lvs -o name,attr,copy_percent,stripes my_vg
# → lv_mirrored  rwi---r--  100.00  4
```

**Пример 2: RAID 5 (distributed parity)**
```bash
# Требует минимум 3 PV. Выдерживает отказ одного диска.
sudo lvcreate --type raid5 -L 200G -n lv_protected my_vg

# Проверка
sudo lvs -o name,attr,copy_percent my_vg
# → lv_protected  rwi---r--  100.00
```

**Пример 3: RAID 6 (двойная избыточность)**
```bash
# Требует минимум 4 PV. Выдерживает отказ двух дисков.
sudo lvcreate --type raid6 -L 300G -n lv_critical my_vg
```

**Мониторинг состояния:**
```bash
# Проверка синхронизации
sudo lvs -o name,copy_percent,devices my_vg

# Проверка деградации
sudo lvs -a -o name,attr my_vg
# → [lv_rimage_0]  Unknown device    — сбойный диск
```

### Сценарий 4: Настройка SSD-кэша для медленного HDD

Задача: ускорить работу тома `lv_data` с помощью NVMe-диска `/dev/nvme0n1p1`.

```bash
# 1. Создание PV на NVMe и добавление в VG
sudo pvcreate /dev/nvme0n1p1
sudo vgextend vg_data /dev/nvme0n1p1

# 2. Создание Cache Pool (данные + метаданные) на NVMe
sudo lvcreate -n cache_pool_data -L 50G vg_data /dev/nvme0n1p1
sudo lvcreate -n cache_pool_meta -L 1G vg_data /dev/nvme0n1p1
sudo lvconvert --type cache-pool --poolmetadata vg_data/cache_pool_meta vg_data/cache_pool_data

# 3. Привязка кэша к основному LV (writethrough)
sudo lvconvert --type cache --cachemode writethrough --cachepool vg_data/cache_pool vg_data/lv_data

# 4. Проверка
sudo lvs -o name,cache_mode,cache_policy,cache_read_hits vg_data
```

### Сценарий 5: Диагностика целостности метаданных

```bash
# Проверка физического тома на ошибки метаданных (MDA)
sudo pvck /dev/sdb1

# Проверка консистентности всей группы томов
sudo vgck my_vg

# Просмотр истории изменений метаданных
sudo vgcfgrestore --list my_vg

# Бэкап текущих метаданных
sudo vgcfgbackup my_vg
```

### Сценарий 6: Recovery через Live CD (полное восстановление)

При полном отказе системы и необходимости восстановления через Live CD.

```bash
# 1. Загрузка с Live CD и активация LVM
sudo vgchange -ay vg_data

# 2. Просмотр структуры
sudo lvs
sudo vgs

# 3. Если VG не виден — восстановление из backup
sudo vgcfgrestore vg_data

# 4. Если PV повреждён — восстановление UUID
sudo pvcreate --uuid "XYZ-123-abc-..." --restorefile /etc/lvm/backup/vg_data /dev/sdb1

# 5. Монтирование и копирование данных
sudo mount /dev/vg_data/lv_data /mnt/recovery
sudo tar czf /external/backup.tar.gz -C /mnt/recovery .
```

### Сценарий 7: Оптимизация I/O для виртуальных машин

Настройка LVM для виртуальных машин с высоким random I/O.

```bash
# 1. Создание LV с оптимальными параметрами для VM
sudo lvcreate -L 200G -i 4 -I 128k --stripesize 128k -n lv_vm vg_data

# 2. Установка read-ahead
sudo lvchange -r 128k /dev/vg_data/lv_vm

# 3. Форматирование с оптимальными параметрами
sudo mkfs.xfs -f -d su=128k,sw=4 /dev/vg_data/lv_vm

# 4. Монтирование с оптимальными опциями
sudo mount -o noatime,nodiratime,discard /dev/vg_data/lv_vm /mnt/vm
```

### Сценарий 8: Переключение между writethrough и writeback

Динамическое изменение режима кэширования без остановки сервисов.

```bash
# Текущий режим
sudo lvs -o name,cache_mode vg_data
# → lv_data  writethrough

# Переключение на writeback (только для безопасных данных!)
sudo lvconvert --cachemode writeback vg_data/lv_data

# Проверка
sudo lvs -o name,cache_mode vg_data
# → lv_data  writeback

# Возврат на writethrough
sudo lvconvert --cachemode writethrough vg_data/lv_data
```

### Сценарий 9: Взаимодействие LVM с Thin Provisioning

Тонкое провизионирование позволяет создавать LV большего размера, чем доступное физическое пространство.

**Преимущества Thin Pool:**
- Динамическое выделение пространства
- Снимки без дублирования данных (thin snapshots)
- Тонкое провизионирование для VM и контейнеров

**Создание Thin Pool:**
```bash
# 1. Создание Thin Pool (данные + метаданные)
sudo lvcreate -L 100G -T vg_data/thin_pool
# Или с явным указанием метаданных:
sudo lvcreate -L 100G -T vg_data/thin_pool --poolmetadata vg_data/thin_pool_meta

# 2. Создание тонкого LV
sudo lvcreate -V 500G -T vg_data/thin_pool -n thin_lv
# LV выглядит как 500 GiB, но физически потребляет только записанные блоки

# 3. Проверка использования
sudo lvs -o name,thin_data_percent,thin_metadata_percent vg_data
# → thin_pool   45.23  1.23
```

**Мониторинг Thin Pool:**
```bash
# Использование данных и метаданных
sudo lvs -o name,data_percent,metadata_percent vg_data/thin_pool
# → thin_pool  45.23  1.23

# Автоматическое расширение (через dmeventd)
sudo systemctl enable --now dmeventd

# Настройка в lvm.conf
# activation {
#     thin_pool_autoextend_threshold = 80
#     thin_pool_autoextend_percent = 20
# }
```

### Сценарий 10: Взаимодействие LVM с NVMe-oF (Remote NVMe)

Для серверов, подключённых к NVMe-oF хранилищам.

**Подключение NVMe-oF устройства:**
```bash
# 1. Обнаружение удалённого NVMe-хоста
sudo nvme discover -t tcp -a 192.168.1.100 -s 4420

# 2. Подключение
sudo nvme connect -t tcp -a 192.168.1.100 -s 4420 -n nqn.2024-01.com.example:storage

# 3. Проверка
ls /dev/nvme*
# → /dev/nvme0n1  — локальный
# → /dev/nvme1n1  — удалённый (NVMe-oF)

# 4. Создание PV и LV
sudo pvcreate /dev/nvme1n1
sudo vgextend vg_data /dev/nvme1n1
sudo lvcreate -L 200G -n lv_remote vg_data
```

**Фильтрация NVMe-oF устройств:**
```ini
# /etc/lvm/lvm.conf
devices {
    # Игнорировать удалённые NVMe (если не нужны)
    global_filter = [
        "a|/dev/nvme[0-9]n[0-9]+|",
        "r|.*|"
    ]
}
```

### Сценарий 11: Diagnostics — определение bottle neck I/O

Определение узкого места в цепочке LVM → ФС → Приложение.

```bash
# 1. Проверка I/O через iostat
iostat -xz 1 5
# → Device   r/s   w/s  await  svctm  %util
# → sdb      5.00  150.00  45.23  6.50  97.50  # Высокий await + %util

# 2. Проверка I/O через LVM
sudo lvs -o name,io_mode,write_cache vg_data
# → lv_data  direct  [write_back]

# 3. Проверка кэша
sudo lvs -o name,cache_read_hits,cache_write_hits vg_data
# → lv_data  85432  45231   # cache_read_hits высокий = кэш работает

# 4. Проверка thin pool
sudo lvs -o name,data_percent,metadata_percent vg_data/thin_pool
# → thin_pool  45.23  1.23   # Низкий % = мало данных

# 5. Проверка через blktrace (углубленная диагностика)
sudo blktrace -d /dev/sdb -o - | blkparse -i -
```

**Типичные bottle neck и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| High await + low %util | Ожидание блокировки (lock contention) | Проверить приложение, уменьшить concurrent I/O |
| High %util + high await | Перегрузка диска | Добавить диски, распределить I/O |
| Low cache_hit_ratio | Маленький cache pool или random workload | Увеличить cache pool, сменить политику |
| thin_pool data_percent > 90% | Thin Pool заполняется | Расширить thin pool, добавить PV |

## Типичные ошибки и их решение

### `Volume group not found` при загрузке

**Причина:** initramfs не содержит LVM-модулей или VG не активируется автоматически.

**Решение:**
```bash
# 1. Проверка initramfs
lsinitramfs /boot/initrd.img-$(uname -r) | grep lvm
# Если пусто — модули отсутствуют

# 2. Пересборка initramfs (из Live CD или emergency shell)
sudo update-initramfs -u    # Debian/Ubuntu
sudo dracut --force --add lvm --regenerate-all    # RHEL/Fedora

# 3. Проверка
sudo vgchange -ay vg_system
sudo mount /dev/vg_system/lv_root /mnt
```

### `Can't activate logical volume` — LV заблокирован

**Причина:** LV уже активен в другом месте или используется процессом.

**Решение:**
```bash
# 1. Проверка активных LV
sudo lvs -a -o name,attr,devices vg_data
# → lv_data  -wi---  /dev/sdb1(0)

# 2. Принудительная деактивация
sudo lvchange -an /dev/vg_data/lv_data

# 3. Если деактивация не удается — проверить зависшие процессы
sudo lsof /dev/vg_data/lv_data
# Или
sudo fuser -vm /dev/vg_data/lv_data

# 4. Завершить процессы и повторить
sudo kill -9 <PID>
sudo lvchange -an /dev/vg_data/lv_data
```

### `insufficient suitable allocatable extents`

**Причина:** Недостаточно свободных экстентов в VG для создания LV.

**Решение:**
```bash
# 1. Проверка свободного места
sudo vgs
# → VG       #PV #LV #SN Attr   VSize   VFree
# → vg_data    2   5   0 wz--n- 500.00g 10.00g

# 2. Расширение VG (добавление нового PV)
sudo pvcreate /dev/sdc1
sudo vgextend vg_data /dev/sdc1

# 3. Или удаление неиспользуемых LV
sudo lvremove /dev/vg_data/lv_old
```

### Cache Pool не привязывается к LV

**Причина:** Размер Cache Pool превышает размер LV или несовместимый тип.

**Решение:**
```bash
# 1. Проверка размеров
sudo lvs -o name,lv_size vg_data
# → lv_data       100.00g
# → cache_pool    200.00g    # ВНИМАНИЕ: cache_pool > lv_data!

# Cache Pool должен быть <= размера LV
# 2. Удаление и пересоздание с правильным размером
sudo lvconvert --splitcache vg_data/lv_data
sudo lvremove /dev/vg_data/cache_pool
sudo lvcreate -n cache_pool -L 50G vg_data    # 50% от lv_data
sudo lvconvert --type cache --cachepool vg_data/cache_pool vg_data/lv_data
```

### Thin Pool переполнен — все LV become read-only

**Причина:** Thin pool исчерпал физическое пространство.

**Решение:**
```bash
# 1. Проверка статуса пула
sudo lvs -o lv_name,attr,data_percent,metadata_percent vg_data/thin_pool

# 2. Расширить thin pool data
sudo lvextend -L +10G /dev/vg_data/thin_pool

# 3. Расширить thin pool metadata (если нужно)
sudo lvextend -L +1G /dev/vg_data/thin_pool_tmeta

# 4. Принудительно сделать LV доступным для записи
sudo lvchange -ay /dev/vg_data/thin_pool
```

### `metadata too large` при создании Thin Pool

**Причина:** Размер метаданных insufficient для указанного размера Thin Pool.

**Решение:**
```bash
# 1. Расчёт минимального размера метаданных
# Формула: metadata_size = (pool_size / metadata_block_size) * sizeof(metadata_block)
# Для 1 TiB pool с 64KiB блоками: (1024*1024 MiB / 64 KiB) * 4 bytes ≈ 2 GiB

# 2. Явное создание metadata LV
sudo lvcreate -L 2G -n thin_pool_meta vg_data
sudo lvconvert --type thin-pool --poolmetadata vg_data/thin_pool_meta vg_data/thin_pool_data
```

## Best Practices

### Общие

1. **Резервное копирование метаданных:** Регулярно делайте `vgcfgbackup` всех VG. Храните копии вне сервера.
2. **Именование:** Используйте осмысленные имена: `lv_data_web`, `lv_logs_app`. Не используйте `lv1`, `lv2`.
3. **Документирование:** Ведите схему раскладки PV/VG/LV для каждого сервера.
4. **Мониторинг:** Настройте алертинг на free extents < 10%, cache hit ratio < 80%, thin pool > 80%.
5. **Тестирование:** Все операции сначала на тестовом стенде, затем на production.

### RAID

6. **Scrubbing:** Регулярно запускайте `lvchange --syncaction check` для RAID5/6 — полное сканирование, выявляющее несогласованные области, пропущенные частичной синхронизацией (режим `repair` — с исправлением).
7. **Восстановление:** Не откладывайте rebuild — чем дольше массив degraded, тем выше риск второго отказа.
8. **Размер rebuild:** На больших массивах rebuild занимает часы. Планируйте в нерабочее время.
9. **Мониторинг:** Настройте оповещения о degraded state через `dmeventd` или mdadm.

### Cache

10. **Размер Cache Pool:** 5–20% от размера LV. Для random workload — больше, для sequential — меньше.
11. **Режим:** `writethrough` для критичных данных, `writeback` только с RAID1 backing.
12. **Мониторинг:** Отслеживайте `cache_read_hits` — если < 50%, кэш неэффективен.
13. **Отключение:** Используйте `--splitcache` для безопасного отключения.

### Thin Provisioning

14. **Автоматическое расширение:** Включите `dmeventd` и настройте пороги в `lvm.conf`.
15. **Overcommit:** Не превышайте 200% overcommit ratio для данных, критичных к целостности.
16. **Snapshots:** Thin-снимки рекурсивны, но добавляют нагрузку на metadata. Мониторьте `thin_metadata_percent`.
17. **Metadata:** Выделяйте достаточно места для metadata (1–5% от pool size, в зависимости от block size).

## Ограничения и особые случаи

- **LVM RAID не заменяет hardware RAID:** Для критичных данных используйте hardware RAID + LVM поверх.
- **Cache-пул не является заменой SSD для swap:** Для swap лучше использовать отдельный LV на SSD без кэширования.
- **Thin Pool metadata важна:** Потеря metadata = потеря всех данных в Thin Pool. Всегда дублируйте metadata LV.
- **Initramfs с LUKS:** При использовании шифрования (LUKS+LVM) необходимы дополнительные модули в initramfs.
- **NVMe-oF и Multipath:** Используйте `global_filter` для исключения дублирующих путей.
- **Stripeing без избыточности:** При отказе одного PV теряются все данные striped LV. Для отказоустойчивости используйте RAID.
- **RAID и thin:** Thin Pool на RAID5 может иметь significantly reduced performance из-за parity overhead.
- **Writethrough vs Writeback:** Writeback без RAID1 backing = риск потери данных при отказе кэш-устройства.
- **readahead и random I/O:** Увеличение readahead для random workload снижает производительность.
- **alignment и legacy:** Старые диски (512e) могут иметь проблемы с выравниванием. Всегда проверяйте `blockdev --getpbsz`.

### См. также
- **[LVM — Практические сценарии восстановления](./practical_scenarios.md)** — восстановление PV по UUID и отмена удаления LV.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — работа с Thin Pool.
- **[LVM — Снимки (Snapshots)](../snapshots.md)** — создание и слияние снимков.
