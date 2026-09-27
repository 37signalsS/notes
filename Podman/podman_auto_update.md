# Автообновление и откат в Podman

## Определения

**Podman Auto-Update** — встроенный механизм автоматического обновления контейнеров при появлении новых версий образов в удаленном реестре. В отличие от Docker (Watchtower), этот механизм не требует постоянно работающего демона-монитора, а опирается на стандартные таймеры и службы **systemd**. Обновление происходит за счет сравнения **дайджестов** (digest) образов, а не меток времени.

**FQIN (Fully Qualified Image Name)** — полностью квалифицированное имя образа, содержащее регистр, namespace и тег (например, `docker.io/library/nginx:latest`). Для политики `registry` использование FQIN обязательно, иначе Podman не может определить, какой образ проверять в реестре.

**Дайджест (Digest)** — криптографический хэш манифеста образа (алгоритм SHA256). Автообновление сравнивает именно дайджесты, а не теги, что исключает обновление по устаревшему тегу.

**Policy (Политика обновления)** — настройка, определяющая источник проверки обновлений. Задается меткой `io.containers.autoupdate` на контейнере или полем `AutoUpdate` в Quadlet-юните:

- **`registry`**: Сравнение локального дайджеста образа с актуальным дайджестом в удаленном реестре (Registry). Требует полностью квалифицированного имени образа (**FQIN**, например `docker.io/library/nginx:latest`), иначе Podman не знает, какой образ проверять и тянуть. Значение метки `image` — устаревший алиас для `registry` (поддерживается для обратной совместимости).
- **`local`**: Обновление на основе локально измененного образа с тем же именем/тегом (например, после пересборки через Buildah или `podman build`). Podman сравнивает дайджест образа контейнера с дайджестом в локальном хранилище; при различии юнит перезапускается.
- По умолчанию (если политика не задана) автообновление **отключено** (`disabled`).

**Rollback (Откат)** — автоматический возврат к предыдущему рабочему образу (по дайджесту), если новый контейнер не смог успешно запуститься или не прошел проверку здоровья (Healthcheck). Включен по умолчанию и управляется флагом `--rollback`.

**Quadlet** — декларативный генератор systemd-юнитов, использующий файлы с расширениями `.container`, `.kube`, `.pod` для описания контейнеров как сервисов. Подробнее см. **[Daemonless архитектура](./podman_daemonless_architecture.md)**.

**Актуально для:** Podman 6.x (проверено на 6.0.2). Механизм стабилен с Podman 4.x.

---

## Основные концепции

### Архитектура и компоненты

Механизм автообновления Podman глубоко интегрирован с операционной системой и использует нативные службы systemd вместо отдельного демона:

1. **`podman-auto-update.timer`**: Планировщик (системный или пользовательский), который периодически запускает процесс проверки. По умолчанию срабатывает раз в сутки (`OnCalendar=daily`), с задержкой `RandomizedDelaySec=900` и `Persistent=true`.
2. **`podman-auto-update.service`**: Служба, выполняющая команду `podman auto-update`. Она сканирует все контейнеры, управляемые systemd, на наличие метки `io.containers.autoupdate`.
3. **Метка `io.containers.autoupdate` / поле `AutoUpdate`**: Активирует механизм для конкретного контейнера. В Quadlet `AutoUpdate=registry` транслируется в метку `io.containers.autoupdate=registry`.
4. **`sdnotify` / `Notify=healthy`**: Протоколы, позволяющие Podman понять, что новый контейнер успешно запустился и готов к работе. Надежность отката напрямую зависит от наличия READY-сообщения.
5. **`conmon` (Container Monitor)**: Легковесный монитор жизненного цикла контейнера, выступающий в роли родительского процесса для контейнера и MAINPID для systemd. При автообновлении conmon отслеживает статус нового контейнера и передает коды завершения. Подробнее об архитектуре см. **[Daemonless архитектура](./podman_daemonless_architecture.md)**.
6. **`podman system service`**: При необходимости авторизации в приватных реестрах `podman-auto-update.service` может использовать сокет Docker API (активируемый по требованию), который обеспечивает доступ к учетным данным, хранящимся в `auth.json`.

