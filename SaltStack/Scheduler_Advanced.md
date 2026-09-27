# Salt Scheduler продвинутый

## Определения

- **Schedule**: Встроенный планировщик Salt, работающий на Миньоне (Pull-модель) или Мастере, выполняющий функции по расписанию.
- **Execution Window**: Окно времени, в которое разрешено выполнение задачи. Определяется параметрами `range_start` и `range_end`.
- **Cron Expression**: Формат расписания в стиле cron ( `minute`, `hour`, `day`, `month`, `dayweek`), доступный в Salt scheduler.
- **Jitter**: Случайная задержка перед выполнением задачи для предотвращения «шторма» одновременных запусков на тысячах миньонах.
- **loop_interval**: Интервал (в секундах) между циклами проверки расписания Salt-планировщика (по умолчанию 60 секунд).
- **schedule.disable / schedule.enable**: Глобальное отключение/включение планировщика на миньоне.
- **Orchestrate Schedule**: Запуск оркестрации через scheduler на мастере (Pull-модель для master-level операций).
- **Until/While**: Условные конструкции, определяющие когда задача должна/не должна выполняться.

---

## Основные концепции

### Типы расписания

| Тип | Описание | Пример |
|:---|:---|:---|
| `function` | Вызов execution-модуля | `state.highstate` |
| `state` | Применение конкретного SLS | `state.apply nginx` |
| `runner` | Запуск runner на мастере | `runner.state.orchestrate` |
| `wheel` | Операция управления мастером | `wheel.key.list` |
| `cmd` | Вызов системной команды | `/usr/bin/backup.sh` |

### Параметры расписания

| Параметр | Описание | Значение по умолчанию |
|:---|:---|:---|
| `function` | Функция для выполнения | — |
| `seconds` | Интервал в секундах | — |
| `minutes` | Интервал в минутах | — |
| `hours` | Интервал в часах | — |
| `days` | Интервал в днях | — |
| `cron` | Cron-выражение | — |
| `when` | Время запуска (ISO 8601) | — |
| `after` | Запуск после указанного времени | — |
| `range_start` | Начало execution window | 00:00:00 |
| `range_end` | Конец execution window | 23:59:59 |
| `jitter` | Максимальная случайная задержка (сек) | 0 |
| `splay` | Случайное отклонение интервала (сек) | 0 |
| `enabled` | Включена ли задача | True |
| `run_on_start` | Запуск при старте миньона | False |

---

## Практические сценарии

### 1. Интервальное расписание

```yaml
# /etc/salt/minion.d/schedule.conf
schedule:
  # Highstate каждые 4 часа
  highstate_4h:
    function: state.highstate
    hours: 4
    jitter: 300
    maxrunning: 1
    run_on_start: True

  # Проверка диска каждые 30 минут
  disk_check:
    function: disk.usage
    minutes: 30
    returner: pg_returner

  # Ротация логов раз в сутки
  log_rotation:
    function: cmd.run
    cmd: '/usr/sbin/logrotate /etc/logrotate.conf'
    days: 1
    hour: 2
    minute: 30
```

### 2. Cron-подобное расписание

```yaml
schedule:
  # Каждые будни в 9:00
  weekday_highstate:
    function: state.highstate
    cron: '0 9 * * 1-5'

  # Каждое воскресенье в 3:00
  weekly_maintenance:
    function: state.apply
    state: maintenance
    cron: '0 3 * * 0'

  # Каждые 15 минут с 8:00 до 20:00
  business_hours_check:
    function: test.ping
    cron: '*/15 8-20 * * *'
```

### 3. Execution Windows

```yaml
schedule:
  # Highstate только ночью (2:00-5:00)
  nightly_highstate:
    function: state.highstate
    hours: 1
    range_start: 02:00
    range_end: 05:00
    jitter: 600

  # Обновления только в окне обслуживания (сб 2:00-6:00)
  weekend_patches:
    function: state.apply
    state: patches
    cron: '0 2 * * 6'
    range_start: 02:00
    range_end: 06:00

  # Проверка SSL-сертификатов в рабочее время
  ssl_check:
    function: certificate.check
    minutes: 30
    range_start: 08:00
    range_end: 18:00
```

### 4. Jitter и Splay

