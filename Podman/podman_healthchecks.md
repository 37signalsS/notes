# Проверки состояния (Healthcheck) в Podman

## Предварительные требования

### Требования к окружению

- **Podman >= 5.0** для поддержки Startup Healthcheck (Gate); рекомендуется **Podman >= 6.0** для полной поддержки `HealthOnFailure`, динамического обновления параметров через `podman update` и стабильной работы `HealthStartupSuccess`.
- **systemd >= 245** (рекомендуется >= 247) — требуется для интеграции через Quadlet и работы `sd_notify`. На дистрибутивах без systemd (например, Alpine с OpenRC) healthcheck работает только через CLI, без `Notify=healthy`.
- **OCI Runtime**: по умолчанию используется `crun`; поддерживаются также `runc`, `runj`, `kata`, `runsc`.
- **Rootless-режим**: если healthcheck используется в user-юнитах systemd, требуется `loginctl enable-linger $USER` для работы без интерактивной сессии.

### Инициализация окружения

```bash
# Проверка версии Podman
podman --version
# → podman version 6.0.2

# Проверка поддержки systemd
systemctl --version
# → systemd 255 (255.4-1.el9_4.6)

# Проверка linger (для rootless)
loginctl show-user $USER -p Linger
# → Linger=yes
```

---

## Определения

**Healthcheck (Проверка состояния)** — встроенный механизм мониторинга работоспособности приложения внутри контейнера. В Podman выполнение проверок делегируется монитору `conmon` или системе инициализации **systemd** (через Quadlet).

**Startup Healthcheck (Проверка при запуске)** — (введено в Podman 5.0, расширено в 6.x) фаза «входного контроля» для приложений с длительной инициализацией. Является блокирующим механизмом (Gate): основной цикл проверок не начнется, пока фаза старта не завершится успешно. В Podman 6.x параметр `--health-startup-success` позволяет настроить количество успешных проверок для завершения фазы (по умолчанию 1).

**Liveness Healthcheck** — основной цикл проверки, выполняемый на протяжении всей жизни контейнера после успешного завершения Startup-фазы. В Podman отсутствует отдельный флаг `--health-liveness`; вместо этого вся проверка после старта считается liveness-проверкой.

**Health Failure Action** — действие, которое Podman автоматически предпринимает при переходе контейнера в статус `unhealthy`. Поддерживаемые значения: `none` (только смена статуса), `restart` (перезапуск контейнера), `kill` (остановка) или `reboot` (перезагрузка хоста — требует привилегий).

**Notify=healthy** — параметр интеграции с **systemd** (Quadlet), позволяющий считать сервис успешно запущенным только после того, как внутренняя проверка вернет статус `healthy`. Транслируется в флаг `podman run --sdnotify=healthy`.

**sd_notify** — протокол уведомлений systemd, используемый для передачи сообщения `READY=1` от приложения к менеджеру системных служб. Службы с `Type=notify` остаются в состоянии `activating`, пока не получат сообщение READY или не истекут таймауты (`TimeoutStartSec`).

**conmon (Container Monitor)** — легковесный монитор жизненного цикла контейнера. В контексте healthcheck conmon отвечает за запуск команды проверки согласно расписанию, запись результатов в хранилище и передачу статуса в systemd (при использовании `sdnotify`). Подробнее о роли conmon: [Daemonless архитектура](./podman_daemonless_architecture.md).

---

## Основные концепции

### Архитектура выполнения проверок

В Podman архитектура **daemonless** определяет способ работы проверок:

1. **Отсутствие центрального демона**: В отличие от Docker, где за проверками следит демон `dockerd`, в Podman за каждую проверку отвечает процесс `conmon`. Если контейнер запущен через systemd, за состоянием следит сама система инициализации.
2. **Форматы образов**: По умолчанию Podman использует OCI-образы, которые не хранят метаданные проверок (в отличие от Docker-формата). Рекомендуется всегда описывать проверки на уровне рантайма (CLI или Quadlet). Директива `HEALTHCHECK` из Dockerfile работает в Podman при использовании Docker-формата образов, но для переносимости настройки следует дублировать в Quadlet.
3. **Логика Gating (Шлюзование)**: С версии 6.x подчеркивается роль Startup Healthcheck как шлюза. Пока `--health-startup-cmd` не вернет успех согласно параметру `--health-startup-success`, основная `--health-cmd` даже не будет запущена, что экономит ресурсы и предотвращает ложные алерты.
4. **Жизненный цикл проверки**: `conmon` запускает команду `HealthCmd` в отдельном процессе. Результат (exit code 0 = healthy, non-zero = unhealthy) записывается в хранилище. В Podman 6.x по умолчанию используется SQLite-бэкенд для хранения истории проверок.

