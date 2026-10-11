# Отладка с помощью Docker Events

**Актуально для:** Docker Engine 29.x (команда и флаги `--since`/`--until` стабильны с 1.10; перечень событий и фильтров актуален для линейки 27–29)

## Определения

**`docker events`** (алиас `docker system events`) — CLI-команда для просмотра потока системных событий Docker Engine в реальном времени. Она позволяет отслеживать изменения состояния объектов (контейнеров, образов, сетей, томов) на уровне управления демоном.

**Management vs Data Plane:** Команда `docker events` фиксирует события **Management Plane** (создание, остановка, подключение сети). Для отладки **Data Plane** (прохождение отдельных пакетов) рекомендуется использовать инструменты на базе eBPF, такие как `Inspektor Gadget`.

**Анатомия события:** каждое событие содержит `Type` (тип объекта), `Action` (действие), `Actor` (ID объекта и атрибуты — имя, образ, метки, `exitCode` и др.) и `scope` (`local` для событий Engine, `swarm` для кластерных событий Swarm).

**Буфер событий:** демон хранит в памяти только **256 последних событий** (`eventsLimit = 256` в `daemon/events/events.go`). При переполнении вытесняются самые старые события; перезапуск демона очищает буфер полностью. Исторические запросы через `--since` работают только в пределах этого окна.

## Основные концепции

### Как работает подписка

`docker events` — пассивный слушатель API: клиент открывает долгоживущее HTTP-соединение к демону (`GET /events`), демон транслирует события по мере их возникновения. Без флагов `--since`/`--until` показываются только события, возникшие после запуска команды (live-стрим). Указание `--since` или `--until` добавляет к потоку снимок из буфера демона.

### Семантика фильтров

- Повтор одного и того же фильтра (`--filter event=die --filter event=oom`) — логическое **OR**.
- Разные фильтры (`--filter container=web-app --filter event=die`) — логическое **AND**.

### Формат вывода

Строка по умолчанию (атрибуты отсортированы по имени):

```text
<timestamp RFC3339Nano> <Type> <Action> <Actor.ID> (<атрибуты>)
```

Пример:

```text
2026-07-19T10:00:06.123456789+00:00 container die c1f2a3b4c5d6 (exitCode=143, image=nginx:1.27, name=web-app)
```

JSON-вывод (`--format '{{json .}}'`) сериализует поля `Type`, `Action`, `Actor.ID`, `Actor.Attributes`, `scope`, `time` (Unix, секунды), `timeNano` (Unix, наносекунды):

```json
{"Type":"container","Action":"die","Actor":{"ID":"c1f2a3b4c5d6","Attributes":{"exitCode":"143","image":"nginx:1.27","name":"web-app"}},"scope":"local","time":1752919206,"timeNano":1752919206123456789}
```

### Типы объектов и события

| Категория | Объект (`type`) | Типичные события (`event`) |
| :--- | :--- | :--- |
| **Контейнеры** | `container` | `create`, `start`, `restart`, `die`, `oom`, `kill`, `pause`, `unpause`, `rename`, `commit`, `exec_create`, `exec_start`, `exec_die`, `health_status: running`, `health_status: healthy`, `health_status: unhealthy` |
| **Образы** | `image` | `pull`, `push`, `tag`, `untag`, `delete`, `save`, `load`, `import`, `prune` |
| **Сети** | `network` | `create`, `connect`, `disconnect`, `destroy` |
| **Тома** | `volume` | `create`, `mount`, `unmount`, `destroy` |
| **Узлы и сервисы (Swarm)** | `node`, `service` | `create`, `update`, `remove` |
| **Прочее** | `plugin`, `secret`, `config`, `daemon`, `builder` | `create`, `remove`, `update`, `reload` и др. |

Полный перечень событий контейнеров также включает `attach`, `detach`, `resize`, `top`, `copy`, `export`, `checkpoint`, `destroy`. Событие `exec_create` содержит команду в самом действии: `exec_create: /bin/sh -c 'echo hello'`.

## Практические сценарии

### Предварительные требования

