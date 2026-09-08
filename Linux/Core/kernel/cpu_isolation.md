# Изоляция CPU

## Определения

**Изоляция CPU (CPU Isolation)** — комплекс мер по резервированию ядер процессора для эксклюзивного выполнения критических задач. Цель — минимизация **jitter** (дрожания задержек), вызванного вмешательством ядра (прерывания, планировщик, фоновые потоки).

**Housekeeping CPUs** — ядра, выделенные для обслуживания системных нужд (обработка прерываний, RCU-коллбэки, системные потоки), чтобы освободить изолированные ядра от фонового шума.

**Adaptive Tickless (`nohz_full`)** — режим работы ядра, при котором системный таймер (тики) отключается на ядре, если на нем выполняется ровно один процесс в пользовательском пространстве.

**cgroup v2 Partitions** — механизм динамического разделения ядер на группы, позволяющий на лету переводить ядра в режим `isolated` с автоматическим отключением балансировки нагрузки планировщиком.

**Exclusive CPUs (`cpuset.cpus.exclusive`)** — резервирование ядер через cgroup, при котором ядра удаляются из общего планировщика для всех групп, кроме текущей.

---

## Предварительные требования

### Аппаратное обеспечение
- x86_64 (Intel VT-d / AMD-Vi не требуются для базовой изоляции, но нужны для SR-IOV)
- Поддержка NUMA (рекомендуется для многосокетных систем)
- BIOS: отключение энергосберегающих режимов (C-states, P-states), отключение SMT/Hyper-Threading для latency-critical workloads

### Программное обеспечение
- Linux kernel 5.15+ (для `cpuset.cpus.partition`); kernel 6.1+ рекомендуется (PSI для IRQ)
- systemd 249+ (для `systemd.cpu_affinity` и корректной работы cpuset)
- `irqbalance` отключен или настроен с banlist для изолированных ядер

---

## Основные концепции

### Источники системного шума (Jitter)

Даже при отсутствии других задач в Userspace, ядро может прерывать выполнение процесса:
1.  **Аппаратные прерывания (IRQ):** Обработка сетевых пакетов или дисковых операций. Решается через `irqaffinity` и `smp_affinity`.
2.  **Программные прерывания (Softirqs):** Потоки `ksoftirqd`, выполняющие отложенную обработку (например, сетевой стек).
3.  **Потоки ядра (kworkers):** Системные задачи (сброс кэша, управление питанием). Подавляются через `workqueue.unbound_cpus`.
4.  **RCU Callbacks:** Очистка структур данных ядра. Переносятся через `rcu_nocbs`.
5.  **Системные таймеры (Timer IRQ):** Периодические тики планировщика. Минимизируются через `nohz_full` и `nohz=off`.
6.  **Power Management:** Частотная шкала (DVFS) и переходы в C-states добавляют недетерминизм. Решаются через `intel_pstate=disable` + `performance` governor.

### Архитектура изоляции (2024–2026)

#### Статическая конфигурация (Boot-time)
Использование параметров загрузки в GRUB обеспечивает наиболее глубокую изоляцию "из коробки":
- **`isolcpus=managed_irq,<cpus>`**: Удаляет ядра из общего планировщика и (опционально) переносит управляемые прерывания.
- **`nohz_full=<cpus>`**: Минимизирует прерывания таймера.
- **`rcu_nocbs=<cpus>`**: Делегирует выполнение RCU-коллбэков на Housekeeping-ядра.
- **`irqaffinity=<cpus>`**: Устанавливает маску по умолчанию для нераспределенных IRQ.
- **`workqueue.unbound_cpus=<cpus>`**: Ограничивает запуск unbound kworkers на указанных ядрах.
- **`systemd.cpu_affinity=<cpus>`**: Привязывает системные сервисы (PID 1 и потомки) к housekeeping-ядрам.
- **`nosmt`**: Отключает гиперпоточность для исключения contention на исполнительных блоках.
- **`intel_pstate=disable` / `amd_pstate=passive`**: Переключает CPU frequency scaling в passive mode с фиксированной частотой.
- **`nohz=off`**: Принудительно включает тики на всех ядрах (для совместимости со старым ПО).