### Динамическое управление (Podman 6.x+)

Podman позволяет изменять параметры Healthcheck для **уже запущенных** контейнеров без их перезапуска с помощью команды `podman update`. Это касается интервалов, количества попыток и даже самой команды проверки. Динамически изменяемые параметры: `--health-interval`, `--health-retries`, `--health-cmd`, `--health-timeout`, `--health-startup-interval`, `--health-startup-retries`, `--health-startup-cmd`.

### Интеграция с systemd (sd_notify)

Для юнитов `.container` и `.kube` Quadlet по умолчанию выставляет `Type=notify`. Подтверждение готовности отправляет Podman/контейнер в зависимости от режима `--sdnotify`:

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

### Особенности Rootless-режима

В Rootless-режиме (через `pasta`) проверка всегда выполняется внутри сетевого неймспейса, поэтому `localhost` внутри `HealthCmd` всегда указывает на сам контейнер. Для доступа к хосту используйте `host.containers.internal` (Podman 5.3+) или явный IP-адрес интерфейса pasta.

### Хранение истории проверок

По умолчанию Podman хранит историю проверок в памяти с возможностью выноса в SQLite. Использование `--health-log-destination` позволяет вынести логи в файлы для долгосрочного анализа. Параметры управления:
- `--health-log-destination=/path/to/file` — путь к файлу логов
- `--health-max-log-count=N` — максимальное количество записей (по умолчанию 5)
- `--health-max-log-size=BYTES` — максимальный размер файла (по умолчанию 1MB)

---

## Практические сценарии

### 1. Настройка через CLI с управлением логами

Пример для приложения, требующего детальной диагностики и управления размером логов.

```bash
podman run -d \
  --name app-server \
  # Фаза старта (Startup Gate)
  --health-startup-cmd="curl -f http://localhost:8080/ready || exit 1" \
  --health-startup-interval=5s \
  --health-startup-retries=10 \
  --health-startup-success=1 \
  # Основная фаза
  --health-cmd="curl -f http://localhost:8080/live || exit 1" \
  --health-interval=30s \
  --health-retries=3 \
  --health-timeout=3s \
  # Управление логами (Podman 6.x)
  --health-log-destination=/var/log/app-health.log \
  --health-max-log-count=10 \
  --health-max-log-size=500 \
  # Реакция на сбой
  --health-on-failure=restart \
  my-app-image
```

**Валидация:**
```bash
# Проверка статуса и истории последних проверок
podman inspect app-server --format '{{json .State.Health}}' | jq
# → {
#     "Status": "healthy",
#     "FailingStreak": 0,
#     "Log": [
#       {"Start": "...", "End": "...", "ExitCode": 0, "Output": "..."}
#     ]
#   }

# Проверка параметров Startup-фазы
podman inspect app-server --format '{{json .Config.StartupHealthCheck}}' | jq
# → {"Test": ["CMD-SHELL", "curl -f http://localhost:8080/ready || exit 1"], ...}
```

### 2. Использование в Quadlet (Production стандарт)

Декларативное описание в systemd-юните обеспечивает максимальную надежность и интеграцию с зависимостями.

**Файл:** `/etc/containers/systemd/api.container`
```ini
[Unit]
Description=API Service with Advanced Healthcheck
After=network-online.target

[Container]
Image=registry.example.com/api:latest
PublishPort=8080:8080

# Конфигурация Healthcheck
HealthCmd=curl -f http://localhost/health || exit 1
HealthInterval=30s
HealthRetries=3
HealthTimeout=3s
HealthOnFailure=restart

# Настройки Startup (Podman 5.0+)
HealthStartupCmd=curl -f http://localhost/init || exit 1
HealthStartupInterval=5s
HealthStartupRetries=10
HealthStartupSuccess=1

# Интеграция с зависимостями systemd
Notify=healthy

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**Валидация:**
```bash
# Генерация service-юнита и проверка параметров
systemctl --user daemon-reload
systemctl --user cat api.service | grep -E 'sdnotify|ExecStart'
# → ExecStart=/usr/bin/podman run ... --sdnotify=healthy ...

