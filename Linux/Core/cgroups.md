# Контрольные группы (cgroups)

## Определения

**Control Groups (cgroups)** — механизм ядра Linux для иерархической организации процессов и управления их доступом к системным ресурсам (CPU, память, I/O, сеть, количество процессов).

На концептуальном уровне `cgroups` дополняют **[Пространства имён (namespaces)](./namespaces.md)**:
- **`namespaces`** отвечают за **изоляцию видимости** (что процесс может *видеть*).
- **`cgroups`** отвечают за **ограничение потребления** (что процесс может *использовать*).

**Ключевая файловая система:** `cgroupfs`, монтируется в `/sys/fs/cgroup`. В современных дистрибутивах (Ubuntu 22.04+, RHEL 9+) по умолчанию используется унифицированная иерархия **cgroups v2**.

---

## Основные концепции

### Контроллеры ресурсов (v2)

Контроллеры (субсистемы) отвечают за управление конкретным типом ресурсов. В v2 они активируются через `cgroup.subtree_control`.

| Контроллер | Назначение | Ключевые файлы (v2) |
| :--- | :--- | :--- |
| **`cpu`** | Управление временем CPU (вес, квоты, burst). | `cpu.weight`, `cpu.max`, `cpu.max.burst`, `cpu.stat` |
| **`memory`** | Ограничение RAM и Swap, управление reclaim. | `memory.min`, `memory.low`, `memory.high`, `memory.max` |
| **`io`** | Ограничение I/O (IOPS, BPS) для блочных устройств. | `io.max`, `io.weight`, `io.stat`, `io.latency` |
| **`pids`** | Защита от fork-бомб (число процессов). | `pids.max`, `pids.current` |
| **`cpuset`** | Жёсткая привязка к ядрам CPU и узлам NUMA. | `cpuset.cpus`, `cpuset.mems` |
| **`hugetlb`** | Лимитирование HugePages. | `hugetlb.<size>.max`, `hugetlb.<size>.current` |
| **`rdma`** | Ограничение ресурсов RDMA/IB. | `rdma.max`, `rdma.current` |
| **`misc`** | Ресурсы вне других групп (например, ASID). | `misc.max`, `misc.current` |

### Сравнение cgroups v1 и v2

**Cgroups v2** — современный стандарт (ядра 4.5+, массово с 5.x). Начиная с **Ubuntu 24.04**, поддержка v1 считается устаревшей.

| Характеристика | Cgroups v1 | Cgroups v2 |
| :--- | :--- | :--- |
| **Иерархия** | Множественные независимые деревья для контроллеров. | Единая унифицированная иерархия. |
| **Процессы** | Процесс может быть в разных группах для разных ресурсов. | Процесс в одной группе для всех контроллеров. |
| **Лимиты памяти** | Только жёсткий лимит (`limit_in_bytes`). | Многоуровневые: `min`, `low`, `high`, `max`. |
| **Давление (PSI)** | Нет нативной интеграции. | Глубокая интеграция с PSI (`*.pressure` файлы). |
| **Threaded Mode** | Отсутствует. | Поддерживается (важно для Go/Java потоков). |
| **Управление** | Файлы типа `tasks` и `cgroup.procs`. | Только `cgroup.procs` (атомарность). |

### Мониторинг давления (PSI)

Cgroups v2 интегрированы с механизмом **[Pressure Stall Information (PSI)](./kernel/psi.md)**. В каждой директории доступны файлы `cpu.pressure`, `memory.pressure`, `io.pressure`.
- **some:** Процент времени, когда хотя бы один процесс ждал ресурса.
- **full:** Процент времени, когда все процессы ждали ресурса (CPU не имеет `full` для предотвращения путаницы с простоем).
- Позволяет современным демонам (например, `systemd-oomd`) превентивно завершать процессы до критического зависания.

### Интеграция с аппаратными технологиями (Resctrl)