- Docker Engine установлен и запущен: `docker info` завершается без ошибок.
- Доступ к сокету демона: пользователь — root или член группы `docker` (`ls -l /var/run/docker.sock`).
- Rootless-режим: экспортируйте `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock`.
- Для Swarm-сценариев — доступ к узлу-менеджеру.

### Сценарий 1: Диагностика циклического перезапуска (Flapping)

**Симптомы:** Контейнер постоянно перезапускается, логи приложения пусты или обрываются, подключиться через `exec` не успевает.

```bash
# Мониторинг жизненного цикла конкретного контейнера
docker events --filter container=web-app --filter event=die --filter event=restart --filter event=health_status
```

**Пример вывода при провале Healthcheck:**

```text
2026-07-19T10:00:05.000000000+00:00 container health_status: unhealthy c1f2a3b4c5d6 (image=nginx:1.27, name=web-app)
2026-07-19T10:00:06.000000000+00:00 container die c1f2a3b4c5d6 (exitCode=143, image=nginx:1.27, name=web-app)
```

**Анализ:** Код 143 (128+15, SIGTERM) после статуса `unhealthy` подтверждает, что контейнер был корректно остановлен оркестратором или `autoheal` на основе данных проверки здоровья. Код 1 — ошибка приложения; 137 (128+9, SIGKILL) — см. Сценарий 2.

### Сценарий 2: Идентификация OOM Killer

**Симптомы:** Контейнер внезапно переходит в статус `Exited (137)`.

```bash
# Поиск событий нехватки памяти за последний час
docker events --filter event=oom --since 1h
```

**Действия:**
1. Если событие `oom` зафиксировано, проверьте флаг и лимит: `docker inspect <id> --format '{{.State.OOMKilled}} {{.HostConfig.Memory}}'`.
2. Сопоставьте время события с выводом `dmesg -T | grep -i "oom-killer"` — строка `oom-kill:constraint=CONSTRAINT_MEMCG` указывает на превышение лимита cgroup контейнера (см. [Диагностика ядра](../../Linux/Diagnostics/Kernel/dmesg/troubleshooting.md)).

**Важно:** событие Docker Engine называется `oom`, а не `oom-kill` — `oom-kill` это паттерн в логах ядра, а не имя события Engine.

### Сценарий 3: Анализ сетевых подключений

**Задача:** Убедиться, что контейнер успешно подключился к пользовательской сети.

```bash
docker events --filter type=network --filter event=connect
```

**Пример вывода:**

```text
2026-07-19T12:30:00.000000000+00:00 network connect a1b2c3d4e5f6 (container=app, name=prod-net)
```

### Сценарий 4: Аудит exec-операций

**Задача:** Установить, кто и когда выполнял команды внутри контейнеров (аудит действий пользователей).

```bash
docker events --filter event=exec_create --filter event=exec_start --format '{{.Time}} {{.Actor.Attributes.name}} {{.Action}}'
```

### Сценарий 5: Запрос исторического окна

**Задача:** Разобрать инцидент, который произошёл час назад (в пределах 256-событийного буфера демона).

```bash
# События от час назад до 30 минут назад; live-стрим не продолжается
docker events --since 1h --until 30m
```

Длительности (`1h`, `30m`, `10s`) и RFC3339-метки (`2026-07-19T10:00:00Z`) принимаются обоими флагами. Длительность в `--until` отсчитывается от текущего момента: `--until 30m` означает «30 минут назад». Указание `--until` отключает live-стрим — команда завершается после выдачи запрошенного окна.

## Валидация

- Команда работает корректно, если при запуске `docker events --filter type=container` в соседнем терминале `docker run --rm alpine echo hi` порождает строки `container create ...` и `container die ... (exitCode=0)`.
- Фильтры применены верно, если `docker events --filter event=oom --since 1h` возвращает только события `oom` (или пустой вывод при их отсутствии) и не завершается ошибкой.
- JSON-вывод валиден, если каждая строка `--format '{{json .}}'` проходит `jq .` без ошибок.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `docker events` не показывает события | Демон не запущен или нет доступа к сокету | `docker info`; проверить `ls -l /var/run/docker.sock` и членство в группе `docker` |
| Нет событий в rootless-режиме | CLI обращается к системному сокету | `export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock` |
| Исторические события пусты | Буфер демона (256 событий) переполнен или очищен перезапуском | Запустить постоянный коллектор: `docker events --format '{{json .}}' \| systemd-cat -t docker-events` |
| `--until 10m` сразу возвращает пустоту | Длительность вычитается из текущего времени — это «10 минут назад», а не «через 10 минут» | Использовать вместе с `--since`: `--since 10h --until 1h` |
| Пропуск событий при высокой интенсивности | Медленный потребитель не успевает в окно приёма pubsub (100 мс, буфер 1024) | Снизить интенсивность фильтрами; агрегировать на стороне коллектора |
| Тысячи событий в секунду | Высокая динамика контейнеров без фильтров | Добавить `--filter`; перенаправлять вывод в syslog/journald или коллектор |

