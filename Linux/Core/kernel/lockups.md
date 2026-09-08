# Зависания ядра: Soft Lockup, Hard Lockup и Hung Task

## Определения

**Lockup (зависание)** — критическое состояние ядра Linux, при котором один или несколько центральных процессоров (CPU) перестают отвечать на запросы планировщика, прерывания или системные события в течение длительного времени.

- **Soft Lockup (мягкое зависание)**: Состояние, при котором CPU зацикливается в контексте ядра (например, бесконечный цикл в драйвере) и не возвращает управление планировщику дольше порогового времени (обычно 20с). При этом аппаратные прерывания (Hard IRQ) продолжают обрабатываться.
- **Hard Lockup (жесткое зависание)**: Состояние, при котором CPU полностью перестает реагировать на любые события, включая прерывания. Обычно вызвано бесконечным циклом в критической секции с программно отключенными прерываниями.
- **Hung Task (зависшая задача)**: Процесс находится в состоянии «беспрерывного сна» (Uninterruptible Sleep, состояние `D`) дольше установленного порога (обычно 120с). Чаще всего это связано с ожиданием дискового ввода-вывода (I/O) или блокировками в файловой системе.
- **RCU CPU Stall (задержка RCU)**: Подсистема Read-Copy Update (RCU) не может завершить «льготный период» (grace period). Это часто является первым симптомом или причиной последующего Soft Lockup.

## Основные концепции

### Сторожевые таймеры (Watchdog)

Для автоматического обнаружения зависаний ядро использует механизмы Watchdog, которые проверяют «прогресс» выполнения задач на каждом ядре.

| Тип детектора | Механизм | Условие срабатывания |
| :--- | :--- | :--- |
| **Soft Lockup** | Поток `watchdog/N` (RT-приоритет) | Метка времени потока не обновлялась более `2 × watchdog_thresh`. |
| **Hard Lockup (NMI)** | Немаскируемые прерывания (NMI) | Счётчик прерываний CPU не инкрементировался в течение `watchdog_thresh`. Требует поддержки `perf`. |
| **Buddy Detector** | Процессоры-напарники (с ядра 6.3) | Соседний CPU проверяет инкремент `hrtimer` напарника. Альтернатива NMI для ARM64/Cloud. |
| **Hung Task** | Поток `khungtaskd` | Процесс в состоянии `D` не меняет состояние дольше `hung_task_timeout_secs`. |

#### Принцип работы Soft Lockup Detector

Поток `watchdog/N` (где N — номер CPU) создаётся ядром при загрузке с приоритетом SCHED_FIFO 99. Он циклически обновляет метку времени `watchdog_touch_ts` на каждом ядре. Если планировщик не управляет выполнять этот поток дольше `2 × watchdog_thresh`, ядро регистрирует Soft Lockup.

Важно: для работы детектора требуется хотя бы один поток с приоритетом RT на каждом ядре. В системах с отключённым `CONFIG_PREEMPT` или при нехватке ресурсов RT watchdog может не стартовать.

#### Принцип работы Hard Lockup Detector

Использует аппаратные NMI (Non-Maskable Interrupts) или парный механизм Buddy. NMI генерируется периодическим таймером (обычно через PMU — Performance Monitoring Unit). Если CPU не обрабатывает NMI в течение `watchdog_thresh`, фиксируется Hard Lockup.

На архитектуре x86/x86_64 NMI watchdog использует локальный APIC timer. На ARM64 может потребоваться парный режим Buddy, если PMU/NMI недоступны.

#### Принцип работы Hung Task Detector

Демон `khungtaskd` сканирует список задач каждые `hung_task_check_interval_secs` (по умолчанию 10с). Если задача находится в состоянии `D` дольше `hung_task_timeout_secs`, ядро выводит предупреждение. При `kernel.hung_task_panic=1` система вызывает панику.

### Причины возникновения

