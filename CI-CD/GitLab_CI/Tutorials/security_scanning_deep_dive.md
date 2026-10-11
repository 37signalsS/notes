# Security Scanning в GitLab CI/CD — глубинное погружение

**Актуально для:** GitLab 17.x–19.x, GitLab Runner 17.x–19.x

> **Примечание:** Базовая теория, архитектура, стандартные сценарии, troubleshooting и best practices описаны в **[Security Scanning в GitLab CI](../Concepts/gitlab_ci_security_scanning.md)**. Общие принципы hardening, защита Runner'ов, артефактов и supply chain — в **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)**. Это руководство фокусируется на продвинутых сценариях: polyglot-проекты, pre-commit hooks, multi-stage сборки, кастомные анализаторы и Kubernetes-интеграции.

## Определения

* **Polyglot Project** — проект, сочетающий несколько языков/фреймворков (например, Python backend + TypeScript frontend + Terraform), требующий запуска нескольких анализаторов SAST в одном пайплайне.
* **Custom SAST Analyzer** — пользовательский анализатор статического анализа, запускаемый как обычный CI job (Bandit, Semgrep с кастомными правилами, Brakeman и др.) и экспортирующий отчёт в формате `gl-sast-report.json`.
* **Pre-commit Hook** — локальный Git hook, выполняющий сканирование до создания коммита. В контексте GitLab CI работает как клиентская защита, дополняющая серверное Secret Detection.
* **Multi-stage Scan Target** — Docker-образ, собираемый через multi-stage build, где production-слой (финальный) сканируется отдельно от сборочных слоёв.
* **Analyzer Image Prefix** — префикс реестра для кастомных или закэшированных analyzer images, используемый в переменной `SAST_ANALYZER_IMAGE_PREFIX`.
* **License Policy** — набор правил (allow/deny), определяющих, какие лицензии зависимостей допустимы в production. Реализуется через License Scanning с кастомными конфигами.
* **Dependency Mirror** — локальная реплика внешнего registry (npm, PyPI, Maven), через которую проксируются запросы анализаторов зависимостей в air-gapped средах.
* **In-cluster DAST** — режим динамического сканирования, при котором ZAP-сканер запускается как pod внутри кластера Kubernetes и имеет прямой доступ к staging-сервисам через внутренний DNS.
* **Security Policy Project** — отдельный GitLab-проект, хранящий централизованные политики безопасности (Pipeline Execution Policies, approval rules), применяемые ко всей группе.
* **False Positive Allow-list** — список исключений (пути, регулярные выражения, finding IDs), suppressing не-уязвимые срабатывания сканеров без изменения исходного кода.

## Предварительные требования

| Роль | Требования |
|:---|:---|
| **Dev** | Знание синтаксиса `.gitlab-ci.yml`, lock-файлов зависимостей (`package-lock.json`, `poetry.lock`, `go.sum`); локальный Git и pre-commit hooks |
| **DevOps/SRE** | Доступ к GitLab Admin Area для настройки analyzer images, registry mirror и Pipeline Execution Policies; доступ к логам Runner'ов и GitLab; знание Docker Registry API |
| **Sysadmin** | Root-доступ к Runner хостам и GitLab Server; управление firewall, DNS, NTP; знание Docker daemon, registry (Harbor/Nexus/GitLab Container Registry), object store для артефактов |
| **Security Engineer** | Управление License Policies, VEX-отчётами, SBOM; настройка MR Approval Rules и Quality Gates; администрирование Security Dashboard |

**Инфраструктура:**
* GitLab CE/EE 17.x–19.x с включёнными Security features (SAST, DAST, Secret Detection, Dependency Scanning, Container Scanning, License Scanning)
* GitLab Runner 17.x–19.x (Docker executor для SaaS, Kubernetes executor для in-cluster DAST)
* Внутренний registry mirror для analyzer images и зависимостей (Harbor, Nexus, GitLab Container Registry)
* DNS и NTP синхронизация между GitLab Server, Runner'ами, registry и staging-окружениями
* Для in-cluster DAST: Kubernetes cluster с RBAC, ServiceAccount и NetworkPolicy, разрешающей egress к staging-сервисам
* Для pre-commit hooks: Python 3.9+ и `pre-commit` framework на рабочих станциях разработчиков
* Для air-gapped сред: offline bundle analyzer images и vulnerability databases (Grype/Trivy)

## Основные концепции

### Архитектура продвинутого security scanning

Продвинутые сценарии расширяют базовый shift-left подход кастомными анализаторами, multi-target сканированием и централизованной агрегацией отчётов.

