# Сканирование безопасности в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x, GitLab Runner 17.x–19.x

## Определения

*   **SAST (Static Application Security Testing)** — статический анализ исходного кода без его выполнения. В GitLab включает Semgrep, Bandit, Brakeman и другие анализаторы. Отчет: `gl-sast-report.json`.
*   **DAST (Dynamic Application Security Testing)** — динамический анализ работающего приложения. В GitLab основан на OWASP ZAP. Отчет: `gl-dast-report.json`.
*   **Secret Detection** — поиск закоммиченных секретов (токены, пароли, ключи) в истории Git. Основан на GitLab Secret Detection (аналог gitleaks). Отчет: `gl-secret-detection-report.json`.
*   **Dependency Scanning** — анализ зависимостей на известные CVE. В GitLab основан на Grype (с 19.0). Отчет: `gl-dependency-scanning-report.json`.
*   **Container Scanning** — анализ Docker-образов на уязвимости. В GitLab основан на Trivy (с 16.0). Отчет: `gl-container-scanning-report.json`.
*   **License Scanning** — проверка лицензий зависимостей на соответствие политике. В GitLab основан на License Finder. Отчет: `gl-license-report.json`.
*   **Security Report Artifact** — агрегированный отчет о находках сканирования в формате JSON, отображаемый в UI Merge Request. Форматы: `gl-sast-report.json`, `gl-dast-report.json`, `gl-secret-detection-report.json`, `gl-dependency-scanning-report.json`, `gl-container-scanning-report.json`, `gl-license-report.json`.
*   **Pipeline Execution Policy** — централизованная политика, принудительно выполняющая security-сканирование на уровне группы/инстанса. Введена в 17.3 как замена Compliance Pipelines.
*   **MR Approval Rules** — правила requiring approval от security-команды при наличии критичных уязвимостей в отчетах.
*   **Analyzer Image** — Docker-образ, содержащий сканер безопасности (Semgrep, Trivy, Grype, ZAP). Версии analyzer images связаны с версиями GitLab и обновляются автоматически.
*   **Quality Gate** — правило, блокирующее merge/deploy при превышении порога уязвимостей (например, Critical > 0).
*   **False Positive** — срабатывание сканера на не-уязвимый код или тестовые данные. Управляется через исключения и approval rules.
*   **CVE (Common Vulnerabilities and Exposures)** — база данных известных уязвимостей программного обеспечения.
*   **VEX (Vulnerability Exploitability eXchange)** — формат для указания, что известная уязвимость не эксплуатируется в конкретном продукте.

> **Примечание:** Общие принципы CI/CD Security Hardening, Supply Chain Attack, Least Privilege, RBAC и защита Runner'ов — в **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)**. Для Pipeline Execution Policies и compliance frameworks — в **[Compliance и Audit в GitLab CI/CD](../Advanced/compliance_and_audit.md)**.

## Базовые концепции / Архитектура / How it works

### Встроенные шаблоны безопасности GitLab

GitLab предоставляет готовые шаблоны для включения сканирования в `.gitlab-ci.yml`:

| Шаблон | Назначение | Инструмент |
|:---|:---|:---|
| `Security/SAST.gitlab-ci.yml` | Статический анализ кода | Semgrep |
| `Security/DAST.gitlab-ci.yml` | Динамический анализ приложения | OWASP ZAP |
| `Security/Secret-Detection.gitlab-ci.yml` | Поиск секретов в коде | GitLab Secret Detection |
| `Security/Dependency-Scanning.gitlab-ci.yml` | Анализ зависимостей | Grype |
| `Security/Container-Scanning.gitlab-ci.yml` | Анализ Docker-образов | Trivy |
| `Security/License-Scanning.gitlab-ci.yml` | Проверка лицензий | License Finder |

### Архитектура security scanning в GitLab CI/CD

Security scanning в GitLab CI/CD работает по принципу **shift-left**: проверки выполняются как можно раньше в конвейере, до попадания кода в production.

**Механизм работы:**
1.  **Pipeline trigger:** При push или merge request GitLab запускает pipeline.
2.  **Security stage:** После build и test запускается security stage с задачами сканирования.
3.  **Analyzer execution:** Каждый сканер запускается в изолированном Docker-контейнере (analyzer image) с доступом к исходному коду или артефактам.
4.  **Report generation:** Сканер генерирует отчет в формате JSON (Security Report Artifact) с Findings (уязвимостями).
5.  **Artifact upload:** Отчет загружается как артефакт задачи с специальным типом `reports`.
6.  **MR Widget:** GitLab автоматически отображает находки в Merge Request на вкладке **Security**.
7.  **Vulnerability Dashboard:** Для GitLab Ultimate находки агрегируются в **Security & Compliance > Vulnerability Report**.