В ядрах 6.x+ продолжается интеграция `resctrl` (Resource Control) в интерфейс cgroups для управления кэшем и памятью:
- **L3 Cache Allocation:** Выделение конкретного объема кэша L3 (Intel RDT, AMD PQoS).
- **Memory Bandwidth:** Ограничение полосы пропускания оперативной памяти (Intel MBA, AMD ABMC).

### Осведомлённость приложений (Container Awareness)

Приложение должно считывать лимиты cgroup, а не ресурсы хоста:
- **Java:** JDK 15+ (бэкпорт в 8u372) полностью поддерживает v2. Старые версии видят RAM хоста, что ведет к OOMKilled при превышении лимита контейнера.
- **Go:** С версии 1.19 введена переменная `GOMEMLIMIT`. Рекомендуется использовать библиотеки (например, `automemlimit`) для динамического считывания `memory.max`.
- **Python/Node.js:** Современные рантаймы используют cgroups для определения количества воркеров (на базе CPU квот).

### Видимость ресурсов внутри контейнера (/proc и /sys)

В cgroups v1 виртуальные файловые системы `/proc/meminfo`, `/proc/cpuinfo` и `/proc/stat` **не являются namespaced** — они показывают информацию хоста, а не ограничения контейнера. Это приводит к тому, что утилиты вроде `top`, `free`, `htop` внутри контейнера отображают общий объем оперативной памяти узла (например, 64 ГБ), а не лимит, заданный в `limits.memory` манифесте Pod (например, 2–4 ГБ).

**Механизм проблемы:**
- `/proc/meminfo` — глобальный файл, не привязан к PID namespace.
- Приложение или рантайм (например, JVM до версии 15, Node.js без `--max-old-space-size`) определяет доступную память через `sysconf(_SC_PHYS_PAGES)` или чтение `/proc/meminfo`, получая значение хоста.
- Если приложение аллоцирует память на основе видимого объема хоста, оно превысит лимит cgroup и будет убито OOM Killer (код выхода 137).

**Решение и лучшие практики:**
1. **Использовать cgroups v2** — в ядрах 5.10+ с включенным `cgroup_namespacing` некоторые файлы в `/proc` начинают учитывать лимиты, но не все.
2. **Явно задавать лимиты памяти в настройках рантайма:**
   - Java: `-XX:MaxRAMPercentage=75.0` (JDK 15+) или `-Xmx`
   - Go: `GOMEMLIMIT` (автоматически считывает cgroup v2 с версии 1.19)
   - Node.js: `--max-old-space-size=800` (в МБ)
3. **Использовать библиотеки** типа `automemlimit` для Go или `cgroup-limits` для Python, которые считывают `memory.max` из cgroupfs напрямую.

### Оверхед и производительность

Активация контроллеров (особенно `memory`) создает нагрузку на ядро из-за отслеживания страниц.
- **CPU:** 1–3% при интенсивных операциях с памятью.
- **RAM:** ~1–2 МБ структур данных ядра на каждую cgroup.
- **I/O:** Минимальный оверхед, но может влиять на задержки при активном дросселировании.

### Внутренняя структура унифицированной иерархии (v2)

В cgroups v2 существует четкая иерархия подгрупп, каждая из которых имеет тип, определяемый в файле `cgroup.type`:

| Тип | Описание | Файлы управления |
| :--- | :--- | :--- |
| **`domain`** | Стандартная группа. Может содержать только дочерние `domain`-группы (не потоки). | `cgroup.procs`, контроллеры |
| **`threaded`** | Группа для управления потоками напрямую. Может содержать как `domain`-, так и `threaded`-группы. | `cgroup.procs`, `cgroup.threads`, контроллеры |
| **`domain threaded`** | Наследуемый тип, когда родительская группа является `threaded`. | Аналогично `domain` |

**Ключевое правило:** В подгруппе, содержащей процессы, можно включить только контроллеры, которые активны в родительской группе (через `cgroup.subtree_control`).

### Делегирование и непривилегированный доступ