```text
Developer Workstation
    └─ pre-commit hook (Secret Detection) → блокирует секрет до коммита

GitLab Pipeline
    ├─ build stage → Docker image
    ├─ test stage → unit/integration tests
    └─ security stage
        ├─ SAST → Semgrep + custom Bandit + custom Semgrep rules → gl-sast-report.json
        ├─ Secret Detection → GitLab Secret Detection → gl-secret-detection-report.json
        ├─ Dependency Scanning → Grype через private mirror → gl-dependency-scanning-report.json
        ├─ Container Scanning → Trivy на production-слой multi-stage → gl-container-scanning-report.json
        ├─ License Scanning → License Finder с allow/deny list → gl-license-report.json
        └─ DAST → OWASP ZAP in-cluster pod → gl-dast-report.json

Security Dashboard
    └─ Агрегация findings → MR Widget → Vulnerability Report → Approval Rules
```

### Жизненный цикл custom analyzer

```text
Push / Merge Request
    └─ Pipeline trigger
        └─ Security job с кастомным анализатором
            ├─ Pull analyzer image из registry mirror
            ├─ Mount исходного кода или артефакта
            ├─ Execute сканер с кастомными правилами
            ├─ Generate report в формате gl-*-report.json
            └─ Upload artifact с reports.type
                └─ GitLab parses findings → MR Widget / Security Dashboard
```

### Стратегии управления analyzer images

| Стратегия | Когда использовать | Описание |
|:---|:---|:---|
| **Default registry** | Онлайн-среды с доступом к registry.gitlab.com | GitLab автоматически подтягивает последние analyzer images |
| **Private mirror** | Self-hosted с ограниченным исходящим трафиком | Mirror analyzer images в корпоративный registry, переопределение через `SAST_ANALYZER_IMAGE_PREFIX` |
| **Custom analyzer** | Специфичные языки или внутренние стандарты | Запуск Bandit, Semgrep с custom rules, Brakeman как обычный CI job |
| **Air-gapped bundle** | Полностью изолированные сегменты | Предзагруженные analyzer images и vulnerability DB на Runner хосте |

### Интеграция pre-commit hooks с GitLab CI

Pre-commit hooks работают на стороне developer workstation до попадания кода в репозиторий. GitLab CI Secret Detection работает как второй уровень защиты на стороне сервера.

```text
Developer workstation
    └─ pre-commit hook (detect-secrets, gitleaks)
        ├─ Сканирование staged файлов
        ├─ Блокировка коммита при обнаружении секрета
        └─ Разрешение коммита при чистом коде
            └─ Push в GitLab
                └─ GitLab CI Secret Detection (серверный уровень)
                    ├─ Сканирование всей истории коммитов
                    ├─ Push protection (Premium/Ultimate)
                    └─ Pipeline job с отчётом
```

### License Compliance enforcement

License Scanning проверяет соответствие лицензий зависимостей корпоративной политике. Нарушения блокируют merge через MR Approval Rules или Quality Gates.

```text
Dependency Scanning (Grype)
    └─ License Finder / ScanCode
        └─ Сравнение с allow/deny list
            ├─ Allow (MIT, Apache-2.0) → OK
            ├─ Deny (GPL-3.0, AGPL) → BLOCK
            └─ Review (SSPL, unknown) → MANUAL approval required
                └─ MR Approval Rule → Security team review
```

### Multi-stage Container Scanning

Multi-stage Docker-образы содержат несколько слоёв: сборочные (builder) и production. Container Scanning должен анализировать только production-слой, чтобы не дублировать CVE из временных зависимостей.

```text
Dockerfile
    ├─ Stage 1: builder (сборочные зависимости)
    └─ Stage 2: production (финальный артефакт)
        └─ docker build --target production
            └─ trivy image production-image:tag
                └─ gl-container-scanning-report.json (только production CVE)
```

## Практические сценарии

### Сценарий 1: SAST для polyglot-проекта

Polyglot-проекты требуют запуска language-specific анализаторов параллельно с встроенным Semgrep.

