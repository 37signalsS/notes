# Управление зависимостями и готовностью в Podman

## Определения

**Зависимости контейнеров** — это логические и временные связи между компонентами распределенного приложения, определяющие порядок их запуска, остановки и перезапуска (например, API-сервер требует предварительного запуска и готовности базы данных).

**Готовность сервиса (Readiness)** — состояние приложения внутри контейнера, при котором оно не только запущено как процесс, но и полностью инициализировано и готово к обработке входящих запросов. Запуск процесса и готовность сервиса — разные события; в Podman их разделение реализуется через Healthcheck в связке с systemd.

**Notify=healthy** — параметр Quadlet (секция `[Container]`), который откладывает подтверждение готовности юнита (сообщение `READY=1` по протоколу `sd_notify`) до момента, когда Healthcheck контейнера вернет статус `healthy`. Транслируется в флаг `podman run --sdnotify=healthy` и требует настройки проверки (`HealthCmd`). Синтаксис проверок описан в [Проверки состояния (Healthcheck) в Podman](./podman_healthchecks.md).

**sd_notify** — протокол уведомлений systemd, используемый для передачи сообщений о готовности (`READY=1`) от приложения к менеджеру системных служб. Службы с `Type=notify` остаются в состоянии `activating`, пока не получат сообщение READY или не истекут таймауты (`TimeoutStartSec`).

**Директивы зависимостей systemd** — ключи секции `[Unit]` (`Requires`, `Wants`, `After`, `Before`, `BindsTo`, `PartOf` и др.), описывающие требования и порядок запуска между юнитами.

**Актуально для:** Podman 6.x (проверено на 6.0.2, июль 2026). Механизм стабилен с Podman 4.x.

**FQIN (Fully Qualified Image Name)** — полное имя образа, включающее реестр, namespace, имя и тег/диджест (например, `docker.io/library/nginx:latest` или `docker.io/library/nginx@sha256:...`). В Podman короткие имена разрешаются только через `registries.conf`; для продакшена и автоматизации рекомендуется использовать FQIN для детерминированности.

**Digest** — криптографический хэш (SHA256) содержимого образа. Используется для абсолютно детерминированных обновлений, когда важно, чтобы тег не изменился между запусками. В Quadlet можно задать `Image=...@sha256:...`.

**Quadlet-юнит** — декларативный файл (`.container`, `.pod`, `.network`, `.volume`, `.kube`, `.image`, `.build`, `.artifact`), размещаемый в каталогах поиска systemd и автоматически транслируемый в `.service`-юнит при `daemon-reload`. Подробнее о каталогах и форматах: [Daemonless архитектура](./podman_daemonless_architecture.md).

**conmon (Container Monitor)** — легковесный монитор жизненного цикла контейнера. В контексте зависимостей conmon выполняет роль MAINPID для systemd-юнита с `Type=notify`, передавая готовность через `sd_notify`. Подробнее о роли conmon: [Daemonless архитектура](./podman_daemonless_architecture.md).

---

## Основные концепции

### Архитектурный вызов: Бездемонность vs Очередность

В Docker центральный демон `dockerd` управляет всей цепочкой запуска. В Podman каждый контейнер — это независимый процесс. Это создает сложности при попытке реализовать классический `depends_on`:

1. **Отсутствие координатора**: Нет единого процесса, который бы ждал готовности одного контейнера перед запуском другого в CLI-режиме.
2. **Проблема "Race Condition"**: Запуск контейнера (`podman run`) считается успешным сразу после старта процесса, даже если приложение внутри будет инициализироваться еще 30 секунд.

### Решение: Делегирование в systemd

В экосистеме Podman управление сложными зависимостями делегируется **systemd**. Это дает ряд преимуществ:

- **Параллелизм**: systemd запускает независимые службы одновременно.
- **Декларативность**: Связи описываются через директивы секции `[Unit]`.
- **Надежность**: Если база данных упадет, зависимое приложение может быть автоматически остановлено или перезапущено.

**Директивы `[Unit]` и их семантика:**