# Проверка статуса
systemctl --user status api.service
# → Active: active (running) since ...

# События healthcheck
podman events --filter event=health_status --format '{{.Time}} {{.Actor}} {{.Status}}'
# → 2026-09-15 ... container health_status api (status=healthy)
```

### 3. Динамическое обновление параметров

Изменение интервала проверки «на лету» для работающего контейнера.

```bash
# Ускорение проверок при подозрении на нестабильность
podman update --health-interval=5s --health-retries=5 app-server

# Отключение проверок полностью
podman update --no-healthcheck app-server

# Изменение команды проверки
podman update --health-cmd="curl -f http://localhost:8080/new-health || exit 1" app-server
```

**Валидация:**
```bash
# Проверка новых параметров
podman inspect app-server --format '{{.HostConfig.Healthcheck}}'
# → {"Test":["CMD-SHELL","curl -f http://localhost:8080/new-health || exit 1"],"Interval":5000000000,...}

# Принудительный запуск проверки
podman healthcheck run app-server
```

### 4. Проверки в составе Подов (Pods)

В Podman Healthcheck может быть настроен как для отдельного контейнера внутри пода, так и влиять на статус всего пода.

```bash
# Создание пода с healthcheck на уровне контейнера
podman pod create --name web-app-pod -p 8080:80

podman run -d --pod web-app-pod --name nginx-server \
  --health-cmd="curl -f http://localhost/health || exit 1" \
  --health-interval=30s \
  --health-retries=3 \
  --health-on-failure=restart \
  nginx:alpine
```

**Валидация:**
```bash
# Просмотр статуса здоровья контейнера в поде
podman ps --filter pod=web-app-pod --filter health=healthy
# → CONTAINER ID  IMAGE       STATUS    NAMES
# → a1b2c3d4e5f   nginx       Up 5m     web-app-pod-nginx-server

# Если критически важный контейнер в поде переходит в `unhealthy`, 
# действие `restart` затронет только этот контейнер.
# Для мониторинга пода в целом используйте внешние инструменты 
# или связку с systemd-юнитом пода.
```

Динамически изменяемые параметры healthcheck для контейнеров в поде совпадают с обычными контейнерами и применяются через `podman update`.

### 5. Интеграция с Auto-Update и Rollback

Healthcheck является критическим компонентом механизма автообновления с откатом.

```ini
# Quadlet-юнит с автообновлением
[Unit]
Description=Web Application with Auto-Update
After=network-online.target

[Container]
Image=registry.example.com/webapp:v1.2.3
AutoUpdate=registry
HealthCmd=curl -f http://localhost/health || exit 1
HealthInterval=30s
HealthRetries=3
Notify=healthy

[Service]
Restart=on-failure
```

**Валидация:**
```bash
# Проверка наличия метки автообновления
podman inspect webapp --format '{{index .Config.Labels "io.containers.autoupdate"}}'
# → registry

# Проверка отката после неудачного обновления
journalctl --user -u webapp.service --since "1 hour ago"
# → ... Rollback triggered ...
```

Подробнее: [Автообновление и откат в Podman](./podman_auto_update.md).

### 6. Использование в Compose-эквивалентах

```yaml
# compose.yaml
services:
  web:
    image: docker.io/library/my-app:latest
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
```

**Валидация:**
```bash
# Проверка статуса healthcheck через Compose
podman-compose ps
# → NAME                STATUS
# → web-app-web-1       running (healthy)

# Ручная проверка
podman inspect web-app-web-1 --format '{{.State.Health.Status}}'
# → healthy
```

> **Важно:** В `podman-compose` (Python) реализация `depends_on.condition: service_healthy` ненадежна (открытые issues `containers/podman-compose#866`, `#1422`). Для продакшена используйте Quadlet + `Notify=healthy` или wait-скрипты.

Подробнее: [Podman Compose](./podman-compose.md).

---

## Управление и диагностика

### Инспекция состояния и Startup-фазы

