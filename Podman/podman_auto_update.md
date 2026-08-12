# Автообновление и откат в Podman

## Определения

**Podman Auto-Update** — встроенный механизм автоматического обновления контейнеров при появлении новых версий образов в удаленном реестре. В отличие от Docker (Watchtower), этот механизм не требует постоянно работающего демона-монитора, а опирается на стандартные таймеры и службы **systemd**. Обновление происходит за счет сравнения **дайджестов** (digest) образов, а не меток времени.

**Policy (Политика обновления)** — настройка, определяющая источник проверки обновлений. Задается меткой `io.containers.autoupdate` на контейнере или полем `AutoUpdate` в Quadlet-юните:

- **`registry`**: Сравнение локального дайджеста образа с актуальным дайджестом в удаленном реестре (Registry). Требует полностью квалифицированного имени образа (**FQIN**, например `docker.io/library/nginx:latest`), иначе Podman не знает, какой образ проверять и тянуть. Значение метки `image` — устаревший алиас для `registry` (поддерживается для обратной совместимости).
- **`local`**: Обновление на основе локально измененного образа с тем же именем/тегом (например, после пересборки через Buildah или `podman build`). Podman сравнивает дайджест образа контейнера с дайджестом в локальном хранилище; при различии юнит перезапускается.
- По умолчанию (если политика не задана) автообновление **отключено** (`disabled`).

**Rollback (Откат)** — автоматический возврат к предыдущему рабочему образу (по дайджесту), если новый контейнер не смог успешно запуститься или не прошел проверку здоровья (Healthcheck). Включен по умолчанию и управляется флагом `--rollback`.

**Актуально для:** Podman 6.x (проверено на 6.0.2). Механизм стабилен с Podman 4.x.

---

## Основные концепции

### Архитектура и компоненты

Механизм автообновления Podman глубоко интегрирован с операционной системой:

1. **`podman-auto-update.timer`**: Планировщик (системный или пользовательский), который периодически запускает процесс проверки. По умолчанию срабатывает раз в сутки (`OnCalendar=daily`), с задержкой `RandomizedDelaySec=900` и `Persistent=true`.
2. **`podman-auto-update.service`**: Служба, выполняющая команду `podman auto-update`. Она сканирует все контейнеры, управляемые systemd, на наличие метки `io.containers.autoupdate`.
3. **Метка `io.containers.autoupdate` / поле `AutoUpdate`**: Активирует механизм для конкретного контейнера. В Quadlet `AutoUpdate=registry` транслируется в метку `io.containers.autoupdate=registry`.
4. **`sdnotify` / `Notify=healthy`**: Протоколы, позволяющие Podman понять, что новый контейнер успешно запустился и готов к работе. Надежность отката напрямую зависит от наличия READY-сообщения.

### Требование к управлению через systemd

Автообновление работает **только для контейнеров, запущенных внутри systemd-юнита** — через Quadlet (`.container`, `.kube`, `.pod`) или сгенерированный юнит `podman generate systemd --new`. Обычные контейнеры, запущенные простым `podman run`, автообновлению не подлежат.

Ключевое условие: юнит должен **создавать новый контейнер** (флаг `--new` в сгенерированном юните). Юниты, которые просто останавливают и запускают существующий контейнер, не смогут переключиться на новый образ.

### Жизненный цикл обновления

1. **Триггер**: Таймер срабатывает согласно расписанию (или `podman auto-update` запускается вручную).
2. **Инспекция**: Podman проверяет метаданные образов для контейнеров с активной политикой.
3. **Загрузка**: Если в реестре обнаружен новый дайджест, скачивается новый образ.
4. **Перезапуск**: systemd-юнит контейнера перезапускается. Podman создает новый контейнер на базе свежего образа.
5. **Верификация**: Если настроен Healthcheck (`HealthCmd`) и `Notify=healthy`, старт systemd-юнита откладывается до получения статуса `healthy`. Если приложение шлет READY через `sdnotify`, ожидание идет до получения сообщения или таймаута.
6. **Откат**: Если в течение заданного времени контейнер стал `unhealthy`, упал или юнит не смог стартовать, Podman перезапускает службу, принудительно указывая дайджест предыдущего (рабочего) образа.

### Формат вывода

Команда `podman auto-update` выводит таблицу с колонками `UNIT`, `CONTAINER`, `IMAGE`, `POLICY`, `UPDATED`. Значения `UPDATED`:

- `true` — образ обновлен и юнит перезапущен;
- `false` — новая версия не найдена;
- `pending` — доступна новая версия (при `--dry-run`);
- `failed` — обновление завершилось ошибкой.

---