1.  **Ошибки в драйверах**: Длительное удержание спин-локов (spinlocks) или бесконечные циклы в контексте прерываний.
2.  **Дедлоки (Deadlocks)**: Ситуации взаимной блокировки ресурсов. См. [Механизмы синхронизации](./kernel_synchronization.md).
3.  **Starvation (голодание)**: Высокоприоритетные Real-Time задачи вытесняют критические потоки ядра (например, RCU kthreads).
4.  **Проблемы с I/O**: Неисправные накопители или перегруженные сетевые хранилища (NFS/iSCSI) приводят к массовым Hung Tasks.
5.  **Виртуализация**: Гипервизор может забирать ресурсы CPU надолго (stolen time), что ядро гостевой ОС интерпретирует как Lockup.
6.  **Реентерантность ядра**: Повторный вход в ядро через прерывания во время обработки исключений или page faults.
7.  **Сторожевые таймеры (watchdog) на уровне оборудования**: Аппаратный watchdog может вызвать перезагрузку, если программный watchdog не сработал вовремя.

## Практические сценарии

### Анализ журналов и дампов

При обнаружении зависания ядро выводит "Splat" (стек вызовов) в `dmesg`.

**Примеры сообщений:**
- `watchdog: BUG: soft lockup - CPU#1 stuck for 22s! [myservice:1234]`
- `INFO: task myservice:1234 blocked for more than 120 seconds.`
- `rcu: INFO: rcu_preempt detected stalls on CPUs/tasks:`

**Алгоритм действий:**
1.  **Поиск виновника:** В стеке вызовов найдите функцию, в которой CPU проводит больше всего времени.
2.  **Проверка прерываний:** Большое количество прерываний в секунду может указывать на "IRQ Storm".
3.  **Анализ состояния D:** Если процессов в состоянии `D` много, проверьте задержки диска через `iostat` или [PSI](./psi.md).

#### Команды для первичной диагностики

```bash
# Поиск soft lockup в текущем буфере dmesg
dmesg | grep -i "soft lockup\|hard lockup\|hung task\|rcu stall"

# Проверка количества процессов в состоянии D
ps -eo pid,stat,comm | grep '^.* D '

# Мониторинг потерь времени на steal (виртуализация)
mpstat -I SALL 1 5

# Статистика прерываний
cat /proc/interrupts | head -20

# Проверка загрузки CPU по ядрам
mpstat -P ALL 1 10
```

### Настройка через sysctl

Параметры детектора настраиваются через [**sysctl**](./sysctl.md).

| Параметр | Значение (Best Practice) | Описание |
| :--- | :--- | :--- |
| `kernel.watchdog_thresh` | `10` (до 20 в VM) | Базовый порог в секундах. |
| `kernel.softlockup_panic` | `1` | Вызывать панику (Kernel Panic) при Soft Lockup. |
| `kernel.hardlockup_panic` | `1` | Вызывать панику при Hard Lockup. |
| `kernel.hung_task_timeout_secs` | `120` | Таймаут для Hung Tasks (0 — выключить). |
| `kernel.hung_task_panic` | `0` | Паника при Hung Task (обычно не рекомендуется в Prod). |
| `kernel.hardlockup_all_cpu_backtrace` | `1` | Дамп стека ВСЕХ ядер при зависании одного. |
| `rcupdate.rcu_cpu_stall_timeout` | `20` | Таймаут для RCU Stall (секунды). |

#### Постоянное сохранение параметров

```bash
# /etc/sysctl.d/99-lockup-tuning.conf
kernel.watchdog_thresh = 10
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
kernel.hardlockup_all_cpu_backtrace = 1
kernel.hung_task_timeout_secs = 120
kernel.hung_task_panic = 0
rcupdate.rcu_cpu_stall_timeout = 20

# Применение
sysctl -p /etc/sysctl.d/99-lockup-tuning.conf
```

### Параметры загрузки ядра (kernel boot parameters)

