# systemd-run

## Определения

**`systemd-run`** — утилита для запуска команд в изолированных временных сервисах или скопах без необходимости создания unit-файлов. Команда становится полноценным `systemd`-юнитом с логированием через `journald`, управлением ресурсами через `cgroups` и sandbox-изоляцией.

## Базовые концепции

### Два режима работы

| Режим | Флаг | Поведение | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Service** | (по умолчанию) | Создаёт временный `.service` юнит, запускает команду асинхронно | Фоновые задачи, отложенный запуск, периодические задачи |
| **Scope** | `--scope` | Подключает текущий процесс к новому cgroup scope | Ограничение ресурсов для уже запущенных команд |

### Ключевые опции

| Опция | Описание | Пример |
| :--- | :--- | :--- |
| `-p`, `--property=` | Установить свойство юнита | `-p CPUQuota=50%` |
| `--unit=` | Имя создаваемого юнита | `--unit=my-task` |
| `--on-active=` | Запуск через время | `--on-active=30s` |
| `--on-calendar=` | Запуск по расписанию | `--on-calendar="daily"` |
| `--on-boot=` | Запуск после загрузки | `--on-boot=1min` |
| `--service-type=` | Тип сервиса | `--service-type=oneshot` |
| `--working-directory=` | Рабочая директория | `--working-directory=/opt/app` |
| `--uid=` / `--gid=` | Запуск от пользователя/группы | `--uid=www-data` |
| `--remain-after-exit` | Не удалять юнит после завершения | Для отладки |
| `--collect` | Автоматически удалять юнит после завершения | По умолчанию включено |

### Именование юнитов

Без `--unit=` systemd генерирует имя вида `run-rXXXXXXXX.service`. Для отладки и управления явно задавайте `--unit=`.

## Практические сценарии

### Ограничение CPU для сборки

```bash
systemd-run --scope -p CPUQuota=20% bash -c "make build"
```

Процесс `make build` будет ограничен 20% CPU. Результат доступен через `journalctl`.

### Одноразовая задача с отложенным запуском

```bash
systemd-run --on-active=300 --unit=delayed-cleanup /usr/local/bin/cleanup.sh
```

Команда выполнится через 5 минут. Статус: `systemctl status delayed-cleanup.service`.

### Периодическая задача (временный таймер)

```bash
systemd-run --on-calendar="hourly" --unit=hourly-cleanup /usr/local/bin/cleanup.sh
```

Создаёт временный timer + service. Существует до перезагрузки. Проверка: `systemctl list-timers --all`.

> Постоянные таймеры через файлы юнитов описаны в [timers.md](./timers.md).

### Sandbox для небезопасного скрипта

```bash
systemd-run \
  -p PrivateTmp=yes \
  -p ProtectSystem=strict \
  -p NoNewPrivileges=yes \
  -p PrivateDevices=yes \
  -p ProtectHome=yes \
  ./untrusted-script.sh
```

Изоляция: отдельный `/tmp`, защита ФС, запрет повышения привилегий, нет доступа к устройствам и `/home`.

### Запуск от другого пользователя

```bash
systemd-run --uid=www-data --gid=www-data -p WorkingDirectory=/var/www /usr/local/bin/app-init.sh
```

### Отладка утечки ресурсов

```bash
# Запуск с логированием и последующим анализом
systemd-run --unit=memory-test -p MemoryMax=2G ./memory-intensive-task

# После завершения — просмотр логов и cgroup-статистики
journalctl -u memory-intensive-task -e
systemctl show memory-test.service | grep -i memory
```

### Временный сервис с сохранением юнита после завершения

```bash
systemd-run --remain-after-exit --unit=post-deploy-check /usr/local/bin/check.sh
```

Юнит не удаляется после завершения — можно проверить `systemctl status post-deploy-check` и логи.

## Дополнительная информация

### Отличия от прямого запуска команд

| Характеристика | Прямой запуск (`./script.sh`) | `systemd-run` |
| :--- | :--- | :--- |
| Логирование | stdout/stderr | `journald` (централизованное) |
| Управление ресурсами | Ручное (`ulimit`, `cgexec`) | Встроенное (`-p CPUQuota=`, `-p MemoryMax=`) |
| Изоляция | Нет | Sandbox (`PrivateTmp`, `ProtectSystem`, и др.) |
| Мониторинг | Нет | `systemctl status`, `journalctl -u` |
| Жизненный цикл | Завершение = потеря | `--remain-after-exit`, автоочистка |

### Связанные файлы

Механизм таймеров с файлами юнитов — в [timers.md](./timers.md). Логирование через `journald` — в [journald.md](../../SystemAdministration/Logging/journald.md). Контрольные группы и ресурсы — в [cgroups.md](../cgroups.md). Обзор systemd — в [overview.md](./overview.md).
