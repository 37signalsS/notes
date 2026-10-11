# CI/CD Security Hardening

**Актуально для:** GitLab 19.x / GitLab Runner 19.x

## Определения

Общие определения CI/CD Security Hardening, Supply Chain Attack, Least Privilege, RBAC и другие описаны в **[Усиление безопасности CI/CD](../Core_Concepts/ci_cd_security_hardening.md)**. Ниже — GitLab-специфичные дополнения.

**Protected branch** — ветка, для которой включены ограничения на push, merge и деплой. В GitLab настраивается в Settings → Repository → Protected branches.

**CODEOWNERS** — файл `.gitlab/CODEOWNERS`, определяющий ответственных за части кода. GitLab требует approval от code owner для merge в protected branch.

**GitLab Secret Detection** — встроенный сканер секретов в коммитах, основанный на GitLab Secret Detection (аналог gitleaks). Включается в CI/CD → Security → Secret Detection или через template `Security/Secret-Detection.gitlab-ci.yml`.

**GitLab Dependency Scanning** — встроенный сканер зависимостей, основанный на Grype. Включается через template `Security/Dependency-Scanning.gitlab-ci.yml`.

**GitLab Container Scanning** — встроенный сканер Docker-образов, основанный на Trivy. Включается через template `Security/Container-Scanning.gitlab-ci.yml`.

**GitLab SAST** — статический анализ кода через интеграцию с Semgrep. Включается через template `Security/SAST.gitlab-ci.yml`.

**GitLab DAST** — динамический анализ работающего приложения. Включается через template `Security/DAST.gitlab-ci.yml`.

**Environment protection** — защита окружений (production, staging) через approval rules. Настраивается в Settings → CI/CD → Environments → Protected environments.

**Push protection** — блокировка push при обнаружении секретов в коммите. Работает через GitLab Secret Detection push protection (Premium/Ultimate).

## Основные концепции

### Архитектура безопасности GitLab CI/CD

Безопасность GitLab CI/CD строится на пяти слоях:

1. **GitLab Server / Групповые политики** — Protected branches, CODEOWNERS, MR approval rules, push rules, group-level security policies.
2. **Проект / .gitlab-ci.yml** — rules, timeout, only/except, artifacts, secret detection jobs, dependency scanning jobs.
3. **Runner / config.toml** — privileged=false, cap_drop, security_opt, readonly_rootfs, ephemeral runners, tags, metrics.
4. **Зависимости / Registry** — lock files, private registry, image scanning, signing (cosign), SBOM.
5. **Артефакты / Supply Chain** — checksums, signing, SBOM, expiration, immutable tags.

### Уровни защиты GitLab CI/CD

| Уровень | Компонент | Меры защиты |
|:---|:---|:---|
| **GitLab Server** | Настройки проекта/группы | Protected branches, CODEOWNERS, MR approvals, push rules |
| **Pipeline** | `.gitlab-ci.yml` | Rules, secrets masking, timeout, protected variables |
| **Runner** | `config.toml` | Privileged=false, isolation, tags, ephemeral |
| **Dependencies** | `package-lock.json`, образы | Lock files, private registry, scanning |
| **Artifacts** | Артефакты пайплайна | Checksums, expiration, signing |
| **Registry** | Docker images | Scanning, signing, immutable tags |

### Три уровня безопасности раннеров

| Тип | Назначение | Характеристики |
|:---|:---|:---|
| **Shared Runner** | Общий пул для всех проектов | Требует тегов, без privileged, без доступа к продовым секретам |
| **Protected Runner** | Только для protected branches | Доступ к продовым секретам, изоляция от shared runners |
| **Ephemeral Runner** | Одноразовый, уничтожается после job | Максимальная изоляция, подходит для untrusted код (forks) |

## Практические сценарии

### Предварительные требования

