# Тестирование в CI/CD с Docker Compose

## Определения

В конвейерах CI/CD основная задача при использовании Docker Compose — управление жизненным циклом тестовых сервисов. В отличие от локальной разработки, в CI/CD необходимо:
1. Запустить основной сервис (тесты) и его зависимости.
2. Дождаться завершения тестов.
3. Получить код возврата (exit code) для определения статуса шага пайплайна.
4. Автоматически остановить все контейнеры после завершения.

## Базовые концепции

Для автоматизации тестирования используются специфические флаги команды `up`:

- **`--exit-code-from <service>`**: Возвращает код завершения указанного сервиса как код завершения всей команды `docker compose`.
- **`--abort-on-container-exit`**: Остановит все контейнеры проекта, как только любой из них прекращает работу.
- **`--build`**: Принудительная сборка образов, гарантирующая тестирование актуального кода из репозитория.

## Практические сценарии

### Пример: Запуск интеграционных тестов

Сценарий: веб-сервис `web` взаимодействует с базой данных `db`.

**Файл `compose.yml` (базовая конфигурация):**

```yaml
services:
  web:
    build: .
    depends_on:
      - db
    environment:
      - DB_HOST=db

  db:
    image: postgres:16
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
```

**Файл `compose.test.yml` (переопределение команды):**

```yaml
services:
  web:
    command: ["npm", "test"]
```

**Команда запуска в CI/CD:**

```bash
docker compose -f compose.yml -f compose.test.yml up \
  --build \
  --abort-on-container-exit \
  --exit-code-from web

# → Building web
# → web-1  | Running tests...
# → web-1  | PASS: All tests passed
# → web-1 exited with code 0
# → Aborting on container exit...
# → Stopping db-1 ... done
```

## Дополнительная информация

### Сравнение с Testcontainers

| Критерий | Docker Compose | Testcontainers |
| :--- | :--- | :--- |
| **Управление** | CLI, декларативно | Программно, из кода тестов |
| **Изоляция** | Общие контейнеры на стек | Отдельные контейнеры на тест |
| **Жизненный цикл** | Внешнее управление (CI) | Автоматическое (JUnit/Pytest) |
| **Когда использовать** | Простые зависимости, локально | Сложные сценарии, динамические порты |

- **[Обзор Testcontainers](../../Testing/testcontainers_overview.md)** — глубокая изоляция в коде
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — общие методологии
- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — описание флагов `up` и `down`