**Поток данных:**
```
Source Code → Analyzer Container → Report JSON → GitLab Artifact → MR Widget → Vulnerability Dashboard
```

**Изоляция:** Сканеры выполняются в отдельных контейнерах с минимальными правами. Для Docker-образов Container Scanning требует доступа к registry. На shared Runner'ах сканеры не имеют доступа к хостовой системе.

### Security Report Artifacts в Merge Request

Каждый сканер генерирует отчет в формате JSON, который GitLab автоматически отображает в Merge Request:

```yaml
# Пример: SAST report artifact
sast:
  stage: security
  include:
    - template: Security/SAST.gitlab-ci.yml
  artifacts:
    reports:
      sast: gl-sast-report.json
    paths:
      - gl-sast-report.json
```

**Валидация:**
```bash
# Проверка: в Merge Request появилась вкладка Security
# Проверка: findings отображаются с severity, confidence, description
# Проверка: при Critical уязвимости MR блокируется (если настроен quality gate)
# Проверка: при нажатии на finding открывается детальная информация с кодом
```

### Vulnerability Dashboard

GitLab Ultimate предоставляет **Security Dashboard** для агрегации findings across all projects. Доступен в `Secure > Vulnerability Report`.

**Валидация:**
```bash
# Проверка: Dashboard отображает все проекты группы
# Проверка: findings фильтруются по severity, scanner, age
# Проверка: доступна экспорт в CSV/JSON для отчетности
# Проверка: для GitLab Ultimate — cross-project агрегация
```

## Практические сценарии / Installation and Setup / Configuration

### Предварительные требования

#### Аппаратные требования

| Компонент | Минимум | Рекомендация |
|:---|:---|:---|
| **GitLab Server** | 4 CPU, 8 ГБ RAM | 8 CPU, 16 ГБ RAM для групп с >50 проектами |
| **Runner** | 2 CPU, 4 ГБ RAM | 4 CPU, 8 ГБ RAM для параллельных сканирований |
| **Диск** | 50 ГБ SSD | 200 ГБ+ SSD для артефактов и кэша сканеров |
| **Сеть** | 1 Гбит/с | Стабильный доступ к GitLab API и registry |

#### Программные требования

| Компонент | Минимум | Рекомендация | Проверка |
|:---|:---|:---|:---|
| **GitLab** | 17.0 | 19.3+ | `gitlab-rake gitlab:env:info` |
| **GitLab Runner** | 17.0 | 19.3+ | `gitlab-runner --version` |
| **Docker** | 24.0+ | 27.0+ | `docker --version` |
| **Registry** | Доступен | Приватный registry с TLS | `curl -k https://registry.example.com/v2/` |

#### Предустановки и конфигурация

1.  **Включите security scanning:** Settings → CI/CD → Security → включите SAST, DAST, Secret Detection, Dependency Scanning, Container Scanning.
2.  **Настройте Protected branches:** Settings → Repository → Protected branches для main/production.
3.  **Создайте `.gitlab/CODEOWNERS`:** Для назначения security-ревьюверов.
4.  **Настройте Protected environments:** Settings → CI/CD → Environments → Protected environments для production.
5.  **Включите push protection:** Settings → CI/CD → Security → Secret Detection → Push protection (Premium/Ultimate).
6.  **Настройте registry:** Убедитесь, что `CI_REGISTRY` и `CI_REGISTRY_USER` настроены для приватного registry.
7.  **Включите Security Dashboard:** Settings → Security & Compliance → Security Dashboard → включите для группы.

### Сценарий 1: Базовый пайплайн с полным security-сканированием