**Аппаратные требования:**
- GitLab Server: 4 CPU, 8 ГБ RAM, 50 ГБ SSD (минимум для small team)
- Runner: 2 CPU, 4 ГБ RAM, 20 ГБ SSD на инстанс
- Сеть: latency между GitLab Server и Runner'ами < 50 ms

**Программные требования:**
- GitLab 19.x (CE или EE)
- GitLab Runner 19.x
- gitleaks или GitLab Secret Detection
- Trivy 0.74+ (для сканирования зависимостей и образов)

**Инициализация:**
1. Включите GitLab Secret Detection в Settings → CI/CD → Security → Secret Detection или добавьте template job.
2. Включите Dependency Scanning и Container Scanning через template jobs.
3. Настройте Protected branches для main/production в Settings → Repository.
4. Создайте `.gitlab/CODEOWNERS` файл.
5. Настройте Protected environments в Settings → CI/CD → Environments.
6. Включите push protection для Secret Detection (Premium/Ultimate).

### Сценарий 1: Защита переменных и секретов

```yaml
# .gitlab-ci.yml — безопасные переменные
variables:
  DATABASE_URL: "postgres://user:${DB_PASSWORD}@db:5432/app"
  DB_PASSWORD:
    value: "supersecret"
    masked: true       # Не отображается в логах
    protected: true    # Только для protected branches
    expand: false      # Не раскрывается в переменных

  deploy_token:
    value: "glpat-xxxxxxxxxxxx"
    masked: true
    protected: true
    file: true         # Ссылается на файл
```

**Валидация:**
```bash
# Проверка: секреты не попадают в логи
# При echo $DB_PASSWORD в логах будет [MASKED]
# При попытке доступа из non-protected branch переменная не доступна
```

### Сценарий 2: Protected branches и CODEOWNERS

```yaml
# .gitlab/CODEOWNERS
# /* @team-frontend
# /infrastructure/* @team-sre
# /docker/* @team-devops
# *.tf @team-iac
# *.py @team-backend

# .gitlab-ci.yml — правила для protected branches
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      variables:
        DEPLOY_ENV: "production"
    - if: $CI_COMMIT_BRANCH =~ /^(develop|feature\/.*)$/
      variables:
        DEPLOY_ENV: "staging"

deploy:production:
  stage: deploy
  script:
    - ./deploy.sh
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
      allow_failure: false
  environment:
    name: production
    url: https://app.example.com
```

**Валидация:**
- Merge request в main требует approval от code owner
- Деплой в production требует manual approval
- Push в main заблокирован без MR

### Сценарий 3: Защита Runner'ов

```toml
# /etc/gitlab-runner/config.toml — hardened
[[runners]]
  name = "hardened-runner"
  executor = "docker"

  [runners.docker]
    privileged = false

    # Ограничение capabilities
    cap_add = ["NET_ADMIN"]
    cap_drop = ["ALL"]

    # Запрет привилегий
    security_opt = ["no-new-privileges:true"]

    # Read-only rootfs
    readonly_rootfs = true

    # Таймаут
    shutdown_timeout = 30

    # Ограничение ресурсов
    memory = "4g"
    cpus = "2"

  # Метрики для мониторинга
  metrics_server = ":9252"
```

**Валидация:**
```bash
# Проверка конфигурации Runner'а
gitlab-runner verify
# → Runner=... verified

# Проверка безопасности контейнера
docker inspect <container_id> | grep -E "SecurityOpt|ReadonlyRootfs"
# → "SecurityOpt": ["no-new-privileges:true"]
# → "ReadonlyRootfs": true
```

### Сценарий 4: Secret Detection в коммитах

```yaml
# .gitlab-ci.yml — детекция секретов через GitLab Secret Detection
secret_detection:
  stage: .pre
  image:
    name: registry.gitlab.com/security-products/secret-detection:19.3.0
    entrypoint: [""]
  script:
    - secret-detection
  artifacts:
    paths: [gl-secret-detection-report.json]
    when: always
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# При наличии секрета в коде пайплайн падает с ошибкой
# gl-secret-detection-report.json содержит детали находки
# Push protection блокирует коммит с секретом (Premium/Ultimate)
```

