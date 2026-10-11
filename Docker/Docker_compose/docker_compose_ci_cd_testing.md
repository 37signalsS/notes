# Тестирование в CI/CD с Docker Compose

**Актуально для:** Docker Compose v5.5.x

## Определения

- **CI/CD (Continuous Integration / Continuous Delivery)** — практика автоматизации сборки, тестирования и доставки приложений. В контексте Docker Compose роль инструмента — управление эфемерными окружениями для интеграционных и системных тестов.
- **Эфемерное окружение (Ephemeral Environment)** — временный стенд, создаваемый для одного прогона тестов и автоматически уничтожаемый после завершения. В отличие от долгоживущих стейджингов, исключает «грязные данные» от предыдущих запусков.
- **Deterministic Process (Детерминированный процесс)** — свойство CI/CD-пайплайна, при котором каждый запуск даёт идентичный результат при одинаковых входных данных: одинаковые образы, одинаковые данные, одинаковые команды.
- **Exit Code Propagation (Передача кода возврата)** — механизм, при котором результат тестового сервиса становится результатом всего `docker compose up`, что позволяет системе оркестрации (GitHub Actions, GitLab CI, Jenkins) корректно определить успех или провал.
- **Graceful Shutdown** — корректная остановка контейнеров с завершением активных соединений и записей на диск. В CI важен для сохранения артефактов и логов перед удалением тома.
- **Artifact (Артефакт)** — файл, produced в рамках пайплайна (логи, отчёты, дампы), который сохраняется после завершения jobs для отладки или compliance.
- **Smoke Test (Дымовой тест)** — минимальный набор проверок, подтверждающий, что развёрнутое приложение стартовало и основные функции доступны.
- **Race Condition (Гонка состояний)** — ошибка, возникающая при запуске тестов до готовности зависимостей (например, до перехода БД в `healthy`).

## Архитектура и принципы работы

### Жизненный цикл CI/CD-задания с Docker Compose

```
[CI Runner] → [Checkout] → [Build] → [docker compose up --wait] → [Tests] → [docker compose down -v]
                  ↓              ↓              ↓                    ↓
             [Source Code]  [Image Build]  [Healthcheck]      [Exit Code]
                                                        ↓
                                                  [Artifacts / Logs]
```

### Ключевые принципы

- **Детерминизм:** Используйте фиксированные версии образов и reproducible builds. Отказ от `latest` в CI — обязательное правило.
- **Изоляция:** Каждый запуск получает уникальный `project-name`. Это предотвращает конфликты портов, имён контейнеров и сетей между параллельными jobs.
- **Автоматическая очистка:** Ресурсы должны удаляться независимо от исхода теста. Используйте `docker compose down -v --remove-orphans` в `finally`-блоке или `when: always`.
- **Observability:** Логи и метрики собираются на каждом шаге. При провале — артефакты сохраняются до удаления контейнеров.
- **Fail-fast:** `--abort-on-container-exit` останавливает стек при первом же критическом сбое, экономя время раннера.

### Компоненты архитектуры

| Компонент | Назначение | Пример |
| :--- | :--- | :--- |
| **CI Runner** | Хост для выполнения пайплайна | GitHub Actions runner, GitLab Runner, Jenkins agent |
| **Docker Engine** | Среда выполнения контейнеров | `dockerd` на раннере или Docker-in-Docker (dind) |
| **Compose Project** | Изолированный стек с уникальным именем | `ci-${CI_PIPELINE_ID}` |
| **Test Runner** | Сервис, выполняющий тесты | `pytest`, `npm test`, `go test` |
| **Dependencies** | Сервисы-зависимости (БД, кэш, брокеры) | `postgres:17-alpine`, `redis:7-alpine` |
| **Registry** | Хранение образов | Harbor, Docker Hub, GitHub Container Registry |
| **Artifacts Store** | Сохранение логов и отчётов | S3, Nexus, GitHub Artifacts |

## Базовые концепции

### Критические флаги для CI/CD