```yaml
schedule:
  # Highstate с jitter (случайная задержка до 300 сек)
  safe_highstate:
    function: state.highstate
    hours: 4
    jitter: 300
    # Задача запустится через случайный промежуток 0-300 сек после наступления времени

  # Проверка сервисов с splay (интервал варьируется)
  service_check:
    function: service.status
    minutes: 5
    splay: 60
    # Интервал будет от 240 до 360 секунд (300 ± 60)

  # Массовая проверка с jitter для предотвращения шторма
  minion_health:
    function: cmd.run
    cmd: '/usr/local/bin/health_check.sh'
    hours: 1
    jitter: 900
    maxrunning: 1
```

### 5. Условные запуски (when/after/until)

```yaml
schedule:
  # Запуск только если файл существует
  conditional_backup:
    function: cmd.run
    cmd: '/usr/local/bin/backup.sh'
    hours: 6
    when: ['test -f /var/run/backup_enabled']

  # Запуск после определенного времени
  post_migration_check:
    function: state.apply
    state: post_migration
    after: '2026-09-15T00:00:00'

  # Запуск пока файл блокировки существует
  watch_migration:
    function: cmd.run
    cmd: 'echo "Migration in progress"'
    minutes: 1
    while: ['test -f /var/run/migration.lock']
```

### 6. Расписание на мастере (Orchestrate)

```yaml
# /etc/salt/master.d/schedule.conf
schedule:
  # Ночная оркестрация
  nightly_orch:
    function: state.orchestrate
    orch: deploy/rolling_update
    cron: '0 2 * * *'
    maxrunning: 1

  # Проверка ключей каждые 6 часов
  key_audit:
    function: wheel.key.list
    hours: 6
    returner: pg_returner

  # Очистка Job Cache раз в сутки
  job_cache_cleanup:
    function: runner.jobs.clean
    cron: '0 4 * * *'
```

### 7. Управление расписанием

```bash
# Просмотр текущего расписания
salt '*' schedule.list

# Включение/отключение
salt '*' schedule.disable
salt '*' schedule.enable

# Включение/отключение конкретной задачи
salt '*' schedule.disable_job highstate_4h
salt '*' schedule.enable_job highstate_4h

# Добавление задачи через CLI
salt '*' schedule.add backup_job function='cmd.run' \\
  cmd='/usr/local/bin/backup.sh' hours=6 jitter=300

# Удаление задачи
salt '*' schedule.delete backup_job

# Принудительный запуск задачи
salt '*' schedule.run highstate_4h
```

### 8. Мониторинг расписания

```bash
# Просмотр активных задач
salt '*' schedule.list show_next_run=True

# Просмотр с详细 информацией
salt '*' schedule.list return_yaml=True

# Проверка последних запусков через Event Bus
salt-run state.event pretty=True | grep salt/schedule
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| Задача не запускается | `enabled: False` или вне execution window | `salt '*' schedule.list`, проверить `range_start/end` |
| Все миньоны запускают одновременно | Нет jitter/splay | Добавить `jitter: 300` или `splay: 60` |
| `maxrunning` не ограничивает | Задача не блокируется | Проверить, что `maxrunning` задан корректно |
| Scheduler не запускается | `loop_interval` слишком большой | Уменьшить `loop_interval` в конфигурации |
| Cron-выражение не работает | Неверный формат | Проверить синтаксис crontab, использовать `cron: '0 2 * * *'` |
| `when` не срабатывает | Файл не существует | Проверить путь в `when`, использовать абсолютные пути |
| Задача запускается при старте | `run_on_start: True` | Отключить если не нужно |

### Best practices

1. **Всегда `jitter`**: Для задач на нескольких тысячах миньонов — jitter обязателен.
2. **`maxrunning: 1`**: Ограничивайте параллельные запуски на одном миньоне.
3. **Execution windows**: Используйте `range_start/end` для критических операций.
4. **`run_on_start: False`**: По умолчанию, чтобы не запускать задачи при перезапуске.
5. **Логирование**: Направляйте результаты scheduled задач в returners.
6. **Мониторинг**: Проверяйте `schedule.list` и Event Bus для отладки.
7. **Версионирование**: Храните расписание в конфигурационных файлах, а не через CLI.

### Версии и совместимость

| Версия Salt | Особенности Scheduler |
|:---|:---|
| 3006 LTS | Базовый scheduler (function, interval) |
| 3007 STS | Добавлены `when`, `after`, `cron` |
| 3008 LTS | Улучшен `jitter`, `splay`, `range_start/end` |

### См. также

- [Оркестрация и автоматизация](Orchestration_and_Automation_Methods.md) — master schedule
- [Архитектура SaltStack](Architecture.md) — Schedule component
- [Event Bus продвинутый](Event_Bus_Advanced.md) — события от scheduler