```yaml
stages:
  - test
  - security

variables:
  SAST_EXCLUDED_PATHS: "spec/, test/, tests/, vendor/, .git/"
  SAST_ANALYZER_IMAGE_PREFIX: "registry.gitlab.example.com/security/analyzers/"
  SAST_ANALYZER_IMAGE_TAG: "4"

# Встроенный SAST (Semgrep)
sast:
  stage: security
  include:
    - template: Security/SAST.gitlab-ci.yml
  variables:
    SEARCH_MAX_DEPTH: 5
    SCAN_KUBERNETES_MANIFESTS: "true"
    SCAN_TERRAFORM_PLAN: "true"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Кастомный SAST для Python (Bandit)
bandit-sast:
  stage: security
  image: python:3.13-slim
  script:
    - pip install --no-cache-dir bandit[toml]
    - bandit -r src/ -f json -o bandit-report.json || true
  artifacts:
    reports:
      sast: bandit-report.json
    paths:
      - bandit-report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "**/*.py"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Кастомный SAST для TypeScript/JavaScript (Semgrep с кастомными правилами)
semgrep-custom:
  stage: security
  image: registry.gitlab.example.com/security/analyzers/sast:4
  script:
    - semgrep --config=auto --json --output=semgrep-report.json src/
  artifacts:
    reports:
      sast: semgrep-report.json
    paths:
      - semgrep-report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "**/*.ts"
        - "**/*.js"
        - "**/*.tsx"
        - "**/*.jsx"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# 1. Bandit report отображается в MR Widget (вкладка Security)
# 2. При изменении Python-файла запускается только bandit-sast
# 3. При изменении TS-файла запускается только semgrep-custom
# 4. При изменении обоих типов запускаются оба параллельно
# 5. В MR видны findings с severity High/Critical от Bandit
```

### Сценарий 2: Secret Detection в pre-commit и CI

Двухуровневая защита: локальный hook блокирует секрет до коммита, GitLab CI Secret Detection проверяет историю на стороне сервера.

```yaml
stages:
  - security

variables:
  SECRET_DETECTION_HISTORIC_SCAN: "true"
  SECRET_DETECTION_EXCLUDED_PATHS: "*.md, *.txt, docs/, .git/, *.example"
  SECRET_DETECTION_GIT_DIFF_MAX_FILES: 100

secret_detection:
  stage: security
  include:
    - template: Security/Secret-Detection.gitlab-ci.yml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "**/*"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false
  artifacts:
    reports:
      secret_detection: gl-secret-detection-report.json
    paths:
      - gl-secret-detection-report.json
```

Локальный pre-commit hook (`.pre-commit-config.yaml`):
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.0
    hooks:
      - id: gitleaks
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

**Валидация:**
```bash
# 1. Локально: git commit с секретом блокируется gitleaks
# 2. В CI: Secret Detection пайплайна падает при наличии секрета в истории
# 3. В MR: finding отображается на вкладке Security
# 4. Push protection блокирует push с секретом (Premium/Ultimate)
# 5. Исключения (*.example, *.md) не триггеруют scanner
```

### Сценарий 3: Container Scanning для multi-stage сборки

Сканирование только production-слоя multi-stage Docker-образа.

```yaml
stages:
  - build
  - security
  - deploy

variables:
  DOCKER_BUILDKIT: "1"

build_image:
  stage: build
  image: docker:27
  services:
    - docker:27-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build --target production -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

container_scanning:
  stage: security
  include:
    - template: Security/Container-Scanning.gitlab-ci.yml
  variables:
    CS_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  dependencies:
    - build_image
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
```bash
# 1. Dockerfile содержит --target production
# 2. CS_IMAGE указывает на production-образ (не builder)
# 3. gl-container-scanning-report.json содержит CVE только production-слоя
# 4. При Critical CVE pipeline падает (allow_failure: false)
# 5. В MR видны Container Scanning findings
```

### Сценарий 4: DAST для Kubernetes с in-cluster scanning

DAST-сканер (OWASP ZAP) запускается как pod внутри кластера, используя внутренний Service Account и NetworkPolicy.

```yaml
stages:
  - deploy
  - dast

deploy_staging:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - kubectl apply -f k8s/staging/
    - kubectl rollout status deployment/myapp -n staging --timeout=300s
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

dast:
  stage: dast
  include:
    - template: Security/DAST.gitlab-ci.yml
  variables:
    DAST_WEBSITE: https://staging.example.com
    DAST_BRANCH: main
    DAST_FULL_SCAN_ENABLED: "true"
    DAST_ZAP_IMAGE: "registry.gitlab.example.com/security/analyzers/dast:4"
    DAST_INCLUDE_HOSTS: "staging.example.com,api.staging.example.com"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: true
  artifacts:
    reports:
      dast: gl-dast-report.json
    paths:
      - gl-dast-report.json
```

Kubernetes RBAC для DAST scanner:
```yaml
# k8s/staging/dast-scanner-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dast-scanner
  namespace: staging
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: dast-scanner
  namespace: staging
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints"]
    verbs: ["get", "list"]
---
apiVersion: v1
kind: Pod
metadata:
  name: dast-scanner
  namespace: staging
