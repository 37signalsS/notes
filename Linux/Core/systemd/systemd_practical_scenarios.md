# systemd Practical Scenarios

## Mount-юниты (`.mount`)

Mount-юниты управляют монтированием файловых систем. Имя файла должно соответствовать пути монтирования (с `/` замененными на `-`).

```ini
# /etc/systemd/system/backup.mount
[Unit]
Description=Mount Backup Disk
# Запускать после сервиса, который подготавливает диск (например, шифрование)
After=wdo.service
# Монтировать ДО запуска локальных файловых систем
Before=local-fs.target
# Требовать запуск сервиса wdo
Requires=wdo.service

[Mount]
Where=/backup
What=/dev/sdb1
Type=ext4
Options=defaults
```

**Ключевые директивы:**

* `Where=` — точка монтирования.
* `What=` — устройство или путь.
* `Type=` — тип файловой системы.
* `Options=` — опции монтирования (как в `/etc/fstab`).

## Automount-юниты (`.automount`)

Automount позволяют монтировать файловую систему **только при обращении** к ней, а не при загрузке. Это полезно для сетевых ФС, зашифрованных дисков или экономии времени загрузки.

```ini
# /etc/systemd/system/backup.automount
[Unit]
Description=Automount Backup Disk
# Зависимости должны совпадать с mount-юнитом
After=wdo.service
Requires=wdo.service

[Automount]
Where=/backup
# Время ожидания перед размонтированием (бездействия)
TimeoutIdleSec=60
```

**Активация:**

```bash
sudo systemctl enable --now backup.automount
```

> **Примечание:** При обращении к `/backup` systemd автоматически смонтирует файловую систему. После `TimeoutIdleSec` секунд бездействия она будет размонтирована.

## Service-юниты для скриптов (Type=oneshot)

Для запуска скриптов (например, бэкапов) используется `Type=oneshot`. Этот тип сообщает systemd, что процесс завершится после выполнения задачи.

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Backup Script Service
# Зависимость от mount-юнита
Requires=backup.mount
After=backup.mount

[Service]
Type=oneshot
# Запуск от имени пользователя (опционально)
User=backup_user
# Путь к скрипту
ExecStart=/usr/local/bin/backup.sh
# Перенаправление вывода в syslog (для journalctl)
StandardOutput=syslog
StandardError=syslog
# Оставаться в "active" после завершения (для зависимостей)
RemainAfterExit=yes

# Опционально: автозапуск не нужен, если запускается таймером
# [Install]
# WantedBy=multi-user.target
```

**Ключевые директивы:**

* `Type=oneshot` — скрипт выполняется один раз и завершается.
* `RemainAfterExit=yes` — сервис считается активным после завершения скрипта (полезно для зависимостей).
* `User=` — пользователь, от имени которого запускается скрипт (повышает безопасность).
* `StandardOutput=syslog` / `StandardError=syslog` — вывод записывается в syslog (доступно через `journalctl -u backup.service`).

## Target-юниты (`.target`)

Таргеты используются для группировки юнитов и управления ими как одним целым.

```ini
# /etc/systemd/system/my-app.target
[Unit]
Description=My Application Target
Documentation=man:systemd.special(7)

[Install]
WantedBy=multi-user.target
```

**Привязка юнитов к таргету:**

В другом юните (например, в `.service`) укажите таргет в секции `[Install]`:

```ini
[Install]
WantedBy=my-app.target
```