### Сценарий 5: Dependency Scanning

```yaml
# .gitlab-ci.yml — сканирование зависимостей через GitLab Dependency Scanning
dependency_scanning:
  stage: .pre
  image:
    name: registry.gitlab.com/security-products/dependency-scanning:19.3.0
    entrypoint: [""]
  script:
    - dependency-scanning
  artifacts:
    paths: [gl-dependency-scanning-report.json]
    when: always
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Валидация:**
```bash
# gl-dependency-scanning-report.json содержит список CVE
# В UI GitLab: Pipeline → dependency_scanning → детали уязвимостей
# При критичных CVE пайплайн падает (если настроен quality gate)
```

### Сценарий 6: Container Scanning

```yaml
# .gitlab-ci.yml — сканирование Docker-образа
container_scanning:
  stage: .post
  image:
    name: registry.gitlab.com/security-products/container-scanning:19.3.0
    entrypoint: [""]
  script:
    - container-scanning
  artifacts:
    paths: [gl-container-scanning-report.json]
    when: always
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# gl-container-scanning-report.json содержит CVE в образе
# В UI GitLab: Pipeline → container_scanning → детали уязвимостей
# Для подписи образа используйте cosign (см. Сценарий 8)
```

### Сценарий 7: Audit logging в GitLab

```yaml
# .gitlab-ci.yml — аудит действий CI/CD
audit_log:
  stage: .post
  image: alpine:latest
  script:
    - |
      echo "=== CI/CD Audit Log ===" >> audit.log
      echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> audit.log
      echo "Pipeline ID: $CI_PIPELINE_ID" >> audit.log
      echo "Project: $CI_PROJECT_PATH" >> audit.log
      echo "Branch: $CI_COMMIT_BRANCH" >> audit.log
      echo "User: $GITLAB_USER_LOGIN" >> audit.log
      echo "Action: $CI_JOB_ACTION" >> audit.log
      echo "========================" >> audit.log
  artifacts:
    paths: [audit.log]
    when: always
  rules:
    - when: always
```

**Валидация:**
```bash
# audit.log сохраняется как артефакт каждого пайплайна
# Для централизованного сбора используйте GitLab Audit Events API
# Включите audit logging в Admin Area → Settings → Audit Events
```

### Сценарий 8: Подписание артефактов (cosign) и SBOM

```bash
# Подписание Docker-образа после сборки
cosign generate-key-pair            # локальный ключ
cosign sign --key cosign.key $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

# Keyless подпись через GitLab OIDC (GitLab 17+)
COSIGN_EXPERIMENTAL=1 cosign sign --yes \
  --certificate-identity-regexp '^https://gitlab\.com/org/.*$' \
  --certificate-oidc-issuer https://gitlab.com \
  $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

# Верификация образа перед деплоем
cosign verify --key cosign.pub $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
```

**Генерация SBOM:**
```bash
# Установка Syft
brew install syft

# Генерация SBOM в формате CycloneDX
syft $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA -o cyclonedx-json > sbom.json

# Attestation SBOM к образу
cosign attest --predicate sbom.json --type cyclonedx \
  $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
```

**Валидация:**
```bash
# cosign sign записывает attestation в registry
# cosign verify возвращает "Verified" для подписанного образа
# При подмене манифеста верификация падает с ненулевым кодом
# SBOM доступен через cosign triangulate
```

### Сценарий 9: CI_JOB_TOKEN безопасность

```yaml
# .gitlab-ci.yml — безопасное использование CI_JOB_TOKEN
variables:
  CI_JOB_TOKEN:
    masked: true
    protected: true

# Внутренний вызов API (в рамках проекта)
trigger_downstream:
  stage: deploy
  script:
    - curl --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{"ref": "main"}' \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/trigger/pipeline"

