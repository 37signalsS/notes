# Диагностика OOM Killer в Linux

## Определения

**Диагностика OOM Killer** — это процесс выявления и ретроспективного анализа причин принудительного завершения процессов ядром из-за исчерпания доступной оперативной памяти или лимитов контрольных групп.

**gfp_mask (Get Free Pages mask)** — набор флагов в логах ядра, описывающий контекст запроса памяти. Помогает понять, кто и зачем запрашивал память (например, процесс в Userspace, прерывание или дисковый драйвер).

**Silent OOM (Тихий OOM)** — завершение процесса без явной записи в системном логе `dmesg`. Часто встречается при использовании cgroups v2, когда ядро убивает дочерний процесс («жертву»), не затрагивая основной процесс контейнера.

**memory.events.local** — файл в cgroups v2, содержащий счетчики событий только для данной группы (в отличие от `memory.events`, который насчитывает события рекурсивно по всей иерархии). Критичен для точной диагностики, в каком именно контейнере/сервисе произошло превышение лимита.

**memory.failcnt** — счетчик в cgroups v2, фиксирующий количество отказов в аллокации памяти из-за превышения `memory.max`. Рост `failcnt` при стабильном `memory.current` означает, что процесс пытается выделить память, но жесткий лимит не дает это сделать, и аллокация возвращает `-ENOMEM`.

**oom_memcg** — путь к контрольной группе, внутри которой сработало cgroup-local OOM. В логе отображается как `oom_memcg=/kubepods/pod...`, что позволяет точно идентифицировать контейнер.

**CONSTRAINT** — флаг в логе OOM, указывающий уровень, на котором произошло событие:
- `CONSTRAINT_NONE` — системный дефицит (вся память хоста).
- `CONSTRAINT_MEMCG` — превышение лимита в cgroup.
- `CONSTRAINT_CPUSET` — нарушение привязки к cpuset (устарел в современных ядрах).
- `CONSTRAINT_CPUSTAT` — используется внутренне ядром.

**smaps_rollup** — агрегированный файл `/proc/<PID>/smaps_rollup`, предоставляющий сводку по памяти процесса (RSS, PSS, Shared_Clean, Shared_Dirty, Private_Clean, Private_Dirty, Swap) без парсинга всего `smaps`. Доступен начиная с ядра 4.18.

## Основные концепции

### Источники диагностических данных

Для качественного расследования инцидента SRE должен использовать несколько источников:

| Источник | Команда | Назначение |
| :--- | :--- | :--- |
| **Ядерный лог (ring buffer)** | `dmesg -T --level=err,crit,alert,emerg` | Первичный анализ события. Ограничен размером буфера; события могут теряться при высокой частоте OOM. |
| **Системный журнал (journald)** | `journalctl -k --since "..." --until "..."` | Постоянное хранение, пережившее перезагрузку. Требует настройки retention. |
| **Счетчики Cgroups v2** | `cat memory.events.local` | Точная статистика `oom_kill` для конкретной группы (не рекурсивная). |
| **Счетчики Cgroups v1** | `cat memory.oom_control` | `oom_kill` и `under_oom` для legacy-систем. |
| **Давление (PSI)** | `cat /proc/pressure/memory` | Поиск корреляции между тормозами системы и моментом OOM. |
| **smaps_rollup** | `cat /proc/<PID>/smaps_rollup` | Быстрый срез памяти процесса (RSS, PSS, Swap) без парсинга smaps. |
| **Утилита smem** | `smem -tk -s pss -r` | Детальный анализ PSS для всей системы. |
| **Perf / bpftrace** | `perf record`, `bpftrace` | Трассировка аллокаций и момента убийства в реальном времени. |

### Глубокий разбор лога OOM Killer

При срабатывании OOM ядро дампит состояние памяти. Ключевой блок:

```text
[1234.56] psql invoked oom-killer: gfp_mask=0x100cca(GFP_HIGHUSER_MOVABLE), order=0, oom_score_adj=0
...
[1234.58] oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/kubepods/pod123,task=psql,pid=1234
[1234.59] Out of memory: Killed process 1234 (psql) total-vm:8GB, anon-rss:4GB, file-rss:0kB, shmem-rss:0kB
```

#### Декодирование параметров

- **`invoked oom-killer`**: Процесс, который «нажал на курок» (последний запросивший память). **Важно:** Это не всегда тот, кто виноват в утечке.
- **`gfp_mask`**:
    - `0x100cca`: Обычная аллокация в пространстве пользователя.
    - `0x14000c0`: Запрос метаданных ФС или сетевого стека. Указывает на системный дефицит, а не на утечку в приложении.