### Требование к управлению через systemd

Автообновление работает **только для контейнеров, запущенных внутри systemd-юнита** — через Quadlet (`.container`, `.kube`, `.pod`) или сгенерированный юнит `podman generate systemd --new`. Обычные контейнеры, запущенные простым `podman run`, автообновлению не подлежат.

**Ключевое условие:** юнит должен **создавать новый контейнер** (флаг `--new` в сгенерированном юните). Юниты, которые просто останавливают и запускают существующий контейнер, не смогут переключиться на новый образ.

**Почему это работает:** При использовании systemd и Quadlet контейнер не является "долгоживущим процессом", а управляется как сервис. При срабатывании таймера `podman auto-update` взаимодействует с systemd через D-Bus, передавая команду на перезапуск юнита с новым образом. Это обеспечивает атомарность операции и корректную обработку зависимостей (например, `After=network-online.target`).

### Жизненный цикл обновления

1. **Триггер**: Таймер срабатывает согласно расписанию (или `podman auto-update` запускается вручную).
2. **Инспекция**: Podman проверяет метаданные образов для контейнеров с активной политикой. Для политики `registry` выполняется pull-запрос к реестру для получения актуального дайджеста. Для `local` — сравнение с локальным хранилищем.
3. **Загрузка**: Если в реестре обнаружен новый дайджест, скачивается новый образ. При наличии `auth.json` учетные данные подставляются автоматически.
4. **Перезапуск**: systemd-юнит контейнера перезапускается. Podman создает новый контейнер на базе свежего образа. При использовании `sdnotify=container` контейнер получает `NOTIFY_SOCKET` для отправки READY-сообщения.
5. **Верификация**: 
   - Если настроен Startup Healthcheck (`HealthStartupCmd` в Quadlet или `--health-startup-cmd` в CLI) и `Notify=healthy`, старт systemd-юнита откладывается до получения статуса `healthy`. Startup-проверка работает как шлюз (Gate): основная проверка не начинается, пока фаза старта не завершится успешно (введено в Podman 5.0, расширено в 6.x).
   - Если приложение шлет READY через `sdnotify`, ожидание идет до получения сообщения или таймаута.
   - При `HealthOnFailure=restart` контейнер автоматически перезапускается при переходе в `unhealthy`.
6. **Откат**: Если в течение заданного времени контейнер стал `unhealthy`, упал или юнит не смог стартовать, Podman перезапускает службу, принудительно указывая дайджест предыдущего (рабочего) образа. Старый образ удаляется только при ручной очистке (`podman image prune`).

### Формат вывода

Команда `podman auto-update` выводит таблицу с колонками `UNIT`, `CONTAINER`, `IMAGE`, `POLICY`, `UPDATED`. Значения `UPDATED`:

- `true` — образ обновлен и юнит перезапущен;
- `false` — новая версия не найдена;
- `pending` — доступна новая версия (при `--dry-run`);
- `failed` — обновление завершилось ошибкой.

**Фильтрация и форматирование вывода:**

```bash
# Показ только обновленных юнитов
podman auto-update --filter updated=true

# JSON-формат для автоматизации (обработка в скриптах, отправка в мониторинг)
podman auto-update --format json
# → [{"unit":"webapp.service","container":"a1b2c3d4","image":"nginx:latest","policy":"registry","updated":true}]

# Кастомный Go-шаблон
podman auto-update --format '{{range .}}{{.Unit}} {{.Updated}}{{"\n"}}{{end}}'
```

**Уровни логирования для диагностики:**

