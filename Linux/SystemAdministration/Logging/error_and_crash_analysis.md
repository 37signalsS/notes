# Анализ ошибок и сбоев

## Определения

**Анализ сбоев (Crash Analysis)** — процесс диагностики причин аварийного завершения ПО или ОС. В отличие от стандартного логирования, фокусируется на событиях, приведших к полной остановке.

**Типы сбоев:**

| Тип | Описание | SSoT |
| :--- | :--- | :--- |
| **Kernel Panic** | Критический сбой ядра, система не может продолжать работу | [kernel_panic.md](../../Core/kernel/kernel_panic.md) |
| **Coredump** | Дамп памяти процесса при аварийном завершении | [troubleshooting.md#Анализ-сбоев-Coredump](../../Core/processes/troubleshooting.md#анализ-сбоев-coredump) |
| **OOM Killer** | Механизм завершения процессов при нехватке памяти | [troubleshooting.md](../../Core/processes/troubleshooting.md) |

## Базовые концепции

### Сбои пространства пользователя (Application Crashes)

Происходят при выполнении недопустимых операций (обращение к неверному адресу памяти, деление на ноль). Система завершает процесс, потенциально создавая `coredump`.

**SSoT:** [Анализ сбоев: Coredump](../../Core/processes/troubleshooting.md#анализ-сбоев-coredump)

### Сбои пространства ядра (Kernel Crashes)

Затрагивают ядро ОС, часто приводят к `Kernel Panic` и перезагрузке. Для анализа требуется механизм сохранения памяти в момент краха (`kdump`).

**SSoT:** [Kernel Panic: анализ и отладка](../../Core/kernel/kernel_panic.md)

## Практические сценарии

### Быстрая диагностика сбоев

```bash
# Проверить наличие дампов памяти (coredump)
coredumpctl list

# Просмотреть логи сбоев за текущую загрузку
journalctl -p err -b

# Проверить сообщения ядра об ошибках
dmesg --level=err,warn

# Найти процессы, завершенные OOM Killer
journalctl -k | grep -i "oom\|killed process"
```

### Анализ Application Crash

1. **Проверить наличие coredump:**
   ```bash
   coredumpctl list
   coredumpctl info <PID>
   ```

2. **Изучить логи сервиса:**
   ```bash
   journalctl -u <сервис> -b
   ```

3. **Анализ дампа в gdb:**
   ```bash
   coredumpctl debug <PID>
   # В gdb: bt (backtrace)
   ```

Подробнее: [Анализ сбоев: Coredump](../../Core/processes/troubleshooting.md#анализ-сбоев-coredump)

### Анализ Kernel Panic

1. **Проверить логи ядра:**
   ```bash
   journalctl -k -b -1  # Предыдущая загрузка
   dmesg -T | less
   ```

2. **Найти сообщения о panic:**
   ```bash
   journalctl -k | grep -i "panic\|bug\|oops"
   ```

3. **Анализ kdump (если настроен):**
   ```bash
   ls -la /var/crash/
   ```

Подробнее: [Kernel Panic: анализ и отладка](../../Core/kernel/kernel_panic.md)

## Дополнительная информация

### Инструменты анализа

| Инструмент | Назначение | SSoT |
| :--- | :--- | :--- |
| `coredumpctl` | Управление дампами памяти процессов | [troubleshooting.md](../../Core/processes/troubleshooting.md) |
| `kdump` | Механизм сбора дампов памяти ядра | [kernel_panic.md](../../Core/kernel/kernel_panic.md) |
| `abrt` | Автоматическое создание отчетов об ошибках (RHEL/Fedora) | — |
| `gdb` | Отладка дампов памяти | — |
| `crash` | Анализ дампов ядра | — |

### Ссылки по теме

- **Coredump и отладка приложений:** [Core/processes/troubleshooting.md](../../Core/processes/troubleshooting.md)
- **Kernel Panic и kdump:** [Core/kernel/kernel_panic.md](../../Core/kernel/kernel_panic.md)
- **Логи ядра:** [dmesg.md](../../Diagnostics/Kernel/dmesg.md)
- **Обзор логирования:** [logging_overview.md](./logging_overview.md)
