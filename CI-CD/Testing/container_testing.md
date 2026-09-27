# Тестирование контейнеров и Docker-образов

## Определения

**Тестирование контейнеров** — проверка корректности сборки, функционирования и безопасности Docker-образов и запущенных контейнеров на всех этапах CI/CD. Включает статический анализ Dockerfile, сканирование образа на уязвимости, функциональное тестирование приложения внутри контейнера и проверку на соответствие стандартам.

**Container Scanning** — автоматический анализ Docker-образа на известные уязвимости (CVE) в зависимостях, OS-пакетах и application dependencies. Подробнее: **[Сканирование Docker-образов на уязвимости](../../Docker/Docker_security/vulnerability_scanning.md)**.

**Image Linting** — статический анализ Dockerfile на соответствие best practices (многоэтапная сборка, минимальные образы, отсутствие секретов). Подробнее: **[Инструменты оптимизации Dockerfile](../../Docker/Dockerfile/dockerfile_optimization_tools.md)**.

**SBOM (Software Bill of Materials)** — формализованный перечень всех компонентов и зависимостей образа. Подробнее: **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.

**Testcontainers** — библиотека для запуска эфемерных зависимостей (базы данных, брокеры сообщений) в Docker-контейнерах во время тестов. Подробнее: **[Testcontainers Overview](../../Testing/testcontainers_overview.md)**.

**Quality Gate** — критерий прохождения этапа pipeline (например, отсутствие CRITICAL уязвимостей, прохождение всех smoke-тестов).

## Основные концепции и архитектура

### Уровни тестирования контейнеров

| Уровень | Что проверяется | Инструменты | Характеристики |
| :--- | :--- | :--- | :--- |
| **Dockerfile Lint** | Best practices, безопасность, оптимизация | Hadolint, Dockle, BuildKit Checks | Быстрый, статический, без сборки образа |
| **Image Scan (CVE)** | Уязвимости в ОС-пакетах и зависимостях | Trivy, Grype, Docker Scout | Средняя скорость, требует собранного образа |
| **SBOM Generation** | Полный состав образа | Syft, Trivy SBOM, Docker SBOM | Быстрый, используется для аудита и подписания |
| **Functional Test** | Приложение работает корректно внутри контейнера | Testcontainers, docker-compose + pytest | Медленный, проверяет runtime-поведение |
| **Compliance** | CIS Benchmark, отраслевые стандарты | Trivy misconfiguration, Dockle | Проверка конфигурации и permissions |
| **Runtime Security** | Поведение контейнера в production | Falco, Sysdig, Aqua | Мониторинг работающего контейнера |

### Жизненный цикл тестирования контейнера в CI/CD

1. **Trigger:** push, merge request, schedule, manual
2. **Lint:** статический анализ Dockerfile (Hadolint, BuildKit Checks)
3. **Build:** сборка образа с фиксацией тега (commit SHA, SemVer)
4. **Scan:** сканирование образа на CVE (Trivy, Grype) и misconfigurations
5. **SBOM:** генерация перечня компонентов (Syft, Trivy SBOM)
6. **Functional Test:** запуск контейнера и выполнение smoke-тестов (pytest, curl, Testcontainers)
7. **Quality Gate:** проверка pass rate, порог уязвимостей, compliance
8. **Sign & Push:** подписание артефакта (Cosign/GPG) и публикация в registry
9. **Cleanup:** остановка контейнеров, удаление временных артефактов

### Интеграция с DevSecOps

Контейнерное тестирование является частью Shift-Left Security. Подробнее о методологии: **[DevSecOps Overview](../../CI-CD/DevSecOps/devsecops_overview.md)**.

## Практические сценарии

### Функциональное тестирование контейнера (Python + Docker SDK)

