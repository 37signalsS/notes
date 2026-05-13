# systemd Units Overview

## Определения

**Юниты (Units)** — основные объекты `systemd`, описывающие системные ресурсы, службы и действия. Каждый юнит представлен файлом конфигурации с расширением, определяющим тип.

**Таргет (Target)** — точка синхронизации, группирующая юниты. Замена уровней выполнения (runlevels) SysVinit.

> Зависимости: [systemd_dependencies.md](./systemd_dependencies.md). Структура unit-файлов: [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Типы сервисов: [systemd_service_types.md](./systemd_service_types.md).

## Базовые концепции

### Таблица типов юнитов

| Тип | Расширение | Описание | Ключевые директивы |
| :--- | :--- | :--- | :--- |
| **Service** | `.service` | Системная служба (демон) | `ExecStart=`, `Type=`, `Restart=` |
| **Socket** | `.socket` | Сокет для активации служб | `ListenStream=`, `Accept=` |
| **Target** | `.target` | Группа юнитов (состояние системы) | `WantedBy=`, `Requires=` |
| **Timer** | `.timer` | Планирование задач (замена cron) | `OnCalendar=`, `Persistent=` |
| **Mount** | `.mount` | Точка монтирования ФС | `Where=`, `What=`, `Type=` |
| **Automount** | `.automount` | Монтирование по обращению | `Where=`, `TimeoutIdleSec=` |
| **Path** | `.path` | Активация при изменении ФС | `PathExists=`, `PathChanged=` |
| **Slice** | `.slice` | Иерархия cgroups для ресурсов | `MemoryMax=`, `CPUQuota=` |

### Таргеты как замена Runlevels

Концепция `systemd` использует **таргеты** для определения состояния системы, обеспечивая обратную совместимость с уровнями выполнения (runlevels) SysVinit.

| Runlevel | Таргет | Описание |
| :--- | :--- | :--- |
| **0** | `poweroff.target` | Выключение системы. |
| **1** | `rescue.target` | Однопользовательский режим (только root, сеть не поднята). Используется для восстановления. |
| **2** | `runlevel2.target` | Многопользовательский режим (в Debian/Ubuntu — полноценный с сетью). |
| **3** | `multi-user.target` | Стандартный многопользовательский режим с сетью, без GUI. Типично для серверов. |
| **4** | `runlevel4.target` | Не используется стандартно, резерв. |
| **5** | `graphical.target` | Многопользовательский режим с графическим интерфейсом (GUI). |
| **6** | `reboot.target` | Перезагрузка системы. |

`graphical.target` зависит от `multi-user.target`, добавляя display manager и графические сервисы.

## Практические сценарии

### Проверка уровня выполнения и таргета

Для диагностики режима работы системы и проверки активности сервисов используются следующие команды:

1. **Просмотр runlevel (legacy):**
   ```bash
   runlevel
   ```
   Вывод `N 3` означает: `N` — предыдущего уровня не было (система только загрузилась), `3` — текущий уровень.

2. **Таргет по умолчанию:**
   ```bash
   systemctl get-default
   # → multi-user.target
   ```

3. **Текущее активное состояние:**
   ```bash
   systemctl list-units --type=target --state=active
   ```

### Управление таргетами

```bash
# Установить таргет по умолчанию
sudo systemctl set-default multi-user.target

# Переключиться в другой таргет (остановит невключённые юниты)
sudo systemctl isolate multi-user.target
```

### Применение в диагностике

Чаще всего runlevel проверяют при поиске причин, по которым сервис не запустился, или для проверки корректности загрузки сервера после перезагрузки. На современных системах `systemctl get-default` дает более точную информацию, но `runlevel` сохраняется для совместимости.

### Диагностика юнитов

```bash
# Статус всех юнитов (активные, failed, inactive)
systemctl list-units --type=service --all

# Только failed-юниты
systemctl --failed

# Список всех загруженных юнитов по типам
systemctl list-units --type=target

# Показать все доступные типы юнитов в системе
systemctl list-unit-files --type=service

# Полная информация о юните
systemctl show nginx.service

# Файл юнита и drop-in override-файлы
systemctl cat nginx.service
```

### Активация юнита вручную

```bash
# Запустить и включить в автозагрузку
sudo systemctl enable --now my-service.service

# Запустить одноразово без enable
sudo systemctl start my-service.service

# Проверить, включён ли юнит
systemctl is-enabled my-service.service
```

### Path-юнит: запуск при изменении файла

```ini
# /etc/systemd/system/config-watcher.path
[Unit]
Description=Watch for config changes

[Path]
PathChanged=/etc/myapp/config.yml

[Install]
WantedBy=multi-user.target
```

При изменении `config.yml` будет запущен `config-watcher.service` (с именем `.service` по имени `.path`).

## Дополнительная информация

### Соотношение с SysVinit

| SysVinit | systemd | Примечание |
| :--- | :--- | :--- |
| `/etc/inittab` | Юниты в `/etc/systemd/system/` | Конфигурация загрузки |
| `chkconfig` | `systemctl enable/disable` | Управление автозапуском |
| `service start/stop` | `systemctl start/stop` | Управление службами |
| `runlevel` | `systemctl get-default` | Текущий уровень |
| `/etc/init.d/` | `.service` юниты | Скрипты запуска |

### Связанные файлы

Зависимости: [systemd_dependencies.md](./systemd_dependencies.md). Структура unit-файлов: [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Типы сервисов: [systemd_service_types.md](./systemd_service_types.md). Таймеры: [timers.md](./timers.md). Практические сценарии: [systemd_practical_scenarios.md](./systemd_practical_scenarios.md). Обзор systemd: [overview.md](./overview.md).