```bash
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="... watchdog_thresh=10 nmi_watchdog=1 ..."

# Обновление grub
update-grub
```

| Параметр | Описание |
| :--- | :--- |
| `watchdog_thresh=N` | Устанавливает порог в секундах (аналогично sysctl, но на этапе загрузки). |
| `nmi_watchdog=1` | Включает NMI watchdog. На некоторых платформах может конфликтовать с perf. |
| `nmi_watchdog=0` | Отключает NMI watchdog. Ядро попытается использовать Buddy Detector. |
| `nowatchdog` | Полностью отключает все watchdog механизмы. Не рекомендуется для production. |
| `hung_task_panic=1` | Вызывать панику при Hung Task. |

### Специфика для ядер 6.x

*   **Buddy Hardlockup Detector:** Если аппаратный NMI недоступен (многие ARM64 сервера и VPS), Buddy Detector становится единственным способом обнаружить жесткое зависание.
    *   Включение: `kernel.nmi_watchdog=0` (если NMI не работает), ядро автоматически переключится на Buddy при наличии поддержки.
*   **Expedited RCU Stalls:** В высокопроизводительных системах (RT/HFT) можно использовать `rcupdate.rcu_cpu_stall_timeout_ms` для миллисекундной точности (вместо секунд).

## Глубокая отладка (Post-Mortem)

Если система уходит в панику при зависании, для анализа причин используйте **Kdump** и утилиту **crash**:

1.  **Сбор дампа:** При панике ядро сохраняет файл `vmcore`.
2.  **Анализ через crash:**
    ```bash
    # Загрузка дампа
    crash vmlinux vmcore
    
    # Показать логи dmesg из дампа
    crash> log
    
    # Показать стеки вызовов всех активных задач
    crash> bt -a
    ```

### Настройка Kdump для анализа lockup-ов

```bash
# Установка (RHEL/CentOS/Fedora)
yum install kexec-tools crash

# Включение службы
systemctl enable --now kdump

# Проверка конфигурации
cat /etc/kdump.conf
# Пример содержимого:
# path /var/crash
# core_collector makedumpfile -l --message-level 1 -d 31

# Проверка работоспособности
kdumpctl status
# → Kdump is operational

# После паники дамп будет в /var/crash/
# Анализ:
crash /usr/lib/debug/lib/modules/$(uname -r)/vmlinux /var/crash/127.0.0.1-<date>/vmcore
```

### Анализ RCU Stall с помощью crash

```bash
# Внутри crash
crash> rcu
# Покажет информацию о grace periods и stalled CPUs

crash> rcu.gp_snap
# Показать snapshot RCU grace period

# Поиск задач, блокирующих RCU
crash> foreach bt
```

## Мониторинг и proactive alerting

### Метрики для мониторинга

```bash
# Проверка количества watchdog-срабатываний через syslog
journalctl -k | grep -c "watchdog: BUG: soft lockup"

# Мониторинг hung tasks
journalctl -k | grep -c "INFO: task.*blocked for more than"

# Статистика RCU stall
grep -c "rcu: INFO: rcu_preempt detected stalls" /var/log/kern.log
```

### Prometheus Alerting Rules (пример)

```yaml
# /etc/prometheus/rules/kernel_lockups.yaml
groups:
  - name: kernel_lockups
    rules:
      - alert: KernelSoftLockup
        expr: rate(node_kernel_softlockup_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Soft Lockup detected on {{ $labels.instance }}"
          description: "CPU {{ $labels.cpu }} stuck for > {{ $labels.threshold }}s"

      - alert: KernelHungTask
        expr: rate(node_kernel_hung_task_total[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Hung Task detected on {{ $labels.instance }}"
          description: "Task {{ $labels.task }} blocked for > {{ $labels.timeout }}s"

      - alert: RCUStallDetected
        expr: rate(node_kernel_rcu_stall_total[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "RCU Stall on {{ $labels.instance }}"
          description: "RCU grace period exceeded on CPU {{ $labels.cpu }}"
```