spec:
  serviceAccountName: dast-scanner
  containers:
    - name: zap
      image: registry.gitlab.example.com/security/analyzers/dast:4
      command: ["zap.sh", "-daemon", "-host", "0.0.0.0", "-port", "8080"]
      ports:
        - containerPort: 8080
```

**Валидация:**
```bash
# 1. Staging развёрнут и доступен через https://staging.example.com
# 2. DAST scanner pod имеет ServiceAccount сRole для чтения services/endpoints
# 3. NetworkPolicy разрешает egress к staging.example.com (443)
# 4. gl-dast-report.json содержит findings (SQL injection, XSS, CSRF)
# 5. В MR видны DAST findings (если allow_failure: false)
```

### Сценарий 5: License Scanning с кастомными allow/deny политиками

Принудительное соблюдение лицензионной политики с блокировкой merge при нарушении.

```yaml
stages:
  - security

variables:
  LICENSE_CHECKSUM: "true"
  LICENSE_EXCLUDED_PATHS: "vendor/, node_modules/, *.min.js"

license_scanning:
  stage: security
  include:
    - template: Security/License-Scanning.gitlab-ci.yml
  variables:
    LICENSE_ALLOWLIST: '["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]'
    LICENSE_DENYLIST: '["GPL-3.0", "AGPL-3.0", "SSPL-1.0"]'
    LICENSE_REVIEWLIST: '["LGPL-3.0", "MPL-2.0", "EPL-2.0"]'
  script:
    - |
      # Кастомная проверка License Scanning через License Finder
      bundle config set --local path 'vendor/bundle'
      bundle exec license_finder --format json --output license-report.json
  artifacts:
    reports:
      license_scanning: gl-license-report.json
    paths:
      - gl-license-report.json
      - license-report.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: false
```

MR Approval Rule для License Scanning:
```yaml
# В Security policy проекте (.gitlab/security-policies.yml)
approval_rules:
  - name: "License Compliance Review"
    type: "regular"
    approvals_required: 1
    rule_attributes:
      scan_result_policies:
        - name: "Block deny-list licenses"
          scan_type: "license_scanning"
          policy_type: "approval"
          attributes:
            license_denylist:
              - "GPL-3.0"
              - "AGPL-3.0"
              - "SSPL-1.0"
```

**Валидация:**
```bash
# 1. gl-license-report.json содержит список всех зависимостей и их лицензий
# 2. При наличии deny-list лицензии pipeline падает
# 3. При наличии review-list лицензии MR требует approval от legal/security team
# 4. В MR Widget отображается License Scanning findings
# 5. Security Dashboard агрегирует license risks по группе проектов
```

### Сценарий 6: Dependency Scanning через приватный registry mirror

Запуск Dependency Scanning (Grype) в air-gapped среде через локальный registry mirror для vulnerability databases.

```yaml
stages:
  - security

variables:
  DEPENDENCY_SCANNING_EXCLUDED_PATHS: "spec/, test/, vendor/"
  GRYPE_DB_AUTO_UPDATE: "false"
  GRYPE_DB_CACHE_DIR: "/cache/grype-db"

dependency_scanning:
  stage: security
  include:
    - template: Security/Dependency-Scanning.gitlab-ci.yml
  image: registry.gitlab.example.com/security/analyzers/dependency-scanning:4
  variables:
    DEPENDENCY_SCANNING_IMAGE: registry.gitlab.example.com/security/analyzers/dependency-scanning:4
  script:
    - |
      # Предзагрузка vulnerability DB из локального mirror
      mkdir -p $GRYPE_DB_CACHE_DIR
      if [ -f "/cache/grype-db/db.tar.gz" ]; then
        tar xzf /cache/grype-db/db.tar.gz -C $GRYPE_DB_CACHE_DIR
      fi
    - dependency-scanning
  artifacts:
    reports:
      dependency_scanning: gl-dependency-scanning-report.json
    paths:
      - gl-dependency-scanning-report.json
      - $GRYPE_DB_CACHE_DIR/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  cache:
    key: grype-db
    paths:
      - $GRYPE_DB_CACHE_DIR/
```

Предзагрузка vulnerability DB на Runner хосте (air-gapped):
```bash
#!/bin/bash
# Скачивание Grype DB на машине с доступом к интернету
GRYPE_DB_CACHE_DIR="/opt/grype-db"
mkdir -p "$GRYPE_DB_CACHE_DIR"

grype db update --dir "$GRYPE_DB_CACHE_DIR"

# Упаковка DB для переноса в air-gapped среду
tar czf grype-db.tar.gz -C "$GRYPE_DB_CACHE_DIR" .

