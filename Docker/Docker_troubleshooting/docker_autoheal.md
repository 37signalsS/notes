# Autoheal в Docker: Автоматическое восстановление контейнеров

**Актуально для:** willfarrell/autoheal (образ `latest`, entrypoint на Alpine), Docker Surgeon 1.1.x

## Определения

**Autoheal** — внешний монитор (контейнер `willfarrell/autoheal`), который периодически опрашивает Docker API и перезапускает контейнеры, перешедшие в статус `unhealthy` по результатам их **Healthcheck**.

**Self-Healing (Самовосстановление)** — архитектурный паттерн, при котором система самостоятельно обнаруживает и исправляет сбои выполнения без вмешательства администратора.

**Dependency-Aware Healing** — восстановление с учётом зависимостей между контейнерами (например, в `Docker Surgeon`: API-сервис перезапускается только после успешного восстановления базы данных).

> **Важно:** Autoheal дополняет стандартную политику `restart`, решая проблему «зависших» приложений, которые продолжают работать (статус `running`), но не выполняют свои функции (статус `unhealthy`). Политика `restart` реагирует только на завершение основного процесса (статус `exited`).

## Основные концепции

### Связка механизмов восстановления

Для полной защиты контейнера необходимо комбинировать три уровня настроек:

1.  **Restart Policy (`restart`):** Docker Engine перезапускает контейнер, если основной процесс завершился (статус `exited`).
2.  **Healthcheck:** инструкция в `Dockerfile` или `compose.yaml`, по которой Docker Engine помечает контейнер `unhealthy` после `retries` неудачных проверок.
3.  **Autoheal:** внешний монитор, который находит контейнеры со статусом `unhealthy` и инициирует их перезапуск.

### Как работает willfarrell/autoheal

Autoheal **не слушает Docker Events** — он опрашивает Docker API. Цикл работы (из исходного кода `docker-entrypoint`):

1.  Каждые `AUTOHEAL_INTERVAL` секунд выполняется запрос `GET /containers/json?filters={"health":["unhealthy"],"label":["<метка>=true"]}` — через unix-сокет (`DOCKER_SOCK`) или TCP/TLS-эндпоинт.
2.  Из ответа исключаются: контейнеры с меткой `autoheal=False`, контейнеры в состоянии `restarting` (чтобы не вклиниваться в идущий перезапуск) и уже удалённые (имя `null`).
3.  Для каждого оставшегося контейнера вызывается `POST /containers/{id}/restart?t={timeout}` — один API-вызов, который выполняет graceful stop (SIGTERM, ожидание до `timeout` секунд) и затем `start`.
4.  Уведомления (`WEBHOOK_URL` / `APPRISE_URL`) и `POST_RESTART_SCRIPT` выполняются асинхронно (фоном), чтобы не блокировать монитор.

Сам контейнер Autoheal имеет собственный `HEALTHCHECK --interval=5s CMD pgrep -f autoheal || exit 1` — монитор контролирует работоспособность своего основного процесса.

### Инструменты автоматического восстановления

#### 1. willfarrell/autoheal

Классическое и наиболее лёгкое решение для одиночных хостов (Alpine + curl + jq).

-   **Принцип:** polling Docker API через смонтированный Docker Socket, выбор контейнеров по метке `autoheal=true`.
-   **Уведомления:** `WEBHOOK_URL` (произвольный webhook; JSON-тело с настраиваемым ключом `WEBHOOK_JSON_KEY`) и **Apprise** (`APPRISE_URL`) — поддержка Apprise добавлена в октябре 2021 г. и позволяет доставлять сообщения в 60+ сервисов (Telegram, Discord, Slack, ntfy) через сервер `caronc/apprise`.
-   **Post-restart скрипт:** `POST_RESTART_SCRIPT` — команда внутри контейнера Autoheal, запускаемая после каждого перезапуска (и после неудачного перезапуска).

#### 2. Docker Surgeon

Современная альтернатива для сложных сред (образ на Docker Hub — `krystall0/docker-surgeon`, исходный код — `kRYstall9/docker-surgeon`). Python-сервис, который, в отличие от Autoheal, слушает Docker Events в реальном времени.