Podman 6.x расширил вывод `inspect`, добавив детальную информацию о фазе запуска.

```bash
# Просмотр статуса и истории последних проверок
podman inspect app-server --format '{{json .State.Health}}' | jq

# Проверка параметров Startup-фазы
podman inspect app-server --format '{{json .Config.StartupHealthCheck}}' | jq

# Проверка текущего статуса (удобно для скриптов)
podman inspect --format='{{.State.Health.Status}}' app-server
# → healthy
```

### Ручной запуск и отладка

```bash
# Принудительное выполнение проверки прямо сейчас (независимо от интервала)
podman healthcheck run app-server

# Отладка с полным выводом логов (stdout/stderr команды проверки)
podman --log-level debug healthcheck run app-server
# → DEBU[0000] Running healthcheck: curl -f http://localhost:8080/live || exit 1
# → DEBU[0000] Healthcheck result: 0

# Проверка статуса всех контейнеров с healthcheck
podman ps --filter health=unhealthy --format 'table {{.Names}}\t{{.Status}}'
# → NAMES             STATUS
# → app-server        unhealthy 2 minutes ago
```

### Мониторинг событий

```bash
# События healthcheck в реальном времени
podman events --filter event=health_status
# → container health_status app-server (status=unhealthy)

# С форматированием для SIEM/мониторинга
podman events --filter event=health_status --format '{{.Time}} {{.Actor}} {{.Status}}'
# → 2026-09-15 18:30:00 +0000 UTC app-server unhealthy
```

### Управление логами healthcheck

```bash
# Просмотр логов healthcheck (если настроен --health-log-destination)
cat /var/log/app-health.log

# Очистка логов healthcheck (файл управляется Podman)
truncate -s 0 /var/log/app-health.log
```

---

## Устранение неполадок

### Healthcheck постоянно возвращает `unhealthy`

**Симптомы:** `podman ps` показывает статус `unhealthy`, `podman events` генерирует повторяющиеся события `health_status` со статусом `unhealthy`.

**Диагностика:**

1. **Проверка команды внутри контейнера:**
```bash
# Выполнение команды healthcheck вручную
podman exec app-server curl -f http://localhost:8080/live
# → curl: (7) Failed to connect...

# Проверка доступности порта
podman port app-server
# → 8080/tcp -> 0.0.0.0:8080

# Проверка слушающих портов внутри контейнера
podman exec app-server ss -tlnp
# → LISTEN 0 128 *:8080 ...
```

2. **Проверка таймаутов:**
```bash
# Увеличьте HealthTimeout, если приложение отвечает медленно
podman update --health-timeout=10s app-server
```

3. **Проверка ресурсов контейнера:**
```bash
# Контейнер может быть `unhealthy` из-за нехватки памяти/CPU
podman stats app-server
# → NAME         CPU %  MEM USAGE / LIMIT
# → app-server   0.00%  45MB / 64MB (OOM возможен)

# Проверка наличия OOM-kill в логах
journalctl --user -u app-server.service | grep -i oom
```

4. **Проверка network namespace (rootless):**
```bash
# В rootless-режиме убедитесь, что pasta корректно настроен
podman inspect app-server --format '{{.HostConfig.NetworkMode}}'
# → pasta

# Проверка DNS резолвинга
podman exec app-server nslookup localhost
# → Address: 127.0.0.1
```

### Startup Healthcheck не завершается (зависает в `starting`)

**Симптом:** `podman ps` показывает `health: starting`, Startup-фаза не завершается.

**Причины и решения:**

1. **Команда `HealthStartupCmd` падает:**
```bash
# Проверка выполнения команды вручную
podman exec app-server curl -f http://localhost:8080/ready
# → exit code 6 (Could not resolve host)

# Исправьте URL или настройки сети
```

2. **Неверное значение `HealthStartupSuccess`:**
```bash
# По умолчанию требуется 1 успешная проверка. 
# Для приложений с нестабильным стартом увеличьте:
podman update --health-startup-success=3 app-server
```

3. **Таймаут systemd:**
```bash
# Увеличьте TimeoutStartSec для юнита
systemctl --user set-property app-server.service TimeoutStartSec=120
```

### `Notify=healthy` не работает (юнит зависает в `activating`)

