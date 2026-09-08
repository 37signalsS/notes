# Паника ядра (Kernel Panic)

## Определения

**Kernel Panic** — критическое состояние, при котором ядро обнаруживает неустранимую ошибку и прекращает работу. Это защитный механизм, предотвращающий повреждение данных на дисках при потере целостности самого ядра. При панике ядро пытается максимально быстро остановить всю систему, чтобы избежать недетерминированного повреждения данных или аппаратуры.

**Kernel Oops** — серьезная, но потенциально нефатальная ошибка. Ядро пытается продолжить работу, "убив" вызвавший ошибку процесс. Однако после Oops состояние ядра считается нестабильным (Tainted). Если после Oops происходит критическая операция (монтирование ФС, запись на диск), может последовать паника.

**BUG() / WARN()** — макросы в коде ядра для обработки аномалий. `BUG()` обычно приводит к панике или Oops, `WARN()` только выводит стек вызовов в `dmesg`. Семейство макросов включает `BUG_ON()`, `WARN_ON()`, `WARN_ON_ONCE()`, `WARN_ONCE()` — каждый с разной строгостью и частотой срабатывания.

**kdump (Kernel Crash Dump)** — механизм сохранения дампа оперативной памяти (`vmcore`) в момент сбоя. Использует `kexec` для загрузки резервного ядра поверх упавшего, минуя POST и BIOS/UEFI.

**pstore (Persistent Store)** — механизм сохранения логов ядра в энергонезависимую память (NVRAM, EFI или зарезервированная RAM — `ramoops`), которая доступна после перезагрузки.

## Основные концепции

### Жизненный цикл паники (Panic Flow)

Когда возникает фатальная ошибка, ядро проходит через следующие этапы:
1.  **Вызов `panic()`**: Функция в `kernel/panic.c` останавливает планировщик и прерывания на текущем CPU через `smp_send_stop()`.
2.  **Оповещение (Notifiers)**: Выполняются функции из `panic_notifier_list` (например, для гашения светодиодов на сервере, отправки сообщения в IPMI или отключения StorPort).
3.  **Запись в pstore**: Если настроен `ramoops` или ERST, ядро копирует содержимое `dmesg` в зарезервированную область памяти.
4.  **Kdump (опционально)**: Если kdump активен, выполняется `crash_kexec()` — немедленный переход в аварийное ядро без сброса оборудования.
5.  **Действие по умолчанию**: Если kdump не сработал, ядро либо зависает (halt), либо перезагружается через время, указанное в `kernel.panic`.

### Семейство макросов BUG() и WARN()

| Макрос | Поведение | Результат | Использование |
| :--- | :--- | :--- | :--- |
| `BUG()` | Безусловная паника | Kernel Panic | Невосстановимые ошибки |
| `BUG_ON(cond)` | Паника если `cond==true` | Kernel Panic | Проверка инвариантов |
| `WARN_ON(cond)` | Лог + продолжение | Oops / продолжение | Предупреждение о баге |
| `WARN_ON_ONCE(cond)` | Лог 1 раз за boot | Oops / продолжение | Одноразовое предупреждение |
| `WARN_ONCE(cond, fmt...)` | Лог 1 раз с fmt | Oops / продолжение | Кастомное одноразовое предупреждение |

Важно: `WARN()` не останавливает систему, но помечает ядро как Tainted. После Oops стабильность не гарантируется.

### Состояние загрязнения ядра (Kernel Taint)

Механизм **Taint** указывает на факторы, влияющие на стабильность и отладку. При панике или Oops ядро помечает себя флагами:

