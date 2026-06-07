# DNF: Практические сценарии

## Определения

Определения ключевых терминов (модуль, поток, профиль) приведены в документе **[Определения](./definitions.md)**. Пакетный менеджер DNF (Dandified YUM) является основным инструментом управления ПО в RPM-based (Red Hat Package Manager) системах.

## Основные концепции

Обзор архитектуры, преимуществ и конфигурации доступен в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

### Базовые операции с пакетами

```bash
# Обновление информации о репозиториях (метаданных)
sudo dnf check-update

# Обновление всех пакетов до последних версий
sudo dnf upgrade

# Обновление конкретного пакета
sudo dnf upgrade <package_name>

# Установка пакета
sudo dnf install <package_name>

# Установка определённой версии пакета
sudo dnf install <package_name>-<version>

# Установка из конкретного репозитория
sudo dnf install --repo <repo_id> <package_name>

# Установка локального .rpm файла (с разрешением зависимостей)
sudo dnf install ./package.rpm

# Удаление пакета
sudo dnf remove <package_name>

# Переустановка пакета
sudo dnf reinstall <package_name>

# Понижение версии пакета (downgrade)
sudo dnf downgrade <package_name>
```

### Поиск и получение информации

```bash
# Поиск пакета по имени или описанию
dnf search <keyword>

# Поиск пакета, предоставляющего конкретный файл или команду
dnf provides <file_or_command>

# Подробная информация о пакете из репозитория
dnf info <package_name>

# Информация об установленном пакете
dnf info installed <package_name>

# Просмотр зависимостей пакета
dnf deplist <package_name>

# Список файлов, входящих в пакет
dnf repoquery --list <package_name>

# Поиск установленных пакетов, зависящих от данного (обратные зависимости)
dnf repoquery --installed --whatrequires <package_name>

# Показать все доступные версии пакета в репозиториях
dnf list --showduplicates <package_name>
```

### Управление кэшем

DNF автоматически управляет кэшем, но иногда требуется ручная очистка для освобождения места или исправления ошибок метаданных.

```bash
# Очистка всех кэшированных данных (метаданные и пакеты)
sudo dnf clean all

# Очистка только кэша метаданных
sudo dnf clean metadata

# Очистка только скачанных файлов пакетов
sudo dnf clean packages

# Очистка кэша и принудительное перестроение базы данных RPM
sudo dnf clean all && sudo rpm --rebuilddb
```

### Работа с группами пакетов

Группы позволяют устанавливать наборы пакетов для определённых задач (например, средства разработки).

```bash
# Список доступных и установленных групп
dnf grouplist

# Подробная информация о составе группы
dnf group info <group_name>

# Установка всех пакетов группы
sudo dnf group install <group_name>

# Удаление всех пакетов группы
sudo dnf group remove <group_name>
```

### Управление модулями (Modularity)

Модули в DNF позволяют переключаться между разными версиями одного ПО (например, Node.js или PostgreSQL).

```bash
# Список всех доступных модулей и их потоков (streams)
dnf module list

# Информация о конкретном модуле
dnf module info <module_name>

# Включение определённого потока (версии) модуля
sudo dnf module enable <module_name>:<stream>

# Установка модуля с профилем по умолчанию
sudo dnf module install <module_name>:<stream>

# Установка модуля с конкретным профилем (например, development или minimal)
sudo dnf module install <module_name>:<stream>/<profile>

# Сброс настроек модуля к состоянию по умолчанию
sudo dnf module reset <module_name>
```

### История транзакций

DNF сохраняет историю всех изменений системы, позволяя просматривать их и выполнять откат.

```bash
# Список последних транзакций
dnf history

# Подробная информация о конкретной транзакции
dnf history info <transaction_id>

# Отмена изменений, внесённых конкретной транзакцией (undo)
sudo dnf history undo <transaction_id>

# Отмена действий последней транзакции
sudo dnf history undo last

# Повторное выполнение ранее отменённой транзакции (redo)
sudo dnf history redo <transaction_id>
```

### Проверка необходимости перезагрузки

После установки обновлений безопасности или нового ядра часто требуется перезагрузка.

```bash
# Проверка, требуется ли перезагрузка всей системы
dnf needs-restarting -r

# Список процессов, использующих старые версии библиотек и требующих перезапуска
dnf needs-restarting

# Список идентификаторов процессов (PID — Process Identifier), требующих перезапуска
dnf needs-restarting -p
```

---

## Дополнительная информация

Дополнительные сведения о плагинах и переменных окружения приведены в документе **[Дополнительная информация](./additional_info.md)**.

### Связанные документы

- **[Определения DNF](./definitions.md)** — глоссарий специфичных терминов.
- **[Основные понятия DNF](./basic_concepts.md)** — архитектура и конфигурация.
- **[Обзор управления пакетами](../linux_package_management_overview.md)** — сравнение систем RPM и DEB.
- **[Зеркалирование репозиториев](../yum_dnf_repository_mirror.md)** — создание локальных зеркал YUM/DNF.
