# Безопасный релиз в GitLab CI/CD: SAST, DAST, SCA, сканирование образов, SBOM и security gates

**Актуально для:** GitLab 18+/19.x, GitLab Runner 18+/19.x, Trivy 0.70+, Cosign v2.6+/v3.1+, HashiCorp Vault 1.21+/2.x (2026)

## Определения

**GitLab CI/CD** — встроенная система CI/CD в GitLab, которая использует `.gitlab-ci.yml` для определения пайплайнов. GitLab предоставляет встроенные шаблоны безопасности (Security Dashboards), которые автоматически собирают результаты сканирования.

**GitLab Runner** — агент, который выполняет jobs пайплайна. Может быть shared (для всего инстанса) или group/project-specific. Поддерживает Docker, Kubernetes, shell executors. GitLab Runner 18+ (совместим с GitLab 18/19) поставляется с обновлёнными prebuilt helper images на Alpine 3.21 и поддержкой `correlation_id` в логах.

**GitLab Security Dashboard** — встроенный интерфейс (Security → Dashboard), который агрегирует результаты SAST, Dependency Scanning, Container Scanning, DAST, Secret Detection и License Scanning. Доступен в Premium/Ultimate tier; в Community Edition результаты доступны через артефакты и API. GitLab 18 добавил Security policy impact assessment с «warn mode» для оценки последствий изменений политик без блокировки MR.

**GitLab CI/CD Variables** — переменные окружения, хранящиеся в Settings → CI/CD → Variables. Поддерживают типы: Variable (plain text), File (содержимое файла), Masked (скрыт в логах), Protected (только для защищённых веток), Environment (только для конкретного окружения).

**Auto DevOps** — встроенный в GitLab пайплайн безопасности, который автоматически включает SAST, DAST, Dependency Scanning, Container Scanning, Secret Detection и License Scanning без рунной конфигурации `.gitlab-ci.yml`.

**Pipeline Execution Policy** — централизованная политика, принудительно выполняющая security-сканирование на уровне группы/инстанса. Введена в GitLab 17.3 как замена Compliance Pipelines; в GitLab 18.x получила Security policy impact assessment и «warn mode», позволяющий оценить влияние политики до её применения.

**SBOM (Software Bill of Materials)** — перечень компонентов ПО (зависимости, версии, лицензии) в машиночитаемом формате (CycloneDX, SPDX). Используется для Dependency Scanning и аттестации артефактов.

**VEX (Vulnerability Exploitability eXchange)** — формат для указания, что известная уязвимость не эксплуатируется в конкретном продукте, позволяющий фильтровать ложные срабатывания.

**Security Gate** — механизм блокировки пайплайна или merge request при превышении порога уязвимостей. Реализуется через `allow_failure: false`, `when: manual` или `rules`.

## Базовые концепции

### Архитектура пайплайна безопасного релиза в GitLab CI

GitLab CI/CD пайплайн состоит из stages, которые выполняются последовательно. Security gates реализуются через:
- `allow_failure: false` — автоматическая блокировка при ошибке сканера
- `when: manual` — ручное подтверждение оператора
- `rules` — условное выполнение job на основе переменных или результатов предыдущих jobs

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Checkout  │ → │  SAST        │ → │  Secret      │ → │  Dependency  │


│             │   │  (Semgrep/   │   │  Detection   │   │  Scanning    │
│             │   │  GitLab SAST)│   │              │   │  (SBOM/Grype)│
└─────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                              │
                                                 ┌────────────┴──────────────┐
                                                 │  DAST / Container Build   │
                                                 │  (ZAP / Docker build)     │
                                                 └────────────┬──────────────┘
                                                              │
                                                 ┌────────────┴──────────────┐
                                                 │  Container Scan + SBOM    │
                                                 │  (Trivy + Syft)           │
                                                 └────────────┬──────────────┘
                                                              │
                                                 ┌────────────┴──────────────┐
                                                 │  License Scan + VEX       │
                                                 │  (License Finder + VEX)   │
                                                 └────────────┬──────────────┘
                                                              │
                                                 ┌────────────┴──────────────┐
                                                 │  Security Gate            │
                                                 │  (auto + manual)          │
                                                 └────────────┬──────────────┘
                                                              │
                                                 ┌────────────┴──────────────┐
                                                 │  Sign & Push              │
                                                 │  (Cosign + GitLab Reg)    │
                                                 └───────────────────────────┘
