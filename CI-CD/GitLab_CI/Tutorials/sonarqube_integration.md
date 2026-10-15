# GitLab CI/CD + SonarQube интеграция

**Актуально для:** GitLab 17.x–19.x, SonarQube 10.x–25.x

## Определения

**SonarQube** — платформа для непрерывного контроля качества кода (Code Quality). Выполняет статический анализ (SAST), вычисляет метрики качества, обнаруживает баги, уязвимости и code smells.

**Quality Gate (QG)** — порог качества, который должен быть пройден перед merge/deploy. Включает условия на покрытие кода, дублирование, уязвимости, технический долг.

**Quality Profile** — набор правил (rules) для анализа конкретного языка программирования. Определяет, какие проверки SonarQube выполняет.

**Branch Analysis** — анализ ветки в SonarQube. Позволяет отслеживать качество кода в каждой ветке отдельно.

**PR Decoration** — автоматическое добавление комментариев в Merge Request с результатами анализа: статус QG, найденные проблемы, покрытие.

**SonarScanner** — CLI-инструмент для отправки исходного кода в SonarQube для анализа. Доступен для большинства языков и CI/CD платформ.

**Coverage** — процент кода, покрытого тестами (unit, integration). SonarQube вычисляет coverage на основе отчетов тестирования (JaCoCo, coverage.py, Istanbul и др.).

**Technical Debt** — оценка времени, необходимого для исправления всех code smells и багов. Вычисляется SonarQube на основе правил.

**Reliability Rating** — рейтинг надёжности кода (A–E) на основе количества багов. A = нет багов, E = много багов.

**Security Rating** — рейтинг безопасности (A–E) на основе количества уязвимостей.

**Maintainability Rating** — рейтинг поддерживаемости (A–E) на основе code smells и технического долга.

**Compute Engine** — фоновый процесс SonarQube, выполняющий анализ проектов. Управляет очередью задач и статусами.

**Webhook** — механизм уведомления GitLab о завершении анализа. Используется для PR Decoration и обновления статусов.

## Предварительные требования

### Роли и ответственные

| Роль | Обязанности |
| :--- | :--- |
| **SonarQube Administrator** | Установка, обновление, резервное копирование, управление пользователями и группами |
| **GitLab Maintainer** | Настройка CI/CD переменных, protected branches, MR approval rules |
| **Developer** | Генерация coverage reports, исправление findings, настройка Quality Profiles |
| **SRE/Platform Engineer** | Мониторинг, масштабирование, сетевые политики, backup/restore |

### Инфраструктура

- **SonarQube Server:** dedicated host или VM с 4+ vCPU, 8+ GB RAM, 50+ GB SSD для данных и логов
- **Database:** PostgreSQL 14+ (production), размещённый отдельно от SonarQube application node; H2 допустим только для evaluation
- **Runner:** GitLab Runner с Docker executor или Kubernetes executor; доступ к SonarQube Server по HTTPS (TCP 443)
- **Network:** egress из Runner'ов к SonarQube API и Container Registry; ingress к SonarQube из браузеров разработчиков

### Программное обеспечение

- GitLab 17.x–19.x
- SonarQube 10.x–25.x (Community, Developer, или Enterprise Edition)
- PostgreSQL 14+ для production deployments
- SonarScanner CLI 6.x+ или Docker image `sonarsource/sonar-scanner-cli`
- curl + jq в CI jobs для Quality Gate проверок
- JaCoCo (Java), coverage.py (Python), Istanbul/NYC (JS), или эквивалентные coverage reporters для поддерживаемых языков

### Безопасность

- `SONAR_TOKEN` — токен с правами `Execute Analysis` на проекте, хранится в GitLab CI/CD Variables как protected/masked
- `GITLAB_TOKEN` — токен с правами `api` для пост-комментариев в MR (если используется кастомный sonar_comment job)
- TLS-сертификаты для SonarQube Server; self-signed допустимы только в development-средах с отключённой верификацией
- Сетевые политики: SonarQube Server не должен быть доступен из публичного интернета без аутентификации

## Установка и настройка

### Развёртывание SonarQube Server

#### Вариант A: Docker Compose (single-node, production)

```yaml
# docker-compose.yml
version: "3.8"
services:
  sonarqube:
    image: sonarqube:25-community
    container_name: sonarqube
    ports:
      - "9000:9000"
    environment:
      SONAR_JDBC_URL: jdbc:postgresql://db:5432/sonarqube
      SONAR_JDBC_USERNAME: sonarqube
      SONAR_JDBC_PASSWORD: ${SONAR_DB_PASSWORD}
    volumes:
      - sonarqube_data:/opt/sonarqube/data
      - sonarqube_extensions:/opt/sonarqube/extensions
      - sonarqube_logs:/opt/sonarqube/logs
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:9000/api/system/status | grep UP"]
      interval: 30s
      timeout: 10s
      retries: 3

  db:
    image: postgres:16-alpine
    container_name: sonarqube_db
    environment:
      POSTGRES_USER: sonarqube
      POSTGRES_PASSWORD: ${SONAR_DB_PASSWORD}
      POSTGRES_DB: sonarqube
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sonarqube"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  sonarqube_data:
  sonarqube_extensions:
  sonarqube_logs:
  postgres_data:
```

```bash
# Запуск
SONAR_DB_PASSWORD=$(openssl rand -base64 32) docker compose up -d

# Проверка статуса
docker compose ps
# → sonarqube      running   9000/tcp
# → sonarqube_db   running   5432/tcp

# Инициализация: откройте http://sonarqube.example.com:9000
# Default: admin / admin (срочно смените пароль)
```

#### Вариант B: Standalone (bare metal / VM)