| Директива | Тип | Поведение |
| :--- | :--- | :--- |
| `Requires=` | Требование (жесткое) | Активирует зависимый юнит; если он не смог успешно стартовать, запуск текущего юнита будет отклонен. |
| `Wants=` | Требование (мягкое) | Активирует зависимый юнит, но его сбой не мешает запуску текущего. |
| `After=` | Порядок (ordering) | Запускает текущий юнит ПОСЛЕ зависимого (не активирует его сам). |
| `Before=` | Порядок | Запускает текущий юнит ДО зависимого. |
| `BindsTo=` | Требование + жизненный цикл | Как `Requires`, но остановка или сбой зависимого юнита приводит к остановке текущего. |
| `PartOf=` | Жизненный цикл | Текущий юнит останавливается/перезапускается вместе с родительским. |

Важно: **требование и порядок — независимые оси**. `Requires=` без `After=` допускает параллельный запуск; `After=` без `Requires=` не активирует зависимость (юнит просто дождется, если зависимость уже активирована другим способом). Для полноценной семантики `depends_on` обычно нужно сочетание обеих директив.

### Методы обеспечения связности (Connectivity)

Директивы systemd решают вопрос *когда* стартует сервис. Чтобы сервис мог обратиться к зависимостям, необходимо настроить сетевое взаимодействие между контейнерами.

#### 1. Сетевое пространство имен Пода (Pod)

Все контейнеры внутри одного пода разделяют один сетевой стек.

- **Взаимодействие**: Только через `localhost` (или `127.0.0.1`) и порты.
- **Особенности**: DNS-имена отдельных контейнеров внутри пода не резолвятся; в DNS-реестре (Aardvark) под регистрируется как единая запись по имени пода. Используйте `DB_HOST=127.0.0.1`.

#### 2. Пользовательские сети (User-defined networks)

Сетевой стек **Netavark** (rootful) или **pasta** (rootless) с DNS-резолвером **Aardvark**.

- **Взаимодействие**: По именам контейнеров через встроенный DNS.
- **Имена**: Для предсказуемого резолвинга задавайте контейнеру `ContainerName=` (в Quadlet) или используйте `NetworkAlias=`. Имена из systemd-префикса (`systemd-db`) технически тоже резолвятся, но неудобны.
- **Тома/сети**: Пользовательская сеть создается `podman network create mynet` или Quadlet-юнитом `mynet.network`.

#### 3. Дефолтная сеть `podman` (bridge)

В Podman DNS-резолвинг **включен по умолчанию** для сетей, включая дефолтную bridge-сеть `podman` (10.88.0.0/16): Aardvark регистрирует контейнеры по имени и алиасам. Это принципиальное отличие от Docker, где дефолтный bridge DNS не предоставляет (резолвинг есть только в user-defined сетях). Отключить DNS для конкретной сети можно при ее создании флагом `podman network create --disable-dns`.

---

### Механизм sd_notify в деталях

Для юнитов `.container` и `.kube` Quadlet по умолчанию выставляет `Type=notify`. Подтверждение готовности отправляет Podman/контейнер, в зависимости от режима `--sdnotify`:

| Режим `--sdnotify` | Кто шлет READY | Когда |
| :--- | :--- | :--- |
| `conmon` (по умолчанию) | conmon | Сразу после запуска процесса в контейнере. |
| `container` | Приложение | Приложение само вызывает `sd_notify`/`systemd-notify --ready` в момент готовности. |
| `healthy` | Podman | Только после того, как Healthcheck вернул `healthy` (требует `--health-cmd`). |
| `ignore` | — | Подтверждение не отправляется. |

В Quadlet эти режимы задаются параметром `Notify=`:

- `Notify=healthy` → `--sdnotify=healthy` (задержка до `healthy`, требуется `HealthCmd`);
- `Notify=true` → `--sdnotify=container` (сокет передается приложению, оно шлет READY самостоятельно);
- не задано → режим `conmon` (подтверждение сразу после старта процесса).

Для приложений внутри контейнера готовность отправляется командой `systemd-notify --ready` (пакет `systemd`) или библиотечным вызовом `sd_notify`; сокет передается через переменную окружения `NOTIFY_SOCKET`.