```

### Инструменты и их роли в GitLab CI

| Инструмент / Функция | Роль в пайплайне | Тип анализа |
| :--- | :--- | :--- |
| **GitLab SAST** | Встроенный SAST-сканер (Semgrep, Bandit, Brakeman и др.) | Статический анализ |
| **GitLab DAST** | Встроенный DAST-сканер (OWASP ZAP) | Динамический анализ |
| **GitLab Secret Detection** | Встроенный поиск секретов в Git-истории | Сканирование секретов |
| **GitLab Dependency Scanning** | Встроенный SCA-сканер (SBOM-based scanner, ранее Gemnasium; deprecated в 17.9) | Анализ зависимостей |
| **GitLab Container Scanning** | Встроенный сканер контейнеров (Trivy) | Сканирование образов |
| **GitLab License Scanning** | Встроенная проверка лицензий (License Finder) | Лицензионный аудит |
| **Semgrep (кастомный)** | SAST с кастомными правилами | Статический анализ |
| **Trivy (кастомный)** | Сканирование Docker-образов, SBOM, IaC | Сканирование образов + SCA |
| **Syft** | Генерация SBOM (CycloneDX, SPDX) | SBOM |
| **Cosign** | Подпись Docker-образа и SBOM перед публикацией в GitLab Container Registry | Криптографическая подпись |
| **HashiCorp Vault** | Хранилище секретов (интеграция через HashiCorp Vault integration) | Секрет-менеджер |

> **Примечание:** GitLab Dependency Scanning исторически использовал Gemnasium (Sonatype). Начиная с GitLab 17.9, Gemnasium помечен как deprecated (предполагаемое удаление в 20.0). В GitLab 18.x SBOM-based Dependency Scanning является стандартным поведением; рекомендуется явно включать `DS_ENFORCE_NEW_ANALYZER: "true"` для совместимости. Для сравнения SCA-инструментов см. **[Сравнение SCA-инструментов](../../Security/Supply_Chain_Security/sca_tools_comparison.md)**. Для глубокого погружения в сканирование образов см. **[Сканирование Docker-образов](../../Docker/Docker_security/vulnerability_scanning.md)**.

> **Внимание — Supply Chain Integrity (2026):** В марте 2026 года в экосистеме Trivy произошла компрометация supply chain (CVE-2026-33634): тег v0.69.4 и связанные GitHub Actions содержали вредоносный код. Всегда используйте фиксированные версии Trivy (≥ 0.70.1), проверяйте SHA256 checksums артефактов и никогда не используйте floating теги (`latest`, `0.69.x`) в production. Аналогичная рекомендация касается Syft и Cosign: скачивайте только из официальных источников и проверяйте подписи.

### Security Gates в GitLab CI

Security gate в GitLab CI реализуется двумя способами:

1. **Автоматический gate:** `allow_failure: false` в job, который запускает сканер. При обнаружении уязвимостей сканер возвращает non-zero exit code, и пайплайн останавливается.
2. **Ручной gate (manual):** `when: manual` в stage или job. GitLab останавливает пайплайн и показывает кнопку "Play" в интерфейсе. Используется для risk acceptance.

В GitLab 18.x появился **Security policy impact assessment** с «warn mode», позволяющий протестировать политику безопасности на MR без блокировки, прежде чем переводить её в enforcement.

### GitLab CI/CD Variables и секреты

В GitLab CI/CD переменные хранятся в Settings → CI/CD → Variables:

| Имя переменной | Тип | Назначение |
| :--- | :--- | :--- |
| `NVD_API_KEY` | Masked | Ключ NVD API для кастомного Dependency Check |
| `COSIGN_PRIVATE_KEY` | Masked, Protected | Закрытый ключ Cosign для подписи образов |
| `COSIGN_PUBLIC_KEY` | Masked, Protected | Открытый ключ Cosign для верификации |
| `REGISTRY_USER` | Masked | Пользователь GitLab Container Registry |
| `REGISTRY_PASSWORD` | Masked, Protected | Пароль или token GitLab Container Registry |
| `VAULT_ADDR` | Masked | Адрес Vault (если используется внешний Vault) |
| `VAULT_TOKEN` | Masked, Protected | Токен доступа к Vault |
| `GITLAB_TOKEN` | Masked, Protected | Token для GitLab API (комментарии в MR, approval rules) |

> **Примечание:** Для работы с GitLab Container Registry используйте встроенные переменные `$CI_REGISTRY`, `$CI_REGISTRY_USER`, `$CI_REGISTRY_PASSWORD`, которые создаются автоматически для каждого проекта.

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум RAM | CPU | Диск |
| :--- | :--- | :--- | :--- |
| **GitLab Runner** | 4 GB | 2 cores | 20 GB |
| **Vault (demo)** | 2 GB | 2 cores | 10 GB |
| **GitLab instance (18+)** | 16 GB | 4 cores | 100 GB |

### Программные требования

- **GitLab:** 18+ (CE или EE с Premium/Ultimate для Security Dashboard, DAST, Push Protection, License Scanning, Security policy impact assessment)
- **GitLab Runner:** 18+ с Docker executor
- **Docker/Podman:** 27+ для запуска сканеров в контейнерах
- **Maven:** 3.8+ (для Java-проектов с Dependency Check)
- **Syft:** 1.52+ для генерации SBOM (если используется кастомный SBOM workflow)

### Начальное состояние окружения

- GitLab instance развёрнута (gitlab.example.com)
- GitLab Runner зарегистрирован в проекте (Settings → CI/CD → Runners)
- Runner имеет тег `docker` для Docker executor
- Vault развёрнут в demo-режиме (опционально)
- GitLab Container Registry включён в проекте (Settings → General → Visibility, project features, permissions → Container registry)
- Security scanning включён (Settings → CI/CD → Security → SAST, DAST, Secret Detection, Dependency Scanning, Container Scanning, License Scanning)
- Protected branches настроены для `main`/`production`

### Валидация окружения

```bash
# Проверка версии GitLab (должна быть 18+)
gitlab-rake gitlab:env:info | grep "Version"