- **`order`**: Порядок аллокации ($2^{order}$ страниц). Если `order > 0`, ядро не смогло найти непрерывный кусок памяти (фрагментация).
- **`constraint`**:
    - `CONSTRAINT_NONE`: Системный дефицит (хост).
    - `CONSTRAINT_MEMCG`: Превышение лимита в Docker/K8s.
    - `CONSTRAINT_CPUSET`: Нарушение ограничений cpuset (редко в современных ядрах).
- **`oom_memcg`**: Путь к cgroup, где произошло событие. Позволяет однозначно идентифицировать контейнер или systemd-сервис.
- **`total-vm` vs `anon-rss`**:
    - `total-vm`: Виртуальное адресное пространство (очень завышено, не показатель).
    - `anon-rss`: Память, выделенная самим приложением (динамические структуры, куча). Именно её OOM Killer пытается освободить.
    - `file-rss`: Кэшированные файлы. Если это значение велико, возможно, проблема не в приложении, а в интенсивном I/O или `mmap`.
    - `shmem-rss`: Память из tmpfs и разделяемых сегментов. Часто игнорируется, но может быть основным потребителем.

#### Анализ состояния процесса через smaps_rollup

Для быстрой проверки, что именно потреблял убитый процесс, используйте `smaps_rollup` (если дамп доступен или анализ на live-системе):

```bash
# Сводка по памяти процесса
cat /proc/<PID>/smaps_rollup | grep -E 'Rss|Pss|Shared|Private|Swap'
# → Rss:               4568 kB
# → Pss:               2345 kB
# → Shared_Clean:        12 kB
# → Shared_Dirty:      8900 kB
# → Private_Clean:     1234 kB
# → Private_Dirty:     3456 kB
# → Swap:                10 kB
```

Высокий `Private_Dirty` указывает на heap-утечку; высокий `Shared_Clean` — на разделяемые библиотеки (не проблема).

#### memory.events.local vs memory.events

В cgroups v2 разница критична для диагностики:

| Файл | Содержание | Применение |
| :--- | :--- | :--- |
| `memory.events` | Суммарные счетчики по группе **и всем ее потомкам** (рекурсивно). | Общая картина по поддереву (например, все контейнеры пода). |
| `memory.events.local` | Счетчики только для **данной** группы, без потомков. | Точная диагностика: какой именно контейнер превысил лимит. |

Пример:
```bash
# Контейнер сервиса
cat /sys/fs/cgroup/kubepods.slice/.../memory.events.local
# → low: 0, high: 5, max: 1, oom: 1, oom_kill: 1

# Родительская группа (все поды)
cat /sys/fs/cgroup/kubepods.slice/memory.events
# → low: 120, high: 340, max: 5, oom: 3, oom_kill: 3
```

Если `memory.events.local` показывает `oom_kill > 0`, а `memory.events` — нет, это означает, что событие произошло в группе-потомке, а родительская группа агрегирует данные рекурсивно.

### Журналирование и сохранение событий

По умолчанию `dmesg` использует кольцевой буфер ограниченного размера. При высокой нагрузке или множестве OOM-событий старые записи могут быть перезаписаны **до** того, как SRE успеет их собрать.

#### Настройка journald для сохранения OOM-логов

```bash
# /etc/systemd/journald.conf
[Journal]
Storage=persistent
SystemMaxUse=1G
SystemMaxFileSize=100M
RuntimeMaxUse=100M
RuntimeMaxFileSize=10M
MaxRetentionSec=30day
ForwardToSyslog=no
MaxLevelStore=debug
```

После изменения:
```bash
systemctl restart systemd-journald
journalctl --rotate
```

#### Проверка размера кольцевого буфера ядра

```bash
# Текущий размер буфера (в килобайтах)
dmesg --printk | head -1
# →    0 0 0 0   (levels: console, default, minimum, boot)

# Увеличение буфера через boot parameter
# /etc/default/grub → GRUB_CMDLINE_LINUX_DEFAULT="... log_buf_len=4M"
update-grub && reboot
```

### Метрики для проактивного мониторинга

Для превентивного обнаружения приближающегося OOM используйте следующие метрики (доступны через `node_exporter`):

