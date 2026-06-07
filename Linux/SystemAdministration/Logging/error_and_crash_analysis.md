# Анализ ошибок и сбоев

## Определения

**Анализ сбоев (Crash Analysis)** — процесс диагностики причин аварийного завершения ПО или ОС. В отличие от стандартного логирования, фокусируется на событиях, приведших к полной остановке.

**Типы сбоев:**

| Тип | Описание |
| :--- | :--- |
| **Kernel Panic** | Критический сбой ядра, система не может продолжать работу | [**Паника ядра**](../../Core/kernel/kernel_panic.md) |
| **Coredump** | Дамп памяти процесса при аварийном завершении | [debugging.md#Анализ-сбоев-Coredump](../../Core/processes/Troubleshooting/debugging.md#анализ-сбоев-coredump) |
| **OOM Killer** | Механизм завершения процессов при нехватке памяти | [oom_killer_mechanism](../../Core/processes/oom_killer_mechanism.md) |

## Базовые концепции

### Сбои пространства пользователя (Application Crashes)

Происходят при выполнении недопустимых операций (обращение к неверному адресу памяти, деление на ноль). Система завершает процесс, потенциально создавая `coredump`.

**Анализ сбоев:** [Coredump](../../Core/processes/Troubleshooting/debugging.md#анализ-сбоев-coredump)

### Сбои пространства ядра (Kernel Crashes)

Затрагивают ядро ОС, часто приводят к `Kernel Panic` и перезагрузке. Для анализа требуется механизм сохранения памяти в момент краха (`kdump`).

**Kernel Panic:** [**Паника ядра**](../../Core/kernel/kernel_panic.md)

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

Подробнее: [Анализ сбоев: Coredump](../../Core/processes/Troubleshooting/debugging.md#анализ-сбоев-coredump)

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

Подробнее: [**Паника ядра: анализ и отладка**](../../Core/kernel/kernel_panic.md)

## Дополнительная информация

### Инструменты анализа и связанные темы

| Инструмент / Тема | Назначение | SSoT-файл |
| :--- | :--- | :--- |
| `coredumpctl`, `gdb` | Управление и отладка дампов процессов | [debugging](../../Core/processes/Troubleshooting/debugging.md) |
| `kdump`, `crash` | Сбор и анализ дампов ядра | [**Паника ядра**](../../Core/kernel/kernel_panic.md) |
| `abrt` | Автоматические отчёты об ошибках (RHEL/Fedora) | — |
| OOM Killer | Механизм завершения процессов при нехватке памяти | [oom_killer_mechanism](../../Core/processes/oom_killer_mechanism.md) |
| dmesg | Просмотр сообщений ядра | [dmesg](../../Diagnostics/Kernel/dmesg/index.md) |
| Обзор логирования | Общая картина систем логирования Linux | [logging_overview](./logging_overview.md) |