## Практические сценарии

### 1. Настройка через Quadlet (Рекомендуемый способ)

Для реализации надежного обновления с откатом в Quadlet необходимо настроить проверку здоровья. Поле `Notify=healthy` размещается в секции `[Container]` (не `[Service]`).

**Файл:** `~/.config/containers/systemd/webapp.container`

```ini
[Unit]
Description=My Secure Web Application
After=network-online.target

[Container]
Image=docker.io/library/nginx:latest
ContainerName=webapp
# Включение автообновления (политика registry требует полное имя образа FQIN)
AutoUpdate=registry
PublishPort=8080:80

# Настройка Healthcheck для обеспечения Rollback
HealthCmd=curl -f http://localhost/ || exit 1
HealthInterval=30s
HealthRetries=3
# Задержать старт юнита до момента, когда контейнер стал healthy
Notify=healthy

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
```

Активация юнита и включение таймера:

```bash
# Генерация service-юнита из Quadlet-файла и его запуск
systemctl --user daemon-reload
systemctl --user enable --now webapp.service

# Включение таймера автообновления для пользователя
systemctl --user enable --now podman-auto-update.timer
# → Created symlink .../podman-auto-update.timer → /usr/lib/systemd/user/podman-auto-update.timer

# Для headless-хостов (без входа в систему) включите linger
loginctl enable-linger $USER
```

Для системных (root) служб аналогично с `sudo systemctl enable --now podman-auto-update.timer`.

### 2. Управление через метки и `podman generate systemd`

Альтернатива Quadlet — пометить контейнер меткой и сгенерировать юнит:

```bash
# Запуск контейнера с меткой автообновления
podman run -d --name webapp \
  --label "io.containers.autoupdate=registry" \
  docker.io/library/nginx:latest

# Проверка метки
podman inspect webapp --format '{{index .Config.Labels "io.containers.autoupdate"}}'
# → registry

# Генерация systemd-юнита, создающего контейнер заново (--new)
podman generate systemd --new --name webapp --files
# → /home/user/container-webapp.service

systemctl --user daemon-reload
systemctl --user enable --now container-webapp.service
```

Дополнительно меткой `io.containers.autoupdate.authfile` можно указать файл авторизации для конкретного контейнера — Podman будет использовать его значение вместо стандартного пути.

### 3. Аутентификация в приватных реестрах

Команда `podman auto-update` работает в неинтерактивном режиме, поэтому ей необходим доступ к файлу авторизации.

```bash
# Выполнение логина (данные сохранятся в стандартный путь)
podman login registry.example.com

# Если используется кастомный путь к auth.json
podman auto-update --authfile /path/to/my/auth.json

# Альтернатива — переменная окружения
export REGISTRY_AUTH_FILE=/path/to/my/auth.json
podman auto-update
```

Расположение `auth.json`:

- Пользовательский (rootless) режим: `${XDG_RUNTIME_DIR}/containers/auth.json` (например, `/run/user/1000/containers/auth.json`). Каталог эфемерный — при перезагрузке создается заново.
- Системные службы (root): `/run/containers/0/auth.json`.
- Персистентный вариант для rootless: `podman login --authfile ~/.config/containers/auth.json registry.example.com`.
- Podman также подхватывает `$HOME/.docker/config.json` (учетные данные `docker login`) как запасной вариант.

### 4. Настройка расписания (systemd timer)

По умолчанию обновление происходит раз в сутки (`OnCalendar=daily`). Расписание меняется через override:

```bash
# Создание override для таймера (пользовательский режим)
systemctl --user edit podman-auto-update.timer
```

**Пример конфигурации (обновление каждый день в 03:30 с рандомизацией):**
```ini
[Timer]
# Очистить значение по умолчанию
OnCalendar=
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=30min
```

```bash
systemctl --user daemon-reload
systemctl --user restart podman-auto-update.timer

# Проверка активного расписания
systemctl --user list-timers podman-auto-update.timer
```

Штатный таймер по умолчанию использует `RandomizedDelaySec=900` и `Persistent=true` (отработавшее «пропущенное» обновление выполнится при следующем запуске системы).

### 5. Ручной запуск и отладка

Перед автоматизацией рекомендуется проверить работу механизма вручную.