**Симптом:** `systemctl status` показывает `activating (start)` бесконечно.

**Диагностика:**
```bash
# Проверка статуса healthcheck
podman inspect --format '{{.State.Health.Status}}' app-server
# → unhealthy (healthcheck не проходит)

# Проверка параметров sdnotify
systemctl --user cat app-server.service | grep sdnotify
# → --sdnotify=healthy

# Проверка Quadlet-файла
systemctl --user cat app-server.service | grep HealthCmd
# → отсутствует (проблема!)
```

**Решение:** Убедитесь, что `HealthCmd` задан в Quadlet-файле. Без `HealthCmd` режим `--sdnotify=healthy` бессмыслен — READY не будет отправлен.

### Ошибка: `connection refused` при старте контейнера

**Симптом:** Healthcheck падает с `connection refused`, хотя приложение запущено.

**Причина:** Гонка состояний (race condition) — healthcheck выполняется быстрее, чем приложение открывает порт.

**Решение:**
```ini
# Используйте Startup Healthcheck как шлюз
[Container]
HealthStartupCmd="curl -f http://localhost:8080/ready || exit 1"
HealthStartupInterval=5s
HealthStartupRetries=10
HealthStartupSuccess=1

# Основная проверка начинается только после готовности
HealthCmd="curl -f http://localhost:8080/live || exit 1"
HealthInterval=30s
```

### Логи healthcheck не создаются

**Симптом:** Файл, указанный в `--health-log-destination`, не создается или пуст.

**Решение:**
```bash
# Убедитесь, что путь доступен для записи
podman exec app-server touch /var/log/app-health.log

# Или используйте внешний путь через bind-mount
podman run -d \
  --health-log-destination=/host/logs/app-health.log \
  -v /var/log/containers:/host/logs \
  my-app
```

### Healthcheck исчезает после `podman update`

**Симптом:** После `podman update --no-healthcheck` проверка отключена.

**Решение:**
```bash
# Восстановление healthcheck
podman update --health-cmd="curl -f http://localhost:8080/health || exit 1" \
  --health-interval=30s --health-retries=3 app-server
```

---

## Best Practices и очистка

### Рекомендации по проектированию

1. **Используйте Startup Healthcheck для приложений с длительной инициализацией:** Это предотвращает запуск основной проверки до готовности приложения и снижает количество ложных `unhealthy`.
2. **Задавайте `HealthTimeout` явно:** По умолчанию Podman использует значение из `containers.conf` (обычно 1s). Для медленных приложений установите `HealthTimeout=5s` или выше.
3. **Выбирайте осмысленные команды проверки:** Избегайте простых проверок порта (`nc -z localhost 8080`); проверяйте прикладной endpoint (`/health`, `/ready`), который отражает реальную готовность.
4. **Используйте `HealthOnFailure=restart` только для stateless-сервисов:** Для баз данных и очередей предпочтительнее `HealthOnFailure=kill` в связке с `Restart=on-failure` в systemd, чтобы избежать деградации данных при неопределенном состоянии.
5. **Ограничивайте интервалы в production:** Интервал менее 5s при большом количестве контейнеров может создавать нагрузку на хост. Минимальное значение — 1s (не рекомендуется для продакшена).
6. **Храните логи healthcheck отдельно:** Настройте `--health-log-destination` и ротацию через `logrotate` для долгосрочного анализа.

### Очистка и ротация

```bash
# Очистка истории healthcheck в памяти (SQLite)
podman system reset -f
# Внимание: останавливает все контейнеры

# Ротация файлов логов healthcheck
# /etc/logrotate.d/podman-healthcheck
/var/log/containers/*-health.log {
  daily
  rotate 7
  compress
  missingok
  notifempty
}
```

---

## Нюансы и ограничения