| Флаг | Значение | Описание |
| :--- | :--- | :--- |
| `P` | Proprietary | Загружен проприетарный драйвер (например, NVIDIA). |
| `F` | Force | Модуль загружен принудительно (`-f`), игнорируя проверку версий. |
| `O` | Out-of-tree | Модуль скомпилирован вне официального дерева исходного кода ядра. |
| `E` | Unsigned | Загружен модуль без валидной цифровой подписи (критично для Secure Boot). |
| `R` | Unsupported module | Модуль явно помечен как unsupported. |
| `S` | SMP with CPUs not designed for SMP | Работа в SMP на не SMP-совместимом железе. |
| `M` | MCE (Machine Check Exception) | Обнаружена аппаратная ошибка процессора/памяти. |
| `B` | Page release | Страница была неожиданно освобождена. |
| `U` | User-mode page | Попытка доступа к пользовательской странице из ядра. |
| `D` | Deadlock | Обнаружена потенциальная deadlock (LOCKDEP). |
| `A` | ACPI table override | Таблица ACPI была переопределена. |
| `W` | Warning | Сработал `WARN_ON()`. |
| `I` | In-kernel instrumentation | Используется tracing/probing (eBPF, kprobes). |

Проверка состояния:
```bash
cat /proc/sys/kernel/tainted
# → 0 (чистое ядро) или числовой код (>0)
# Расшифровка: python3 -c "print(''.join([c for i,c in enumerate('POORSMRBDUAWI') if (int(open('/proc/sys/kernel/tainted').read()) >> i) & 1]))"
```

### Параметры паники (panic_on_*)

Ядро предоставляет тонкий контроль над тем, какие события считаются фатальными:

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `kernel.panic` | `30` | Время (сек) до автоматической перезагрузки после паники. `0` — отключить авто-перезагрузку. |
| `kernel.panic_on_oops` | `1` | Считать любой Oops фатальным (рекомендуется для HA-кластеров и embedded). |
| `kernel.panic_on_warn` | `0` | Вызывать панику при любом `WARN_ON()` (полезно для fuzz-тестирования). |
| `kernel.panic_on_taint` | `0` | Маска флагов taint, при которых вызывать панику. Например, `0x40` — паника при флаге `N` (nested XEN). |
| `kernel.panic_on_rcu_stall` | `0` | Паника при RCU stall (если не настроен `rcupdate.rcu_cpu_stall_timeout`). |
| `kernel.softlockup_panic` | `1` | Вызывать панику при Soft Lockup (см. [Lockups](./lockups.md)). |
| `kernel.hardlockup_panic` | `1` | Вызывать панику при Hard Lockup. |

### Архитектурные особенности

#### x86_64
- При панике используется архитектурно-зависимый код в `arch/x86/kernel/dumpstack.c`.
- Аппаратные регистры (CR0-CR4, EFLAGS, RIP, RSP) сохраняются в `struct pt_regs`.
- Состояние FPU/SIMD (XSAVE) может быть сохранено в `vmcore` при наличии `CONFIG_X86_SAVEFP_REGS`.

#### ARM64 (AArch64)
- Используется `arch/arm64/kernel/process.c` для `__crash_kexec()`.
- Регистры сохраняются в `struct pt_regs` (x0-x30, sp, pc, pstate).
- На ARM64 требуется поддержка `CONFIG_ARM64_PANIC_ON_RPANIC` для автоматического перезапуска.
- В системах без APEI (ACPI Platform Error Interface) сложнее получить аппаратные журналы MCE.

### kdump: Резервирование памяти

Для надежной работы `kdump` требуется зарезервировать память заранее через параметры загрузки ядра:
- `crashkernel=auto` — автоматическое выделение (может не работать в виртуализации и некоторых старых системах).
- `crashkernel=256M` — рекомендуемый минимум для современных систем с 4-8 ГБ RAM.
- `crashkernel=1G-:64M` — 64 МБ, если RAM больше 1 ГБ (старый синтаксис).
- `crashkernel=4G-:192M` — 192 МБ для систем с 4+ ГБ RAM.

#### Что сохраняется в vmcore
- **Страницы пользовательского пространства:** По умолчанию сохраняются все страницы, принадлежащие процессам.
- **Страницы ядра:** Все страницы, отображенные в адресное пространство ядра (Kernel Direct Map).
- **Структуры ядра:** task_struct, mm_struct, vm_area_struct и другие (при наличии debuginfo).
- **Регистры CPU:** Состояние всех CPU на момент паники.
- **dmesg ring buffer:** Копия кольцевого буфера.