# Проверка версии Runner (должна быть 18+)
gitlab-runner --version

# Проверка доступности registry
curl -k https://gitlab.example.com/v2/

# Проверка доступности Vault (опционально)
vault status
```

## Практические сценарии

### Сценарий 1: Полный `.gitlab-ci.yml` с встроенными шаблонами безопасности

GitLab предоставляет встроенные шаблоны безопасности, которые автоматически настраивают SAST, DAST, Secret Detection, Dependency Scanning, Container Scanning и License Scanning.

```yaml
include:
  # Встроенные шаблоны безопасности GitLab
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/DAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml
  - template: Security/Container-Scanning.gitlab-ci.yml
  - template: Security/License-Scanning.gitlab-ci.yml

stages:
  - test
  - security
  - build
  - deploy

variables:
  # Кастомные переменные для security scanning
  SAST_EXCLUDED_PATHS: "spec, test, tests, vendor"
  SECRET_DETECTION_EXCLUDED_PATHS: "spec, test, tests, vendor"
  DEPENDENCY_SCANNING_EXCLUDED_PATHS: "spec, test, tests, vendor"
  LICENSE_SCANNING_EXCLUDED_PATHS: "spec, test, tests, vendor"
  CONTAINER_SCANNER: "trivy"
  # Включение SBOM-based Dependency Scanning (рекомендуется для GitLab 17+; в GitLab 18.x становится стандартом)
  DS_ENFORCE_NEW_ANALYZER: "true"

# Кастомный SAST с Semgrep (если встроенный недостаточен)
sast_custom:
  stage: security
  image: returntocorp/semgrep:1.175
  variables:
    SEMGREP_RULES: .sgrep-rules
  script:
    - semgrep scan --config=$SEMGREP_RULES --json --output gl-sast-report.json src/
  artifacts:
    reports:
      sast: gl-sast-report.json
    paths:
      - gl-sast-report.json
  rules:
    - if: $SAST_ENABLED == "true"
  allow_failure: true  # Начните с warning-mode, затем перейдите к false

# Security Gate: автоматическая проверка + ручное подтверждение
security_gate:
  stage: security
  image: alpine:latest
  variables:
    SAST_HIGH_THRESHOLD: 0
    SCA_CRITICAL_THRESHOLD: 0
  script:
    - apk add --no-cache jq
    - |
      # Проверка SAST (Semgrep)
      if [ -f gl-sast-report.json ]; then
        SAST_HIGH=$(jq '[.results[] | select(.extra.severity == "HIGH")] | length' gl-sast-report.json)
        echo "Semgrep HIGH: $SAST_HIGH"
        if [ "$SAST_HIGH" -gt "$SAST_HIGH_THRESHOLD" ]; then
          echo "FAIL: найдено $SAST_HIGH HIGH-уязвимостей в SAST"
          exit 1
        fi
      fi
    - |
      # Проверка Dependency Scanning (SBOM-based или Gemnasium)
      if [ -f gl-dependency-scanning-report.json ]; then
        SCA_CRITICAL=$(jq '[.vulnerabilities[]? | select(.severity == "CRITICAL")] | length' gl-dependency-scanning-report.json)
        echo "Dependency Scanning CRITICAL: $SCA_CRITICAL"
        if [ "$SCA_CRITICAL" -gt "$SCA_CRITICAL_THRESHOLD" ]; then
          echo "FAIL: найдено $SCA_CRITICAL CRITICAL CVE в SCA"
          exit 1
        fi
      fi
    - echo "Все security gates пройдены"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: false
```

**Ключевые моменты:**
- **Встроенные шаблоны:** `Security/SAST.gitlab-ci.yml`, `Security/DAST.gitlab-ci.yml`, `Security/Secret-Detection.gitlab-ci.yml`, `Security/Dependency-Scanning.gitlab-ci.yml`, `Security/Container-Scanning.gitlab-ci.yml`, `Security/License-Scanning.gitlab-ci.yml` автоматически настраивают сканеры
- **Artifacts reports:** GitLab распознаёт форматы `sast`, `dast`, `secret_detection`, `dependency_scanning`, `container_scanning`, `license_scanning` и отображает результаты в Security Dashboard
- **Rules:** jobs выполняются только для merge request (`merge_request_event`), чтобы не блокировать merges в main
- **allow_failure:** начинайте с `true` (warning-mode), затем перейдите к `false` (enforcement)
- **SBOM-based scanning:** `DS_ENFORCE_NEW_ANALYZER: "true"` включает новый анализатор на основе SBOM (в GitLab 18.x это поведение по умолчанию)
- **Supply Chain Integrity:** всегда используйте фиксированные версии образов сканеров (Semgrep 1.175+, Trivy 0.74+, Syft 1.52+) и проверяйте их checksums; избегайте тегов `latest` в production

**Валидация:**
```bash
# 1. В Merge Request: вкладка Security показывает findings по всем сканерам
# 2. При CRITICAL/HIGH уязвимости: pipeline падает (allow_failure: false)
# 3. В Security Dashboard: findings агрегируются по проекту
# 4. При секретах в коде: Secret Detection блокирует merge (Premium/Ultimate с Push Protection)
# 5. В License Scanning: findings по недопустимым лицензиям отображаются в MR
```

### Сценарий 2: GitLab Security Dashboard и reporting

GitLab Security Dashboard агрегирует результаты всех security scanners в единый интерфейс.

**Включение Security Dashboard:**

1. Перейдите в **Security → Dashboard** в проекте
2. GitLab автоматически отображает:
   - **SAST findings** из `gl-sast-report.json`
   - **DAST findings** из `gl-dast-report.json`
   - **Secret Detection findings** из `gl-secret-detection-report.json`
   - **Dependency Scanning findings** из `gl-dependency-scanning-report.json`
   - **Container Scanning findings** из Trivy/Gemnasium
   - **License Scanning findings** из `gl-license-report.json`

**Настройка отчётов:**

```yaml
# Включение SAST отчёта в GitLab Security Dashboard
sast:
  stage: security
  artifacts:
    reports:
      sast: gl-sast-report.json
    paths:
      - gl-sast-report.json
  rules:
    - if: $SAST_ENABLED == "true"