## Best Practices

- **Всегда фильтруйте** в production: `--filter` снижает нагрузку и объём вывода; при >500 контейнерах фильтры обязательны.
- **Комбинируйте с `docker inspect`**: событие `die` даёт `exitCode`, а `docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}'` — финальное состояние контейнера.
- **Алерты на `oom` и `die`**: `docker events --filter event=oom --filter event=die --format '{{json .}}'` — минимальный набор для мониторинга отказов.
- **Остановка потока:** Ctrl+C в интерактивном режиме; в скриптах — `--until` для ограничения окна или завершение процесса пайпа.
- **Долгосрочное хранение:** демон не персистирует события на диск — для расследований, выходящих за 256 событий, настройте форвардинг в journald/syslog или SIEM.

## Дополнительная информация

### Флаги и форматирование

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-f, --filter` | Фильтрация `key=value`; повтор одного ключа — OR, разные ключи — AND | `--filter label=stage=prod` |
| `--since` | События после указанного времени (длительность `1h` или RFC3339) | `--since 10m` |
| `--until` | События до указанного времени; отключает live-стрим | `--until 30m` |
| `--format` | Go-шаблон или `{{json .}}` для обработки скриптами | `--format '{{.Time}} {{.Actor.Attributes.name}}'` |

Поддерживаемые ключи фильтров: `type`, `event`, `container`, `image`, `network`, `volume`, `label` (и `label==` для точного совпадения), `scope`, `node`, `service`, `secret`, `config`, `plugin`, `daemon`.

### Сравнение инструментов отладки

| Инструмент | Фокус | Преимущество |
| :--- | :--- | :--- |
| **`docker events`** | Жизненный цикл | Минимальная нагрузка, ловит «мгновенные» падения. |
| **`docker logs`** | Логика кода | Детальный вывод ошибок приложения. |
| **`docker debug`** | Интерактивность | Shell и Toolbox внутри контейнера/образа даже без `/bin/sh`; функция Docker Desktop 4.33+ (подписка Pro/Teams/Business), в standalone Engine недоступна — см. [docker_debug.md](./docker_debug.md). |
| **eBPF (Inspektor Gadget)** | Трафик и системные вызовы | Анализ Data Plane без внедрения в контейнер. |

### Особенности в разных средах

- **Производительность:** Команда является пассивным слушателем API и практически не потребляет CPU/RAM.
- **Docker Swarm:** На конкретном узле видны только локальные события (`scope=local`). Для мониторинга всего кластера запускайте команду на менеджере с фильтрами `type=service` или `type=node` — кластерные события имеют `scope=swarm`.
- **Программный доступ:** HTTP API `GET /events` с параметрами `since`, `until`, `filters` — основа для автоматизации и коллекторов.

### См. также

- **[Docker Exit Codes](./docker_exit_codes.md)** — интерпретация кодов в событиях `die`.
- **[Docker Debug](./docker_debug.md)** — интерактивная отладка в Docker Desktop.
- **[Зависшие контейнеры](./hung_containers.md)** — события `kill`/`die` при зависании и D-state.
- **[Инструкции HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)** — как генерировать события здоровья.
- **[Диагностика сети](./network_connectivity_issues.md)** — использование сетевых событий.
- **[Мониторинг безопасности](../Docker_security/runtime_monitoring.md)** — аудит через `docker events` и интеграция с auditd/Falco.
- **[Нативные метрики](../Docker_metrics/docker_native_metrics.md)** — события в контексте метрик Docker.