```yaml
stages:
  - build
  - test
  - security
  - deploy

variables:
  SAST_EXCLUDED_PATHS: "spec, test, tests, vendor"
  DEPENDENCY_SCANNING_EXCLUDED_PATHS: "spec, test, tests, vendor"

build:
  stage: build
  image: golang:1.22
  script:
    - go build -o myapp .
  artifacts:
    paths:
      - myapp

test:
  stage: test
  image: golang:1.22
  script:
    - go test -v ./...

# SAST: статический анализ кода
sast:
  stage: security
  include:
    - template: Security/SAST.gitlab-ci.yml
  variables:
    SAST_EXCLUDED_PATHS: "spec, test, vendor"

# Secret Detection: поиск секретов
secret_detection:
  stage: security
  include:
    - template: Security/Secret-Detection.gitlab-ci.yml
  variables:
    SECRET_DETECTION_EXCLUDED_PATHS: "spec, test, vendor"

# Dependency Scanning: анализ зависимостей
dependency_scanning:
  stage: security
  include:
    - template: Security/Dependency-Scanning.gitlab-ci.yml
  variables:
    DEPENDENCY_SCANNING_EXCLUDED_PATHS: "spec, test, vendor"

# Container Scanning: анализ Docker-образа
container_scanning:
  stage: security
  include:
    - template: Security/Container-Scanning.gitlab-ci.yml
  variables:
    CS_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  dependencies:
    - build

deploy:
  stage: deploy
  image: alpine:latest
  script:
    - echo "Deploying..."
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
```bash
# 1. Проверка: pipeline завершается успешно, security reports сгенерированы
# 2. В Merge Request: вкладка Security показывает findings
# 3. При Critical уязвимости: pipeline падает (если настроен allow_failure: false)
# 4. В Security Dashboard: findings агрегируются по проекту
# 5. При secrets в коде: Secret Detection блокирует merge (Premium/Ultimate)
```

### Сценарий 2: Кастомный DAST с предварительным развертыванием

```yaml
stages:
  - build
  - deploy
  - dast

variables:
  DAST_WEBSITE: "https://staging.example.com"

build:
  stage: build
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

deploy_staging:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/my-app my-app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA -n staging
    - kubectl rollout status deployment/my-app -n staging --timeout=300s

dast:
  stage: dast
  include:
    - template: Security/DAST.gitlab-ci.yml
  variables:
    DAST_WEBSITE: "https://staging.example.com"
    DAST_BROWSER_SCAN: "true"
  allow_failure: true
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# 1. Проверка: приложение развернуто в staging
# 2. DAST сканирует staging.example.com
# 3. В MR видны DAST findings (если allow_failure: false)
# 4. При недоступности DAST_WEBSITE: пайплайн падает с timeout
# 5. Проверка: DAST_FULL_SCAN_ENABLED управляет глубиной сканирования
```

### Сценарий 3: Принудительное сканирование через Pipeline Execution Policy

```yaml
# В security policy проекте (.gitlab/security-policies.yml)
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
```

**Валидация:**
```bash
# 1. Проверка: политика активна в группе
# 2. При push в main: SAST и Dependency Scanning запускаются автоматически
# 3. При отключенном сканировании в .gitlab-ci.yml: политика принудительно включает его
# 4. В Audit Events: фиксируется применение политики
# 5. Для MR: политика инжектирует сканирование даже если проект его отключил
```

### Сценарий 4: Агрегация security reports в downstream пайплайн

```yaml
# Родительский пайплайн
stages:
  - build
  - test
  - security

build:
  stage: build
  script: [echo "build"]

security_scan:
  stage: security
  script:
    - echo "Running security scans..."
  artifacts:
    reports:
      sast: sast-report.json
      dependency_scanning: dependency-report.json
    paths:
      - sast-report.json
      - dependency-report.json

trigger_downstream:
  stage: security
  trigger:
    project: security/aggregator
    branch: main
  strategy: depend
```

**Валидация:**
```bash
# 1. Проверка: downstream пайплайн получает reports artifacts
# 2. В downstream: Security Dashboard агрегирует findings из нескольких проектов
# 3. При потере артефактов: strategy: depend гарантирует передачу
# 4. Проверка: downstream пайплайн имеет доступ к security reports
```

### Сценарий 5: Container Scanning с приватным Registry

```yaml
container_scanning:
  stage: security
  include:
    - template: Security/Container-Scanning.gitlab-ci.yml
  variables:
    CS_IMAGE: registry.example.com/myapp:$CI_COMMIT_SHORT_SHA
    CS_REGISTRY_URL: registry.example.com
    CS_AUTH_TOKEN: $REGISTRY_TOKEN
  script:
    - echo "$CS_REGISTRY_URL"
    - echo "$CS_AUTH_TOKEN" | docker login $CS_REGISTRY_URL -u $CI_REGISTRY_USER --password-stdin
```

**Валидация:**
```bash
# 1. Проверка: registry.example.com доступен из Runner'а
# 2. Проверка: $REGISTRY_TOKEN имеет права на чтение образа
# 3. Проверка: gl-container-scanning-report.json содержит CVE
# 4. При неверном токене: container_scanning падает с authentication error
# 5. Для air-gapped: используйте registry mirror с кэшированием
```

## Operations and Commands

### Ручной запуск сканирования

```bash
# Запуск пайплайна с security scanning вручную
gitlab-runner exec docker sast --builds-dir /tmp/builds

