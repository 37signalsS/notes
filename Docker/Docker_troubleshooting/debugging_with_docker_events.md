# Отладка с помощью Docker Events

## Определения

**`docker events`** — это команда для просмотра потока системных событий демона Docker в реальном времени. Она позволяет отслеживать изменения состояния объектов (контейнеров, образов, сетей, томов) на уровне управления демоном.

**Gordon AI Integration (2026):** В современных версиях Docker поток событий может быть передан ИИ-помощнику Gordon для автоматического поиска аномалий и корреляции с логами системы.

## Основные концепции

### Когда использовать `docker events`

Стандартные инструменты (`docker logs`, `docker exec`) могут быть неэффективны, если:
- Контейнер завершается слишком быстро (Flapping), и вы не успеваете подключиться к нему.
- Приложение "молчит" в `stdout`/`stderr` перед падением.
- Причина сбоя находится вне приложения: OOM Killer ядра, сбой сетевого плагина или действие оркестратора.

### Типы объектов и событий

| Категория | Объект (`type`) | Типичные события (`event`) |
| :--- | :--- | :--- |
| **Контейнеры** | `container` | `create`, `start`, `stop`, `die`, `oom-kill`, `health_status`, `exec_die` |
| **Образы** | `image` | `pull`, `push`, `tag`, `untag`, `delete` |
| **Сети** | `network` | `create`, `connect`, `disconnect`, `destroy` |
| **Тома** | `volume` | `create`, `mount`, `unmount`, `destroy` |
| **Узлы (Swarm)** | `node` | `create`, `update`, `remove` |
| **Плагины** | `plugin` | `install`, `enable`, `disable`, `remove` |

## Практические сценарии

### Сценарий 1: Диагностика циклического перезапуска (Flapping)

**Симптомы:** Контейнер постоянно перезапускается, логи пусты.

```bash
# Мониторинг событий конкретного контейнера
docker events --filter container=web-app --filter event=die --filter event=health_status
```

**Ожидаемый результат (анализ healthcheck):**
```text
2026-07-19T10:00:05Z container health_status: unhealthy actor.name=web-app
2026-07-19T10:00:05Z container kill signal=15 actor.name=healthcheck
2026-07-19T10:00:06Z container die exitCode=143 actor.name=web-app
```
**Вывод:** Контейнер убит сигналом SIGTERM (15) процессом healthcheck из-за неудовлетворительного состояния здоровья.

### Сценарий 2: Идентификация OOM Killer

**Симптомы:** Контейнер внезапно исчезает или переходит в статус `Exited (137)`.

```bash
# Поиск событий нехватки памяти за последний час
docker events --filter event=oom-kill --since 1h
```

**Ожидаемый результат:**
```text
2026-07-19T11:45:23Z container oom-kill id=abc123name=redis-cache
```

**Действия:**
1. Проверить текущие лимиты: `docker inspect redis-cache --format '{{.HostConfig.Memory}}'`.
2. Сопоставить с системным буфером: `dmesg -T | grep -i "oom-killer"`.
3. Подробнее о кодах завершения: **[Exit Codes](./docker_exit_codes.md)**.

### Сценарий 3: Отслеживание команд `exec` (Аудит)

**Задача:** Узнать, кто и когда входил в контейнер и когда сессия завершилась.

```bash
docker events --filter event=exec_create --filter event=exec_die
```

**Ожидаемый результат:**
```text
2026-07-19T12:00:00Z container exec_create: /bin/bash actor.name=prod-db
2026-07-19T12:15:00Z container exec_die exitCode=0 actor.name=prod-db
```

### Сценарий 4: Анализ событий через Gordon AI (2026)

**Задача:** Автоматически интерпретировать поток событий.

```bash
docker events --format '{{json .}}' | docker ai analyze --stream
# → [Gordon] Обнаружена аномалия: контейнер "worker" упал 5 раз за 2 минуты.
# → [Gordon] Причина: Таймаут подключения к БД (network disconnect в 12:05:01).
```

### Сценарий 5: Экспорт событий в JSON

Для интеграции с внешними системами мониторинга (Loki, ELK).

```bash
docker events --format '{{json .}}' --since 2026-07-19T00:00:00
```

## Дополнительная информация

### Основные флаги

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `--filter` | Фильтрация по ключу (type, event, label, container, image) | `--filter type=volume` |
| `--since` | Начальная точка (RFC3339, timestamp или относительное время) | `--since 30m`, `--since 2026-07-19` |
| `--until` | Конечная точка | `--until 5m` |
| `--format` | Шаблон вывода (Go-templates или `json`) | `--format '{{.Actor.Attributes.name}}'` |

### Сравнение инструментов отладки

| Инструмент | Уровень | Когда лучше |
| :--- | :--- | :--- |
| **`docker events`** | Демон (Infrastructure) | Ошибки жизненного цикла, OOM, Healthchecks |
| **`docker logs`** | Приложение (Stdout/Stderr) | Логика приложения, ошибки внутри кода |
| **`docker inspect`** | Конфигурация (State) | Проверка лимитов, монтирований, IP-адресов |
| **`docker debug`** | Интерактивный (Shell) | Ручная проверка файлов и сети "изнутри" |

### Ограничения и особенности

- **Хранение:** Демон Docker хранит в памяти ограниченное количество событий (обычно до 1000). Если вам нужен глубокий ретроспективный анализ, события должны собираться внешней системой.
- **Производительность:** `docker events` потребляет минимальное количество ресурсов, так как является пассивным слушателем API.
- **Swarm:** В режиме Swarm команда `docker events` на конкретном узле показывает только события этого узла. Для глобальных событий используйте фильтры `type=service`, `type=node` на менеджере.

### Связанные темы

- **[Docker Exit Codes](./docker_exit_codes.md)** — интерпретация кодов завершения.
- **[Docker Debug](./docker_debug.md)** — современный инструмент интерактивной отладки.
- **[Health Signals](../Dockerfile/Instructions/health_signals.md)** — настройка и мониторинг состояния здоровья.
- **[Namespaces](../../Linux/Core/namespaces.md)** — изоляция на уровне ядра.