> **Примечание:** Метрики `node_kernel_softlockup_total`, `node_kernel_hung_task_total`, `node_kernel_rcu_stall_total` доступны через node_exporter с опцией `--collector.softnet`, `--collector.ksmd` или через текстовый файл exporter с парсингом `/proc` и `dmesg`.

### Логирование и централизованный сбор

```bash
# Настройка journald для сохранения kernel ring buffer
# /etc/systemd/journald.conf
Storage=persistent
MaxRetentionSec=30day

# Перезапуск
systemctl restart systemd-journald

# Экспорт в ELK/Graylog
# Добавьте в filebeat/config:
# - /var/log/kern.log
# - /var/log/messages
# Фильтр: "soft lockup" OR "hard lockup" OR "hung task" OR "rcu: INFO: rcu"
```

## Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `soft lockup` на CPU | Бесконечный цикл в ядре, драйвер, RT-прерывания | Обновите драйвер/ядро; проверяйте `dmesg` на предмет функции-виновника; используйте `perf top -g` для профилирования |
| `hard lockup` | NMI не срабатывает, аппаратная проблема | Проверьте `dmesg | grep -i nmi`; убедитесь, что `nmi_watchdog=1` в параметрах ядра; на ARM64 используйте Buddy Detector |
| `hung task` в состоянии D | Проблемы с диском, NFS, iSCSI, FS | Проверьте `iostat -x 1`; `cat /proc/$(pid)/stack` для определения точки блокировки; проверьте SMART-статус дисков |
| `rcu: INFO: rcu_preempt detected stalls` | Длительная операция в контексте ядра | Увеличьте `rcupdate.rcu_cpu_stall_timeout`; проверьте `dmesg` на предмет функции-виновника; проверьте нагрузку на CPU |
| Watchdog не стартует | Нет RT-приоритета, CONFIG_PREEMPT выключен | Проверьте `dmesg | grep -i watchdog`; убедитесь, что `CONFIG_PREEMPT` включен; проверьте `cgroups` и `cpuset` |
| Частые ложные срабатывания в VM | Steal time, пере расписание | Увеличьте `kernel.watchdog_thresh` до 20-30; настройте `perf`; проверьте гипервизор |

### Диагностика с помощью perf

```bash
# Установка perf
apt-get install linux-tools-$(uname -r) linux-tools-common

# Профилирование на всех ядрах
perf top -g -a -- sleep 30

# Поиск функции, вызывающей lockup
perf record -g -a -- sleep 60
perf report

# Анализ конкретного процесса
perf top -p <pid>
```

### Диагностика с помощью ftrace

```bash
# Включение tracer
echo 1 > /sys/kernel/debug/tracing/tracing_on
echo function > /sys/kernel/debug/tracing/current_tracer

# Фильтр по проблемной функции (если известна)
echo <function_name> > /sys/kernel/debug/tracing/set_ftrace_filter

# Чтение трасс
cat /sys/kernel/debug/tracing/trace

# Отключение
echo 0 > /sys/kernel/debug/tracing/tracing_on
```

### Проверка состояния через /proc

```bash
# Статус watchdog
cat /proc/sys/kernel/watchdog_thresh
cat /proc/sys/kernel/nmi_watchdog

# Активные watchdog-потоки
ps -eo pid,rtprio,comm | grep watchdog

# Статистика hung tasks
cat /proc/sys/kernel/hung_task_timeout_secs
cat /proc/sys/kernel/hung_task_check_interval_secs

# RCU stall threshold
cat /proc/sys/rcu/rcu_cpu_stall_timeout
```

## Профили настройки для рабочих нагрузок

### Базовая конфигурация (Production Server)