```bash
# Подробный вывод с отладочной информацией о запросах к реестру
podman --log-level debug auto-update

# Проверка логов службы systemd
journalctl --user -u podman-auto-update.service --since "1 hour ago" -o json-pretty
```

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

**Безопасное хранение учетных данных (DevOps/SRE best practices):**

```bash
# Персистентный auth файл для rootless (не эфемерный)
mkdir -p ~/.config/containers
podman login --authfile ~/.config/containers/auth.json registry.example.com

# Использование credential helpers (вместо хранения plaintext паролей)
# Пример для docker-credential-pass
export REGISTRY_AUTH_FILE=<(echo '{"auths":{},"credHelpers":{"registry.example.com":"pass"}}')
podman auto-update

# Проверка провайдера авторизации
cat ~/.config/containers/auth.json | jq '.auths | keys'
```

Расположение `auth.json`:

- Пользовательский (rootless) режим: `${XDG_RUNTIME_DIR}/containers/auth.json` (например, `/run/user/1000/containers/auth.json`). Каталог эфемерный — при перезагрузке создается заново.
- Системные службы (root): `/run/containers/0/auth.json`.
- Персистентный вариант для rootless: `podman login --authfile ~/.config/containers/auth.json registry.example.com`.
- Podman также подхватывает `$HOME/.docker/config.json` (учетные данные `docker login`) как запасной вариант.

**TLS и недоверенные реестры:**

```bash
# Отключение проверки TLS (не рекомендуется для production)
podman auto-update --tls-verify=false

# Настройка insecure registry в containers.conf (альтернатива)
# Файл: /etc/containers/containers.conf или ~/.config/containers/containers.conf
[engine]
insecure_registries = ["registry.example.com:5000"]
```

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

### 7. Безопасность и ограничение ресурсов

Для production-среды рекомендуется дополнительно настроить ограничения ресурсов и безопасность в Quadlet-юните:

```ini
[Unit]
Description=Secure Web Application
After=network-online.target
# Запрет на взаимодействие с другими сервисами (опционально)
ProtectSystem=strict
ProtectHome=yes

[Container]
Image=docker.io/library/nginx:latest
AutoUpdate=registry
PublishPort=8080:80
# Ограничения ресурсов
# Cpus=0.5
# Memory=256M
# MemorySwap=0
# PidsLimit=100
HealthCmd=curl -f http://localhost/ || exit 1
Notify=healthy
# Drop all capabilities, keep only NET_BIND_SERVICE if needed
# CapDrop=ALL

[Service]
Restart=on-failure
# Лимиты на файлы (например, 1024 открытых дескрипторов)
LimitNOFILE=1024
```

### 8. Очистка образов и управление хранилищем

Podman не удаляет старые образы после обновления автоматически. Для предотвращения заполнения диска настройте отдельный таймер:

```bash
# Создание таймера для очистки неиспользуемых образов
# Файл: ~/.config/systemd/user/podman-prune-images.timer
```

```ini
[Unit]
Description=Podman Image Prune Timer

[Timer]
OnCalendar=daily
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# Файл: ~/.config/systemd/user/podman-prune-images.service
[Unit]
Description=Podman Image Prune Service

[Service]
Type=oneshot
ExecStart=/usr/bin/podman image prune -f --all
# --all удаляет все неиспользуемые образы (не только dangling)
# Для удаления только dangling (не помеченных тегами) уберите --all
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now podman-prune-images.timer

# Проверка статуса таймера
systemctl --user list-timers podman-prune-images.timer
```

**Важно:** При использовании `--all` удаляются все неиспользуемые образы, включая те, что могут понадобиться для отката. Для сохранения нескольких предыдущих версий используйте фильтрацию по дате или вручную управляйте retention.

---

## Нюансы и ограничения