#### Динамическая изоляция (Cgroup v2)
Современный метод, позволяющий изменять границы изоляции без перезагрузки:
- Контроллер `cpuset` при установке `cpuset.cpus.partition` в значение `isolated` создает "раздел", ядра которого исключаются из домена балансировки (`sched_domain`).
- **Важно:** Для эффективной работы требует, чтобы Housekeeping ядра были явно определены в родительской группе.

### Детальный разбор параметров загрузки

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `isolcpus=managed_irq,<cpus>` | Исключает ядра из общего планировщика. `managed_irq` переносит управляемые IRQ на housekeeping. | Использовать `managed_irq` для сетевых workloads. |
| `nohz_full=<cpus>` | Отключает системный тик на указанных ядрах. | Требует, чтобы на изолированных ядрах была ровно одна задача. |
| `rcu_nocbs=<cpus>` | Переносит RCU-коллбэки с изолированных ядер. | Обязателен при использовании `nohz_full`. |
| `irqaffinity=<cpus>` | Маска по умолчанию для `/proc/irq/default_smp_affinity`. | Устанавливается на housekeeping-ядра. |
| `workqueue.unbound_cpus=<cpus>` | Ограничивает запуск unbound kworkers. | Должен совпадать с housekeeping-ядрами. |
| `systemd.cpu_affinity=<cpus>` | Жестко привязывает systemd и его потомков. | Дополнительная страховка против "убегающих" сервисов. |
| `nosmt` | Отключает гиперпоточность (SMT). | Обязателен для ultra-low latency. |
| `intel_pstate=disable` | Переключает Intel frequency scaling в passive mode. | Позволяет установить `performance` governor. |
| `amd_pstate=passive` | Аналог для AMD. | Для AMD EPYC / Ryzen. |
| `skew_tick=1` | Распределяет тики таймера между ядрами. | Рекомендуется для SMP-систем > 4 ядер. |

### Подавление фоновых сервисов и таймеров

На уровне userspace критично отключить или ограничить фоновые процессы, способные создавать шум на изолированных ядрах:

```bash
# 1. Отключение irqbalance (если используется ручная привязка)
systemctl mask irqbalance

# 2. Отключение thermald / power-profiles-daemon (энергополитики)
systemctl mask thermald power-profiles-daemon

# 3. Отключение служб логирования, способных создавать прерывания
systemctl mask systemd-journald-audit.socket

# 4. Ограничение periodic timers для systemd
# /etc/systemd/system.conf
# TimerSlackNSec=0
# DefaultTimerAccuracySec=1s

# 5. Проверка pending timers на изолированном ядре
cat /proc/timer_list | grep -A 20 "cpu: <N>"
```

---

## Практические сценарии

### Настройка максимальной изоляции (GRUB)

Пример для 16-ядерной системы, где ядра 2-15 выделены под Low-Latency нагрузку:

```text
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="... isolcpus=managed_irq,2-15 nohz_full=2-15 rcu_nocbs=2-15 irqaffinity=0,1 workqueue.unbound_cpus=0,1 systemd.cpu_affinity=0,1 nosmt intel_pstate=disable skew_tick=1"
```
*Примечание: `workqueue.unbound_cpus` гарантирует, что системные kworkers не будут запускаться на изолированных ядрах.*

Применение:
```bash
sudo update-grub
sudo reboot
```

Проверка:
```bash
cat /sys/devices/system/cpu/isolated
# → 2-15

cat /sys/devices/system/cpu/present
# → 0-15
```

### Динамическая изоляция через cgroup v2

Алгоритм перевода ядер в изолированный режим вручную:

```bash
# 1. Создание группы
sudo mkdir /sys/fs/cgroup/high-priority

# 2. Назначение ядер и NUMA-ноды (опционально)
echo 2-15 | sudo tee /sys/fs/cgroup/high-priority/cpuset.cpus
echo 0 | sudo tee /sys/fs/cgroup/high-priority/cpuset.mems

# 3. Активация изолированного раздела
echo isolated | sudo tee /sys/fs/cgroup/high-priority/cpuset.cpus.partition
# -> Проверка: cat cpuset.cpus.partition должен вернуть 'isolated'

# 4. Перенос процесса в группу
echo <PID> | sudo tee /sys/fs/cgroup/high-priority/cgroup.procs
```

