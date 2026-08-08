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

### Оверхед и производительность

Активация контроллеров (особенно `memory`) создает нагрузку на ядро из-за отслеживания страниц.
- **CPU:** 1–3% при интенсивных операциях с памятью.
- **RAM:** ~1–2 МБ структур данных ядра на каждую cgroup.
- **I/O:** Минимальный оверхед, но может влиять на задержки при активном дросселировании.

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

---

## Дополнительная информация

### Инструменты мониторинга

| Инструмент | Назначение | Пример команды |
| :--- | :--- | :--- |
| `systemd-cgls` | Дерево cgroups и процессов. | `systemd-cgls` |
| [`systemd-cgtop`](./systemd/cgtop.md) | Мониторинг ресурсов в реальном времени. | `systemd-cgtop` |
| `cat /sys/fs/cgroup/.../cpu.stat` | Статистика дросселирования. | `cat /sys/fs/cgroup/user.slice/cpu.stat` |
| `cat /proc/pressure/*` | Статистика давления PSI на хосте. | `cat /proc/pressure/memory` |

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **OOMKilled** | Превышен `memory.max`. | См. `memory.events` (счетчик `oom_kill`). Увеличьте лимит или настройте `memory.high`. |
| **Throttling** | Превышен `cpu.max`. | Проверьте `cpu.stat` (поле `nr_throttled`). Увеличьте квоту или используйте `cpu.max.burst`. |
| **Internal Process Constraint** | Попытка включить контроллер в группе с процессами. | В v2 процессы могут быть только в листовых узлах, если включены контроллеры. |
| **Контроллер недоступен** | Не включен в `cgroup.subtree_control`. | `echo "+cpu" > .../cgroup.subtree_control` в родительской группе. |
| **Java OOM** | Старая JVM не видит лимиты. | Обновите JDK (11+ / 8u372+) или используйте `-Xmx`. |

### Связанные темы

- **[Пространства имён (namespaces)](./namespaces.md)** — изоляция видимости.
- **[OOM Killer в контейнерах](./processes/oom_killer_containers.md)** — иерархический OOM и QoS классы.
- **[Привязка процессоров (CPU Pinning)](./cpu_pinning.md)** — методы изоляции ядер.
- **[Давление на ресурсы (PSI)](./kernel/psi.md)** — детальный разбор метрик давления.
- **[Концепции лимитов ресурсов (rlimits)](./processes/resource_limits_concepts.md)** — сравнение cgroups и ulimit.
- **[Изоляция контейнеров](../../Docker/Concepts/linux_isolation.md)** — применение в Docker/K8s.

### Ресурсы

- [Документация ядра Linux (cgroup-v2.rst)](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Systemd Resource Control](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)