- **Требование systemd**: Автообновляются только контейнеры внутри systemd-юнитов (Quadlet или `podman generate systemd --new`). Простые `podman run` контейнеры игнорируются, даже если помечены меткой.
- **FQIN обязателен для `registry`**: Политика требует полностью квалифицированного имени образа. Контейнер, созданный по короткому имени (`nginx:latest`) или по ID образа, обновить нельзя.
- **Обновление Подов (Pods)**: При обновлении контейнера внутри пода Podman перезапускает соответствующие systemd-юниты (`.pod`/`.kube`); при необходимости перезапускается весь под для сохранения сетевого пространства имен.
- **Откат требует READY-сообщения**: Надежное определение успеха происходит через `sdnotify` (контейнер создан с `--sdnotify=container`, приложение шлет `systemd-notify --ready`). Без этого перезапуск юнита может считаться успешным, даже если контейнер упал сразу после старта. `Notify=healthy` дополнительно ждет статуса `healthy` по Healthcheck. Startup Healthcheck (Podman 5.0+) работает как шлюз (Gate) и предотвращает запуск основной проверки до завершения фазы старта.
- **Очистка образов**: Podman автоматически не удаляет старые образы после обновления. Рекомендуется настроить отдельный таймер для `podman image prune -f` (при желании с `--all`).
- **Rootless специфика**: В безрутовом режиме таймер и служба включаются для каждого пользователя отдельно (`systemctl --user`). На headless-хостах требуется `loginctl enable-linger $USER`, иначе юниты пользователя не стартуют при загрузке.
- **Зависимость от тегов**: Автообновление работает только если образ в реестре обновился, но сохранил тот же тег (например, `:latest` или `:stable`). Если вы используете уникальные теги для каждой версии (например, `:v1.2.3`), автообновление их не подхватит.
- **Auth файл эфемерный в rootless**: Файл `auth.json` в `${XDG_RUNTIME_DIR}/containers/` создается заново при каждой перезагрузке. Для автоматизации без входа пользователя используйте персистентный путь `~/.config/containers/auth.json` или credential helper.
- **Сетевая доступность**: При использовании rootless-режима с `slirp4netns` (если Pasta недоступна) проверка обновлений может работать медленнее из-за NAT. Убедитесь, что порт 443 (HTTPS) доступен для выхода в интернет.
- **Одновременное обновление**: Если несколько хостов обновляют один и тот же сервис одновременно, возможна кратковременная деградация (если не используется балансировщик). Расписание таймера с `RandomizedDelaySec` помогает снизить риски.
- **Версия Podman**: Механизм автообновления появился в Podman 4.x. В Podman 5.0 добавлена поддержка Startup Healthcheck, в 6.0 — улучшена обработка отката и интеграция с systemd. Рекомендуется использовать не старше 6.0.

---

## Диагностика и устранение неполадок

### Типичные ошибки

**1. `FQIN required for registry policy`**
- **Причина:** Контейнер создан с коротким именем образа или ID образа.
- **Решение:** Используйте полностью квалифицированное имя (например, `docker.io/library/nginx:latest`) в Quadlet или при запуске.

**2. `authentication required` / `x509: certificate signed by unknown authority`**
- **Причина:** Отсутствуют учетные данные для приватного реестра или не настроен TLS.
- **Решение:** Выполните `podman login registry.example.com` или укажите `--authfile`. Для самоподписанных сертификатов добавьте реестр в `insecure_registries` в `containers.conf`.

**3. `Update failed: dial tcp: lookup registry.example.com`**
- **Причина:** Отсутствует сетевая доступность или DNS.
- **Решение:** Проверьте сетевые настройки хоста, доступность реестра и работу DNS. В rootless-режиме проверьте настройки `slirp4netns` или `pasta`.

**4. `Rollback triggered` без явной причины**
- **Причина:** Контейнер упал сразу после старта, или Healthcheck не настроен, и systemd считает юнит failed.
- **Решение:** Настройте `Notify=healthy` и `HealthCmd`. Проверьте логи контейнера (`podman logs webapp`) и journalctl.

