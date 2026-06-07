# Обзор юнитов systemd (systemd Units Overview)

## Определения

* **Юниты (Units)** — это базовые объекты управления в системе инициализации `systemd`. Каждый юнит описывает определенный системный ресурс, службу или действие. Юниты представляются текстовыми конфигурационными файлами с расширением, определяющим их тип (например, `.service`, `.timer`).
* **Таргет (Target)** — специальный тип юнита, который служит точкой синхронизации и группировки других юнитов. Таргеты используются для определения состояния системы (целевого режима работы).

## Основные концепции

### Типы юнитов

`systemd` управляет различными типами ресурсов через специализированные юниты:

| Тип юнита | Расширение | Назначение | Ключевые параметры |
| :--- | :--- | :--- | :--- |
| **Service** | `.service` | Управление системной службой (демоном). | `ExecStart`, `Restart` |
| **Socket** | `.socket` | Активация служб при обращении к сетевому сокету или IPC (Inter-Process Communication). | `ListenStream` |
| **Target** | `.target` | Группировка юнитов (аналог уровней выполнения). | `Requires`, `After` |
| **Timer** | `.timer` | Планировщик задач (альтернатива cron). | `OnCalendar` |
| **Mount** | `.mount` | Управление точкой монтирования файловой системы. | `What`, `Where` |
| **Automount** | `.automount` | Динамическое монтирование при обращении к пути. | `TimeoutIdleSec` |
| **Swap** | `.swap` | Управление файлом или разделом подкачки. | `What` |
| **Device** | `.device` | Устройство, опознанное ядром (генерируется udev). | — |
| **Path** | `.path` | Активация службы при изменении файлов или директорий. | `PathModified` |
| **Slice** | `.slice` | Иерархическое управление ресурсами через cgroups (Control Groups). | `MemoryMax`, `CPUQuota` |
| **Scope** | `.scope` | Внешние процессы, не запущенные через `systemd`. | — |

### Таргеты и уровни выполнения (Runlevels)

`systemd` заменяет устаревшую концепцию уровней выполнения (runlevels) из SysVinit на более гибкую систему таргетов.

| Runlevel | Таргет systemd | Описание состояния |
| :--- | :--- | :--- |
| **0** | `poweroff.target` | Завершение работы и выключение питания. |
| **1** | `rescue.target` | Режим восстановления (однопользовательский, сеть отключена). |
| **3** | `multi-user.target` | Многопользовательский режим без графики (стандарт для серверов). |
| **5** | `graphical.target` | Многопользовательский режим с GUI (Graphical User Interface). |
| **6** | `reboot.target` | Перезагрузка ОС (Операционная Система). |

`graphical.target` является надстройкой над `multi-user.target`, добавляя графическую оболочку и соответствующие службы.

## Практические сценарии

### Определение текущего состояния системы

Для диагностики активного режима работы и настроек по умолчанию используются следующие команды:

1. **Проверка текущего таргета (и уровня выполнения):**

    ```bash
    runlevel
    ```

   # → N 3 (предыдущего уровня нет, текущий — 3)

2. **Просмотр таргета по умолчанию:**

    ```bash
    systemctl get-default
    ```

   # → multi-user.target

3. **Список всех активных таргетов:**

    ```bash
    systemctl list-units --type=target --state=active
    ```

   # → UNIT                LOAD   ACTIVE SUB    DESCRIPTION

   # → multi-user.target   loaded active active Multi-User System

   # → network.target      loaded active active Network

### Управление юнитами и их типами

```bash
# Список всех загруженных юнитов (служб)
systemctl list-units --type=service
# → UNIT            LOAD   ACTIVE SUB     DESCRIPTION
# → nginx.service   loaded active running A high performance web server

# Просмотр всех установленных юнит-файлов (включая неактивные)
systemctl list-unit-files --type=service
# → UNIT FILE                    STATE           VENDOR PRESET
# → ssh.service                  enabled         enabled
# → ufw.service                  disabled        enabled

# Установка графического режима по умолчанию
sudo systemctl set-default graphical.target
# → Removed /etc/systemd/system/default.target.
# → Created symlink /etc/systemd/system/default.target -> /lib/systemd/system/graphical.target.

# Мгновенное переключение режима работы (без перезагрузки)
sudo systemctl isolate multi-user.target
# → остановка графических служб и переход в текстовый режим
```

## Дополнительная информация

### Иерархия управления ресурсами

Юниты типа `.slice` позволяют объединять службы в группы для совместного ограничения ресурсов CPU (Central Processing Unit) и RAM (Random Access Memory). Подробнее см. в разделе [Control Groups (cgroups)](../cgroups.md).

### См. также

* [Структура юнит-файла](./systemd_unit_file_structure.md) — детальный разбор секций и параметров.
* [Зависимости юнитов](./systemd_dependencies.md) — механизмы `Requires`, `Wants` и `After`.
* [Таймеры systemd](./timers.md) — запуск юнитов по расписанию.
* [Управление службами (systemctl)](./service_management.md) — команды для повседневной работы.