```bash
# Проверка наличия обновлений без их применения (UPDATED = pending)
podman auto-update --dry-run
# → UNIT          CONTAINER                IMAGE                                    POLICY     UPDATED
# → webapp.service  a1b2c3d4e5f6 (webapp)   docker.io/library/nginx:latest          registry   pending

# Выборочный вывод: только юнит и статус
podman auto-update --dry-run --format "{{.Unit}} {{.Updated}}"
# → webapp.service pending

# Принудительное обновление всех помеченных контейнеров
podman auto-update
# → UNIT          CONTAINER                IMAGE                                    POLICY     UPDATED
# → webapp.service  a1b2c3d4e5f6 (webapp)   docker.io/library/nginx:latest          registry   true

# Вывод в формате JSON (для автоматизации)
podman auto-update --format json

# Отключение автоматического отката (не рекомендуется для продакшена)
podman auto-update --rollback=false

# Управление проверкой TLS при обращении к реестрам
podman auto-update --tls-verify=false

# Просмотр логов последнего обновления
journalctl --user -u podman-auto-update.service
```

### 6. Автообновление Kubernetes-манифестов

Podman поддерживает автообновление рабочих нагрузок, описанных Kubernetes YAML (юниты `.kube` или `podman kube play` внутри systemd). Политика задается Podman-специфичными аннотациями:

```yaml
# deployment.yaml — применить политику ко всем контейнерам
annotations:
  io.containers.autoupdate: "registry"

# либо только к конкретному контейнеру
annotations:
  io.containers.autoupdate/db: "registry"
```

```bash
# Запуск манифеста как systemd-сервиса
systemctl --user start kube-app.service

# Проверка обновлений для всех контейнеров манифеста
podman auto-update --dry-run
```

По умолчанию для манифестов политика автообновления отключена, а `sdnotify` равен `conmon`.

---

## Нюансы и ограничения

- **Требование systemd**: Автообновляются только контейнеры внутри systemd-юнитов (Quadlet или `podman generate systemd --new`). Простые `podman run` контейнеры игнорируются, даже если помечены меткой.
- **FQIN обязателен для `registry`**: Политика требует полностью квалифицированного имени образа. Контейнер, созданный по короткому имени (`nginx:latest`) или по ID образа, обновить нельзя.
- **Обновление Подов (Pods)**: При обновлении контейнера внутри пода Podman перезапускает соответствующие systemd-юниты (`.pod`/`.kube`); при необходимости перезапускается весь под для сохранения сетевого пространства имен.
- **Откат требует READY-сообщения**: Надежное определение успеха происходит через `sdnotify` (контейнер создан с `--sdnotify=container`, приложение шлет `systemd-notify --ready`). Без этого перезапуск юнита может считаться успешным, даже если контейнер упал сразу после старта. `Notify=healthy` дополнительно ждет статуса `healthy` по Healthcheck.
- **Очистка образов**: Podman автоматически не удаляет старые образы после обновления. Рекомендуется настроить отдельный таймер для `podman image prune -f` (при желании с `--all`).
- **Rootless специфика**: В безрутовом режиме таймер и служба включаются для каждого пользователя отдельно (`systemctl --user`). На headless-хостах требуется `loginctl enable-linger $USER`, иначе юниты пользователя не стартуют при загрузке.
- **Зависимость от тегов**: Автообновление работает только если образ в реестре обновился, но сохранил тот же тег (например, `:latest` или `:stable`). Если вы используете уникальные теги для каждой версии (например, `:v1.2.3`), автообновление их не подхватит.

---

## Дополнительная информация

### Сравнение с Watchtower

Дополнительное сравнение механизмов Docker и Podman см. в [Сравнение Podman и Docker](./podman_vs_docker.md).

| Характеристика | Watchtower (Docker) | Podman Auto-Update |
| :--- | :--- | :--- |
| **Механизм** | Отдельный контейнер-агент. | Интеграция с нативным планировщиком ОС. |
| **Безопасность** | Требует доступа к `docker.sock`. | Работает в рамках прав пользователя (Rootless). |
| **Откат (Rollback)** | Сложная настройка, часто нестабилен. | Нативный механизм через дайджесты образов (`--rollback`, по умолчанию включен). |
| **Ресурсы** | Постоянно потребляет RAM. | 0 МБ в режиме ожидания (timer-based). |
| **Kubernetes YAML** | Требует `compose`/сторонних решений. | Нативная поддержка аннотаций в `.kube`-манифестах. |

### Связанные разделы

- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — основы интеграции с systemd и Quadlet.
- **[Healthchecks в Podman](./podman_healthchecks.md)** — детальная настройка проверок, необходимых для отката.
- **[Rootless режим в Podman](./podman_rootless.md)** — особенности работы таймеров и linger.

### Ссылки

- **[podman-auto-update(1)](https://docs.podman.io/en/latest/markdown/podman-auto-update.1.html)** — официальная документация команды (англ.).
- **[podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** — параметры Quadlet, включая `AutoUpdate` и `Notify` (англ.).
