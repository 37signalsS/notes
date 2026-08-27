# Тестирование контейнеров и Docker-образов

## Определения

**Тестирование контейнеров** — проверка корректности сборки, функционирования и безопасности Docker-образов и запущенных контейнеров. Включает валидацию Dockerfile, проверку образа на уязвимости, тестирование функциональности приложения внутри контейнера и compliance.

**Container Scanning** — автоматический анализ Docker-образа на известные уязвимости (CVE) в зависимостях, OS-пакетах и application dependencies.

**Image Linting** — статический анализ Dockerfile на соответствие best practices (многоэтапная сборка, минимальные образы, отсутствие секретов).

**Compliance Check** — проверка контейнера на соответствие корпоративным и отраслевым стандартам (CIS Docker Benchmark, NIST, PCI-DSS).

## Основные концепции

### Уровни тестирования контейнеров

| Уровень | Что проверяется | Инструменты |
| :--- | :--- | :--- |
| **Dockerfile Lint** | Best practices, безопасность, оптимизация | Hadolint, Dockle, Dockerfilelint |
| **Image Scan (CVE)** | Уязвимости в ОС-пакетах и зависимостях | Trivy, Grype, Snyk Container |
| **Functional Test** | Приложение работает корректно внутри контейнера | Testcontainers, docker-compose + pytest |
| **SBOM (Software Bill of Materials)** | Полный состав образа | Syft, Trivy SBOM, Docker SBOM |
| **Compliance** | CIS Benchmark, разрешенные образы | Trivy misconfiguration, Dockle |
| **Runtime Security** | Поведение контейнера в production | Falco, Sysdig, Aqua |

### Hadolint: линтинг Dockerfile

```bash
# Установка
brew install hadolint  # macOS
# или
docker run --rm -i hadolint/hadolint < Dockerfile

# Проверка Dockerfile
hadolint Dockerfile

# Проверка с игнорированием определенных правил
hadolint --ignore DL3008 --ignore DL3013 Dockerfile

# Проверка в CI
hadolint Dockerfile --format json > results/hadolint.json
```

### Trivy: сканирование образов на уязвимости

```bash
# Сканирование локального образа
trivy image myapp:latest

# Сканирование с фильтрацией по severity
trivy image --severity HIGH,CRITICAL myapp:latest

# Сканирование с выводом в JSON
trivy image -f json -o results/trivy.json myapp:latest

# Сканирование Dockerfile на misconfigurations
trivy config --misconfig-scanners dockerfile Dockerfile

# SBOM генерация
trivy image --format spdx-json -o results/sbom.json myapp:latest

# Порог для CI (fail при CRITICAL)
trivy image --exit-code 1 --severity CRITICAL myapp:latest
```

### Grype: альтернатива Trivy

```bash
# Сканирование образа
grype myapp:latest

# Сканирование с порогом
grype myapp:latest --fail-on critical

# Сравнение двух образов
grype myapp:v1 vs myapp:v2
```

### Dockle: CIS Benchmark проверка

```bash
# Установка
brew install dockle

# Проверка образа на соответствие CIS
dockle myapp:latest

# Проверка с игнорированием
dockle --exit-code 1 --exit-level warn myapp:latest
```

---

## Практические реализации

### Функциональное тестирование контейнера

```python
import docker
import requests
import time
import pytest

@pytest.fixture(scope="module")
def container():
    """Запуск контейнера для тестирования."""
    client = docker.from_env()
    
    container = client.containers.run(
        "myapp:latest",
        ports={"8080/tcp": 8080},
        detach=True,
        environment={"DATABASE_URL": "sqlite:///test.db"}
    )
    
    time.sleep(5)  # Ожидание запуска
    
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

### Trivy в CI/CD Pipeline

```yaml
# GitLab CI
container_scan:
  stage: test
  image:
    name: aquasec/trivy:latest
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

### Testcontainers: тестирование приложения в контейнере

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

---

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
  image: aquasec/trivy:latest
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

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Hadolint: `DL3007` — using latest tag | Dockerfile использует `FROM image:latest` | Зафиксировать версию: `FROM image:1.2.3` |
| Trivy: `CRITICAL` vulnerabilities | Устаревшие зависимости в образе | Обновить base image и dependencies, пересобрать |
| Контейнер падает при запуске в CI | Нет health check / insufficient memory | Добавить `healthcheck` в Dockerfile, увеличить `--memory` |
| `permission denied` при запуске от non-root | Файлы принадлежат root | Добавить `USER` и `COPY --chown` в Dockerfile |
| Dockle: `CIS-DI-0002` — secrets in image | API-ключи захардкожены в образе | Использовать Docker secrets, multi-stage build, `.dockerignore` |
| SBOM не генерируется | Неподдерживаемый формат образа | Убедиться, что образ — OCI/Docker manifest v2 |

---

## Дополнительная информация

### См. также
- **[Безопасность контейнеров](../../Docker/Docker_security/vulnerability_scanning.md)** — SSoT для Trivy, Grype, сканирования.
- **[Dockerfile: оптимизация](../../Docker/Dockerfile/dockerfile_optimization_tools.md)** — инструменты оптимизации.
- **[SBOM и Supply Chain](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — SBOM, SLSA, Sigstore.
- **[DevSecOps Overview](../../CI-CD/DevSecOps/devsecops_overview.md)** — Shift-Left Security.
- **[Testcontainers](../../Testing/testcontainers_overview.md)** — изолированные контейнеры для тестов.

### Внешние ресурсы
- [Hadolint](https://github.com/hadolint/hadolint) — Dockerfile linter.
- [Trivy](https://trivy.dev/) — scanner для контейнеров, IaC, SBOM.
- [Grype](https://github.com/anchore/grype) — scanner уязвимостей образов.
- [Dockle](https://github.com/goodwithtech/dockle) — CIS Docker Benchmark checker.
