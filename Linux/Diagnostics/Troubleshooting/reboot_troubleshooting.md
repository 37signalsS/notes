# Диагностика причин перезагрузки Linux

## Definitions

**Диагностика перезагрузки** — анализ системной информации и журналов для установления причины перезагрузки ОС. Цель — отличить штатное инициированное действие от аварийного сбоя.

**Штатная перезагрузка (Initiated Reboot)** — вызвана преднамеренным действием пользователя или процесса (`reboot`, `shutdown -r`, `init 6`, автообновление ядра). Оставляет чёткие следы в журналах.

**Аварийная перезагрузка (System Crash)** — вызвана непредвиденным событием (сбой электропитания, аппаратная ошибка, Kernel Panic). Логи могут отсутствовать или быть неполными.

**Magic SysRq Key** — механизм ядра для выполнения низкоуровневых команд напрямую, в обход высокоуровневых абстракций ОС.

**kdump** — механизм сохранения дампа памяти (`vmcore`) при Kernel Panic для последующего анализа утилитой `crash`.

## Basic Concepts

### Типы перезагрузок

| Тип | Причина | Логи | Примеры |
| :--- | :--- | :--- | :--- |
| Штатная | Действие пользователя/процесса | Полные, чёткие | `reboot`, `shutdown`, обновление ядра |
| Аварийная | Аппаратный сбой, Kernel Panic | Отсутствуют/неполные | Отключение питания, ошибка ядра, RAM/CPU fault |

### Почему `reboot` может не работать при отказе диска

При сбое RAID-контроллера или полной недоступности дисковой подсистемы:

1. **Бинарные файлы** (`/usr/bin/reboot`, `/usr/bin/systemctl`) находятся на недоступном диске.
2. **Unit-файлы systemd** для остановки сервисов не читаются.
3. **Вызов `sync`** зависает в состоянии `D` (uninterruptible sleep) при попытке сбросить кэши на мёртвый диск.

Результат: работающая в памяти ОС не может завершить процесс перезагрузки.

## Practical Scenarios

### Шаг 1: Определение времени перезагрузки

```bash
# Время текущей загрузки
who -b

# История всех зарегистрированных перезагрузок
last reboot
```

Команда `last reboot` считывает `/var/log/wtmp` и показывает время каждой загрузки.

### Шаг 2: Анализ системных журналов

**systemd:**

```bash
# Список всех зарегистрированных загрузок
journalctl --list-boots

# Логи предыдущей загрузки (обратный порядок — от конца к началу)
journalctl -b -1 -r
```

Что искать: `reboot`, `shutdown`, `power off`, `Reached target Shutdown`, критические ошибки перед потерей связи.

**syslog (старые системы):**

```bash
grep -iE 'shutdown|reboot|power' /var/log/messages
```

### Шаг 3: Проверка auditd

Если настроен `auditd`, он точно покажет, какой процесс/пользователь инициировал перезагрузку:

```bash
ausearch -i -m system_boot,system_shutdown
```

### Шаг 4: Анализ Kernel Panic (kdump)

Стандартные логи при Kernel Panic неполны — ядро «падает» до записи информации.

```bash
# Проверка наличия vmcore-файлов
ls /var/crash/
```

Наличие `vmcore` — прямое доказательство паники ядра. Анализ:

```bash
crash /usr/lib/debug/lib/modules/$(uname -r)/vmlinux /var/crash/<timestamp>/vmcore
```

### Шаг 5: Аварийная перезагрузка при отказе диска (Magic SysRq — REISUB)

Когда `reboot` не работает из-за недоступности диска, используйте Magic SysRq:

```bash
# Включить SysRq
echo 1 > /proc/sys/kernel/sysrq

# Последовательность REISUB — безопасная перезагрузка
echo r > /proc/sysrq-trigger  # Raw — перехватить клавиатуру
echo e > /proc/sysrq-trigger  # Terminate — SIGTERM всем процессам
echo i > /proc/sysrq-trigger  # Kill — SIGKILL всем процессам
echo s > /proc/sysrq-trigger  # Sync — сбросить кэши (может зависнуть)
echo u > /proc/sysrq-trigger  # Unmount — перемонтировать в read-only
echo b > /proc/sysrq-trigger  # Reboot — немедленная перезагрузка
```

`echo b` — «последнее средство», аналог нажатия Reset. Данные в кэше могут быть потеряны.

## Additional Information

### Постоянное хранение логов journald

По умолчанию логи хранятся в `/run/log/journal` (в памяти) и теряются при сбое.

```bash
# Включить постоянное хранение
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald

# Проверка (должно быть: Storage: persistent)
journalctl -b | head -n 1
```

### Связанные темы

- [journalctl](../journalctl/journalctl_overview.md)
- [Kernel Panic](../../Core/kernel/kernel_panic.md)
- [OOM Killer Diagnostics](../../Core/processes/oom_killer_diagnostics.md)
- [Общая методология диагностики](./general_troubleshooting_methodology.md)