Связка `HealthOnFailure=kill` + `Restart=on-failure` в `[Service]` обеспечивает автоматическое восстановление: контейнер, ставший `unhealthy`, убивается и перезапускается systemd.

### Жизненный цикл контейнера в контексте зависимостей

Когда systemd активирует Quadlet-юнит, запускается следующая цепочка:

1. **Systemd** запускает сгенерированный `.service`-юнит с `Type=notify`.
2. **Podman CLI** (внутри ExecStart) создает контейнер и порождает **conmon**.
3. **Conmon** становится MAINPID для systemd и наблюдает за процессом контейнера.
4. **sd_notify**: в зависимости от режима (`--sdnotify`) conmon или приложение отправляет `READY=1`.
5. **Systemd** переводит юнит в `active`, и зависимые юниты (по `After=`) могут стартовать.

`podman system service` (REST API, совместимый с Docker) не участвует в этой цепочке — он активируется по требованию через сокет и используется внешними инструментами, а не systemd-зависимостями.

### Аутентификация в цепочках зависимостей

Если зависимый сервис (например, база данных) загружается из приватного реестра, учетные данные должны быть доступны **до** запуска контейнера. В Quadlet это обеспечивается через:

- `Authfile=~/.config/containers/auth.json` в секции `[Container]` (путь относительно домашней директории пользователя, который управляет юнитом).
- Переменная окружения `REGISTRY_AUTH_FILE` в `[Container]` или `[Service]`.

```ini
[Container]
Image=registry.example.com/internal/postgres:16
Authfile=~/.config/containers/auth.json
```

Для rootful-служб путь к auth.json: `/run/containers/0/auth.json` (эфемерный) или `/etc/containers/auth.json` (персистентный).

---

## Практические сценарии

### 1. Реализация Readiness через Quadlet (Рекомендуется)

Наиболее надежный способ имитации `depends_on` с проверкой состояния. Приложение стартует только после того, как база данных перешла в статус `healthy`.

**База данных: `db.container`**
```ini
[Unit]
Description=Database Service

[Container]
Image=docker.io/library/postgres:16
# Имя контейнера — используется как DNS-имя в сети приложения
ContainerName=db
# Общая сеть для app и db (Quadlet создаст сеть systemd-app)
Network=app.network
Environment=POSTGRES_PASSWORD=secret

# Проверка готовности внутри образа
HealthCmd=pg_isready -U postgres
HealthInterval=5s
HealthRetries=3
# При переходе в unhealthy — убить контейнер, systemd перезапустит его
HealthOnFailure=kill
# Сообщаем systemd о готовности только когда Healthcheck = healthy
Notify=healthy

[Service]
# Важно: Type=notify и sdnotify=healthy Quadlet выставляет автоматически
Restart=on-failure

[Install]
# default.target — для rootless (systemctl --user); multi-user.target — для системных служб
WantedBy=default.target
```

**Сеть: `app.network`**
```ini
[Network]
Subnet=10.90.0.0/24
```

**Приложение: `app.container`**
```ini
[Unit]
Description=Application Service
# Логическая зависимость: app не запустится без db
Requires=db.container
# Временная зависимость: ждать завершения старта db (до статуса healthy)
After=db.container
# Жесткая связь: если db упадет, app тоже остановится
BindsTo=db.container

[Container]
Image=docker.io/library/my-app:latest
Network=app.network
# DNS-имя db — ContainerName, резолвится через Aardvark
Environment=DB_HOST=db
```

Ключевые моменты:

- Ссылки на другие Quadlet-юниты указываются по имени файла (`db.container`) — Quadlet автоматически транслирует их в имена сгенерированных служб (`db.service`). Указание `db.service` напрямую также допустимо.
- `BindsTo=` останавливает `app` при остановке/сбое `db`; если требуется лишь переживать сбой зависимости — используйте `Requires=` + `After=` без `BindsTo`.
- Если сервисы находятся в одном поде (`Pod=web.pod`), сеть не нужна: соединение выполняется через `localhost` (`Environment=DB_HOST=127.0.0.1`).
- Директива `HealthCmd=pg_isready -U postgres` предполагает, что образ PostgreSQL содержит утилиту `pg_isready` (присутствует в официальных образах).