Делегирование позволяет непривилегированным пользователям или сервисам управлять собственными подгруппами cgroups без root-прав.

**Механизм:**
1. **Активация контроллеров:** В родительской группе записываются нужные контроллеры в `cgroup.subtree_control`.
2. **Наследование:** Все дочерние группы автоматически наследуют активные контроллеры.
3. **Ограничение:** Процесс, уже находящийся в группе, не может получить доступ к контроллерам, которые не были активированы до его помещения в группу.

```bash
# Делегирование контроллеров пользовательской сессии (root)
echo "+cpu +memory +io +pids" | sudo tee /sys/fs/cgroup/user.slice/cgroup.subtree_control

# Настройка лимитов для конкретного пользователя (root)
echo 2G | sudo tee /sys/fs/cgroup/user.slice/user-1000.slice/memory.max
echo "200000 100000" | sudo tee /sys/fs/cgroup/user.slice/user-1000.slice/cpu.max
```

**В systemd:** Делегирование происходит автоматически для user instances (`user@.service`), если указано `Delegate=yes` в unit-файле.

### cgroup Namespace

**Cgroup Namespace** (`CLONE_NEWCGROUP`) — изолирует представление процесса об иерархии контрольных групп. Процесс внутри cgroup namespace видит только свою ветку дерева, что скрывает информацию о других контейнерах/сервисах.

**Практическое значение:**
- Защита от утечек информации о cgroup-иерархии хоста в контейнерах.
- Упрощение миграции контейнеров между узлами (относительные пути cgroup).
- Взаимодействие с **Mount Namespace:** без изолированного mount namespace процессы могут обойти cgroup namespace, монтируя `/sys/fs/cgroup` хоста.

### Управление потоками (Threaded Mode)

В cgroups v2 threaded mode позволяет помещать отдельные потоки (threads) в разные группы, в отличие от классического подхода, где вся группа процессов treated as a single unit.

**Когда необходимо:**
- **Go / Java приложения:** massive thread pools, где часть потоков должна иметь строгие лимиты.
- **Web-серверы (nginx, Apache):** выделение отдельных worker'ов в отдельные группы для QoS.
- **Database connections:** ограничение конкретных пулов соединений.

**Ограничения:**
- Только `domain` группы могут содержать процессы.
- `threaded` группы содержат потоки, но не процессы напрямую.
- Не все контроллеры поддерживают управление потоками (например, `pids` действует на уровне процессов).

---

## Практические сценарии

### Управление через systemd

`systemd` — рекомендуемый способ управления cgroups. Каждая служба помещается в собственный unit или slice.

#### Пример: Настройка ресурсов в юнит-файле

```ini
# /etc/systemd/system/my-app.service
[Service]
ExecStart=/usr/bin/my-app

# --- CPU ---
CPUAccounting=true
CPUQuota=50%               # 50% от одного ядра
CPUWeight=100              # Относительный вес (1-10000)

# --- Память ---
MemoryAccounting=true
MemoryMin=100M             # Гарантированный минимум (не вытесняется)
MemoryHigh=500M            # Мягкий лимит (начинается reclaim/throttle)
MemoryMax=1G               # Жесткий лимит (вызов OOM Killer)

# --- I/O ---
IOAccounting=true
IOWeight=100
IOReadBandwidthMax=/dev/sda 10M

# --- Прочее ---
TasksMax=1000              # Лимит процессов (pids.max)
Delegate=yes               # Разрешить приложению управлять своими cgroups
```

### Ручное управление cgroups v2

#### 1. Создание группы и установка лимитов
```bash
# Создание директории (автоматически создает группу)
sudo mkdir /sys/fs/cgroup/test_group

# Включение контроллеров в дочерней иерархии
echo "+cpu +memory +pids" | sudo tee /sys/fs/cgroup/cgroup.subtree_control

# Установка квоты CPU (10% от одного ядра: 10мс из 100мс)
echo "10000 100000" | sudo tee /sys/fs/cgroup/test_group/cpu.max

# Установка жесткого лимита памяти
echo 512M | sudo tee /sys/fs/cgroup/test_group/memory.max
```

