# Таймеры systemd: Планирование задач

## Определения

* **systemd Timers** — системный механизм планирования задач, встроенный в `systemd`. Является современной заменой `cron`. Таймер — это юнит типа `.timer`, который активирует связанный с ним `.service` юнит по заданному расписанию или событию.
* **Монотонные таймеры (Monotonic Timers)** — запускаются относительно определенного события в системе (загрузка, старт таймера, завершение предыдущей задачи).
* **Календарные таймеры (Realtime Timers)** — запускаются в фиксированное время (аналог cron). Используют директиву `OnCalendar=`.
* **Связанный сервис (Linked Service)** — `.service` юнит, который активируется таймером. Если имя сервиса совпадает с именем таймера (до расширения), связь устанавливается автоматически.
* **Таргет `timers.target`** — группа, к которой присоединяются таймеры при включении (`WantedBy=timers.target`). Это гарантирует, что таймер запустится после готовности системы.

## Основные концепции

### Архитектура и жизненный цикл

При запуске таймера systemd выполняет следующую последовательность:
1. **Активация:** по событию (календарное время, загрузка, старт таймера) `systemd` проверяет условия в секции `[Timer]`.
2. **Проверка перекрытия:** если сервис уже выполняется, таймер не запускает его повторно (если не задано иное).
3. **Запуск сервиса:** активируется связанный `.service` юнит с учетом зависимостей (`After=`, `Requires=`).
4. **Журналирование:** все stdout/stderr сервиса направляются в `journald` с тегами, связанными с именем юнита.
5. **Статус:** таймер остается активным и ждет следующего события.

> **Важно:** Таймер не выполняет полезную работу самостоятельно — он является триггером для запуска существующего `.service` юнита. Вся логика, параметры окружения и изоляция описываются в сервисе, а не в таймере.

### Структура unit-файла таймера

Таймер состоит минимум из двух файлов: сам таймер (`.timer`) и сервис (`.service`). Если сервис имеет то же базовое имя, что и таймер, systemd связывает их автоматически.

**Пример полной структуры файла таймера** (`/etc/systemd/system/backup.timer`):
```ini
[Unit]
Description=Ежедневный запуск резервного копирования
Requires=backup.service

[Timer]
OnCalendar=daily
AccuracySec=1h
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
```

**Секция `[Timer]`** поддерживает уникальные директивы:
| Директива | Тип | Описание |
| :--- | :--- | :--- |
| `OnCalendar=` | Календарный | Абсолютное время по формату `ДеньНедели ГГГГ-ММ-ДД ЧЧ:ММ:СС`. |
| `OnActiveSec=` | Монотонный | Задержка после активации самого таймера. |
| `OnBootSec=` | Монотонный | Задержка после загрузки системы. |
| `OnStartupSec=` | Монотонный | Задержка после старта systemd (точнее для контейнеров). |
| `OnUnitActiveSec=` | Монотонный | Интервал после последнего успешного запуска сервиса. |
| `OnUnitInactiveSec=` | Монотонный | Интервал после последнего завершения сервиса. |
| `AccuracySec=` | Точность | Окно отклонения для coalescing пробуждений (по умолчанию 1 минута). |
| `Persistent=` | Boolean | Выполнить пропущенную задачу после перезагрузки. |
| `WakeSystem=` | Boolean | Разбудить систему из сна для выполнения задачи. |
| `RandomizedDelaySec=` | Задержка | Случайная задержка для разнесения нагрузки (thundering herd protection). |

### Интеграция с сервисами

Таймер наследует механизмы безопасности и управления ресурсами из связанного `.service` юнита:
* **Изоляция:** `PrivateTmp`, `ProtectSystem`, `ProtectHome`, `PrivateDevices` применяются к процессу, запущенному таймером.
* **Ресурсы:** `MemoryMax`, `CPUQuota`, `IOWeight` ограничивают потребление именно задачи, а не самого таймера.
* **Зависимости:** таймер может требовать наличие сети (`Wants=network-online.target`), монтирования или других сервисов.

