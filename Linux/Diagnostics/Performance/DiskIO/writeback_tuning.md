# Настройка writeback: параметры ядра

## Определение

- **Грязные страницы (Dirty Pages)**: Страницы оперативной памяти в системном кэше (Page Cache), содержимое которых было изменено приложением, но ещё не синхронизировано с постоянным хранилищем. В ядре помечаются флагом `PG_dirty`.
- **Обратная запись (Writeback)**: Фоновый механизм ядра Linux по переносу «грязных» страниц из оперативной памяти на диск. Управляется flusher-потоками (современный вариант `kworker`).
- **BDI (Backing Device Info)**: Структура данных ядра, позволяющая подсистеме writeback отслеживать состояние конкретного блочного устройства и применять к нему специфичные лимиты.
- **balance_dirty_pages()**: Ключевая функция ядра, регулирующая скорость, с которой приложения могут создавать новые dirty pages. При превышении `vm.dirty_ratio` вызывает принудительное замедление процессов (I/O Throttling), заставляя их участвовать в сбросе данных.
- **Flusher Threads**: Специализированные потоки ядра (в современных ядрах представлены как `kworker`), ответственные за выполнение writeback для конкретных устройств. Работают периодически, проверяя, не «стареют» ли dirty pages.
- **WritebackTmp**: Временная память, используемая ядром при сбросе грязных страниц на диск. Учитывается в `/proc/meminfo` как `WritebackTmp` и добавляется к `Dirty` при расчёте общей нагрузки на I/O.
- **dirtytime_expire_seconds**: Время (в секундах), по истечении которого atime/mtime сбрасывается на диск в режиме монтирования `lazytime`. Не влияет на данные файла, но предотвращает бесконечное накопление метаданных в памяти.

## Основные концепции

Ядро Linux использует отложенную запись для повышения производительности дисковой подсистемы за счёт объединения мелких запросов в крупные последовательные блоки. Параметры `vm.dirty_*` позволяют сбалансировать скорость работы, риск потери данных при сбое и отзывчивость системы.

### Жизненный цикл грязной страницы

1.  **Clean**: Страница в памяти идентична данным на диске.
2.  **Dirty**: Приложение вызвало `write()`, данные в RAM изменены, страница помечена флагом `PG_dirty`.
3.  **Writeback**: Подсистема инициирует сброс, страница помечается `PG_writeback`, начинаются сетевые/дисковые операции.
4.  **Clean**: После подтверждения от драйвера устройства страница снова становится `Clean`.

### Механизм balance_dirty_pages

Каждый раз, когда процесс создаёт dirty page, ядро вызывает `balance_dirty_pages()`. Функция сравнивает:
- Текущий объём грязных страниц с порогами (`vm.dirty_background_ratio` / `vm.dirty_bytes`).
- Скорость, с которой диск способен сбрасывать данные.

Если приложение пишет быстрее, чем диск может переварить, ядро принудительно замедляет процесс (I/O Throttling), заставляя его участвовать в сбросе. Это видно по процессам в `D-state` с `wchan=balance_dirty_pages`.

### Ключевые параметры тюнинга

| Параметр | По умолчанию | Описание | Рекомендация (2025-2026) |
| :--- | :--- | :--- | :--- |
| **`vm.dirty_background_ratio`** | 10 | % RAM, при котором фоновые потоки (`kworker`) начинают асинхронную запись. Не блокирует приложения. | 3–7% (для NVMe/SSD) |
| **`vm.dirty_ratio`** | 20 | % RAM, при котором процесс принудительно блокируется до освобождения памяти (I/O Stall/Throttling). | 10–20% |
| **`vm.dirty_background_bytes`** | 0 | Альтернатива `ratio` в байтах. Имеет приоритет над `ratio`. | 128MB–512MB |
| **`vm.dirty_bytes`** | 0 | Альтернатива `ratio` в байтах. Имеет приоритет над `ratio`. | 1GB–2GB |
| **`vm.dirty_expire_centisecs`** | 3000 | Время (в 0.01 сек), по истечении которого страница считается «старой» и подлежит сбросу. | 1500 (15с) – 3000 (30с) |
| **`vm.dirty_writeback_centisecs`** | 500 | Интервал (в 0.01 сек) пробуждения потоков `kworker` для проверки «старых» страниц. | 100 (1с) – 500 (5с) |
| **`vm.dirtytime_expire_seconds`** | 43200 | Время (в сек) для сброса метаданных (inode), если используется режим монтирования `lazytime`. | 43200 (12ч) |
| **`vm.vfs_cache_pressure`** | 100 | Приоритет очистки Slab (метаданные: dentry/inode) относительно Page Cache. | 50 (для СУБД) |