#### 2. Перемещение процесса и управление
```bash
# Добавление процесса в группу
echo <PID> | sudo tee /sys/fs/cgroup/test_group/cgroup.procs

# Атомарное завершение всех процессов в группе (Kernel 5.14+)
echo 1 | sudo tee /sys/fs/cgroup/test_group/cgroup.kill

# Принудительная очистка памяти (Kernel 5.19+)
echo "100M" | sudo tee /sys/fs/cgroup/test_group/memory.reclaim
```

#### 3. Управление всплесками (cpu.max.burst)
Позволяет использовать неиспользованную квоту CPU для обработки кратковременных всплесков нагрузки.
```bash
# Лимит 50% и burst на 20%
echo "50000 100000" | sudo tee /sys/fs/cgroup/test_group/cpu.max
echo "20000" | sudo tee /sys/fs/cgroup/test_group/cpu.max.burst
```

### Контроллер cpuset: изоляция CPU и NUMA

`cpuset` обеспечивает **жёсткую привязку** к ядрам, в отличие от `cpu` (который дает долю времени).

```bash
# Создание изолированной группы
mkdir /sys/fs/cgroup/isolated

# Привязка к ядрам 2-3 и NUMA-узлу 0
echo "2-3" > /sys/fs/cgroup/isolated/cpuset.cpus
echo "0" > /sys/fs/cgroup/isolated/cpuset.mems

# Перемещение процесса
echo <PID> > /sys/fs/cgroup/isolated/cgroup.procs
```
Подробнее: [**CPU Pinning**](./cpu_pinning.md).

### Архитектура systemd Slice

`systemd` строит иерархию cgroups автоматически. Понимание этой иерархии необходимо для корректной настройки лимитов:

```
/sys/fs/cgroup/
├── system.slice/           # Системные сервисы
│   ├── sshd.service/
│   ├── nginx.service/
│   └── docker-<id>.scope/
├── user.slice/             # Пользовательские сессии
│   └── user-1000.slice/
│       └── user@1000.service/
├── machine.slice/          # Виртуальные машины (systemd-nspawn)
│   └── my-vm.scope/
├── init.scope/             # PID 1
└── /                        # Root cgroup (не делегировано)
```

**Ключевые slice:**
- **`system.slice`:** все системные сервисы.
- **`user.slice`:** сессии пользователей (UDC — User Derived Cgroups).
- **`machine.slice`:** контейнеры и ВМ, управляемые через `machinectl`.

### Лимиты для пользовательских сессий (Per-User Resource Limits)

Для ограничения ресурсов конкретного пользователя или группы через systemd используйте drop-in конфигурации:

```ini
# /etc/systemd/system/user@.service.d/10-resource-limits.conf
[Service]
# Ограничение всего пользовательского инстанса
MemoryMax=4G
CPUQuota=200%           # 2 ядра на всю сессию
TasksMax=512
IOWeight=50
```

```ini
# /etc/systemd/system/getty@tty1.service.d/10-limits.conf
[Service]
# Лимит конкретного сервиса
MemoryMax=256M
CPUQuota=50%
```

### Эфемерные задачи через systemd-run

Для разовых задач с гарантированными ресурсами используйте `systemd-run` вместо `nohup`/`screen`:

```bash
# Запуск бэкапа с лимитами (автоматически создается transient scope)
sudo systemd-run --unit=backup-job \
  --scope \
  --memory=1G \
  --cpu-quota=25% \
  --blockio-weight=200 \
  /usr/local/bin/backup.sh

# Проверка статуса
systemctl status backup-job.scope

# Просмотр cgroup
systemd-cgls /system.slice/backup-job.scope
```

**Преимущества:**
- Автоматическое создание cgroup с лимитами.
- Логирование через journald.
- Автоматическая очистка после завершения (`tmpfiles.d` для временных юнитов).