**Активация:**
```bash
systemctl --user daemon-reload
systemctl --user start db.service app.service

# Проверка порядка: app ждет db
systemctl --user status app.service
# → ● app.service — Application Service
# →   Active: activating (start) ...  пока db не healthy
```

### 2. Ожидание через "Init-логику" в CLI

Если вы не используете systemd (например, в скриптах миграции), используйте циклы ожидания.

```bash
# Запуск БД с проверкой здоровья
podman run -d --name db-server \
  --health-cmd="pg_isready -U postgres" \
  --health-interval=5s --health-retries=10 \
  -e POSTGRES_PASSWORD=secret docker.io/library/postgres:16

# Ожидание готовности порта перед запуском приложения
podman run --rm --network host alpine sh -c '
  until nc -z localhost 5432; do
    echo "Waiting for DB..."
    sleep 1
  done
  echo "DB is up!"'

# Запуск основного приложения
podman run -d --name web-app --network app-net my-web-app
```

Примечания:

- `--network host` в rootless-режиме работает через `pasta` (Podman 4.2+).
- `--link` (как в Docker) в Podman поддерживается лишь для совместимости и добавляет записи в `/etc/hosts`; современный способ — имена через DNS.
- Ожидание только порта (`nc -z`) не гарантирует готовности приложения. Более точный вариант — цикл по статусу Healthcheck: `podman inspect --format '{{.State.Health.Status}}' db-server` до получения `healthy`, либо цикл на прикладной endpoint (`curl -f http://db/ready`).

### 3. Использование `depends_on` в Compose-эквивалентах

Спецификация Compose определяет условия `depends_on`:

- `service_started` (по умолчанию) — сервис запущен (процесс стартовал);
- `service_healthy` — сервис прошел Healthcheck;
- `service_completed_successfully` — сервис (одноразовая задача) завершился с кодом 0.

**Пример `compose.yaml`:**
```yaml
services:
  db:
    image: docker.io/library/postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5

  web:
    image: docker.io/library/my-app:latest
    depends_on:
      db:
        condition: service_healthy
```

**Реалии инструментов Podman:**

- **`podman-compose` (Python-утилита)** поддерживает простую форму `depends_on` (порядок запуска), однако `condition: service_healthy` реализована ненадежно — поведение ожидания готовности не гарантируется (открытые issues `containers/podman-compose#866`, `#1422`). Перед использованием проверяйте фактическое поведение на своей версии.
- **`podman compose` (встроенная подкоманда)** проксирует команды внешнему провайдеру: с провайдером `docker-compose` логика ожидания (`service_healthy`) реализована корректно, так как ожидание выполняется самим Compose через Docker API.
- **Рекомендация для продакшена**: если требуется гарантированное ожидание готовности, используйте Quadlet + `Notify=healthy` (сценарий 1) либо wait-скрипты (сценарий 2) вместо `depends_on.condition` в `podman-compose`.

Детали инструментов: [Podman Compose](./podman-compose.md).

### 4. Зависимости при `podman generate systemd` (устаревший способ)

`podman generate systemd` генерирует systemd-юниты из существующих контейнеров/подов. Команда официально **deprecated** (рекомендуется Quadlet), но продолжает поддерживаться без новых функций.

```bash
# Генерация юнитов с привязкой порядка и требований
podman generate systemd --new \
  --name web-app \
  --requires db-server \
  --after db-server \
  --files
# → container-web-app.service

podman generate systemd --new --name db-server --files
# → container-db-server.service

systemctl --user daemon-reload
systemctl --user enable --now container-db-server.service container-web-app.service
```

Опции зависимостей: `--wants`, `--requires`, `--after`, `--before` (указываются многократно и добавляются в секцию `[Unit]` сгенерированного файла).

