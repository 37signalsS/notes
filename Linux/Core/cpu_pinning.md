# CPU Pinning (Привязка к CPU)

## Определения

**CPU Pinning** (привязка к процессорным ядрам, CPU affinity) — механизм назначения процесса или потока для выполнения на определённом ядре (или наборе ядер) CPU. Гарантирует, что планировщик ОС не будет перемещать процесс между ядрами.

**Ключевая цель:** Повышение предсказуемости производительности и снижение задержек за счёт:

- Улучшения использования кэша CPU (L1/L2/L3)
- Устранения накладных расходов на миграцию между ядрами
- Изоляции рабочих нагрузок от «шумных соседей»
- Оптимизации для NUMA-архитектур

## Основные концепции

### Механизмы привязки в Linux

| Механизм | Уровень | Назначение | Инструменты |
| :--- | :--- | :--- | :--- |
| **CPU affinity** | User-space | Привязка процесса к ядрам | `taskset`, `sched_setaffinity()` |
| **cpuset (cgroups)** | Kernel | Привязка + изоляция памяти NUMA | `cgroups`, `kubectl` |
| **isolcpus** | Kernel | Полная изоляция от планировщика | Параметр ядра |
| **IRQ affinity** | Kernel | Привязка прерываний к ядрам | `/proc/irq/*/smp_affinity` |

### Инструменты привязки

#### 1. `taskset` — базовая привязка

Простой инструмент для установки/get CPU affinity процесса.

```bash
# Запустить процесс на ядре 2
taskset -c 2 ./my_app

# Изменить привязку запущенного процесса (PID 1234)
taskset -pc 0,3 1234

# Показать текущую привязку
taskset -p 1234

# Маска CPU (шестнадцатеричная)
taskset 0x3 ./my_app  # Ядра 0 и 1
```

#### 2. `numactl` — привязка с учётом NUMA

Управление политикой CPU и памяти для NUMA-систем.

```bash
# Запустить на ядрах 0-3 с памятью NUMA-узла 0
numactl --cpunodebind=0 --membind=0 ./my_app

# Запустить на конкретных ядрах
numactl --physcpubind=0,1,2,3 --membind=0 ./my_app

# Показать NUMA-топологию
numactl --hardware
```

#### 3. `cpuset` (cgroups) — изоляция ресурсов

Контроллер cgroups для привязки CPU + памяти NUMA.

```bash
# Создать cpuset cgroup
mkdir /sys/fs/cgroup/cpuset/isolated_group

# Задать ядра 2-3 и NUMA-узел 0
echo 2-3 > /sys/fs/cgroup/cpuset/isolated_group/cpuset.cpus
echo 0 > /sys/fs/cgroup/cpuset/isolated_group/cpuset.mems

# Включить cpuset для дочерних групп
echo 1 > /sys/fs/cgroup/cpuset/isolated_group/cgroup.subtree_control

# Переместить процесс в группу
echo <PID> > /sys/fs/cgroup/cpuset/isolated_group/cgroup.procs
```

#### 4. `sched_setaffinity()` — программный интерфейс

Системный вызов для управления привязкой из кода.

```c
#include <sched.h>

cpu_set_t mask;
CPU_ZERO(&mask);
CPU_SET(2, &mask);  // Ядро 2

sched_setaffinity(0, sizeof(mask), &mask);
```

## Практические сценарии

### 1. Виртуализация и контейнеризация

**Kubernetes:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: cpu-pinned-app
  annotations:
    # Запрос выделенных CPU (требует CPU Manager)
    cpuset: "0,1"
spec:
  containers:
  - name: app
    image: my-app
    resources:
      requests:
        cpu: "2"  # Гарантированные ядра
      limits:
        cpu: "2"
```

**Docker:**

```bash
# Запустить контейнер на ядрах 0-3
docker run --cpuset-cpus="0-3" my-app

# Запустить с ограничением CPU
docker run --cpus="1.5" my-app  # 1.5 ядра
```

### 2. Высокопроизводительные вычисления (HPC)

```bash
# Изолировать ядра 4-7 для вычислений
# В GRUB: isolcpus=4,5,6,7 nohz_full=4-7

# Запустить вычисления на изолированных ядрах
numactl --cpunodebind=3 --membind=3 ./hpc_application