### Изоляция пакетных задач (Batch Jobs)

Для фоновых работ (рендеринг, бэкапы, сборка) создайте отдельный slice:

```ini
# /etc/systemd/system/batch-jobs.slice
[Slice]
CPUWeight=10             # Низкий приоритет относительно system.slice
MemoryMax=8G
IOWeight=50
TasksMax=200
```

```ini
# /etc/systemd/system/batch-worker@.service
[Unit]
Description=Batch Worker %i
PartOf=batch-jobs.slice

[Service]
Slice=batch-jobs.slice
ExecStart=/opt/scripts/batch-worker %i
MemoryMax=512M
CPUQuota=20%
Nice=10
IOSchedulingClass=idle
```

### Экстренное сдерживание ресурсов (Emergency Containment)

При обнаружении "прожорливого" процесса без перезапуска:

```bash
# 1. Найти проблемный cgroup
systemd-cgtop --batch --iterations=1 --order=memory | head -n 5

# 2. Применить мягкий лимит (throttle)
echo 500M | sudo tee /sys/fs/cgroup/system.slice/problem-app.service/memory.high

# 3. Применить жесткий лимит (OOM protection для остальных)
echo 1G | sudo tee /sys/fs/cgroup/system.slice/problem-app.service/memory.max

# 4. Ограничить CPU (ядерный троттлинг)
echo "20000 100000" | sudo tee /sys/fs/cgroup/system.slice/problem-app.service/cpu.max

# 5. Мониторинг давления через PSI
watch cat /sys/fs/cgroup/system.slice/problem-app.service/memory.pressure
```

### Диагностика ресурсов сервиса (cgroup v2)

#### Учёт памяти сервиса

Текущее потребление памяти против жёсткого лимита. Если `memory.current` приближается к `memory.max` — скорый OOM:

```bash
# Текущее потребление vs лимит
cat /sys/fs/cgroup/system.slice/<name>.service/memory.current
cat /sys/fs/cgroup/system.slice/<name>.service/memory.max
# → 1879048192
# → 2147483648
# Или в одну строку:
echo "current=$(cat /sys/fs/cgroup/system.slice/<name>.service/memory.current) max=$(cat /sys/fs/cgroup/system.slice/<name>.service/memory.max)"

# События памяти (OOM-киллы, реклейм)
cat /sys/fs/cgroup/system.slice/<name>.service/memory.events
# → oom 3 oom_kill 3
```

#### Давление памяти по PSI

PSI (Pressure Stall Information) показывает, сколько времени задачи простаивают из-за реклейма памяти. Рост `avg10` — скорый троттлинг до OOM:

```bash
# Текущая нагрузка на память
cat /sys/fs/cgroup/system.slice/<name>.service/memory.pressure
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=123456
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

#### Статистика троттлинга CPU

Сколько раз и на сколько мкс cgroup троттился по квоте `cpu.max`:

```bash
# Чтение и статистика CPU квоты
cat /sys/fs/cgroup/system.slice/<name>.service/cpu.max
# → "50000 100000" = 50% одного ядра; "max 100000" = безлимит