### Сравнение с Cron

| Характеристика | Cron | systemd Timers |
| :--- | :--- | :--- |
| **Точность** | До минуты | До микросекунды |
| **Логирование** | stdout/stderr (часто в почту) | Родная интеграция с `journald` |
| **Зависимости** | Отсутствуют | Полная поддержка `After=`, `Requires=`, `Wants=` |
| **Ресурсы** | Минимальные (`nice`/`ionice`) | Лимиты `cgroups` (CPU, Memory, I/O) |
| **Надёжность** | `anacron` (для пропущенных) | `Persistent=true` (встроенный механизм) |
| **Изоляция** | Выполняется в шелле пользователя | Изолированный Sandbox (Namespaces, Seccomp) |

### Типы триггеров

#### 1. Монотонные (относительные)
Используются для задач, которые должны выполняться периодически или с задержкой после старта.

| Директива | Точка отсчёта | Применение |
| :--- | :--- | :--- |
| `OnActiveSec=` | Активация самого `.timer` | Разовая задержка после старта таймера. |
| `OnBootSec=` | Загрузка системы | Задачи, выполняемые сразу после старта ОС. |
| `OnStartupSec=` | Запуск менеджера systemd | Аналогично `OnBootSec`, но точнее для контейнеров. |
| `OnUnitActiveSec=` | Последняя активация `.service` | Циклический запуск (например, каждые 15 минут). |
| `OnUnitInactiveSec=` | Последнее завершение `.service` | Запуск после периода «покоя». |

#### 2. Календарные (абсолютные)
Используют синтаксис `OnCalendar=`. Формат: `ДеньНедели ГГГГ-ММ-ДД ЧЧ:ММ:СС`.

* **Списки и диапазоны:** `Mon,Wed,Fri` или `Mon..Fri`.
* **Шаги:** `*:0/15` (каждые 15 минут).
* **Специфические значения:** `~` (последний день месяца).
* **Временные зоны:** Можно указать зону в конце, например `12:00 UTC` или `12:00 Europe/Moscow`.

### Энергосбережение и точность

* **`AccuracySec=`** — окно допустимого отклонения (по умолчанию 1 минута). Позволяет ядру объединять (coalescing) пробуждения системы для нескольких таймеров, что критично для ноутбуков и мобильных устройств.
* **`WakeSystem=true`** — если система находится в режиме сна, таймер «разбудит» её для выполнения задачи.

### Надежность (Persistence)

Директива **`Persistent=true`** заставляет systemd сохранять время последнего успешного запуска на диске (в `/var/lib/systemd/timers/`). Если система была выключена в момент планового запуска, задача будет выполнена немедленно после следующей загрузки.

## Практические сценарии

### 1. Ежедневный бэкап с ограничением ресурсов

**Файл сервиса** (`/etc/systemd/system/backup.service`):
```ini
[Unit]
Description=Daily Backup Service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
# Изоляция и лимиты
MemoryMax=1G
CPUQuota=20%
PrivateTmp=yes
ProtectSystem=strict
```

**Файл таймера** (`/etc/systemd/system/backup.timer`):
```ini
[Unit]
Description=Run backup daily

[Timer]
OnCalendar=daily
Persistent=true
# Случайная задержка до 30 минут (разнос нагрузки в кластере)
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now backup.timer
```

### 2. Временные (Transient) таймеры

