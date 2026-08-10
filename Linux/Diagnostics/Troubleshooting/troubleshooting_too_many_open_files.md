# Диагностика ошибки «too many open files»

## Definitions

**Файловый дескриптор (File Descriptor, FD)** — неотрицательное целое число, используемое процессом для обращения к открытым файлам, сокетам, каналам (pipes) и другим ресурсам ввода-вывода. Подробнее: [**Файловые дескрипторы**](../../FileSystems/file_descriptors.md).

**Ошибка EMFILE (Too many open files)** — исчерпан лимит дескрипторов на уровне конкретного процесса. Приложение не может открывать новые ресурсы.

**Ошибка ENFILE (File table overflow)** — исчерпан общесистемный лимит дескрипторов в ядре Linux (суммарно всеми процессами).

**Soft limit (Мягкий лимит)** — текущее действующее ограничение. Процесс может самостоятельно увеличить его до значения жесткого лимита.

**Hard limit (Жесткий лимит)** — «потолок» для мягкого лимита. Увеличить его может только пользователь с правами root.

**fs.nr_open** — системный параметр ядра, определяющий абсолютный максимум для любого `ulimit -n`. Даже root не может установить лимит выше этого значения.

---

## Basic Concepts

### Иерархия лимитов

Ограничения проверяются ядром последовательно. Процесс должен пройти через все «фильтры»:

| Уровень | Механизм / Параметр | Где настраивается |
| :--- | :--- | :--- |
| **Ядро (Hard)** | `fs.nr_open` | `/proc/sys/fs/nr_open` |
| **Система (Total)** | `fs.file-max` | `/proc/sys/fs/file-max`, `sysctl` |
| **Пользователь** | `nofile` soft/hard | `/etc/security/limits.conf` (через PAM) |
| **Сервис (systemd)** | `LimitNOFILE` | Unit-файл сервиса |
| **Сессия** | `ulimit -n` | `~/.bashrc`, `/etc/profile` |
| **Процесс** | `/proc/<PID>/limits` | Наследуется от родителя |

### Причины возникновения ошибки

1.  **Утечка дескрипторов:** Программа открывает файлы/сокеты, но не закрывает их (например, из-за ошибок в логике или отсутствия блоков `finally`).
2.  **Недостаток прав доступа (Косвенно):** Если у процесса нет прав на запись в директорию, он может бесконечно пытаться переоткрыть файл в цикле, поглощая дескрипторы при некорректной обработке ошибок.
3.  **Лимиты сред выполнения:** Интерпретаторы (PHP-FPM, Java) могут иметь собственные настройки пулов, которые ниже системных.
4.  **CLOSE_WAIT Storm:** Накопление сокетов, которые не были закрыты приложением после получения FIN от клиента.

---

## Practical Scenarios

### Шаг 1: Подсчёт и анализ открытых дескрипторов

```bash
# Общее количество открытых FD процесса
ls /proc/<PID>/fd | wc -l
# → 1024

# Глубокий анализ типов ресурсов (позволяет найти источник утечки)
ls -l /proc/<PID>/fd
# → lrwx------ 1 ... 0 -> /etc/hosts (Файл)
# → lrwx------ 1 ... 3 -> socket:[123456] (Сеть)
# → lrwx------ 1 ... 4 -> anon_inode:[eventfd] (События ядра, характерно для Java/Netty)
# → lrwx------ 1 ... 5 -> pipe:[234567] (Межпроцессное взаимодействие)
```

### Шаг 2: Проверка лимитов процесса и системы

```bash
# Какие лимиты видит ядро для конкретного процесса прямо сейчас
grep "Max open files" /proc/<PID>/limits
# → Max open files            1024                 4096                 files

# Глобальная статистика использования дескрипторов (выделено / свободно / максимум)
cat /proc/sys/fs/file-nr
# → 2944    0    1048576

# Лимит systemd-сервиса (без чтения файлов юнитов)
systemctl show <service_name> -p LimitNOFILE
# → LimitNOFILE=65536
```

---

### Шаг 3: Увеличение лимитов

**Системный уровень:**
```bash
# Временно
sudo sysctl -w fs.file-max=2097152
# Постоянно (/etc/sysctl.d/90-file-max.conf)
fs.file-max = 2097152
fs.nr_open = 2097152
```

**Сервис systemd (правильный метод):**
```bash
sudo systemctl edit <service_name>
# [Service]
# LimitNOFILE=1048576

sudo systemctl daemon-reload
sudo systemctl restart <service_name>
```

**Пользовательский уровень (PAM):**
В `/etc/security/limits.conf`:
```text
*    soft    nofile    65535
*    hard    nofile    65535
```

---

### Шаг 4: Диагностика и настройка в Kubernetes

В Kubernetes лимиты наследуются от рантайма узла (Node), а не от параметров `resources` в манифесте пода.

**Диагностика внутри пода:**
```bash
# Проверка мягкого и жесткого лимитов
kubectl exec $POD -- sh -c 'ulimit -Sn; ulimit -Hn'
# → 1024
# → 1048576
```

**Настройка через Container Runtime (Рекомендуется):**
Для **containerd** (`/etc/containerd/config.toml`):
```toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  Rlimits = [
    { type = "RLIMIT_NOFILE", hard = 1048576, soft = 1048576 }
  ]
```
После изменения рантайм требует перезапуска, а поды — пересоздания.

**Костыль (ulimit в entrypoint):**
```dockerfile
ENTRYPOINT ["/bin/sh", "-c", "ulimit -n 65536 && exec /app/binary"]
```
*Внимание:* Работает только если контейнеру разрешена capability `CAP_SYS_RESOURCE`.

---

## Additional Information

### ulimit vs Inode limit (Вопрос на собеседовании)

| Характеристика | ulimit (nofile) | Inode limit (df -i) |
| :--- | :--- | :--- |
| **Что ограничивает** | Кол-во открытых FD в RAM | Кол-во файлов на диске |
| **Типичная ошибка** | `Too many open files` | `No space left on device` |
| **Утечка** | Программная (не вызван `close`) | Системная (миллионы мелких файлов) |

### Динамическая трассировка (strace)

Если лимиты высоки, но FD растут — ищите код, который не закрывает файлы.
```bash
sudo strace -p <PID> -e trace=openat,socket,close
# → openat(AT_FDCWD, "/tmp/tmp.txt", ...) = 10
# → socket(AF_INET, SOCK_STREAM, ...) = 11
# (Если за ними не следует close(10) или close(11) — это утечка)
```

### Мониторинг (PromQL)

```promql
# Процент использования лимита процессом
process_open_fds / process_max_fds > 0.8

# Обнаружение CLOSE_WAIT шторма
node_netstat_Tcp_CloseWait > 1000
```

### Связанные темы

- [**Файловые дескрипторы**](../../FileSystems/file_descriptors.md)
- [**Утечки файловых дескрипторов**](./troubleshooting_file_descriptor_leaks.md)
- [**Иерархия лимитов процессов**](../../Core/processes/resource_limits_concepts.md)
- [**Утилита lsof**](../Processes/lsof.md)
- [**Трассировка и отладка**](./tracing_and_debugging.md)