**Готовность с проверкой здоровья** в сгенерированных юнитах настраивается вручную: по умолчанию генерируется `--sdnotify=conmon`, при котором READY отправляется сразу после старта процесса. Для ожидания `healthy` замените в `ExecStart` на `--sdnotify=healthy` и добавьте `--health-cmd='pg_isready -U postgres'` (или соответствующий флаг вашего образа). После этого `--requires=...` + `--after=...` гарантируют старт приложения только после готовности зависимости.

### 5. Диагностика и отладка

При проблемах с запуском зависимых служб используйте следующие инструменты:

**Проверка состояния юнитов:**
```bash
systemctl --user status db.service app.service
# Если db.service застрял в статусе activating — Healthcheck не проходит
# или Notify=healthy не срабатывает
```

**Просмотр сгенерированного юнита (проверка `--sdnotify` и директив):**
```bash
systemctl --user cat db.service
# → [Service]
# → ExecStart=/usr/bin/podman run ... --sdnotify=healthy ...
```

**Анализ логов готовности:**
```bash
# Просмотр событий Healthcheck в реальном времени
podman events --filter event=health_status
# → 2026-07-27 ... container health_status db (status=unhealthy)

# Логи службы
journalctl --user -u app.service
```

**Инспекция статуса здоровья:**
```bash
podman inspect --format '{{.State.Health.Status}}' db
# → healthy
```

**Верификация Quadlet-файлов (проверка зависимостей и синтаксиса):**
```bash
systemd-analyze --user --generators=true verify app.container
```

### 6. Rootless + Linger для постоянных служб

В rootless-режиме пользовательские службы останавливаются при выходе пользователя из системы. Для постоянной работы включите linger:

```bash
# Включить linger (от root)
sudo loginctl enable-linger $USER

# Проверка
loginctl show-user $USER -p Linger
# → Linger=yes
```

После этого `systemctl --user enable --now app.service` будет работать без активной сессии. Для rootless-служб используйте каталог `~/.config/containers/systemd/` для Quadlet-файлов. Подробнее о rootless-окружении: [Rootless режим](./podman_rootless.md).

```ini
# ~/.config/containers/systemd/app.container
[Unit]
Description=App Service (rootless)
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/library/my-app:latest
Network=app.network
Environment=DB_HOST=db

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now app.service
```

### 7. Приватный реестр и аутентификация в цепочках зависимостей

Если образы зависимых сервисов хранятся в приватном реестре, настройте `auth.json` **до** запуска юнитов:

```bash
# Rootless: персистентный файл
mkdir -p ~/.config/containers
podman login --authfile ~/.config/containers/auth.json registry.example.com

# Rootful: персистентный файл
sudo mkdir -p /etc/containers
sudo podman login --authfile /etc/containers/auth.json registry.example.com
```

В Quadlet:

```ini
[Container]
Image=registry.example.com/internal/postgres:16
Authfile=~/.config/containers/auth.json
HealthCmd=pg_isready -U postgres
Notify=healthy
```

Для CI/CD используйте переменную окружения:

```ini
[Service]
Environment=REGISTRY_AUTH_FILE=/run/secrets/registry-auth.json
```

### 8. Ограничение ресурсов и изоляция

В production задавайте лимиты на уровне Quadlet, чтобы зависимый сервис не потреблял все ресурсы хоста:

```ini
[Container]
Image=docker.io/library/postgres:16
Cpus=1.5
Memory=1g
PidsLimit=100
HealthCmd=pg_isready -U postgres
Notify=healthy

[Service]
Restart=on-failure
RestartSec=5
```

Дополнительные параметры изоляции:

```ini
[Container]
CapDrop=ALL
SecurityOpt=no-new-privileges
ReadOnly=true
Tmpfs=/tmp:/tmp
```

В rootless-режиме для лимитов CPU и I/O требуется делегирование cgroup-контроллеров (см. [Rootless режим](./podman_rootless.md)).

### 9. Production best practices

**Стратегия обновления с откатом:**