# Registry access
docker_login:
  stage: build
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
```

**Валидация:**
- CI_JOB_TOKEN по умолчанию имеет scope проекта
- Начиная с GitLab 18.0, межпроектные вызовы требуют inbound allowlist
- Никогда не передавайте CI_JOB_TOKEN наружу через SSH
- Проверяйте, что токен не попадает в артефакты

**Настройка inbound allowlist:**
1. Перейдите в `Settings → CI/CD → Token Access`
2. Включите `Authorized groups and projects`
3. Добавьте проекты/группы, которым разрешено обращаться к текущему проекту

### Сценарий 10: Push rules и валидация коммитов

```yaml
# Включение push rules через GitLab API
push_rules:
  stage: .pre
  script:
    - |
      # Установка push rules через API
      curl --request PUT \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{
          "commit_message_regex": "^(feat|fix|docs|chore|refactor|test|build|ci|revert|perf|style|merge)(\(.+\))?: .{1,100}",
          "prevent_secrets": true,
          "author_email_regex": "^[a-zA-Z0-9._%+-]+@example\\.com$",
          "file_name_regex": "^(?!.*\\.(env|secret|key)$).*$",
          "max_file_size": 10485760
        }' \
      "$CI_API_V4_URL/projects/$CI_PROJECT_ID/push_rule"
```

**Валидация:**
- Push отклоняется при несоответствии сообщения коммита regex
- Push отклоняется при обнаружении секретов в файлах
- Push отклонён, если email автора не входит в whitelist

### Сценарий 11: CODEOWNERS и approval policies

```yaml
# .gitlab/CODEOWNERS
# Обязательный ревью для инфраструктуры
/terraform/**/* @devops-team
/ansible/**/* @devops-team
/kubernetes/**/* @devops-team

# Обязательный ревью для безопасности
/security/**/* @security-team
/audit/**/* @security-team

# Обязательный ревью для production кода
/src/**/* @backend-team
/frontend/**/* @frontend-team
```

**Настройка approval policies:**
```yaml
# GitLab 19.0+: Deployment Approval Policy
# Settings → CI/CD → Deployment approval policy
# - Требует 2 approve от Maintainer для production
# - Автоматически назначает code owners из CODEOWNERS
# - TTL approval: 24 часа
```

### Сценарий 9: Pipeline security best practices

```yaml
# .gitlab-ci.yml — безопасный пайплайн
stages:
  - security
  - build
  - test
  - deploy

# 1. Проверка целостности пайплайна
verify_pipeline:
  stage: security
  image: alpine:latest
  script:
    - echo "Verifying pipeline integrity..."
    - echo "Pipeline source: $CI_PIPELINE_SOURCE"
    - echo "Commit: $CI_COMMIT_SHA"
    - echo "Branch: $CI_COMMIT_BRANCH"
  rules:
    - when: always

# 2. Ограничение времени выполнения jobs
build:
  stage: build
  timeout: 30m
  script:
    - ./build.sh

# 3. Защита артефактов
artifacts:
  paths: [build/]
  expire_in: 1 week
  when: on_success
  reports:
    junit: test-results.xml