# Перенос через offline bundle
echo "grype-db.tar.gz ready for air-gapped transfer"
```

**Валидация:**
```bash
# 1. Dependency Scanning job запускается с приватного analyzer image
# 2. Grype DB загружается из cache (нет запросов к внешнему интернету)
# 3. gl-dependency-scanning-report.json содержит CVE для зависимостей
# 4. При обновлении DB: tar czf grype-db.tar.gz на machine с доступом
# 5. В air-gapped среде DB автоматически обновляется через cache key
```

## Валидация и проверка

Выполните проверки после настройки продвинутых security scenarios:

1. **Polyglot SAST:** Bandit и Semgrep custom генерируют `bandit-report.json` и `semgrep-report.json`, отображаются в MR.
   - *Ожидаемый результат:* findings отображаются с severity, confidence, description; при Critical уязвимости pipeline падает.
2. **Pre-commit Secret Detection:** Локальный hook блокирует коммит с секретом; GitLab CI Secret Detection проверяет историю.
   - *Ожидаемый результат:* коммит с секретом отклонён локально; pipeline падает при секрете в истории.
3. **Multi-stage Container Scanning:** Сканируется production-слой (`--target production`), `CS_IMAGE` указывает на финальный образ.
   - *Ожидаемый результат:* report содержит CVE только production-слоя; сборочные CVE не дублируются.
4. **DAST для Kubernetes:** DAST scanner pod имеет RBAC, NetworkPolicy и доступ к staging.
   - *Ожидаемый результат:* `gl-dast-report.json` содержит findings; scanner не падает с permission denied.
5. **License Scanning:** Deny-list лицензии блокируют merge; review-list требуют approval.
   - *Ожидаемый результат:* pipeline падает при GPL-3.0; MR требует approval при LGPL-3.0.
6. **Dependency Scanning в air-gapped:** Grype DB загружается из cache, нет запросов к внешнему интернету.
   - *Ожидаемый результат:* `gl-dependency-scanning-report.json` сгенерирован; egress к внешним хостам отсутствует.
7. **Analyzer Image Mirror:** Все analyzer images доступны из приватного registry mirror.
   - *Ожидаемый результат:* `docker pull registry.gitlab.example.com/security/analyzers/sast:4` успешен.
8. **Security Policy Project:** Централизованные политики применяются ко всей группе.
   - *Ожидаемый результат:* отключённый в проекте SAST запускается принудительно через policy.

## Operations and Commands

### Ручной запуск advanced security scans

```bash
# Запуск polyglot SAST pipeline вручную
gitlab-runner exec docker bandit-sast --builds-dir /tmp/builds

# Или через GitLab API
curl --request POST \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"ref": "main", "variables": {"SAST_DEBUG": "true"}}' \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline"
```

### Управление analyzer images в air-gipped среде

```bash
# На машине с доступом к интернету: скачивание analyzer images
for image in sast secret-detection dependency-scanning container-scanning license-scanning dast; do
  docker pull registry.gitlab.com/security-products/$image:4
  docker tag registry.gitlab.com/security-products/$image:4 \
    registry.gitlab.example.com/security/analyzers/$image:4
  docker push registry.gitlab.example.com/security/analyzers/$image:4
done

# Настройка SAST_ANALYZER_IMAGE_PREFIX в .gitlab-ci.yml
# SAST_ANALYZER_IMAGE_PREFIX: "registry.gitlab.example.com/security/analyzers/"
```

### Предзагрузка vulnerability databases

```bash
# Grype DB для Dependency Scanning
grype db update --dir /opt/grype-db
tar czf grype-db.tar.gz -C /opt/grype-db .

# Trivy DB для Container Scanning
trivy --cache-dir /opt/trivy-cache image --download-db-only
tar czf trivy-db.tar.gz -C /opt/trivy-cache .
```

### Просмотр и агрегация security reports

```bash
# Скачивание aggregated report через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts/gl-sast-report.json" \
  -o sast-report.json

# Просмотр Critical findings через glab
glab api projects/$PROJECT_ID/security/findings | \
  jq '.[] | select(.severity=="Critical") | {title, severity, location, scanner}'

# Агрегация reports из нескольких проектов
for proj in "group/frontend" "group/backend" "group/infra"; do
  curl --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$(echo $proj | tr '/' '%2F')/security/findings" \
    -o ${proj##*/}-findings.json
done

jq -s 'add' *-findings.json > aggregated-findings.json
```

### Отладка custom analyzer'ов

```bash
# Запуск Bandit в debug режиме
bandit -r src/ -f json -o bandit-report.json -v

