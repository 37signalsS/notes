# Поиск и устранение неисправностей с dmesg

## Определения

**Диагностика (Troubleshooting) с помощью dmesg** — это методология выявления первопричин системных сбоев путем интерпретации сообщений кольцевого буфера ядра. Этот процесс позволяет локализовать ошибки в аппаратном обеспечении (CPU, RAM, PCI-E), драйверах (Modules) или подсистемах управления ресурсами (Memory Management, Scheduler).

---

## Базовые концепции

### Критические структуры данных

При анализе вывода `dmesg` необходимо понимать структуру сложных отчетов об ошибках:

*   **Call Trace:** Стек вызовов функций, предшествовавших сбою. Читается снизу вверх (от инициатора к месту падения). Помогает определить конкретный модуль или системный вызов, вызвавший исключение.
*   **Kernel Oops:** Серьезное нарушение, после которого ядро может попытаться продолжить работу (в отличие от Panic), но стабильность системы более не гарантируется.
*   **Machine Check Exception (MCE):** Аппаратная ошибка, обнаруженная процессором. Требует расшифровки через внешние утилиты (`mcelog` или `rasdaemon`).

### Состояние «загрязнения» ядра (Kernel Taint)

Флаги **Tainted** указывают на факторы, которые могут влиять на поведение ядра и осложнять отладку разработчиками. Ищите строку `Tainted: ...` в сообщениях Oops или Panic.

| Флаг | Значение | Описание |
| :--- | :--- | :--- |
| `P` | Proprietary | Загружен проприетарный модуль (например, NVIDIA). |
| `F` | Force | Модуль загружен принудительно (игнорируя версии). |
| `O` | Out-of-tree | Модуль скомпилирован вне дерева исходников ядра. |
| `E` | Unsigned | Модуль не имеет валидной цифровой подписи. |

### Инструменты расшифровки Call Trace

Адреса в `Call Trace` (например, `[<ffffffff...>]`) бессмысленны без символов. Для их расшифровки используются:

*   **`addr2line`** (из пакета `binutils`): Преобразует адрес в файл и строку исходного кода.
    ```bash
    # Пример: расшифровка адреса из Call Trace
    addr2line -e /usr/lib/debug/boot/vmlinux-$(uname -r) ffffffff81000000
    # → /usr/src/linux/kernel/pid.c:123
    ```
*   **`scripts/decodecode`** из дерева исходников ядра: Автоматически расшифровывает весь блок `Call Trace` из файла или stdin.
*   **`crash`**: Интерактивный анализатор дампов ядра (работает с `vmcore` от kdump или live `/proc/kcore`). Команда `bt` выводит backtrace с символьными именами.

### Параметр загрузки `loglevel`

Параметр ядра `loglevel=N` (0–7) задает минимальный уровень сообщений, которые ядро выведет в кольцевой буфер **во время загрузки**:

*   `0` (KERN_EMERG) — только аварийные сообщения.
*   `4` (KERN_WARNING) — стандарт для production; исключает информационный шум.
*   `7` (KERN_DEBUG) — максимальная детализация, полезно при отладке драйверов.

**Взаимодействие с `dmesg -n`:** `loglevel` управляет записью в буфер, а `dmesg -n` — только выводом на консоль. Для полного отключения debug-сообщений используйте оба: `loglevel=5` в GRUB + `dmesg -n 5`.

---

## Практические сценарии

### Диагностика программных сбоев

#### Интерпретация Call Trace

Если в `dmesg` виден блок `Call Trace:`, обратите внимание на:
1.  **RIP/PC (Instruction Pointer):** Адрес инструкции, на которой произошел сбой.
2.  **Символьные имена:** Например, `[<ffffffff...>] ? pci_mmcfg_read+0x...`. Это указывает на функцию и смещение в коде.
3.  **Модуль:** Если ошибка произошла в загружаемом модуле, его имя будет в квадратных скобках (например, `[ext4]`).

**Практическое расшифрование:** Для перевода адресов в читаемый исходный код используйте `addr2line` или `crash`. Пример:
```bash
# Расшифровка одного адреса
addr2line -e /usr/lib/debug/boot/vmlinux-$(uname -r) ffffffff81000000

# Или через crash для всего дампа
sudo crash /usr/lib/debug/boot/vmlinux-$(uname -r) /proc/kcore
crash> bt
```

