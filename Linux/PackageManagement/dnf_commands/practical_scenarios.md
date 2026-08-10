# DNF — Практические сценарии

## Определения

Определения ключевых терминов (модуль, поток, профиль, транзакция) приведены в документе **[Определения](./definitions.md)**. Пакетный менеджер DNF является основным высокоуровневым инструментом управления ПО в RPM-based системах.

---

## Основные концепции

Обзор архитектуры (DNF 4 vs DNF 5), преимуществ SAT-solver и глобальной конфигурации доступен в файле **[Основные понятия](./basic_concepts.md)**. Детальное описание плагинов и переменных окружения приведено в **[Продвинутых возможностях](./additional_info.md)**.

---

## Практические сценарии

### Базовое управление пакетами

```bash
# Обновление метаданных всех репозиториев
sudo dnf makecache

# Обновление всех пакетов до последних версий
sudo dnf upgrade

# Установка пакета (с автоматическим разрешением зависимостей)
sudo dnf install <package_name>

# Установка конкретной версии (из доступных в репозиториях)
sudo dnf install <package_name>-<version>

# Удаление пакета (без удаления зависимостей)
sudo dnf remove <package_name>

# Удаление пакета и всех неиспользуемых зависимостей (рекомендуется)
sudo dnf autoremove <package_name>

# Переустановка пакета (например, при повреждении файлов)
sudo dnf reinstall <package_name>

# Понижение версии пакета (downgrade)
sudo dnf downgrade <package_name>

# Замена одного пакета другим (полезно при миграции, например, mysql -> mariadb)
sudo dnf swap <old_package> <new_package>
```

### Групповые операции

Группы позволяют устанавливать наборы пакетов для конкретных задач (например, "Development Tools").

```bash
# Список всех доступных и установленных групп
dnf group list

# Информация о составе группы (обязательные, рекомендуемые пакеты)
dnf group info "Development Tools"

# Установка группы
sudo dnf group install "Development Tools"

# Удаление группы
sudo dnf group remove "Development Tools"

# Установка группы окружения (Environment Group)
sudo dnf group install "Server with GUI"
```

### Расширенный поиск и инспекция (Repoquery)

Утилита `repoquery` позволяет делать сложные запросы к базе данных пакетов.

```bash
# Поиск пакета по имени или части описания
dnf search <keyword>

# Показать, какой пакет предоставляет конкретный файл (например, /usr/bin/python3)
dnf provides /usr/bin/python3

# Подробная информация о пакете (версия, лицензия, описание)
dnf info <package_name>

# Список всех файлов, входящих в пакет (даже если он не установлен)
dnf repoquery --list <package_name>

# Поиск пакетов, которые зависят от указанного (обратные зависимости)
dnf repoquery --installed --whatrequires <package_name>

# Поиск пакета, предоставляющего конкретную Capability или shared library
dnf repoquery --whatprovides "libssl.so.1.1()(64bit)"

# Список всех зависимостей пакета
dnf deplist <package_name>

# Показать все доступные версии пакета во всех репозиториях
dnf list --showduplicates <package_name>

# Показать пакеты, установленные не из репозиториев (локальные или устаревшие)
dnf list extras
```

### Управление модулями и потоками (AppStream)

Модули позволяют переключаться между разными версиями одного ПО в рамках одного дистрибутива.

```bash
# Список модулей и их доступных потоков (streams)
dnf module list

# Включение конкретного потока (например, Node.js 20)
sudo dnf module enable nodejs:20

# Установка модуля с профилем по умолчанию (обычно common)
sudo dnf module install nodejs:20

# Установка модуля с конкретным профилем (например, минимальная установка)
sudo dnf module install nodejs:20/minimal

# Переключение на другой поток (автоматически обновит/заменит пакеты)
sudo dnf module switch-to nodejs:22

# Сброс состояния модуля (отмена выбора потока)
sudo dnf module reset nodejs
```

### История транзакций и откат изменений

DNF ведет детальный лог всех изменений, что позволяет безопасно откатывать систему.

```bash
# Просмотр списка последних транзакций
dnf history

# Детальная информация о транзакции (кто, когда и что изменил)
dnf history info <transaction_id>

# Отмена изменений конкретной транзакции (undo)
sudo dnf history undo <transaction_id>

# Повтор ранее выполненной транзакции (redo)
sudo dnf history redo <transaction_id>

# Полный откат состояния системы к моменту после указанной транзакции
sudo dnf history rollback <transaction_id>

# Список транзакций, инициированных пользователем (а не системой)
dnf history userinstalled
```

### Продвинутые техники и автоматизация

```bash
# Фиксация версии пакета (запрет обновления через плагин versionlock)
sudo dnf versionlock add nginx

# Удаление блокировки версии
sudo dnf versionlock delete nginx

# Установка зависимостей для сборки пакета (из .spec файла)
sudo dnf builddep <package_name>.spec

# Проверка базы данных RPM на наличие ошибок и конфликтов
dnf check

# Синхронизация версий установленных пакетов с версиями в репозитории
sudo dnf distro-sync

# Интерактивная оболочка DNF (ускоряет выполнение нескольких команд подряд)
dnf shell
```

### Тюнинг поведения через флаги

```bash
# Пропуск обновлений для конкретных пакетов
sudo dnf upgrade --exclude=kernel*

# Отключение установки слабых зависимостей (recommends)
sudo dnf install <package_name> --setopt=install_weak_deps=False

# Использование только локального кэша (без сети)
dnf upgrade --cacheonly

# Скачивание RPM-пакета без установки
dnf download --destdir=/tmp <package_name>

# Скачивание исходного кода пакета (Source RPM)
dnf download --source <package_name>
```

---

## Дополнительная информация

### Сравнение с DNF 5

В DNF 5 (Fedora 41+, RHEL 10) синтаксис остается практически идентичным, но вводятся некоторые уточнения:

| Задача | Команда DNF 4 | Команда DNF 5 |
| :--- | :--- | :--- |
| **История** | `dnf history` | `dnf5 history list` |
| **Поиск** | `dnf search` | `dnf5 search` |
| **Скорость** | Стандартная | Значительно выше (C++) |

### Связанные документы

- **[Определения DNF](./definitions.md)** — глоссарий терминов.
- **[Основные понятия DNF](./basic_concepts.md)** — архитектура и настройки.
- **[Продвинутые возможности DNF](./additional_info.md)** — плагины, переменные и `dnf-automatic`.
- **[Управление репозиториями](../Repository_Management/index.md)** — настройка источников ПО.
- **[Анализ пакетов](../package_analysis.md)** — глубокая инспекция RPM и метаданных.
- **[База данных пакетов](../package_database.md)** — структура RPMDB и работа с ней.