```bash
# 1. Скачайте SonarQube
curl -sSLo sonarqube.zip https://binaries.sonarsource.com/Distribution/sonarqube/sonarqube-25.1.0.zip
unzip sonarqube.zip -d /opt
ln -s /opt/sonarqube-25.1.0 /opt/sonarqube
chown -R sonar:sonar /opt/sonarqube*

# 2. Настройте PostgreSQL
sudo -u postgres psql -c "CREATE DATABASE sonarqube ENCODING 'UTF8';"
sudo -u postgres psql -c "CREATE USER sonarqube WITH PASSWORD 'secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE sonarqube TO sonarqube;"

# 3. Настройте sonar.properties
cat > /opt/sonarqube/conf/sonar.properties << 'EOF'
sonar.jdbc.url=jdbc:postgresql://localhost:5432/sonarqube
sonar.jdbc.username=sonarqube
sonar.jdbc.password=secure_password
sonar.web.port=9000
sonar.web.host=0.0.0.0
sonar.path.data=/opt/sonarqube/data
sonar.path.logs=/opt/sonarqube/logs
sonar.path.temp=/opt/sonarqube/temp
EOF

# 4. Запуск
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh start
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh status
# → SonarQube is running (pid 12345)
```

#### Вариант C: Kubernetes (Helm Chart)

```bash
# Добавьте репозиторий
helm repo add sonarqube https://SonarSource.github.io/helm-chart-sonarqube
helm repo update

# Установка
helm install sonarqube sonarqube/sonarqube \
  --namespace infra --create-namespace \
  --set postgresql.enabled=false \
  --set jdbcOverwrite.enabled=true \
  --set jdbcOverwrite.jdbcUrl="jdbc:postgresql://postgres.infra.svc.cluster.local:5432/sonarqube" \
  --set jdbcOverwrite.jdbcUsername="sonarqube" \
  --set jdbcOverwrite.jdbcPassword="${SONAR_DB_PASS}" \
  --set sonarProperties."sonar\.forceAuthentication"="true" \
  --set sonarProperties."sonar\.auth\.gitlab\.enabled"="true" \
  --set sonarProperties."sonar\.auth\.gitlab\.url"="https://gitlab.example.com" \
  --set sonarProperties."sonar\.auth\.gitlab\.applicationId"="${SONAR_GITLAB_APP_ID}" \
  --set sonarProperties."sonar\.auth\.gitlab\.secret"="${SONAR_GITLAB_SECRET}" \
  --set sonarProperties."sonar\.auth\.gitlab\.allowUsersToSignUp"="true" \
  --set persistence.enabled=true \
  --set persistence.storageClass="local-path" \
  --set persistence.size="20Gi" \
  --set resources.requests.cpu="400m" \
  --set resources.requests.memory="1Gi" \
  --set resources.limits.cpu="2" \
  --set resources.limits.memory="2Gi" \
  --set jvmOpts="-Xms512m -Xmx1536m" \
  --set service.type=ClusterIP \
  --set ingress.enabled=true \
  --set ingress.hosts[0].name="sonarqube.example.com"
```

> **Примечание:** Параметр `jdbcOverwrite.enabled=true` отключает встроенную базу данных H2 и переключает SonarQube на внешний PostgreSQL. Без этого используется встроенная база — для продакшена она не годится: данные пропадают при перезапуске пода.
> 
> Параметр `jvmOpts="-Xms512m -Xmx1536m"` задаёт минимальный и максимальный размер JVM heap. Максимум должен оставлять запас на накладные расходы JVM в пределах лимита памяти контейнера: `limits.memory: 2Gi − 1536m heap = ~512m` на ОС и non-heap.
```

#### Вариант D: Kubernetes (HelmRelease с Flux)

Для GitOps-подхода с Flux можно использовать HelmRelease с теми же значениями, что и вручную через `helm install`.

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: sonarqube
  namespace: infra
spec:
  chart:
    spec:
      chart: sonarqube
      version: "10.4.*"
      sourceRef:
        kind: HelmRepository
        name: sonarqube
        namespace: flux-system
  values:
    edition: "community"
    jdbcOverwrite:
      enable: true
      jdbcUrl: "jdbc:postgresql://postgres.infra.svc.cluster.local:5432/sonarqube"
      jdbcUsername: sonarqube
      jdbcPassword: "${SONAR_DB_PASS}"
    sonarProperties:
      sonar.forceAuthentication: "true"
      sonar.auth.gitlab.enabled: "true"
      sonar.auth.gitlab.url: "https://gitlab.example.com"
      sonar.auth.gitlab.applicationId: "${SONAR_GITLAB_APP_ID}"
      sonar.auth.gitlab.secret: "${SONAR_GITLAB_SECRET}"
      sonar.auth.gitlab.allowUsersToSignUp: "true"
    persistence:
      enabled: true
      storageClass: local-path
      size: 20Gi
    resources:
      requests:
        cpu: 400m
        memory: 1Gi
      limits:
        cpu: 2
        memory: 2Gi
    jvmOpts: "-Xms512m -Xmx1536m"
```

> **Примечание:** Значения в `values` идентичны тем, что используются вручную через `helm install` (см. Вариант C). Секретные значения (например, `${SONAR_DB_PASS}`) должны быть предоставлены через механизмы секретов Kubernetes (например, External Secrets Operator, как описано ниже).
#### Настройка внешних зависимостей

##### База данных PostgreSQL с CloudNativePG

SonarQube требует внешней базы данных. На infra-кластере небольшой PostgreSQL запущен через оператор CloudNativePG:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: postgres
  namespace: infra
spec:
  instances: 1
  storage:
    size: 10Gi
    storageClass: local-path
  bootstrap:
    initdb:
      database: sonarqube
      owner: sonarqube
      secret:
        name: postgres-sonarqube-creds
