# Работа с DNF (Dandified YUM)

## Определения

DNF (Dandified YUM) — это современный высокоуровневый пакетный менеджер для RPM-based дистрибутивов. Является заменой устаревшего `yum`, сохраняя с ним обратную совместимость (команда `yum` обычно является символической ссылкой на `dnf`).

## Основные команды DNF

```bash
# Обновление информации о репозиториях (метаданных)
sudo dnf check-update

# Обновление всех пакетов до最新 versions
sudo dnf update
# или
sudo dnf upgrade

# Обновление конкретного пакета
sudo dnf update <package_name>

# Установка пакета
sudo dnf install <package_name>

# Удаление пакета
sudo dnf remove <package_name>

# Поиск пакета по имени или описанию
dnf search <keyword>

# Информация о пакете
dnf info <package_name>

# Показать зависимости пакета
dnf deplist <package_name>

# Скачать пакет без установки
dnf download <package_name>

# Установить скачанный пакет (с зависимостями)
sudo dnf install ./package.rpm

# Проверить, есть ли обновления
dnf check-update

# Определить, какому пакету принадлежит файл (до установки)
dnf provides '*/<file_name>'
dnf provides <command_name>

# Очистить кэш
sudo dnf clean all
```

## Работа с группами пакетов

Группы позволяют установить набор пакетов, объединенных общей целью (например, "Development Tools").

```bash
# Список доступных групп
dnf grouplist

# Информация о группе
dnf group info <group_name>

# Установить группу
sudo dnf group install <group_name>

# Удалить группу
sudo dnf group remove <group_name>
```

## Работа с модулями (Stream)

Модули позволяют управлять параллельными версиями ПО (например, несколько версий Python или Node.js).

```bash
# Список модулей
dnf module list

# Информация о модуле
dnf module info <module_name>

# Включить модуль (с указанием стрима)
sudo dnf module enable <module_name>:<stream>

# Установить модуль
sudo dnf module install <module_name>:<stream>

# Сбросить модуль в состояние по умолчанию
sudo dnf module reset <module_name>
```

## История операций

DNF ведет историю всех операций, что позволяет откатывать изменения.

```bash
# История операций
dnf history

# Детали конкретной операции
dnf history info <transaction_id>

# Откатить операцию (удалить установленное или восстановить удаленное)
sudo dnf history undo <transaction_id>

# Повторить операцию
sudo dnf history redo <transaction_id>
```

## Определение необходимости перезагрузки

После обновления системных библиотек или ядра может потребоваться перезагрузка.

```bash
# Показать, какие сервисы/процессы требуют перезагрузки
dnf needs-restarting
```

---

См. также: [Обзор управления пакетами в Linux](./linux_package_management_overview.md)