| Метрика node_exporter | Источник | Порог (warning/critical) |
| :--- | :--- | :--- |
| `node_memory_MemAvailable_bytes` | `/proc/meminfo` | < 15% / < 10% |
| `node_vmstat_pswpin/s` | `/proc/vmstat` | > 50 / > 100 pages/sec |
| `node_vmstat_pswpout/s` | `/proc/vmstat` | > 50 / > 100 pages/sec |
| `node_vmstat_oom_kill` | `/proc/vmstat` | > 0 (critical) |
| `node_vmstat_pgfault` | `/proc/vmstat` | growth rate spike |
| `node_pressure_memory_full_avg10` | `/proc/pressure/memory` | > 10% / > 20% |

Корреляция `oom_kill > 0` с `MemAvailable_bytes < 10%` и `pswpin/s > 100` указывает на системный дефицит, а не на проблему в одном контейнере.

## Практические сценарии

### Сценарий 1: Ретроспективный поиск OOM

Если сервер «лагал» ночью, проверьте историю:

```bash
# Поиск событий за конкретный период
journalctl -k --since "2026-08-01" --until "2026-08-02" | grep -i "killed process"

# Поиск по времени загрузки (если событие было до сегодняшнего boot)
journalctl -k -b -1 | grep -iE "oom|out of memory|killed process"

# Статистика: сколько раз срабатывал OOM для конкретной cgroup
cat /sys/fs/cgroup/system.slice/nginx.service/memory.events.local
# → low: 0, high: 42, max: 3, oom: 2, oom_kill: 2

# Проверка, сохранились ли записи в dmesg (кольцевой буфер может быть перезаписан)
dmesg -T | grep -iE "oom|killed process" | tail -20

# Для legacy cgroups v1
cat /sys/fs/cgroup/memory/system.slice/nginx.service/memory.oom_control
# → oom_kill 2
# → under_oom 1
```

### Сценарий 2: Мониторинг в реальном времени (eBPF)

Использование BCC-скриптов или `bpftrace` позволяет получить отчет мгновенно, не дожидаясь записи в файл лога.

#### Базовый bpftrace: отслеживание жертв

```bpftrace
# Отслеживание функции oom_kill_process
# Выводит PID убитого процесса, его имя и PID того, кто вызвал OOM.
bpftrace -e 'kprobe:oom_kill_process {
    $victim = args->chosen;
    printf("[%s] OOM-Kill: Victim: PID %d (%s), Triggered by: PID %d\n",
           strftime("%H:%M:%S", nsecs), $victim->pid, str($victim->comm), pid);
}'
```

#### Расширенный bpftrace: жертва + триггер + cgroup

```bpftrace
# Выводит также cgroup и gfp_mask
bpftrace -e 'kprobe:oom_kill_process {
    $v = args->chosen;
    $gfp = args->gfp_mask;
    $order = args->order;
    printf("[%s] OOM-Kill: PID %d (%s) | Trigger: PID %d | gfp=0x%x order=%d\n",
           strftime("%H:%M:%S", nsecs), $v->pid, str($v->comm), pid, $gfp, $order);
}'
```

#### BCC-скрипт: трассировка аллокаций, приведших к OOM

```bash
# Установка BCC (если не установлен)
sudo apt install bpfcc-tools  # Debian/Ubuntu
sudo dnf install bcc-tools    # RHEL/Fedora

# Запись аллокаций за последние 30 секунд до OOM
sudo /usr/share/bcc/tools/memleak -p <PID> -a 30
```

### Сценарий 3: Корреляция с PSI (Thrashing)

Часто OOM случается не мгновенно, а после периода «агонии» системы (Thrashing).

```bash
# Проверьте лог PSI перед моментом OOM
# Если avg10 в full достигает 20-40%, система была парализована ожиданием памяти.
cat /proc/pressure/memory
# → some avg10=8.20 avg60=5.10 avg300=2.80 total=12345678
# → full avg10=3.50 avg60=1.20 avg300=0.40 total=280381

# full avg10 > 5% на протяжении >60 секунд — система деградирует.
# Корреляция: если full avg10 > 20% и через 2-5 минут появилась запись в dmesg — это классический Thrashing → OOM.
```

### Сценарий 4: Анализ кандидатов через oom_score

Если вы подозреваете, что OOM скоро случится, найдите следующую «жертву»:

```bash
# Топ-10 кандидатов по версии ядра (сортировка по oom_score)
printf "%-10s %-10s %-10s %s\n" "SCORE" "PID" "ADJ" "COMMAND"
for p in /proc/[0-9]*; do
    pid=${p##*/}
    [ -r $p/oom_score ] && printf "%-10s %-10s %-10s %s\n" \
        "$(cat $p/oom_score)" "$pid" "$(cat $p/oom_score_adj)" "$(cat $p/comm)"
done 2>/dev/null | sort -nr | head -10
```