```bash
# /etc/sysctl.d/99-lockup-tuning.conf
kernel.watchdog_thresh = 10
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
kernel.hardlockup_all_cpu_backtrace = 1
kernel.hung_task_timeout_secs = 120
kernel.hung_task_panic = 0
kernel.hung_task_check_interval_secs = 10
rcupdate.rcu_cpu_stall_timeout = 20
```

### Конфигурация для виртуализации (KVM/VMware)

```bash
# Увеличиваем пороги из-за возможного stolen time
kernel.watchdog_thresh = 20
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
kernel.hung_task_timeout_secs = 180
rcupdate.rcu_cpu_stall_timeout = 30
```

### Конфигурация для высоконагруженных RT-систем

```bash
# Минимальные пороги, но с паникой для быстрого failover
kernel.watchdog_thresh = 5
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
kernel.hung_task_timeout_secs = 60
rcupdate.rcu_cpu_stall_timeout = 10
```

### Конфигурация для отладки (Development/Staging)

```bash
# Отключаем панику, увеличиваем таймауты для сбора диагностики
kernel.watchdog_thresh = 30
kernel.softlockup_panic = 0
kernel.hardlockup_panic = 0
kernel.hardlockup_all_cpu_backtrace = 1
kernel.hung_task_timeout_secs = 300
kernel.hung_task_panic = 0
rcupdate.rcu_cpu_stall_timeout = 60
```

## Взаимодействие с cgroup и systemd

### Влияние cgroup на watchdog

Watchdog-потоки (`watchdog/N`) привязаны к конкретным CPU и не управляются через cgroup напрямую. Однако:

- **cpuset**: Если ядро запрещено планировать на определённых CPU через `cpuset.cpus`, watchdog на этих ядрах может не запуститься.
- **CPU affinity**: Проверяйте affinity watchdog-потоков:
  ```bash
  # Показать affinity
  taskset -pc $(pgrep watchdog | head -1)
  ```

### systemd и watchdog

Службы systemd могут использовать внутренний watchdog механизм:

```ini
# /etc/systemd/system/myapp.service
[Service]
ExecStart=/usr/bin/myapp
WatchdogSec=30
Restart=on-failure
RestartSec=5

# Приложение должно периодически отправлять:
# sd_notify("WATCHDOG=1")
# или
# sd_notify("WATCHDOG=trigger")
```

## Валидация изменений

```bash
# Проверка текущих значений
sysctl kernel.watchdog_thresh kernel.softlockup_panic kernel.hung_task_timeout_secs

# Проверка после применения
sysctl -p /etc/sysctl.d/99-lockup-tuning.conf

# Проверка загрузки модулей (если используется softdog)
lsmod | grep softdog

# Проверка NMI статуса
dmesg | grep -i nmi

# Проверка активных watchdog-потоков
ps -eo pid,rtprio,comm | grep watchdog

# Сбор метрик
watch -n1 'cat /proc/softirqs | head -5'

# Имитация нагрузки для проверки
stress --cpu $(nproc) --timeout 60
```

## Дополнительная информация

### Связанные темы

- **Критическая ошибка:** [Kernel Panic](./kernel_panic.md) — механизмы фатального сбоя.
- **Диагностика давления:** [PSI (Pressure Stall Information)](./psi.md) — как отличить I/O задержки от зависаний.
- **Синхронизация:** [Механизмы синхронизации](./kernel_synchronization.md) — причины Deadlocks и Stall-ов.
- **Настройка:** [sysctl](./sysctl.md) — детальное описание настройки параметров.
- **Диагностика перезагрузки:** [Reboot Troubleshooting](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) — анализ аварийных перезагрузок, включая Watchdog Reset.

### Полезные ссылки

- [Linux Kernel Documentation: Lockup Detectors](https://www.kernel.org/doc/html/latest/admin-guide/lockup-watchdogs.html)
- [RCU Stall Detector Documentation](https://www.kernel.org/doc/Documentation/RCU/stallwarn.txt)
- [Kdump Documentation](https://docs.kernel.org/kdump/)