# Или через GitLab API
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"ref": "main"}' \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipeline"
```

### Просмотр отчетов

```bash
# Скачивание security report через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/jobs/$JOB_ID/artifacts/gl-sast-report.json" \
  -o sast-report.json

# Просмотр findings через CLI (glab)
glab api projects/$PROJECT_ID/security/findings | jq '.[] | select(.severity=="Critical")'

# Фильтрация по scanner
glab api projects/$PROJECT_ID/security/findings?scanner=sast | jq '.[] | {title, severity, location}'
```

### Обновление analyzer images

```bash
# Проверка текущих версий analyzer images
docker images | grep registry.gitlab.com/security-products

# Принудительное обновление analyzer image
gitlab-runner exec docker sast --builds-dir /tmp/builds \
  --env SAST_ANALYZER_IMAGE_TAG=5

# В self-hosted: обновление registry mirror
docker pull registry.gitlab.com/security-products/sast:latest
docker tag registry.gitlab.com/security-products/sast:latest registry.example.com/security/sast:latest
docker push registry.example.com/security/sast:latest
```

### Отладка сканеров

```bash
# Запуск сканера в debug режиме
sast:
  stage: security
  variables:
    SAST_DEBUG: "true"
    LOG_LEVEL: "debug"
  script:
    - echo "Debug mode enabled"

# Просмотр логов Scanner'а
docker logs <analyzer_container_id> --tail 100

