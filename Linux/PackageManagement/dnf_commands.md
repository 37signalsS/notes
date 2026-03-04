# Работа с DNF (Dandified YUM)

## Определения

**DNF (Dandified YUM)** — современный высокоуровневый пакетный менеджер для RPM-based дистрибутивов (Fedora, RHEL 8+, CentOS, AlmaLinux, Rocky Linux). Написан на Python с использованием библиотек `libsolv` и `hawkey`. Является заменой устаревшего `yum`, сохраняя обратную совместимость (команда `yum` — символическая ссылка на `dnf`).

**Модуль (Module)** — механизм управления параллельными версиями ПО и их зависимостями (например, несколько версий Python, Node.js, PostgreSQL одновременно).

**Транзакция (Transaction)** — атомарная операция установки, удаления или обновления пакетов, которая может быть отменена или повторена.

## Основные понятия

### Преимущества DNF перед YUM

- **Разрешение зависимостей** — улучшенный алгоритм на основе `libsolv`
- **Модульность** — поддержка Fedora Modularity и RHEL Application Streams
- **Производительность** — ленивая загрузка метаданных
- **История транзакций** — полный журнал с возможностью отката
- **Расширяемость** — система плагинов на Python

### Конфигурация

| Файл | Назначение |
| :--- | :--- |
| `/etc/dnf/dnf.conf` | Основная конфигурация DNF |
| `/etc/yum.repos.d/` | Директория с `.repo` файлами репозиториев |
| `/var/cache/dnf/` | Кэш метаданных и пакетов |
| `/var/log/dnf.log*` | Логи операций |
| `/var/log/dnf.history` | История транзакций |

## Практические сценарии

### Базовые операции с пакетами

```bash
# Обновление информации о репозиториях (метаданных)
sudo dnf check-update

# Обновление всех пакетов до последних версий
sudo dnf update
# или (синоним)
sudo dnf upgrade

# Обновление конкретного пакета
sudo dnf update <package_name>

# Установка пакета
sudo dnf install <package_name>

# Установка определённой версии
sudo dnf install <package_name>-<version>

# Установка из конкретного репозитория
sudo dnf install --repo <repo_id> <package_name>

# Установка локального .rpm файла (с зависимостями)
sudo dnf install ./package.rpm

# Удаление пакета
sudo dnf remove <package_name>
# или (синоним)
sudo dnf erase <package_name>

# Переустановка пакета
sudo dnf reinstall <package_name>

# Понижение версии пакета (downgrade)
sudo dnf downgrade <package_name>
```

### Поиск и информация о пакетах

```bash
# Поиск пакета по имени или описанию
dnf search <keyword>

# Расширенный поиск по всем метаданным
dnf search --all <keyword>

# Поиск по предоставленным файлам
dnf provides '*/<file_name>'
dnf provides <command_name>

# Информация о пакете (из репозитория)
dnf info <package_name>

# Информация об установленном пакете
dnf info installed <package_name>

# Показать зависимости пакета
dnf deplist <package_name>

# Показать содержимое пакета (файлы)
dnf repoquery --list <package_name>

# Показать обратные зависимости (кто зависит от этого пакета)
dnf repoquery --installed --whatrequires <package_name>

# Показать доступные версии пакета
dnf list --showduplicates <package_name>
```

### Работа с кэшем

```bash
# Очистить весь кэш (метаданные и пакеты)
sudo dnf clean all

# Очистить только кэш метаданных
sudo dnf clean metadata

# Очистить только кэш пакетов
sudo dnf clean packages

# Очистить кэш и перестроить базу RPM
sudo dnf clean all && sudo rpm --rebuilddb

# Показать размер кэша
du -sh /var/cache/dnf/
```

### Работа с группами пакетов

Группы позволяют установить набор пакетов, объединённых общей целью (например, "Development Tools").

```bash
# Список доступных групп
dnf grouplist

# Список всех групп (включая скрытые)
dnf grouplist hidden

# Информация о группе
dnf group info <group_name>

# Установить группу
sudo dnf group install <group_name>

# Установить группу без обязательных пакетов
sudo dnf group install --setopt=group_package_types=mandatory <group_name>

# Удалить группу
sudo dnf group remove <group_name>

# Полное удаление группы (с необязательными пакетами)
sudo dnf group remove --setopt=group_package_types=default,optional,mandatory <group_name>
```

### Работа с модулями (Modularity)

Модули позволяют управлять параллельными версиями ПО (например, несколько версий Python или Node.js).

```bash
# Список доступных модулей
dnf module list

# Список установленных модулей
dnf module list --installed

# Информация о модуле
dnf module info <module_name>

# Показать профили модуля (наборы пакетов)
dnf module info <module_name>:<stream>

# Включить модуль (с указанием стрима)
sudo dnf module enable <module_name>:<stream>

# Отключить модуль
sudo dnf module disable <module_name>

# Установить модуль
sudo dnf module install <module_name>:<stream>

# Установить модуль с профилем
sudo dnf module install <module_name>:<stream>/<profile>

# Сбросить модуль в состояние по умолчанию
sudo dnf module reset <module_name>

# Удалить модуль
sudo dnf module remove <module_name>:<stream>
```