-   **Dependency Tracking:** порядок перезапуска задаётся меткой `com.monitor.depends.on` (несколько зависимостей — через запятую). Зависимости обрабатываются топологической сортировкой: родительские контейнеры перезапускаются первыми, а зависимые ждут здоровья родителя (начиная с v1.1.0).
-   **Политика перезапуска:** переменная `RESTART_POLICY` (JSON) — список исключённых контейнеров и кодов выхода, не вызывающих перезапуск.
-   **Multi-host:** мониторинг нескольких удалённых хостов через агенты.
-   **Уведомления:** Apprise. **Dashboard:** в README упоминается дашборд (рекомендуется сохранять данные в `/app/app/data`); порт дашборда в документации не указан — требует проверки.

## Практические сценарии

### Сценарий 1: Автовосстановление с уведомлениями (Docker Compose)

Базовая настройка с webhook-уведомлениями:

```yaml
services:
  app:
    image: your-app:latest
    restart: unless-stopped
    labels:
      - "autoheal=true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s         # Провалы в первые 2 минуты не считаются — время старта JVM

  autoheal:
    image: willfarrell/autoheal:latest
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock # Критически важно для доступа к Docker API
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal   # Мониторить контейнеры с меткой autoheal=true
      AUTOHEAL_INTERVAL: 30                # Опрашивать API раз в 30 с (дефолт: 5)
      AUTOHEAL_START_PERIOD: 180           # Однократная задержка первого прохода после старта монитора
      AUTOHEAL_DEFAULT_STOP_TIMEOUT: 30    # Ожидание graceful stop перед kill (дефолт: 10)
      WEBHOOK_URL: http://webhook-receiver:8080/hook
      WEBHOOK_JSON_KEY: content            # Ключ в JSON-теле — адаптируйте под приёмник
```

**Уведомления через Telegram (через Apprise).** Apprise работает как отдельный сервер:

```bash
# Шаг 1: запустить сервер Apprise (в той же compose-сети, что и autoheal)
docker run -d --name apprise --restart=always -p 8000:8000 caronc/apprise

# Шаг 2: создать конфигурацию уведомлений для Autoheal
curl -X PUT "http://localhost:8000/cfg/autoheal" \
  -H "Content-Type: text/yaml" \
  --data-binary "urls:
  - tgram://<bot_token>@<chat_id>"
# → 200 OK (конфигурация сохранена; <bot_token> и <chat_id> — из @BotFather)

# Шаг 3: указать Autoheal адрес конфигурации (в environment сервиса autoheal):
#   APPRISE_URL=http://apprise:8000/notify/autoheal
```

При перезапуске контейнера Autoheal отправляет на Apprise payload `{"title":"Autoheal","body":"Container app (...) found to be unhealthy. Successfully restarted the container!"}`.

### Сценарий 2: Глобальный запуск через CLI

Запуск монитора для всех контейнеров на хосте, имеющих метку `autoheal=true`:

```bash
docker run -d \
  --name autoheal \
  --restart=always \
  -e AUTOHEAL_CONTAINER_LABEL=autoheal \
  -v /var/run/docker.sock:/var/run/docker.sock \
  willfarrell/autoheal:latest
```

**Вариант «все контейнеры»:** специальное значение `all` снимает фильтр по метке — мониторятся все контейнеры с healthcheck (контейнеры с меткой `autoheal=False` при этом исключаются):

```bash
docker run -d \
  --name autoheal \
  --restart=always \
  -e AUTOHEAL_CONTAINER_LABEL=all \
  -v /var/run/docker.sock:/var/run/docker.sock \
  willfarrell/autoheal:latest
```

### Сценарий 3: Зависимые сервисы через Docker Surgeon

Если API падает без базы данных, используйте перезапуск с учётом зависимостей:

```yaml
services:
  db:
    image: postgres:16
    labels:
      - "autoheal=true"

  api:
    image: my-api:v1
    labels:
      - "autoheal=true"
      - "com.monitor.depends.on=db" # api зависит от db: при падении db перезапускается первым
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "8080"]

  surgeon:
    image: krystall0/docker-surgeon:latest
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./surgeon-data:/app/app/data # Постоянные данные (рекомендуется при включённом дашборде)
    environment:
      LOG_LEVEL: INFO
      RESTART_POLICY: '{"excludedContainers":["surgeon"],"statuses":{"exited":{"codesToExclude":[0]}}}'
```

