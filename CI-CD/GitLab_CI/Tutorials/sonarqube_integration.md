# GitLab CI/CD + SonarQube интеграция

**Актуально для:** GitLab 17.x–19.x (самообслуживание), SonarQube Server 2026.5 LTA / 2026.1 LTA и SonarQube Community Build 26.x, SonarScanner CLI 12.x

> **Терминология.** С 2025 года линейка Community Edition переименована в **SonarQube Community Build** (прежнее название — Community Edition). Платные редакции — Developer / Enterprise — теперь называются **SonarQube Server**. Self-hosted и SaaS-вариант (**SonarCloud**) — разные продукты: в этой статье речь только о self-hosted SonarQube.

## Определения

**SonarQube** — платформа для непрерывного контроля качества кода (Code Quality). Выполняет статический анализ (SAST), вычисляет метрики качества, обнаруживает баги, уязвимости и code smells. Полный обзор редакций и функциональных отличий — в [SonarQube (Tools)](../../Tools/sonarqube.md).

**Quality Gate (QG)** — порог качества, который должен быть пройден перед merge/deploy. Включает условия на покрытие кода, дублирование, уязвимости, технический долг.

**Quality Profile** — набор правил (rules) для анализа конкретного языка программирования. Определяет, какие проверки SonarQube выполняет.

**New Code** — период (по умолчанию — изменения за N дней или от предыдущего релиза), в рамках которого SonarQube считает код «новым». Условия Quality Gate по умолчанию применяются именно к новому коду (подход Clean as You Code): старые проблемы не блокируют merge, блокируют только появляющиеся заново.

**Branch Analysis** — анализ ветки в SonarQube (Developer/Enterprise). Позволяет отслеживать качество кода в каждой ветке отдельно.

**PR Decoration** — автоматическое добавление комментариев в Merge Request с результатами анализа: статус QG, найденные проблемы, покрытие. Требует Developer/Enterprise и настроенной DevOps-интеграции с GitLab.

**SonarScanner** — CLI-инструмент для отправки исходного кода в SonarQube для анализа. Доступен для большинства языков и CI/CD платформ; для CI рекомендуется Docker-образ `sonarsource/sonar-scanner-cli`.

**Coverage** — процент кода, покрытого тестами (unit, integration). SonarQube вычисляет coverage на основе отчётов тестирования (JaCoCo, coverage.py, Istanbul и др.).

**Technical Debt** — оценка времени, необходимого для исправления всех code smells и багов. Вычисляется SonarQube на основе правил.

**Reliability Rating** — рейтинг надёжности кода (A–E) на основе количества багов. A = нет багов, E = много багов.

**Security Rating** — рейтинг безопасности (A–E) на основе количества уязвимостей.

**Maintainability Rating** — рейтинг поддерживаемости (A–E) на основе code smells и технического долга.

**Compute Engine** — фоновый процесс SonarQube, выполняющий обработку результатов анализа (индексация, расчёт метрик и Quality Gate). Управляет очередью задач и статусами; статусы читаются через `api/ce/activity` и `api/ce/task`.

**Webhook** — механизм уведомления GitLab о завершении анализа. Используется для PR Decoration и обновления статусов.

## Предварительные требования

### Роли и ответственные

| Роль | Обязанности |
| :--- | :--- |
| **SonarQube Administrator** | Установка, обновление, резервное копирование, управление пользователями и группами |
| **GitLab Maintainer** | Настройка CI/CD переменных, protected branches, MR approval rules, Merge Checks |
| **Developer** | Генерация coverage reports, исправление findings, настройка Quality Profiles |
| **SRE/Platform Engineer** | Мониторинг, масштабирование, сетевые политики, backup/restore |

### Инфраструктура

