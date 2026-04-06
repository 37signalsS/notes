# База данных установленных пакетов

## Определения

**База данных пакетов (Package Database)** — системное хранилище информации об установленных, удалённых и доступных пакетах. Содержит метаданные, списки файлов, статус, зависимости и конфигурации.

## Основные понятия

### Назначение базы данных

- **Отслеживание установленных пакетов** — версия, статус, приоритет
- **Сопоставление файлов пакетам** — какой пакет установил файл
- **Управление зависимостями** — какие пакеты зависят от данного
- **Контроль целостности** — проверка изменённых файлов
- **Ведение истории** — журнал установки/удаления

## Практические сценарии

### DPKG (Debian/Ubuntu)

#### Расположение и структура

| Файл/Директория | Назначение |
| :--- | :--- |
| `/var/lib/dpkg/` | Корневая директория базы данных |
| `/var/lib/dpkg/status` | Текущий статус всех пакетов (основной файл) |
| `/var/lib/dpkg/available` | Информация о доступных пакетах (кэш) |
| `/var/lib/dpkg/info/` | Скрипты и списки файлов пакетов |
| `/var/lib/dpkg/info/<pkg>.list` | Список файлов пакета |
| `/var/lib/dpkg/info/<pkg>.md5sums` | Контрольные суммы файлов |
| `/var/lib/dpkg/info/<pkg>.*` | Скрипты (preinst, postinst, prerm, postrm) |
| `/var/lib/dpkg/triggers/` | Ожидающие триггеры |
| `/var/lib/dpkg/updates/` | Ожидающие обновления |
| `/var/lib/dpkg/lock` | Блокировка от параллельного запуска |
| `/var/lib/dpkg/lock-frontend` | Блокировка для frontend-операций |

#### Работа со статусом пакетов

```bash
# Просмотр статуса конкретного пакета
dpkg -s <package_name>

# Статус в кратком формате
dpkg-query -W -f='${Package}\t${Status}\n' <package_name>

# Все пакеты и их статус
dpkg-query -W -f='${Package}\t${Status}\t${Version}\n'

# Флаги статуса:
# ii  — установлен (installed)
# rc  — удалён, конфиги остались (removed, config-files)
# pn  — никогда не установлен (purge, not-installed)
# iv  — неверно установлен (invalid)
# hi  — установлен наполовину (half-installed)
# uf  — ошибка распаковки (unpacked, failed)
```

#### Восстановление базы данных

```bash
# Переконфигурация всех пакетов
dpkg --configure -a

# Восстановление после прерванной установки
sudo apt-get install -f

# Резервное копирование статуса
sudo cp /var/lib/dpkg/status /var/lib/dpkg/status.backup

# Восстановление из резервной копии
sudo cp /var/lib/dpkg/status.backup /var/lib/dpkg/status
sudo dpkg --configure -a
```

### RPM (Fedora/RHEL/CentOS)

#### Расположение и структура

| Файл/Директория | Назначение |
| :--- | :--- |
| `/var/lib/rpm/` | Корневая директория базы данных |
| `/var/lib/rpm/rpmdb.sqlite` | Основная БД (SQLite, современные версии) |
| `/var/lib/rpm/Packages` | Основная БД (Berkeley DB, старые версии) |
| `/var/lib/rpm/__db.*` | Индексы Berkeley DB |
| `/var/lib/rpm/.db.*` | Служебные файлы SQLite |
| `/var/lib/rpm/lock` | Блокировка базы данных |
| `/var/log/dnf.log*` | Логи операций DNF |
| `/var/log/dnf.history` | История транзакций DNF |

#### Формат базы данных

Современные версии RPM (Fedora 33+, RHEL 9+) используют **SQLite** вместо Berkeley DB:

- **rpmdb.sqlite** — основная база с метаданными пакетов
- Индексы для ускорения поиска по имени, файлам, зависимостям

#### Восстановление базы данных

```bash
# Перестройка базы данных (регенерация индексов)
sudo rpm --rebuilddb

# Проверка целостности базы
rpm --verifydb

# Очистка кэша и перестройка
sudo dnf clean all
sudo rpm --rebuilddb

# Резервное копирование перед восстановлением
sudo tar -czf /root/rpmdb-backup.tar.gz /var/lib/rpm/
```

#### История транзакций (DNF)

```bash
# Показать историю операций
dnf history

# Детали конкретной транзакции
dnf history info <transaction_id>

# Откат транзакции
sudo dnf history undo <transaction_id>

# Повтор транзакции
sudo dnf history redo <transaction_id>

# Экспорт истории
dnf history history-list > dnf-history.txt
```

## Дополнительная информация

### Сравнение баз данных DPKG и RPM

| Характеристика | DPKG | RPM |
| :--- | :--- | :--- |
| **Формат хранения** | Текстовые файлы | SQLite / Berkeley DB |
| **Основной файл** | `/var/lib/dpkg/status` | `/var/lib/rpm/rpmdb.sqlite` |
| **Списки файлов** | `/var/lib/dpkg/info/<pkg>.list` | Внутри базы данных |
| **Контрольные суммы** | `/var/lib/dpkg/info/<pkg>.md5sums` | В базе данных (digest) |
| **История операций** | `/var/log/dpkg.log` | `dnf history` (SQLite) |
| **Блокировки** | `/var/lib/dpkg/lock*` | `/var/lib/rpm/.lock` |
| **Восстановление** | `dpkg --configure -a` | `rpm --rebuilddb` |

### Проблемы и решения

| Проблема | DPKG | RPM |
| :--- | :--- | :--- |
| **Зависшая блокировка** | `sudo rm /var/lib/dpkg/lock` | `sudo rm /var/lib/rpm/.lock` |
| **Прерванная установка** | `sudo dpkg --configure -a` | `sudo dnf history undo last` |
| **Повреждённая база** | Восстановление из backup | `sudo rpm --rebuilddb` |
| **Неверный статус** | Редактирование `/var/lib/dpkg/status` | `sudo rpm --rebuilddb` |

### Полезные запросы

#### DPKG

```bash
# Какой пакет установил файл?
dpkg -S /path/to/file

# Какие файлы у пакета?
dpkg -L <package_name>

# Все установленные пакеты
dpkg --get-selections

# Пакеты, ожидающие настройки
dpkg -l | grep ^un

# Пакеты с повреждёнными файлами
debsums -s  # требует установки debsums
```

#### RPM

```bash
# Какой пакет установил файл?
rpm -qf /path/to/file

# Какие файлы у пакета?
rpm -ql <package_name>

# Все установленные пакеты
rpm -qa

# Пакеты, не из репозиториев
rpm -qa --nodigest | grep -v "@.*@"

# Проверка целостности пакета
rpm -V <package_name>
```