1. Используйте FQIN с Digest для детерминированности: `Image=registry.example.com/postgres@sha256:abc123...`.
2. Настройте `HealthStartupCmd` как шлюз (Podman 5.0+) — основная проверка не начнется, пока старт не завершится.
3. Задайте `HealthOnFailure=kill` для автоматического перезапуска при unhealthy.
4. Мониторьте события: `podman events --filter event=health_status`.
5. Сохраняйте старые образы: `podman image prune` удаляет только неиспользуемые; для отката оставьте предыдущий слой.

**Резервное копирование auth.json:**

```bash
# Rootless
cp ~/.config/containers/auth.json ~/.config/containers/auth.json.bak

# Rootful
sudo cp /etc/containers/auth.json /etc/containers/auth.json.bak
```

### 10. Мониторинг и алертинг

Сбор логов и метрик из зависимых служб:

```bash
# Логи конкретного юнита
journalctl --user -u app.service --since "1 hour ago" -f

# События health_status в реальном времени
podman events --filter event=health_status --format '{{.Time}} {{.Actor}} {{.Status}}'

# Статус всех контейнеров с healthcheck
podman ps --filter health=unhealthy --format 'table {{.Names}}\t{{.Status}}'
```

Synthetic Healthcheck из systemd (проверка зависимостей извне):

```ini
[Service]
ExecStopPost=/usr/local/bin/check-db-health.sh
```

```bash
#!/bin/bash
# check-db-health.sh
for i in $(seq 1 10); do
  if podman exec db pg_isready -U postgres >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done
echo "DB dependency failed" >&2
exit 1
```

## Устранение неполадок

### Ошибка: `db.service` завис в activating

**Симптом:** `systemctl status app.service` показывает `activating (start)` бесконечно.

**Причины и решения:**

1. **Healthcheck не проходит:**
   ```bash
   # Проверка статуса healthcheck
   podman inspect --format '{{.State.Health.Status}}' db
   # → unhealthy

   # Просмотр логов healthcheck
   podman logs db
   # Убедитесь, что команда HealthCmd существует в образе
   ```

2. **Notify=healthy без HealthCmd:**
   ```bash
   # Проверка Quadlet-файла
   systemctl --user cat db.service | grep sdnotify
   # → --sdnotify=healthy

   # Если HealthCmd отсутствует, добавьте его в [Container]
   # Или измените на Notify=true / Notify=conmon
   ```

3. **Таймаут systemd:**
   ```bash
   # Увеличьте TimeoutStartSec
   systemctl --user set-property db.service TimeoutStartSec=120
   ```

### Ошибка: `Failed to start app.service: Unit not found`

**Причина:** Зависимый юнит не найден. Убедитесь, что имена указаны правильно:

```bash
# В Quadlet ссылки указываются по имени файла без расширения
Requires=db.container   # правильно
Requires=db.service      # также допустимо
Requires=db              # неправильно
```

### Ошибка: DNS не резолвит `db`

**Симптом:** Приложение не может подключиться к `db` по имени.

**Решение:**

```bash
# Проверка контейнерного DNS
podman exec app nslookup db
# → должен вернуть IP контейнера db

# Если контейнеры в разных сетях, используйте FQIN с сетью
Network=app.network

# Или используйте localhost внутри пода
Pod=myapp.pod
Environment=DB_HOST=127.0.0.1
```

### Ошибка: `authentication required` при pull

**Симптом:** Зависимый сервис не стартовал из-за ошибки авторизации.

**Решение:**

```bash
# Проверка auth.json
cat ~/.config/containers/auth.json | jq '.auths["registry.example.com"]'

# Повторный логин
podman login --authfile ~/.config/containers/auth.json registry.example.com

# Для systemd-юнитов укажите authfile в Quadlet
Authfile=~/.config/containers/auth.json
```

### Ошибка: `dial tcp` / `connection refused`

**Симптом:** Приложение стартовало, но не может подключиться к зависимости.

**Причина:** Зависимость еще не готова, несмотря на `After=`. Используйте `Notify=healthy` вместо простого `After=`.

```ini
[Container]
Image=docker.io/library/postgres:16
HealthCmd=pg_isready -U postgres
Notify=healthy
```

---

## Нюансы и ограничения