- **SonarQube Server:** dedicated host или VM с 4+ vCPU, 8+ GB RAM, 50+ GB SSD для данных и логов
- **Database:** PostgreSQL 12+ (поддерживается SonarQube; в production практикуется 15/16), размещённый отдельно от SonarQube application node; встроенная H2 допустима только для evaluation/тестов
- **OS-параметры:** для Elasticsearch, который использует SonarQube, требуется `vm.max_map_count=262144` и достаточное значение `fs.file-max` (см. [Installing the database](https://docs.sonarsource.com/sonarqube-server/server-installation/installing-the-database.md))
- **Runner:** GitLab Runner с Docker executor (рекомендация SonarQube для CI-интеграций) или Kubernetes executor; доступ к SonarQube по HTTPS (TCP 443)
- **Network:** egress из Runner'ов к SonarQube API и Container Registry; ingress к SonarQube из браузеров разработчиков
- **GitLab → SonarQube:** исходный код должен быть доступен сканеру (Runner клонирует репозиторий); SonarQube не ходит в GitLab за кодом — обратная связь (декорация MR) идёт через API GitLab

### Программное обеспечение

- GitLab 17.x–19.x
- SonarQube Server 2026.x LTA (Developer/Enterprise) или SonarQube Community Build 26.x
- PostgreSQL 12+ для production
- SonarScanner CLI 12.x (Docker image `sonarsource/sonar-scanner-cli:12` или zip-дистрибутив)
- curl + jq в CI jobs для проверок Quality Gate и отправки комментариев в MR
- JaCoCo (Java), coverage.py (Python), Istanbul/NYC (JS), `dotnet-coverage` (.NET) или эквивалентные coverage reporters

### Безопасность

- `SONAR_TOKEN` — токен типа **Project Analysis Token** (права только на анализ указанного проекта) или глобальный токен с правом `Execute Analysis`; хранится в GitLab CI/CD Variables как protected + masked
- `GITLAB_TOKEN` — токен с правами `api` (или group access token со скоупом `api`) для кастомных комментариев в MR; аналогично protected + masked
- `sonar.web.systemPasscode` — секрет для Prometheus-скрейпа метрик SonarQube (см. раздел «Настройка мониторинга (SRE)»)
- TLS-сертификаты для SonarQube; self-signed допустим только в development, в air-gapped средах с internal CA настраивается truststore сканера (см. сценарий 6)
- Сетевые политики: SonarQube не должен быть доступен из публичного интернета без аутентификации; включите `sonar.forceAuthentication=true`

## Установка и настройка

### Развёртывание SonarQube Server

#### Вариант A: Docker Compose (single-node)

```yaml
# docker-compose.yml
services:
  sonarqube:
    # Community Build. Для SonarQube Server LTA (Developer) используйте
    # тег вида sonarqube:2026.5-lta-developer
    image: sonarqube:community
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

# Дождитесь полной инициализации (миграция схемы БД при первом старте занимает минуты)
curl -s http://localhost:9000/api/system/status | jq -r .status
# → "UP"

# Первый вход: http://sonarqube.example.com:9000
# admin / admin (срочно смените пароль)
```

> **Примечание:** тег `sonarqube:community` — «скользящий» (последний Community Build). Для воспроизводимости пиньте точный тег из [Docker Hub](https://hub.docker.com/_/sonarqube), например `sonarqube:26.10.0.133078-community`.

#### Вариант B: Standalone (bare metal / VM)

```bash
# 1. Скачайте SonarQube (актуальную LTA-версию смотрите в Distribution)
SQ_VERSION=2026.5.1   # замените на актуальную версию
curl -sSLo sonarqube.zip \
  "https://binaries.sonarsource.com/Distribution/sonarqube/sonarqube-${SQ_VERSION}.zip"
unzip sonarqube.zip -d /opt
ln -s "/opt/sonarqube-${SQ_VERSION}" /opt/sonarqube
useradd -r -s /bin/false sonar
chown -R sonar:sonar /opt/sonarqube*

# 2. Подготовьте PostgreSQL (PostgreSQL 15+: схема public принадлежит владельцу БД,
# поэтому базу сразу создаём под пользователем sonarqube)
sudo -u postgres psql <<'SQL'
CREATE USER sonarqube WITH PASSWORD 'secure_password';
CREATE DATABASE sonarqube OWNER sonarqube ENCODING 'UTF8';
SQL

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
sonar.forceAuthentication=true
EOF

# 4. Параметры ОС (Elasticsearch)
sysctl -w vm.max_map_count=262144
sysctl -w fs.file-max=65535
# закрепите в /etc/sysctl.conf

# 5. Запуск (дистрибутив содержит встроенный JRE; отдельная установка Java не нужна)
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh start
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh status
# → SonarQube is running (pid 12345)
```

#### Вариант C: Kubernetes (Helm Chart)

```bash
# Добавьте репозиторий и посмотрите доступные версии чарта
helm repo add sonarqube https://SonarSource.github.io/helm-chart-sonarqube
helm repo update
helm search repo sonarqube/sonarqube --versions | head

# Установка (Community Build)
helm install sonarqube sonarqube/sonarqube \
  --namespace infra --create-namespace \
  --version 2026.5.1001 \
  --set community.enabled=true \
  --set community.buildNumber=26.10.0.133078 \
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
  --set env[0].name=SONAR_WEB_JAVAOPTS \
  --set env[0].value="-Xms512m -Xmx1536m" \
  --set persistence.enabled=true \
  --set persistence.storageClass="local-path" \
  --set persistence.size="20Gi" \
  --set resources.requests.cpu="400m" \
  --set resources.requests.memory="1Gi" \
  --set resources.limits.cpu="2" \
  --set resources.limits.memory="2Gi" \
  --set service.type=ClusterIP \
  --set ingress.enabled=true \
  --set ingress.hosts[0].name="sonarqube.example.com"
```

> **Примечание:** для SonarQube Server (Developer/Enterprise) вместо `community.*` используйте `--set edition=developer` — допустимые значения `edition`: `developer`, `enterprise`. Значение `edition: "community"` чарт не принимает: Community Build включается ключом `community.enabled`.
>
> `jdbcOverwrite.enabled=true` переключает SonarQube на внешний PostgreSQL (без него используется встроенная H2 — для продакшена она не годится: данные пропадают при перезапуске пода). Ключ `jdbcOverwrite.enable` помечен в чарте как deprecated — используйте `enabled`.
>
> `jvmOpts`/`jvmCeOpts` в чарте deprecated: heap настраивается через переменные окружения `SONAR_WEB_JAVAOPTS` и `SONAR_CE_JAVAOPTS`. Максимум heap должен оставлять запас на non-heap в пределах лимита памяти контейнера: `limits.memory: 2Gi − 1536m heap ≈ 512m` на ОС и non-heap.
>
> Версию чарта уточняйте в [helm-chart-sonarqube](https://github.com/SonarSource/helm-chart-sonarqube) или через `helm search repo`; значения `sonarProperties`, `monitoringPasscode`, `caCerts`, `prometheusExporter.enabled` читайте в values.yaml соответствующей версии чарта.

#### Вариант D: Kubernetes (Argo CD Application)

Для GitOps-подхода с Argo CD SonarQube разворачывается через `Application` CR в неймспейсе `argocd`. Значения идентичны тем, что используются вручную через `helm install` (см. Вариант C).

```yaml
# argocd/projects/infra/applications/sonarqube.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sonarqube
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: infra
  source:
    repoURL: https:// SonarSource.github.io/helm-chart-sonarqube
    chart: sonarqube
    targetRevision: "2026.5.1001"
    helm:
      values: |
        community:
          enabled: true
          buildNumber: "26.10.0.133078"
        jdbcOverwrite:
          enabled: true
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
        env:
          - name: SONAR_WEB_JAVAOPTS
            value: "-Xms512m -Xmx1536m"
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
  destination:
    server: https://kubernetes.default.svc
    namespace: infra
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

> **Важно:** в Arаrgo CD секретные значения (например, `${SONAR_DB_PASS}`) подставляются через `argocd-vault-plugin` или `External Secrets Operator`. Убедитесь, что `argocd-repo-server` имеет доступ к Vault или ESO синхронизирует секреты в неймспейс `infra` перед синхронизацией SonarQube.

**Установка через CLI:**

```bash
# Добавление Helm-репозитория в Argo CD
argocd repo add https:// SonarSource.github.io/helm-chart-sonarqube

# Создание Application
argocd app create sonarqube \
  --repo https:// SonarSource.github.io/helm-chart-sonarqube \
  --chart sonarqube \
  --revision 2026.5.1001 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace infra \
  --helm-set community.enabled=true \
  --helm-set community.buildNumber=26.10.0.133078 \
  --set jdbcOverwrite.enabled=true \
  --set jdbcOverwrite.jdbcUrl="jdbc:postgresql://postgres.infra.svc.cluster.local:5432/sonarqube" \
  --set jdbcOverwrite.jdbcUsername=sonarqube \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# Синхронизация
argocd app sync sonarqube
```

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
        key: infra/sonarqube
        property: db_password
    - secretKey: SONAR_GITLAB_APP_ID
      remoteRef:
        key: infra/sonarqube
        property: gitlab_app_id
    - secretKey: SONAR_GITLAB_SECRET
      remoteRef:
        key: infra/sonarqube
        property: gitlab_secret
```

##### Настройка OIDC с GitLab

Перед деплоем создайте GitLab Application (`GitLab → Admin Area → Applications → New Application`):

| Поле | Значение |
| :--- | :--- |
| Name | SonarQube |
| Redirect URI | `https://sonarqube.example.com/oauth2/callback/gitlab` |
| Scopes | `read_user`, `api` |

Сохраните Application ID и Secret в Vault:

```bash
vault kv put secret/infra/sonarqube \
  gitlab_app_id=YOUR_APP_ID \
  gitlab_secret=YOUR_SECRET \
  db_password=POSTGRES_PASS
```

### Настройка проекта в SonarQube

1. **Создание проекта:**
   ```bash
   curl -u admin:$SONAR_ADMIN_PASS \
     -X POST "https://sonarqube.example.com/api/projects/create" \
     -d "name=myproject&project=mygroup_myproject&visibility=private"
   ```
   Ключ проекта (`project=`) может содержать буквы, цифры, дефисы, подчёркивания, точки и двоеточия (до 400 символов, минимум один нецифровой символ) — поэтому моно-репозитории удобно размечать ключами вида `mygroup_myproject:backend`.

2. **Генерация токена:**
   - UI: `My Account → Security → Generate Tokens`; для CI предпочтителен тип **Project Analysis Token** (привязка к одному проекту)
   - Или API:
     ```bash
     curl -u admin:$SONAR_ADMIN_PASS \
       -X POST "https://sonarqube.example.com/api/user_tokens/generate?name=gitlab-ci" \
       -d "type=PROJECT_ANALYSIS_TOKEN&project=mygroup_myproject"
     ```

3. **Настройка Quality Gate:**
   - UI: `Quality Gates → Create` или используйте встроенный `Sonar way`
   - Условия настраиваются на New Code (по умолчанию): покрытие нового кода, дублирование нового кода, новые баги/уязвимости, рейтинги на новом коде (см. таблицу в разделе «Quality Gate условия»)
   - Назначьте QG проекту: `Quality Gates → ... → Set as default`, либо через API `api/qualitygates/select`

4. **Настройка Quality Profile:**
   - UI: `Quality Profiles → Set as default` для каждого языка проекта
   - Импортируйте кастомные правила при необходимости; конфигурацию QP версионируйте экспортом (см. «Крайние случаи → Версионный drift Quality Profiles»)

## Конфигурация

### Основные концепции

#### Архитектура интеграции GitLab CI + SonarQube

```
Push / MR → GitLab CI Pipeline
  ├── test (unit tests + coverage)
  │   └── Генерация coverage report (JaCoCo, coverage.py, lcov, dotnet-coverage)
  ├── sonar_scan
  │   ├── Запуск SonarScanner в изолированном контейнере
  │   ├── Отправка исходного кода и coverage report в SonarQube
  │   ├── Ожидание Compute Engine и Quality Gate (sonar.qualitygate.wait=true)
  │   └── Job падает, если Quality Gate = ERROR
  └── sonar_comment (опционально, Community Build)
      └── Публикация метрик в MR через GitLab API
```

#### Сравнение инструментов анализа кода

| Инструмент | Тип | Языки | Quality Gate | Интеграция с GitLab |
| :--- | :--- | :--- | :--- | :--- |
| **SonarQube (self-hosted)** | SAST + метрики | 25+ | Да | Да (SonarScanner + API; декорация MR в Server) |
| **SonarCloud** | SaaS SonarQube | 25+ | Да | Да (native GitLab integration) |
| **Codecov** | Coverage | Мультиязычный | Нет | Да (через API) |
| **Code Climate** | SAST + coverage | Мультиязычный | Да | Да (через API) |

Подробное сравнение редакций и альтернатив — в [SonarQube (Tools)](../../Tools/sonarqube.md); интеграция статического анализа в пайплайн в целом — в [SAST](../../DevSecOps/sast_overview.md).

#### Quality Gate условия

Quality Gate по умолчанию строится вокруг New Code: критерий — не ухудшать уже накопленное качество. Типовые условия (пороги настраиваются под команду):

| Условие (New Code) | Ключ метрики | Пример порога |
| :--- | :--- | :--- |
| **Coverage on New Code** | `new_coverage` | < 80% → FAIL |
| **Duplicated Lines on New Code** | `new_duplicated_lines_density` | > 3% → FAIL |
| **Reliability Rating on New Code** | `new_reliability_rating` | worse than A (значение > 1) → FAIL |
| **Security Rating on New Code** | `new_security_rating` | worse than A (значение > 1) → FAIL |
| **Maintainability Rating on New Code** | `new_maintainability_rating` | worse than A (значение > 1) → FAIL |
| **New Bugs** | `new_bugs` | > 0 → FAIL |
| **New Vulnerabilities** | `new_vulnerabilities` | > 0 → FAIL |

Условия по всему коду («Coverage», «Duplicated Lines», «Reliability Rating» без префикса New) тоже доступны, но противоречат идее Clean as You Code: они блокируют merge из-за старого кода, над которым команда сейчас не работает.

#### Механизм PR Decoration

Developer/Enterprise отправляет комментарии в MR (требуется DevOps-интеграция, см. сценарий 2):

1. GitLab шлёт событие (webhook/событие пайплайна) в SonarQube; сканер в GitLab CI дополнительно автоопределяет MR/ветку по переменным окружения
2. Compute Engine завершает обработку анализа и вычисляет Quality Gate
3. SonarQube публикует комментарий в MR через GitLab API (токен интеграции со скоупом `api`)
4. В MR появляется блок: статус QG, метрики coverage, bugs, vulnerabilities

> **Важно:** декорация MR — информационная. Сама по себе она не блокирует merge: для блокировки нужен failing pipeline + Merge Checks в GitLab (см. сценарий 4).

### Параметры анализа и переменные окружения

Сканер читает параметры из `-D...` либо из одноимённых переменных окружения — в CI удобнее задавать `SONAR_TOKEN` и `SONAR_HOST_URL` как CI/CD-переменные и не дублировать их в `script`.

| Переменная окружения / параметр | Описание | Обязательность |
| :--- | :--- | :--- |
| `SONAR_HOST_URL` (`-Dsonar.host.url`) | URL SonarQube Server | Да |
| `SONAR_TOKEN` (`-Dsonar.token`) | Токен с правом `Execute Analysis`. `sonar.login` устарел и не должен использоваться | Да |
| `SONAR_USER_HOME` (`-Dsonar.userHome`) | Базовый каталог сканера; кэш анализа лежит в `$SONAR_USER_HOME/cache` (по умолчанию `~/.sonar`) | Нет (в CI задаётся для кэширования) |
| `SONAR_SCANNER_JAVA_OPTS` (`-Dsonar.scanner.javaOpts`) | Аргументы JVM процесса сканера (SonarScanner CLI 6.0+), например `-Xmx2g` | Нет |
| `sonar.qualitygate.wait` | Дождаться результата Quality Gate и завершить job с ошибкой при FAIL (по умолчанию `false`) | Рекомендуется |
| `sonar.qualitygate.timeout` | Сколько секунд сканер ждёт обработки анализа (по умолчанию `300`) | Нет |
| `sonar.exclusions` | Паттерны исключаемых файлов, например `**/bin/**,**/obj/**,**/node_modules/**` | Нет |
| `SONAR_JDBC_URL` | JDBC URL для внешней БД (секция сервера, не сканера) | Нет (H2 по умолчанию) |

Параметры `sonar.organization` и `sonar.gitlab.*` (legacy community-плагин) к self-hosted SonarQube не относятся и не используются.

### Шаблоны .gitlab-ci.yml

```yaml
stages:
  - test
  - sonar_scan

variables:
  SONAR_HOST_URL: "https://sonarqube.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"

test:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pytest --cov=src --cov-report=xml:coverage.xml
  artifacts:
    paths:
      - coverage.xml
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 week

sonar_scan:
  stage: sonar_scan
  image:
    name: sonarsource/sonar-scanner-cli:12
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"                    # полная история — для git blame
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  cache:
    key: "sonar-${CI_JOB_NAME_SLUG}"
    paths:
      - .sonar/cache
  script:
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY"
        -Dsonar.sources=src/
        -Dsonar.coverage.jacoco.xmlReportPaths=coverage.xml
        -Dsonar.qualitygate.wait=true
        -Dsonar.qualitygate.timeout=300
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "src/**/*"
        - "*.py"
        - "*.js"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes:
        - "src/**/*"
        - "*.py"
        - "*.js"
```

Пояснения:

- `SONAR_TOKEN` и `SONAR_HOST_URL` передаются как CI/CD-переменные; сканер подхватывает их автоматически. Явный `-Dsonar.token="$SONAR_TOKEN"` допустим, если хотите зафиксировать параметр в YAML.
- `entrypoint: [""]` отключает встроенный entrypoint образа — так же поступает официальный пример интеграции.
- `GIT_DEPTH: "0"` — без полной истории blame-данные неполные, и SonarQube сообщает «Missing blame information».
- `SONAR_USER_HOME` + `cache.paths: .sonar/cache` — иначе кэш сканера (включая кэш инкрементального анализа) пишется в домашний каталог контейнера и не переживает job.
- `sonar.qualitygate.wait=true` — официальный механизм: сканер опрашивает SonarQube и валит job при ERROR Quality Gate. Отдельный polling-job с curl/jq для блокировки merge не нужен.
- `-Dsonar.coverage.jacoco.xmlReportPaths=coverage.xml` указывается только если coverage отчёты попали в job; для этого файл добавлен в `artifacts:paths`.

## Практические сценарии

### Сценарий 1: Базовая интеграция с SonarQube Community Build

**Установка SonarScanner:**
```bash
# Вариант 1: Docker (рекомендуется для CI)
docker run --rm \
  -e SONAR_TOKEN -e SONAR_HOST_URL \
  -v "${HOME}/.sonar/cache:/root/.sonar/cache" \
  -v "${PWD}:/usr/src" \
  sonarsource/sonar-scanner-cli:12

# Вариант 2: zip-дистрибутив SonarScanner CLI
# (https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/)
```

**Вариант A: Прямой запуск SonarScanner (без GitLab CI)**
```bash
sonar-scanner \
  -Dsonar.projectKey=mygroup_myproject \
  -Dsonar.sources=src/ \
  -Dsonar.host.url=https://sonarqube.example.com \
  -Dsonar.token="$SONAR_TOKEN"
```

**Вариант B: GitLab CI (.gitlab-ci.yml)** — используйте шаблон из раздела «Шаблоны .gitlab-ci.yml»: job `sonar_scan` с `sonar.qualitygate.wait=true` проверяет Quality Gate автоматически.

**Валидация:**
```bash
# Проверьте, что анализ завершён
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&ps=1" | jq '.tasks[0].status'
# → "SUCCESS"

# Проверьте Quality Gate
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" | jq '.projectStatus.status'
# → "OK"

# Ожидаемый результат:
# - job sonar_scan зелёный (сканер сам дождался QG)
# - projectStatus.status = "OK", все conditions[] со статусом "OK"
```

### Сценарий 2: SonarQube Developer/Enterprise (Branch Analysis + PR Decoration)

Предварительно настройте DevOps-интеграцию: `Administration → DevOps Platform Integrations → GitLab` — URL GitLab, Application ID/Secret (GitLab Application со скоупом `api`), затем `Project Settings → General Settings → Pull Request Decoration` — привязка к GitLab-проекту.

```yaml
variables:
  SONAR_HOST_URL: "https://sonarqube.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"

sonar_scan:
  stage: sonar_scan
  image:
    name: sonarsource/sonar-scanner-cli:12
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  cache:
    key: "sonar-${CI_JOB_NAME_SLUG}"
    paths:
      - .sonar/cache
  script:
    # В Developer/Enterprise при подключённой DevOps-интеграции сканер сам
    # определяет MR/ветку по переменным GitLab CI — отдельные параметры не нужны
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY"
        -Dsonar.sources=src/
        -Dsonar.coverage.jacoco.xmlReportPaths=coverage.xml
        -Dsonar.qualitygate.wait=true
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

Если автоопределение не срабатывает (нет привязки интеграции), передайте параметры MR явно:

```bash
-Dsonar.pullrequest.key="$CI_MERGE_REQUEST_IID" \
-Dsonar.pullrequest.branch="$CI_COMMIT_REF_NAME" \
-Dsonar.pullrequest.base="$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"
```

**Что даёт Developer/Enterprise:**
- Branch Analysis — отдельный анализ каждой ветки
- PR Decoration — автоматические комментарии и статус в MR
- Portfolio Management — агрегация метрик по нескольким проектам
- Дополнительные условия Quality Gate и расширенные правила

**Валидация:**
```bash
# Метрики ветки (Branch Analysis)
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&branch=$CI_COMMIT_REF_NAME&metricKeys=coverage,new_coverage,bugs,vulnerabilities" | jq '.component.measures'

# Метрики MR (PR Analysis)
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&pullRequest=$CI_MERGE_REQUEST_IID&metricKeys=coverage" | jq '.component.measures'

# Ожидаемый результат:
# - ответ содержит measures для запрошенной ветки/MR
# - в MR есть комментарий SonarQube со статусом Quality Gate
```

### Сценарий 3: Автоматический комментарий в Merge Request (Community Build)

В Community Build нет встроенного PR Decoration — комментарий можно публиковать кастомным job'ом. JSON формируйте через `jq` (конкатенация строк ломается на переносах и кавычках), а образ должен содержать и `curl`, и `jq`: в `curlimages/curl` jq отсутствует.

```yaml
sonar_comment:
  stage: sonar_scan
  image: alpine:3.20
  script:
    - apk add --no-cache curl jq
    - |
      STATUS=$(curl -s -u "$SONAR_TOKEN": \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')
      COVERAGE=$(curl -s -u "$SONAR_TOKEN": \
        "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=coverage" \
        | jq -r '.component.measures[] | select(.metric=="coverage") | .value // "n/a"')
      BUGS=$(curl -s -u "$SONAR_TOKEN": \
        "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=bugs" \
        | jq -r '.component.measures[] | select(.metric=="bugs") | .value // "n/a"')
      VULNERABILITIES=$(curl -s -u "$SONAR_TOKEN": \
        "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=vulnerabilities" \
        | jq -r '.component.measures[] | select(.metric=="vulnerabilities") | .value // "n/a"')

      BODY=$(jq -n \
        --arg status "$STATUS" \
        --arg coverage "$COVERAGE" \
        --arg bugs "$BUGS" \
        --arg vulns "$VULNERABILITIES" \
        --arg url "$SONAR_HOST_URL/dashboard?id=$SONAR_PROJECT_KEY" \
        '{
          body: ("## SonarQube Analysis\n\n"
                 + "**Quality Gate:** " + $status + "\n"
                 + "**Coverage:** " + $coverage + "%\n"
                 + "**Bugs:** " + $bugs + "\n"
                 + "**Vulnerabilities:** " + $vulns + "\n\n"
                 + "[View full report](" + $url + ")")
        }')

      curl -s --fail-with-body -X POST \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "$BODY" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"
  needs:
    - sonar_scan
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: true
```

**Валидация:**
```bash
# Проверьте, что комментарий создан
curl -s --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes" \
  | jq '.[].body' | grep -m1 "SonarQube Analysis"

# Ожидаемый результат:
# - в MR есть комментарий "SonarQube Analysis" с метриками и рабочей ссылкой
```

### Сценарий 4: Блокировка merge при failing Quality Gate

В GitLab нет раздела «Settings → CI/CD → Quality Gates». Блокировка собирается из двух частей:

1. **SonarQube:** действующий Quality Gate на проекте (условия на New Code).
2. **GitLab:** `Settings → Merge requests → Merge Checks → Pipelines must succeed` (галочка «Pipelines must succeed»). При необходимости добавьте MR approval rules.
3. **CI:** job `sonar_scan` с `-Dsonar.qualitygate.wait=true` и без `allow_failure` — при ERROR Quality Gate job падает, pipeline становится failed, и Merge Check блокирует merge.

```yaml
sonar_scan:
  stage: sonar_scan
  image:
    name: sonarsource/sonar-scanner-cli:12
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  script:
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY"
        -Dsonar.sources=src/
        -Dsonar.qualitygate.wait=true
        -Dsonar.qualitygate.timeout=600
  allow_failure: false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# 1. Создайте MR с умышленно failing QG (например, coverage нового кода ниже 80%)
# 2. Проверьте, что job sonar_scan упал с сообщением Quality Gate
# 3. Проверьте, что кнопка Merge заблокирована

# Ожидаемый результат:
# - Job status = failed, в логе сканера виден статус Quality Gate
# - Merge button отключена, подсказка: "The pipeline for this merge request failed"
```

### Сценарий 5: Multi-module проект (monorepo)

Ключи модулей через двоеточие (`mygroup_myproject:backend`) допустимы в SonarQube. Декорация MR для нескольких проектов из одного репозитория — функция Developer/Enterprise; в Community Build достаточно валидации QG по каждому модулю.

```yaml
variables:
  SONAR_PROJECT_KEY: "mygroup_myproject"

sonar_scan_backend:
  stage: sonar_scan
  image:
    name: sonarsource/sonar-scanner-cli:12
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  script:
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY:backend"
        -Dsonar.sources=backend/src/
        -Dsonar.coverage.jacoco.xmlReportPaths=backend/coverage.xml
        -Dsonar.qualitygate.wait=true
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "backend/**/*"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes:
        - "backend/**/*"

sonar_scan_frontend:
  stage: sonar_scan
  image:
    name: sonarsource/sonar-scanner-cli:12
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  script:
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY:frontend"
        -Dsonar.sources=frontend/src/
        -Dsonar.javascript.lcov.reportPaths=frontend/coverage/lcov.info
        -Dsonar.qualitygate.wait=true
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "frontend/**/*"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes:
        - "frontend/**/*"
```

Каждый job со своим `sonar.qualitygate.wait=true` проверяет QG своего модуля — отдельный aggregation-job не обязателен.

**Валидация:**
```bash
# Проверьте, что оба модуля проанализированы
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY:backend&metricKeys=coverage,bugs" | jq '.component.key'
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY:frontend&metricKeys=coverage,bugs" | jq '.component.key'

# Ожидаемый результат:
# - оба ключа возвращают measures
# - оба job зелёные (QG каждого модуля пройден)
```

### Сценарий 6: Air-gapped среда (внутренний registry, нет внешнего доступа)

**Предварительные требования:**
- SonarQube развёрнут внутри air-gapped сети
- GitLab Runner имеет доступ к SonarQube Server
- Образы SonarScanner и coverage-инструментов предзагружены во внутренний registry
- Для SonarQube с internal CA настроен truststore сканера

```yaml
variables:
  SONAR_HOST_URL: "https://sonarqube.internal.example.com"
  SONAR_PROJECT_KEY: "mygroup_myproject"
  INTERNAL_REGISTRY: "registry.internal.example.com:5000"

sonar_scan:
  stage: sonar_scan
  image:
    name: "${INTERNAL_REGISTRY}/sonarsource/sonar-scanner-cli:12"
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
    # Прокси, если SonarQube доступен только через корпоративный прокси:
    # SONAR_SCANNER_PROXY_HOST: "proxy.internal.example.com"
    # SONAR_SCANNER_PROXY_PORT: "3128"
  cache:
    key: "sonar-${CI_JOB_NAME_SLUG}"
    paths:
      - .sonar/cache
  script:
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY"
        -Dsonar.sources=src/
        -Dsonar.coverage.jacoco.xmlReportPaths=coverage.xml
        -Dsonar.qualitygate.wait=true
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Настройка сервера в air-gapped сети:**

```properties
# conf/sonar.properties — отключите отправку телеметрии наружу
sonar.telemetry.enable=false
```

- **Плагины:** скачайте `.jar` на машине с доступом в интернет (Marketplace в UI: `Administration → Marketplace`) и разместите в `extensions/plugins/` на сервере, затем перезапустите SonarQube.
- **Internal CA / self-signed:** сканер по умолчанию использует truststore `$SONAR_USER_HOME/ssl/truststore.p12` (параметры `sonar.scanner.truststorePath`, пароль по умолчанию `changeit`). Переведите сертификат CA в PKCS12 и положите в этот путь (в CI — монтируйте файл или встраивайте в образ).
- **Телеметрия и уведомления:** отключаются на сервере (см. выше); внешние webhook-уведомления просто не настраиваются.

**Валидация:**
```bash
# Runner может вытащить образ из внутреннего registry
docker pull registry.internal.example.com:5000/sonarsource/sonar-scanner-cli:12

# SonarQube отвечает (при internal CA — с CA, лежащим в системном truststore)
curl -s --cacert /etc/ssl/internal-ca.crt -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/system/status" | jq -r .status
# → "UP"

# Ожидаемый результат:
# - анализ завершается успешно, ошибок TLS нет
# - Quality Gate проверяется без внешнего доступа
```

### Сценарий 7: Разделение анализа и проверки Quality Gate

Иногда анализ нужно запускать автоматически, а решение о merge оставлять человеку: сканер отправляет результат без ожидания QG, а проверка выполняется отдельным manual-job'ом.

```yaml
sonar_scan:
  stage: sonar_scan
  image:
    name: sonarsource/sonar-scanner-cli:12
    entrypoint: [""]
  variables:
    GIT_DEPTH: "0"
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
  script:
    - sonar-scanner
        -Dsonar.projectKey="$SONAR_PROJECT_KEY"
        -Dsonar.sources=src/
        -Dsonar.qualitygate.wait=false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

quality_gate:
  stage: sonar_scan
  image: alpine:3.20
  script:
    - apk add --no-cache curl jq
    - |
      STATUS=$(curl -s -u "$SONAR_TOKEN": \
        "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
        | jq -r '.projectStatus.status')
      if [ "$STATUS" != "OK" ]; then
        echo "Quality Gate: $STATUS"
        curl -s -u "$SONAR_TOKEN": \
          "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" \
          | jq '.projectStatus.conditions'
        exit 1
      fi
  when: manual
  allow_failure: false
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Валидация:**
```bash
# 1. Создайте MR
# 2. sonar_scan завершится сразу после отправки анализа
# 3. quality_gate появится как manual job и проверит QG по ручному запуску

# Ожидаемый результат:
# - sonar_scan зелёный без ожидания Compute Engine
# - quality_gate виден в UI как manual job
```

## Валидация и проверка

### Базовые проверки

```bash
# 1. Проверка доступности SonarQube
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/system/status" | jq -r .status
# → "UP"

# 2. Проверка, что проект существует
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/projects/search?q=$SONAR_PROJECT_KEY" | jq -r '.components[0].key'
# → "mygroup_myproject"

# 3. Проверка Quality Profile для языка
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/qualityprofiles/search?project=$SONAR_PROJECT_KEY" | jq '.profiles[].name'
# → ["Sonar way", ...]
```

### Продвинутые проверки

```bash
# 4. Проверка статуса последней задачи Compute Engine
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&ps=1" | jq '.tasks[0].status'
# → "SUCCESS"

# 5. Проверка метрик (ветка MR или ветки — только Developer/Enterprise)
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=coverage,bugs,vulnerabilities,code_smells" | jq '.component.measures'
# → [{"metric":"coverage","value":"85.5"}, ...]

# 6. Проверка Quality Gate с учётом ветки (DE+)
curl -u "$SONAR_TOKEN": \
  "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY&branch=$CI_COMMIT_REF_NAME" | jq '.projectStatus.status'
# → "OK"
```

### Ожидаемые результаты по сценариям

| Сценарий | Критерий успеха |
| :--- | :--- |
| **1: Базовая интеграция** | Анализ завершён, QG = OK, coverage отображается в SonarQube |
| **2: Developer/Enterprise** | Branch Analysis работает, PR Decoration опубликован в MR |
| **3: Комментарий в MR** | Комментарий с метриками создан в MR |
| **4: Блокировка merge** | Merge button отключена при failing QG |
| **5: Multi-module** | Оба модуля проанализированы, QG пройден для каждого |
| **6: Air-gapped** | Анализ работает без внешнего доступа, образы из внутреннего registry |
| **7: Разделение QG** | sonar_scan завершается сразу, quality_gate = manual |

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
docker compose stop sonarqube
# Или
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh stop
```

### Управление проектами и токенами

```bash
# Создание проекта
curl -u admin:$SONAR_ADMIN_PASS \
  -X POST "$SONAR_HOST_URL/api/projects/create" \
  -d "name=myproject&project=mygroup_myproject"

# Генерация токена
curl -u admin:$SONAR_ADMIN_PASS \
  -X POST "$SONAR_HOST_URL/api/user_tokens/generate?name=gitlab-ci" \
  -d "type=PROJECT_ANALYSIS_TOKEN&project=mygroup_myproject"

# Отзыв токена — по имени токена (значение токена API не принимает)
curl -u admin:$SONAR_ADMIN_PASS \
  -X POST "$SONAR_HOST_URL/api/user_tokens/revoke" \
  -d "name=gitlab-ci"
# Для чужого токена добавьте login владельца: -d "name=gitlab-ci&login=ci-bot"

# Удаление проекта
curl -u admin:$SONAR_ADMIN_PASS \
  -X POST "$SONAR_HOST_URL/api/projects/delete" \
  -d "project=mygroup_myproject"

# Список проектов
curl -u admin:$SONAR_ADMIN_PASS "$SONAR_HOST_URL/api/projects/search" | jq '.components[].key'
```

### Управление Quality Gates

```bash
# Список Quality Gates
curl -u admin:$SONAR_ADMIN_PASS "$SONAR_HOST_URL/api/qualitygates/search" | jq '.qualitygates[].name'

# Получение условий QG
curl -u admin:$SONAR_ADMIN_PASS "$SONAR_HOST_URL/api/qualitygates/get?name=Sonar%20Way" | jq '.conditions'

# Назначение QG проекту
curl -u admin:$SONAR_ADMIN_PASS \
  -X POST "$SONAR_HOST_URL/api/qualitygates/select" \
  -d "gateName=Sonar%20Way&projectKey=mygroup_myproject"

# Добавление условия в QG (op: GREAT_THAN / LESS_THAN / worse_than / etc.)
curl -u admin:$SONAR_ADMIN_PASS \
  -X POST "$SONAR_HOST_URL/api/qualitygates/create_condition" \
  -d "gateName=Sonar%20Way&metric=new_coverage&op=LT&error=80"
```

### Управление анализами

```bash
# Статус последней задачи Compute Engine
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/ce/activity?component=$SONAR_PROJECT_KEY&ps=1" | jq '.tasks[0]'

# Детали конкретной задачи
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/ce/task?id=TASK_ID" | jq '.task | {id,status,submittedAt,executedAt}'

# Quality Gate последнего анализа
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=$SONAR_PROJECT_KEY" | jq '.projectStatus'

# Метрики
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/measures/component?component=$SONAR_PROJECT_KEY&metricKeys=coverage,bugs,vulnerabilities,code_smells,duplicated_lines_density" | jq '.component.measures'

# Issues
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/issues/search?componentKeys=$SONAR_PROJECT_KEY&ps=10" | jq '.issues[] | {key, severity, type, message}'

# Принудительного «rerun» анализа SonarQube не имеет:
# достаточно повторного анализа той же ревизии (push / re-run job)
```

### Предзагрузка образов и кастомный CI-образ

```bash
# Продвижение образа сканера во внутренний registry
docker pull sonarsource/sonar-scanner-cli:12
docker tag sonarsource/sonar-scanner-cli:12 \
  registry.internal.example.com:5000/sonarsource/sonar-scanner-cli:12
docker push registry.internal.example.com:5000/sonarsource/sonar-scanner-cli:12
```

```dockerfile
# Кастомный образ на базе SonarScanner CLI.
# Внимание: официальный образ построен на Amazon Corretto (AL2023) —
# пакетный менеджер dnf, не apt/apk; базовый пользователь — UID 1000.
FROM sonarsource/sonar-scanner-cli:12

USER root
RUN dnf install -y jq python3 nodejs npm \
  && dnf clean all \
  && npm install -g nyc
USER 1000
```

## Крайние случаи (Edge Cases)

### Air-gapped среда

**Проблема:** SonarQube и Runner'ы не имеют доступа к интернету.

**Решение:** см. сценарий 6 — внутренний registry, offline-установка плагинов, `sonar.telemetry.enable=false`, truststore для internal CA, прокси-параметры сканера.

### Network partitions и потеря связи

**Проблема:** Runner не может достичь SonarQube Server.

**Решение:**
1. Настройте health check в CI job с retries:
   ```bash
   for i in 1 2 3 4 5; do
     curl -sf -o /dev/null "$SONAR_HOST_URL/api/system/status" && break
     sleep 10
   done
   ```
2. Для анализа без жёсткой зависимости используйте `sonar.qualitygate.wait=false` + отдельный manual-job (сценарий 7). Не помечайте анализ как `allow_failure: true`, если merge должен блокироваться при недоступности SonarQube.
3. Настройте алерты на недоступность SonarQube (см. «Настройка мониторинга (SRE)»).

### H2 Database в production

**Проблема:** SonarQube использует встроенную H2 вместо PostgreSQL.

**Решение:**
1. H2 — встроенная БД «для тестов и evaluation»; в production сразу разворачивайте PostgreSQL ([Installing the database](https://docs.sonarsource.com/sonarqube-server/server-installation/installing-the-database.md)).
2. Прямой перенос данных из H2 в другую СУБД штатной командой не выполняется. Путаницу вносят два разных механизма:
   - `api/system/migrate_db` запускает миграцию **схемы БД** при обновлении версии SonarQube (в т.ч. из safe mode) — это не «перенос между СУБД» и не «очистка кэша»;
   - подкоманды `sonar.sh migrate-db` не существует: миграция схемы выполняется автоматически при старте сервера.
3. Поддерживаемый путь переноса между разными СУБД — [DB Copy Tool (Migrating database)](https://docs.sonarsource.com/sonarqube-server/server-update-and-maintenance/maintenance/sonarqube-db-copy-tool.md); поддержка H2 в качестве исходной СУБД документацией не подтверждается — согласуйте такой сценарий с Sonar Support.
4. Если данные не критичны (например, H2 использовался для evaluation): разверните чистый инстанс на PostgreSQL, пересоздайте проекты и Quality Gates, перенесите Quality Profiles через `api/qualityprofiles/export` + `api/qualityprofiles/restore`, затем запустите анализ заново.

### Fork pipelines и untrusted код

**Проблема:** анализы из fork'ов перегружают SonarQube и расходуют токен.

**Решение:**
1. `SONAR_TOKEN` — protected + masked: защищённые переменные не передаются в пайплайны из fork'ов. Добавьте явное пропускание запуска без токена:
   ```yaml
   sonar_scan:
     rules:
       # В fork-pipeline токена нет — анализ не запускаем
       - if: $SONAR_TOKEN == null
         when: never
       - if: $CI_PIPELINE_SOURCE == "merge_request_event"
       - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
   ```
2. Ограничьте частоту фоновых задач в SonarQube: `Administration → Configuration → General Settings → Analysis → Background Tasks`.
3. Для публичных проектов дополнительно ограничьте SonarQube-анализ ролями: `Execute Analysis` выдаётся только trusted пользователям/группам.

### Исключения правил для legacy-кода

**Проблема:** в проекте есть legacy-области, чьи findings не должны блокировать merge.

**Решение:**
1. Настройте исключения на уровне проекта: `Project Settings → General Settings → Analysis Scope` (исключения файлов) и Issue Exclusions (`sonar.issue.ignore.multicriteria` — исключение конкретных правил из конкретных файлов/каталогов).
2. Держите проблемный код вне New Code: Quality Gate на новом коде не реагирует на старые findings.
3. Лицензирование кода SonarQube не проверяет — для анализа зависимостей и лицензий используйте SBoM-инструменты, см. [SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md).

### Версионный drift Quality Profiles

**Проблема:** Quality Profile устарел после обновления языка/правил.

**Решение:**
1. Регулярно обновляйте Quality Profiles (в UI у профиля появляется доступная новая версия правил).
2. Версионируйте конфигурацию QP в репозитории:
   ```bash
   curl -u admin:$SONAR_ADMIN_PASS \
     "$SONAR_HOST_URL/api/qualityprofiles/export?language=java&qualityProfile=Sonar%20way" > sonar-way-java.xml
   ```
3. Восстановление на новом инстансе: `api/qualityprofiles/restore` (multipart upload того же XML).

### Большие репозитории и таймауты

**Проблема:** анализ крупного проекта не укладывается в отведённое время.

**Решение:**
1. Увеличьте таймаут GitLab CI job:
   ```yaml
   sonar_scan:
     timeout: 60m
   ```
2. Увеличьте ожидание Quality Gate сканером (секунды, по умолчанию 300):
   ```bash
   -Dsonar.qualitygate.timeout=1800
   ```
   Параметр `sonar.ws.timeout` устарел и не должен использоваться.
3. Включите/сохраните кэш инкрементального анализа: серверный кэш анализа работает по умолчанию (отключается `sonar.analysisCache.enabled=false`); на стороне CI сохраняйте `$SONAR_USER_HOME/cache` через GitLab cache (см. шаблон). Кэш ветки обновляется при анализе ветки; для PR кэш подгружается, если целевая ветка анализировалась ранее ([Incremental analysis](https://docs.sonarsource.com/sonarqube-server/discovering/code-analysis/incremental-analysis.md)).
4. Исключите служебные каталоги: `-Dsonar.exclusions=**/bin/**,**/obj/**,**/node_modules/**,**/dist/**`.

### Cache invalidation и `GIT_DEPTH`

**Проблема:** SonarQube не получает корректные blame-данные из-за shallow clone.

**Решение:**
```yaml
sonar_scan:
  variables:
    GIT_DEPTH: "0"
    GIT_STRATEGY: clone
  script:
    - git fetch --unshallow || true
    - sonar-scanner ...
```

### Истечение срока действия SONAR_TOKEN

**Проблема:** `SONAR_TOKEN` истёк, анализ падает с 401 Unauthorized.

**Решение:**
1. Токены SonarQube имеют срок жизни; владелец получает email-уведомление SonarQube до истечения и после (настройки уведомлений — `My Account → Notifications`).
2. Ротация: сгенерируйте новый токен (имена токенов у пользователя должны быть уникальны — используйте суффикс даты), обновите CI/CD-переменную, затем отзовите старый:
   ```bash
   # новый токен
   curl -u admin:$SONAR_ADMIN_PASS \
     -X POST "$SONAR_HOST_URL/api/user_tokens/generate?name=gitlab-ci-2026-10" \
     -d "type=PROJECT_ANALYSIS_TOKEN&project=mygroup_myproject"

   # отзыв старого — по имени
   curl -u admin:$SONAR_ADMIN_PASS \
     -X POST "$SONAR_HOST_URL/api/user_tokens/revoke" -d "name=gitlab-ci"
   ```
3. Для CI используйте отдельного machine user с Project Analysis Token, чтобы ротация не задевала персональные токены разработчиков.

### Восстановление после сбоя Compute Engine

**Проблема:** Compute Engine завис, анализ не завершается.

**Решение:**
1. Проверьте статус задач:
   ```bash
   curl -u admin:$SONAR_ADMIN_PASS "$SONAR_HOST_URL/api/ce/activity?ps=10" \
     | jq '.tasks[] | select(.status == "FAILED" or .status == "IN_PROGRESS")'
   ```
2. Отмените зависшую задачу (параметр — `id`; отменяются только pending-задачи):
   ```bash
   curl -u admin:$SONAR_ADMIN_PASS -X POST "$SONAR_HOST_URL/api/ce/cancel?id=TASK_ID"
   # или разом:
   curl -u admin:$SONAR_ADMIN_PASS -X POST "$SONAR_HOST_URL/api/ce/cancel_all"
   ```
3. Перезапустите SonarQube (перезапуск web/CE не требует остановки всей инфраструктуры):
   ```bash
   docker compose restart sonarqube
   ```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` | Неверный или истёкший `SONAR_TOKEN`; параметр `sonar.login` больше не поддерживается | Используйте `sonar.token` / `SONAR_TOKEN`; проверьте токен в `My Account → Security` |
| `Project not found` | Проект не создан в SonarQube или токен привязан к другому проекту | Создайте проект (`api/projects/create`); для Project Analysis Token проверьте привязку |
| `Quality Gate is FAILED` | Не выполнены условия QG | Проверьте coverage, bugs, vulnerabilities в SonarQube по ветке/MR |
| `Coverage not reported` | Отчёт coverage не найден сканером | Проверьте путь к отчёту (`sonar.coverage.*.xmlReportPaths`, lcov, `dotnet-coverage`) и что файл попал в job |
| `PR Decoration not working` | Нет DevOps-интеграции/привязки проекта или нет прав токена в GitLab | Настройте `Administration → DevOps Platform Integrations → GitLab`; проверьте scope `api` у токена интеграции |
| `Analysis is stuck` | Долгий анализ или зависший Compute Engine | Проверьте `api/ce/activity`, логи `ce.log`, отмените задачу (`api/ce/cancel?id=`) |
| `Compute Engine out of memory` | Недостаточно RAM для SonarQube | Увеличьте память до 8+ GB, настройте `sonar.ce.javaOpts` |
| `Database connection refused` | PostgreSQL недоступен | Проверьте `SONAR_JDBC_URL`, сетевые политики, credentials |
| `jq: command not found` | Образ job'а без jq (`curlimages/curl` jq не содержит) | Используйте `alpine` + `apk add --no-cache curl jq` или кастомный образ |
| `Missing blame information` | Shallow clone, история неполная | `GIT_DEPTH: "0"`, при необходимости `git fetch --unshallow` |
| `Quality Gate timeout` | Compute Engine не уложился в ожидание сканера | Увеличьте `-Dsonar.qualitygate.timeout` (по умолчанию 300 с) и `timeout:` job'а |
| `PKIX path building failed` / TLS errors | Internal CA не в truststore сканера | Положите CA в `$SONAR_USER_HOME/ssl/truststore.p12` (см. сценарий 6) |
| `vm.max_map_count` / bootstrap check failed | Elasticsearch не стартует на хосте | `sysctl -w vm.max_map_count=262144` |

## Best Practices

### Разработка (Dev)

1. **Генерируйте coverage report для каждого языка:** JaCoCo (Java), coverage.py (Python), Istanbul/NYC (JS), `dotnet-coverage` (.NET).
2. **Настройте Quality Gate на New Code:** не блокируйте merge старыми findings (Clean as You Code).
3. **Используйте PR Decoration (Server):** автоматические комментарии в MR упрощают review.
4. **Настраивайте Quality Profile для каждого языка:** разные наборы правил для backend/frontend.
5. **Версионируйте Quality Profiles:** экспортируйте конфигурацию QP и храните в репозитории.
6. **Используйте `rules:changes`:** запускайте анализ только при изменении релевантных путей.
7. **Следите за New Code period:** период (дни/релиз) задаётся в проекте и напрямую влияет на поведение QG.

### Эксплуатация (DevOps/SRE)

1. **Блокируйте merge при failing QG:** `Settings → Merge requests → Merge Checks → Pipelines must succeed` + `sonar.qualitygate.wait=true` в scan-job.
2. **Мониторьте метрики SonarQube:** тренд coverage, технический долг, количество багов.
3. **Регулярно обновляйте правила:** Quality Profile должен актуализироваться под новые версии языков; обновляйте сам SonarQube до актуальной LTA.
4. **Используйте Branch Analysis:** отслеживайте качество кода в каждой ветке (Developer/Enterprise).
5. **Настройте алерты на ухудшение качества:** падение coverage на новом коде — сигнал в Slack/Telegram.
6. **Используйте PostgreSQL для production:** H2 не предназначен для production workloads.
7. **Настройте backup:** ежедневный бэкап PostgreSQL и экспорта конфигурации (QG/QP).
8. **Масштабируйте Compute Engine:** для большого числа проектов выделите отдельный узел CE с увеличенной памятью.

### Sysadmin

1. **Настройте retention:** Housekeeping (`Administration → Configuration → Housekeeping`) ограничивает хранение старых анализов.
2. **Ограничьте доступ к SonarQube:** `sonar.forceAuthentication=true`, роли и группы, reverse proxy с TLS.
3. **Используйте отдельный SonarQube для production:** изоляция данных.
4. **Резервное копирование:** регулярно бэкапите PostgreSQL (dump) и каталог конфигурации.
5. **Масштабируйте SonarQube:** для больших развёртываний — Data Center Edition.
6. **Настройте мониторинг:** `/api/monitoring/metrics` → Prometheus (см. ниже), алерты на статус web/CE и место на диске Elasticsearch.
7. **Используйте reverse proxy:** Nginx/Apache для TLS termination, gzip, access logs.
8. **Настройте firewall:** к SonarQube — только порт 9000 (или 443 за reverse proxy), к PostgreSQL — только с узла SonarQube.

### Настройка мониторинга (SRE)

SonarQube экспортирует Prometheus-метрики на `/api/monitoring/metrics` (с 9.3). Доступ защищён `sonar.web.systemPasscode` (задаётся в `conf/sonar.properties` или переменной `SONAR_WEB_SYSTEMPASSCODE`); клиент аутентифицируется заголовком `Authorization: Bearer <passcode>`.

```properties
# conf/sonar.properties на сервере SonarQube
sonar.web.systemPasscode=CHANGE_ME_STRONG_RANDOM
```

```yaml
# prometheus.yml
scrape_configs:
  - job_name: sonarqube
    metrics_path: /api/monitoring/metrics
    scheme: https
    tls_config:
      insecure_skip_verify: true   # только для self-signed; лучше добавить CA в truststore Prometheus
    authorization:
      type: Bearer
      credentials: "${SONAR_WEB_SYSTEMPASSCODE}"   # Prometheus 2.26+
    static_configs:
      - targets: ['sonarqube.example.com:443']
```

```yaml
# Пример правил алертинга; имена метрик сверьте со своим инстансом
# (откройте /api/monitoring/metrics и посмотрите фактические имена)
groups:
  - name: sonarqube
    rules:
      - alert: SonarQubeWebDown
        expr: sonarqube_health_web_status != 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SonarQube web недоступен"
      - alert: SonarQubeEsDiskUsageHigh
        expr: sonarqube_es_disk_usage_percent > 85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Высокое использование диска Elasticsearch SonarQube"
```

Для Kubernetes-развёртывания чарт SonarQube умеет поднимать sidecar/exporter: `prometheusExporter.enabled=true` + `monitoringPasscode` (см. values чарта).

## Очистка

### Удаление проекта

```bash
# Удаление проекта через API
curl -u admin:$SONAR_ADMIN_PASS -X POST "$SONAR_HOST_URL/api/projects/delete" \
  -d "project=mygroup_myproject"
```

### Отзыв токенов

```bash
# Отзыв по имени токена (значение токена API не принимает)
curl -u admin:$SONAR_ADMIN_PASS -X POST "$SONAR_HOST_URL/api/user_tokens/revoke" \
  -d "name=gitlab-ci"

# Список токенов пользователя (в т.ч. для инвентаризации перед ротацией)
curl -u "$SONAR_TOKEN": "$SONAR_HOST_URL/api/user_tokens/search" | jq '.userTokens[] | {name,type,createdAt,expiresAt}'
```

### Очистка старых анализов и задач

```bash
# Удаление конкретного анализа (нужен uuid анализа из api/project_analyses/search)
curl -u admin:$SONAR_ADMIN_PASS \
  "$SONAR_HOST_URL/api/project_analyses/search?project=$SONAR_PROJECT_KEY&ps=10" \
  | jq -r '.analyses[].analysis'
# → <uuid1> <uuid2> ...

curl -u admin:$SONAR_ADMIN_PASS -X POST \
  "$SONAR_HOST_URL/api/project_analyses/delete?analysis=ANALYSIS_UUID"

# Отмена зависших задач Compute Engine
for TASK_ID in $(curl -s -u admin:$SONAR_ADMIN_PASS "$SONAR_HOST_URL/api/ce/activity?ps=100" \
  | jq -r '.tasks[] | select(.status == "IN_PROGRESS") | .id'); do
  curl -u admin:$SONAR_ADMIN_PASS -X POST "$SONAR_HOST_URL/api/ce/cancel?id=$TASK_ID"
done
```

> **Примечание:** для автоматической очистки старых анализов настройте Housekeeping: `Administration → Configuration → Housekeeping` (период хранения анализов и связанных данных). Отдельной команды «очистки очереди CE» нет — используются отмена задач (`api/ce/cancel`, `api/ce/cancel_all`) и Housekeeping.

### Очистка логов и временных файлов

```bash
# Docker Compose: удаление томов УДАЛЯЕТ БАЗУ ДАННЫХ — только для полного демонтажа
docker compose down -v        # уничтожает и postgres_data!
docker volume prune

# Standalone: остановите сервер, затем очистите логи/temp.
# Каталог data/ (данные Elasticsearch) не очищать — это потеря индекса и истории.
sudo -u sonar /opt/sonarqube/bin/linux-x86-64/sonar.sh stop
sudo -u sonar rm -rf /opt/sonarqube/logs/* /opt/sonarqube/temp/*
```

### Удаление неиспользуемых плагинов

```bash
# Удаляйте только конкретные плагины: каталог extensions/plugins содержит
# и встроенные анализаторы языков, удаление всех *.jar сломает анализ.
docker compose exec sonarqube rm -f /opt/sonarqube/extensions/plugins/unused-plugin.jar
docker compose restart sonarqube
```

## Дополнительная информация

### Связанные файлы

- **[SonarQube (Tools)](../../Tools/sonarqube.md)** — обзор платформы, редакции, метрики, SSoT по SonarQube
- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — общие принципы защиты CI/CD
- **[Policy-as-Code в GitLab CI](../Advanced/policy_as_code.md)** — OPA, Checkov, TFLint, Trivy
- **[SBOM и подпись артефактов](../Advanced/sbom_and_artifact_signing.md)** — Cosign, Sigstore, анализ лицензий зависимостей
- **[Security Scanning в GitLab CI](../Concepts/gitlab_ci_security_scanning.md)** — встроенные шаблоны безопасности GitLab
- **[Proxy и Air-Gapped GitLab CI/CD](../Tutorials/proxy_air_gapped_gitlab_ci.md)** — настройка прокси и air-gapped сред
- **[SAST](../../DevSecOps/sast_overview.md)** — место статического анализа в DevSecOps
- **[Метрики покрытия](../../../Testing/testing_coverage_metrics.md)** — coverage как метрика и её пороги
- **[gitlab_monorepo_ci](../Advanced/gitlab_monorepo_ci.md)** — CI-паттерны для монорепозиториев
- **[Мониторинг GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — мониторинг пайплайнов и раннеров

### Внешние ресурсы

- [SonarQube Server Documentation](https://docs.sonarsource.com/sonarqube-server/)
- [GitLab CI/CD integration](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/ci-integration/gitlab-ci-cd/)
- [Analysis parameters (not settable in the UI)](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/analysis-parameters/parameters-not-settable-in-ui.md) — `sonar.token`, `sonar.qualitygate.wait/timeout`
- [Incremental analysis](https://docs.sonarsource.com/sonarqube-server/discovering/code-analysis/incremental-analysis.md)
- [Installing the database](https://docs.sonarsource.com/sonarqube-server/server-installation/installing-the-database.md)
- [Web API](https://docs.sonarsource.com/sonarqube-server/extension-guide/web-api.md) — полный каталог endpoint'ов (Help → Web API на своём инстансе)
- [Helm chart for SonarQube](https://github.com/SonarSource/helm-chart-sonarqube)
- Docker images: [sonarqube](https://hub.docker.com/_/sonarqube), [sonarsource/sonar-scanner-cli](https://hub.docker.com/r/sonarsource/sonar-scanner-cli)
- [Distribution (zip-дистрибутивы)](https://binaries.sonarsource.com/Distribution/sonarqube/)

## Практика: .NET + dotnet-sonarscanner в GitLab CI

Данный раздел описывает рабочую настройку для .NET-проектов (микросервисов), когда несколько репозиториев на разных версиях .NET отправляют отчёты анализа в один экземпляр SonarQube.

Ключевые моменты:
- Кастомный CI-образ с предустановленными `dotnet-sonarscanner` и `dotnet-coverage` — исключает `dotnet tool install` при каждом запуске job.
- `GIT_DEPTH: "0"` и `GIT_STRATEGY: clone` — необходимы для корректной работы `git blame` в SonarQube.
- Выбор образа под версию .NET через `rules` + переменные.
- Сбор покрытия через `dotnet-coverage` (без `coverlet` package references).
- Сравнение дельты покрытия между MR и последним успешным пайплайном на базовой ветке (`cover_compare`).
- Интеграция с PR Decoration для отображения Quality Gate прямо в MR.

### Кастомный CI-образ для .NET + SonarScanner

Рекомендуется собирать собственный образ, в который уже включены глобально установленные инструменты анализа.

```dockerfile
FROM mcr.microsoft.com/dotnet/sdk:8.0

RUN dotnet tool install --global dotnet-sonarscanner \
 && dotnet tool install --global dotnet-coverage

ENV PATH="$PATH:/root/.dotnet/tools"
```

Под разные версии .NET собираются отдельные теги образа, например: `sonarqube:net6`, `sonarqube:net8`, `sonarqube:net10`. В GitLab CI нужный тег выбирается динамически.

### Job анализа для .NET-проекта

Ниже приведён типовой job `analysis` для запуска `dotnet-sonarscanner`.

```yaml
variables:
  DOCKER_NET_IMAGE: registry.example.com/ci-images/sonarqube:${DOCKER_NET_IMAGE_TAG}
  DOCKER_NET_IMAGE_TAG: net6   # значение по умолчанию

analysis:
  stage: sonarqube
  image: ${DOCKER_NET_IMAGE}
  variables:
    SONAR_USER_HOME: "${CI_PROJECT_DIR}/.sonar"
    GIT_STRATEGY: clone     # обязательно clone, не fetch
    GIT_DEPTH: "0"          # полная история для корректного git blame
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - .sonar/cache         # кэш SonarScanner
  script:
    - dotnet sonarscanner begin
        /k:"$SONAR_PROJECT"
        /d:sonar.token="$SONAR_TOKEN"
        /d:sonar.host.url="$SONAR_HOST_URL"
        /d:sonar.qualitygate.wait=true
        /d:sonar.cs.vscoveragexml.reportsPaths=coverage.xml
        /d:sonar.scm.provider=git
        /n:$CI_PROJECT_PATH_SLUG
    - dotnet nuget list source   # проверка доступных NuGet-источников
    - dotnet build --no-incremental src/
    # Для репозиториев с unit-тестами раскомментируйте сбор покрытия:
    # - dotnet-coverage collect "dotnet test src/ -c Release --no-build --filter Category!~IntegrationExternal" -f xml -o coverage.xml
    - dotnet sonarscanner end /d:sonar.token="$SONAR_TOKEN"
  allow_failure: true
  tags:
    - sonarqube              # раннер с доступом к SonarQube
```

**Пояснения:**

- `GIT_DEPTH: "0"` — без полной истории `git blame` даёт пропуски, из-за чего SonarQube сообщает `SCM blame information is missing` для строк, затронутых коммитами старше глубины клона.
- `GIT_STRATEGY: clone` — надёжнее, чем `fetch`, особенно при работе с shallow-клонами. При `fetch` углубление истории не всегда отрабатывает предсказуемо.
- `sonar.token` — предпочтительный параметр вместо устаревшего `sonar.login` (deprecated начиная с SonarQube 9.x; параметр упоминается только для обратной совместимости старых версий).
- `/d:sonar.qualitygate.wait=true` — делает то же, что и в шаблоне для сканера CLI: job падает при ERROR Quality Gate. Если Quality Gate должен проверяться отдельным job'ом (сценарий 7) — уберите параметр.
- `sonar.cs.vscoveragexml.reportsPaths=coverage.xml` — путь к XML-отчёту покрытия, формируемому `dotnet-coverage`.
- `SONAR_TOKEN` хранится в групповых/проектных CI-переменных GitLab с маскированием.

### Выбор образа по проекту (rules)

Если в группе несколько сервисов на разных версиях .NET, можно переопределять `DOCKER_NET_IMAGE_TAG` через `rules`:

```yaml
rules:
  # Сервисы на .NET 8
  - if: $CI_PROJECT_PATH_SLUG =~ /^(my-api|other-service|third-service)/
    variables:
      DOCKER_NET_IMAGE_TAG: net8
  # .NET 10 для bleeding-edge проекта
  - if: $CI_PROJECT_PATH_SLUG == "my-new-api"
    variables:
      DOCKER_NET_IMAGE_TAG: net10
  # Запускать анализ только при пуше в dev
  - if: $CI_COMMIT_BRANCH == "dev"
  # Во всех остальных случаях не запускать
  - when: never
```

Такой подход позволяет держать один job `analysis`, избегая дублирования конфигурации. Частый приём — запускать SonarQube только на `dev` (или на `main` + MR), чтобы не плодить анализы по каждой feature-ветке.

### Сбор покрытия через dotnet-coverage

`dotnet-coverage` работает напрямую с `dotnet test` и **не требует** добавления `coverlet.collector`/`coverlet.msbuild` в тестовые проекты.

```bash
dotnet-coverage collect \
  "dotnet test src/ -c Release --no-build --filter Category!~IntegrationExternal" \
  -f xml -o coverage.xml
```

- `-f xml` — формат, совместимый с SonarQube
- `-o coverage.xml` — совпадает с `sonar.cs.vscoveragexml.reportsPaths`
- Фильтр `Category!~IntegrationExternal` позволяет исключить интеграционные тесты, которым для работы нужны внешние зависимости (БД, брокеры и др.)

Если в репозитории только unit-тесты — сбор покрытия можно смело включать. Если же есть тяжёлые интеграционные тесты — разумнее оставлять его закомментированным либо прогонять отдельным образом.

### Сравнение дельты покрытия в MR (cover_compare)

Отдельный скрытый job можно добавить для сравнения покрытия текущего MR с последним успешным пайплайном на базовой ветке. Это даёт быструю обратную связь без ожидания полного прохода Quality Gate в UI.

```yaml
.cover_compare:
  stage: cover_compare
  image: alpine:3.20
  script:
    - apk add --no-cache jq curl
    - |
      latest=$(curl -sH "PRIVATE-TOKEN: $ACCESS_TOKEN_READ" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID" \
        | jq -r '.coverage // "0"' | awk -F. '{print $1}')
    - |
      prev_id=$(curl -sH "PRIVATE-TOKEN: $ACCESS_TOKEN_READ" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipelines?ref=dev&status=success&per_page=1" \
        | jq -r '.[0].id')
      prev=$(curl -sH "PRIVATE-TOKEN: $ACCESS_TOKEN_READ" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipelines/$prev_id" \
        | jq -r '.coverage // "0"' | awk -F. '{print $1}')
    - |
      if [ "$latest" -ge "$prev" ]; then
        status="[OK] coverage ${latest}% >= ${prev}%"
      else
        status="[WARN] coverage dropped: ${latest}% < ${prev}%"
      fi
      curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" \
        -d text="${CI_PROJECT_PATH_SLUG}: ${status}"
  rules:
    - if: $CI_MERGE_REQUEST_ID
  allow_failure: true
  tags:
    - dind
```

**Требования:**
- `ACCESS_TOKEN_READ` — групповой токен GitLab со скоупом `read_api`. Достаточно для чтения метаданных пайплайнов, без доступа к коду.
- `TG_BOT_TOKEN`, `TG_CHAT_ID` — для уведомления в Telegram (при желании можно заменить на другой канал).
- `tags: - dind` — зависит от инфраструктуры раннеров; при использовании shell/kubernetes executor может отличаться.

> **Примечание:** GitLab API возвращает `coverage` в виде числа/строки (чаще с десятичной частью). В примере выше для сравнения берётся целая часть (`awk -F. '{print $1}'`). При желании можно сравнивать как числа с плавающей точкой.

### Именование проекта SonarQube

- `SONAR_PROJECT` — ключ проекта в SonarQube. Удобно использовать `company-backend-<service>` или совпадать с `CI_PROJECT_PATH_SLUG`. Ключ должен быть уникальным в рамках инстанса; допустимы буквы, цифры, дефис, подчёркивание, точка и двоеточие (до 400 символов, минимум один нецифровой символ) — поэтому `company/service:backend` тоже корректен.
- `/n:$CI_PROJECT_PATH_SLUG` — отображаемое имя проекта в UI SonarQube.

### PR Decoration и Quality Gate

Чтобы SonarQube автоматически оставлял комментарий со статусом Quality Gate в GitLab MR (Developer/Enterprise):

1. В SonarQube: `Administration → DevOps Platform Integrations → GitLab` — добавить URL GitLab и токен со скоупом `api`.
2. В проекте SonarQube: `Project Settings → General Settings → Pull Request Decoration` — выбрать соответствующий GitLab-проект.

После настройки декорирование срабатывает автоматически при анализе MR. Сам job `analysis` при этом может оставаться с `allow_failure: true` — сигналом для команды служит именно комментарий в MR и статус Quality Gate. Если merge нужно блокировать — используйте `sonar.qualitygate.wait=true` и Merge Checks (сценарий 4).

**Рекомендуемый Quality Gate (базовый):**
- Нет новых багов/уязвимостей критического/блокирующего уровня
- Покрытие нового кода ≥ 80% (настраивается под команду)
- Дублирование нового кода ≤ 3%
- Maintainability/Reliability/Security Rating на новом коде — не ниже B (чаще A)

## Типичные проблемы при интеграции .NET

| Проблема | Причина | Решение |
|---|---|---|
| `SCM blame information is missing` | `GIT_DEPTH` меньше `0`-эквивалента (shallow clone) | Добавить `GIT_DEPTH: "0"` в переменные job анализа |
| Анализ падает при `fetch`-стратегии | Некорректное углубление истории на shallow-клоне | Использовать `GIT_STRATEGY: clone` вместо `fetch` |
| SonarScanner не видит токен | Неправильное имя переменной/маскирование | Использовать `sonar.token="$SONAR_TOKEN"`. Для обратной совместимости старых версий можно временно `sonar.login`, но `sonar.token` предпочтителен |
| OOM при анализе крупных солюшенов | Малый heap JVM у SonarScanner | Добавить `SONAR_SCANNER_JAVA_OPTS: "-Xmx2g"` (и при необходимости больше) с учётом ресурсов раннера |
| Покрытие не подтягивается в SonarQube | Неверный путь/формат отчёта | Убедиться, что `coverage.xml` создан и путь совпадает с `sonar.cs.vscoveragexml.reportsPaths`. Также можно использовать glob: `**/coverage.xml` |
| Медленный анализ | Много файлов в `bin/`, `obj/`, `node_modules/` | Исключить через `sonar.exclusions=**/bin/**,**/obj/**,**/node_modules/**` при необходимости |
| Исключения не срабатывают | Ошибки в паттернах | Предпочитать `**/*.generated.cs` вместо `*.generated.cs` |
