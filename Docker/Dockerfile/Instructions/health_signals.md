# Инструкции Dockerfile: Состояние и Сигналы

## Определения

**`HEALTHCHECK`** — инструкция, встраивающая в образ механизм для проверки работоспособности приложения внутри контейнера.

**`STOPSIGNAL`** — инструкция, определяющая сигнал ОС, отправляемый основному процессу (PID 1) при остановке контейнера.

## Основные концепции

### `HEALTHCHECK` — синтаксис

```dockerfile
HEALTHCHECK [OPTIONS] CMD command
HEALTHCHECK [OPTIONS] CMD-SHELL command
HEALTHCHECK NONE
```

**Формы команды:**

| Форма | Описание |
| :--- | :--- |
| `CMD command` | Выполняет команду для проверки здоровья (exec-форма) |
| `CMD-SHELL command` | Выполняет команду через оболочку (`/bin/sh -c`) |
| `NONE` | Отключает HEALTHCHECK, унаследованный от базового образа |

**Опции:**

| Опция | Описание | По умолчанию |
| :--- | :--- | :--- |
| `--interval` | Время между проверками | `30s` |
| `--timeout` | Максимальное время выполнения команды | `30s` |
| `--start-period` | Период инициализации (не учитывается в неудачах) | `0s` |
| `--retries` | Количество неудачных попыток до статуса `unhealthy` | `3` |

**Коды возврата команды:**

| Код | Статус | Описание |
| :--- | :--- | :--- |
| `0` | `healthy` | Проверка успешна |
| `1` | `unhealthy` | Проверка провалена |
| `2` | — | Зарезервировано |

**Статусы здоровья контейнера:**

| Статус | Описание |
| :--- | :--- |
| `starting` | Начальная фаза (в течение `start-period`) |
| `healthy` | Проверки успешны |
| `unhealthy` | Превышено количество `retries` |

**Проверка статуса:**

```bash
docker inspect --format='{{.State.Health.Status}}' my_container
docker inspect --format='{{json .State.Health}}' my_container
docker ps  # колонка STATUS покажет (healthy) или (unhealthy)
```

> **Важно:** HEALTHCHECK требует BuildKit. Последняя инструкция `HEALTHCHECK` в Dockerfile имеет приоритет.

### `STOPSIGNAL` — синтаксис

```dockerfile
STOPSIGNAL <signal>
```

**Форматы указания сигнала:**

| Формат | Пример |
| :--- | :--- |
| По имени | `STOPSIGNAL SIGTERM` |
| По номеру | `STOPSIGNAL 15` |
| С переменной | `STOPSIGNAL ${STOP_SIG}` |

**Поведение по умолчанию:**

- Если `STOPSIGNAL` не указан, Docker отправляет `SIGTERM` (15)
- Если процесс не завершается за 10 секунд, Docker отправляет `SIGKILL` (9)
- Время ожидания можно изменить через `docker stop --time <seconds>`

**Поддерживаемые сигналы:**

| Сигнал | Номер | Описание |
| :--- | :--- | :--- |
| `SIGTERM` | 15 | Корректное завершение (по умолчанию) |
| `SIGINT` | 2 | Прерывание (аналог Ctrl+C) |
| `SIGQUIT` | 3 | Выход с дампом памяти (Java, Nginx) |
| `SIGKILL` | 9 | Немедленное завершение (не рекомендуется) |
| `SIGUSR1` | 10 | Пользовательский сигнал 1 |
| `SIGUSR2` | 12 | Пользовательский сигнал 2 |

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
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD pg_isready -U postgres || exit 1
```

### Сценарий 3: Healthcheck для Redis

```dockerfile
FROM redis:7-alpine
HEALTHCHECK --interval=5s --timeout=3s \
  CMD redis-cli ping | grep -q PONG || exit 1
```

### Сценарий 4: Healthcheck с CMD-SHELL

```dockerfile
FROM python:3.11-slim
HEALTHCHECK --interval=30s --timeout=10s \
  CMD-SHELL curl -f http://localhost:8000/health || exit 1
```

### Сценарий 5: Отключение HEALTHCHECK базового образа

```dockerfile
FROM nginx:alpine
# Отключаем HEALTHCHECK из базового образа
HEALTHCHECK NONE
```

### Сценарий 6: Java JVM с кастомным STOPSIGNAL

```dockerfile
FROM openjdk:17-slim
STOPSIGNAL SIGQUIT  # Грамотный shutdown для JVM
CMD ["java", "-jar", "app.jar"]
```

### Сценарий 7: Nginx с SIGQUIT

```dockerfile
FROM nginx:alpine
STOPSIGNAL SIGQUIT  # Корректное завершение соединений
```

### Сценарий 8: STOPSIGNAL с переменной окружения

```dockerfile
FROM ubuntu
ENV STOP_SIG=SIGINT
STOPSIGNAL ${STOP_SIG}
CMD ["./app"]
```

## Дополнительная информация

**Лучшие практики HEALTHCHECK:**

1. **Команда должна быть идемпотентной** — многократное выполнение не должно влиять на состояние
2. **Избегайте длительных проверок** — `timeout` должен быть разумным
3. **Используйте `start-period`** для контейнеров с длительным запуском
4. **Избегайте внешних зависимостей** — проверка должна работать внутри контейнера
5. **Не полагайтесь только на HEALTHCHECK** — используйте вместе с restart policies

**Лучшие практики STOPSIGNAL:**

1. **Используйте `SIGTERM`** по умолчанию для корректного завершения
2. **Избегайте `SIGKILL`** — не даёт приложению выполнить очистку
3. **Настройте приложение** для обработки указанного сигнала
4. **Тестируйте завершение** через `docker stop` с вашей конфигурацией
5. **Документируйте выбор** — добавьте комментарий, почему выбран сигнал

В Docker Compose healthcheck настраивается через секцию `healthcheck` и используется для зависимостей с `depends_on.condition: service_healthy` (подробнее **[Docker Compose file example](../../Docker_compose/docker_compose_file_example.md)** и **[Docker Compose directives](../../Docker_compose/docker_compose_directives.md)**).