#### Диагностика модулей на Rust

В ядрах 6.x/7.x ошибки в Rust-драйверах часто сопровождаются сообщениями `panic!` с указанием файла и строки исходного кода крейта. В отличие от C-модулей, они редко приводят к повреждению памяти, но могут вызывать логические остановки подсистем.

#### Ошибки Intel FRED

В новых архитектурах Intel (6.x+) ищите записи `FRED: ... error`. Это указывает на сбои в новом механизме доставки событий, что критично для отладки виртуализации и прерываний.

---

### Диагностика аппаратных сбоев

#### Ошибки шины PCI-E (AER)

**AER (Advanced Error Reporting)** логирует сбои на шине.
*   **Симптомы:** Записи `pcieport ...: AER: ... error`.
*   **Анализ:** Указывает на плохой контакт, проблемы с питанием устройства или неисправность контроллера.
*   **Восстановление:** Для устройства в состоянии `AER: Fatal` выполните:
    ```bash
    # 1. Определите идентификатор устройства
    lspci | grep -i " malfunctioning"
    # → 01:00.0 NVIDIA Device 1b80

    # 2. Сбросите устройство
    echo 1 | sudo tee /sys/bus/pci/devices/0000:01:00.0/reset

    # 3. Перезагрузите драйвер (если нужно)
    sudo modprobe -r nvidia && sudo modprobe nvidia

    # 4. Если повторяется — проверьте физический слот, кабель, питание
    ```
*   **Подробнее:** [**Диагностика NVMe через AER и Reset**](../../Hardware/nvme-errors-diagnostics.md)

#### Ошибки памяти (MCE / EDAC)

*   **MCE (Machine Check):** Записи вида `CPU 0: Machine Check Exception: ...`.
*   **EDAC:** Сообщения `EDAC MC0: CE row 0, channel 0, label "CPU_SrcID#0_...`.
*   **Интерпретация:** `CE` (Correctable Error) — исправлено; `UE` (Uncorrectable Error) — фатальный сбой RAM, требует замены.

**Практическая диагностика:**
```bash
# Проверка состояния ECC через edac-util (требует пакет edac-util)
edac-util -v
# → edac-util: CE count on MC0 (RAM idx 0): 0
# → edac-util: UE count on MC0 (RAM idx 0): 1  ← фатальный сбой

# Просмотр детальной информации о модулях памяти
edac-util -s
# → Bus 0, Device 0, Function 0: 8192 MB (4096 bits wide, ECC enabled)

# Поиск MCE через rasdaemon (альтернатива mcelog)
ras-mc-ctl --summary
```
**Действие при UE:** Определите физический модуль по `row`/`channel` из dmesg → найдите слот через `dmidecode -t memory` → замените модуль. Для Dell/HP используйте `ipmitool sdr type memory` для корреляции с физическими слотами.

#### Сбои дисков и SCSI Sense Codes

При ошибках ввода-вывода `dmesg` выводит коды ответов контроллера:
`sd 0:0:0:0: [sda] Sense Key : Medium Error [current]`
*   **Действие:** Проверьте `smartctl` и логи `dmesg` на наличие `reset_link` или `hard resetting link`.
*   **Источник:** [**Диагностика дисков через smartctl**](../../Hardware/smartctl/index.md)

#### Анализ slab corruption

Повреждение slab SLUB/SLAB указывает на повреждение памяти в драйвере или модуле ядра. В `dmesg` появляются сообщения `BUG:` и `INFO:` с дампами объектов.

```bash
# Поиск повреждений slab
dmesg -T | grep -iE "slab|corruption|bug:|BUG:"
# → BUG kmalloc-2k: Object at 0xffff888000123450 not last freed
```

Для детального анализа: [**Slab Allocator в Linux**](../../../Core/memory/slab_allocator.md)

---

### Интерпретация системных лимитов

#### Ratelimit (`__ratelimit`)