Обратите внимание на `ADJ`:
- `-1000`: иммунитет (обычно PID 1 или критические службы).
- `0..200`: нормальные пользовательские процессы.
- `500..999`: низкий приоритет (nohang, earlyoom candidates).
- `1000`: BestEffort / первый кандидат.

### Сценарий 5: Пакетный анализ кластера

При массовом OOM на нескольких серверах соберите данные централизованно:

```bash
#!/bin/bash
# oom_audit_cluster.sh
# Требования: ssh, ключи без пароля, bc

HOSTS="web01 web02 web03 db01 db02"
REPORT=/tmp/oom_cluster_$(date +%Y%m%d).txt

echo "=== OOM Cluster Audit: $(date) ===" > $REPORT

for h in $HOSTS; do
    echo "--- $h ---" >> $REPORT
    ssh $h "
        echo 'dmesg (last 10 OOM lines):'
        dmesg -T | grep -iE 'oom|killed process' | tail -10
        echo ''
        echo 'memory.events.local (system.slice):'
        cat /sys/fs/cgroup/system.slice/memory.events.local 2>/dev/null || echo 'N/A'
        echo ''
        echo 'PSI memory:'
        cat /proc/pressure/memory 2>/dev/null || echo 'N/A'
        echo ''
        echo 'MemAvailable:'
        awk '/MemAvailable/{print \$2}' /proc/meminfo
        echo ''
    " >> $REPORT 2>&1
done

echo "Report saved to $REPORT"
```

Альтернатива для сред с Ansible:
```bash
ansible all -m shell -a "dmesg -T | grep -iE 'oom|killed process' | tail -5"
ansible all -m shell -a "cat /sys/fs/cgroup/system.slice/memory.events.local"
```

### Сценарий 6: Фореnsic-таймлайн инцидента

Восстановите хронологию событий, предшествовавших OOM:

```bash
#!/bin/bash
# oom_forensic_timeline.sh
# Требования: sar (sysstat), journalctl, dmesg

SINCE="2026-08-01 02:00:00"
UNTIL="2026-08-01 04:00:00"
OUT="/tmp/oom_timeline_$(date +%s).txt"

echo "=== Forensic Timeline: $SINCE — $UNTIL ===" > $OUT

echo ">> Journald OOM events:" >> $OUT
journalctl -k --since "$SINCE" --until "$UNTIL" | grep -iE "oom|killed process|invoked oom" >> $OUT

echo "" >> $OUT
echo ">> PSI Memory snapshots (if sar available):" >> $OUT
sar -P ALL 1 360 -s "$SINCE" -e "$UNTIL" 2>/dev/null | grep -E "Memory|CPU" | tail -30 >> $OUT

echo "" >> $OUT
echo ">> vmstat (swap activity):" >> $OUT
sar -W 1 360 -s "$SINCE" -e "$UNTIL" 2>/dev/null >> $OUT

echo "" >> $OUT
echo ">> dmesg (last OOM kernel log):" >> $OUT
dmesg -T | grep -iE "oom|killed process|out of memory" | tail -20 >> $OUT

echo "Timeline saved to $OUT"
```

#### Интерпретация

| Паттерн | Вероятная причина |
| :--- | :--- |
| `si/so` растут за 10–30 минут, потом `oom_kill` | Активный свопинг → Thrashing → OOM. Нужно увеличить RAM или настроить `memory.high`. |
| `psi full avg10` > 20% за 5 минут, потом `oom_kill` | Критическое давление на память без свопа. systemd-oomd должен был сработать раньше. |
| `buddyinfo` показывает пустые high-order столбцы при свободных страницах | Фрагментация. OOM произошел не из-за нехватки RAM, а из-за невозможности выделить contiguous блок. |
| `oom_kill` в `memory.events.local`, но `dmesg` чистый | Silent OOM в cgroups v2. Жертва — дочерний процесс внутри cgroup. |

### Сценарий 7: Анализ через coredump и perf

Если процесс был убит OOM, его последнее состояние можно восстановить через coredump (если настроен `systemd-coredump` или `apport`):

```bash
# Список дампов, связанных с OOM-событиями
coredumpctl list | grep -i "$(date +%Y-%m-%d)"

# Извлечение дампа убитого процесса
coredumpctl dump <PID> --output=/tmp/oom_victim.core

# Быстрый backtrace без GDB
coredumpctl info <PID> | grep -A5 "StackTrace"

# Или интерактивно
coredumpctl gdb <PID>
(gdb) bt
(gdb) info registers
(gdb) quit
```