#### Что НЕ сохраняется в vmcore
- Аппаратные регистры DMA контроллеров.
- Состояние устройств PCI (BAR, MSI-X таблицы).
- Dirty page cache (не записанное на диск).
- Сетевое соединение в состоянии TCP (не отправленный и не подтвержденный сегменты).
- Состояние файловых дескрипторов ядра (fdtable) — доступно через `crash` только если страницы сохранены.

### ramoops: Конфигурация pstore

Чтобы pstore работал через оперативную память, необходимо выделить сегмент, который **не будет** очищен при мягкой перезагрузке:

```bash
# Пример 1: Резервирование 1 МБ по адресу 0x60000000
memmap=1M$0x60000000 ramoops.mem_address=0x60000000 ramoops.mem_size=0x100000 ramoops.record_size=0x4000

# Пример 2: Автоматический режим (ядро само ищет свободную область выше 4 ГБ)
memmap=4M$0x100000000 ramoops.mem_size=0x400000

# Пример 3: Резервирование через crashkernel (если kdump не нужен)
# crashkernel=256M ramoops.mem_address=0x1000000 ramoops.mem_size=0x20000
```

Параметры `ramoops`:
- `mem_address`: Физический адрес зарезервированной области.
- `mem_size`: Размер области (рекомендуется 1-4 МБ).
- `record_size`: Размер одной записи (обычно 4 КБ — соответствует размеру страницы).
- `max_rmem_records`: Максимальное количество записей в кольцевом буфере.

### Другие бэкенды pstore

Помимо `ramoops`, pstore поддерживает:

| Бэкенд | Хранилище | Описание |
| :--- | :--- | :--- |
| `ramoops` | Зарезервированная RAM | Стандартный бэкенд для большинства серверов. |
| `erst` | NVRAM (ACPI ERST) | Error Record Serialization Table — аппаратная таблица на серверном железе. |
| `mce` | MCE-регистры | Запись Machine Check Exceptions (аппаратные ошибки CPU/памяти). |
| `efi` | EFI переменные | Сохранение в NVRAM UEFI (ограниченный объем). |

Проверка доступных бэкендов:
```bash
# Просмотр доступных записей pstore
ls -la /sys/fs/pstore/
# → dmesg-ramoops-0  dmesg-erst-0  mce-0  mce-1
```

## Практические сценарии

### Настройка поведения через sysctl

Управление поведением системы при различных типах сбоев:

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `kernel.panic` | `30` | Время (сек) до автоматической перезагрузки после паники. |
| `kernel.panic_on_oops` | `1` | Считать любой Oops фатальным (рекомендуется для HA-кластеров). |
| `kernel.softlockup_panic` | `1` | Вызывать панику, если процесс завис в ядре более чем на 20 сек. |
| `kernel.unknown_nmi_panic` | `1` | Паника при получении неизвестного немаскируемого прерывания (NMI). |
| `kernel.hardlockup_panic` | `1` | Паника при Hard Lockup. |
| `kernel.panic_on_warn` | `0` | Паника при любом `WARN_ON()` (для отладки/fuzzing). |
| `kernel.panic_on_taint` | `0` | Маска флагов taint для принудительной паники. |
| `kernel.hardlockup_all_cpu_backtrace` | `1` | Дамп стека ВСЕХ ядер при зависании одного. |

### Настройка kdump

#### RHEL / CentOS / Fedora / Rocky Linux

```bash
# Установка пакетов
sudo dnf install kexec-tools crash kernel-debuginfo

# Проверка резервирования памяти
cat /proc/cmdline | grep crashkernel
# → crashkernel=256M

# Включение и запуск службы
sudo systemctl enable --now kdump

# Проверка статуса
sudo kdumpctl status
# → Kdump is operational

# Просмотр конфигурации
cat /etc/kdump.conf
# → path /var/crash
# → core_collector makedumpfile -l --message-level 1 -d 31
# → default initrd
```

#### Debian / Ubuntu

```bash
# Установка пакетов
sudo apt install kdump-tools crash kdump-tools-dbgsym

# Проверка конфигурации
cat /etc/default/kdump-tools
# → USE_KDUMP=1
# → KDUMP_COREDIR="/var/crash"
# → KDUMP_CMDLINE_APPEND=""

# Включение службы
sudo systemctl enable --now kdump

# Проверка
sudo kdump-config show
# → kdump: operational
# → crashkernel: 256M
# → vmcore location: /var/crash
```