### Проблема больших объёмов оперативной памяти

На современных серверах с 128 ГБ+ RAM значения по умолчанию (10%/20%) становятся опасными:
- **10% от 128 ГБ** = 12.8 ГБ грязных данных в памяти.
- При внезапном сбросе такого объёма возникает «I/O storm», полностью блокирующий диск на несколько секунд или даже минут, что вызывает огромные задержки (Tail Latency) для приложений.
- **Решение**: Использовать абсолютные значения через `vm.dirty_bytes` и `vm.dirty_background_bytes`, чтобы ограничить кэш записи разумными пределами (например, до 1–2 ГБ), которые диск способен сбросить быстро.

### Writeback и cgroups v2

В современных системах writeback учитывает лимиты cgroup (`memory.high` / `memory.max`). Это гарантирует, что один «прожорливый» контейнер не сможет занять весь системный бюджет грязных страниц и не вызовет throttling у других приложений.

### Взаимодействие с journaling (jbd2)

Для файловых систем с журналированием (ext4, XFS) writeback работает в тандеме с потоками `jbd2`:
1. Изменения данных попадают в Page Cache как dirty pages.
2. `jbd2` записывает транзакции метаданных в журнал.
3. `kworker` сбрасывает как данные, так и journal на диск.

Высокая нагрузка на `jbd2` при низкой активности `kworker` обычно указывает на проблемы с метаданными (тысячи мелких файлов). Подробнее о диагностике: [Роль kworker и процессов writeback](./kworker_flush.md).

### NFS и сетевой writeback

Для NFS writeback имеет особенности:
- Отложенная запись (`async`) позволяет приложению продолжить работу, но при зависании сервера поток writeback для этого BDI уходит в `D-state` на неопределённое время.
- Это блокирует не только сам `kworker`, но и процессы, пытающиеся записать в ту же точку монтирования (через `balance_dirty_pages`).
- В sysfs NFS-специфичная статистика доступна в `/sys/class/bdi/<MAJOR:MINOR>/` как `NFS_Writeback`.

Подробнее: [Роль kworker и процессов writeback](./kworker_flush.md).

## Практические сценарии

### Предварительные требования

Для тюнинга writeback необходимы базовые инструменты, доступные в любой стандартной установке Linux:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y sysstat procps

# RHEL/CentOS/AlmaLinux
sudo dnf install -y sysstat procps-ng

# openSUSE
sudo zypper install -y sysstat procps
```

Проверка доступа:
```bash
# Достаточно прав обычного пользователя для чтения /proc/meminfo
grep -E "Dirty|Writeback" /proc/meminfo
```

### Просмотр и временная настройка

```bash
# Просмотр текущих значений всех параметров dirty
sysctl -a | grep vm.dirty
# → result: vm.dirty_background_ratio = 10, vm.dirty_ratio = 20 ...

# Мониторинг грязных страниц в реальном времени
watch -n1 "grep -E 'Dirty|Writeback' /proc/meminfo"

# Временное изменение (сбросится после перезагрузки)
sudo sysctl -w vm.dirty_ratio=15
sudo sysctl -w vm.dirty_background_ratio=7
# → result: vm.dirty_ratio = 15, vm.dirty_background_ratio = 7
```

### Профили настройки под разные нагрузки

#### Базы данных (PostgreSQL, MySQL) и низкая задержка
Цель: максимально частый и мелкий сброс данных, минимизация риска потери и исключение I/O Stalls.
```bash
# Агрессивный фоновый сброс
vm.dirty_background_ratio = 3
vm.dirty_ratio = 10
vm.dirty_expire_centisecs = 1500
vm.dirty_writeback_centisecs = 100
vm.vfs_cache_pressure = 50
vm.swappiness = 1
```

#### Системы с большим объёмом RAM (128 ГБ+)
Цель: ограничение абсолютного размера кэша для предотвращения "дисковых штормов".
```bash
# Ограничение 256 МБ для фона и 1 ГБ для блокировки
vm.dirty_background_bytes = 268435456
vm.dirty_bytes = 1073741824
```

#### Современные NVMe накопители (2025-2026)
Цель: использование высокой параллельности NVMe, более интенсивный сброс без вреда для латентности.
```bash
vm.dirty_background_ratio = 5
vm.dirty_ratio = 15
vm.dirty_writeback_centisecs = 200
```

#### Файловые серверы (высокая пропускная способность)
Цель: максимальное накопление данных для последовательной записи крупными блоками.
```bash
vm.dirty_background_ratio = 20
vm.dirty_ratio = 40
vm.dirty_writeback_centisecs = 1000
```

### Предварительный анализ перед тюнингом

Перед изменением параметров зафиксируйте baseline:
```bash
# 1. Текущие значения sysctl
sysctl vm.dirty_ratio vm.dirty_background_ratio vm.dirty_bytes vm.dirty_background_bytes vm.dirty_expire_centisecs vm.dirty_writeback_centisecs