# Привязать прерывания к ядрам 0-3
for irq in /proc/irq/*/smp_affinity_list; do
    echo "0-3" > $irq
done
```

### 3. Базы данных с низкой задержкой

```bash
# Выделить ядра 0-1 для СУБД, 2-7 для остальной системы
# Привязка PostgreSQL
taskset -c 0-1 pg_ctl start

# Привязка прерываний диска к ядрам 0-1
echo "0-1" > /proc/irq/$(cat /proc/interrupts | grep nvme | awk '{print $1}' | tr -d ':')/smp_affinity_list
```

### 4. Сетевые приложения (DPDK, NFV)

```bash
# Выделить ядра для обработки пакетов
# GRUB: isolcpus=2-7 nohz_full=2-7 rcu_nocbs=2-7

# Запустить DPDK-приложение
taskset -c 2-7 ./dpdk_app

# Привязать RX/TX очереди NIC к ядрам
ethtool -L eth0 combined 6
irqbalance --banlist=2,3,4,5,6,7
```

### 5. Проверка и мониторинг

```bash
# Проверить привязку процесса
taskset -p <PID>

# Показать привязку всех процессов
ps -eLo pid,psr,comm | head -20

# Мониторинг загрузки ядер
mpstat -P ALL 1

# Проверить миграции процессов
perf sched record
perf sched latency
```

## Дополнительная информация

### Связанные темы

- **[CPU Isolation](./kernel/cpu_isolation.md)** — kernel-level изоляция через параметры ядра
- **[cgroups cpuset](./cgroups.md#контроллеры-cgroups)** — контроллер cpuset
- **[NUMA](./memory/performance_tuning.md#numa-локальность-памяти)** — NUMA-архитектура и оптимизация
- **[Prерывания](./kernel/interrupts.md)** — IRQ affinity
- **[Планировщик](./kernel/scheduler.md)** — планировщик процессов Linux

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Процесс мигрирует между ядрами | Не установлена affinity | Использовать `taskset` или `cpuset` |
| Нет ожидаемого прироста производительности | Кэш сбрасывается при миграции | Проверить `ps -eLo pid,psr,comm` |
| NUMA-несбалансированная память | Процесс на одном узле, память на другом | Использовать `numactl --membind` |
| Прерывания на изолированных ядрах | IRQ affinity не настроена | Перенастроить `/proc/irq/*/smp_affinity` |

### Предостережения

- **Не изолируйте все ядра:** Оставьте хотя бы 1-2 ядра для системных задач
- **Мониторинг обязателен:** Используйте `mpstat`, `pidstat`, `perf` для контроля
- **Тестируйте нагрузку:** CPU pinning может ухудшить производительность при неправильной настройке
- **IRQ affinity:** Без настройки прерываний изоляция неполная

### Выбор конфигурации CPU: один мощный vs несколько менее мощных

| Аспект | **Один CPU (больше ядер)** | **Несколько CPU (меньше ядер каждый)** |
| :--- | :--- | :--- |
| **Стоимость** | Дешевле (1 сокет, меньше RAM-модулей) | Дороже (больше сокетов, больше RAM-слотов) |
| **Латентность памяти** | Ниже (единый контроллер памяти, нет NUMA) | Выше (NUMA, доступ к «чужой» памяти медленнее) |
| **Масштабируемость RAM** | Ограничена 1 каналом/контроллером | Выше (больше контроллеров и каналов памяти) |
| **Отказоустойчивость** | Одна точка отказа | При сбое одного CPU система может выжить |
| **Лицензирование ПО** | Дешевле (лицензии часто по сокетам) | Дороже (больше сокетов = больше лицензий) |
| **Производительность** | Лучше для латентно-чувствительных нагрузок | Лучше для пропускной способности (memory bandwidth) |
| **CPU pinning** | Проще (нет NUMA-нод) | Требует учёта NUMA-топологии |

**Рекомендации:**

- **Один CPU** — для баз данных (PostgreSQL, MySQL, Redis), виртуализации, Kubernetes-нод, latency-sensitive приложений (меньше латентность, проще эксплуатация, нет NUMA)
- **Несколько CPU** — для параллельных нагрузок (рендеринг, компиляция, batch), когда нужен максимальный объём RAM, при требованиях к отказоустойчивости

**NUMA-эффект в многопроцессорных системах:**

- Доступ к «своей» памяти: ~100 ns
- Доступ к «чужой» памяти (через QPI/UPI): ~150-200 ns

**Решение для NUMA:** Включить NUMA-aware scheduling (`numactl`, `taskset`) или использовать `interleave` mode для равномерного распределения памяти.

### Дополнительные ресурсы

- **man taskset:** [taskset(1)](https://man7.org/linux/man-pages/man1/taskset.1.html)
- **man numactl:** [numactl(1)](https://man7.org/linux/man-pages/man8/numactl.8.html)
- **Kernel CPU affinity:** [sched_setaffinity(2)](https://man7.org/linux/man-pages/man2/sched_setaffinity.2.html)
- **Kubernetes CPU Manager:** [CPU Management Policies](https://kubernetes.io/docs/tasks/administer-cluster/cpu-management-policies/)
