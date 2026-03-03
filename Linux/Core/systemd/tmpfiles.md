# systemd-tmpfiles: Управление временными файлами

## Определения

* **`systemd-tmpfiles`**: Механизм для автоматического создания, очистки и управления временными файлами и каталогами в Linux.

## Основные концепции

* **Назначение**: Используется для `/tmp`, `/var/tmp`, логов и кэш-каталогов.
* **Функциональность**: Файлы и папки создаются с нужными правами и удаляются по правилам времени жизни (age-based cleanup).

### Типы директив

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `d` | Создать директорию | `d /run/myservice 0755 user group -` |
| `D` | Создать директорию, очистить если старше | `D /tmp/cache 0755 user group 1d` |
| `f` | Создать файл | `f /run/myservice.pid 0644 user group -` |
| `F` | Создать файл, очистить если старше | `F /var/log/app.log 0640 user group 7d` |
| `w` | Записать в файл | `w /proc/sys/vm/drop_caches - - - - 1` |
| `L` | Создать symlink | `L /run/alias - - - - /var/target` |
| `x` | Удалить файл (игнорируя возраст) | `x /tmp/oldfile - - - -` |
| `X` | Удалить файл, если старше | `X /var/tmp/old 0755 user group 7d` |
| `r` | Удалить директорию (рекурсивно) | `r /var/cache/old - - - -` |
| `R` | Удалить директорию (игнорируя возраст) | `R /tmp/olddir - - - -` |
| `v` | Создать subvolume (btrfs) | `v /var/lib/subvol 0755 user group -` |

**Формат строки:**
```
<тип> <путь> <режим> <владелец> <группа> <возраст> <аргумент>
```

## Практические сценарии

### 1. Создание временной директории для сервиса

```ini
# /etc/tmpfiles.d/myservice.conf
# Создать директорию для runtime-файлов
d /run/myservice 0750 myuser mygroup -

# Создать PID-файл
f /run/myservice/myservice.pid 0644 myuser mygroup -

# Создать socket для IPC
L /run/myservice.sock - - - - /run/myservice/actual.sock
```

### 2. Очистка старых логов

```ini
# /etc/tmpfiles.d/app-logs.conf
# Хранить логи 7 дней, затем удалять
F /var/log/myapp/*.log 0640 myuser mygroup 7d

# Очистить архивы логов старше 30 дней
X /var/log/myapp/archive/*.gz 0640 myuser mygroup 30d
```

### 3. Настройка кэш-директории

```ini
# /etc/tmpfiles.d/app-cache.conf
# Создать кэш-директорию
d /var/cache/myapp 0750 myuser mygroup -

# Очищать кэш старше 1 дня
D /var/cache/myapp/temp 0750 myuser mygroup 1d
```

### 4. Применение конфигурации

```bash
# Создать файлы и директории
sudo systemd-tmpfiles --create

# Очистить старые файлы
sudo systemd-tmpfiles --clean

# Удалить файлы (тестовый режим)
sudo systemd-tmpfiles --remove

# Проверка без внесения изменений
sudo systemd-tmpfiles --create --dry-run
```

## Дополнительная информация

* **Конфигурация**: Правила для `systemd-tmpfiles` описываются в файлах конфигурации, обычно расположенных в `/etc/tmpfiles.d/*.conf` и `/usr/lib/tmpfiles.d/*.conf`.
* **Ручной запуск**: `systemd-tmpfiles` может быть запущен вручную с помощью команды `systemd-tmpfiles --create` для создания файлов или `systemd-tmpfiles --clean` для очистки.
* **Автоматический запуск**: Служба `systemd-tmpfiles-clean.timer` автоматически запускает очистку по расписанию.