```python
import docker
import requests
import time
import pytest

@pytest.fixture(scope="module")
def container():
    """Запуск контейнера для функционального тестирования."""
    client = docker.from_env()
    
    container = client.containers.run(
        "myapp:latest",
        ports={"8080/tcp": 8080},
        detach=True,
        environment={"DATABASE_URL": "sqlite:///test.db"}
    )
    
    time.sleep(5)  # Ожидание запуска приложения
    
    yield container
    
    container.stop()
    container.remove()

def test_health(container):
    """Проверка health endpoint."""
    resp = requests.get("http://localhost:8080/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_app_version(container):
    """Проверка версии приложения."""
    resp = requests.get("http://localhost:8080/version")
    assert resp.status_code == 200
    assert "version" in resp.json()

def test_container_user(container):
    """Проверка, что контейнер не запущен от root."""
    result = container.exec_run("whoami")
    assert result.exit_code == 0
    assert result.output.decode().strip() != "root"
```

### docker-compose: тестирование multi-service стека

```yaml
# docker-compose.test.yml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      DATABASE_URL: postgresql://test:test@db/testdb
      REDIS_URL: redis://redis:6379
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
  
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: testdb
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test"]
      interval: 5s
      timeout: 5s
      retries: 5
  
  redis:
    image: redis:7-alpine
```

Запуск тестов:

```bash
# Поднять стек и запустить тесты
docker compose -f docker-compose.test.yml up -d --build
docker compose -f docker-compose.test.yml exec app pytest tests/
EXIT_CODE=$?
docker compose -f docker-compose.test.yml down
exit $EXIT_CODE
```

### Testcontainers: тестирование приложения с зависимостями

```java
@Testcontainers
class ApplicationIntegrationTest {
    
    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16")
        .withDatabaseName("testdb")
        .withUsername("test")
        .withPassword("test");
    
    @Container
    static GenericContainer<?> app = new GenericContainer<>("myapp:latest")
        .withExposedPorts(8080)
        .withEnv("DATABASE_URL", () -> 
            "postgresql://test:test@" + postgres.getHost() + ":" + postgres.getFirstMappedPort() + "/testdb")
        .waitingFor(Wait.forHttp("/health", 8080));
    
    @Test
    void shouldReturnHealthCheck() {
        given()
            .port(app.getFirstMappedPort())
        .when()
            .get("/health")
        .then()
            .statusCode(200)
            .body("status", equalTo("ok"));
    }
}
```

Подробнее о конфигурации, стратегиях ожидания и безопасности Testcontainers: **[Testcontainers Overview](../../Testing/testcontainers_overview.md)**.

### Trivy в CI/CD Pipeline

```yaml
# GitLab CI
container_scan:
  stage: test
  image:
    name: aquasec/trivy:0.74.0
    entrypoint: [""]
  script:
    # Сканирование на уязвимости
    - trivy image --exit-code 1 --severity HIGH,CRITICAL ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
    # Сканирование Dockerfile на misconfigurations
    - trivy config --exit-code 1 --misconfig-scanners dockerfile Dockerfile
    # Генерация SBOM
    - trivy image --format spdx-json -o sbom.json ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
  artifacts:
    paths:
      - sbom.json
```

```yaml
# GitHub Actions
- name: Run Trivy vulnerability scanner
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: '${{ github.repository }}:${{ github.sha }}'
    format: 'sarif'
    output: 'trivy-results.sarif'
    severity: 'CRITICAL,HIGH'
    exit-code: '1'
```

## Операции и команды

### CLI-инструменты для тестирования контейнеров

