# Ulimit Usage

## Определения

**ulimit** — встроенная команда shell для просмотра и установки resource limits текущей сессии оболочки. Управляет soft limits (могут быть увеличены до hard limit) и hard limits (повышает только root). Подробное описание типов лимитов и иерархии применения: [**Resource Limits Concepts**](./resource_limits_concepts.md).

## Основные концепции

### Ограничения ulimit

- **Область действия:** Только текущая сессия shell и её дочерние процессы
- **Soft limit:** Может быть уменьшен любым пользователем, увеличен — только до hard limit
- **Hard limit:** Может быть увеличен только root
- **Временность:** Сбрасывается при выходе из сессии

Постоянная настройка лимитов: [**Persistent Limits Configuration**](./persistent_limits_configuration.md).

## Практические сценарии

### Просмотр лимитов

```bash
# Все лимиты сессии
ulimit -a

# Конкретный лимит: открытые файлы
ulimit -n

# Конкретный лимит: процессы
ulimit -u

# Hard limits (вместо soft)
ulimit -Hn
```

Пример вывода `ulimit -a`:

```
core file size          (-c) 0
data seg size           (-d) unlimited
scheduling priority     (-e) 0
file size               (-f) unlimited
pending signals         (-i) 7544
max locked memory       (-l) 251860
max memory size         (-m) unlimited
open files              (-n) 1024
pipe size            (512 bytes) (-p) 8
POSIX message queues     (-q) 819200
real-time priority      (-r) 0
stack size              (-s) 8192
cpu time               (-t) unlimited
max user processes      (-u) 7544
virtual memory          (-v) unlimited
file locks              (-x) unlimited
```

### Установка лимитов

```bash
# Увеличить лимит открытых файлов (до hard limit)
ulimit -n 4096

# Защита от Fork Bomb: лимит процессов
ulimit -u 1024

# Ограничить виртуальную память (в KB)
ulimit -v 2048000

# Hard limit (требует root для увеличения)
ulimit -Hn 65536
```

> **Важно:** Увеличить hard limit выше текущего значения может только root. Soft limit можно увеличивать только до значения hard limit.

### Практические значения nofile

| Сценарий | Soft | Hard | Обоснование |
| :--- | :--- | :--- | :--- |
| **Default (система)** | 1024 | 1048576 | Достаточно для простых задач |
| **Web-сервер (nginx)** | 65536 | 65536 | Каждый клиент = файловый дескриптор |
| **База данных (PostgreSQL)** | 65536 | 131072 | Множество соединений + файлы данных |
| **Высоконагруженный сервис** | 131072 | 1048576 | Тысячи одновременных подключений |

```bash
# Проверить системный максимум файловых дескрипторов
cat /proc/sys/fs/file-max

# Проверить лимиты конкретного процесса
cat /proc/<PID>/limits | grep "Max open files"
```

### Диагностика проблем с лимитами

```bash
# Too many open files — проверка текущего лимита
ulimit -n

# Проверить, сколько дескрипторов использует процесс
ls /proc/<PID>/fd/ | wc -l

# Сравнить с лимитом процесса
grep "Max open files" /proc/<PID>/limits

# Найти процессы с наибольшим количеством открытых файлов
for pid in /proc/[0-9]*/fd; do
    count=$(ls "$pid" 2>/dev/null | wc -l)
    echo "$count $(basename $(dirname $pid))"
done | sort -rn | head -10
```

## Дополнительная информация

### ulimit в скриптах

При запуске скрипта через `#!/bin/bash` ulimit наследуется от родительской сессии:

```bash
#!/bin/bash
ulimit -n 65536  # Установить лимит для скрипта и его дочерних процессов
# ... выполнение скрипта
```

> **Ограничение:** Скрипт не может повысить hard limit выше унаследованного значения без root.

### Отличие от limits.conf и systemd

| Механизм | Область | Постоянство | Приоритет |
| :--- | :--- | :--- | :--- |
| **ulimit** | Текущая сессия | Временный | Низший |
| **limits.conf** | Пользовательские сессии (PAM) | Постоянный | Средний |
| **systemd** | Сервисы | Постоянный | Высший (для демонов) |
| **cgroups** | Контейнеры/группы | Постоянный | Абсолютный |

Подробнее: [**Иерархия лимитов**](./limits_hierarchy.md).
