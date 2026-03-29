# Debugging with Docker Events

## Определения

**`docker events`** — команда для просмотра потока системных событий демона Docker в реальном времени. Показывает действия на уровне демона, а не внутри контейнера.

## Основные концепции

### Когда использовать `docker events`

Стандартные инструменты (`docker logs`, `docker exec`) бесполезны, если:
- Контейнер перезапускается слишком быстро
- Приложение не пишет в stdout/stderr
- Проблема вызвана внешними факторами (OOM kill, healthcheck, оркестрация)

`docker events` показывает события, которые не попадают в логи приложения.

### Типы событий

| Категория | События |
| :--- | :--- |
| **Жизненный цикл** | `create`, `start`, `stop`, `die`, `restart`, `kill`, `pause`, `unpause` |
| **Здоровье** | `health_status: starting/healthy/unhealthy` |
| **Память** | `oom-kill` |
| **Образы** | `pull`, `push`, `tag`, `untag`, `delete` |
| **Сеть** | `network create/connect/disconnect` |
| **Тома** | `mount`, `unmount`, `create`, `destroy` |

## Практические сценарии

### Сценарий 1: Диагностика перезапускающегося контейнера

**Симптомы:** Контейнер циклически перезапускается, `docker logs` пуст.

**Решение:**

```bash
# Фильтрация по контейнеру в реальном времени
docker events --filter container=<container_id_or_name>

# Или за последние 30 минут
docker events --filter container=<container_id> --since 30m
```

**Пример вывода (проблема с healthcheck):**

```
2026-03-29T10:20:01Z container create ...
2026-03-29T10:20:02Z container start ...
2026-03-29T10:20:05Z container health_status: unhealthy ...
2026-03-29T10:20:05Z container kill signal=SIGTERM actor.name=healthcheck
2026-03-29T10:20:06Z container die exitCode=137
2026-03-29T10:20:07Z container restart ...
```

**Вывод:** Контейнер убит из-за проваленного healthcheck, сработал `restart policy`.

### Сценарий 2: Обнаружение OOM kill

**Симптомы:** Контейнер завершается с кодом 137, в логах тишина.

**Решение:**

```bash
# Поиск событий oom-kill
docker events --filter type=container --filter event=oom-kill --since 1h
```

**Пример вывода:**

```
2026-03-29T11:45:23Z container oom-kill id=abc123 name=my-app
```

**Действия:**
1. Проверить лимиты: `docker inspect <container> --format '{{.HostConfig.Memory}}'`
2. Увеличить лимит памяти или оптимизировать приложение
3. Проверить `dmesg | grep -i "killed process"`

### Сценарий 3: Аудит безопасности

**Задача:** Отследить все действия с образами и сетями за период инцидента.

```bash
# Все события образов за последние 2 часа
docker events --filter type=image --since 2h --until now

# Сетевые события
docker events --filter type=network --since 2h
```

**Пример вывода:**

```
2026-03-29T09:00:00Z image pull id=sha256:... name=nginx:latest
2026-03-29T09:15:00Z network create id=net123 name=backend
2026-03-29T09:30:00Z image delete id=sha256:... name=old-app:v1
```

### Сценарий 4: Мониторинг healthcheck

**Задача:** Отслеживать состояние здоровья всех контейнеров.

```bash
# Только события health_status
docker events --filter type=container --filter event=health_status
```

**Пример вывода:**

```
2026-03-29T12:00:00Z container health_status: healthy id=abc123 name=web
2026-03-29T12:05:00Z container health_status: unhealthy id=def456 name=db
```

### Сценарий 5: JSON-вывод для автоматизации

**Задача:** Парсинг событий скриптами или SIEM-системой.

```bash
# JSON формат для каждой строки
docker events --format '{{json .}}' --since 1h

# Пример обработки через jq
docker events --format '{{json .}}' | jq 'select(.Type=="container")'
```

**Структура JSON:**

```json
{
  "status": "die",
  "id": "abc123...",
  "from": "nginx:latest",
  "Type": "container",
  "Action": "die",
  "Actor": {
    "ID": "abc123...",
    "Attributes": {
      "name": "web-server",
      "image": "nginx:latest"
    }
  },
  "time": 1711710000,
  "timeNano": 1711710000123456789
}
```

## Дополнительная информация

### Флаги команды

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `--filter <key>=<value>` | Фильтрация по типу, событию, контейнеру | `--filter container=web` |
| `--since <timestamp>` | События после указанного времени | `--since 30m`, `--since 2026-03-29T10:00:00` |
| `--until <timestamp>` | События до указанного времени | `--until 1h` |
| `--format <string>` | Форматирование вывода | `--format '{{json .}}'` |

### Типы фильтров

```bash
# По типу объекта
--filter type=container
--filter type=image
--filter type=network
--filter type=volume

# По событию
--filter event=start
--filter event=die
--filter event=oom-kill
--filter event=health_status

# По объекту
--filter container=<name_or_id>
--filter image=<image_name>
```

### Связанные темы

- **[HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)** — настройка проверок здоровья
- **[Docker Debug](./docker_debug.md)** — интерактивная отладка контейнеров
- **[Exit Codes](./docker_exit_codes.md)** — коды завершения контейнеров

### Примечания

- События хранятся в памяти демона Docker (по умолчанию ~1000 событий)
- Для долгосрочного хранения настройте логирование через драйверы (`json-file`, `syslog`, `fluentd`)
- Команда работает в реальном времени — прерывается через `Ctrl+C`