```

> **Примечание:** `secret.name: postgres-sonarqube-creds` указывает на Kubernetes Secret с ключами `username` и `password`. CloudNativePG создаёт базу данных и пользователя при первом запуске.

##### Учётные данные через External Secrets Operator (ESO)

Для безопасного хранения и injection секретов используется External Secrets Operator, который получает секреты из Vault:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: sonarqube-creds
  namespace: infra
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: sonarqube-creds
  data:
    - secretKey: SONAR_DB_PASS
      remoteRef:
        key: secret/infra/sonarqube
        property: db_password
    - secretKey: SONAR_GITLAB_APP_ID
      remoteRef:
        key: secret/infra/sonarqube
        property: gitlab_app_id
    - secretKey: SONAR_GITLAB_SECRET
      remoteRef:
        key: secret/infra/sonarqube
        property: gitlab_secret
```

##### Настройка OIDC с GitLab

Перед деплоем создайте GitLab Application:

    GitLab → Admin Area → Applications → New Application
    Название: SonarQube
    Redirect URI: https://sonarqube.example.com/oauth2/callback/gitlab
    Scopes: read_user, api
    Сохранить Application ID и Secret в Vault:

```bash
vault kv put secret/infra/sonarqube \
  gitlab_app_id=YOUR_APP_ID \
  gitlab_secret=YOUR_SECRET \
  db_password=POSTGRES_PASS
```



### Настройка проекта в SonarQube

1. **Создание проекта:**
   ```bash
   curl -u admin:admin_password \
     -X POST "http://localhost:9000/api/projects/create" \
     -d "name=myproject&project=mygroup_myproject&visibility=private"
   ```

2. **Генерация токена:**
   - UI: `My Account → Security → Generate Tokens`
   - Или API:
     ```bash
     curl -u admin:admin_password \
       -X POST "http://localhost:9000/api/user_tokens/generate?name=gitlab-ci" \
       -d ""
     ```

3. **Настройка Quality Gate:**
   - UI: `Quality Gates → Create` или используйте встроенный `Sonar Way`
   - Добавьте условия: coverage < 80%, reliability rating < A, new bugs > 0
   - Назначьте QG как default для проекта

4. **Настройка Quality Profile:**
   - UI: `Quality Profiles → Set as default` для каждого языка проекта
   - Импортируйте кастомные правила при необходимости

## Конфигурация

### Основные концепции

#### Архитектура интеграции GitLab CI + SonarQube

```
Push → GitLab CI Pipeline
  ├── sonar_scan
  │   ├── Запуск SonarScanner в изолированном контейнере
  │   ├── Отправка исходного кода и coverage report в SonarQube
  │   ├── Ожидание завершения Compute Engine
  │   └── Получение отчёта (issues, coverage, duplications)
  ├── test (unit tests + coverage)
  │   └── Генерация coverage report (JaCoCo, coverage.py, lcov)
  └── quality_gate
      └── Проверка Quality Gate через SonarQube API
          ├── block_merge: true (при failing QG)
          └── comment_on_mr: true (опционально)
```

#### Сравнение инструментов анализа кода

| Инструмент | Тип | Языки | Quality Gate | Интеграция с GitLab |
| :--- | :--- | :--- | :--- | :--- |
| **SonarQube** | SAST + метрики | 25+ | Да | Да (через SonarScanner + API) |
| **SonarCloud** | SaaS SonarQube | 25+ | Да | Да (native GitLab integration) |
| **Codecov** | Coverage | Мультиязычный | Нет | Да (через API) |
| **Code Climate** | SAST + coverage | Мультиязычный | Да | Да (через API) |

#### Quality Gate условия

| Условие | Описание | Пример порога |
| :--- | :--- | :--- |
| **Coverage** | Покрытие кода тестами | < 80% → FAIL |
| **Duplicated Lines** | Дублирование кода | > 3% → FAIL |
| **Reliability Rating** | Рейтинг надёжности | < A → FAIL |
| **Security Rating** | Рейтинг безопасности | < A → FAIL |
| **Maintainability Rating** | Рейтинг поддерживаемости | < A → FAIL |
| **New Bugs** | Новые баги в коде | > 0 → FAIL |
| **New Vulnerabilities** | Новые уязвимости | > 0 → FAIL |
| **New Code Smells** | Новые code smells | > 0 → FAIL |
| **Technical Debt** | Технический долг | > 5% → FAIL |

#### Механизм PR Decoration

Developer/Enterprise Edition отправляет комментарии в MR через Webhook:
1. SonarQube получает событие `Pull Request` от GitLab (или polling)
2. Compute Engine завершает анализ и вычисляет QG
3. SonarQube публикует комментарий в MR через GitLab API
4. В MR появляется блок: статус QG, метрики coverage, bugs, vulnerabilities

### Переменные окружения

| Переменная | Описание | Обязательность |
| :--- | :--- | :--- |
| `SONAR_HOST_URL` | URL SonarQube Server | Да |
| `SONAR_PROJECT_KEY` | Уникальный ключ проекта в SonarQube | Да |
| `SONAR_TOKEN` | Токен аутентификации с правами `Execute Analysis` | Да |
| `SONAR_ORGANIZATION` | Организация (только Developer Edition) | Нет |
| `SONAR_JDBC_URL` | JDBC URL для внешней БД | Нет (H2 по умолчанию) |

### Шаблоны .gitlab-ci.yml