# 2. Объём грязных страниц
grep -E "Dirty|Writeback|WritebackTmp" /proc/meminfo

# 3. Активность kworker
ps -eo pid,state,wchan:30,comm | grep -E "kworker|flush" | head -n 10

# 4. Утилизация диска
iostat -xz 1 3 | grep -E "Device|sda|nvme"

# 5. PSI (давление на I/O)
cat /proc/pressure/io
```

Сохраните вывод. После применения настроек сравните показатели через 15–30 минут нормальной нагрузки.

### Валидация изменений

После применения новых параметров проверьте:
```bash
# 1. Параметры применены
sysctl vm.dirty_ratio vm.dirty_background_ratio

# 2. Dirty pages не накапливаются бесконечно
watch -n5 "grep -E 'Dirty|Writeback' /proc/meminfo"
# Ожидаемо: Dirty поднимается до ~ dirty_background_bytes и стабильно сбрасывается

# 3. Нет аномальной активности kworker
top -bn1 | grep kworker
# Ожидаемо: kworker не в топе по CPU при отсутствии активной записи

# 4. Нет процессов в D-state (balance_dirty_pages)
ps -eo pid,state,wchan:30,comm | grep " D " | grep -c balance_dirty_pages
# Ожидаемо: 0 или единичные случаи при кратковременных пиках
```

### Аварийный runbook: I/O storm

**Симптом:** Диск 100% загружен (`%util = 100%`), `await > 100ms`, приложения "фризят", `Dirty` растёт, `Writeback` не успевает.

**Действия (по порядку):**

1. **Оцените масштаб:**
   ```bash
   watch -n1 "grep -E 'Dirty|Writeback' /proc/meminfo && iostat -xz 1 1 | grep -E 'Device|sda|nvme'"
   ```

2. **Немедленное снижение порога** (если используется ratio):
   ```bash
   # Для систем с 64GB+ RAM резкое изменение ratio на абсолютные значения
   sudo sysctl -w vm.dirty_background_bytes=134217728
   sudo sysctl -w vm.dirty_bytes=536870912
   ```

3. **Приостановка записывающих процессов** (если диск полностью заблокирован):
   ```bash
   # Найти топ-писателей
   sudo iotop -oP -d 1 | head -n 10
   
   # Приостановить (SIGSTOP)
   sudo kill -STOP <pid>
   ```

4. **Проверка здоровья диска:**
   ```bash
   sudo dmesg | grep -iE "timeout|error|reset|scsi"
   sudo smartctl -a /dev/sda | grep -E "Reallocated|Current_Pending|Offline_Uncorrectable"
   ```

5. **Если диск физически здоров, но не справляется** — рассмотрите переход на tmpfs для временных данных или отключение writeback для критичных ФС (только если есть UPS):
   ```bash
   mount -o remount,data=writeback /mnt/temp
   ```

### Мониторинг и алерты (Prometheus / Node Exporter)

Метрики для отслеживания здоровья writeback:

```yaml
groups:
  - name: writeback_alerts
    rules:
      - alert: HighDirtyPages
        expr: node_memory_Dirty_bytes / node_memory_MemTotal_bytes > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий объём грязных страниц на {{ $labels.instance }}"
          description: "Dirty pages {{ $value | humanizePercentage }}. Проверьте vm.dirty_* параметры и скорость диска."

      - alert: WritebackStalled
        expr: rate(node_memory_Writeback_bytes[5m]) > 0 and (node_memory_Dirty_bytes - node_memory_Writeback_bytes) / node_memory_MemTotal_bytes > 0.03
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Writeback заблокирован на {{ $labels.instance }}"
          description: "Dirty растёт, Writeback не сбрасывается. Возможна проблема с диском или NFS."

      - alert: DirtyRatioNearThreshold
        expr: node_memory_Dirty_bytes / node_memory_MemTotal_bytes > (node_vm_dirty_ratio - 5) / 100
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Dirty pages приближаются к порогу vm.dirty_ratio"
          description: "Текущий уровень {{ $value | humanizePercentage }}, порог {{ $labels.ratio }}%."
```

Для ручного мониторинга:
```bash
# Порог: Dirty > 5% RAM — повод задуматься
TOTAL_MB=$(free -m | awk '/Mem:/ {print $2}')
DIRTY_MB=$(grep Dirty /proc/meminfo | awk '{print $2}')
DIRTY_PCT=$(echo "scale=1; $DIRTY_MB * 100 / $TOTAL_MB" | bc)
echo "Dirty: ${DIRTY_MB}MB (${DIRTY_PCT}%)"