Логика: если `db` падает → Surgeon перезапускает `db`, затем `api`; если падает `api` → перезапускается только `api`. Политика выше исключает из перезапуска самого Surgeon и контейнеры, завершившиеся с кодом 0.

### Сценарий 4: Тестирование самовосстановления

Контейнер, который гарантированно станет `unhealthy` через ~5 секунд (`interval` × `retries`):

```bash
docker run -d \
  --name test-autoheal \
  --label autoheal=true \
  --health-cmd="exit 1" \
  --health-interval=5s \
  --health-retries=1 \
  alpine sleep 3600
# → <container_id>

# Проверка статуса здоровья:
docker inspect test-autoheal --format '{{.State.Health.Status}}'
# → unhealthy

# Лог Autoheal — фиксация перезапуска:
docker logs autoheal
# → 03-10-2026 18:30:00 Container test-autoheal (a1b2c3d4e5f6) found to be unhealthy - Restarting container now with 10s timeout

# Очистка (без неё контейнер будет перезапускаться бесконечно):
docker rm -f test-autoheal
```

### Сценарий 5: Предотвращение ложных перезапусков при медленном старте

**Причина цикла:** healthcheck без `start_period` помечает медленно стартующее приложение `unhealthy` → Autoheal перезапускает его → приложение снова не успевает стартовать → бесконечный цикл рестартов.

**Пример из практики:** при сбое DNS на хосте контейнеры начали падать в `unhealthy` и перезапускаться. При одновременном перезапуске 20 контейнеров CPU был утилизирован на 100%, а Java-приложения не успевали стартовать, деля эти ресурсы. В итоге система захлёбывалась сама в себя — контейнеры постоянно находились в перезапуске.

**Шаг 1: Проверка применённых настроек**

Entrypoint Autoheal выводит конфигурацию при старте:

```bash
docker logs autoheal
# → AUTOHEAL_CONTAINER_LABEL=autoheal
# → AUTOHEAL_START_PERIOD=180
# → AUTOHEAL_INTERVAL=30
# → AUTOHEAL_DEFAULT_STOP_TIMEOUT=30
# → AUTOHEAL_ONLY_MONITOR_RUNNING=false
```

Если строк нет — Autoheal работает со встроенными дефолтами (интервал 5 секунд, стартовый период 0).

**Шаг 2: Две независимые плоскости настроек**

| Плоскость | Параметр | Что контролирует |
| :--- | :--- | :--- |
| Container-level (`healthcheck`) | `start_period` | Сколько секунд после старта контейнера провалы проверки **не** считаются — Docker Engine не помечает контейнер `unhealthy` |
| Container-level (`healthcheck`) | `interval`, `retries` | Частота проверок и число провалов до `unhealthy` |
| Autoheal-level | `AUTOHEAL_START_PERIOD` | **Однократная** задержка первого прохода мониторинга после старта самого Autoheal (полезна после перезагрузки хоста, когда стартуют все контейнеры сразу) |
| Autoheal-level | `AUTOHEAL_INTERVAL` | Частота polling Docker API |
| Autoheal-level | `AUTOHEAL_DEFAULT_STOP_TIMEOUT` | Таймаут graceful stop перед SIGKILL |