- **Отсутствие утилит в образе**: В Distroless или Scratch образах часто нет `curl`. Используйте `/dev/tcp/localhost/8080` (в bash) или специализированные бинарные файлы-чекеры.
- **Производительность**: Каждый запуск `HealthCmd` — это новый процесс. Избегайте интервалов менее 1 секунды при большом количестве контейнеров.
- **Сетевой контекст**: В Rootless-режиме (через `pasta`) проверка всегда выполняется внутри сетевого неймспейса, поэтому `localhost` внутри `HealthCmd` всегда указывает на сам контейнер.
- **Хранение логов**: По умолчанию Podman хранит историю проверок в SQLite. Использование `--health-log-destination` позволяет вынести это в файлы для долгосрочного анализа.
- **Rootless linger**: При использовании `Notify=healthy` в rootless-юнитах убедитесь, что `loginctl enable-linger $USER` выполнен, иначе юнит не стартует при загрузке.
- **Порядок внутри пода**: Podman не гарантирует порядок запуска контейнеров внутри одного пода. Для управления порядком используйте отдельные Quadlet-юниты с директивами `[Unit]`.

### Известные ограничения и баги

- **Healthcheck в `podman-compose` (Python)**: `depends_on.condition: service_healthy` реализована ненадежно (открытые issues `containers/podman-compose#866`, `#1422`). Для продакшена используйте Quadlet + `Notify=healthy`.
- **`slirp4netns` удален в Podman 6.0**: На старых дистрибутивах без pasta healthcheck в rootless-режиме может работать некорректно.
- **CNI удален в Podman 6.0**: Если вы используете кастомные CNI-плагины, мигрируйте на Netavark перед обновлением.

---

## Версионирование

| Версия Podman | Особенности Healthcheck |
| :--- | :--- |
| **4.x** | Базовый `HealthCmd`, `HealthInterval`, `HealthRetries`, `HealthOnFailure`. `podman generate systemd` — основной способ. |
| **5.0** | Добавлен Startup Healthcheck (Gate) как часть верификации. `pasta` по умолчанию для rootless. |
| **5.3** | Улучшено взаимодействие rootless-контейнера с хостом (`host.containers.internal`). |
| **6.0+** | Полная поддержка `HealthOnFailure`, динамическое обновление параметров Healthcheck через `podman update`. Удалена поддержка CNI, BoltDB, slirp4netns. Рекомендуемая версия. |

---

## Сравнение с Docker

| Критерий | Docker | Podman |
| :--- | :--- | :--- |
| **Хранение метаданных** | В Docker-формате образа (совместим с Docker CLI). | В OCI-формате метаданные не хранятся; настраивается на уровне рантайма (CLI/Quadlet). |
| **Запуск проверки** | Централизованно демоном `dockerd`. | Делегировано `conmon` или systemd. |
| **Startup Healthcheck** | Поддерживается с Docker 1.12 (как `--health-startup-period` в Compose v3). | Нативный флаг `--health-startup-cmd` с логикой Gate (Podman 5.0+). |
| **Динамическое обновление** | Требует `docker update --health-*` (ограниченная поддержка). | Полная поддержка через `podman update` (Podman 6.x). |
| **Интеграция с systemd** | Ограниченная, через внешние скрипты. | Нативная через Quadlet (`Notify=healthy`). |
| **Хранение логов** | В выводе `docker inspect` или logging driver. | В SQLite + опционально в файлы (`--health-log-destination`). |

Подробнее об архитектурных различиях: [Podman vs Docker](./podman_vs_docker.md).

---

## Дополнительная информация

### Связанные разделы

- **[Автообновление и откат](./podman_auto_update.md)** — использование Healthcheck для безопасного деплоя.
- **[Управление зависимостями](./podman-dependencies.md)** — как `Notify=healthy` заменяет `depends_on`.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — глубокое описание работы `conmon`.
- **[Поды в Podman](./podman_pods.md)** — особенности healthcheck внутри пода.
- **[Podman Compose](./podman-compose.md)** — нюансы `service_healthy`.
- **[Миграция с Docker](./migration-from-docker.md)** — маппинг `HEALTHCHECK` в Quadlet.

### Ссылки

- **[Podman Healthcheck Documentation](https://docs.podman.io/en/latest/markdown/podman-healthcheck.1.html)** (англ.) — справочник команд healthcheck.
- **[Podman Update Documentation](https://docs.podman.io/en/latest/markdown/podman-update.1.html)** (англ.) — параметры динамического изменения конфигурации.
- **[Podman Healthcheck Run](https://docs.podman.io/en/latest/markdown/podman-healthcheck-run.1.html)** (англ.) — ручное управление проверками.
- **[Quadlet upstream documentation](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** (англ.) — справочник параметров секции `[Container]`.