# Включение Dependency Scanning отчёта
dependency_scanning:
  stage: security
  artifacts:
    reports:
      dependency_scanning: gl-dependency-scanning-report.json
  rules:
    - if: $DEPENDENCY_SCANNING_ENABLED == "true"

# Включение Container Scanning отчёта
container_scanning:
  stage: security
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
  rules:
    - if: $CONTAINER_SCANNING_ENABLED == "true"
```

**Валидация:**
```bash
# 1. В интерфейсе GitLab Security → Pipeline security dashboard отображаются все findings с severity, CVE, и рекомендациями по исправлению
# 2. Для GitLab Ultimate: доступна cross-project агрегация в Group Security Dashboard
# 3. Экспорт в CSV/JSON для отчетности
# 4. При Critical уязвимости: MR блокируется (если настроен quality gate)
```

### Сценарий 3: GitLab Container Registry, Cosign, SBOM attestation и VEX

GitLab предоставляет встроенный Container Registry для каждого проекта. Cosign используется для подписи образов и SBOM перед push.

```yaml
stages:
  - build
  - security
  - sign
  - deploy

variables:
  DOCKER_TLS_CERTDIR: "/certs"
  COSIGN_EXPERIMENTAL: "1"  # Включение экспериментальных команд (attest)

# 1. Build Docker image
build_image:
  stage: build
  image: docker:27
  services:
    - docker:27-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
    - if: $CI_COMMIT_TAG

# 2. Генерация SBOM через Syft
generate_sbom:
  stage: security
  image: anchore/syft:1.52
  script:
    - syft $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA -o cyclonedx-json > sbom.json
    - echo "SBOM сгенерирован: $(wc -c < sbom.json) байт"
  artifacts:
    paths:
      - sbom.json
    expire_in: 7 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

# 3. Аттестация SBOM через Cosign
attest_sbom:
  stage: sign
  image: golang:1.27
  script:
    - go install github.com/sigstore/cosign/v2/cmd/cosign@v2.6.5
    - echo "$COSIGN_PRIVATE_KEY" > /tmp/cosign.key
    - chmod 600 /tmp/cosign.key
    - cosign attest --predicate sbom.json --type cyclonedx --key /tmp/cosign.key $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - rm -f /tmp/cosign.key
  dependencies:
    - generate_sbom
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

# 4. Подпись образа через Cosign
sign_image:
  stage: sign
  image: golang:1.27
  script:
    - go install github.com/sigstore/cosign/v2/cmd/cosign@v2.6.5
    - echo "$COSIGN_PRIVATE_KEY" > /tmp/cosign.key
    - chmod 600 /tmp/cosign.key
    - cosign sign --key /tmp/cosign.key --yes $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - rm -f /tmp/cosign.key
  dependencies:
    - build_image
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

# 5. Верификация подписи (опционально, в отдельном stage)
verify_signature:
  stage: security
  image: golang:1.27
  script:
    - go install github.com/sigstore/cosign/v2/cmd/cosign@v2.6.5
    - cosign verify --key cosign.pub $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Ключевые моменты:**
- **GitLab Container Registry:** использует встроенные переменные `$CI_REGISTRY`, `$CI_REGISTRY_USER`, `$CI_REGISTRY_PASSWORD`
- **SBOM attestation:** Cosign связывает SBOM с образом через OCI Referrers API
- **Cosign:** подпись происходит после успешного прохождения security gates
- **Docker-in-Docker:** используется для сборки и push образа

**Валидация:**
```bash
# 1. Проверка: образ pushed в GitLab Container Registry
curl -u $CI_REGISTRY_USER:$CI_REGISTRY_PASSWORD $CI_REGISTRY/v2/$CI_PROJECT_PATH/tags/list

# 2. Проверка: SBOM сгенерирован и attestation добавлена
cosign verify-attestation --key cosign.pub $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

# 3. Проверка: подпись образа валидна
cosign verify --key cosign.pub $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

### Сценарий 4: GitLab CI/CD Variables и интеграция с Vault

GitLab поддерживает интеграцию с HashiCorp Vault для динамических секретов.

**Настройка Vault integration в GitLab:**

1. Перейдите в **Settings → CI/CD → Variables → Expand → HashiCorp Vault**
2. Укажите:
   - **Vault URL:** `https://vault.internal:8200`
   - **Auth method:** `token` или `jwt` (для GitLab JWT)
   - **Token:** `$VAULT_TOKEN` (если используется token auth)

