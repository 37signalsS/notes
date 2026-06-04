# Подман: Автообновление и откат контейнеров

## Определения

**Podman Auto-Update** — встроенный механизм автоматического обновления контейнеров при появлении новых образов в реестре. Реализован через команду `podman auto-update` и таймеры **systemd**, не требует внешних демонов-мониторов.

**Auto-Update Labels** — специальные метки (лейблы), определяющие политику обновления для контейнера:

- `registry` — сравнение дайджестов с удалённым реестром.
- `local` — проверка локально собранных образов.

**Rollback (Откат)** — автоматический возврат к предыдущей версии образа при неудачном запуске контейнера после обновления.

**sdnotify (systemd notification)** — протокол уведомления **systemd** о готовности или состоянии приложения.

**OCI (Open Container Initiative)** — открытый стандарт форматов образов и сред выполнения контейнеров.

## Основные концепции

### Архитектура механизма

В отличие от Docker, требующего внешних инструментов (например, Watchtower), Podman реализует автообновление нативно:

| Компонент | Назначение |
| :--- | :--- |
| **podman auto-update** | Команда для проверки и применения обновлений |
| **systemd-таймер** | Планировщик для периодического запуска процесса обновления |
| **io.containers.autoupdate** | Лейбл для активации механизма автообновления |
| **systemd-юниты** | Управление жизненным циклом процесса и его откатом |

### Принцип работы

1. **Проверка**: systemd-таймер запускает службу, которая выполняет `podman auto-update`.
2. **Сравнение**: Podman сравнивает дайджесты локальных образов с данными в реестре.
3. **Обновление**: При обнаружении новой версии — скачивается новый образ.
4. **Перезапуск**: Текущий контейнер останавливается, и запускается новый на базе свежего образа.
5. **Верификация**: Проверка успешности запуска через механизмы **systemd** (Health check или sdnotify).
6. **Откат**: Если новый контейнер не прошел проверку — система возвращает предыдущую рабочую версию образа.

### Требования для работы

1. **Управление через systemd**: Контейнер должен быть запущен как служба **systemd**.
2. **Метка autoupdate**: При создании контейнера необходимо указать `--label "io.containers.autoupdate=registry"`.
3. **Механизм отката**: В конфигурации юнита (особенно Quadlet) должны быть настроены параметры проверки состояния.
4. **Health check**: Приложение должно сообщать о своей готовности (через `HealthCmd` или `sdnotify`).

## Практические сценарии

### 1. Настройка через Quadlet (Рекомендуемый способ)

**Quadlet** — декларативный способ управления контейнерами Podman через нативные файлы конфигурации **systemd**.

**Файл:** `/etc/containers/systemd/my-service.container`

```ini
[Unit]
Description=My Service Container

[Container]
Image=docker.io/library/nginx:latest
ContainerName=my-service
AutoUpdate=registry
PublishPort=8080:80
# Настройка проверки для реализации отката
HealthCmd=curl -f http://localhost/ || exit 1
HealthInterval=30s
HealthTimeout=5s
HealthRetries=3

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Ключ `AutoUpdate=registry` автоматически добавляет необходимый лейбл в конфигурацию контейнера.

### 2. Устаревший способ (через podman generate systemd)

> **Внимание:** Данный метод считается устаревшим (legacy). Рекомендуется использовать **Quadlet**.

```bash
# 1. Создание контейнера с меткой
podman run -d --name my-service \
  --label "io.containers.autoupdate=registry" \
  docker.io/library/nginx:latest
# → a1b2c3d4... (ID контейнера)

# 2. Генерация юнита systemd
podman generate systemd --name my-service --files --new
# → my-service.service

# 3. Включение таймера автообновления
systemctl --user enable --now podman-auto-update.timer
# → Created symlink ...
```

### 3. Настройка расписания обновлений

По умолчанию таймер срабатывает раз в сутки. Для изменения расписания используется переопределение таймера.

**Проверка синтаксиса OnCalendar:**

```bash
systemd-analyze calendar "Mon *-*-* 03:30:00"
# → Normalized form: Mon *-*-* 03:30:00
# → Next elapse: Mon 2026-06-01 03:30:00 MSK
```

**Кастомное расписание:**
Файл `/etc/systemd/user/podman-auto-update.timer.d/custom-schedule.conf`:

```ini
[Timer]
OnCalendar=Mon *-*-* 03:30:00
RandomizedDelaySec=30m
Persistent=true
```

### 4. Механизм автоматического отката (Rollback)

Откат активируется автоматически, если контейнер управляется **systemd** и имеет настроенный `HealthCheck`.

**Последовательность действий:**

1. `podman auto-update` скачивает новый образ.
2. **systemd** останавливает старый и запускает новый контейнер.
3. Выполняются проверки здоровья (`HealthCmd`).
4. Если проверки провалены (превышено число попыток `HealthRetries`):
   - Podman фиксирует сбой.
   - Система автоматически перезапускает контейнер, используя предыдущий дайджест образа.

### 5. Проверка статуса и отладка

```bash
# Проверка состояния таймера
systemctl --user status podman-auto-update.timer
# → Active: active (waiting) since ...

# Просмотр логов процесса обновления
journalctl --user -u podman-auto-update.service

# Список контейнеров с активным автообновлением
podman ps --format "table {{.Names}}\t{{.Labels}}" | grep autoupdate
# → my-service    ...io.containers.autoupdate=registry...

# Тестовый запуск без внесения изменений
podman auto-update --dry-run
# → UNIT                     CONTAINER           IMAGE               POLICY      UPDATED
# → my-service.service       my-service          nginx:latest        registry    pending
```

## Дополнительная информация

### Сравнение с Watchtower (Docker)

| Характеристика | Watchtower (Docker) | Podman Auto-Update |
| :--- | :--- | :--- |
| **Архитектура** | Внешний контейнер-монитор | Встроенная команда системы |
| **Требования** | Доступ к сокету Docker | Интеграция с **systemd** |
| **Откат** | Ограничен, часто через внешние скрипты | Нативный механизм через дайджесты |
| **Планировщик** | Встроенный в приложение | Стандартные **systemd-таймеры** |
| **Безопасность** | Требует привилегий (Docker socket) | Полная поддержка **Rootless** режима |

### Уведомления через sdnotify

Использование `sdnotify` считается более надежным способом, так как приложение само сообщает системе о своей готовности.

**Пример на Python:**

```python
import sdnotify
import time

n = sdnotify.SdNotify()
# Сообщаем systemd, что приложение готово принимать трафик
n.notify("READY=1")

while True:
    # Цикл работы приложения
    time.sleep(30)
```

### Связанные темы

- **Интеграция с systemd:** [Daemonless архитектура Podman](./podman_daemonless_architecture.md)
- **Безрутовый режим:** [Rootless режим в Podman](./podman_rootless.md)
- **Основные операции:** [Podman: Основные команды](./podman_basic_commands.md)
- **Сигналы готовности:** [HEALTHCHECK в Dockerfile](../Docker/Dockerfile/Instructions/health_signals.md) — настройка проверок на уровне образа **OCI**.