**Важно:** При использовании `isolated` родительская группа (`/sys/fs/cgroup/cpuset`) не должна иметь этих ядер в `cpuset.cpus`, иначе планировщик будет игнорировать изоляцию.

### Подавление ksoftirqd и прерываний

Даже на изолированных ядрах могут возникать Softirqs. Для их минимизации:
1.  **Перенос IRQ:** `echo 0003 > /proc/irq/default_smp_affinity` (битовая маска для ядер 0,1).
2.  **Threaded IRQs:** Запуск ядра с параметром `threadirqs` позволяет управлять приоритетами обработчиков прерываний как обычных процессов через `chrt`.

```bash
# Отключение irqbalance
sudo systemctl stop irqbalance
sudo systemctl mask irqbalance

# Привязка всех IRQ сетевой карты к housekeeping-ядрам
for irq in $(grep eth0 /proc/interrupts | awk '{print $1}' | tr -d ':'); do
    echo 3 | sudo tee /proc/irq/$irq/smp_affinity
done

# Проверка отсутствия прерываний на изолированных ядрах
watch -n 1 "cat /proc/interrupts | grep -E 'CPU[2-9]|CPU1[0-5]'"
```

### Изоляция для баз данных и stateful-сервисов

Для СУБД (PostgreSQL, MySQL) и консенсусных систем (etcd, Consul):
1.  Выделите отдельные housekeeping-ядра (0,1) для OS и IO-потоков.
2.  Выделите изолированные ядра (2-7) для foreground-обработки транзакций.
3.  Отключите NUMA balancing (`echo 0 > /proc/sys/kernel/numa_balancing`).
4.  Установите `performance` governor.

```bash
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="... isolcpus=managed_irq,2-7 nohz_full=2-7 rcu_nocbs=2-7 irqaffinity=0,1 workqueue.unbound_cpus=0,1 systemd.cpu_affinity=0,1 nosmt intel_pstate=disable"

# sysctl для NUMA
echo 0 | sudo tee /proc/sys/kernel/numa_balancing
echo 0 | sudo tee /proc/sys/kernel/numa_zoned_reclaim_order
```

### Изоляция для высокопроизводительных сетевых приложений

Для DPDK, сетевых шлюзов, L7-balancer'ов:
1.  Используйте `isolcpus=managed_irq` для автоматического переноса IRQ.
2.  Привяжите все очереди RX/TX NIC к изолированным ядрам через `smp_affinity_list`.
3.  Отключите `irqbalance` и `systemd-udevd` (если не нужен).

```bash
# Проверка NUMA-ноды NIC
cat /sys/bus/pci/devices/0000:03:00.0/numa_node

# Привязка всех IRQ устройства к изолированным ядрам той же NUMA-ноды
for irq in $(grep 0000:03:00 /proc/interrupts | awk '{print $1}' | tr -d ':'); do
    echo e | sudo tee /proc/irq/$irq/smp_affinity
done
```

---

## Валидация и мониторинг

### Проверка «чистоты» ядер

Для анализа того, что именно прерывает вашу задачу, используйте `ftrace` или специализированные инструменты:

```bash
# Просмотр статистики прерываний по ядрам
watch -n 1 "cat /proc/interrupts"

# Поиск "убежавших" потоков ядра
ps -eLo psr,tid,cls,rtprio,comm | grep -E "^ *[2-9]|^ *1[0-5]"

# Проверка давления прерываний (ядро 6.1+)
cat /proc/pressure/irq
# some avg10=2.50 avg60=1.80 avg300=1.20 total=12345678
# avg10=2.50 означает 2.5% времени на IRQ — допустимо для latency-sensitive
```

### Метрики и алерты

| Метрика | Порог | Команда |
| :--- | :--- | :--- |
| PSI IRQ `some avg10` | > 10-15% | `cat /proc/pressure/irq` |
| `si%` (SoftIRQ) | > 5% на изолированном ядре | `mpstat -P ALL 1` |
| Context switches (cs) | Рост > 10K/s на ядро | `pidstat -w 1` |
| RCU callbacks | > 1000/s на housekeeping | `cat /proc/stat | grep rcua` |