```yaml
stages:
  - test
  - sonar_scan
  - quality_gate

variables:
  SONAR_HOST_URL: "https://sonarqube.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"

sonar_scan:
  stage: sonar_scan
  image: sonarsource/sonar-scanner-cli:6.2.1
  variables:
    GIT_DEPTH: "0"
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY \
        -Dsonar.sources=src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.gitlab.commit_sha=$CI_COMMIT_SHA \
        -Dsonar.gitlab.ref_name=$CI_COMMIT_REF_NAME
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "src/**/*"
        - "*.py"
        - "*.js"
    - if: $CI_COMMIT_BRANCH == "main"
      changes:
        - "src/**/*"
        - "*.py"
        - "*.js"
  cache:
    key: sonar-scanner-cache
    paths:
      - .sonar/cache

test:
  stage: test
  image: python:3.11
  script:
    - pip install -r requirements.txt
    - pytest --cov=src --cov-report=xml:coverage.xml
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 week

quality_gate:
  stage: quality_gate
  image: curlimages/curl:8.7.1
  script:
    - |
      ANALYSIS_ID=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&maxResults=1" \
        | jq -r '.tasks[0].id')

      for i in {1..60}; do
        STATUS=$(curl -s -u $SONAR_TOKEN: \
          "$SONAR_HOST_URL/api/ce/task?id=$ANALYSIS_ID" \
          | jq -r '.task.status')
        if [ "$STATUS" == "SUCCESS" ]; then
          break
        elif [ "$STATUS" == "FAILED" ]; then
          echo "SonarQube analysis failed"
          exit 1
        fi
        sleep 5
      done

      RESULT=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')

      if [ "$RESULT" != "OK" ]; then
        echo "Quality Gate failed!"
        curl -s -u $SONAR_TOKEN: \
          "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
          | jq '.projectStatus.conditions'
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "src/**/*"
        - "*.py"
        - "*.js"
    - if: $CI_COMMIT_BRANCH == "main"
```

## Практические сценарии

### Сценарий 1: Базовая интеграция с SonarQube (Community Edition)

**Установка SonarScanner:**
```bash
# Для Python
pip install sonar-scanner

# Для JavaScript
npm install -g sonar-scanner

# Или используйте Docker
docker run --rm -v $(pwd):/workspace sonarsource/sonar-scanner-cli:6.2.1
```

**Вариант A: Прямой запуск SonarScanner (без GitLab CI)**
```bash
sonar-scanner \
  -Dsonar.projectKey=mygroup_myproject \
  -Dsonar.sources=src/ \
  -Dsonar.host.url=https://sonarqube.example.com \
  -Dsonar.login=$SONAR_TOKEN
```

**Вариант B: GitLab CI (.gitlab-ci.yml)**
```yaml
stages:
  - sonar
  - test
  - quality_gate

variables:
  SONAR_HOST_URL: "https://sonarqube.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"

sonar_scan:
  stage: sonar
  image: sonarsource/sonar-scanner-cli:6.2.1
  variables:
    GIT_DEPTH: "0"
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY \
        -Dsonar.sources=src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"

test:
  stage: test
  image: python:3.11
  script:
    - pip install -r requirements.txt
    - pytest --cov=src --cov-report=xml:coverage.xml
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

quality_gate:
  stage: quality_gate
  image: curlimages/curl:8.7.1
  script:
    - |
      ANALYSIS_ID=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&maxResults=1" \
        | jq -r '.tasks[0].id')

      for i in {1..60}; do
        STATUS=$(curl -s -u $SONAR_TOKEN: \
          "$SONAR_HOST_URL/api/ce/task?id=$ANALYSIS_ID" \
          | jq -r '.task.status')
        if [ "$STATUS" == "SUCCESS" ]; then
          break
        elif [ "$STATUS" == "FAILED" ]; then
          echo "SonarQube analysis failed"
          exit 1
        fi
        sleep 5
      done

      RESULT=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')

      if [ "$RESULT" != "OK" ]; then
        echo "Quality Gate failed!"
        curl -s -u $SONAR_TOKEN: \
          "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
          | jq '.projectStatus.conditions'
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
```

**Валидация:**
```bash
# Проверьте, что анализ завершён
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&maxResults=1" | jq

# Проверьте Quality Gate
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" | jq

# Ожидаемый результат:
# - projectStatus.status = "OK"
# - conditions[] с status = "OK" для всех правил
# - В MR отображается блок "SonarQube Analysis" с метриками
```

### Сценарий 2: SonarQube Developer/Enterprise Edition (Branch Analysis + PR Decoration)

```yaml
variables:
  SONAR_HOST_URL: "https://sonarqube.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"
  SONAR_ORGANIZATION: "mygroup"

sonar_scan:
  stage: sonar
  image: sonarsource/sonar-scanner-cli:6.2.1
  variables:
    GIT_DEPTH: "0"
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY \
        -Dsonar.organization=$SONAR_ORGANIZATION \
        -Dsonar.sources=src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.pullrequest.key=$CI_MERGE_REQUEST_IID \
        -Dsonar.pullrequest.branch=$CI_COMMIT_REF_NAME \
        -Dsonar.pullrequest.base=$CI_MERGE_REQUEST_TARGET_BRANCH_NAME \
        -Dsonar.pullrequest.provider=gitlab \
        -Dsonar.coverage.jacoco.xmlReportPaths=coverage.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "src/**/*"
        - "*.py"
        - "*.js"
```

**Версия Developer/Enterprise Edition поддерживает:**
- Branch Analysis — отдельный анализ каждой ветки
- PR Decoration — автоматические комментарии в MR
- Portfolio Management — агрегация метрик по нескольким проектам
- Custom Quality Gates — продвинутые условия

**Валидация:**
```bash
# Проверьте, что анализ PR создан
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY:branch-$CI_COMMIT_REF_NAME&metricKeys=bugs,vulnerabilities,coverage" | jq

# Проверьте, что PR Decoration опубликован
# В MR должен появиться комментарий от SonarQube bot со статусом QG

# Ожидаемый результат:
# - Компонент с ключом mygroup_myproject:branch-feature-x существует
# - В MR есть блок с метриками качества
# - Quality Gate статус отображается в MR
```

### Сценарий 3: Автоматический комментарий в Merge Request (Community Edition)

Для Community Edition, где нет встроенного PR Decoration, можно использовать кастомный job:

```yaml
sonar_comment:
  stage: quality_gate
  image: curlimages/curl:8.7.1
  script:
    - |
      STATUS=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')

      COVERAGE=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=coverage" \
        | jq -r '.component.measures[0].value')

      BUGS=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=bugs" \
        | jq -r '.component.measures[0].value')

      VULNERABILITIES=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=vulnerabilities" \
        | jq -r '.component.measures[0].value')

      COMMENT="## SonarQube Analysis

      **Quality Gate:** $STATUS
      **Coverage:** $COVERAGE%
      **Bugs:** $BUGS
      **Vulnerabilities:** $VULNERABILITIES

      [View full report]($SONAR_HOST_URL/dashboard?id=$SONAR_PROJECT_KEY)"

      curl --request POST \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{\"body\": \"$COMMENT\"}" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Валидация:**
```bash
# Проверьте, что комментарий создан
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes" | jq

# Ожидаемый результат:
# - В MR появился комментарий "SonarQube Analysis"
# - Комментарий содержит метрики coverage, bugs, vulnerabilities
# - Ссылка на dashboard корректная
```

### Сценарий 4: Блокировка merge при failing Quality Gate

**Настройка в GitLab:**
1. Перейдите в `Settings → CI/CD → Quality Gates`
2. Включите `Block merge if Quality Gate fails`
3. Настройте условия Quality Gate в SonarQube (`Quality Gates → Create`)

**.gitlab-ci.yml:**
```yaml
quality_gate:
  stage: quality_gate
  image: curlimages/curl:8.7.1
  script:
    - |
      STATUS=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')

      if [ "$STATUS" != "OK" ]; then
        echo "Quality Gate failed. Merge blocked."
        exit 1
      fi
  allow_failure: false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Валидация:**
```bash
# 1. Создайте MR с умышленно failing QG (например, coverage < 80%)
# 2. Проверьте, что pipeline завершился с ошибкой
# 3. Проверьте, что кнопка "Merge" заблокирована

# Ожидаемый результат:
# - Pipeline status = failed
# - Merge button отключена
# - В MR видно причину: "Quality Gate failed"
```

### Сценарий 5: Multi-module проект (monorepo)

```yaml
variables:
  SONAR_PROJECT_KEY: "mygroup_myproject"

sonar_scan_backend:
  stage: sonar
  image: sonarsource/sonar-scanner-cli:6.2.1
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY:backend \
        -Dsonar.sources=backend/src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.coverage.jacoco.xmlReportPaths=backend/coverage.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "backend/**/*"
        - "backend/coverage.xml"
    - if: $CI_COMMIT_BRANCH == "main"
      changes:
        - "backend/**/*"

sonar_scan_frontend:
  stage: sonar
  image: sonarsource/sonar-scanner-cli:6.2.1
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY:frontend \
        -Dsonar.sources=frontend/src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.javascript.lcov.reportPaths=frontend/coverage/lcov.info
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "frontend/**/*"
        - "frontend/coverage/lcov.info"
    - if: $CI_COMMIT_BRANCH == "main"
      changes:
        - "frontend/**/*"

quality_gate:
  stage: quality_gate
  image: curlimages/curl:8.7.1
  script:
    - |
      for MODULE in backend frontend; do
        RESULT=$(curl -s -u $SONAR_TOKEN: \
          "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY:$MODULE" \
          | jq -r '.projectStatus.status')
        if [ "$RESULT" != "OK" ]; then
          echo "Quality Gate failed for $MODULE"
          exit 1
        fi
      done
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "backend/**/*"
        - "frontend/**/*"
```

**Валидация:**
```bash
# Проверьте, что оба модуля проанализированы
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY:backend&metricKeys=coverage,bugs" | jq
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY:frontend&metricKeys=coverage,bugs" | jq

# Ожидаемый результат:
# - Оба проекта backend и frontend имеют статус OK
# - Coverage отображается отдельно для каждого модуля
# - В MR видны findings из обоих модулей
```

### Сценарий 6: Air-gapped среда (внутренний registry, нет внешнего доступа)

**Предварительные требования:**
- SonarQube deployed внутри air-gapped сети
- GitLab Runner имеет доступ к SonarQube Server
- SonarScanner image предзагружен во внутренний registry
- Coverage reporters предустановлены в Runner image

```yaml
variables:
  SONAR_HOST_URL: "https://sonarqube.internal.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"
  INTERNAL_REGISTRY: "registry.internal.example.com:5000"

sonar_scan:
  stage: sonar
  image: "${INTERNAL_REGISTRY}/sonarsource/sonar-scanner-cli:6.2.1"
  variables:
    GIT_DEPTH: "0"
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY \
        -Dsonar.sources=src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.coverage.jacoco.xmlReportPaths=coverage.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "src/**/*"
        - "*.py"
        - "*.java"
    - if: $CI_COMMIT_BRANCH == "main"
```

**Валидация:**
```bash
# Проверьте, что Runner может вытащить образ
docker pull registry.internal.example.com:5000/sonarsource/sonar-scanner-cli:6.2.1

# Проверьте доступность SonarQube
curl -k -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/system/status" | jq

# Ожидаемый результат:
# - Образ скачивается из внутреннего registry
# - Анализ завершается успешно
# - Quality Gate проверяется без внешнего доступа
```

### Сценарий 7: Отключение Quality Gate для определённых jobs

```yaml
sonar_scan:
  stage: sonar
  image: sonarsource/sonar-scanner-cli:6.2.1
  script:
    - sonar-scanner \
        -Dsonar.projectKey=$SONAR_PROJECT_KEY \
        -Dsonar.sources=src/ \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.qualitygate.wait=false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "src/**/*"

quality_gate:
  stage: quality_gate
  image: curlimages/curl:8.7.1
  script:
    - |
      STATUS=$(curl -s -u $SONAR_TOKEN: \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')
      if [ "$STATUS" != "OK" ]; then
        echo "Quality Gate failed"
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  when: manual
```

**Валидация:**
```bash
# 1. Создайте MR
# 2. Проверьте, что sonar_scan завершается без ожидания QG
# 3. Проверьте, что quality_gate job требует ручного запуска

# Ожидаемый результат:
# - sonar_scan завершается сразу после отправки анализа
# - quality_gate виден в UI как manual job
# - При ручном запуске проверяется QG
```