| Инструмент | Назначение | Основные команды |
| :--- | :--- | :--- |
| **hadolint** | Линтинг Dockerfile | `hadolint Dockerfile --ignore DL3008` |
| **trivy** | Сканирование CVE, secrets, misconfigurations | `trivy image --severity HIGH,CRITICAL myapp:latest` |
| **grype** | Сканирование уязвимостей | `grype myapp:latest --fail-on critical` |
| **dockle** | CIS Docker Benchmark проверка | `dockle --exit-code 1 myapp:latest` |
| **syft** | Генерация SBOM | `syft myapp:latest -o spdx-json > sbom.json` |
| **dive** | Анализ слоев образа | `dive myapp:latest` |
| **docker scout** | Рекомендации по base image | `docker scout recommendations myapp:latest` |
| **Testcontainers** | Эфемерные контейнеры для тестов | Программный API (Java, Python, Go) |
| **docker compose** | Управление multi-service тестовыми стеками | `docker compose -f docker-compose.test.yml up -d` |

### Основные параметры Trivy

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--severity` | Фильтр по критичности | `--severity HIGH,CRITICAL` |
| `--exit-code` | Exit code при обнаружении уязвимостей | `--exit-code 1` |
| `--ignore-unfixed` | Только уязвимости с доступным исправлением | `--ignore-unfixed` |
| `--format` | Формат вывода | `--format json` |
| `--misconfig-scanners` | Сканеры misconfigurations | `--misconfig-scanners dockerfile` |
| `-o, --output` | Файл отчета | `-o results/trivy.json` |
| `--show-epss` | Показ EPSS-метрик | `--show-epss` |

### Основные параметры Hadolint

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--ignore` | Игнорировать правила | `--ignore DL3008 --ignore DL3013` |
| `--format` | Формат вывода | `--format json` |
| `-t, --threshold` | Порог для warning/error | `-t warning` |

## GitLab CI: полный pipeline тестирования контейнера

```yaml
stages:
  - lint
  - build
  - scan
  - test
  - push

variables:
  IMAGE: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}

dockerfile_lint:
  stage: lint
  image: hadolint/hadolint:latest-debian
  script:
    - hadolint Dockerfile --format json > hadolint.json
    - |
      ERRORS=$(cat hadolint.json | jq '[.[] | select(.level=="error")] | length')
      if [ "$ERRORS" -gt 0 ]; then
        echo "Dockerfile lint errors found"
        cat hadolint.json | jq '.[] | select(.level=="error")'
        exit 1
      fi
  artifacts:
    paths:
      - hadolint.json

build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker build -t $IMAGE .
    - docker save $IMAGE > image.tar
  artifacts:
    paths:
      - image.tar

container_scan:
  stage: scan
  image: aquasec/trivy:0.74.0
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL --input image.tar
    - trivy image --format spdx-json -o sbom.json --input image.tar
  artifacts:
    paths:
      - sbom.json

functional_test:
  stage: test
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker load < image.tar
    - docker compose -f docker-compose.test.yml up -d --build
    - sleep 10
    - docker compose -f docker-compose.test.yml exec -T app pytest tests/ --junitxml=results.xml
    - docker compose -f docker-compose.test.yml down
  artifacts:
    reports:
      junit: results.xml
```

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Hadolint: `DL3007` — using latest tag | Dockerfile использует `FROM image:latest` | Зафиксировать версию: `FROM image:1.2.3` |
| Hadolint: `DL3002` — running as root | Контейнер запущен от root | Добавить `USER nonroot` в Dockerfile |
| Trivy: `CRITICAL` vulnerabilities | Устаревшие зависимости в образе | Обновить base image и dependencies, пересобрать |
| Контейнер падает при запуске в CI | Нет health check / insufficient memory | Добавить `healthcheck` в Dockerfile, увеличить `--memory` |
| `permission denied` при запуске от non-root | Файлы принадлежат root | Добавить `USER` и `COPY --chown` в Dockerfile |
| Dockle: `CIS-DI-0002` — secrets in image | API-ключи захардкожены в образе | Использовать Docker secrets, multi-stage build, `.dockerignore` |
| SBOM не генерируется | Неподдерживаемый формат образа | Убедиться, что образ — OCI/Docker manifest v2 |
| Testcontainers: `Cannot connect to Docker` | Docker socket не проброшен в CI | Добавить сервис `docker:dind` или пробросить `/var/run/docker.sock` |
| Ryuk: container cleanup failed | Привилегированный режим запрещен | Отключить Ryuk: `TESTCONTAINERS_RYUK_DISABLED=true` |
| `no space left on device` в CI | Накопление образов и контейнеров | Настроить prune политику: `docker system prune -f` |