```

**Валидация:**
- Jobs без timeout завершаются автоматически через 30m
- Артефакты удаляются через 1 неделю
- Fork pipelines не имеют доступа к protected variables

### Сценарий 10: Отключение fork pipelines

```yaml
# .gitlab-ci.yml — отключение пайплайнов из forks
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH != "main"
```

**Валидация:**
- Fork MR создаёт пайплайн, но без доступа к protected variables и protected runners
- Деплой в production возможен только из основного проекта

## Устранение неполадок

### Типичные ошибки

| Симптом | Возможная причина | Диагностика | Решение |
|:---|:---|:---|:---|
| Секреты в логах | `masked: false` или переменная слишком короткая | Поиск по логам пайплайна | Установите `masked: true`, минимум 8 символов |
| `pipelines_finished_total` не появляется | GitLab версии < 19.2 | `curl /-/metrics \| grep pipelines_finished_total` | Обновите GitLab или используйте `gitlab_ci_pipeline_time_to_finished_seconds` |
| Secret Detection не находит секреты | Устаревший шаблон или отключен push protection | Проверка версии template | Обновите template до последней версии |
| Dependency Scanning пропускает файлы | Неподдерживаемый менеджер пакетов | Проверка Supported languages в документации | Используйте lock file или SBOM-генератор |
| Runner с privileges | `privileged = true` в config.toml | `cat /etc/gitlab-runner/config.toml` | Установите `privileged = false` |
| Fork получает доступ к секретам | Protected variables не настроены | Проверка Settings → CI/CD → Variables | Включите `protected: true` для продовых секретов |
| Container Scanning падает | Нет доступа к registry или образ не найден | Логи job container_scanning | Проверьте `CI_REGISTRY` и `CI_JOB_TOKEN` |
| CODEOWNERS не работает | Неправильный синтаксис или файл не в `.gitlab/` | Settings → Merge requests → Approval rules | Проверьте путь и синтаксис CODEOWNERS |

### Диагностические команды

```bash
# 1. Проверка настроек Protected branches
gitlab-rake gitlab:protected_branches:list
# → список protected branches

# 2. Проверка CODEOWNERS
gitlab-rake gitlab:code_owners:check
# → синтаксис и applicability code owners

# 3. Проверка Runner конфигурации
gitlab-runner verify
# → Runner=... verified

# 4. Проверка feature flags
gitlab-rake gitlab:feature_flags:list | grep builds_queuing
# → gitlab_ci_builds_queuing_metrics | enabled | false

# 5. Проверка Secret Detection
curl -sk -H "Authorization: Bearer $TOKEN" "https://gitlab.example.com/api/v4/projects/$ID/variables" | jq '.[] | select(.masked==true)'
# → список masked переменных