#### Arch Linux

```bash
# Установка пакетов
sudo pacman -S kexec-tools crash

# Добавление параметра загрузки
# В /etc/default/grub:
# GRUB_CMDLINE_LINUX_DEFAULT="... crashkernel=256M"

# Создание systemd юнита (если нет)
sudo mkdir -p /etc/systemd/system/kdump.service.d
cat <<EOF | sudo tee /etc/systemd/system/kdump.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/bin/kdumpctl start
EOF

# Включение и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now kdump
```

#### openSUSE / SUSE

```bash
# Установка
sudo zypper install kdump kexec-tools crash

# Проверка конфигурации
cat /etc/sysconfig/kdump
# → KDUMP_SAVEDIR="/var/crash"
# → KDUMP_KERNELVER="$(uname -r)"
# → KDUMP_CMD_LINE=""

# Включение
sudo systemctl enable --now kdump
```

### kdump: Troubleshooting

```bash
# 1. Проверка, что crashkernel зарезервирован
cat /proc/iomem | grep -i crash
# → 100000000-10fffffff : Crash kernel

# 2. Проверка, что kexec загружен
sudo kexec -l /boot/vmlinuz-$(uname -r) --initrd=/boot/initramfs-$(uname -r).img --reuse-cmdline

# 3. Проверка работы kdump
sudo systemctl status kdump
sudo kdumpctl status

# 4. Принудительная перезагрузка через kexec (без паники) для теста
sudo kexec -e

# 5. Если kdump не срабатывает — проверка dmesg
dmesg | grep -i kexec
# → kexec: Reserving the memory...

# 6. Проверка места на диске
df -h /var/crash
# → /dev/sda1 50G 10G 40G 20% /var/crash

# 7. Проверка debuginfo
ls /usr/lib/debug/lib/modules/$(uname -r)/vmlinux
# → /usr/lib/debug/lib/modules/5.14.0/vmlinux
```

### Глубокий анализ дампа (crash)

Если `kdump` создал файл `vmcore`, анализ выполняется утилитой `crash` (требует пакет `kernel-debuginfo` или `linux-image-*-dbgsym`):

```bash
# Запуск анализатора
sudo crash /usr/lib/debug/boot/vmlinux-$(uname -r) /var/crash/127.0.0.1-.../vmcore

# Ключевые команды внутри crash:
crash> bt              # стек вызовов текущего процесса
crash> bt -a           # стеки вызовов всех процессов
crash> bt <PID>        # стек конкретного процесса
crash> log             # вывод dmesg из дампа (последние сообщения перед паникой)
crash> ps              # список всех процессов в момент сбоя
crash> ps -o           # процессы с расширенной информацией
crash> mod             # список загруженных модулей ядра
crash> struct          # просмотр содержимого структур ядра в памяти
crash> struct task_struct <addr>  # просмотр конкретной структуры
crash> vm              # виртуальные адресные пространства процесса
crash> files           # открытые файловые дескрипторы
crash> dev             # список блочных и символьных устройств
crash> net             # сетевая статистика (sockets, sk_buff)
crash> timer           # активные таймеры
crash> rcu             # информация о RCU grace periods
crash> foreach bt      # стеки вызовов всех CPU
crash> list            # список элементов в linked list ядра
crash> mount           # смонтированные ФС
crash> ipcs            # IPC сегменты (shmem, semaphores)
crash> sig             # обработчики сигналов
crash> swap            # swap-области
crash> q               # выход

# Пример: найти процесс, вызвавший панику
crash> ps -o | grep -i panic

# Пример: посмотреть последние сообщения
crash> log | tail -n 50
```

### Диагностика через pstore

После перезагрузки проверьте наличие отчетов:

```bash
# Монтировать pstore, если не сделано автоматически
mount -t pstore pstore /sys/fs/pstore 2>/dev/null || true

# Просмотр лога паники (ramoops)
cat /sys/fs/pstore/dmesg-ramoops-0
# → <1>[ 1234.567890] Kernel panic - not syncing: Fatal exception in interrupt

# Просмотр всех файлов pstore
ls -la /sys/fs/pstore/
# → dmesg-ramoops-0         4096  2026-08-09 17:55:01
# → dmesg-erst-0            4096  2026-08-09 17:55:01
# → mce-0                   4096  2026-08-09 17:55:00

# Если pstore не монтируется автоматически — проверка модулей
lsmod | grep pstore
# → pstore         16384  0
# → ramoops         24576  0
```