# Проверка конфигурации Scanner'а
docker run --rm registry.gitlab.com/security-products/sast:latest --help
```

## Лучшие практики

### Безопасность

1.  **Включайте все сканеры по умолчанию**: SAST, Secret Detection, Dependency Scanning, Container Scanning.
2.  **Используйте Pipeline Execution Policies**: Принудительное сканирование на уровне группы предотвращает обход проверок.
3.  **Настройте MR Approval Rules**: Блокируйте merge при наличии Critical/High уязвимостей.
4.  **Используйте Allow-lists**: Исключайте тесты и сгенерированный код из SAST/Secret Detection.
5.  **Регулярно обновляйте сканеры**: GitLab обновляет базы сигнатур автоматически, но для self-hosted проверяйте версии.
6.  **Rotate registry tokens**: Периодически ротируйте токены доступа к registry.
7.  **Настройте Quality Gates**: Блокируйте merge при Critical уязвимостях (`allow_failure: false`).

### Организация

1.  **Групповые политики**: Настраивайте сканирование на уровне группы, а не проекта.
2.  **Исключайте тесты**: `SAST_EXCLUDED_PATHS`, `SECRET_DETECTION_EXCLUDED_PATHS`.
3.  **Используйте custom rules**: Semgrep поддерживает кастомные правила для внутренних стандартов.
4.  **SBOM Generation**: Генерируйте SBOM для каждого артефакта через `syft` или `trivy`.
5.  **Centralized policy management**: Храните политики в security policy проекте, а не в каждом `.gitlab-ci.yml`.

### Производительность

1.  **Параллельное сканирование**: Запускайте SAST, DAST, Dependency Scanning параллельно через DAG (`needs`).
2.  **Кэширование зависимостей**: Ускоряет Dependency Scanning (Grype кэширует базу CVE).
3.  **Инкрементальное сканирование**: Используйте `rules:changes` для запуска сканирования только при изменении затронутых файлов.
4.  **Ограничьте DAST**: Запускайте DAST только для protected branches, используйте `allow_failure: true`.
5.  **Интервал опроса**: Устанавливайте `check_interval = 1` для production-раннеров.

### Sysadmin: эксплуатация инфраструктуры сканирования

1.  **Analyzer image mirroring**: В air-gapped средах настройте registry mirror для analyzer images.
    ```bash
    # Настройка mirror в config.toml
    [runners.docker]
      image = "registry.example.com/security/analyzers/sast:latest"
    ```
2.  **Мониторинг scanner health**: Мониторьте метрики выполнения сканеров (время, OOM, failures) через Prometheus.
3.  **Резервное копирование reports**: Настройте экспорт security reports в долговременное хранилище для compliance.
4.  **Очистка артефактов**: Устанавливайте `expire_in` для security reports (рекомендуется 90 дней).
5.  **Capacity planning**: Планируйте capacity для Runner'ов исходя из пикового количества параллельных сканирований.

## Особенности и ограничения (Edge Cases)

### Лимиты и совместимость

| Параметр | Лимит | Примечание |
|:---|:---|:---|
| Максимум security reports на MR | 1000 findings | При превышении отчет обрезается |
| SAST: максимальный размер файла | 10 MB | Большие файлы пропускаются |
| Secret Detection: минимальная длина | 4 символа | Короткие строки игнорируются |
| Container Scanning: максимальный размер образа | 2 GB | При превышении сканирование прерывается |
| Dependency Scanning: максимальное количество зависимостей | 10000 | При превышении отчет обрезается |

### Несовместимость

| Конфликт | Описание | Решение |
|:---|:---|:---|
| SAST + не-Software-устройства | Semgrep не работает для non-Software проектов | Используйте custom SAST analyzer |
| DAST + аутентификация | DAST требует доступ к работающему приложению | Настройте `DAST_AUTH_URL` и credentials |
| Secret Detection + бинарные файлы | Сканер не анализирует бинарники | Используйте `SECRET_DETECTION_EXCLUDED_PATHS` |
| Container Scanning + multi-stage builds | Сканер анализирует только последний слой | Используйте `CS_IMAGE` с явным тегом |

### Версионная совместимость

| Функция | Минимальная версия | Примечание |
|:---|:---|:---|
| Встроенные security templates | 13.9+ | SAST, DAST, Secret Detection |
| Security Dashboard | 14.0+ | Агрегация findings across projects |
| Pipeline Execution Policies | 17.3+ | Принудительное сканирование |
| Scheduled Execution Policies | 19.2+ | Регулярное сканирование группы |
| Dependency Scanning (Grype) | 16.0+ | Замена Gemnasium |
| Container Scanning (Trivy) | 16.0+ | Замена Clair |

### Air-gapped среды

*   **Analyzer images:** В air-gapped средах сканеры недоступны из registry.gitlab.com. Настройте mirror registry и переопределите `SAST_ANALYZER_IMAGE_PREFIX`, `DAST_ZAP_IMAGE` и т.д.
*   **Vulnerability databases:** Сканеры (Grype, Trivy) требуют обновления баз CVE. Настройте периодическое обновление через cron на отдельном хосте с доступом к интернету.
*   **License Scanning:** В air-gapped средах License Finder требует локального кэша license-данных.

### Fork pipelines

*   **По умолчанию** fork pipelines имеют доступ к masked/protected variables. Отключите это в Settings → CI/CD → General pipelines → "Pipelines for contributed projects" → "No variables from the fork project".
*   **Security scanning** в fork pipelines может быть отключен через `workflow: rules` или `if: $CI_PROJECT_NAMESPACE == $CI_PROJECT_NAMESPACE`.

### Ресурсы и производительность

*   **Ограничение параллельности:** Настройте `concurrent` в `config.toml` для Runner'ов, выполняющих security scanning, чтобы избежать исчерпания ресурсов.
*   **Timeout:** Устанавливайте `timeout` для security задач (например, 30m для DAST, 10m для SAST).
*   **Memory limits:** Для SAST на больших репозиториях увеличьте `memory` в `config.toml` или используйте `resource_group` для последовательного выполнения.
*   **Интервал опроса:** Для security-first пайплайнов уменьшите `check_interval` до 1-3 секунд для быстрого получения задач.

## Дополнительная информация

*   **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — пятислойная архитектура безопасности, три уровня раннеров, защита артефактов.
*   **[Compliance и Audit в GitLab CI/CD](../Advanced/compliance_and_audit.md)** — Pipeline Execution Policies, Compliance Frameworks, Audit Trail.
*   **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — методология управления секретами.
*   **[Supply Chain Security](../../DevSecOps/iac-security-defense-in-depth.md)** — SBOM, cosign, VEX.
*   **[Security Scanning — глубинное погружение](../Tutorials/security_scanning_deep_dive.md)** — продвинутые сценарии: polyglot SAST, pre-commit Secret Detection, multi-stage Container Scanning, DAST для Kubernetes.
*   **[GitLab Docs: Security Scanning](https://docs.gitlab.com/ee/user/application_security/)** — официальная документация.

> **Критичные изменения последних версий:**
>
> *   **19.2**: Scheduled Execution Policies для регулярного сканирования группы.
> *   **19.0**: Dependency Scanning перешел на Grype (замена Gemnasium).
> *   **18.0**: Удален `CI_JOB_JWT` в пользу `id_tokens` для OIDC.
> *   **17.3**: Compliance Pipelines устарели; заменены на Pipeline Execution Policies.
