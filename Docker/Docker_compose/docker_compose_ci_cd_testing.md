# Тестирование в CI/CD с Docker Compose

## Определения

В конвейерах CI/CD основная роль Docker Compose заключается в автоматизированном управлении эфемерными (временными) окружениями для запуска интеграционных и системных тестов. 

**Ключевое отличие от разработки:** в CI/CD процесс должен быть полностью детерминированным — от сборки актуальных образов до автоматической очистки ресурсов и передачи кода возврата (exit code) системе оркестрации (GitHub Actions, GitLab CI, Jenkins).

## Базовые концепции

### Командные инструменты для CI/CD

Современный Docker Compose (v5+) предоставляет специализированные механизмы для надежной работы в пайплайнах:

- **`--exit-code-from <service>`**: Критически важный флаг для команды `up`. Он заставляет Docker Compose завершиться с тем же кодом, с которым завершился указанный тестовый сервис.
- **`--abort-on-container-exit`**: Останавливает все сервисы проекта, как только любой из контейнеров прекращает работу.
- **`--wait`**: (Compose v2.20+) Гарантирует, что команда `up` не вернет управление, пока все сервисы не перейдут в состояние `healthy` (согласно их `healthcheck`). Это исключает "race conditions", когда тесты запускаются до готовности базы данных.
- **`docker compose wait`**: (Compose v2.21+) Отдельная команда, позволяющая блокировать выполнение пайплайна до достижения сервисами заданного состояния.

### Переопределение конфигураций

В CI/CD рекомендуется использовать стратегию наложения (overlay) файлов:
1. `compose.yml` — базовая конфигурация инфраструктуры.
2. `compose.test.yml` — специфичные настройки для тестов (другие точки входа, переменные окружения, моки).

## Практические сценарии

### Сценарий 1: Запуск интеграционных тестов с ожиданием готовности

Сценарий: запуск Node.js тестов, требующих готовности PostgreSQL.

**Файл `compose.yml` (базовая структура):**

```yaml
services:
  database:
    image: postgres:17-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 5s
      timeout: 3s
      retries: 10
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password

  app:
    build: .
    depends_on:
      database:
        condition: service_healthy

secrets:
  db_password:
    file: ./test_db_password.txt
```

**Файл `compose.test.yml` (тестовая точка входа):**

```yaml
services:
  app:
    command: ["npm", "run", "test:integration"]
    environment:
      - NODE_ENV=test
      - DB_HOST=database
```

**Команда запуска в CI-пайплайне:**

```bash
# 1. Запуск стека с ожиданием готовности всех healthcheck
docker compose -f compose.yml -f compose.test.yml up \
  --build \
  --wait \
  --abort-on-container-exit \
  --exit-code-from app

# 2. Очистка ресурсов после завершения (включая анонимные тома)
docker compose down -v
```

### Сценарий 2: Использование в GitHub Actions

Пример шага в `.github/workflows/ci.yml`:

```yaml
    steps:
      - uses: actions/checkout@v4
      - name: Run Integration Tests
        run: |
          echo "${{ secrets.DB_PASSWORD }}" > test_db_password.txt
          docker compose up --build --wait --abort-on-container-exit --exit-code-from app
        env:
          DOCKER_CONTENT_TRUST: 1
```

## Дополнительная информация

### Сравнение с Testcontainers

| Характеристика | Docker Compose | Testcontainers |
| :--- | :--- | :--- |
| **Управление** | Внешнее (YAML + CLI) | Программное (Java, Go, Python SDK) |
| **Изоляция** | Один стек на запуск | Изолированные контейнеры на каждый тест |
| **Сложность** | Низкая (декларативно) | Средняя (требует написания кода) |
| **Динамические порты** | Требуют ручной настройки | Автоматизированы "из коробки" |
| **Версионирование** | В отдельных файлах | В коде тестов |

### Рекомендации

- **Очистка данных:** всегда используйте `docker compose down -v` в CI, чтобы гарантировать отсутствие побочных эффектов от предыдущих запусков на том же раннере.
- **Логирование:** если тесты упали, используйте `docker compose logs`, чтобы извлечь состояние упавших сервисов перед их удалением.
- **Локальный реестр:** в крупных CI-системах используйте кэширование слоев (`--cache-from`) для ускорения сборки образов.

### См. также

- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — подробнее о флагах `--wait` и `--exit-code-from`.
- **[Обзор Testcontainers](../../Testing/testcontainers_overview.md)** — программное управление тестовым окружением.
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — общие стратегии обеспечения качества.