### Настройка journald для постоянного логирования ядра

Для сохранения логов ядра между перезагрузками:

```bash
# /etc/systemd/journald.conf
[Journal]
Storage=persistent
MaxRetentionSec=30day
RuntimeMaxUse=1G
PersistentMaxUse=4G
SystemMaxUse=4G
MaxFileSec=1day

# Применение
sudo systemctl restart systemd-journald

# Проверка
journalctl -b -1 -k | tail -n 20
# → сообщения ядра предыдущей загрузки
```

### Автоматизированный мониторинг и алертинг

#### Prometheus (node_exporter + alertmanager)

```yaml
# /etc/prometheus/rules/kernel_panics.yaml
groups:
  - name: kernel_stability
    rules:
      - alert: KernelPanicDetected
        expr: increase(node_kernel_panic_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Kernel Panic on {{ $labels.instance }}"
          description: "System experienced {{ $value }} kernel panic(s) in last 5m"

      - alert: KernelOopsDetected
        expr: increase(node_kernel_oops_total[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Kernel Oops on {{ $labels.instance }}"
          description: "System experienced {{ $value }} kernel oops(s) in last 5m"

      - alert: KdumpNotOperational
        expr: node_kdump_status{status!="operational"} == 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Kdump not operational on {{ $labels.instance }}"
          description: "kdump status: {{ $value }}"
```

#### Проверка статуса kdump через systemd

```bash
# Скрипт для мониторинга (можно запускать через cron или systemd timer)
#!/bin/bash
STATUS=$(kdumpctl status 2>&1)
if echo "$STATUS" | grep -qi "not operational\|failed\|inactive"; then
    echo "CRITICAL: kdump is not operational: $STATUS"
    # Отправка алерта: mail, slack, pagerduty
    exit 2
elif echo "$STATUS" | grep -qi "operational"; then
    echo "OK: kdump is operational"
    exit 0
else
    echo "UNKNOWN: kdump status unclear: $STATUS"
    exit 3
fi
```

### Параметры загрузки для улучшения диагностики

| Параметр | Описание |
| :--- | :--- |
| `earlyprintk=ttyS0,115200n8` | Вывод сообщений ядра на раннем этапе (до инициализации консоли). |
| `earlycon=uart,mmio32,0x3F8` | Ранняя консоль через UART (альтернатива earlyprintk). |
| `loglevel=7` | Максимальный уровень логирования ядра. |
| `initcall_debug` | Вывод времени выполнения каждого initcall (полезно для диагностики медленной загрузки). |
| `debug` | Включает расширенную отладочную информацию. |
| `rd.systemd.show_status=1` | Показывает статус загрузки юнитов systemd в initramfs. |
| `rd.break` | Остановка загрузки внутри initramfs перед `switch_root` для ручного исправления. |
| `systemd.debug_shell` | Запускает root-оболочку на TTY9 (Ctrl+Alt+F9). |
| `boot_delay=1000` | Задержка 1 сек на каждом этапе загрузки (полезно для slow serial console). |
| `no_console_suspend` | Не приостанавливать консоль при переходе в suspend (если используется). |

### Анализ типов паник

#### NULL pointer dereference
```bash
# В dmesg перед паникой:
# BUG: unable to handle kernel NULL pointer dereference at 0000000000000018
# IP: my_driver_function+0x12/0x30 [mydriver]
# PGD 0 P4D 0
# Oops: 0002 [#1] SMP

# Диагностика через crash:
crash> bt
# → показывает стек с my_driver_function
crash> struct task_struct <addr>
# → проверка контекста процесса
```

#### Stack overflow
```bash
# В dmesg:
# BUG: stack guard page was hit at .. in
# Kernel panic - not syncing: stack-protector: Kernel stack is corrupted

# Причины:
# - Рекурсивный вызов в ядре
# - Слишком глубокий вызов через softirq/tasklet
# - Переполнение стека из-за слишком глубокого вложения
```