Создание таймеров без файлов конфигурации описано в [systemd-run](./systemd_run.md#динамические-таймеры).

### 3. Пользовательские таймеры (User Timers)

Таймеры могут работать в контексте пользователя. Файлы размещаются в `~/.config/systemd/user/`.

```bash
# Включение таймера для текущего пользователя
systemctl --user enable --now my-task.timer

# ВАЖНО: Чтобы таймеры работали без активной сессии пользователя, 
# необходимо включить lingering:
sudo loginctl enable-linger username
```

### 4. Предотвращение параллельного запуска (Overlap Protection)

Для критичных задач (бэкапы, миграции), которые не могут выполняться одновременно, используйте следующие паттерны:

**Вариант A: `Condition...` с lock-файлом**
```ini
[Unit]
ConditionPathExists=!/var/run/backup.lock

[Service]
Type=oneshot
ExecStartPre=/usr/bin/touch /var/run/backup.lock
ExecStartPost=/usr/bin/rm -f /var/run/backup.lock
ExecStart=/usr/local/bin/backup.sh
```

**Вариант B: `ExecCondition=` (v243+)**
```ini
[Service]
Type=oneshot
ExecCondition=/usr/bin/flock -n /var/run/backup.lock true
ExecStart=/usr/local/bin/backup.sh
```

**Вариант C: `RefuseManualStart=` в таймере**
```ini
[Timer]
OnCalendar=daily
RefuseManualStart=yes
```
Запрещает ручной запуск таймера, оставляя только планируемое выполнение.

### 5. Ротация логов через timer

Пример реального сценария для ротации логов приложения, которое не использует `logrotate`:
```ini
[Unit]
Description=Rotate application logs

[Service]
Type=oneshot
ExecStart=/usr/local/bin/rotate-app-logs.sh

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
```

### 6. Обновление сертификатов TLS

Автоматизация обновления через `certbot` или кастомный скрипт:
```ini
[Unit]
Description=Renew TLS certificates

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet
# Уведомление systemd о необходимости перезагрузки nginx
ExecStartPost=/bin/systemctl reload nginx.service

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
AccuracySec=10min

[Install]
WantedBy=timers.target
```

### 7. Обслуживание базы данных

Регулярное выполнение `VACUUM` или `ANALYZE` в PostgreSQL:
```ini
[Unit]
Description=Weekly PostgreSQL maintenance

[Service]
Type=oneshot
User=postgres
ExecStart=/usr/bin/vacuumdb --all --analyze

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=2h

[Install]
WantedBy=timers.target
```

### 8. Мониторинг и Health Checks

Проверка доступности сервисов и запись результата в `journald`:
```ini
[Unit]
Description=HTTP endpoint health check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/health-check.sh
# Стандартный вывод будет записан в journald

[Timer]
OnCalendar=*:00/5
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
```

### 9. Очистка временных файлов и артефактов CI/CD

Удаление старых файлов из `/tmp` или артефактов сборки:
```ini
[Unit]
Description=Cleanup old build artifacts

[Service]
Type=oneshot
ExecStart=/usr/bin/find /var/builds -type f -mtime +30 -delete

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 10. Throttling и разнесение нагрузки (Thundering Herd Protection)

В кластерных средах одновременный запуск одинаковых таймеров на множестве хостов создает всплески нагрузки на shared-сервисы (базы, API, хранилища). Для предотвращения этого используют:

```ini
[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=15min
AccuracySec=5min
```

`RandomizedDelaySec` добавляет случайную задержку к каждому запуску. В сочетании с `AccuracySec` это позволяет ядру коалесцировать (объединять) пробуждения и снижать нагрузку.

## Диагностика и управление

### Основные команды

```bash
# Список всех активных таймеров и время следующего запуска
systemctl list-timers

# Проверка статуса конкретного таймера
systemctl status my-task.timer

# Просмотр логов срабатывания таймера и сервиса
journalctl -u my-task.timer -u my-task.service
```

### Проверка расписания

Утилита `systemd-analyze` позволяет проверить синтаксис `OnCalendar` и увидеть ближайшие даты срабатывания.

```bash
systemd-analyze calendar "Mon..Fri 10:00:00"
# →  Next elapse: Mon 2024-06-10 10:00:00 UTC
# →  From now: 2 days left
```

### Проверка корректности работы

```bash
# 1. Убедитесь, что таймер активен
systemctl is-active backup.timer

# 2. Просмотр времени следующего запуска
systemctl list-timers backup.timer

# 3. Проверка, что сервис был запущен в ожидаемое время
journalctl -u backup.service --since "2 hours ago"

# 4. Валидация unit-файлов
systemd-analyze verify backup.timer backup.service
```

## Диагностика и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Таймер не запускается | Сервис не указан или имеет неверное имя. | Убедитесь, что `backup.service` существует и имеет то же базовое имя, что и `backup.timer`, или укажите `Unit=backup.service` в секции `[Timer]`. |
| Сервис запускается, но «пропускает» расписание | `Persistent=false` и система была выключена в момент запуска. | Включите `Persistent=true` или проверьте логи загрузки (`journalctl -b`). |
| Несколько экземпляров сервиса одновременно | Таймер сработал до завершения предыдущего запуска. | Добавьте `Condition...` или `ExecCondition=` с lock-файлой, либо установите `RefuseManualStart=yes` и `Condition...` в сервисе. |
| Таймер срабатывает в неправильное время | Неверный часовой пояс или формат `OnCalendar`. | Используйте `systemd-analyze calendar "<value>"` для проверки. Убедитесь, что на хосте настроен правильный `timedatectl set-timezone`. |
| `OnCalendar=daily` срабатывает в полночь, а нужно в 02:00 | Используется сокращение `daily` вместо явного времени. | Замените на `OnCalendar=*-*-* 02:00:00`. |
| Высокая нагрузка при старте системы | Множество таймеров с `OnBootSec` запускаются одновременно. | Добавьте `RandomizedDelaySec=` или используйте `After=network-online.target` для постепенной активации. |
| Задача не выполняется в周末 | В `OnCalendar` указан диапазон, исключающий выходные. | Проверьте синтаксис: `Mon..Fri` вместо `*..*`. |

## Рекомендации по эксплуатации (Best Practices)

1. **Используйте `Persistent=true` для критичных задач:** Это гарантирует выполнение пропущенных задач после перезагрузки системы.
2. **Устанавливайте `AccuracySec=` осознанно:** Для точного расписания (например, сертификаты) уменьшайте окно до 1 минуты или менее. Для фоновых задач оставляйте 1 минуту или больше для coalescing.
3. **Применяйте `RandomizedDelaySec=` в кластерах:** Защищает shared-инфраструктуру от одновременной нагрузки при старте системы.
4. **Никогда не пишите логи в stdout без `journald`:** systemd перенаправляет вывод автоматически, но избегайте дублирования в файлы.
5. **Используйте `RefuseManualStart=` и `RefuseManualStop=`** для таймеров, которые не должны запускаться вручную (соблюдение политики).
6. **Валидируйте синтаксис `OnCalendar`** через `systemd-analyze calendar` перед деплоем.
7. **Для oneshot-сервисов указывайте `Type=oneshot`** и `RemainAfterExit=no`, чтобы systemd корректно отслеживал завершение.
8. **Изолируйте сервисы таймеров:** Применяйте `User=`, `Group=`, `ProtectSystem=`, `PrivateTmp=yes` к связанному `.service` юниту.

## Ограничения

* Таймеры не предназначены для задач с высокой частотой (< 1 минуты) — используйте `watch` или специализированные демоны.
* `OnCalendar=daily` всегда означает полночь. Для другого времени используйте явный формат.
* В пользовательских таймерах (`--user`) `Persistent=true` работает только при включенном `lingering`.
* Некоторые дистрибутивы (например, RHEL/CentOS) используют устаревшие версии systemd с ограниченной поддержкой `AccuracySec=`.
* Монотонные таймеры (`OnBootSec=`, `OnUnitActiveSec=`) сбрасываются при каждой перезагрузке или перезапуске таймера — они не substitutes для календарных планировщиков.

## Дополнительная информация

### См. также

* [Временные задачи через systemd-run](./systemd_run.md) — детальное описание динамических таймеров.
* [Обзор юнитов systemd](./systemd_units_overview.md) — общая структура юнитов.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — работа с логами выполнения.
