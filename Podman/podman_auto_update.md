# Podman: Автообновление и откат контейнеров

## Определения

**Podman Auto-Update** — встроенный механизм автоматического обновления контейнеров при появлении новых образов в реестре. Реализован через команду `podman auto-update` и systemd-таймеры, не требует внешних демонов-мониторов.

**Auto-Update Labels** — специальные лейблы, определяющие политику обновления для контейнера:

- `registry` — сравнение дайджестов с удалённым реестром
- `local` — проверка локально собранных образов

**Rollback** — автоматический откат к предыдущей версии образа при неудачном запуске контейнера после обновления.

## Основные концепции

### Архитектура механизма

В отличие от Docker, требующего внешних инструментов (Watchtower), Podman реализует автообновление нативно:

| Компонент | Назначение |
| :--- | :--- |
| **podman auto-update** | Проверка и применение обновлений |
| **systemd-таймер** | Планирование периодического запуска |
| **io.containers.autoupdate** | Лейбл для активации автообновления |
| **systemd-юниты** | Управление жизненным циклом и откатом |

### Принцип работы

1. **Проверка**: systemd-таймер запускает `podman auto-update`
2. **Сравнение**: Podman сравнивает дайджесты локальных образов с реестром
3. **Обновление**: При несовпадении — скачивает новый образ
4. **Перезапуск**: Останавливает старый контейнер, запускает новый
5. **Верификация**: Проверяет успешность запуска через systemd
6. **Откат**: При сбое — возвращает предыдущий образ

### Требования для работы

1. **systemd-управление**: Контейнер должен быть запущен через systemd-юнит
2. **Лейбл autoupdate**: При создании контейнера указан `--label "io.containers.autoupdate=registry"`
3. **Флаг rollback**: В systemd-юните включён `--rollback`
4. **Health check**: Контейнер сигнализирует о готовности через sdnotify

## Практические сценарии

### 1. Базовая настройка автообновления

**Создание контейнера с лейблом:**

```bash
podman run -d --name my-service \
  --label "io.containers.autoupdate=registry" \
  docker.io/library/nginx:latest
```

**Генерация systemd-юнита:**

```bash
podman generate systemd --name my-service --files --new
```

**Включение таймера автообновления:**

```bash
systemctl --user enable --now podman-auto-update.timer
```

### 2. Настройка Quadlet для автообновления

Quadlet — декларативный способ управления контейнерами через systemd-файлы.

**Файл `/etc/containers/systemd/my-service.container`:**

```ini
[Unit]
Description=My Service Container

[Container]
Image=docker.io/library/nginx:latest
ContainerName=my-service
AutoUpdate=registry
PublishPort=8080:80

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Ключ `AutoUpdate=registry` автоматически добавляет необходимый лейбл.

### 3. Настройка расписания обновлений

**Проверка выражения OnCalendar:**

```bash
systemd-analyze calendar "Mon *-*-* 03:30:00"
```

Команда покажет следующее время срабатывания и проверит синтаксис.

**Создание кастомного таймера:**

Файл `/etc/systemd/user/podman-auto-update.timer.d/custom-schedule.conf`:

```ini
[Timer]
OnCalendar=Mon *-*-* 03:30:00
RandomizedDelaySec=30m
Persistent=true
```

**Параметры:**

- `OnCalendar` — выражение в формате systemd.time(7)
- `RandomizedDelaySec` — случайная задержка для избежания одновременных обновлений
- `Persistent=true` — пропущенные обновления применяются при следующем запуске

**Примеры выражений OnCalendar:**

| Выражение | Описание |
| :--- | :--- |
| `*-*-* 04:00:00` | Ежедневно в 04:00 |
| `Mon *-*-* 03:30:00` | Каждый понедельник в 03:30 |
| `*-*-1,15 02:00:00` | 1-го и 15-го числа в 02:00 |
| `hourly` | Каждый час |
| `daily` | Ежедневно в 00:00 |
| `weekly` | Еженедельно по понедельникам |

### 4. Настройка отката (Rollback)

**Как работает rollback:**

Rollback — встроенное поведение `podman auto-update`. При обновлении Podman сохраняет дайджест предыдущего образа. Если новый контейнер не проходит health check, Podman автоматически откатывается к предыдущей версии.

**Требования для отката:**

1. Контейнер управляется через systemd
2. Установлен лейбл `io.containers.autoupdate=registry`
3. Настроен health check (`--health-cmd` или `HealthCmd` в Quadlet)
4. systemd-юнит имеет `Restart=always` или `Restart=on-failure`

**Настройка через Quadlet (рекомендуемый способ):**

Файл `/etc/containers/systemd/my-service.container`:

```ini
[Unit]
Description=My Service Container