Фраза `__ratelimit: ... msgs suppressed` говорит о том, что подсистема `printk` заблокировала избыточный вывод.
*   **Действие:** Проверьте события непосредственно перед этой записью — именно они вызвали «шторм» сообщений.
*   **Временное отключение для отладки:** Добавьте `printk.devkmsg=ratelimit off` в параметры загрузки ядра (GRUB), чтобы видеть все сообщения во время воспроизведения проблемы.
*   **Постоянное увеличение лимита:** `echo 0 > /proc/sys/kernel/printk_devkmsg` (требует прав root).

#### OOM Killer и нехватка ресурсов

Когда ядро убивает процесс по памяти, в `dmesg` появляется детальный дамп состояния памяти.
*   **Паттерн для поиска:** `dmesg | grep -i oom-killer`.
*   **Различие типов OOM:**
    *   `oom-kill:constraint=CONSTRAINT_MEMCG` — ограничение по cgroup (контейнер).
    *   `oom-kill:constraint=CONSTRAINT_SYS` — глобальное исчерпание всей физической памяти.
*   **Источник:** [**Механизм OOM Killer**](../../../Core/processes/oom_killer_mechanism.md)

### Диагностика файловых систем

Ошибки ввода-вывода, указанные в `dmesg`, часто являются симптомом проблем с диском, а не самим сбоем файловой системы. Методология:

```bash
# 1. Анализ логов ядра
dmesg -T | grep -Ei 'EXT4|JBD2|XFS|I/O error|Buffer I/O|read-only|abort'
# → [Sep 10 14:23:01] EXT4-fs error (device sdc1): ext4_journal_check_start_recovery

# 2. Проверка SMART-статуса накопителя
sudo smartctl -a /dev/sdc | grep -E "SMART overall|Reallocated|Current_Pending"

# 3. Проверка на наличие сбросов линка
dmesg -T | grep -i "hard resetting link"
```

**Ключевые паттерны:**
*   `EXT4-fs error (device sdc1): ext4_journal_check_start_recovery` — повреждение журнала.
*   `Buffer I/O error` — проблемы с диском или контроллером.
*   `Remounting filesystem read-only` — ядро принудительно перемонтировало ФС в защитном режиме.

> **Важно:** Запуск `fsck` на смонтированной файловой системе приведет к разрушению данных. Всегда монтируйте в режиме `ro` или используйте rescue-окружение.
> Подробная методология: [**Файловая система в режиме read-only**](../../../FileSystems/read_only_filesystem_troubleshooting.md)

### Анализ thermal throttling

Троттлинг (снижение частоты CPU/GPU) происходит при достижении критических температур и фиксируется в `dmesg`:

```bash
# Поиск событий throttling
dmesg -T | grep -iE "thermal|throttl|overheat|cpu.*temp"

# Корреляция с показаниями датчиков (пакет lm-sensors)
watch sensors
# → coretemp-isa-0000
#   Package id 0:  +92.0°C  (high = +100.0°C, crit = +100.0°C)
```

**Типичные причины:**
*   Загрязнение радиатора или неисправность вентилятора.
*   Неправильная паста/прокладка.
*   Проблемы с BIOS/UEFI (отключен PWM fan control).

### Автоматизированные проверки работоспособности

Для регулярного мониторинга создайте скрипт и добавьте в cron:

```bash
#!/bin/bash
# /usr/local/bin/dmesg_health_check.sh
LOG="/var/log/dmesg_health.log"
ERRORS=$(dmesg -T 2>/dev/null | grep -iE "error|fail|crit|mce|aer|thermal|throttl" | tail -n 50)

if [ -n "$ERRORS" ]; then
    echo "[$(date +%F)] CRITICAL: dmesg errors detected:" >> "$LOG"
    echo "$ERRORS" >> "$LOG"
    # Отправка уведомления (mail, slack, pagerduty)
    # send_alert "dmesg errors on $(hostname)"
fi
```

```bash
# Добавление в cron (ежедневный запуск в 08:00)
0 8 * * * root /usr/local/bin/dmesg_health_check.sh
```

### Восстановление после Kernel Panic

При аварийной перезагрузке `dmesg` текущей сессии пуст. Для получения логов паники:

```bash
# 1. Проверьте pstore (работает без монтирования корневой ФС)
cat /sys/fs/pstore/dmesg-ramoops-0 2>/dev/null || echo "pstore не содержит дампа"

# 2. Если используется kdump — анализируйте vmcore
ls -R /var/crash/
crash /usr/lib/debug/boot/vmlinux-$(uname -r) /var/crash/*/vmcore
```