#### Perf: кто выделял память перед OOM

```bash
# Запись аллокаций за последний час (требует root)
perf record -e kmem:kmalloc -e kmem:kfree -a -- sleep 3600

# Или, если OOM уже произошел, проверьте последние события
perf script | grep -iE "kmalloc|kfree" | tail -50
```

Для приложений, скомпилированных с `-g`, можно использовать `heaptrack` или `valgrind --tool=massif` для пост-мортем анализа, но это требует перезапуска приложения.

### Сценарий 8: NUMA-aware диагностика

На мультисокетных серверах OOM может происходить в одном NUMA-узле, хотя в другом есть свободная память:

```bash
# Состояние NUMA-узлов
numastat -m

# Потребление памяти по узлам для конкретного PID
numastat -p <PID>

# Какой узел "отказал"
cat /proc/zoneinfo | grep -E 'Node [0-9]|free|min'

# Проверка fallback-свопинга (кросс-узельный)
# Если si/so в vmstat растут, а iostat показывает низкий await локального диска
iostat -x 1 5
# → Если await низкий, а swap активен — вероятен кросс-узельный свопинг через QPI/UPI.
```

## Дополнительная информация

### Чек-лист расследования (RCA)

1.  **Кто виноват?** Сравните `invoked` и `Killed`. Если они разные, ищите процесс с максимальным `PSS` через `smem` или `smaps_rollup`.
2.  **Где лимит?** Проверьте `constraint`. Если это `MEMCG`, увеличьте `limits.memory` в манифесте Kubernetes или настройте `memory.high` для throttling вместо жесткого OOM.
3.  **Есть ли Swap?** Если Swap есть, но он пуст в момент OOM, проверьте `vm.swappiness` и `vm.overcommit_memory`.
4.  **Фрагментация?** Если `order > 0`, проверьте `/proc/buddyinfo` и включите `compaction_proactiveness`.
5.  **Logs lost?** Проверьте размер `dmesg` буфера (`dmesg --printk`). Если буфер мал, события могли быть перезаписаны. Настройте `log_buf_len` и `journald` retention.
6.  **Silent OOM?** Проверьте `memory.events.local` в cgroup контейнера. Если `oom_kill > 0`, а PID 1 жив — тихий OOM. Настройте `memory.oom.group=1`.
7.  **PSI pressure?** Если `psi full avg10 > 20%` в течение >5 минут перед OOM, система находилась в thrashing. Настройте `systemd-oomd` или пользовательский алерт.
8.  **Оборудование?** На NUMA-системах проверьте `numastat -m`. Один узел может быть исчерпан, в то время как другой имеет свободную память.
9.  **Post-incident:** Восстановите сервис, проверьте `systemctl status`, `journalctl -u <service> --since "10 minutes ago"`. Убедитесь, что нет зомби-процессов.

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **OOM при наличии свободного cache** | `vm.min_free_kbytes` слишком высокий или фрагментация | Уменьшение `min_free_kbytes`, проверка `buddyinfo`, включение compaction |
| **Медленный OOM (Freeze)** | Медленный swap (HDD), `vm.swappiness=100` | Переход на SSD, zswap/zram, уменьшение swappiness |
| **Системный panic вместо OOM** | `vm.panic_on_oom=1` | См. [Управление OOM Killer](./oom_killer_management.md) |
| **Java-процесс убит, несмотря на -1000** | OOM в cgroup (Docker/K8s), а не системный | Проверка `memory.max` и `oom_kill` в cgroup events |
| **Silent OOM в контейнере** | cgroups v2 убивает дочерний процесс, PID 1 жив | Проверка `memory.events.local`, настройка `memory.oom.group=1` |
| **OOM kill отсутствует в dmesg** | Кольцевой буфер перезаписан или journald не настроен | Увеличение `log_buf_len`, настройка `journald.conf` Storage=persistent |
| **Фрагментация despite free RAM** | `order > 0`, buddyinfo пуст в высоких порядках | `echo 1 > /proc/sys/vm/compact_memory`, увеличение ZONE_MOVABLE |

### См. также

- [**Механизм OOM Killer**](./oom_killer_mechanism.md) — теория и алгоритм выбора жертвы.
- [**Управление OOM Killer**](./oom_killer_management.md) — настройки и `oom_score_adj`.
- [**Давление на ресурсы (PSI)**](../kernel/psi.md) — превентивная диагностика.