Docker Compose v5.x предоставляет флаги, которые превращают его из инструмента разработки в надёжный компонент пайплайна:

| Флаг | Версия | Назначение |
| :--- | :--- | :--- |
| `--exit-code-from <service>` | v2.0+ | Завершить `up` с кодом возврата указанного сервиса. Без этого флага `up` всегда возвращает `0`, даже если тесты упали. |
| `--abort-on-container-exit` | v2.0+ | Остановить все сервисы проекта, как только любой контейнер прекратит работу. Критичен для CI, где падение одного сервиса не должно блокировать остальные. |
| `--abort-on-container-failure` | v2.27+ | Условие для остановки: только если контейнер завершился с ненулевым кодом. В сочетании с `--exit-code-from` исключает прерывание по успешным side-service. |
| `--wait` / `--wait-timeout` | v2.2.0+ / v2.17.0+ | Блокировать `up` до перехода всех сервисов в `running\|healthy`. Исключает race conditions при запуске тестов. Таймаут по умолчанию — `0` (ожидание без таймаута). |
| `docker compose wait` | Отдельная команда, блокирующая до остановки контейнеров сервиса (одноразовые сервисы, миграции). Не является health-gate — для готовности используйте `up --wait`. |
| `-p` / `--project-name` | v2.0+ | Уникальный идентификатор проекта для изоляции параллельных запусков. Эквивалент переменной `COMPOSE_PROJECT_NAME`. |

### Изоляция и параллелизм

На общих CI-раннерах несколько пайплайнов могут выполняться одновременно. Без изоляции возникают конфликты:

- **Имена контейнеров:** Docker Compose генерирует имена вида `<project>_<service>_1`. Одинаковые имена проектов приводят к конфликтам. Решение — динамические имена через `CI_PIPELINE_ID` или `GITHUB_RUN_ID`.
- **Порты:** Если два пайплайна маппят одинаковые порты на хост, второй завершится ошибкой. В CI тесты общаются с сервисами внутри Docker-сети по именам, поэтому маппинг портов на хост часто не требуется.
- **Сети и тома:** Compose создаёт сеть с именем `<project>_default`. Уникальный `project-name` изолирует и сеть, и тома.

### Оптимизация сборки

В CI время выполнения напрямую влияет на стоимость и пропускную способность:

- **BuildKit:** Включите `DOCKER_BUILDKIT=1` для параллельной сборки слоёв.
- **Внешний кэш:** `--cache-from` позволяет использовать слои из ранее собранных образов в реестре.
- **Docker Bake:** Инструмент для декларативной параллельной сборки нескольких образов через `docker compose bake`.
- **Артефакты сборки:** Используйте `--build` только когда изменился `Dockerfile` или контекст. Для ускорения используйте `docker compose build --pull`.

### Паттерны очистки ресурсов

Неочищенные ресурсы приводят к утечкам и ложным ошибкам:

- **Тома:** `docker compose down -v` удаляет анонимные тома. Именованные тома (`db_data`) сохраняются — это опционально, но в CI обычно удаляются.
- **Орфаны:** `--remove-orphans` удаляет контейнеры от предыдущих запусков, оставшиеся в сети проекта.
- **Сети:** Compose автоматически удаляет сеть проекта при `down`. Если сеть external — удаляется вручную.
- **Изображения:** `--rmi local` удаляет собранные локальные образы. В CI это редко нужно, так как runner часто эфемерен.

## Практические сценарии

### Сценарий 1: Интеграционные тесты с ожиданием готовности

Запуск тестов, требующих реальных зависимостей (PostgreSQL, Redis), с гарантией готовности через healthcheck.

**compose.yml:**
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
    environment:
      - DATABASE_URL=postgres://user:${DB_PASSWORD}@database:5432/app

secrets:
  db_password:
    file: ./test_db_password.txt
```

**Запуск в пайплайне:**
```bash
PROJECT_ID="ci-${CI_PIPELINE_ID}"