# Просмотр Semgrep custom rules
semgrep --config=semgrep-rules/ --dump-ast src/ --debug

# Проверка License Finder отчёта
bundle exec license_finder --format json --output license-debug.json --debug

# Логи DAST scanner pod
kubectl logs -n staging deployment/dast-scanner -c zap --tail=200
```

### Управление pre-commit hooks

```bash
# Установка hooks в репозиторий
pre-commit install

# Запуск всех hooks вручную
pre-commit run --all-files

# Обновление hook версий
pre-commit autoupdate

# Генерация baseline для detect-secrets
detect-secrets scan --baseline .secrets.baseline

# Очистка кэша hooks
pre-commit clean
```

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Custom SAST analyzer failed: module not found** | Отсутствуют зависимости в образе | Проверьте `pip install bandit[toml]`. Убедитесь, что образ `python:3.13-slim` доступен. Для air-gapped: подтяните image из mirror. |
| **Pre-commit hook not triggered** | Hook не установлен или `.pre-commit-config.yaml` не в корне | Выполните `pre-commit install`. Проверьте путь к конфигу. Для monorepo: настройте `files:` в `.pre-commit-config.yaml`. |
| **Multi-stage scan wrong layer** | `CS_IMAGE` указывает на сборочный слой | Укажите `--target production` в `docker build` и используйте тег final-образа. Проверьте `docker history $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA`. |
| **DAST auth failed in K8s** | `DAST_AUTH_URL` не resolves из пода | Проверьте Service/Ingress DNS. Убедитесь, что `TEST_USER`/`TEST_PASSWORD` корректны. Для in-cluster DAST: проверьте NetworkPolicy и RBAC. |
| **Historic scan too slow** | Большая история коммитов | Увеличьте `SECRET_DETECTION_GIT_DIFF_MAX_FILES` или запускайте historic scan только в nightly пайплайне через `cron:`. |
| **License Scanning: deny-list license blocked but shouldn't** | Ложное срабатывание (transitive dependency) | Добавьте исключение в `LICENSE_ALLOWLIST` или используйте `rules:changes` для запуска только при изменении `package-lock.json`/`go.sum`. |
| **Dependency Scanning: no vulnerabilities found in air-gapped** | Grype DB устарел или отсутствует | Проверьте `GRYPE_DB_CACHE_DIR`. Предзагрузите актуальную DB через `grype db update`. Убедитесь, что `GRYPE_DB_AUTO_UPDATE: "false"` в air-gapped. |
| **SAST findings not displayed in MR** | Artifact `reports: sast` не сгенерирован или пуст | Проверьте, что `bandit-report.json` существует и не пуст. Убедитесь, что job завершился успешно. Для пустого отчёта: добавьте `|| true` в script. |
| **Container Scanning: image not found** | Registry недоступен или токен истёк | Проверьте `CI_REGISTRY` и `CI_JOB_TOKEN`. Для приватного registry: настройте `CS_REGISTRY_URL` и `CS_AUTH_TOKEN`. |
| **DAST: target not reachable from scanner pod** | NetworkPolicy блокирует egress | Разрешите egress к `DAST_WEBSITE` (443) в NetworkPolicy. Проверьте `kubectl exec -it <dast-pod> -- curl -I https://staging.example.com`. |
| **Pre-commit hook fails on CI but passes locally** | Разные версии Python/библиотек | Зафиксируйте версии в `requirements.txt` для bandit. Используйте `pre-commit` с pinned `rev:`. |
| **License Scanning: false positive on MIT** | Пакет содержит dual-licensed код (MIT + GPL) | Добавьте исключение для конкретного пакета в `LICENSE_REVIEWLIST`. Используйте SBOM для детального анализа. |

## Лучшие практики (Best Practices)

### Безопасность

* Используйте `allow_failure: false` для Critical и High уязвимостей в custom analyzer'ах.
* Для pre-commit Secret Detection используйте отдельный hook для каждого типа секретов (AWS, GitHub, GitLab, database credentials).
* В multi-stage сборках сканируйте только production-образ, чтобы не дублировать findings из сборочных слоёв.
* Настройте MR Approval Rules с scan_result_policies: блокируйте merge при Critical уязвимостях, deny-list лицензиях и секретах.
* Для DAST в Kubernetes используйте отдельный Namespace и минимальные RBAC права для scanner ServiceAccount.
* Включите push protection для Secret Detection (Premium/Ultimate) как complement к pre-commit hooks.
* Храните analyzer images в приватном registry mirror с TLS и scan on push.
* Не запускайте DAST scanner с `privileged: true` — используйте NetworkPolicy для ограничения доступа.

### Производительность