[Container]
Image=docker.io/library/nginx:latest
ContainerName=my-service
AutoUpdate=registry
PublishPort=8080:80
HealthCmd=curl -f http://localhost/ || exit 1
HealthInterval=30s
HealthTimeout=5s
HealthRetries=3
HealthStartPeriod=10s

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**Настройка через `podman generate systemd`:**

```bash
# Создание контейнера с health check
podman run -d --name my-service \
  --label "io.containers.autoupdate=registry" \
  --health-cmd="curl -f http://localhost/ || exit 1" \
  --health-interval=30s \
  --health-timeout=5s \
  --health-retries=3 \
  --health-start-period=10s \
  docker.io/library/nginx:latest

# Генерация systemd-юнита
podman generate systemd --name my-service --files --new
```

> **Важно:** Флаг `--rollback` не существует как отдельный параметр `podman run`. Rollback — это автоматическое поведение `podman auto-update`, активируемое при наличии health check.

### 5. Механизм отката: последовательность

```
1. podman auto-update скачивает новый образ
   ↓
2. systemd останавливает текущий контейнер
   ↓
3. Запускается контейнер с новым образом
   ↓
4. Начинают выполняться health check'и
   ↓
5a. Health OK (в течение HealthRetries × HealthInterval)
    → Контейнер работает, обновление завершено
   ↓
5b. Health FAIL (превышены HealthRetries)
    → Podman фиксирует неработоспособность
   ↓
6. Podman откатывается к предыдущему дайджесту образа
   ↓
7. Контейнер перезапускается со старой версией
```

> **Примечание:** Для Quadlet-контейнеров настройка health check и rollback полностью декларативна — достаточно указать `HealthCmd` и связанные параметры в секции `[Container]`.

### 6. Проверка статуса обновлений

**Просмотр последних обновлений:**

```bash
# Статус таймера
systemctl --user status podman-auto-update.timer

# Журнал обновлений
journalctl --user -u podman-auto-update.service

# Проверка контейнеров с autoupdate
podman ps --format "table {{.Names}}\t{{.Labels}}" | grep autoupdate
```

**Принудительное обновление:**

```bash
podman auto-update --dry-run    # Проверка без применения
podman auto-update --verbose    # Подробный вывод
```

## Дополнительная информация

### Сравнение с Watchtower

| Характеристика | Watchtower (Docker) | Podman Auto-Update |
| :--- | :--- | :--- |
| **Архитектура** | Внешний демон-монитор | Встроенная команда |
| **Требования** | Отдельный контейнер | Только systemd |
| **Откат** | Через сторонние скрипты | Нативный rollback |
| **Планировщик** | Встроенный интервал | systemd-таймеры |
| **Rootless** | Ограниченная поддержка | Полная поддержка |
| **Зависимости** | Docker API | Нет внешних зависимостей |

### Health check с sdnotify

**Почему sdnotify надёжнее health check:**

| Health check | sdnotify |
| :--- | :--- |
| Периодическая проверка | Мгновенный сигнал готовности |
| Задержка обнаружения | Немедленная реакция |
| Не знает о внутренних процессах | Приложение само знает о готовности |
| Может пропустить сбой | Гарантированный сигнал |

**Пример приложения с sdnotify (Python):**

```python
import sdnotify
import time

n = sdnotify.SdNotify()
n.notify("READY=1")

# Приложение работает
while True:
    if not health_check_passed():
        n.notify("STATUS=Health check failed")
        n.notify("ERRNO=1")
    time.sleep(30)
```

### Troubleshooting

**Лейбл не распознаётся:**

```bash
# Проверка лейбла
podman inspect my-service --format '{{.Config.Labels}}'

# Пересоздание контейнера с лейблом
podman rm -f my-service
podman run -d --name my-service \
  --label "io.containers.autoupdate=registry" \
  nginx:latest
```

### Связанные темы

- **systemd-интеграция:** [Daemonless архитектура Podman](./podman_daemonless_architecture.md)
- **Rootless режим:** [Rootless режим в Podman](./podman_rootless.md)
- **Основные команды:** [Podman: Основные команды](./podman_basic_commands.md)
- **Health check:** [HEALTHCHECK в Dockerfile](../Docker/Dockerfile/Instructions/health_signals.md) — встраивание проверок здоровья в образ