docker compose -p "${PROJECT_ID}" up \
  --build \
  --wait \
  --wait-timeout 120 \
  --abort-on-container-exit \
  --exit-code-from app

# Очистка
docker compose -p "${PROJECT_ID}" down -v --remove-orphans
```

**Ожидаемый результат:** `up` возвращает `0`, если тесты прошли; ненулевой код, если `app` завершился с ошибкой. Все ресурсы удалены.

### Сценарий 2: Параллельное тестирование на одном раннере

Если нужно запустить тесты для разных веток одновременно:

```bash
export COMPOSE_PROJECT_NAME="test_${CI_COMMIT_REF_SLUG}_${CI_JOB_ID}"

docker compose up -d database
docker compose run --rm test-runner npm test
docker compose down -v --remove-orphans
```

**Ожидаемый результат:** Изоляция по имени проекта исключает конфликты. `down -v --remove-orphans` гарантирует очистку.

### Сценарий 3: GitHub Actions

Пример шага в `.github/workflows/ci.yml`:

```yaml
jobs:
  integration-tests:
    runs-on: ubuntu-latest
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
      - name: Collect logs on failure
        if: failure()
        run: docker compose logs > containers.log
      - name: Upload logs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: containers-log
          path: containers.log
```

**Ожидаемый результат:** При провале тестов логи сохраняются как артефакт. Runner останавливается с ненулевым кодом.

### Сценарий 4: GitLab CI

Аналогичный сценарий для GitLab CI:

```yaml
integration_tests:
  stage: test
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker compose up --build --wait --abort-on-container-exit --exit-code-from app
    - docker compose logs > containers.log
  after_script:
    - docker compose down -v --remove-orphans
  artifacts:
    paths:
      - containers.log
    when: on_failure
```

### Сценарий 5: Валидация перед переключением трафика (Smoke-test)

Скрипт для проверки готовности Target-сервера в миграционных сценариях:

```bash
#!/bin/bash
set -e

TARGET_IP="<TARGET_PUBLIC_IP>"
HEALTH_ENDPOINT="https://${TARGET_IP}/health"

echo "Waiting for services to become healthy..."
docker compose --wait --wait-timeout 120 ps

echo "Running smoke tests..."
for i in {1..10}; do
  if curl -sf "${HEALTH_ENDPOINT}" > /dev/null; then
    echo "Smoke test passed"
    exit 0
  fi
  sleep 5
done

echo "Smoke test failed"
exit 1
```

**Ожидаемый результат:** Скрипт завершается с `0` только при успешном smoke-тесте. Используется как gate в пайплайне.

## Операции и команды

### Основные команды для CI/CD

| Команда | Описание | Использование в CI |
| :--- | :--- | :--- |
| `docker compose -p <name> up --build --wait --abort-on-container-exit --exit-code-from <service>` | Полный цикл: сборка, запуск, ожидание healthcheck, возврат кода теста | Основная команда CI-джобы |
| `docker compose -p <name> down -v --remove-orphans` | Остановка, удаление томов и орфанов | Очистка в `finally` / `after_script` |
| `docker compose -p <name> logs` | Сбор логов всех сервисов | Сохранение артефактов при провале |
| `docker compose -p <name> ps` | Статус сервисов | Диагностика перед переключением |
| `docker compose config` | Валидация конфигурации | Pre-flight проверка перед запуском |
| `docker compose -p <name> run --rm <service> <cmd>` | Запуск одноразовой задачи в сервисе | Выполнение тестов без длинного `up` |
| `docker compose -p <name> wait` | Ожидание готовности сервисов | Multi-stage пайплайны |
| `docker compose -p <name> build --no-cache` | Принудительная пересборка без кэша | Отладка проблем с кэшем |

### Переменные окружения для CI

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `COMPOSE_PROJECT_NAME` | Имя проекта (эквивалент `-p`) | `ci-${CI_PIPELINE_ID}` |
| `COMPOSE_FILE` | Путь к compose-файлам (эквивалент `-f`) | `docker-compose.yml:docker-compose.ci.yml` |
| `COMPOSE_ENV_FILES` | Файлы переменных окружения | `.env.ci` |
| `COMPOSE_BAKE` | Включить Docker Bake | `true` |
| `DOCKER_BUILDKIT` | Включить BuildKit | `1` |

### Шаблон CI-джобы

```bash
#!/bin/bash
set -euo pipefail

