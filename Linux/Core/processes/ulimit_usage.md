# Ulimit Usage

## Практические сценарии

### Просмотр всех лимитов (`ulimit -a`)

Команда `ulimit -a` показывает все лимиты ресурсов для текущей сессии shell:

```bash
ulimit -a
```

Пример вывода:

```
real-time non-blocking time (-R)    unlimited
core file size (-c)                 0
data seg size (-d)                  unlimited
scheduling priority (-e)            0
file size (-f)                      unlimited
pending signals (-i)                7544
max locked memory (-l)              251860
max memory size (-m)                unlimited
open files (-n)                     1024
pipe size (-p)                      8
POSIX message queues (-q)           819200
real-time priority (-r)             0
stack size (-s)                     8192
cpu time (-t)                       unlimited
max user processes (-u)             7544
virtual memory (-v)                 unlimited
file locks (-x)                     unlimited
```

**Расшифровка:**

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `real-time non-blocking time (-R)` | `unlimited` | Лимит времени выполнения real-time задач без блокировок |
| `core file size (-c)` | `0` | Размер core-дампа при падении процесса (0 = отключено) |
| `data seg size (-d)` | `unlimited` | Максимальный размер сегмента данных (heap) |
| `scheduling priority (-e)` | `0` | Приоритет планирования процессов |
| `file size (-f)` | `unlimited` | Максимальный размер создаваемых файлов |
| `pending signals (-i)` | `7544` | Максимальное количество ожидающих сигналов для пользователя |
| `max locked memory (-l)` | `251860` | Объём памяти, который можно заблокировать в RAM (не свопить) |
| `max memory size (-m)` | `unlimited` | Максимальный размер резидентной памяти процесса |
| `open files (-n)` | `1024` | **Важно:** макс. количество открытых файловых дескрипторов |
| `pipe size (-p)` | `8` | Размер буфера канала (в единицах по 512 байт) |
| `POSIX message queues (-q)` | `819200` | Максимальный размер очереди сообщений |
| `real-time priority (-r)` | `0` | Приоритет real-time процессов |
| `stack size (-s)` | `8192` | Размер стека потока (8 MB) |
| `cpu time (-t)` | `unlimited` | Лимит процессорного времени |
| `max user processes (-u)` | `7544` | Макс. количество процессов/потоков для пользователя |
| `virtual memory (-v)` | `unlimited` | Лимит виртуальной памяти |
| `file locks (-x)` | `unlimited` | Количество файловых блокировок |

### Управление лимитами (`ulimit`)

Команда `ulimit` позволяет просматривать и устанавливать "мягкие" лимиты для **текущей сессии оболочки**.

```bash
# Посмотреть все текущие лимиты
ulimit -a

# Посмотреть и установить лимит на количество открытых файлов (nofile)
ulimit -n
ulimit -n 4096

# Защита от «Fork Bomb» путем ограничения количества процессов
ulimit -u 1024

# Ограничить максимальный объем виртуальной памяти для процесса (в килобайтах)
ulimit -v 2048000
```

> **Важно:** Изменения `ulimit` действуют только для текущей сессии и дочерних процессов.

---

**См. также:**

* [Типы лимитов](./resource_limits_concepts.md)
* [Постоянная настройка лимитов](./persistent_limits_configuration.md)