# Статистика троттлинга
grep -E 'nr_throttled|throttled_usec' /sys/fs/cgroup/system.slice/<name>.service/cpu.stat
# → nr_throttled 1234
# → throttled_usec 567890
```

#### Давление и статистика I/O по устройствам

PSI по I/O плюс `rbytes`/`wbytes`/`rios` по major:minor — ловит шумных соседей по диску:

```bash
cat /sys/fs/cgroup/system.slice/<name>.service/io.pressure
cat /sys/fs/cgroup/system.slice/<name>.service/io.stat
# → 8:0 rbytes=12345678 wbytes=9876543 rios=100 wios=200 ...
```

#### Список PID в cgroup сервиса

Все PID в слайсе сервиса. Сверка с деревом из `systemctl status`:

```bash
cat /sys/fs/cgroup/system.slice/<name>.service/cgroup.procs
systemctl status <name>.service | grep CGroup
```

#### Полное дерево cgroup

`systemd-cgls --all` показывает и пустые cgroup; `systemd-cgtop` ранжирует слайсы по CPU/памяти/I/O:

```bash
systemd-cgls --all --no-pager
systemd-cgtop -d 2 --depth=3
```

---

### Миграция с cgroups v1 на v2

**Проверка текущей версии:**
```bash
stat -fc %T /sys/fs/cgroup
# cgroup2fs → v2 активна
# tmpfs → требуется монтирование
```

**Включение v2 (для дистрибутивов с ядром 4.15+):**
```bash
# RHEL/CentOS 8+ / Ubuntu 22.04+ / Debian 11+ — обычно уже v2 по умолчанию
# Для Ubuntu 20.04 / Debian 10:
sudo grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"
sudo reboot
```

**Валидация после перезагрузки:**
```bash
# Проверка типа ФС
stat -fc %T /sys/fs/cgroup
# → cgroup2fs

# Проверка доступных контроллеров
cat /sys/fs/cgroup/cgroup.controllers
# → cpu io memory pids ...

# Проверка, что systemd использует v2
systemctl status | grep "CGroup:"
# → CGroup: /system.slice (/sys/fs/cgroup/system.slice)
```

**Типичные проблемы при миграции:**
- **Docker:** требуется `cgroupfs` или `systemd` driver (не `devicemapper` cgroup v1 style).
- **Kubernetes:** kubelet автоматически определяет v2, но старые containerd требуют `SystemdCgroup=true`.
- **Java приложения:** старые JVM (<15) не видят лимиты памяти, работают с объемом хоста.

### Управление в системах без systemd (cgroup-tools)

На минимальных системах (Alpine, container-оркестраторы) используйте утилиты `cgroup-tools`:

```bash
# Установка (Debian/Ubuntu)
sudo apt install cgroup-tools

# Создание группы иерархии
sudo cgcreate -g cpu,memory,io:/mygroup

# Установка лимитов
sudo cgset -r cpu.shares=512 mygroup
sudo cgset -r memory.limit_in_bytes=1G mygroup

# Запуск процесса в группе
sudo cgexec -g cpu,memory,io:mygroup /usr/bin/my-app