## Валидация и проверка

### Базовые проверки

```bash
# 1. Проверка доступности SonarQube
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/system/status" | jq '.status'
# → "UP"

# 2. Проверка, что проект существует
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/projects/search?q=$SONAR_PROJECT_KEY" | jq '.components[0].key'
# → "mygroup_myproject"

# 3. Проверка Quality Profile для языка
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/qualityprofiles/search?project=$SONAR_PROJECT_KEY" | jq '.profiles[0].name'
# → "Sonar way"
```

### Продвинутые проверки

```bash
# 4. Проверка последнего анализа
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&maxResults=1" | jq '.tasks[0].status'
# → "SUCCESS"

# 5. Проверка метрик
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=coverage,bugs,vulnerabilities,code_smells" | jq '.component.measures'
# → [{"metric":"coverage","value":"85.5"}, ...]

# 6. Проверка Quality Gate
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" | jq '.projectStatus.status'
# → "OK"
```

### Ожидаемые результаты по сценариям

| Сценарий | Критерий успеха |
| :--- | :--- |
| **1: Базовая интеграция** | Анализ завершён, QG = OK, coverage отображается в MR |
| **2: Developer Edition** | Branch Analysis работает, PR Decoration опубликован |
| **3: Автоматический комментарий** | Комментарий с метриками создан в MR |
| **4: Блокировка merge** | Merge button отключена при failing QG |
| **5: Multi-module** | Оба модуля проанализированы, QG проходит для каждого |
| **6: Air-gapped** | Анализ работает без внешнего доступа, образы из внутреннего registry |
| **7: Отключение QG** | sonar_scan завершается сразу, quality_gate = manual |

## Operations and Commands

### Управление SonarQube Server

```bash
# Статус
docker compose ps
# Или для standalone
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh status

# Логи
docker compose logs -f sonarqube
# Или
tail -f /opt/sonarqube/logs/sonar.log
tail -f /opt/sonarqube/logs/ce.log
tail -f /opt/sonarqube/logs/web.log

# Перезапуск
docker compose restart sonarqube
# Или
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh restart

# Остановка
docker compose down
# Или
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh stop
```

### Управление проектами и токенами

```bash
# Создание проекта
curl -u admin:admin \
  -X POST "http://localhost:9000/api/projects/create" \
  -d "name=myproject&project=mygroup_myproject"

# Генерация токена
curl -u admin:admin \
  -X POST "http://localhost:9000/api/user_tokens/generate?name=gitlab-ci" \
  -d ""

# Удаление проекта
curl -u admin:admin \
  -X POST "http://localhost:9000/api/projects/delete" \
  -d "project=mygroup_myproject"

# Список проектов
curl -u admin:admin "http://localhost:9000/api/projects/search" | jq '.components[].key'
```

### Управление Quality Gates

```bash
# Список Quality Gates
curl -u admin:admin "http://localhost:9000/api/qualitygates/search" | jq '.qualitygates[].name'

# Получение условий QG
curl -u admin:admin "http://localhost:9000/api/qualitygates/get?name=Sonar%20Way" | jq '.conditions'

# Назначение QG по умолчанию
curl -u admin:admin \
  -X POST "http://localhost:9000/api/qualitygates/select" \
  -d "gateName=Sonar%20Way&projectKey=mygroup_myproject"
```

### Управление анализами

```bash
# Проверка статуса последнего анализа
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&maxResults=1" | jq '.tasks[0]'

# Проверка Quality Gate
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" | jq '.projectStatus'

# Получение метрик
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=coverage,bugs,vulnerabilities,code_smells,duplicated_lines_density" | jq '.component.measures'

# Получение issues
curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/issues/search?componentKeys=$SONAR_PROJECT_KEY&ps=10" | jq '.issues[] | {key, severity, type, message}'

# Принудительный rerun анализа (через re-scan)
# SonarQube не имеет принудительного rerun; повторите push в branch
```

### Предзагрузка образов и кэширование

```bash
# Предзагрузка SonarScanner image в internal registry
docker pull sonarsource/sonar-scanner-cli:6.2.1
docker tag sonarsource/sonar-scanner-cli:6.2.1 registry.internal.example.com:5000/sonarsource/sonar-scanner-cli:6.2.1
docker push registry.internal.example.com:5000/sonarsource/sonar-scanner-cli:6.2.1

# Предзагрузка coverage reporters в Runner image
# Dockerfile для кастомного Runner image:
FROM sonarsource/sonar-scanner-cli:6.2.1
RUN apt-get update && apt-get install -y \
    jq \
    python3-pip \
    nodejs \
    npm \
  && pip3 install coverage \
  && npm install -g Istanbul

# Очистка кэша SonarQube (если требуется)
curl -u admin:admin -X POST "http://localhost:9000/api/system/migrate_db"
```

## Крайние случаи (Edge Cases)

### Air-gapped среда

**Проблема:** SonarQube Server и Runner'ы не имеют доступа к интернету.

**Решение:**
1. Разверните SonarQube внутри air-gapped сети
2. Предзагрузите `sonarsource/sonar-scanner-cli` во внутренний registry
3. Настройте coverage reporters в кастомном Runner image
4. Отключите уведомления и внешние webhooks:
   ```properties
   sonar.notifications.disable=true
   ```