#### RCU Stall
```bash
# В dmesg:
# INFO: rcu_preempt detected stalls on CPUs/tasks:
# CPU: 1 PID: 1234 Comm: myapp
# rcu_preempt detected stall on CPU 1 (t=10000 jiffies)

# Диагностика:
crash> rcu
# → информация о grace periods
crash> foreach bt
# → найти задачи, блокирующие RCU
```

#### Page Fault (нехватка памяти)
```bash
# В dmesg:
# BUG: unable to handle page fault for address: ffffffffffffffff
# #PF: error_code(0x0002) - not-present page

# Проверка:
dmesg | grep -i "out of memory"
journalctl -k -g "Out of memory"
```

### Безопасный тест kdump (без паники)

```bash
# Метод 1: Имитация паники через sysrq (осторожно!)
echo c > /proc/sysrq-trigger
# → ядро перезагрузится, kdump должен сработать

# Метод 2: Сброс kdump и проверка загрузки
sudo kdumpctl restart
sudo kdumpctl status
# → Kdump is operational

# Метод 3: Проверка конфигурации без перезагрузки
sudo kexec -l /boot/vmlinuz-$(uname -r) \
     --initrd=/boot/initramfs-$(uname -r).img \
     --reuse-cmdline
sudo kexec -e
# ← вернется после перезагрузки в текущее ядро (если kexec настроен корректно)
```

### Учетные записи и права

```bash
# Кто может запустить kdumpctl (обычно root)
sudo kdumpctl status

# Проверка прав на каталог с дампами
ls -la /var/crash/
# → drwx------ 2 root root 4096 ... /var/crash

# Просмотр информации о vmcore (без crash)
file /var/crash/*/vmcore
# → /var/crash/202608091756/vmcore: ELF 64-bit LSB core file, x86-64, version 1 (SYSV), SVR4-style

# Размер vmcore
ls -lh /var/crash/*/vmcore
# → 1.2G /var/crash/202608091756/vmcore
```

### Интеграция с виртуализацией

#### KVM / QEMU

```bash
# В конфигурации libvirt XML для виртуальной машины:
# <features>
#   <apic/>
#   <msi/>
#   <acpi/>
# </features>
# <on_crash>preserve</on_crash>  # не перезагружать VM автоматически

# Проверка внутри VM:
dmesg | grep -i "kexec\|kdump"
# → kexec: Reserving the memory...

# Проверка kexec:
sudo kexec -l /boot/vmlinuz-$(uname -r) --initrd=/boot/initramfs-$(uname -r).img --reuse-cmdline
```

#### VMware

```bash
# В VMware kdump работает, но требует настройки:
# 1. Включить "Support cold boot for fault tolerance" в vSphere
# 2. Убедиться, что crashkernel= не конфликтует с vRAM
# 3. Проверить, что VM Configuration Parameters содержит:
#    hypervisor.cpuid.v0 = "FALSE"  # иногда требуется для kexec
```

#### Hyper-V

```bash
# Hyper-V поддерживает kdump через synthetic interrupt (Sint) для kexec.
# Проверка:
dmesg | grep -i "hyperv\|kdump"
# → hv_vmbus: Hyper-V Guest Bus Driver
# → kexec: Reserving the memory...
```

### Мониторинг давления прерываний (PSI)

```bash
# Проверка давления прерываний
cat /proc/pressure/irq
# → some avg10=18.50 avg60=12.30 avg300=8.10 total=87654321
# → full avg10=5.20 avg60=2.10 avg300=1.05 total=12345678

# avg10=18.50 означает, что за последние 10 секунд система тратила 18.5% времени на обработку прерываний
# Пороги для алертов: avg10 > 10-15% — возможен IRQ-шторм
```

### Распространенные сценарии аварийного восстановления

#### Сценарий 1: Система перезагрузилась — проверка причины

