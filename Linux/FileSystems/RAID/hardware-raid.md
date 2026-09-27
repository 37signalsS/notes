# Аппаратные RAID-контроллеры

## Определения

**Аппаратный RAID-контроллер (Hardware RAID Controller)** — специализированная плата (HBA с RAID-функционалом), управляющая дисковым массивом независимо от операционной системы. Содержит собственный процессор, RAM и опционально BBU/Flash для защиты кэша.

**HBA (Host Bus Adapter)** — адаптер шины хоста, обеспечивающий подключение накопителей к системе. В контексте RAID: HBA с поддержкой аппаратного RAID (MegaRAID, Smart Array) или чистый HBA (для программного RAID/ZFS).

**BBU (Battery Backup Unit) / CacheVault** — аппаратная батарейка или суперконденсатор на RAID-контроллере, обеспечивающий сохранность данных в кэше контроллера при отключении питания.

**Write-Back vs Write-Through** — режимы кэширования. Write-Back подтверждает запись после попадания данных в кэш (быстрее, требует BBU). Write-Through подтверждает только после физической записи на диск (медленнее, безопаснее).

**Patrol Read** — фоновый процесс контроллера, проверяющий все диски массива на наличие ошибок чтения. Аналог scrubbing в программном RAID.

---

## Основные концепции

### Сравнение аппаратного и программного RAID

| Критерий | Аппаратный (HBA/RAID) | Программный (mdadm) |
| :--- | :--- | :--- |
| **Стоимость** | Высокая ($200-$2000+) | Нулевая (встроен в ядро) |
| **Производительность** | Высокая (свой процессор + кэш) | Зависит от CPU (1-3% при нагрузке) |
| **Отказоустойчивость контроллера** | Потеря контроллера = потеря массива | Нет привязки (переносимость) |
| **Кэш** | Аппаратный (256 МБ - 32 ГБ) + BBU | Ядро ОС (page cache) |
| **Восстановление** | Только на совместимом контроллере | `mdadm --assemble` на любом Linux |
| **Vendor lock-in** | Да (MegaCLI, hpssacli) | Нет |
| **Управление** | Vendor CLI / Web GUI | CLI + sysfs |

### Когда использовать аппаратный RAID

| Сценарий | Рекомендация |
| :--- | :--- |
| OLTP БД, 100K+ IOPS | Аппаратный (write-back кэш + BBU) |
| Виртуализация (VMware, KVM) | Аппаратный или программный |
| Файловый сервер (средняя нагрузка) | Программный (mdadm) |
| NAS (ZFS/Btrfs) | Программный (HBA в IT-режиме) |
| Сервер начального уровня | Программный (mdadm) |

### Режимы работы контроллеров

| Режим | Описание | Использование |
| :--- | :--- | :--- |
| **RAID** | Контроллер управляет RAID-массивом | Стандартный режим |
| **IT (HBA)** | Контроллер работает как простой HBA | ZFS, программный RAID |
| **JBOD** | Каждый диск доступен отдельно | Программный RAID, ZFS |

---

## Практические сценарии

### LSI MegaRAID / Dell PERC (storcli)

#### Просмотр состояния

```bash
# Просмотр всех контроллеров
sudo storcli /c0 show all

# Просмотр физических дисков
sudo storcli /c0 /eall /sall show

# Просмотр логических массивов
sudo storcli /c0 /vall show all

# Просмотр BBU
sudo storcli /c0 /bbu show all

# Краткий статус
sudo storcli /c0 show | grep -E "RAID|State|Size"
```

#### Создание массива

```bash
# RAID 1 из 2 дисков
sudo storcli /c0 add raid=r1 drives=e25:s0,e25:s1

# RAID 5 из 4 дисков
sudo storcli /c0 add raid=r5 drives=e25:s0,e25:s1,e25:s2,e25:s3

# RAID 10 из 6 дисков
sudo storcli /c0 add raid=r10 drives=e25:s0,e25:s1,e25:s2,e25:s3,e25:s4,e25:s5

# RAID 6 из 8 дисков
sudo storcli /c0 add raid=r6 drives=e25:s0,e25:s1,e25:s2,e25:s3,e25:s4,e25:s5,e25:s6,e25:s7
```