Для детального разбора паники используйте: [**Анализ Kernel Panic**](../../../Core/kernel/kernel_panic.md)

### Удаленное логирование через netconsole

Для серверов без локального доступа к консоли настройте `netconsole` — отправляет сообщения ядра по сети на диагностический хост:

```bash
# На диагностируемом хосте (загрузка модуля)
sudo modprobe netconsole netconsole=@/eth0,@192.168.1.100/514

# Постоянное применение через /etc/modprobe.d/netconsole.conf
options netconsole netconsole=@/eth0,@192.168.1.100/514
```

**На диагностическом хосте** (приемник):
```bash
# Простой прием через nc
nc -lu 514

# Или через syslogd, настроенный на порт 514 UDP
```

### Подготовка bug report для kernel developers

При отправке отчета в kernel Bugzilla или upstream mailing list включите:

```bash
# 1. Полный дамп dmesg текущей сессии
sudo dmesg -T > ~/bugreport/dmesg_full.log

# 2. Конфигурация ядра
zcat /proc/config.gz > ~/bugreport/kernel_config 2>/dev/null || \
    cat /boot/config-$(uname -r) > ~/bugreport/kernel_config

# 3. Список загруженных модулей
cat /proc/modules > ~/bugreport/modules_list

# 4. Журналы journalctl
sudo journalctl -k -b > ~/bugreport/journalctl_kernel.log

# 5. Сжатие
tar czf ~/bugreport.tar.gz -C ~/bugreport .
```

**Правила:**
*   Убедитесь, что в логах нет паролей или-sensitive данных.
*   Приложите шаги для воспроизведения проблемы.
*   Укажите версию ядра (`uname -r`) и дистрибутив.

---

## Дополнительная информация

### Основные фильтры для поиска (Grep Patterns)

```bash
# Поиск всех критических событий
dmesg | grep -iE "panic|oops|error|fail|crit"

# Поиск аппаратных проблем (CPU/RAM/Bus)
dmesg | grep -iE "mce|edac|aer|thermal|throttl"

# Поиск проблем с прошивками (Firmware)
dmesg | grep -i "firmware"

# Block layer ошибки
dmesg | grep -iE "blk_update_request|I/O error|Buffer I/O|cmd timeout"

# Сетевой стек
dmesg | grep -iE "conntrack.*table full|SYN.*flood|softirq|NET_RX"

# Модули ядра
dmesg | grep -iE "FATAL.*module|Unknown symbol|taint|Invalid module"

# Виртуализация
dmesg | grep -iE "kvm.*error|virtio.*error|hv_.*error|balloon.*error"

# NUMA
dmesg | grep -iE "numa.*error|node.*out.*range|numa_balancing.*crash"
```

### Связанные темы

*   [**Обзор dmesg (SSoT)**](./index.md) — архитектура, уровни важности и механизмы доступа.
*   [**Использование и фильтрация**](./usage.md) — флаги, временные форматы и мониторинг в реальном времени.
*   [**Диагностика Block Layer**](./block-layer.md) — blk_update_request, I/O errors, queue depth.
*   [**Диагностика сетевого стека**](./network-stack.md) — SYN flood, softirq, conntrack, TCP drops.
*   [**Диагностика модулей ядра**](./modules-lifecycle.md) — загрузка/выгрузка, taint, Secure Boot.
*   [**Диагностика виртуализации**](./virtualization.md) — KVM, VMware, Hyper-V, balloon, steal time.
*   [**Диагностика частоты CPU**](./cpu-frequency.md) — cpufreq, thermal throttling, C-states.
*   [**Диагностика NUMA**](./numa.md) — NUMA topology, миграция страниц.
*   [**Диагностика live patching**](./live-patching.md) — kpatch, ftrace-based patching.
*   [**Production sysctl**](../../../Core/kernel/sysctl_production.md) — kernel tunables для продакшена.
*   [**Мониторинг dmesg**](../../../SystemAdministration/Logging/dmesg_monitoring.md) — экспорт в Prometheus/Loki/Grafana.
*   [**Анализ Kernel Panic**](../../../Core/kernel/kernel_panic.md) — детальный разбор фатальных сбоев, kdump и pstore.