* Для polyglot-проектов запускайте language-specific анализаторы параллельно с встроенным SAST через DAG (`needs`).
* Используйте `rules:changes` для запуска Bandit/Semgrep только при изменении файлов соответствующего языка.
* Для DAST в Kubernetes используйте `interruptible: true` для прерываемых пайплайнов и `timeout: 30m`.
* Кэшируйте Grype/Trivy DB между пайплайнами через `cache:` — обновление DB раз в сутки.
* Запускайте License Scanning только при изменении lock-файлов (`package-lock.json`, `go.sum`, `poetry.lock`).
* Для large repos увеличьте `SEARCH_MAX_DEPTH` или используйте `.sastignore` для исключения тестов и сгенерированного кода.

### Надёжность (SRE)

* Документируйте все custom analyzer'ы и их настройки в runbook.
* Используйте retry для network-dependent scanners (DAST, Container Scanning) через `retry:`.
* Мониторьте время выполнения сканирования и настраивайте алерты при превышении порога (SAST > 10m, DAST > 30m).
* Настройте алерты на недоступность analyzer image mirror и vulnerability DB.
* Используйте immutable tags для analyzer images; запретите overwrite `latest` в production mirror.
* Для air-gapped сред: автоматизируйте обновление vulnerability DB через nightly job на edge-хосте с доступом к интернету.

### Эксплуатация

* Размещайте Runner'ы для security scanning в отдельном пуле с увеличенным memory (8 ГБ+ для SAST на больших репозиториях).
* Настраивайте `check_interval = 1` для security-first пайплайнов при низкой задержке сети.
* Используйте ephemeral Runner'ы для untrusted код (forks) — максимальная изоляция.
* Настройте `expire_in: 90 days` для security reports артефактов.
* Документируйте firewall/NetworkPolicy правила для каждого scanner'а (SAST: нет исходящих соединений, DAST: egress к target, Container Scanning: доступ к registry).
* Проверяйте MTU после изменений сети (VPN, VLAN, оверлеи); единый MTU на всех участках пути между scanner и target.

### Sysadmin: эксплуатация инфраструктуры сканирования

* Настройте registry mirror для analyzer images в air-gapped средах, переопределяя `SAST_ANALYZER_IMAGE_PREFIX` на уровне группы.
* Мониторьте метрики выполнения сканеров (время, OOM, failures) через Prometheus; экспортируйте `gitlab_runner_job_duration_seconds`.
* Настройте экспорт security reports в долговременное хранилище (S3/MinIO) для compliance и аудита.
* Планируйте capacity для Runner'ов исходя из пикового количества параллельных сканирований; используйте `concurrent` в `config.toml`.
* Ротируйте токены доступа к registry (`CI_JOB_TOKEN`, `CS_AUTH_TOKEN`) каждые 90 дней.
* Проводите регулярные penetration tests на staging DAST targets; обновляйте `DAST_INCLUDE_HOSTS`.

## Крайние случаи (Edge Cases)

* **Полная air-gapped среда (no proxy):** Analyzer images и vulnerability DB должны быть предзагружены на Runner хосте. Используйте offline bundle и `SAST_ANALYZER_IMAGE_PREFIX` с локальным registry.
* **Смена upstream registry:** При изменении URL registry analyzer images не переносятся автоматически. Обновите mirror и переопределите префиксы переменных (`SAST_ANALYZER_IMAGE_PREFIX`, `DAST_ZAP_IMAGE`).
* **Cross-project dependency proxy:** Project-level Dependency Proxy видит только кеш своего проекта. Для overlapping зависимостей используйте group-level proxy.
* **Private upstream registries:** Если upstream требует аутентификацию, Dependency Scanning не сможет закешировать артефакты без явной настройки credentials в GitLab.
* **Large artifacts:** Артефакты >500 MB (по умолчанию `max_artifact_size`) не кешируются. Увеличьте лимит в `gitlab.rb` или используйте отдельный object store.
* **Network partitions:** При разрыве connectivity между Runner и GitLab job завершается с timeout. Настройте `retry` в `.gitlab-ci.yml` или увеличьте `job_timeout`.
* **MTU mismatch:** Разный MTU на сетевом пути приводит к фрагментации или тихому падению HTTPS для DAST scanner. Используйте `ping -M do -s 1472` для диагностики.
* **Fork pipelines:** По умолчанию fork pipelines имеют доступ к masked/protected variables. Отключите это в Settings → CI/CD → General pipelines → "Pipelines for contributed projects" → "No variables from the fork project".
* **License dual-licensing:** Пакет может содержать код под несколькими лицензиями (например, MIT + GPL-3.0 для разных файлов). License Scanning может неверно определить основную лицензию. Используйте SBOM (Syft/Trivy) для детального анализа.
* **DAST authentication token expiry:** Если `DAST_AUTH_USERNAME`/`DAST_AUTH_PASSWORD` являются временными токенами, они могут истечь во время длительного сканирования. Используйте Service Account с длительным TTL или обновляйте токены через API.
* **Custom analyzer resource exhaustion:** Bandit/Semgrep на больших репозиториях (>100k строк) могут исчерпать memory. Увеличьте `memory` в `config.toml` или используйте `resource_group` для последовательного выполнения.
* **License Scanning lock file inconsistency:** Если `package-lock.json` и `yarn.lock` расходятся, License Scanning может проанализировать неактуальные зависимости. Удаляйте `node_modules/` перед сканированием.