#### Замена диска

```bash
# Пометить диск как failed
sudo storcli /c0 /e25 /s0 set failure

# Извлечь failed диск
sudo storcli /c0 /e25 /s0 hotsparedown
sudo storcli /c0 /e25 /s0 remove

# Установить новый диск и добавить в массив
sudo storcli /c0 /e25 /s0 add hotsparedrive
```

#### Управление кэшем и BBU

```bash
# Проверка статуса BBU
sudo storcli /c0 /bbu show all
# -> BatteryState: Charging / Discharged / OK

# Переключение в Write-Back (если BBU заряжена)
sudo storcli /c0 set wrcache=WB

# Переключение в Write-Through (если BBU разряжена)
sudo storcli /c0 set wrcache=WT

# Автоматическое управление (адаптивный режим)
sudo storcli /c0 set wrcache=ADWB
```

#### Patrol Read

```bash
# Запуск Patrol Read
sudo storcli /c0 set patrolread mode=on

# Просмотр прогресса
sudo storcli /c0 /patrol show

# Остановка Patrol Read
sudo storcli /c0 set patrolread mode=off
```

### HP Smart Array (ssacli)

```bash
# Просмотр контроллеров
sudo ssacli ctrl all show config

# Просмотр физических дисков
sudo ssacli ctrl slot=0 physicaldrive all show status

# Просмотр логических массивов
sudo ssacli ctrl slot=0 logicaldrive all show

# Создание RAID 1
sudo ssacli ctrl slot=0 create type=logicaldrive drives=1I:1:1,1I:1:2 raid=1

# Создание RAID 5
sudo ssacli ctrl slot=0 create type=logicaldrive drives=1I:1:1,1I:1:2,1I:1:3 raid=5

# Замена диска
sudo ssacli ctrl slot=0 physicaldrive 1I:1:1 modify rebuild
```

### MegaCLI (устаревший, но встречается)

```bash
# Просмотр физических дисков
sudo MegaCLI -PDList -aALL

# Просмотр логических массивов
sudo MegaCLI -LDInfo -Lall -aALL

# Просмотр BBU
sudo MegaCLI -AdpBbuCmd -aALL

# Создание RAID 1
sudo MegaCLI -CfgLdAdd -r1 [252:0, 252:1] -a0

# Создание RAID 5
sudo MegaCLI -CfgLdAdd -r5 [252:0, 252:1, 252:2, 252:3] -a0

# Замена диска
sudo MegaCLI -PDRbld -Start -PhysDrv[252:0] -a0
```

---

## Мониторинг аппаратного RAID

### SMART через контроллер

```bash
# LSI MegaRAID
sudo smartctl -d megaraid,0 -a /dev/sda

# HP Smart Array
sudo smartctl -d cciss,0 -a /dev/sda

# Проверка здоровья всех дисков
for disk in /dev/sd{a..z}; do
    sudo smartctl -H -d megaraid,0 $disk 2>/dev/null | grep -i "result"
done
```

### Мониторинг через Prometheus

```bash
# Использование storcli + textfile collector
cat <<'EOF' > /usr/local/bin/hwraid_metrics.sh
#!/bin/bash
METRICS_FILE="/var/lib/node_exporter/textfile/hwraid.prom"

echo "# HELP hwraid_vd_state Virtual drive state" > ${METRICS_FILE}.tmp
echo "# TYPE hwraid_vd_state gauge" >> ${METRICS_FILE}.tmp

# Получение состояния логических массивов
sudo storcli /c0 /vall show all | grep -E "State|Size" | while read line; do
    echo "hwraid_vd_state $line" >> ${METRICS_FILE}.tmp
done

mv ${METRICS_FILE}.tmp ${METRICS_FILE}
EOF

chmod +x /usr/local/bin/hwraid_metrics.sh
```