```bash
# 1. Проверка истории перезагрузок
last reboot | head -n 3
# → reboot   system boot  6.8.0-40-generic Sun Aug  9 18:00   still running

# 2. Проверка последних логов предыдущей сессии
journalctl -b -1 -p err | tail -n 30

# 3. Проверка kdump дампов
ls -R /var/crash/

# 4. Проверка pstore
mount -t pstore pstore /sys/fs/pstore 2>/dev/null || true
cat /sys/fs/pstore/dmesg-ramoops-0 2>/dev/null | tail -n 50

# 5. Проверка аппаратных журналов (IPMI)
sudo ipmitool sel list | tail -n 5
# → Watchdog | Timer expired
```

#### Сценарий 2: Система зависла — попытка получить диагностику

```bash
# 1. Проверка SysRq (если включен)
cat /proc/sys/kernel/sysrq
# → 1 (все функции включены)

# 2. Попытка получить трассу
echo t > /proc/sysrq-trigger  # Вывод трассы всех задач
echo p > /proc/sysrq-trigger  # Вывод информации о регистрах
echo c > /proc/sysrq-trigger  # Немедленная перезагрузка (если kdump не настроен)

# 3. Если есть SSH, но reboot не работает
echo 1 > /proc/sys/kernel/sysrq
for x in r e i s u b; do echo $x > /proc/sysrq-trigger; sleep 1; done
```

#### Сценарий 3: Анализ конкретного дампа vmcore

```bash
# 1. Установка debuginfo-пакетов (Debian/Ubuntu)
sudo apt install linux-image-$(uname -r)-dbgsym

# Или через debuginfod (современный способ)
export DEBUGINFOD_URLS="https://debuginfod.ubuntu.com/"
sudo apt install crash
crash /usr/lib/debug/lib/modules/$(uname -r)/vmlinux /var/crash/.../vmcore

# 2. Быстрый анализ
crash> log | tail -n 50           # последние сообщения перед паникой
crash> bt                         # стек текущего процесса
crash> ps -o                      # все процессы
crash> mod                        # модули
crash> kmem -s                    # статистика аллокатора

# 3. Поиск функции-виновника
crash> list -s <function_name>    # найти адрес функции
crash> dis <addr>                 # дизассемблировать
```

### Проверка поддерживаемых функций ядра

```bash
# Параметры сборки ядра
grep CONFIG_CRASH_DUMP /boot/config-$(uname -r)
# → CONFIG_CRASH_DUMP=y

grep CONFIG_PROC_VMCORE /boot/config-$(uname -r)
# → CONFIG_PROC_VMCORE=y

grep CONFIG_DEBUG_BUGVERBOSE /boot/config-$(uname -r)
# → CONFIG_DEBUG_BUGVERBOSE=y

grep CONFIG_PSTORE /boot/config-$(uname -r)
# → CONFIG_PSTORE=y

# Проверка Secure Boot
bootctl status | grep "Secure Boot"
# → Secure Boot: enabled

# Проверка EFI переменных
[ -d /sys/firmware/efi ] && echo "UEFI Mode" || echo "Legacy Mode"

# Проверка модулей ядра
lsmod | head -n 10

# Проверка статуса TPM
cat /sys/class/tpm/tpm0/tpm_version_major
# → 2 (TPM 2.0)
```

## Дополнительная информация

### Связанные темы

- **Зависания и Watchdog:** [Lockups](./lockups.md) — механизмы обнаружения блокировок до паники.
- **Процесс загрузки:** [Boot Process](./boot_process.md) — роль `kexec` и диагностика ранних сбоев.
- **Живые обновления:** [Live Patching и kexec](./live_patching.md) — использование kexec вне kdump.
- **Интерфейс настройки:** [sysctl](./sysctl.md) — управление параметрами ядра в реальном времени.
- **Журналирование:** [dmesg](../../Diagnostics/Kernel/dmesg/index.md) — просмотр сообщений ядра.
- **Анализ ошибок:** [Анализ ошибок и сбоев](../../SystemAdministration/Logging/error_and_crash_analysis.md) — Root Cause Analysis критических инцидентов.
- **Диагностика перезагрузки:** [Диагностика причин перезагрузки](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) — стратегии определения триггера перезагрузки.
- **Виртуальные ФС:** [Виртуальные файловые системы](../../FileSystems/virtual_filesystems.md) — pstore, procfs, sysfs.
