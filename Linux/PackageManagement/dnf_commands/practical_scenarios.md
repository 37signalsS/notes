# DNF — Практические сценарии

## Определения

Определения ключевых терминов (модуль, поток, профиль) приведены в документе **[Определения](./definitions.md)**. Пакетный менеджер DNF является основным инструментом управления ПО в RPM-based системах.

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

# Обновление только пакетов безопасности
sudo dnf upgrade --security

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

# Удаление пакета и всех неиспользуемых зависимостей
sudo dnf autoremove <package_name>

# Очистка системы от всех неиспользуемых зависимостей
sudo dnf autoremove

# Замена одного пакета другим (с сохранением зависимостей)
sudo dnf swap <old_package> <new_package>

# Переустановка пакета
sudo dnf reinstall <package_name>

# Понижение версии пакета (downgrade)
sudo dnf downgrade <package_name>
```

### Поиск и расширенные запросы

```bash
# Поиск пакета по имени или описанию
dnf search <keyword>

# Поиск пакета, предоставляющего конкретный файл или команду
dnf provides <file_or_command>

# Подробная информация о пакете из репозитория
dnf info <package_name>

# Просмотр зависимостей пакета
dnf deplist <package_name>

# Список файлов, входящих в пакет (неустановленный)
dnf repoquery --list <package_name>

# Поиск установленных пакетов, зависящих от данного (обратные зависимости)
dnf repoquery --installed --whatrequires <package_name>

# Показать все доступные версии пакета в репозиториях
dnf list --showduplicates <package_name>

# Список всех пакетов, установленных не из официальных репозиториев
dnf list extras
```
### Работа с репозиториями и COPR

Детальное руководство по управлению источниками ПО, использованию `config-manager` и работе с COPR приведено в разделе **[Операции с репозиториями](../Repository_Management/operations.md)**.

```bash
# Краткий список активных репозиториев
dnf repolist
```

---

### Управление модулями

Модули позволяют переключаться между разными версиями одного ПО (например, Node.js или PostgreSQL).

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

# Полный откат состояния к моменту после указанной транзакции
sudo dnf history rollback <transaction_id>
```

### Работа в автономном режиме

```bash
# Использование только локального кэша (без обращения к сети)
dnf upgrade --cacheonly

# Загрузка пакетов без установки
sudo dnf install --downloadonly <package_name>
```

### Специфика DNF 5

DNF 5 — новая версия менеджера на C++ (доступна в Fedora 41+).

```bash
# Основной синтаксис идентичен, но работает значительно быстрее
dnf5 install <package_name>

# Просмотр истории в DNF 5
dnf5 history list
```

### Проверка необходимости перезагрузки

```bash
# Проверка, требуется ли перезагрузка всей системы
dnf needs-restarting -r

# Список процессов, требующих перезапуска после обновления библиотек
dnf needs-restarting -s
```

---

## Дополнительная информация

Дополнительные сведения о плагинах и переменных окружения приведены в документе **[Продвинутые возможности DNF](./additional_info.md)**.

### Связанные документы

- **[Определения DNF](./definitions.md)** — глоссарий специфичных терминов.
- **[Основные понятия DNF](./basic_concepts.md)** — архитектура и конфигурация пакетного менеджера.
- **[Продвинутые возможности DNF](./additional_info.md)** — плагины, переменные окружения и сравнение с YUM.
- **[Обзор управления пакетами](../linux_package_management_overview.md)** — сравнение систем RPM и DEB.
- **[Зеркалирование репозиториев](../yum_dnf_repository_mirror.md)** — создание локальных зеркал YUM/DNF.