### Изоляция в Kubernetes (CPU Manager)

При использовании `Static Policy` в Kubelet, Kubernetes автоматически применяет `cpuset` для контейнеров класса `Guaranteed`. Однако для полной изоляции (включая `nohz_full`) узлы должны быть предварительно настроены через параметры GRUB.

```yaml
# Pod манифест для Guaranteed QoS
spec:
  containers:
  - name: latency-sensitive
    image: my-app:latest
    resources:
      limits:
        cpu: "4"
        memory: "4Gi"
      requests:
        cpu: "4"
        memory: "4Gi"
```

---

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `isolcpus` не применяется | systemd/docker переопределяют cpuset в родительской группе | Проверьте `/sys/fs/cgroup/cpuset/cpuset.cpus` на наличие изолированных ядер в родителе. |
| Высокий `si%` на изолированном ядре | IRQ affinity не настроена или `irqbalance` перезапустился | Отключите `irqbalance`; проверьте `/proc/irq/default_smp_affinity`. |
| kworkers на изолированных ядрах | `workqueue.unbound_cpus` не установлен или устарел | Добавьте параметр GRUB; проверьте `cat /proc/*/task/*/status | grep Cpus_allowed_list`. |
| Планировщик ставит задачи на изолированные ядра | Используется `sched_setaffinity` без учета `isolcpus`, или ядра не в `isolated` cgroup | Проверьте `isolcpus` через `cat /sys/devices/system/cpu/isolated`. |
| Пропускная способность падает после `nosmt` | Приложение не поддерживает запуск на одном физическом ядре | Откатите `nosmt`; проверьте топологию через `lscpu -e`. |
| P99 latency растет под нагрузкой | NUMA-несоответствие или cache-line false sharing | Проверьте `numactl --hardware`; используйте `perf c2c`. |
| `rcu_nocbs` не работает | Ядро собрано без `CONFIG_RCU_NOCB_CPU` | Проверьте `grep CONFIG_RCU_NOCB_CPU /boot/config-$(uname -r)`. |

---

## Рекомендации

- **Housekeeping ядра:** Всегда резервируйте минимум 2 ядра (0,1) для housekeeping на системах с < 8 ядрами, минимум 4 ядра на больших системах.
- **NUMA-локальность:** Привязывайте IRQ и процессы к ядрам той же NUMA-ноды, что и устройство/память.
- **Измеряйте, а не гадайте:** Используйте `cyclictest` или `rt-tests` для валидации P99/Max latency до и после изоляции.
- **Вероятностная проверка:** Запускайте нагрузку 10–30 минут; краткие тесты (< 1 мин) могут не захватить периодические события (TPS, trim).
- **Откатываемость:** Сохраняйте исходный `GRUB_CMDLINE_LINUX_DEFAULT` в VCS; изоляция может сломать совместимость с некоторыми драйверами.
- **SMT:** Для latency-critical workloads отключайте SMT в BIOS. Если это невозможно, не размещайте критичные потоки на sibling-ядрах.
- **CPU Governor:** Используйте `performance` governor; исключите `ondemand` и `conservative`.
- **Системные сервисы:** Маскируйте `irqbalance`, `thermald`, `power-profiles-daemon` только после проверки влияния на температуру и стабильность.

---

## Дополнительная информация

### Связанные темы

- **Привязка процессов:** [CPU Pinning](../cpu_pinning.md) — инструменты `taskset` и привязка на уровне приложений.
- **Контрольные группы:** [Cgroups v2](../cgroups.md) — иерархическое управление ресурсами.
- **Прерывания:** [Обработка IRQ](./interrupts.md) — детальный разбор механизмов прерываний.
- **Вытесняющая многозадачность ядра:** [Kernel Preemption](./preemption.md) — влияние PREEMPT_RT и EEVDF на задержки.
- **Диагностика CPU:** [CPU Info](../../../Linux/Diagnostics/Hardware/cpu_info.md) — топология, кэши, флаги.
