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

### Изоляция и параллелизм

При запуске тестов на общих CI-раннерах часто возникают конфликты имен контейнеров и портов. Решение — использование динамических имен проектов:

- **Флаг `-p` или `--project-name`**: Позволяет задать уникальный идентификатор для каждого запуска (например, на основе ID пайплайна).
- **Использование `0` в портах**: Настройка маппинга портов как `0:PORT` заставляет Docker выделить свободный случайный порт на хосте, предотвращая конфликты (хотя чаще в CI тесты общаются с сервисами внутри сети Docker по именам).

### Оптимизация сборки (BuildKit)

В CI критически важно время выполнения. Использование BuildKit и внешнего кэша значительно ускоряет сборку:
- **`--cache-from`**: Позволяет использовать слои из ранее собранных и загруженных в реестр образов.
- **`COMPOSE_BAKE`**: Использование инструмента **[Docker Bake](../Dockerfile/docker-bake.md)** через Compose-файлы для параллельной сборки нескольких образов.

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
    deploy:
      resources:
        limits:
          memory: 512M

  app:
    build: .
    depends_on:
      database:
        condition: service_healthy

secrets:
  db_password:
    file: ./test_db_password.txt
```

**Команда запуска в пайплайне:**

```bash
# Использование уникального имени проекта для изоляции
PROJECT_ID="ci-${CI_PIPELINE_ID}"

docker compose -p "${PROJECT_ID}" up \
  --build \
  --wait \
  --abort-on-container-exit \
  --exit-code-from app

# Полная очистка ресурсов после тестов
docker compose -p "${PROJECT_ID}" down -v --remove-orphans
```

### Сценарий 2: Параллельное тестирование на одном раннере

Если нужно запустить тесты для разных веток одновременно:

```bash
# В CI-пайплайне задаем уникальный префикс
export COMPOSE_PROJECT_NAME="test_${CI_COMMIT_REF_SLUG}_${CI_JOB_ID}"

docker compose up -d database
docker compose run --rm test-runner npm test
docker compose down -v
```

### Сценарий 3: Использование в GitHub Actions

Пример шага в `.github/workflows/ci.yml` с использованием современных практик:

```yaml
    steps:
      - uses: actions/checkout@v4
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      - name: Run Tests
        run: |
          echo "${{ secrets.DB_PASSWORD }}" > test_db_password.txt
          docker compose up --build --wait --abort-on-container-exit --exit-code-from app
        env:
          COMPOSE_PROJECT_NAME: "ci-${{ github.run_id }}-${{ github.run_attempt }}"
```

## Дополнительная информация

### Рекомендации по эксплуатации в CI

1.  **Безопасная очистка:** Всегда используйте `docker compose down -v --remove-orphans`. Флаг `-v` удаляет анонимные тома, а `--remove-orphans` очищает контейнеры, оставшиеся от предыдущих или прерванных запусков.
2.  **Сбор артефактов:** Если тесты провалились, выполните `docker compose logs > containers.log` перед выполнением `down`, чтобы сохранить логи для отладки.
3.  **Ограничение ресурсов:** Всегда задавайте `deploy.resources.limits` в `compose.yml`. В CI-средах (особенно общих раннерах) один "прожорливый" тест может привести к зависанию всей системы.
4.  **Реестр образов:** Используйте внутренние прокси-реестры (например, Harbor) для кэширования базовых образов, чтобы избежать лимитов Docker Hub (Rate Limiting).

### Сравнение с Testcontainers

| Характеристика | Docker Compose | Testcontainers |
| :--- | :--- | :--- |
| **Управление** | Внешнее (YAML + CLI) | Программное (Java, Go, Python SDK) |
| **Изоляция** | Один стек на запуск | Изолированные контейнеры на каждый тест |
| **Сложность** | Низкая (декларативно) | Средняя (требует написания кода) |
| **Динамические порты** | Требуют ручной настройки (флаг `-p`) | Автоматизированы "из коробки" |
| **Применимость** | Системные и E2E тесты | Интеграционные тесты в коде |

### См. также

- **[Docker Bake: Оркестрация сборки](../Dockerfile/docker-bake.md)** — декларативное управление процессом Build.
- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — подробнее о флагах `--wait` и `--exit-code-from`.
- **[Обзор Testcontainers](../../Testing/testcontainers_overview.md)** — программное управление тестовым окружением.
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — общие стратегии обеспечения качества.