# 6. Проверка audit log
gitlab-rake gitlab:audit_log:list
# → последние события аудита
```

## Рекомендации

### При проектировании безопасности пайплайнов:
- Начинайте с 3 критичных мер: masked/protected переменные, Protected branches, Secret Detection.
- Настройте approval rules до создания пайплайнов. Approval без code owner — технический долг.
- Используйте ephemeral runners для untrusted код (forks, MR из внешних репозиториев).
- Отключайте fork pipelines или ограничивайте их доступ к секретам и protected runners.
- Регулярно пересматривайте список Protected branches и Environments.

### При настройке Runner'ов:
- Выставляйте `privileged = false` по умолчанию. Privileged нужен только для dind.
- Используйте `cap_drop = ["ALL"]` и добавляйте только необходимые capabilities.
- Настройте `readonly_rootfs = true` для дополнительной изоляции.
- Разделяйте Runner'ы по типам: shared (общие задачи), protected (только trusted), ephemeral (MR/forks).
- Мониторьте Runner метрики через `metrics_server = ":9252"`.

### При сборе SBOM и подписи артефактов:
- Определите, что считается "артефактом", до начала сбора. Зафиксируйте определение в runbook.
- Генерируйте SBOM на каждом build stage (syft в CycloneDX).
- Подписывайте образы через cosign с ключом или workload identity.
- Храните SBOM и подпись как артефакты пайплайна с retention policy.

### При настройке сканирования зависимостей:
- Включайте Dependency Scanning для всех проектов с кодом.
- Для frontend-проектов используйте `package-lock.json` или `npm audit`.
- Для backend-проектов используйте `go.sum`, `requirements.txt`, `Gemfile.lock`.
- Настройте quality gate: пайплайн падает при критичных CVE.

### При аудите и compliance:
- Включите GitLab Audit Events для отслеживания всех действий пользователей.
- Настройте retention для audit logs: минимум 90 дней.
- Используйте CODEOWNERS для автоматического назначения reviewers.
- Регулярно проверяйте список service accounts и их права.

## Дополнительная информация

### Связанные темы

- **[Усиление безопасности CI/CD](../../Core_Concepts/ci_cd_security_hardening.md)** — общие принципы, Least Privilege, SSH hardening, mTLS
- **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — OIDC, Vault, ротация и инциденты
- **[Эшелонированная защита в IaC](../../DevSecOps/iac-security-defense-in-depth.md)** — Trivy, Checkov, Cosign, SBOM
- **[Переменные и секреты GitLab CI/CD](../Concepts/gitlab_ci_variables_secrets.md)** — GitLab-specific переменные, masked/protected, GitLab Secrets Manager
- **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)** — SLI/SLO, трейсы, Golden Signals
- **[Incident Response для CI/CD](./incident_response_cicd.md)** — реагирование на инциденты, runbooks
- **[Метрики DORA](../../Core_Concepts/dora_metrics.md)** — Deployment Frequency, Lead Time, CFR, MTTR
- **[CI_JOB_TOKEN безопасность](./ci_job_token_security.md)** — allowlist, scope, attack vectors
- **[Resource Group и контроль пайплайнов](./resource_group_and_pipeline_control.md)** — мьютекс, concurrency, retry
- **[Changed files и workflow rules](./changed_files_and_workflow_rules.md)** — path filters, push rules, CODEOWNERS
- **[Dependency Proxy](./dependency_proxy.md)** — кеширование зависимостей, air-gapped
- **[Policy-as-Code](./policy_as_code.md)** — OPA, Checkov, TFLint, Trivy
- **[SBOM и подпись артефактов](./sbom_and_artifact_signing.md)** — Syft, Cosign, SLSA
- **[Развертывание через Docker Compose](../Tutorials/gitlab_runner_docker_compose.md)** — локальный стек GitLab + Runner

### Ограничения и edge cases

1. **GitLab Editions:** Secret Detection, Dependency Scanning, Container Scanning, SAST, DAST — доступны в GitLab Ultimate. В CE/EE доступны только базовые возможности (masked variables, protected branches). Для self-managed инстансов может потребоваться лицензия.
2. **Push protection:** Доступен только в GitLab Premium и Ultimate. В CE/EE используйте pre-commit hooks (gitleaks) как альтернативу.
3. **Protected runners:** Доступны только в GitLab Premium и Ultimate. В CE используйте tags и manual approval rules как компенсирующий контроль.
4. **Ephemeral runners:** В Docker executor ephemeral runners работают через `--ephemeral` флаг. В Kubernetes executor — через отдельный namespace с TTL.
5. **Feature flags:** Некоторые security-фичи (например, `gitlab_ci_builds_queuing_metrics`) требуют включения feature flags на инстансе. На GitLab.com они могут быть включены по умолчанию, на self-managed — нет.
6. **Cardinality:** Метрики с labels `project`, `ref`, `branch` имеют высокую кардинальность. При >10k projects в инстансе Prometheus TSDB может испытывать pressure. Используйте recording rules и агрегацию.
7. **Fork pipelines:** По умолчанию fork pipelines имеют доступ к masked/protected variables. Отключите это в Settings → CI/CD → General pipelines → "Pipelines for contributed projects" → "No variables from the fork project".
8. **Runner isolation:** Docker executor предоставляет изоляцию на уровне контейнера. Для критичных workloads используйте отдельный Runner pool с dedicated хостами.
9. **SBOM retention:** SBOM-артефакты могут занимать много места. Настройте `expire_in` для SBOM-артефактов (рекомендуется 90 дней для compliance).
10. **Сканирование в monorepo:** Trivy/Checkov могут долго работать на больших monorepo. Используйте инкрементальное сканирование (только изменённые файлы) и кэширование результатов.
