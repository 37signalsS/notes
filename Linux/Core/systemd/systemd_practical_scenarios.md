# Практические сценарии systemd

## Определения

**Практические сценарии systemd** — это типовые наборы конфигураций для решения прикладных задач администрирования: от автоматического монтирования дисков до создания сложных цепочек зависимых сервисов. Каждый сценарий демонстрирует оптимальную комбинацию типов юнитов (units) и директив для обеспечения отказоустойчивости и корректного порядка запуска в Операционной Системе (ОС).

## Основные концепции

### Правила именования юнитов монтирования

Для юнитов типов `.mount` и `.automount` имя файла **обязано** точно соответствовать пути к точке монтирования в Файловой Системе (ФС).

* Слэши (`/`) заменяются на дефисы (`-`).
* Ведущий слэш игнорируется.

| Точка монтирования | Имя юнит-файла |
| :--- | :--- |
| `/backup` | `backup.mount` |
| `/mnt/data/share` | `mnt-data-share.mount` |
| `/var/lib/docker` | `var-lib-docker.mount` |

> **Внимание**: Если имя файла не совпадает с путём монтирования, `systemd` не сможет активировать юнит.

### Типовые паттерны зависимостей

1. **Подготовка ресурса**: Сначала выполняется сервис (например, расшифровка раздела LUKS), затем монтируется диск.
2. **Цепочка выполнения**: Сначала монтируется диск, затем запускается скрипт обработки данных.
3. **Группировка**: Объединение нескольких микросервисов под единый `.target` для массового управления.

## Практические сценарии

### 1. Монтирование файловой системы (.mount)

Используется для управления дисками через `systemd` вместо классического `/etc/fstab`.

```ini
# /etc/systemd/system/mnt-storage.mount
[Unit]
Description=Mount External Storage
# Ждем расшифровки диска
Requires=systemd-cryptsetup@storage.service
After=systemd-cryptsetup@storage.service

[Mount]
What=/dev/mapper/storage
Where=/mnt/storage
Type=ext4
Options=defaults,noatime

[Install]
WantedBy=multi-user.target
```

Детальное руководство по всем параметрам монтирования: [Systemd mount units](../../FileSystems/mounting/scenarios/systemd_mount.md).

### 2. Динамическое монтирование (.automount)

Юнит активирует точку монтирования только в момент обращения к ней (например, при выполнении `cd /mnt/storage`).

```ini
# /etc/systemd/system/mnt-storage.automount
[Unit]
Description=Automount Storage on Access

[Automount]
Where=/mnt/storage
# Размонтировать через 5 минут бездействия
TimeoutIdleSec=300

[Install]
WantedBy=multi-user.target
```

```bash
# Активация автомонтирования
sudo systemctl enable --now mnt-storage.automount
# → Created symlink /etc/systemd/system/multi-user.target.wants/mnt-storage.automount ...
```

### 3. Резервное копирование по событию (Type=oneshot)

Запуск скрипта, который должен завершиться перед тем, как система посчитает задачу выполненной.

```ini
# /etc/systemd/system/daily-backup.service
[Unit]
Description=Daily Backup Script
# Запуск только после успешного монтирования хранилища
Requires=mnt-storage.mount
After=mnt-storage.mount

[Service]
Type=oneshot
User=backup_user
ExecStart=/usr/local/bin/backup.sh
# Сохранять статус active после выхода, чтобы зависимые юниты видели успех
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

### 4. Создание пользовательского таргета (.target)

Позволяет объединить группу сервисов проекта для одновременного запуска или остановки.

```ini
# /etc/systemd/system/my-project.target
[Unit]
Description=My Full Project Stack
AllowIsolate=yes

[Install]
WantedBy=multi-user.target
```

**Привязка сервиса к таргету**:
В юнит-файле конкретной службы добавьте:

```ini
[Unit]
PartOf=my-project.target

[Install]
WantedBy=my-project.target
```

## Дополнительная информация

### Диагностика сложных связей

```bash
# Проверить статус монтирования
systemctl status mnt-storage.mount
# → ● mnt-storage.mount - Mount External Storage
# →    Active: active (mounted) ...

# Посмотреть, какие юниты зависят от хранилища (реверсивные зависимости)
systemctl list-dependencies --reverse mnt-storage.mount
# → mnt-storage.mount
# → └─daily-backup.service

# Анализ логов конкретной задачи
journalctl -u daily-backup.service -e
# → -- Logs begin at ... --
# → Jun 07 10:00:01 host backup.sh[1234]: Backup completed successfully.
```

### См. также

* [Детальное руководство по монтированию](../../FileSystems/mounting/scenarios/systemd_mount.md)
* [Управление зависимостями юнитов](./systemd_dependencies.md)
* [Структура юнит-файла](./systemd_unit_file_structure.md)
* [Типы сервисов systemd](./systemd_service_types.md)