### Диагностика в air-gapped средах

При отсутствии доступа к внешним репозиториям:

```bash
# Проверка наличия образов локально
docker images | grep myapp

# Проверка статуса контейнера
docker ps -a --filter "name=myapp"

# Просмотр логов контейнера
docker logs --tail 100 myapp-container

# Проверка занятого места
docker system df

# Проверка health check
docker inspect --format='{{.State.Health.Status}}' myapp-container

# Ручной запуск healthcheck
docker exec myapp-container curl -f http://localhost:8080/health
```

## Best Practices

### Проектирование Dockerfile

- **Минимальные образы:** используйте `distroless` или `alpine`. Чем меньше пакетов в ОС, тем меньше поверхность атаки и количество CVE.
- **Фиксированные версии:** никогда не используйте `:latest` в CI/CD; фиксируйте версии base image и пакетов.
- **Multi-stage сборки:** удаляйте компиляторы, менеджеры пакетов и SSH-ключи из финального образа.
- **Non-root пользователи:** запускайте контейнер от непривилегированного пользователя.
- **Health check:** добавляйте `HEALTHCHECK` в Dockerfile для отслеживания состояния контейнера.
- **`.dockerignore`:** исключайте файлы с секретами, `.git`, `node_modules` из контекста сборки.

### Pipeline

- **Quality Gates:** fail-fast на lint-уровне, progressive testing (сначала быстрые проверки, потом медленное сканирование).
- **Параллелизм:** запуск lint и scan параллельно при отсутствии зависимости.
- **Кэширование:** кэширование слоев Docker (`--cache-from`) между стадиями для ускорения сборки.
- **Artifacts:** сохранение SBOM, отчетов Trivy/Hadolint на каждой стадии для аудита.
- **Image Tag Pinning:** использование commit SHA или SemVer вместо `latest`.

### Security

- **Секреты:** never hardcode secrets in Dockerfile; используйте build-time secrets (`docker build --secret`) или runtime secrets.
- **Сканирование на всех этапах:** lint → build → scan → runtime.
- **SBOM:** генерация и подпись SBOM для каждого артефакта.
- **Supply Chain:** верификация подписи образа перед запуском в production (Cosign + Kyverno admission control).

### Air-gapped среды

- **Offline registry:** размещение registry внутри периметра с зеркалированием нужных образов.
- **Local cache:** кэширование сканеров (Trivy, Grype) и баз данных CVE.
- **Pre-staging:** предварительная загрузка образов зависимостей на CI-раннеры.

## Дополнительная информация

### См. также

* **[Сканирование Docker-образов на уязвимости](../../Docker/Docker_security/vulnerability_scanning.md)** — Trivy, Grype, Copacetic, VEX.
* **[Инструменты оптимизации Dockerfile](../../Docker/Dockerfile/dockerfile_optimization_tools.md)** — Hadolint, Dive, Docker Scout.
* **[Testcontainers Overview](../../Testing/testcontainers_overview.md)** — изолированные контейнеры для интеграционных тестов.

### Внешние ресурсы

* [Hadolint](https://github.com/hadolint/hadolint) — Dockerfile linter.
* [Trivy](https://trivy.dev/) — scanner для контейнеров, IaC, SBOM.
* [Grype](https://github.com/anchore/grype) — scanner уязвимостей образов.
* [Dockle](https://github.com/goodwithtech/dockle) — CIS Docker Benchmark checker.
* [Testcontainers](https://testcontainers.com/) — библиотека для интеграционных тестов с контейнерами.
