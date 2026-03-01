# Инструкции Dockerfile: Состояние и Сигналы

## Определения

**`HEALTHCHECK`** — инструкция, встраивающая в образ механизм для проверки работоспособности приложения внутри контейнера.

**`STOPSIGNAL`** — инструкция, определяющая сигнал ОС, отправляемый основному процессу (PID 1) при остановке контейнера.

## Основные концепции

### `HEALTHCHECK`

Docker периодически выполняет указанную команду и на основе её кода завершения определяет состояние контейнера:

- `0`: `healthy` (здоров)
- `1`: `unhealthy` (нездоров)
- `2`: `starting` (контейнер запускается, используется в некоторых реализациях)

**Синтаксис:**

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost/ || exit 1
```

**Параметры:**

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `--interval` | Интервал между проверками | `30s` |
| `--timeout` | Таймаут выполнения проверки | `30s` |
| `--start-period` | Время на запуск приложения | `0s` |
| `--retries` | Количество неудач подряд для статуса `unhealthy` | `3` |

**Проверка состояния:**

```bash
docker inspect --format='{{.State.Health.Status}}' my_container
```

### `STOPSIGNAL`

По умолчанию Docker отправляет сигнал `SIGTERM` (15) для корректного завершения. Если процесс не завершается, через 10 секунд Docker отправляет `SIGKILL` (9).

```dockerfile
STOPSIGNAL SIGTERM
# или
STOPSIGNAL 15
```

## Практические сценарии

### Сценарий 1: HTTP healthcheck для веб-сервера

```dockerfile
FROM nginx:alpine
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1
```

### Сценарий 2: Healthcheck для PostgreSQL

```dockerfile
FROM postgres:16-alpine
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s \
  CMD pg_isready -U postgres || exit 1
```

### Сценарий 3: Healthcheck для Redis

```dockerfile
FROM redis:7-alpine
HEALTHCHECK --interval=5s --timeout=3s \
  CMD redis-cli ping | grep -q PONG
```

### Сценарий 4: Java JVM с кастомным STOPSIGNAL

```dockerfile
FROM openjdk:17-slim
STOPSIGNAL SIGQUIT  # Грамотный shutdown для JVM
CMD ["java", "-jar", "app.jar"]
```

## Дополнительная информация

- В Docker Compose healthcheck настраивается через секцию `healthcheck`
- Healthcheck влияет на `docker ps` вывод и может использоваться в Docker Compose для зависимостей (`depends_on` с condition)
- STOPSIGNAL полезен для приложений, требующих специального сигнала: Java (`SIGQUIT`), Nginx (`SIGQUIT`), PostgreSQL (`SIGTERM`)
- Подробнее о Docker Compose см. **[Docker Compose file example](../../Docker_compose/docker_compose_file_example.md)**
