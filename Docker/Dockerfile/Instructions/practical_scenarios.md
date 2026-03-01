# Инструкции Dockerfile: Практические Сценарии

## Определения

**Приоритет команд при запуске контейнера** — порядок, в котором `docker run` и `docker-compose.yml` переопределяют инструкции из `Dockerfile`.

## Основные концепции

### Приоритет переопределения

| Источник | ENTRYPOINT | CMD |
| :--- | :--- | :--- |
| Dockerfile | `ENTRYPOINT ["/app/run"]` | `CMD ["--default"]` |
| docker-compose.yml / docker run | `entrypoint: /app/debug` | `command: --prod` |
| **Результат** | Переопределяется | Переопределяется |

**Золотое правило:** `docker-compose.yml` (или `docker run`) всегда имеет приоритет над `Dockerfile`.

1. `command:` в `compose.yml` (или аргументы в `docker run`) **заменяет** `CMD` из `Dockerfile`
2. `entrypoint:` в `compose.yml` (или `--entrypoint` в `docker run`) **заменяет** `ENTRYPOINT` из `Dockerfile`

## Практические сценарии

### Сценарий 1: Базовая работа ENTRYPOINT и CMD

| В Dockerfile | В docker-compose / docker run | Итоговая команда |
| :--- | :--- | :--- |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | (ничего) | `/app/run --default` |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | `command: --prod` | `/app/run --prod` |
| `ENTRYPOINT ["/app/run"]` | `entrypoint: /app/debug` | `/app/debug` |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | `entrypoint: /app/debug`<br>`command: --verbose` | `/app/debug --verbose` |

### Сценарий 2: Переопределение CMD для ping

**Dockerfile:**

```dockerfile
FROM alpine:3.20.0
ENTRYPOINT ["ping", "-c", "3"]
CMD ["localhost"]
```

По умолчанию: `ping -c 3 localhost`

**docker-compose.yml:**

```yaml
services:
  pinger:
    build: .
    command: google.com
```

**Результат:** `ping -c 3 google.com`

### Сценарий 3: Отладка с переопределением ENTRYPOINT

```yaml
services:
  app:
    build: .
    entrypoint: /bin/sh
    command: -c "echo debug && tail -f /dev/null"
```

## Дополнительная информация

- Подробнее о формах записи (shell vs exec) см. **[Выполнение при запуске](./runtime_execution.md)**
- Подробнее о docker-compose см. **[Docker Compose](../Docker_compose/docker_compose_file_example.md)**