### История операций

DNF ведёт историю всех операций, что позволяет откатывать изменения.

```bash
# История операций (транзакций)
dnf history

# Детали конкретной операции
dnf history info <transaction_id>

# Показать пакеты, установленные в транзакции
dnf history info <transaction_id> | grep Install

# Откатить операцию (удалить установленное или восстановить удаленное)
sudo dnf history undo <transaction_id>

# Откат последней операции
sudo dnf history undo last

# Повторить операцию
sudo dnf history redo <transaction_id>

# Экспорт истории в файл
dnf history history-list > dnf-history.txt

# Статистика истории
dnf history stats
```

### Определение необходимости перезагрузки

После обновления системных библиотек или ядра может потребоваться перезагрузка.

```bash
# Показать сервисы/процессы, требующие перезагрузки
dnf needs-restarting

# Проверить, требуется ли перезагрузка системы
dnf needs-restarting -r

# Показывает только процессы с указанием PID
dnf needs-restarting -p
```

### Работа с репозиториями

```bash
# Список включённых репозиториев
dnf repolist

# Список всех репозиториев (включая отключенные)
dnf repolist all

# Подробная информация о репозитории
dnf repoinfo <repo_id>

# Включить репозиторий
sudo dnf config-manager --set-enabled <repo_id>

# Отключить репозиторий
sudo dnf config-manager --set-disabled <repo_id>

# Добавить репозиторий по URL
sudo dnf config-manager --add-repo <repo_url>

# Сохранить репозиторий в файл
sudo dnf config-manager --save
```

### Продвинутые операции

```bash
# Загрузить пакет без установки
dnf download <package_name>

# Загрузить пакет со всеми зависимостями
dnf install --downloadonly <package_name>

# Разрешить установку пакетов из отключенных репозиториев
sudo dnf install --enablerepo=<repo_id> <package_name>

# Исключить пакеты из обновления
sudo dnf update --exclude=<package_name>

# Обновить только определённые пакеты
sudo dnf update <package1> <package2>

# Проверка целостности установленных пакетов
rpm -Va

# Показать пакеты, ожидающие обновления
dnf list --upgrades

# Показать недавно установленные пакеты
dnf list --recent
```

## Дополнительная информация

### Переменные окружения DNF

| Переменная | Назначение |
| :--- | :--- |
| `DNF_CONF_FILE` | Путь к файлу конфигурации |
| `DNF_PLUGIN_PATH` | Путь к плагинам |
| `RELEASEVER` | Версия дистрибутива (подставляется в URL репозиториев) |

### Конфигурационные опции (dnf.conf)

```ini
[main]
gpgcheck=1              # Проверка GPG-подписей по умолчанию
installonly_limit=3     # Количество сохраняемых версий ядра
clean_requirements_on_remove=true  # Удалять ненужные зависимости
best=True               # Использовать лучшую версию пакета
skip_if_unavailable=False  # Не пропускать недоступные репозитории
```

### Плагины DNF

| Плагин | Назначение |
| :--- | :--- |
| `dnf-plugins-core` | Базовые плагины (config-manager, needs-restarting) |
| `dnf-plugin-versionlock` | Блокировка версий пакетов |
| `dnf-plugin-post-transaction-actions` | Действия после транзакций |
| `dnf-plugin-debuginfo-install` | Установка отладочной информации |

```bash
# Установка плагинов
sudo dnf install dnf-plugins-core

# Блокировка версии пакета
sudo dnf versionlock add <package_name>

# Показать заблокированные пакеты
sudo dnf versionlock list

# Снять блокировку
sudo dnf versionlock delete <package_name>

# Очистить все блокировки
sudo dnf versionlock clear
```

### Сравнение DNF и YUM

| Команда YUM | Команда DNF | Примечание |
| :--- | :--- | :--- |
| `yum update` | `dnf update` | Полная совместимость |
| `yum install` | `dnf install` | Полная совместимость |
| `yum remove` | `dnf remove` | Полная совместимость |
| `yum search` | `dnf search` | Полная совместимость |
| `yum provides` | `dnf provides` | Полная совместимость |
| `yum history` | `dnf history` | Улучшенная функциональность |
| `yum groupinstall` | `dnf group install` | Изменён синтаксис |
| — | `dnf module` | Новая функция в DNF |

### Связанные темы

* **[Обзор управления пакетами](./linux_package_management_overview.md)** — базовые концепции
* **[Управление репозиториями DNF](./dnf_repository_management.md)** — настройка репозиториев
* **[Анализ и получение пакетов](./package_analysis.md)** — изучение метаданных и содержимого
* **[База данных пакетов](./package_database.md)** — история транзакций и восстановление
* **[Локальное зеркало репозитория](./local_repository_mirror.md)** — создание зеркал для YUM/DNF