- **Порядок внутри пода**: Podman не гарантирует порядок запуска контейнеров внутри одного пода (см. [Поды в Podman](./podman_pods.md)). Для управления порядком используйте отдельные Quadlet-юниты с директивами `[Unit]`.
- **`BindsTo=` останавливает зависимые**: при остановке или сбое базы данных связанные приложения будут остановлены. Для слабой связи используйте `Wants=` + `After=`.
- **`Requires=` без `After=`**: если задано только `Requires=`, зависимость активируется, но может стартовать параллельно — требуемая связь может оказаться не готова к моменту старта приложения.
- **READY без Healthcheck**: режим `Notify=healthy`/`--sdnotify=healthy` без `HealthCmd` бессмыслен — READY не будет отправлен вовсе, и служба зависнет в `activating` до таймаута. Для проверки используйте `Notify=healthy` только вместе с `HealthCmd`.
- **Readiness ≠ старт процесса**: подтверждение conmon (режим по умолчанию) означает лишь запуск процесса, а не готовность приложения. Для зависимостей, где важен именно Ready-статус, настраивайте Healthcheck.
- **DNS-имена**: резолвятся имена контейнеров/алиасы, а не имена systemd-юнитов. `Environment=DB_HOST=db.service` (имя юнита) работать не будет — используйте `DB_HOST=db` (имя контейнера) или `127.0.0.1` внутри пода.
- **podman-compose**: `depends_on.condition: service_healthy` в Python-реализации ненадежна (см. сценарий 3); не полагайтесь на нее без теста.
- **Rootless**: пользовательские службы требуют активной пользовательской сессии systemd (`systemctl --user`) и `loginctl enable-linger` для работы без входа пользователя в систему.

---

## Дополнительная информация

### Сравнение методов управления

| Метод | Плюсы | Минусы |
| :--- | :--- | :--- |
| **systemd (Quadlet)** | Максимальная надежность, нативный откат, управление ресурсами, ожидание `healthy`. | Требует настройки юнит-файлов. |
| **Wait-скрипты** | Простота, не зависит от системы инициализации. | "Засорение" образов, отсутствие мониторинга после старта. |
| **Podman Compose** | Привычный синтаксис Docker Compose, переносимость файлов. | `condition: service_healthy` ненадежен в `podman-compose` (Python); требует внешнего провайдера для `podman compose`. |

### Связанные разделы

- **[Проверки состояния (Healthcheck) в Podman](./podman_healthchecks.md)** — синтаксис проверок и параметры `HealthCmd`, используемые для готовности.
- **[Поды в Podman](./podman_pods.md)** — разделяемое сетевое пространство имен и ограничения порядка запуска внутри пода.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — интеграция Podman с systemd и Quadlet.
- **[Rootless режим](./podman_rootless.md)** — linger, cgroup delegation, пользовательские службы.
- **[Podman vs Docker](./podman_vs_docker.md)** — архитектурные различия и выбор инструмента.
- **[Podman Compose](./podman-compose.md)** — особенности `depends_on` и `service_healthy`.

### Версионирование

| Версия Podman | Особенности зависимостей и готовности |
| :--- | :--- |
| **4.x** | Базовый `sdnotify=conmon`/`container`, Quadlet стабилен. `podman generate systemd` — основной способ. |
| **5.0** | Добавлен Startup Healthcheck (Gate) как часть верификации. `pasta` по умолчанию для rootless. |
| **5.3** | Улучшено взаимодействие rootless-контейнера с хостом (`host.containers.internal`). |
| **6.0+** | Полная поддержка `HealthOnFailure`, динамическое обновление параметров Healthcheck через `podman update`. Удалена поддержка CNI, BoltDB, slirp4netns. Рекомендуемая версия. |

### Ссылки

- **[podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** — официальная документация Quadlet: директива `Notify=`, `HealthOnFailure`, трансляция зависимостей `[Unit]` (англ.).
- **[podman-generate-systemd(1)](https://docs.podman.io/en/latest/markdown/podman-generate-systemd.1.html)** — флаги `--after`/`--requires`/`--new`, статус deprecation (англ.).

# force reindex test