### Алертинг

```bash
# Проверка состояния массива (script для cron)
#!/bin/bash
# /usr/local/bin/hwraid_check.sh

STATUS=$(sudo storcli /c0 /vall show all | grep "State" | grep -v "Optimal")
if [ -n "$STATUS" ]; then
    echo "RAID array degraded: $STATUS" | mail -s "RAID ALERT" admin@example.com
fi

# Проверка BBU
BBU_STATUS=$(sudo storcli /c0 /bbu show all | grep "BatteryState" | grep -v "OK")
if [ -n "$BBU_STATUS" ]; then
    echo "BBU issue: $BBU_STATUS" | mail -s "RAID BBU ALERT" admin@example.com
fi
```

---

## Диагностика и решение проблем

### Диск не определяется в массиве

```bash
# Проверка физических дисков
sudo storcli /c0 /eall /sall show

# Проверка статуса диска
sudo storcli /c0 /e25 /s0 show all

# Принудительное добавление
sudo storcli /c0 /e25 /s0 add hotsparedrive
```

### BBU разряжена

```bash
# Проверка статуса
sudo storcli /c0 /bbu show all

# Если BBU разряжена, контроллер автоматически переключится в Write-Through
# Производительность упадёт до восстановления заряда

# Ручное переключение (если нужно вернуть Write-Back принудительно)
sudo storcli /c0 set wrcache=WB
# ВНИМАНИЕ: Это опасно без заряженного BBU!
```

### Массив в состоянии "Offline" или "Degraded"

```bash
# Проверка состояния
sudo storcli /c0 /vall show all

# Если диск помечен как Failed - замена
sudo storcli /c0 /e25 /s0 set failure
sudo storcli /c0 /e25 /s0 remove
# Физическая замена диска
sudo storcli /c0 /e25 /s0 add hotsparedrive

# Если массив Offline - попытка восстановления
sudo storcli /c0 /v0 start migrate
```

### Переход из RAID в HBA/IT-режим

```bash
# ВНИМАНИЕ: Это уничтожит все массивы!

# Для LSI/Broadcom:
# 1. Скачать Packer из https://techmikeny.com/
# 2. Создать загрузочную USB
# 3. Загрузиться и выбрать IT-firmware

# Для Dell PERC:
# 1. Скачать firmware HBA330
# 2. Загрузиться в UEFI shell
# 3. Запустить обновление
```

---

## Лучшие практики

### Выбор контроллера
*   Для ZFS/Btrfs — чистый HBA (IT-режим), не RAID-контроллер
*   Для аппаратного RAID — LSI/Broadcom MegaRAID или Dell PERC
*   Проверяйте совместимость с вашей ОС и ядром

### Конфигурация
*   Всегда включайте BBU/CacheVault для write-back
*   Настройте Patrol Read для проверки дисков
*   Включите автоматическое переключение в write-through при разрядке BBU

### Мониторинг
*   Мониторьте статус BBU и температуру контроллера
*   ПроверяйтеSMART физических дисков через контроллер
*   Настраивайте алертинг на degraded state

### Безопасность
*   Храните конфигурацию контроллера (egaercfg)
*   Делайте бэкап метаданных массива
*   При замене контроллера убедитесь в совместимости firmware

---

## Дополнительная информация

* [Обзор RAID и mdadm](./overview.md) — сравнение с программным RAID.
* [Влияние RAID на I/O](../../Diagnostics/Performance/DiskIO/raid_io_impact.md) — Write-Back, BBU, кэширование.
* [Диагностика дисков (smartctl)](../../Diagnostics/Hardware/smartctl/index.md) — проверка SMART через контроллер.
* [Мониторинг RAID-массивов](./monitoring.md) — настройка уведомлений.