**Использование Vault в пайплайне:**

```yaml
stages:
  - security

variables:
  # Vault integration автоматически экспортирует секреты
  VAULT_ADDR: "https://vault.internal:8200"

get_cosign_key:
  stage: security
  image: vault:1.15
  script:
    - vault login -method=gitlab jwt=$CI_JOB_JWT
    - vault kv get -field=key secret/cosign/cosign-key > /tmp/cosign.key
    - chmod 600 /tmp/cosign.key
    - echo "Cosign key получен из Vault"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Альтернатива: GitLab CI/CD Variables с Vault:**

Если интеграция с Vault не настроена, используйте GitLab CI/CD Variables для хранения секретов:

```yaml
variables:
  COSIGN_PRIVATE_KEY: $COSIGN_PRIVATE_KEY  # Masked, Protected variable в GitLab
  NVD_API_KEY: $NVD_API_KEY  # Masked variable
```

### Сценарий 5: GitLab Merge Request Pipelines, Approval Rules и Pipeline Execution Policies

GitLab позволяет настроить approval rules для merge request, которые требуют approval от security-команды при обнаружении критических уязвимостей. Pipeline Execution Policies (GitLab 17.3+) принудительно включают сканирование даже если проект его отключил. В GitLab 18.x политики получили Security policy impact assessment с «warn mode», позволяющим протестировать правило без блокировки MR перед переводом в enforcement.

**Настройка Approval Rules:**

1. Перейдите в **Settings → Merge request → Merge request approvals**
2. Добавьте правило:
   - **Approvals required:** 1
   - **Approvers:** @security-team
   - **Conditions:** Security findings in merge request

**Настройка Merge Request Pipelines:**

```yaml
stages:
  - test
  - security
  - build

security_scan:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    - trivy fs --format json --output trivy-report.json .
  artifacts:
    reports:
      container_scanning: trivy-report.json
    expire_in: 7 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: true  # Warning mode для MR

# Security gate для MR
security_gate_mr:
  stage: security
  image: alpine:latest
  script:
    - apk add --no-cache jq
    - |
      CRITICAL=$(jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' trivy-report.json)
      if [ "$CRITICAL" -gt 0 ]; then
        echo "FAIL: найдено $CRITICAL CRITICAL CVE"
        # Добавление комментария в MR
        curl -X POST "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes" \
          --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
          --header "Content-Type: application/json" \
          --data '{"body": "⚠️ Security gate: найдены критические уязвимости. Требуется approval от security-команды."}'
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: false
```

**Pipeline Execution Policy (централизованное принудительное сканирование):**

```yaml
# .gitlab/security-policies.yml
include:
  - template: Security/Security-Policy-Admin.gitlab-ci.yml

pipeline_execution_policy:
  - type: pipeline_execution_policy
    name: "Mandatory Security Scanning"
    rules:
      - if: $CI_PIPELINE_SOURCE == "push"
    config:
      - scan_execution_policy:
          - name: "SAST and Dependency Scanning"
            rules:
              - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
            actions:
              scan:
                - scan_type: sast
                - scan_type: dependency_scanning
                - scan_type: container_scanning
```

**Валидация:**
```bash
# 1. При обнаружении критических уязвимостей в MR:
#    - Пайплайн завершается с ошибкой
#    - В MR добавляется комментарий с предупреждением
#    - Требуется approval от security-команды для merge
# 2. Pipeline Execution Policy принудительно включает сканирование даже если проект отключил его в .gitlab-ci.yml
# 3. В Audit Events фиксируется применение политики
```

### Сценарий 6: Auto DevOps и кастомизация

GitLab Auto DevOps автоматически включает security scanning без ручной конфигурации `.gitlab-ci.yml`.

**Включение Auto DevOps:**

1. Перейдите в **Settings → CI/CD → Auto DevOps**
2. Включите **Auto DevOps**
3. Выберите:
   - **Security scanning:** SAST, DAST, Dependency Scanning, Container Scanning, Secret Detection, License Scanning
   - **Deployment strategy:** Manual, Continuous, Auto

**Кастомизация Auto DevOps:**

Если Auto DevOps не подходит, создайте кастомный `.gitlab-ci.yml` на основе шаблонов:

```yaml
# .gitlab-ci.yml с кастомизацией Auto DevOps
include:
  - template: Auto-DevOps.gitlab-ci.yml

# Переопределение security scanning
sast:
  stage: security
  variables:
    SAST_EXCLUDED_PATHS: "spec, test, tests, vendor"
    SAST_RULES: ".sgrep-rules"  # Кастомные правила Semgrep

dependency_scanning:
  stage: security
  variables:
    DS_ENFORCE_NEW_ANALYZER: "true"  # SBOM-based scanner

container_scanning:
  stage: security
  variables:
    SCANNER: "trivy"
    TRIVY_SEVERITY: "CRITICAL,HIGH"
```

## Оперативные команды

### GitLab CI/CD API

```bash
# Получение статуса пайплайна
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID"

# Получение артефактов пайплайна
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts" \
  --output artifacts.zip

# Добавление комментария в MR
curl -X POST "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes" \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"body": "Security gate: найдены критические уязвимости."}'
```

### GitLab Runner management

```bash
# Проверка статуса GitLab Runner
sudo gitlab-runner status