if [ "$(echo "$DIRTY_PCT > 5" | bc)" -eq 1 ]; then
    echo "WARNING: Dirty pages превышают 5% RAM"
fi
```

### Тюнинг для контейнеров (cgroups v2)

В cgroups v2 writeback учитывает лимиты `memory.high` и `memory.max`. Это предотвращает ситуацию, когда один контейнер «загрязняет» память и вызывает throttling для всей системы.

**Важные нюансы:**
- Если `memory.high` ниже точки, при которой срабатывает `vm.dirty_background_ratio`, контейнер может получить throttling раньше времени.
- Рекомендуется настраивать `vm.dirty_*` на хосте так, чтобы фоновый сброс начинался при заполнении не более 3-5% RAM, и ставить `memory.high` для контейнера выше этого порога.
- В cgroups v1 аналога нет — writeback может игнорировать лимиты памяти. Используйте `blkio.throttle.write_bps` как запасной вариант.

### Откат изменений

Если новые параметры вызвали деградацию производительности:

```bash
# Быстрый откат к дефолтным значениям
sudo sysctl -w vm.dirty_ratio=20
sudo sysctl -w vm.dirty_background_ratio=10
sudo sysctl -w vm.dirty_bytes=0
sudo sysctl -w vm.dirty_background_bytes=0

# Или удалите конфигурационный файл и примените defaults
sudo rm /etc/sysctl.d/99-writeback-tuning.conf
sudo sysctl --system
```

Для постоянной откатки проверьте, что в `/etc/sysctl.d/` нет файлов с изменёнными `vm.dirty_*`.

### Сохранение настроек (постоянно)

```bash
# Создание конфигурационного файла
cat << EOF | sudo tee /etc/sysctl.d/99-writeback-tuning.conf
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 300
vm.vfs_cache_pressure = 50
EOF
# → result: (создан файл /etc/sysctl.d/99-writeback-tuning.conf)

# Применение изменений без перезагрузки
sudo sysctl --system
# → result: * Applying /etc/sysctl.d/99-writeback-tuning.conf ...
```

## Ограничения и особые случаи

### NFS и сетевые файловые системы

При монтировании NFS с `sync` все операции `write()` блокируются до физической записи на сервер. Это полностью устраняет writeback на клиенте, но резко снижает производительность. Рекомендуется использовать `async` с надёжным сервером и UPS.

При зависании NFS-сервера поток writeback уходит в `D-state`, блокируя процессы. Единственное решение: `umount -f` или перезагрузка.

### cgroups v1 vs v2

В cgroups v1 writeback не учитывает лимиты memory контроллера по умолчанию. Это означает, что один контейнер может «загрязнить» память и вызвать throttling для всей системы. Решение: миграция на cgroups v2 или использование `blkio.throttle.write_bps`.

### 32-битные системы

На 32-битных ядрах лимиты `vm.dirty_ratio` могут быть слишком низкими на дисках >1 ТБ, что вызывает частые сбросы. На практике используйте абсолютные значения (`vm.dirty_bytes`).

### SSD и Write Amplification

На SSD активность flusher threads может провоцировать внутренние процессы Garbage Collection (GC), увеличивая видимую нагрузку. Особенно критично при заполнении диска >80%. Решение: мониторинг свободного места (`df -h`) и использование `fstrim.timer`.

### Паравиртуализация (KVM, Xen, VMware)

В гостевой ОС `/proc/meminfo` показывает виртуализированную статистику. Если хост перегружен, guest может видеть высокий `Dirty` при нормальном `Writeback`, так как гипервизор замедляет доступ к диску. Для точной картины необходимы метрики гипервизора.

### Overcommit и OOM

Если `vm.overcommit_memory = 1` (HEURISTIC), ядро может разрешить приложению записать больше данных, чем есть памяти + swap. При нехватке памяти активируется Direct Reclaim, который вызывает синхронный writeback и блокирует процессы. Рекомендуется `vm.overcommit_memory = 0` (STRICT) для продакшн-серверов баз данных.

## Дополнительная информация

### См. также

- [Роль kworker и процессов writeback](./kworker_flush.md) — детальный разбор работы фоновых потоков ядра, диагностика через bpftrace/perf.
- [Диагностический чеклист ввода-вывода](./diagnostic_checklist.md) — пошаговый алгоритм поиска проблем I/O.
- [Оптимизация производительности ФС](../../../FileSystems/performance_tuning.md) — влияние параметров монтирования (noatime, commit) на производительность.