**5. `No containers found with autoupdate label`**
- **Причина:** Метка не установлена, или контейнер не управляется systemd.
- **Решение:** Убедитесь, что юнит создан с флагом `--new` (Quadlet), и метка `io.containers.autoupdate` присутствует.

### Диагностические команды

```bash
# Проверка наличия метки на контейнере
podman inspect webapp --format '{{index .Config.Labels "io.containers.autoupdate"}}'

# Просмотр systemd-юнита, управляющего контейнером
systemctl --user list-units | grep webapp

# Проверка конфигурации таймера
systemctl --user cat podman-auto-update.timer

# Отладка запросов к реестру
podman --log-level debug auto-update --dry-run

# Просмотр истории обновлений
journalctl --user -u podman-auto-update.service --since "7 days ago"

# Проверка конфигурации containers.conf (включая insecure_registries)
cat ~/.config/containers/containers.conf | jq '.engine'
```

---

## Дополнительная информация

### Версионирование и совместимость

| Версия Podman | Статус автообновления |
| :--- | :--- |
| **4.x** | Механизм стабилен, поддерживаются все базовые политики. |
| **5.0** | Добавлен Startup Healthcheck (Gate) как часть верификации. Улучшена обработка `sdnotify`. |
| **6.0+** | Полная поддержка `HealthOnFailure`, динамическое обновление параметров Healthcheck через `podman update`. Улучшена обработка откатов. Удалена поддержка CNI, BoltDB. Рекомендуемая версия. |

**Минимальные требования:**
- Podman >= 4.0
- systemd >= 245 (рекомендуется >= 247 для поддержки `OnCalendar` с секциями)
- SQLite бэкенд (автоматически мигрируется в Podman 6.0)

### Сравнение с Watchtower

Дополнительное сравнение механизмов Docker и Podman см. в [Сравнение Podman и Docker](./podman_vs_docker.md).

| Характеристика | Watchtower (Docker) | Podman Auto-Update |
| :--- | :--- | :--- |
| **Механизм** | Отдельный контейнер-агент. | Интеграция с нативным планировщиком ОС. |
| **Безопасность** | Требует доступа к `docker.sock`. | Работает в рамках прав пользователя (Rootless). |
| **Откат (Rollback)** | Сложная настройка, часто нестабилен. | Нативный механизм через дайджесты образов (`--rollback`, по умолчанию включен). |
| **Ресурсы** | Постоянно потребляет RAM. | 0 МБ в режиме ожидания (timer-based). |
| **Kubernetes YAML** | Требует `compose`/сторонних решений. | Нативная поддержка аннотаций в `.kube`-манифестах. |
| **Healthcheck** | Зависит от настроек Watchtower. | Использует нативные Healthcheck Podman + `Notify=healthy`. |
| **Аутентификация** | Через Docker config. | Через `auth.json` / credential helpers. |

### Связанные разделы

- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — основы интеграции с systemd и Quadlet.
- **[Healthchecks в Podman](./podman_healthchecks.md)** — детальная настройка проверок, необходимых для отката.
- **[Rootless режим в Podman](./podman_rootless.md)** — особенности работы таймеров и linger.
- **[Управление зависимостями](./podman-dependencies.md)** — как `Notify=healthy` интегрируется с systemd.
- **[Переход с Docker](./migration-from-docker.md)** — миграция автообновления с Watchtower на Podman.

### Ссылки

- **[podman-auto-update(1)](https://docs.podman.io/en/latest/markdown/podman-auto-update.1.html)** — официальная документация команды (англ.).
- **[podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** — параметры Quadlet, включая `AutoUpdate` и `Notify` (англ.).
- **[podman-healthcheck(1)](https://docs.podman.io/en/latest/markdown/podman-healthcheck.1.html)** — управление проверками здоровья (англ.).
- **[Podman Auto-Update Blog Post](https://blog.podman.io/2022/03/08/auto-update-containers-with-podman/)** — обзор механизма (англ.).
