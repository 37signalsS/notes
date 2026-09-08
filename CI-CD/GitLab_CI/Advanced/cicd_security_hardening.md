# CI/CD Security Hardening

## Определения

**CI/CD Security Hardening** — процесс укрепления безопасности пайплайнов, Runner'ов и инфраструктуры CI/CD от угроз: утечки секретов, комппрометации зависимостей, несанкционированного доступа и supply chain атак.

**Supply Chain Attack** — атака на инфраструктуру разработки (CI/CD, зависимости, инструменты) для компрометации конечного продукта.

**CI/CD Pipeline Poisoning** — модификация пайплайна для выполнения вредоносного кода (например, через изменение `.gitlab-ci.yml`).

**Least Privilege в CI/CD** — принцип предоставления Runner'ам и переменным только минимально необходимых прав.

## Теоретический блок

### Угрозы CI/CD

| Угроза | Описание | Критичность | Митигация |
|:---|:---|:---|:---|
| **Secrets leak** | Утечка токенов, ключей через логи | Критическая | Masking, скрытые переменные |
| **Dependency confusion** | Подмена зависимостей | Высокая | Lock files, приватные репозитории |
| **Pipeline injection** | Внедрение кода в пайплайн | Критическая | Protected branches, CODEOWNERS |
| **Runner compromise** | Компрометация Runner'а | Критическая | Isolation,ephemeral runners |
| **Artifact tampering** | Подмена артефактов | Высокая | Checksums, signed artifacts |
| **Registry poisoning** | Подмена Docker images | Высокая | Image scanning, signing |
| **Fork-based attacks** | Атаки через forks MR | Средняя | Fork pipelines off |
| **Variable exposure** | Утечка переменных в логах | Высокая | Masking, protected vars |

### Уровни защиты

| Уровень | Компонент | Меры защиты |
|:---|:---|:---|
| **GitLab Server** | Настройки проекта | Protected branches, CODEOWNERS, MR approvals |
| **Pipeline** | `.gitlab-ci.yml` | Rules, secrets masking, timeout |
| **Runner** | `config.toml` | Privileged=false, isolation, tags |
| **Dependencies** | `package-lock.json` | Hash verification, private registry |
| **Artifacts** | Архефакты пайплайна | Checksums, expiration, signing |
| **Registry** | Docker images | Scanning, signing, immutable tags |

### Best Practices矩阵

| Практика | Важность | Сложность | Приоритет |
|:---|:---|:---|:---|
| Masking секретов в переменных | Критическая | Низкая | P0 |
| Protected branches для main | Критическая | Низкая | P0 |
| Runner без privileged | Критическая | Низкая | P0 |
| Dependency scanning | Высокая | Средняя | P1 |
| Container scanning | Высокая | Средняя | P1 |
| Secret detection в коммитах | Высокая | Низкая | P1 |
| Pipeline approval для prod | Высокая | Средняя | P1 |
| Signed artifacts/images | Средняя | Высокая | P2 |
| Network policies для Runner'ов | Средняя | Средняя | P2 |
| Audit logging | Средняя | Низкая | P2 |

## Практический блок

### Защита переменных

```yaml
# Сокрытие переменных в логах
variables:
  DATABASE_URL: "postgres://user:${DB_PASSWORD}@db:5432/app"
  DB_PASSWORD:
    value: "supersecret"
    masked: true  # Не отображается в логах
    protected: true  # Только для protected branches
    expand: false  # Не раскрывается в переменных

# Специальные masked переменные
deploy_token:
  value: "glpat-xxxxxxxxxxxx"
  masked: true
  protected: true
  file: true  # Ссылается на файл
```

### Protected branches и approvals

```yaml
# Правила для protected branches
workflow:
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      variables:
        DEPLOY_ENV: "production"
    - if: $CI_COMMIT_BRANCH =~ /^(develop|feature\/.*)$/
      variables:
        DEPLOY_ENV: "staging"

# Требования к approval для production
# (настраивается в GitLab UI: Settings → Merge requests)
# - Minimum 2 approvals
# - Code owners must approve
# - Pipelines must succeed
# - Discussion must be resolved
```

### Защита Runner'ов

```toml
# /etc/gitlab-runner/config.toml — hardened
[[runners]]
  name = "hardened-runner"
  executor = "docker"
  
  # НЕ используйте privileged без необходимости
  [runners.docker]
    privileged = false
    
    # Ограничение capabilities
    cap_add = ["NET_ADMIN"]
    cap_drop = ["ALL"]
    
    # Запрет привилегий
    security_opt = ["no-new-privileges:true"]
    
    # Read-only rootfs
    readonly_rootfs = true
    
    # Ограничение сети
    network_mode = "gitlab-isolated"
    
    # Таймаут
    shutdown_timeout = 30
    
  # Метрики для мониторинга
  metrics_server = ":9252"
```

### Secret Detection в коммитах

```yaml
# .gitlab-ci.yml — детекция секретов
secret_detection:
  stage: .pre
  image: 
    name: zricethezav/gitleaks:latest
    entrypoint: [""]
  script:
    - gitleaks detect --source=. --report-format=json --report-path=gitleaks-report.json
  artifacts:
    paths: [gitleaks-report.json]
    when: always
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Использование GitLab Built-in Secret Detection
# (включается в Settings → CI/CD → Secret Detection)
```

### Dependency scanning

```yaml
# Сканирование зависимостей
dependency_scanning:
  stage: .pre
  image: 
    name: aquasec/trivy:latest
    entrypoint: [""]
  script:
    - trivy fs --format json --output dependency-results.json .
    - trivy fs --severity HIGH,CRITICAL --exit-code 1 .
  artifacts:
    paths: [dependency-results.json]
    when: always
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Docker image scanning
container_scanning:
  stage: .post
  image:
    name: aquasec/trivy:latest
    entrypoint: [""]
  script:
    - trivy image --format json --output image-results.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - trivy image --severity HIGH,CRITICAL --exit-code 1 $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  artifacts:
    paths: [image-results.json]
    when: always
```

### Pipeline security best practices

```yaml
# Безопасный пайплайн
stages:
  - security
  - build
  - test
  - deploy

# 1. Проверка целостности .gitlab-ci.yml
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

# 3. Использование only/except для контроля запуска
deploy:production:
  stage: deploy
  script:
    - ./deploy.sh
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
      allow_failure: false
    - when: never

# 4. Защита артефактов
artifacts:
  paths: [build/]
  expire_in: 1 week
  when: on_success
  reports:
    junit: test-results.xml
```

### Audit logging

```yaml
# Логирование действий в CI/CD
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
    - cat audit.log
  artifacts:
    paths: [audit.log]
    when: always
  rules:
    - when: always
```

## Дополнительная информация

### Связанные темы
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — работа с переменными
- **[Защита в Kubernetes](../Tutorials/gitlab_kubernetes_integration_guide.md)** — безопасность в K8s
- **[Интеграция Vault](../Tutorials/vault_kubernetes_integration.md)** — управление секретами
- **[Docker Compose безопасность](../Tutorials/gitlab_runner_docker_compose.md)** — настройка Runner'ов

### Чек-лист безопасности
- [ ] masked=true для всех секретов
- [ ] protected=true для production переменных
- [ ] Runner без privileged (если не критично)
- [ ] Secret detection включён
- [ ] Dependency scanning включён
- [ ] Container scanning включён
- [ ] Protected branches настроены
- [ ] CODEOWNERS файл создан
- [ ] Pipeline approval для production
- [ ] Audit logging включён
- [ ] Timeout настроен для всех задач
- [ ] Fork pipelines отключены
