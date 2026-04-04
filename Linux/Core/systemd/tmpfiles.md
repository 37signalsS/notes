# systemd-tmpfiles

## Определения

**`systemd-tmpfiles`** — механизм создания, очистки и управления временными файлами и каталогами. Обрабатывает `/tmp`, `/var/tmp`, `/run`, `/var/log` и кэш-директории по правилам из конфигурационных файлов. Создаёт файлы с нужными правами и удаляет по возрасту.

> Логирование через journald: [journald.md](../../SystemAdministration/Logging/journald.md). Таймеры и расписание: [timers.md](./timers.md).

## Базовые концепции

### Расположение конфигурационных файлов

| Путь | Назначение | Приоритет |
| :--- | :--- | :--- |
| `/etc/tmpfiles.d/*.conf` | Пользовательские правила | Высший |
| `/run/tmpfiles.d/*.conf` | Динамические правила (runtime) | Средний |
| `/usr/lib/tmpfiles.d/*.conf` | Пакетные правила | Низший |

> Файлы в `/etc/` переопределяют файлы с тем же именем в `/usr/lib/`.

### Формат строки

```
<тип> <путь> <режим> <владелец> <группа> <возраст> <аргумент>
```

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `тип` | Операция (см. таблицу ниже) | `d`, `f`, `F` |
| `путь` | Путь к файлу/каталогу | `/run/myservice` |
| `режим` | Права доступа (octal) | `0755`, `0644`, `-` |
| `владелец` | Пользователь | `nginx`, `-` |
| `группа` | Группа | `nginx`, `-` |
| `возраст` | Время жизни (очистка) | `1d`, `30min`, `-` |
| `аргумент` | Зависит от типа (содержимое, цель symlink) | `-` |

### Таблица типов директив

| Тип | Операция | Очистка по возрасту | Пример |
| :--- | :--- | :--- | :--- |
| `d` | Создать директорию | Нет | `d /run/myservice 0755 user group -` |
| `D` | Создать директорию | Да | `D /tmp/cache 0755 user group 1d` |
| `f` | Создать файл | Нет | `f /run/myservice.pid 0644 user group -` |
| `F` | Создать/перезаписать файл | Да | `F /var/log/app.log 0640 user group 7d` |
| `w` | Записать в существующий файл | Нет | `w /proc/sys/vm/drop_caches - - - - 1` |
| `L` | Создать symlink | Нет | `L /run/alias - - - - /var/target` |
| `c` | Создать символьное устройство | Нет | `c /dev/null 0666 root root -` |
| `b` | Создать блочное устройство | Нет | `b /dev/sda 0660 root disk -` |
| `p` | Создать FIFO (pipe) | Нет | `p /run/mypipe 0600 user group -` |
| `x` | Исключить из очистки | Нет | `x /tmp/important - - - -` |
| `X` | Исключить из очистки (кроме старых) | Да | `X /var/tmp/old 0755 user group 7d` |
| `r` | Удалить директорию (рекурсивно) | Нет | `r /var/cache/old - - - -` |
| `R` | Удалить директорию (рекурсивно, включая файлы) | Нет | `R /tmp/olddir - - - -` |
| `v` | Создать subvolume (btrfs) | Нет | `v /var/lib/subvol 0755 user group -` |
| `q` | Как `d`, но создать поддиректорию с уникальным именем | Нет | `q /tmp/prefix - - - -` |
| `Z` | Рекурсивно изменить права (игнорировать возраст) | Нет | `Z /var/log/app 0640 user group -` |
| `t` | Изменить атрибуты (immutable, append-only) | Нет | `t /important/dir - - - -` |

> `-` в поле означает «не указывать» (права, владелец, возраст — не применяются).

## Практические сценарии

### Создание директории для сервиса

```ini
# /etc/tmpfiles.d/myservice.conf
d /run/myservice 0750 myuser mygroup -
f /run/myservice/myservice.pid 0644 myuser mygroup -
L /run/myservice.sock - - - - /run/myservice/actual.sock
```

### Очистка старых логов

```ini
# /etc/tmpfiles.d/app-logs.conf
F /var/log/myapp/app.log 0640 myuser mygroup 7d
X /var/log/myapp/archive/*.gz 0640 myuser mygroup 30d
```

### Кэш-директория с автоочисткой

```ini
# /etc/tmpfiles.d/app-cache.conf
d /var/cache/myapp 0750 myuser mygroup -
D /var/cache/myapp/temp 0750 myuser mygroup 1d
```

### Защита важных файлов от очистки

```ini
# /etc/tmpfiles.d/important.conf
x /tmp/important-data - - - -
```

Файл `/tmp/important-data` не будет удалён при `--clean`, несмотря на нахождение в `/tmp`.

### Применение конфигурации

```bash
# Создать файлы и директории
sudo systemd-tmpfiles --create

# Очистить файлы старше указанного возраста
sudo systemd-tmpfiles --clean

# Удалить файлы по правилам r/R/X
sudo systemd-tmpfiles --remove

# Тестовый режим (без изменений)
sudo systemd-tmpfiles --create --dry-run
```

### Автоматическая очистка по расписанию

```bash
# Проверить статус таймера
systemctl status systemd-tmpfiles-clean.timer

# Включить
sudo systemctl enable --now systemd-tmpfiles-clean.timer

# Просмотр расписания
systemctl cat systemd-tmpfiles-clean.timer
```

> Таймер управляется стандартным механизмом systemd. Подробности: [timers.md](./timers.md).

## Дополнительная информация

### Приоритет и переопределение правил

Файлы обрабатываются в лексикографическом порядке. Файл с тем же именем в `/etc/tmpfiles.d/` полностью заменяет файл в `/usr/lib/tmpfiles.d/`. Правила в одном файле применяются последовательно.

### Интеграция с journald

`systemd-tmpfiles` используется для автоматической очистки логов journald. Пример конфигурации:

```ini
# /etc/tmpfiles.d/systemd-journald.conf
e /var/log/journal - - - 14d -
```

Параметр `Age` (`14d`) указывает, что файлы старше 14 дней будут удалены при `systemd-tmpfiles --clean`. Подробности о journald: [journald.md](../../SystemAdministration/Logging/journald.md).

### Безопасность

Не устанавливайте права `0777` на директории в `/run` — используйте `0755` или строже. Для файлов с секретами используйте `0600` и указывайте конкретного владельца. `x` и `X` не удаляют файлы, а исключают из очистки — для удаления используйте `r`, `R`.
