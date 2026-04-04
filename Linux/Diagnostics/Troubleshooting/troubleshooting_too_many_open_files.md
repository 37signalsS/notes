# Диагностика ошибки "too many open files"

## Definitions

**Файловый дескриптор (File Descriptor, FD)** — неотрицательное целое число, идентифицирующее открытый файл, сокет или другой ресурс I/O. Подробнее: [Файловые дескрипторы](../../FileSystems/file_descriptors.md).

**Ошибка «too many open files» (EMFILE/ENFILE)** — возникает при исчерпании лимита открытых файловых дескрипторов процессом (EMFILE) или системой в целом (ENFILE).

**Soft limit** — текущий действующий лимит. Процесс может увеличить soft limit до значения hard limit.

**Hard limit** — максимальное значение для soft limit. Изменить может только root.

## Basic Concepts

### Иерархия лимитов

Лимиты устанавливаются на нескольких уровнях:

| Уровень | Механизм | Где настраивается |
| :--- | :--- | :--- |
| Система | `fs.file-max` | `/proc/sys/fs/file-max`, `sysctl` |
| Пользователь | `nofile` soft/hard | `/etc/security/limits.conf` |
| Сервис (systemd) | `LimitNOFILE` | Unit-файл сервиса |
| Сессия | `ulimit -n` | `~/.bashrc`, `/etc/profile` |
| Процесс | `/proc/<PID>/limits` | Наследуется от родителя |

Подробно: [Иерархия лимитов процессов](../../Core/processes/limits_hierarchy.md).

### Утечка файловых дескрипторов

Ситуация, когда процесс открывает файлы/сокеты, но не закрывает их. Приводит к постепенному исчерпанию лимита и ошибке EMFILE.

## Practical Scenarios

### Шаг 1: Подсчёт открытых дескрипторов

```bash
# Количество открытых FD процесса
sudo lsof -p <PID> | wc -l

# Альтернатива через /proc
ls /proc/<PID>/fd | wc -l
```

Подробнее: [`lsof`](../Processes/lsof.md).

### Шаг 2: Проверка лимитов процесса

```bash
grep "Max open files" /proc/<PID>/limits
```

Пример вывода:
```
Max open files            8192                 65535                files
```
Здесь `8192` — soft limit, `65535` — hard limit.

### Шаг 3: Проверка лимитов на разных уровнях

```bash
# Текущая сессия
ulimit -n

# Глобальный лимит системы
cat /proc/sys/fs/file-max

# Лимиты пользователя
cat /etc/security/limits.conf

# Лимит systemd-сервиса
systemctl show <service_name> -p LimitNOFILE
```

### Шаг 4: Увеличение лимита

**systemd-сервис:**
```ini
[Service]
LimitNOFILE=65535
```
```bash
sudo systemctl daemon-reexec
sudo systemctl restart <service_name>
```

**Системный уровень:**
```bash
# Временно
sudo sysctl -w fs.file-max=2097152

# Постоянно (/etc/sysctl.d/90-file-max.conf)
fs.file-max = 2097152
```

**Пользовательский уровень (`/etc/security/limits.conf`):**
```
*    soft    nofile    65535
*    hard    nofile    65535
```

## Additional Information

### Динамическая трассировка с strace

Для выявления утечки FD отслеживают вызовы `openat` и `close`:

```bash
sudo strace -e trace=openat,close -p <PID>
```

Подробнее: [Трассировка и отладка](./tracing_and_debugging.md).

### Связанные темы

- [Файловые дескрипторы](../../FileSystems/file_descriptors.md)
- [Иерархия лимитов](../../Core/processes/limits_hierarchy.md)
- [`lsof`](../Processes/lsof.md)