# Просмотр статистики
sudo cgget -g cpu,memory,io:mygroup
```

**Разовый cgroup в legacy v1 (memory-only):**

Для одного контроллера используйте сокращённый синтаксис:

```bash
cgcreate -g memory:/<name>
cgset -r memory.limit_in_bytes=512M <name>
cgexec -g memory:/<name> <command>
```

> **Примечание:** `cgroup-tools` работает только с **cgroups v1**. Для v2 используйте ручное управление файлами в `/sys/fs/cgroup/` или `systemd-run --scope`.

### Взаимодействие с SELinux и AppArmor

**SELinux (RHEL/Fedora/CentOS):**
- Контексты cgroup-файлов должны соответствовать политике. Проверка: `ls -Z /sys/fs/cgroup/...`
- При создании подгрупп от имени непривилегированного пользователя могут потребоваться `sudo restorecon` или `chcon`.
- **`cgroup_disable=all`** или **`cgroup_no_v1=all`** в GRUB полностью отключают cgroups — несовместимо с современными контейнерами.

**AppArmor (Ubuntu/Debian):**
- Профили AppArmor для systemd-юнитов могут блокировать запись в cgroup-файлы. Проверяйте логи: `journalctl -u <service> | grep DENIED`.

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **OOMKilled** | Превышен `memory.max`. | См. `memory.events` (счетчик `oom_kill`). Увеличьте лимит или настройте `memory.high`. |
| **Throttling** | Превышен `cpu.max`. | Проверьте `cpu.stat` (поле `nr_throttled`). Увеличьте квоту или используйте `cpu.max.burst`. |
| **Internal Process Constraint** | Попытка включить контроллер в группе с процессами. | В v2 процессы могут быть только в листовых узлах, если включены контроллеры. |
| **Контроллер недоступен** | Не включен в `cgroup.subtree_control`. | `echo "+cpu" > .../cgroup.subtree_control` в родительской группе. |
| **Java OOM** | Старая JVM не видит лимиты. | Обновите JDK (11+ / 8u372+) или используйте `-Xmx`. |
| **Cannot allocate memory при создании cgroup** | Достигнут лимит `pids.max` в родительской группе или недостаточно памяти в родительской `memory.max`. | Увеличьте `pids.max` в родителе или проверьте `memory.high`/`memory.max`. |
| **Делегирование контроллеров не работает** | Контроллеры не активированы в `cgroup.subtree_control` родительской группы. | `echo "+cpu +memory" > /sys/fs/cgroup/parent/cgroup.subtree_control` (от root). |
| **Конфликт systemd и containerd/docker** | Разные драйверы cgroup (cgroupfs vs systemd). | Установите `SystemdCgroup = true` в containerd. |
| **Потоки (threads) не перемещаются** | Попытка переместить поток в группу без `cgroup.threads` (требуется threaded mode). | Перемещайте по PID через `cgroup.procs` или настройте threaded subtree. |
| **No space left on device при создании cgroup** | Достигнут лимит `cgroup.max_depth` или `cgroup.max_descendants` в родителе. | Увеличьте лимиты в родительской группе. |
| **I/O троттлинг не применяется** | `IOAccounting=no` или контроллер `io` не делегирован. | Включите `IOAccounting=yes` в unit-файле; проверьте `cgroup.subtree_control`. |
| **SELinux denies cgroup write** | Политика SELinux блокирует запись в cgroup-файлы. | `audit2allow -w -a` для анализа; `restorecon -R /sys/fs/cgroup` для исправления контекстов. |

### Best Practices

1. **Иерархия:** Создавайте cgroup-дерево, отражающее архитектуру сервисов (по окружениям, приоритетам, командам). Не смешивайте временные и постоянные группы в одном пути.
2. **Мягкие лимиты (`memory.high`, `cpu.max` burst):** Используйте для graceful degradation. Жесткие лимиты (`memory.max`) — для катастрофической защиты (OOM Kill).
3. **Делегирование:** Для сервисов, управляемых через `systemd-run` или контейнеры, всегда включайте `Delegate=yes`, если приложение само управляет подгруппами (например, Kubernetes kubelet).
4. **Мониторинг:** Включайте `CPUAccounting=yes`, `MemoryAccounting=yes`, `IOAccounting=yes` в production-юнитах. Оверхед минимален, но данные критичны для диагностики.
5. **Атомарность операций:** Для изменения нескольких параметров одновременно используйте скрипты с `cat > file` (atomic write), а не множественные `echo >>` (append).
6. **PIDs limit:** Всегда устанавливайте `TasksMax=` для сервисов, обрабатывающих внешний ввод (web, API). Рекомендуемое значение: 5–10x от ожидаемого числа воркеров.
7. **Read-only корень:** Для контейнеров и chroot-окружений монтируйте корень как `ro` и используйте `memory.min` для защиты кэша от агрессивного reclaim.
8. **Очистка:** Удаляйте неиспользуемые cgroup-группы. В systemd это происходит автоматически; в ручном режиме — `rmdir` после остановки всех процессов.
9. **Версионирование:** Начиная с Ubuntu 24.04 / RHEL 10, cgroups v1 полностью удалена. Все новые конфигурации должны быть для v2.
10. **Документация:** Комментируйте unit-файлы и скрипты, указывая **почему** установлены конкретные лимиты (SLA, тип нагрузки, количество пользователей).

### Граничные случаи и ограничения

- **Thread placement:** В v2 процесс может находиться только в одной `domain`-группе, но его потоки — в разных `threaded`-группах. Попытка переместить процесс в группу, где уже есть потоки, завершится `EBUSY`.
- **Cgroup Namespace + Mount Namespace:** Без изолированного mount namespace процесс может обойти cgroup namespace, перемонтировав `/sys/fs/cgroup`. Для полной изоляции используйте `unshare --cgroup --mount`.
- **Очистка `memory.reclaim`:** Файл `memory.reclaim` (ядро 5.19+) возвращает количество страниц, которые не удалось освободить (например, из-за активных анонимных страниц). Это нормально и не является ошибкой.
- **`io.latency` controller:** Требует точной настройки `target` (например, `10ms`). Неправильное значение может привести к деградации производительности вместо улучшения.
- **Hotplug и cgroups:** При добавлении нового устройства (диска, NIC) cgroup-лимиты (`io.max`, `io.weight`) не применяются автоматически. Требуется перезагрузка конфигурации или systemd daemon-reload.
- **Root cgroup:** Нельзя установить лимиты напрямую в корневой cgroup (`/sys/fs/cgroup/`). Все ограничения применяются только в дочерних группах.
- **`cgroup.kill`:** Уничтожает все процессы в группе (ядро 5.14+). Работает только для листовых узлов. Не работает, если группа содержит подгруппы.
- **Виртуальные файловые системы:** `cgroupfs` не кэширует атрибуты. Каждое чтение файла `/sys/fs/cgroup/.../memory.current` вызывает syscall в ядро — не используйте в высокочастотных циклах без кэширования.
- **Приоритет лимитов:** Если cgroup ограничивает `memory.max=512M`, а `RLIMIT_AS` (ulimit) установлен в `1G`, процесс будет убит при 512MB. Cgroups имеют приоритет над rlimits.
- **Persistence:** Изменения в `/sys/fs/cgroup/` живут только до перезагрузки. Для persistence используйте systemd drop-ins, `/etc/tmpfiles.d/` или ини-скрипты.

---

## Дополнительная информация

### Инструменты мониторинга

| Инструмент | Назначение | Пример команды |
| :--- | :--- | :--- |
| `systemd-cgls` | Дерево cgroups и процессов. | `systemd-cgls --all --no-pager` |
| [`systemd-cgtop`](./systemd/cgtop.md) | Мониторинг ресурсов в реальном времени. | `systemd-cgtop -d 2 --depth=3` |
| `cat /sys/fs/cgroup/.../cpu.stat` | Статистика дросселирования. | `grep -E 'nr_throttled\|throttled_usec' /sys/fs/cgroup/system.slice/<name>.service/cpu.stat` |
| `cat /sys/fs/cgroup/.../memory.current` | Текущее потребление памяти. | `cat /sys/fs/cgroup/system.slice/<name>.service/memory.current` |
| `cat /proc/pressure/*` | Статистика давления PSI на хосте. | `cat /proc/pressure/memory` |

### Связанные темы

- **[Пространства имён (namespaces)](./namespaces.md)** — изоляция видимости.
- **[OOM Killer в контейнерах](./processes/oom_killer_containers.md)** — иерархический OOM и QoS классы.
- **[Привязка процессоров (CPU Pinning)](./cpu_pinning.md)** — методы изоляции ядер.
- **[Давление на ресурсы (PSI)](./kernel/psi.md)** — детальный разбор метрик давления.
- **[Концепции лимитов ресурсов (rlimits)](./processes/resource_limits_concepts.md)** — сравнение cgroups и ulimit.
- **[Изоляция контейнеров](../../Docker/Concepts/linux_isolation.md)** — применение в Docker/K8s.
- **[Эфемерные задачи (systemd-run)](./systemd/systemd_run.md)** — динамические юниты с автоматическим управлением cgroups.
- **[Планирование процессов (scheduler)](./processes/scheduling.md)** — взаимодействие `cpu.max`/`cpu.weight` с CFS/EEVDF.

### Ресурсы

- [Документация ядра Linux (cgroup-v2.rst)](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Systemd Resource Control](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)
