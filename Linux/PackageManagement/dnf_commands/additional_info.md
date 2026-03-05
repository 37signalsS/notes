# DNF: Дополнительная информация

## Переменные окружения DNF

| Переменная | Назначение |
| :--- | :--- |
| `DNF_CONF_FILE` | Путь к файлу конфигурации |
| `DNF_PLUGIN_PATH` | Путь к плагинам |
| `RELEASEVER` | Версия дистрибутива (подставляется в URL репозиториев) |

## Плагины DNF

| Плагин | Назначение |
| :--- | :--- |
| `dnf-plugins-core` | Базовые плагины (config-manager, needs-restarting) |
| `dnf-plugin-versionlock` | Блокировка версий пакетов |
| `dnf-plugin-post-transaction-actions` | Действия после транзакций |
| `dnf-plugin-debuginfo-install` | Установка отладочной информации |

### Установка и использование плагинов

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

## Сравнение DNF и YUM

| Команда YUM | Команда DNF | Примечание |
| :--- | :--- | :--- |
| `yum update` | `dnf update` | Полная совместимость |
| `yum install` | `dnf install` | Полная совместимость |
| `yum remove` | `dnf remove` | Полная совместимость |
| `yum search` | `dnf search` | Полная совместимость |
| `yum provide` | `dnf provide` | Полная совместимость |
| `yum history` | `dnf history` | Улучшенная функциональность |
| `yum groupinstall` | `dnf group install` | Изменён синтаксис |
| — | `dnf module` | Новая функция в DNF |

## Связанные темы

* **[Обзор управления пакетами](./linux_package_management_overview.md)** — базовые концепции
* **[Управление репозиториями DNF](./dnf_repository_management.md)** — настройка репозиториев
* **[Анализ и получение пакетов](./package_analysis.md)** — изучение метаданных и содержимого
* **[База данных пакетов](./package_database.md)** — история транзакций и восстановление
* **[Локальное зеркало репозитория](./local_repository_mirror.md)** — создание зеркал для YUM/DNF

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины
* **[Основные понятия](./basic_concepts.md)** — преимущества, конфигурация, структура
* **[Практические сценарии](./practical_scenarios.md)** — базовые операции, поиск, группы, модули

---

*Этот файл является частью декомпозированной документации. Исходный файл: [dnf_commands.md](../dnf_commands.md)*