## Очистка

```bash
# Очистка security reports через GitLab API
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs" | \
  jq -r '.[] | select(.name|test("sast|dast|dependency_scanning|container_scanning|secret_detection|license_scanning")) | .id' | \
  while read job_id; do
    curl --request DELETE --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
      "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$job_id/artifacts" || true
  done

# Очистка orphaned отчетов на Runner хосте
find /tmp/gitlab-security-reports -type f -mtime +90 -delete

# Очистка pre-commit кэша и базы секретов
pre-commit clean
rm -f .secrets.baseline

# Очистка vulnerability DB cache (при необходимости полного обновления)
rm -rf /opt/grype-db/*
rm -rf /opt/trivy-cache/*

# Очистка analyzer images из локального registry mirror
for image in sast dast dependency-scanning container-scanning license-scanning secret-detection; do
  curl --request DELETE \
    --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    "https://registry.gitlab.example.com/v2/security/analyzers/$image:4/manifests/$(
      curl -s -I -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
        "https://registry.gitlab.example.com/v2/security/analyzers/$image:4/manifests/latest" | \
      grep Docker-Content-Digest | awk '{print $2}' | tr -d $'\r'
    )" || true
done
```

## Дополнительная информация

### Смотрите также

* **[Security Scanning в GitLab CI — полное руководство](../Concepts/gitlab_ci_security_scanning.md)** — теория, все типы сканирования, prerequisites, operations, troubleshooting
* **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — пятислойная архитектура безопасности, три уровня раннеров, защита артефактов, cosign, SBOM
* **[Compliance и Audit в GitLab CI/CD](../Advanced/compliance_and_audit.md)** — Pipeline Execution Policies, Compliance Frameworks, Audit Trail
* **[Container Registry Management](../Tutorials/container_registry_management.md)** — управление Docker-образами, registry mirror, lifecycle policies
* **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — методология управления секретами, ротация, зонирование, Zero Trust
* **[Supply Chain Security](../../DevSecOps/iac-security-defense-in-depth.md)** — SBOM, cosign, VEX, SLSA
* **[Proxy и Air-Gapped GitLab CI/CD](../Tutorials/proxy_air_gapped_gitlab_ci.md)** — air-gapped стратегии для analyzer images и зависимостей
* **[GitLab Runner в Docker Compose](../Tutorials/gitlab_runner_docker_compose.md)** — развёртывание hardened Runner'ов для security scanning
* **[GitLab Administration](https://docs.gitlab.com/ee/administration/)** — официальная документация по администрированию
* **[GitLab Docs: Security Scanning](https://docs.gitlab.com/ee/user/application_security/)** — официальная документация по security scanning

### Внешние ресурсы

* [GitLab: SAST](https://docs.gitlab.com/ee/user/application_security/sast/)
* [GitLab: DAST](https://docs.gitlab.com/ee/user/application_security/dast/)
* [GitLab: Dependency Scanning](https://docs.gitlab.com/ee/user/application_security/dependency_scanning/)
* [GitLab: Container Scanning](https://docs.gitlab.com/ee/user/application_security/container_scanning/)
* [GitLab: License Scanning](https://docs.gitlab.com/ee/user/application_security/license_scanning/)
* [GitLab: Secret Detection](https://docs.gitlab.com/ee/user/application_security/secret_detection/)
* [OWASP ZAP](https://www.zaproxy.org/)
* [Grype](https://github.com/anchore/grype)
* [Trivy](https://github.com/aquasecurity/trivy)
* [Bandit](https://bandit.readthedocs.io/)
* [Semgrep](https://semgrep.dev/)
* [detect-secrets](https://github.com/Yelp/detect-secrets)
* [gitleaks](https://github.com/gitleaks/gitleaks)
* [pre-commit](https://pre-commit.com/)