Container-level параметры описаны в [HEALTHCHECK: параметры конфигурации](../Dockerfile/Instructions/health_signals.md#параметры-конфигурации-options). Оба уровня работают независимо — настройки Autoheal дополняют, а не заменяют Healthcheck.

**Шаг 3: Визуальная схема**

```
Контейнер стартует
    │
    ▼
[Container-level: healthcheck.start_period=120s]
│  Docker Engine НЕ помечает контейнер unhealthy
│  при провалах проверок в первые 120 с
    │
    ▼
[Autoheal-level: AUTOHEAL_START_PERIOD=180 — однократно, после старта монитора]
│  Первый проход мониторинга — через 180 с после старта Autoheal
    │
    ▼
Цикл: каждые AUTOHEAL_INTERVAL=30 с
│  unhealthy → graceful stop (до 30 с, AUTOHEAL_DEFAULT_STOP_TIMEOUT) → start
```

**Практическое правило:** если приложение стартует дольше 5 секунд (особенно Java-сервисы, сервисы с миграциями БД и большими кэшами), **всегда** задавайте `start_period` в healthcheck больше реального времени старта. `AUTOHEAL_START_PERIOD` используйте только для отсрочки первого прохода монитора после его собственного старта.

## Валидация

```bash
# 1. Настройки применились (entrypoint выводит их при старте):
docker logs autoheal 2>&1 | grep "AUTOHEAL"

# 2. Монитор работает:
docker inspect autoheal --format '{{.State.Status}} {{.RestartCount}}'
# → running 0

# 3. События перезапусков:
docker events --filter 'event=restart' --format '{{.Time}} {{.Actor.Attributes.name}}'

# 4. Контейнер действительно перезапущен (время старта обновилось):
docker ps --filter name=app --format '{{.Names}} {{.Status}}'
# → app Up 2 minutes (health: healthy)
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Autoheal не перезапускает `unhealthy`-контейнер | У контейнера нет метки `autoheal=true` или она не совпадает с `AUTOHEAL_CONTAINER_LABEL` | `docker inspect <container> --format '{{json .Config.Labels}}'` |
| Autoheal не перезапускает контейнер | У контейнера нет healthcheck — он никогда не станет `unhealthy` | Добавьте `healthcheck` в Dockerfile/compose |
| Autoheal не перезапускает контейнер | Контейнер `paused` и установлен `AUTOHEAL_ONLY_MONITOR_RUNNING=true` | Уберите флаг или разморозьте контейнер (`docker unpause`) |
| Autoheal не перезапускает контейнер | Контейнер уже в состоянии `restarting` — Autoheal пропускает его | Дождитесь завершения перезапуска |
| `unix socket is currently not available` в логах Autoheal | Docker Socket не смонтирован или недоступен | Проверьте `-v /var/run/docker.sock:/var/run/docker.sock` и права на сокет |
| Бесконечный цикл перезапусков | Приложение не успевает стартовать за `start_period` healthcheck | Увеличьте `start_period` (см. [Сценарий 5](#Сценарий-5-Предотвращение-ложных-перезапусков-при-медленном-старте)) |
| Уведомления не приходят | `WEBHOOK_URL` / `APPRISE_URL` недостижимы из контейнера Autoheal (`localhost` — это сам контейнер Autoheal) | Используйте имя сервиса compose или IP хоста; для Apprise — запустите `caronc/apprise` в той же сети |
| В логах `Restarting container ... failed` | API-вызов restart вернул ошибку (например, контейнер удалён параллельно) | Проверьте `docker ps -a` и права доступа к Docker API |

## Лучшие практики

1.  **Не ставьте метку `autoheal=true` на сам контейнер Autoheal** — если монитор станет `unhealthy` (его собственный HEALTHCHECK `pgrep`), он попытается перезапустить себя.
2.  **Ограничьте доступ к сокету:** используйте `tecnativa/docker-socket-proxy` с whitelist эндпоинтов. Учтите: для перезапуска нужен метод `POST` (`/containers/*/restart`) — read-only прокси недостаточно.
3.  **`start_period` healthcheck** — не меньше реального времени старта приложения.
4.  **Мониторьте самого Autoheal:** его HEALTHCHECK (`pgrep -f autoheal`) плюс внешний мониторинг (например, через `docker events`).
5.  **Часовой пояс:** `-v /etc/localtime:/etc/localtime:ro` — временные метки в логах Autoheal будут совпадать с хостом.
6.  **Per-container таймаут:** метка `autoheal.stop.timeout=20` для контейнеров с долгим graceful shutdown (например, при flush кэша на диск).

## Дополнительная информация

### Справочник переменных окружения (willfarrell/autoheal)

| Переменная | Дефолт | Описание |
| :--- | :--- | :--- |
| `AUTOHEAL_CONTAINER_LABEL` | `autoheal` | Метка для выбора контейнеров (значение метки должно быть `true`). Специальное значение `all` — мониторить все контейнеры с healthcheck |
| `AUTOHEAL_INTERVAL` | `5` | Интервал polling Docker API, секунд |
| `AUTOHEAL_START_PERIOD` | `0` | Однократная задержка первого прохода мониторинга после старта самого Autoheal, секунд |
| `AUTOHEAL_DEFAULT_STOP_TIMEOUT` | `10` | Таймаут graceful stop перед SIGKILL при перезапуске (переопределяется меткой `autoheal.stop.timeout`) |
| `AUTOHEAL_ONLY_MONITOR_RUNNING` | `false` | `true` — мониторить только running-контейнеры (paused игнорируются) |
| `DOCKER_SOCK` | `/var/run/docker.sock` | Unix-сокет или TCP/TLS-эндпоинт (`tcp://...`, `tcps://...` с клиентскими сертификатами в `/certs`) |
| `CURL_TIMEOUT` | `30` | `--max-time` для запросов к Docker API, секунд |
| `WEBHOOK_URL` | пусто | Webhook для уведомлений о перезапуске (и о неудачном перезапуске) |
| `WEBHOOK_JSON_KEY` | `content` | Ключ в JSON-теле webhook (адаптируйте под приёмник, например `message` для ntfy) |
| `APPRISE_URL` | пусто | URL конфигурации на сервере Apprise (`caronc/apprise`), например `http://apprise:8000/notify/autoheal` |
| `POST_RESTART_SCRIPT` | пусто | Скрипт внутри контейнера Autoheal, запускаемый после перезапуска; аргументы: `CONTAINER_NAME`, `CONTAINER_SHORT_ID`, `CONTAINER_STATE`, `RESTART_TIMEOUT` |

### Метки контейнеров

| Метка | Описание |
| :--- | :--- |
| `autoheal=true` | Включает мониторинг контейнера (при `AUTOHEAL_CONTAINER_LABEL=autoheal`) |
| `autoheal=False` | Исключает контейнер из мониторинга (полезно при `AUTOHEAL_CONTAINER_LABEL=all`) |
| `autoheal.stop.timeout=20` | Per-container таймаут graceful stop при перезапуске, секунд |

### Сравнение методов восстановления

| Метод | Уровень | Когда использовать | Плюсы |
| :--- | :--- | :--- | :--- |
| **Restart Policy** | Процесс | Всегда | Минимум накладных расходов |
| **Autoheal** | Состояние | Single Host / Edge | Простота, уведомления |
| **Docker Surgeon** | Система | Сложные стеки | Зависимости, Web UI |
| **Orchestrator** | Кластер | Swarm / K8s | Нативное самовосстановление |

### Нюансы использования

*   **Безопасность:** монтирование Docker Socket даёт полный контроль над хостом. Ограничивайте доступ через Docker Contexts или защищённые прокси (например, `tecnativa/docker-socket-proxy`) — для перезапуска Autoheal нужны права на запись (метод `POST`).
*   **Логирование:** всегда проверяйте логи Autoheal/Surgeon при отладке цикличных рестартов (Restart Loops) — каждое событие логируется с датой и short ID контейнера. Если приложение падает сразу после запуска, увеличьте `start_period` в healthcheck — см. [Сценарий 5](#Сценарий-5-Предотвращение-ложных-перезапусков-при-медленном-старте).
*   **Оркестрация:** в **Docker Swarm** и **Kubernetes** внешние инструменты не нужны. Оркестратор сам убивает и пересоздаёт задачи/поды, если пробы здоровья (`livenessProbe`) не проходят.
*   **Podman:** используйте встроенную политику `--restart-policy` и systemd/Quadlet. `podman auto-update` обновляет образы, но не лечит `unhealthy`-контейнеры — для healthcheck-логики применяйте мониторинг через `podman events` и systemd-таймеры.

### См. также

*   **[Инструкции HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)** — глубокое погружение в настройку проверок.
*   **[Политики перезапуска](../docker_commands.md#политики-перезапуска)** — базовый уровень восстановления.
*   **[Диагностика через Docker Events](./debugging_with_docker_events.md)** — мониторинг событий `health_status: unhealthy` и `restart`.