PROJECT_NAME="ci-${CI_PIPELINE_ID:-local}"
COMPOSE_CMD="docker compose -p ${PROJECT_NAME}"

# Pre-flight: валидация конфигурации
${COMPOSE_CMD} config > /dev/null

# Запуск зависимостей
${COMPOSE_CMD} up -d --wait --wait-timeout 120

# Выполнение тестов
${COMPOSE_CMD} run --rm test-runner npm test

# Сбор логов при провале
if [ $? -ne 0 ]; then
  ${COMPOSE_CMD} logs > containers.log
fi

# Очистка (всегда)
${COMPOSE_CMD} down -v --remove-orphans
```

## Устранение неполадок

### Типичные ошибки CI/CD

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`container name is already in use`** | Дублирование имён проектов | Убедитесь, что `COMPOSE_PROJECT_NAME` уникален для каждого запуска |
| **`--abort-on-container-exit` не работает** | Используется с `-d` (detached) | Флаг несовместим с detached mode. Уберите `-d` |
| **`--wait` зависает / timeout** | Сервис не переходит в `healthy` | Увеличьте `--wait-timeout` или проверьте `healthcheck` |
| **`port is already allocated`** | Порт занят другим процессом/контейнером | Освободите порт (`lsof -i :PORT`), удалите старый контейнер или используйте внутреннюю сеть Docker |
| **`deadline exceeded`** при сборке | Слишком большой контекст сборки | Уменьшите `.dockerignore`, используйте multi-stage builds |
| **`permission denied`** при `cp` | Нет прав на чтение/запись файла | Проверьте права на хосте и внутри контейнера, используйте `--user` |
| **`No such service`** | Неверное имя сервиса в Compose | Проверьте имя сервиса в `compose.yml` с учётом регистра |
| **`orphan containers found`** | Контейнеры от предыдущего запуска | Используйте `--remove-orphans` или удалите вручную |
| **`unknown flag: --wait`** | Устаревшая версия Compose | Обновите Docker Compose до v5.x |
| **`permission denied`** при `docker compose up` | Пользователь раннера не в группе `docker` | Добавьте пользователя в группу `docker` или используйте Docker-in-Docker |
| **Потеря артефактов** | `down` выполняется до сохранения логов | Сохраняйте логи перед `down`, используйте `when: always` в CI |
| **Flaky-тесты в CI** | Отсутствие изоляции данных/состояния | Используйте уникальную схему/базу на прогон, фиксируйте версии образов |

### Диагностический процесс

При возникновении проблем с CI/CD-пайплайном:

1. **Проверить версию Docker Compose:** `docker compose version` — убедиться, что поддерживаются используемые флаги.
2. **Валидировать конфигурацию:** `docker compose config` — выводит итоговый YAML, помогает найти синтаксические ошибки.
3. **Проверить статус сервисов:** `docker compose ps` — найти сервисы не в состоянии `healthy` или exited с ненулевым кодом.
4. **Изучить логи:** `docker compose logs <service> --tail 100` — искать `ERROR`, `failed`, `connection refused`.
5. **Проверить изоляцию:** Убедиться, что `COMPOSE_PROJECT_NAME` уникален и нет конфликтов с другими раннерами.
6. **Проверить ресурсы раннера:** `docker system df` — убедиться, что есть место для образов и томов.

## Рекомендации

### Безопасность

- **Никогда не хардкодите секреты:** Используйте `secrets:` с файлами или переменными окружения CI. Для временных файлов паролей — удаляйте после использования.
- **Ограничьте ресурсы раннера:** Задавайте `deploy.resources.limits` в `compose.yml`. Один «прожорливый» тест может привести к зависанию всего раннера.
- **Внутренний registry:** Используйте прокси-реестр (Harbor, Nexus) для кэширования базовых образов. Это ускоряет сборку и защищает от отключения Docker Hub.
- **Проверяйте образы:** Сканируйте тестовые образы на уязвимости (Trivy, Grype) перед запуском.

### Надёжность

- **Фиксируйте версии образов:** Используйте дайджесты или SHA-хэши вместо тегов `latest`. Пример: `postgres:17.4` вместо `postgres:latest`.
- **Используйте `--wait`:** Гарантирует готовность сервисов перед запуском тестов. Для CI/CD используйте `--exit-code-from` и `--abort-on-container-failure`.
- **Всегда имейте план отката:** Убедитесь, что `docker compose down` восстанавливает работоспособность раннера.
- **Тестируйте на изоляции:** Перед каждым крупным изменением пайплайна проверьте параллельный запуск двух джоб.
- **Используйте `COMPOSE_PROJECT_NAME`:** Для изоляции параллельных запусков на общем хосте (например, в CI/CD).

### Производительность

- **Используйте BuildKit:** `DOCKER_BUILDKIT=1` ускоряет сборку за счёт параллельной обработки слоёв.
- **Кэшируйте зависимости:** `actions/cache` для pip/npm, внешний кэш для Docker-образов.
- **Ограничьте параллелизм:** Слишком большое количество параллельных jobs на одном раннере приводит к contention по CPU/IO.
- **tmpfs для временных данных:** Снижает I/O на диск для сервисов с интенсивной записью.
- **Используйте `--build` с кэшированием:** При пересборке образов используйте BuildKit для ускорения.

### Поддержка и эксплуатация

- **Версионируйте `compose.yml`:** Храните в Git с четкими коммитами для каждого изменения пайплайна.
- **Документируйте процедуру:** Создайте runbook с командами и критериями перехода между фазами тестирования.
- **Мониторинг inotify:** Для SRE: настройте алерты на `node_filefd_allocated` при использовании `watch`.
- **Регулярно тестируйте откат:** Убедитесь, что `docker compose down` и повторный `up` восстанавливают работоспособность.
- **Архивируйте артефакты:** Храните логи и отчёты минимум 14 дней (или per compliance требованиям).

## Дополнительная информация

### Связанные документы

- **[Справочник команд CLI](./docker_compose_cli_commands.md)** — подробнее о флагах `--wait`, `--exit-code-from`, `--abort-on-container-exit`, `COMPOSE_PROJECT_NAME`.
- **[Docker Compose Watch Mode](./docker_compose_watch_mode.md)** — наблюдение за изменениями файлов в development; в CI используется реже.
- **[Примеры compose.yml](./docker_compose_file_example.md)** — паттерны `healthcheck`, `depends_on`, `deploy.resources.limits`.
- **[Директивы и правила слияния](./docker_compose_directives.md)** — приоритеты при наложении нескольких файлов.
- **[Обзор Testcontainers](../../Testing/testcontainers_overview.md)** — программное управление тестовым окружением.
- **[Виды тестирования: Unit, Integration, E2E](../../Testing/testing_types_unit_integration_e2e.md)** — стратегия тестирования, эфемерные окружения.
- **[Приёмочное тестирование и UAT](../../Testing/acceptance_uat_testing.md)** — acceptance-уровень, pipeline gates.
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — общие стратегии обеспечения качества.
- **[Docker Bake: Оркестрация сборки](../Dockerfile/docker-bake.md)** — декларативное управление процессом Build.

### Внешние ресурсы

- [Docker Compose File Reference](https://docs.docker.com/reference/compose-file/) — официальная документация.
- [docker/compose releases](https://github.com/docker/compose/releases) — история версий.
- [Docker Bake Documentation](https://docs.docker.com/buildx/working-with-bake/) — документация по Bake.