# Перерегистрация Runner
sudo gitlab-runner register \
  --url https://gitlab.example.com/ \
  --registration-token $REGISTRATION_TOKEN \
  --executor docker \
  --docker-image alpine:latest \
  --tag-list docker \
  --run-untagged=false \
  --locked=false

# Очистка кэша Runner
sudo gitlab-runner cache-clean
```

### SBOM и аттестации

```bash
# Генерация SBOM через Syft 1.52+
syft $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA -o cyclonedx-json > sbom.json

# Аттестация SBOM через Cosign v2.6+/v3.1+
cosign attest --predicate sbom.json --type cyclonedx --key /tmp/cosign.key $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

# Верификация attestation
cosign verify-attestation --key cosign.pub $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

# Создание VEX-отчёта (исключение не-эксплуатируемых CVE)
trivy image --format cyclonedx --vex ./vex-statement.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

# Проверка целостности Trivy (рекомендуется в production)
trivy --version
trivy image --download-db-only
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| GitLab SAST не запускается | Runner не имеет тега `sast` или не поддерживает Kubernetes | Проверьте теги Runner в Settings → CI/CD → Runners; используйте `tags: [sast, docker]` |
| Dependency Scanning не видит transitive-зависимости | Используется устаревший Gemnasium вместо SBOM-based scanner | Переключитесь на `DS_ENFORCE_NEW_ANALYZER: "true"` или обновите GitLab до 17+ |
| GitLab пропускает версию 18.10.2 / 18.9.4 / 18.8.8 | Известный баг: эти патчи были пропущены в релизе | Установите ближайший доступный патч (18.10.3, 18.9.5, 18.8.9) или выше; см. [GitLab release notes](https://docs.gitlab.com/releases/patches/patch-release-gitlab-18-10-3-released) |
| Сканер уязвим из-за скомпрометированного образа | Использована скомпрометированная версия Trivy (v0.69.4, CVE-2026-33634) | Сканируйте артефакты на наличие бэкдоров, используйте только проверенные версии (≥ 0.70.1) и проверяйте checksums; ротируйте все секреты, доступные пайплайну |
| Container Scanning не сканирует образ | Образ не доступен в registry | Убедитесь, что образ pushed в GitLab Container Registry; используйте `$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA` |
| Security Dashboard пустой | Artifacts reports не сконфигурированы | Проверьте, что artifacts содержат `reports: sast:`, `reports: dependency_scanning:`, `reports: container_scanning:` |
| Cosign подпись не работает | Ключ не найден или Vault недоступен | Проверьте переменные `COSIGN_PRIVATE_KEY`; проверьте доступность Vault |
| `allow_failure: false` блокирует MR | Сканер возвращает non-zero exit code при findings | Настройте пороги в сканере (`--severity CRITICAL,HIGH`) или начните с `allow_failure: true` |
| Secret Detection не находит секреты | Push Protection не включён (требуется Premium/Ultimate) | Включите Push Protection в Settings → CI/CD → Security → Secret Detection |
| License Scanning не запускается | Требуется GitLab Ultimate | Проверьте tier лицензии; в Premium/Free функция недоступна |
| Pipeline Execution Policy не применяется | Политика не активна на уровне группы | Проверьте статус политики в Settings → Security → Policies; убедитесь что группа имеет Ultimate лицензию |

## Рекомендации

### Security Gates

- **Critical/High — блокировать по умолчанию:** Настройте `allow_failure: false` для security jobs после формирования baseline
- **Merge Request pipelines:** Запускайте security scans только для MR (`rules: - if: $CI_PIPELINE_SOURCE == "merge_request_event"`), чтобы не блокировать merges
- **Auto DevOps:** Используйте Auto DevOps для быстрого старта, затем кастомизируйте под нужды команды
- **Quality Gates:** Настройте Approval Rules для merge request с security findings

### Секреты

- **GitLab CI/CD Variables:** Используйте `Masked` и `Protected` флаги для секретов
- **Vault integration:** Для production используйте HashiCorp Vault integration вместо plaintext переменных
- **Cosign keys:** Храните закрытые ключи в Vault, а не в GitLab Variables
- **Push Protection:** Включите Secret Detection Push Protection (Premium/Ultimate) для блокировки секретов до merge

### Оптимизация производительности

- **Кэширование:** Используйте GitLab cache для кэширования зависимостей (`cache: paths: - ~/.cache/trivy/`)
- **Incremental scans:** Запускайте SAST/SCA только для изменённых файлов в MR (`rules: - if: $CI_PIPELINE_SOURCE == "merge_request_event"`)
- **Parallel jobs:** GitLab автоматически параллелит независимые jobs в одном stage
- **SBOM caching:** Кэшируйте SBOM между пайплайнами, чтобы не генерировать его заново

### Compliance и аудит

- **Pipeline visibility:** Включите **Pipeline visibility** в Settings → General → Visibility, project features, permissions
- **Audit events:** GitLab логирует все изменения в CI/CD variables и пайплайнах (Settings → Audit Events)
- **Security Dashboard:** Используйте встроенный Security Dashboard для Compliance reporting
- **Pipeline Execution Policies:** Используйте для принудительного сканирования в air-gapped средах

### Supply Chain

- **SBOM-first:** Перейдите на SBOM-based Dependency Scanning (GitLab 18+) вместо устаревшего Gemnasium
- **Attestation:** Аттестуйте SBOM и VEX через Cosign для отслеживания происхождения артефактов
- **Reproducible builds:** Используйте reproducible builds для гарантии идентичности артефактов
- **Continuous Dependency Scanning:** Включите Continuous Dependency Scanning для отслеживания новых CVE без перезапуска пайплайнов
- **Integrity checks:** Всегда проверяйте checksums сканеров (Trivy, Syft, Cosign) и используйте фиксированные версии; ротируйте секреты при любом подозрении на компрометацию supply chain (см. CVE-2026-33634)

### SRE-метрики и эксплуатация security pipeline

- **Pipeline Duration (security jobs):** целевое p95 < 10 минут для SAST+SCA+Container scan; превышение — сигнал для оптимизации кэширования или параллельного запуска
- **Gate Block Rate:** процент пайплайнов, заблокированных security gates; целевое значение < 5% после формирования baseline
- **Gate Latency:** время от push/ MR до результата security scan; влияет на developer experience
- **Runner Utilization:** утилизация CPU/ RAM раннеров; при > 80% добавьте capacity или перераспределите jobs
- **False Positive Rate:** процент ложных срабатываний; высокий FPR снижает доверие команды к security gates
- **MTTR (Mean Time to Remediate):** время от triage до исправления Critical/High findings; целевое < 7 дней для production
- **MTTT (Mean Time to Triage):** время от detection до классификации findings; автоматизируйте triage через VEX и allow-lists
- **Pipeline Failure Rate:** процент пайплайнов, упавших по причинам, не связанным с security findings (infrastructure, network); отдельный SLI для SRE
- **Мониторинг:** экспортируйте метрики GitLab Runner (Prometheus format) и настройте алерты на падение jobs, рост queue time, ошибки executor; см. детали в **[Мониторинг и метрики DevSecOps](./devsecops_monitoring.md)**

###灾вoor Recovery и Change Management

- **Резервное копирование GitLab:** регулярный `gitlab-backup create` (без внешних сервисов); храните бэкапы на локальном NAS или отдельном хосте в той же сети
- **Резервное копирование Vault:** настройте `vault operator raft autopilot` или периодическое `vault read` + файловый бэкап secrets; тестируйте восстановление на отдельном стенде не реже раза в квартал
- **Change freeze:** запрещайте изменения в security policies и runner конфигурации во время release freeze без explicit approval
- **Change window:** внесение изменений в security scanning (новые сканеры, повышение порогов) планируйте в стандартное окно изменений; фиксируйте изменения в Audit Events
- **Горячие патчи:** при критических CVE в инфраструктуру (GitLab, Runner, Vault) приоритизируйте обновление до патч-релиза, пропуская стандартный цикл approvals; GitLab 18.x требует внимания к пропускам версий (например, 18.10.2 был пропущен)

## Граничные случаи (Edge Cases)

### Air-gapped среды

В изолированных сегментах без доступа к интернету:
- Предзагрузите analyzer images в корпоративный registry mirror
- Настройте локальный mirror баз CVE (Trivy, Grype)
- Используйте `air-gapped bundle` для GitLab Runner
- Настройте Dependency Scanning с локальным advisory DB

### Многомодульные проекты (monorepo)

При сканировании monorepo:
- Используйте `SAST_EXCLUDED_PATHS` для исключения несвязанных модулей
- Настройте отдельные security jobs для каждого модуля
- Используйте `rules:changes` для запуска сканирования только для изменённых модулей

### Фальшивые срабатывания (False Positives)

- Используйте встроенные allow-lists в GitLab Security Dashboard
- Для Semgrep: `.semgrepignore` и `# nosem`
- Для Trivy: `.trivyignore`
- Для Secret Detection: `.gitlab/secret-detection-ruleset.yml`

### Ретроспективное сканирование

Для существующих проектов с накопленным "долгом":
1. Начните с `allow_failure: true` для всех security jobs
2. Сформируйте baseline отчётов
3. Постепенно снижайте пороги и переходите к `allow_failure: false`
4. Используйте MR pipelines для блокировки новых уязвимостей, пока исправляете старые

### Degraded runners и инфраструктурные инциденты

При падении или деградации раннеров:
- **Диспатчер jobs:** проверяете queue time в GitLab Admin → Overview → Runners; при росте queue time добавьте capacity или перераспределите нагрузку
- **Executor failures:** для Docker executor проверяйте доступность DinD образа и сетевую связность; для Kubernetes executor — ресурсы pods и лимиты namespace
- **Log correlation:** используйте `correlation_id` (GitLab Runner 18.1+) для трассировки job через все сервисы (runner, GitLab, Vault)
- **Fallback:** настройте запасной shared runner на другом хосте/в другом сегменте сети для критических проектов

### Supply chain compromise response

При обнаружении скомпрометированного инструмента (как Trivy v0.69.4 в марте 2026):
1. **Изолируйте:** остановите все пайплайны, использующие компрометированный бинарник/образ
2. **Аудит:** проверьте логи jobs на признаки эксфильтрации секретов (CI_JOB_TOKEN, VAULT_TOKEN, COSIGN_PRIVATE_KEY)
3. **Ротация:** ротируйте все секреты, доступные в пайплайнах; отзовите Cosign ключи, перевыпустите Vault токены
4. **Верификация:** пересканируйте последние артефакты на наличие бэкдоров; откатите deployment скомпрометированных сборок
5. **Пост-инцидент:** обновите политику выбора образов (фиксированные версии + checksums), добавьте SBOM attestation в mandatory gate, пересмотрите allow-lists

## Очистка (Cleanup)

### Отключение security scanning

```yaml
# Отключение конкретного сканера
variables:
  SAST_DISABLED: "true"
  DEPENDENCY_SCANNING_DISABLED: "true"
  CONTAINER_SCANNING_DISABLED: "true"
  DAST_DISABLED: "true"
  SECRET_DETECTION_DISABLED: "true"
  LICENSE_SCANNING_DISABLED: "true"
```

### Удаление Pipeline Execution Policy

```bash
# Через GitLab UI: Settings → Security → Policies → удалить политику
# Через API:
curl --request DELETE --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/security_policies/$POLICY_ID"
```

### Очистка артефактов security scanning

```yaml
# Уменьшение времени хранения артефактов
security_scan:
  artifacts:
    reports:
      sast: gl-sast-report.json
    expire_in: 3 days
```

### Очистка кэша Trivy и устаревших баз уязвимостей

```bash
# Очистка кэша Trivy на runner'е (если используется volume cache)
rm -rf ~/.cache/trivy/

# Принудительное обновление advisory DB (если кэш повреждён или устарел)
trivy image --download-db-only --db-repository public.ecr.aws/aquasecurity/trivy-db
```

### Ротация секретов

```bash
# Ротация Cosign ключей (если используется Vault)
vault kv put secret/cosign/cosign-key key="$(cosign generate-key-pair | grep private | cut -d' ' -f2)"
# Обновите public key в GitLab CI/CD Variables (Settings → CI/CD → Variables)

# Ротация Vault токена (если используется JWT auth)
# Токен короткоживущий, но при компрометации Runner перевыпустите AppRole или JWT policy
```

## Дополнительная информация

### Связанные документы

- **[Сканирование безопасности в GitLab CI/CD](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_security_scanning.md)** — архитектура, встроенные шаблоны, механизм работы security scanning в GitLab
- **[Security Scanning в GitLab CI/CD — глубинное погружение](../../CI-CD/GitLab_CI/Tutorials/security_scanning_deep_dive.md)** — продвинутые сценарии, polyglot-проекты, custom analyzers, in-cluster DAST
- **[Сравнение SCA-инструментов](../../Security/Supply_Chain_Security/sca_tools_comparison.md)** — Trivy, Grype, Snyk, OWASP Dependency Check
- **[Сканирование Docker-образов](../../Docker/Docker_security/vulnerability_scanning.md)** — стратегии сканирования, Trivy, Copacetic
- **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — Cosign, Notation, Sigstore, VSA, OCI 1.1
- **[DevSecOps — обзор методологии](./devsecops_overview.md)** — принципы, ASPM, maturity model
- **[Сравнение инструментов DevSecOps](./devsecops_tools_comparison.md)** — SAST, SCA, IaC, secrets managers
- **[Мониторинг и метрики DevSecOps](./devsecops_monitoring.md)** — pipeline метрики, SLO, Alertmanager, Grafana дашборды для security pipeline
- **[CI/CD Security Hardening](../../CI-CD/GitLab_CI/Advanced/cicd_security_hardening.md)** — общие принципы защиты CI/CD, Runner hardening, supply chain

### Ресурсы GitLab

- **GitLab CI/CD Documentation:** https://docs.gitlab.com/ee/ci/
- **GitLab Security Scanning:** https://docs.gitlab.com/ee/user/application_security/
- **GitLab Container Registry:** https://docs.gitlab.com/ee/user/packages/container_registry/
- **GitLab Auto DevOps:** https://docs.gitlab.com/ee/topics/autodevops/
- **GitLab Runner:** https://docs.gitlab.com/ee/runner/
- **GitLab Security Dashboard:** https://docs.gitlab.com/ee/user/application_security/security_dashboard/
- **Pipeline Execution Policies:** https://docs.gitlab.com/ee/user/application_security/policies/#pipeline-execution-policies
- **Dependency Scanning (SBOM):** https://docs.gitlab.com/ee/user/application_security/dependency_scanning/dependency_scanning_sbom/
- **GitLab 18 Release Notes:** https://docs.gitlab.com/releases/18/gitlab-18-0-released
- **Security Policy Impact Assessment (warn mode):** https://docs.gitlab.com/ee/user/application_security/policies/security_policy_management.html#policy-impact-assessment
