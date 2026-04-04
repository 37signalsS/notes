# systemd Practical Scenarios

## Определения

**Практические сценарии systemd** — типовые конфигурации юнитов для решения распространённых задач: монтирование ФС, запуск скриптов, группировка сервисов. Каждый сценарий демонстрирует корректную комбинацию директив зависимостей, типов сервисов и секций.

> Справочник по зависимостям: [systemd_dependencies.md](./systemd_dependencies.md). Структура unit-файлов: [systemd_unit_file_structure.md](./systemd_unit_file_structure.md).

## Базовые концепции

### Именование юнитов

Имя файла юнита **обязано** соответствовать управляемому ресурсу. Для `.mount` и `.automount` путь монтирования преобразуется: `/` заменяется на `-`, убирается ведущий `/`.

| Путь монтирования | Имя юнита |
| :--- | :--- |
| `/backup` | `backup.mount` |
| `/mnt/data/share` | `mnt-data-share.mount` |
| `/var/lib/app/data` | `var-lib-app-data.mount` |

> Нарушение правила приведёт к ошибке: systemd не сможет сопоставить юнит с ресурсом.

### Типичные паттерны зависимостей

| Сценарий | Паттерн |
| :--- | :--- |
| Монтирование после подготовки диска | `Requires=` + `After=` (подготавливающий сервис) |
| Скрипт после монтирования | `Requires=` + `After=` (`.mount` юнит) |
| Группировка сервисов | `WantedBy=` в `[Install]`, `PartOf=` в сервисах |

## Практические сценарии

### 1. Mount-юнит (`.mount`)

Управление монтированием файловых систем. Подробное руководство с зависимостями — в [systemd_mount.md](../../../Linux/FileSystems/mounting/scenarios/systemd_mount.md).

```ini
# /etc/systemd/system/backup.mount
[Unit]
Description=Mount Backup Disk
# Запуск после сервиса подготовки диска (например, расшифровка LUKS)
After=systemd-cryptsetup@backup.service
Requires=systemd-cryptsetup@backup.service
# Монтировать ДО локальных файловых систем
Before=local-fs.target

[Mount]
Where=/backup
What=/dev/mapper/backup
Type=ext4
Options=defaults
```

**Ключевые директивы:** `Where=` — точка монтирования, `What=` — устройство, `Type=` — ФС, `Options=` — опции (как в `/etc/fstab`).

### 2. Automount-юнит (`.automount`)

Монтирование **по обращению**, а не при загрузке. Полезно для сетевых ФС и зашифрованных дисков.

```ini
# /etc/systemd/system/backup.automount
[Unit]
Description=Automount Backup Disk
# Зависимости должны совпадать с mount-юнитом
After=systemd-cryptsetup@backup.service
Requires=systemd-cryptsetup@backup.service

[Automount]
Where=/backup
# Размонтирование после бездействия
TimeoutIdleSec=60
```

```bash
# Активация (enable --only автомонтирование, не mount)
sudo systemctl enable --now backup.automount
```

> При обращении к `/backup` systemd автоматически смонтирует ФС. После `TimeoutIdleSec` секунд бездействия — размонтирует.

### 3. Service-юнит для скриптов (`Type=oneshot`)

Для одноразовых задач (бэкапы, миграции, инициализация).

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Backup Script Service
Requires=backup.mount
After=backup.mount

[Service]
Type=oneshot
User=backup_user
ExecStart=/usr/local/bin/backup.sh
StandardOutput=journal
StandardError=journal
# Сервис остаётся «active» после завершения (для зависимостей)
RemainAfterExit=yes
```

**Ключевые директивы:** `Type=oneshot` — процесс завершается после выполнения, `RemainAfterExit=yes` — статус остаётся active (полезно для зависимостей), `User=` — запуск от имени пользователя (безопасность).

### 4. Target-юнит (`.target`)

Группировка юнитов для совместного управления.

```ini
# /etc/systemd/system/my-app.target
[Unit]
Description=My Application Target

[Install]
WantedBy=multi-user.target
```

Привязка сервисов к таргету — в их `[Install]`:

```ini
[Install]
WantedBy=my-app.target
```

```bash
# Запустить все сервисы, привязанные к таргету
sudo systemctl start my-app.target

# Остановить все сервисы с PartOf=my-app.target
sudo systemctl stop my-app.target
```

## Дополнительная информация

### Диагностика

```bash
# Дерево зависимостей юнита
systemctl list-dependencies backup.mount

# Почему юнит не запустился
systemctl status backup.mount
journalctl -u backup.mount -e

# Какие юниты ждут указанный (реверсивные зависимости)
systemctl list-dependencies --reverse backup.mount
```

### Связанные файлы

Детальное руководство по mount/automount — в [systemd_mount.md](../../../Linux/FileSystems/mounting/scenarios/systemd_mount.md). Зависимости systemd — в [systemd_dependencies.md](./systemd_dependencies.md). Структура unit-файлов — в [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Типы сервисов — в [systemd_service_types.md](./systemd_service_types.md).