5. Для language plugins: скачайте `.jar` файлы из [SonarQube Marketplace](https://docs.sonarqube.org/latest/instance-administration/plugins/) и разместите в `extensions/plugins/`

### Network partitions и потеря связи

**Проблема:** Runner не может достичь SonarQube Server.

**Решение:**
1. Настройте health check в CI job с retries:
   ```bash
   for i in {1..5}; do
     curl -s -o /dev/null -w "%{http_code}" "$SONAR_HOST_URL/api/system/status" && break
     sleep 10
   done
   ```
2. Используйте `allow_failure: true` для quality_gate job с fallback
3. Настройте алерты на недоступность SonarQube

### H2 Database в production

**Проблема:** SonarQube использует встроенную H2 вместо PostgreSQL.

**Решение:**
1. H2 не рекомендуется для production; используйте PostgreSQL
2. Для миграции с H2 на PostgreSQL:
   ```bash
   # Остановите SonarQube
   docker compose stop sonarqube
   
   # Запустите миграцию
   docker compose exec sonarqube /opt/sonarqube/bin/sonar.sh migrate-db
   
   # Обновите sonar.properties для использования PostgreSQL
   ```

### Fork pipelines и untrusted код

**Проблема:** SonarQube может быть перегружен сканированиями из fork'ов.

**Решение:**
1. Ограничьте SonarQube scan jobs только trusted branches:
   ```yaml
   rules:
     - if: $CI_PROJECT_PATH == "mygroup/myproject"
     - if: $CI_COMMIT_BRANCH == "main"
   ```
2. Используйте ephemeral Runner'ы для fork pipelines
3. Ограничьте rate limit в SonarQube (`Administration → Configuration → General Settings → Analysis → Background Task`)

### Лицензирование и dual-licensed языки

**Проблема:** Проект содержит код с разными лицензиями (GPL, MIT, proprietary).

**Решение:**
1. Настройте License Scanning Quality Gate с allow/deny списками
2. Используйте `sonar.issue.ignore.multicriteria` для исключения лицензионных findings
3. Автоматизируйте проверку через CI:
   ```bash
   curl -u $SONAR_TOKEN: "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=license_hash" | jq
   ```

### Версионный drift Quality Profiles

**Проблема:** Quality Profile устарел после обновления языка.

**Решение:**
1. Регулярно обновляйте Quality Profiles
2. Версионируйте конфигурацию QP в виде XML/JSON:
   ```bash
   curl -u admin:admin "http://localhost:9000/api/qualityprofiles/export?language=java&qualityProfile=Sonar%20way" > sonar-way-java.xml
   ```
3. Храните конфигурацию в репозитории и восстанавливайте после обновления

### Большие репозитории и таймауты

**Проблема:** Анализ long-running проектов превышает таймаут CI.

**Решение:**
1. Увеличьте `sonar.ws.timeout` в SonarQube:
   ```properties
   sonar.ws.timeout=300
   ```
2. Увеличьте таймаут GitLab CI job:
   ```yaml
   sonar_scan:
     timeout: 30m
   ```
3. Используйте `sonar.analysis.mode=incremental` (если поддерживается версией)

### Cache invalidation и `GIT_DEPTH`

**Проблема:** SonarQube анализирует не все коммиты из-за shallow clone.

**Решение:**
```yaml
sonar_scan:
  variables:
    GIT_DEPTH: "0"
  script:
    - git fetch --unshallow || true
    - sonar-scanner ...
```

### DAST и SonarQube token expiry

**Проблема:** `SONAR_TOKEN` истёк, анализ падает с 401.

**Решение:**
1. Настройте алерты на истечение токена (за 7 дней до expiry)
2. Используйте machine user с длительным сроком жизни
3. Восстановите доступ через API:
   ```bash
   curl -u admin:admin -X POST "http://localhost:9000/api/user_tokens/revoke?login=gitlab-ci&token=old_token"
   curl -u admin:admin -X POST "http://localhost:9000/api/user_tokens/generate?name=gitlab-ci" -d ""
   ```

### Восстановление после сбоя Compute Engine

**Проблема:** Compute Engine завис, анализ не завершается.

**Решение:**
1. Проверьте статус Compute Engine:
   ```bash
   curl -u admin:admin "http://localhost:9000/api/ce/activity?maxResults=10" | jq '.tasks[] | select(.status == "FAILED" or .status == "IN_PROGRESS")'
   ```
2. Отмените зависшие задачи:
   ```bash
   curl -u admin:admin -X POST "http://localhost:9000/api/ce/cancel?taskId=TASK_ID"
   ```
3. Перезапустите Compute Engine:
   ```bash
   docker compose restart sonarqube
   ```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` | Неверный `SONAR_TOKEN` | Проверьте токен в SonarQube → My Account → Security |
| `Project not found` | Проект не создан в SonarQube | Создайте проект вручную или через API |
| `Quality Gate is FAILED` | Не выполнены условия QG | Проверьте coverage, bugs, vulnerabilities |
| `Coverage not reported` | Отчет coverage не найден | Проверьте путь к coverage report в sonar-scanner |
| `PR Decoration not working` | Нет прав на MR в GitLab | Проверьте права SonarQube в GitLab |
| `Analysis is stuck` | Долгий анализ или проблемы с SonarQube | Проверьте логи SonarQube, увеличьте таймаут |
| `Compute Engine out of memory` | Недостаточно RAM для SonarQube | Увеличьте память до 8+ GB, настройте `sonar.search.javaOpts` |
| `Database connection refused` | PostgreSQL недоступен | Проверьте `SONAR_JDBC_URL`, сетевые политики, credentials |
| `License not found` | Отсутствует лицензия для language plugin | Установите плагин через `Administration → Marketplace` |
| `jq: command not found` | В образе Runner отсутствует jq | Используйте образ с jq или установите: `apk add jq` |
| `GIT_DEPTH=0 missing` | Shallow clone, анализ неполный | Установите `GIT_DEPTH: "0"` в job variables |
| `Quality Gate timeout` | Анализ не завершается за 5 минут | Увеличьте timeout в quality_gate job до 10 минут |

## Best Practices

### Разработка (Dev)

1. **Генерируйте coverage report для каждого языка:** JaCoCo (Java), coverage.py (Python), Istanbul/NYC (JS).
2. **Интегрируйте SonarScanner в pre-commit hook:** Локальная проверка перед коммитом.
3. **Используйте PR Decoration:** Автоматические комментарии в MR упрощают review.
4. **Настраивайте Quality Profile для каждого языка:** Разные наборы правил для backend/frontend.
5. **Версионируйте Quality Profiles:** Экспортируйте конфигурацию QP в виде XML/JSON.
6. **Используйте `rules:changes`:** Ограничьте запуск SonarQube scan только изменёнными файлами для экономии времени.

### Эксплуатация (DevOps/SRE)

1. **Блокируйте merge при failing QG:** Включите `Block merge if Quality Gate fails` в GitLab.
2. **Мониторьте метрики SonarQube:** Тренд coverage, технический долг, количество багов.
3. **Регулярно обновляйте правила:** Quality Profile должен актуализироваться под новые версии языков.
4. **Используйте branch analysis:** Отслеживайте качество кода в каждой ветке отдельно.
5. **Настройте алерты на ухудшение качества:** При падении coverage > 5% — алерт в Slack.
6. **Используйте PostgreSQL для production:** H2 не предназначен для production workloads.
7. **Настройте backup:** Ежедневный бэкап PostgreSQL и конфигурации SonarQube.
8. **Масштабируйте Compute Engine:** Для >50 проектов используйте отдельный узел Compute Engine с увеличенной памятью.

### Sysadmin

1. **Настройте retention для анализа:** Ограничьте хранение старых анализов (30–90 дней).
2. **Ограничьте доступ к SonarQube:** Только authorized users имеют доступ к проектам.
3. **Используйте отдельный SonarQube для production:** Изоляция данных.
4. **Резервное копирование базы SonarQube:** Регулярно бэкапите PostgreSQL и конфигурацию.
5. **Масштабируйте SonarQube:** Для >100 проектов используйте cluster mode.
6. **Настройте мониторинг:** JMX метрики (JVM, Compute Engine, Database), экспортируйте в Prometheus.
7. **Используйте reverse proxy:** Nginx/Apache для TLS termination, gzip, access logs.
8. **Настройте firewall:** Разрешите только порт 9000 (или 443 за reverse proxy) и 5432 (PostgreSQL) для SonarQube Server.

### Настройка мониторинга (SRE)

```yaml
# prometheus.yml — SonarQube JMX Exporter
rules:
  - job_name: sonarqube
    static_configs:
      - targets: ['localhost:9000']
    metrics_path: '/api/monitoring/metrics'
    scheme: https
    tls_config:
      insecure_skip_verify: true
    basic_auth:
      username: admin
      password: $SONAR_MONITORING_TOKEN
```

## Очистка

### Удаление проекта

```bash
# Удаление проекта через API
curl -u admin:admin -X POST "http://localhost:9000/api/projects/delete" \
  -d "project=mygroup_myproject"

# Удаление токена
curl -u admin:admin -X POST "http://localhost:9000/api/user_tokens/revoke?login=gitlab-ci&token=$TOKEN"
```

### Очистка старых анализов

```bash
# Очистка старых задач Compute Engine
curl -u admin:admin -X POST "http://localhost:9000/api/ce/clean"

# Удаление анализов за определенный период
# Пример: удалить анализы для проекта my-project с 2024-01-01 по 2024-06-01
curl -u admin:admin -X POST \
  "http://localhost:9000/api/projects/delete_analyses?project=my-project&from=2024-01-01&to=2024-06-01"
```

> **Примечание:** Для автоматического очищения старых анализов можно настроить параметры через интерфейс SonarQube: Administration → Configuration → Housekeeping. Там можно настроить период хранения анализов и другие параметры очистки.

### Удаление orphaned отчетов

```bash
# Просмотр старых задач
curl -u admin:admin "http://localhost:9000/api/ce/activity?maxResults=100" | jq '.tasks[] | select(.status == "FAILED") | .id'

# Отмена зависших задач
for TASK_ID in $(curl -s -u admin:admin "http://localhost:9000/api/ce/activity?maxResults=100" | jq -r '.tasks[] | select(.status == "IN_PROGRESS") | .id'); do
  curl -u admin:admin -X POST "http://localhost:9000/api/ce/cancel?taskId=$TASK_ID"
done
```

### Очистка кэша и логов

```bash
# Docker Compose
docker compose down -v
docker volume prune

# Standalone
sudo -u sonar rm -rf /opt/sonarqube/data/*
sudo -u sonar rm -rf /opt/sonarqube/logs/*
sudo -u sonar rm -rf /opt/sonarqube/temp/*

# Внутри контейнера
docker compose exec sonarqube rm -rf /opt/sonarqube/data/*
docker compose exec sonarqube rm -rf /opt/sonarqube/logs/*
```

### Удаление language plugins

```bash
# Удаление неиспользуемых плагинов
docker compose exec sonarqube rm -f /opt/sonarqube/extensions/plugins/*.jar
docker compose restart sonarqube
```

## Дополнительная информация

### Связанные файлы

- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — общие принципы защиты CI/CD
- **[Policy-as-Code в GitLab CI](../Advanced/policy_as_code.md)** — OPA, Checkov, TFLint, Trivy
- **[SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md)** — Cosign, Sigstore
- **[Security Scanning в GitLab CI](../Concepts/gitlab_ci_security_scanning.md)** — встроенные шаблоны безопасности GitLab
- **[Proxy и Air-Gapped GitLab CI/CD](../Tutorials/proxy_air_gapped_gitlab_ci.md)** — настройка прокси и air-gapped сред

### Внешние ресурсы

- [SonarQube Documentation](https://docs.sonarqube.org/latest/)
- [SonarScanner Documentation](https://docs.sonarqube.org/latest/analysis/scan/sonarscanner/)
- [SonarQube GitLab Integration](https://docs.sonarqube.org/latest/analysis/gitlab/)
- [SonarQube Administration Guide](https://docs.sonarqube.org/latest/instance-administration/)
- [Quality Gates Documentation](https://docs.sonarqube.org/latest/user-guide/quality-gates/)
