# Compliance и Audit в GitLab CI/CD

## Определения

- **Compliance в CI/CD** — соответствие нормативным требованиям (SOC2, ISO27001, HIPAA, PCI DSS) к процессам разработки и deployments. Обеспечивает соответствие стандартам безопасности, аудита и регуляторным требованиям через автоматизацию в пайплайнах.

- **Audit Trail** — журнал всех действий в CI/CD пайплайне для трассируемости. Включает записи о коммитах, изменениях конфигураций, запусках пайплайнов, изменениях секретов и deployment'ах.

- **Pipeline Execution Policy** — политик GitLab для принудительного выполнения задач в пайплайнах. Определяет обязательные этапы, которые должны быть выполнены перед слиянием кода или деплоем.

- **Change Management** — управление изменениями через CI/CD (approval workflows, MR templates). Контролирует процесс внесения изменений с помощью требований одобрения, шаблонов и автоматических проверок.

- **Compliance Pipeline** — пайплайн, созданный из Compliance-проекта для проверки соответствия нормативным требованиям. Запускается автоматически и не может быть пропущен.

- **Protected Environment** — среда (production, staging), доступ к которой ограничен и требует одобрения от определённых пользователей или групп перед деплоем.

## Теоретический блок

### Требования к Compliance в CI/CD

| Стандарт | Основные требования к CI/CD |
|----------|----------------------------|
| **SOC2** | Контроль доступа, аудит действий, change management, разделение обязанностей |
| **ISO27001** | Управление изменениями, непрерывность процессов, документирование |
| **HIPAA** | Защита данных (PHI), шифрование, аудит доступа, регулярные проверки |
| **PCI DSS** | Контроль изменений, тестирование безопасности, мониторинг доступа |

### Pipeline Execution Policies

GitLab поддерживает два типа политик:

1. **Include-Type** — включает дополнительные этапы из внешних проектов в каждый пайплайн. Используется для добавления compliance-проверок.

2. **Merge-Request-Type** — применяется только к merge request'ам. Определяет обязательные задачи для MR перед слиянием.

**Порядок выполнения:**
- Сначала выполняются этапы из проекта пользователя
- Затем — этапы из Compliance Pipeline (из Compliance-проекта)
- Compliance Pipeline не может быть отключён или изменён пользователем

### Merge Request Approval Rules

GitLab позволяет настроить правила одобрения:

- **Approvals required** — минимальное количество необходимых одобрений
- **Code owners** — автоматическое назначение ревьюеров на основе CODEOWNERS
- **Protected branches** — правила для защищённых веток
- **Approval groups** — одобрение от определённых групп пользователей
- **Prevent approval by author** — запрет автору одобрять собственный MR
- **Prevent committers** — запрет коммиттерам одобрять MR

### Audit Events API

GitLab предоставляет API для получения событий аудита:

- События аудита включают: кто, что, когда и где изменил
- Доступны через REST API (`/audit_events`) и GraphQL
- Включают действия с: проектами, пользователями, секретами, deployment'ами, пайплайнами
- Данные хранятся в течение определённого периода и доступны для экспорта

### Tracing от кода до production

GitLab поддерживает полную трассируемость:

- **Commit SHA** — уникальный идентификатор коммита в каждом артефакте
- **Container Registry** — привязка образов к коммитам
- **Package Registry** — версионирование пакетов с привязкой к коммитам
- **Sbom (Software Bill of Materials)** — автоматическое создание в CI/CD
- **DORA metrics** — метрики для отслеживания циклов доставки

## Практический блок

### Настройка Pipeline Execution Policies

```yaml
# Compliance-проект: .gitlab-ci.yml
compliance_pipeline:
  stage: compliance
  script:
    - echo "Проверка compliance требований"
    - ./scripts/security-scan.sh
    - ./scripts/license-check.sh
    - ./scripts/policy-validation.sh
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

**Включение políticas в проекте:**

1. Перейти в **Settings → CI/CD → Pipeline execution policies**
2. Добавить политику, указав Compliance-проект и файл конфигурации
3. Указать тип политики (Include или Merge-Request)

### Merge Request templates для compliance

```
<!-- .gitlab/merge_request_templates/Compliance.md -->

## Описание изменения
<!-- Краткое описание что изменено и зачем -->

## Тип изменения
- [ ] Feature
- [ ] Bugfix
- [ ] Refactoring
- [ ] Configuration change
- [ ] Security patch

## Compliance проверки
- [ ] Добавлены/обновлены тесты
- [ ] Пройдены все automated checks
- [ ] Обновлена документация
- [ ] Проверены лицензии зависимостей
- [ ] Выполнена security scanning

## Одобрения
<!-- Список необходимых одобрений -->
```

### Audit Events через API

```bash
# Получение событий аудита для проекта
curl --header "PRIVATE-TOKEN: <access_token>" \
  "https://gitlab.example.com/api/v4/audit_events"

# Фильтрация по дате
curl --header "PRIVATE-TOKEN: <access_token>" \
  "https://gitlab.example.com/api/v4/audit_events?created_after=2025-01-01T00:00:00Z"

# GraphQL запрос для аудита
query {
  auditEvents(first: 10) {
    nodes {
      id
      createdAt
      author {
        username
      }
      details
      ipAddress
    }
  }
}
```

### Compliance pipelines

```yaml
# Настройка в Group Settings → CI/CD → Compliance pipeline
# Указать Compliance-проект и путь к конфигурации

# Пример Compliance конфигурации
stages:
  - security
  - compliance
  - quality

security_scan:
  stage: security
  image: security-scanner:latest
  script:
    - run-sast-scan
    - run-dependency-scan
    - run-secret-detection
  artifacts:
    reports:
      sast: gl-sast-report.json
      dependency_scanning: gl-dependency-scanning-report.json

compliance_check:
  stage: compliance
  script:
    - validate-licenses
    - check-software-bill
    - verify-access-controls
  needs: [security_scan]

quality_gate:
  stage: quality
  script:
    - check-code-coverage
    - verify-test-results
    - validate-deployment-readiness
  needs: [compliance_check]
```

### Tracing артефактов

```yaml
# В CI/CD конфигурации добавляем информацию о трассировке
build:
  stage: build
  script:
    - echo "Building application..."
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  variables:
    # Привязка к коммиту автоматически
    DOCKER_BUILDKIT: 1

deploy_production:
  stage: deploy
  script:
    - echo "Deploying commit $CI_COMMIT_SHA to production"
    - kubectl set image deployment/app app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  needs: [build]
```

### Protected environments с approval

```yaml
# Настройка в Settings → CI/CD → Protected environments
# Для production environment:

# Требования:
# - Минимум 2 одобрения
# - Только от группы "Release Managers"
# - Deploy access только для main ветки
```

```yaml
# Конфигурация в .gitlab-ci.yml
deploy_staging:
  stage: deploy
  environment:
    name: staging
  script:
    - ./deploy.sh staging
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy_production:
  stage: deploy
  environment:
    name: production
  script:
    - ./deploy.sh production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  # Approval rules настраиваются в UI проекта
  # для protected environments
```

## Дополнительная информация

### Связанные темы

- [Security scanning в GitLab CI](./security_scanning.md)
- [Secret management](./secret_management.md)
- [Deployment strategies](./deployment_strategies.md)
- [Monitoring и observability](./monitoring.md)
- [Incident management](./incident_management.md)
- [Disaster recovery](./disaster_recovery.md)

### Чек-лист compliance

**Процесс:**
- [ ] Настроены Pipeline Execution Policies
- [ ] Используются Merge Request templates
- [ ] Настроены правила одобрения для MR
- [ ] Включены Protected environments
- [ ] Настроен аудит событий
- [ ] Включены security scanning (SAST, DAST, dependency scanning)
- [ ] Настроено secret detection

**Документация:**
- [ ] Описан процесс change management
- [ ] Есть чек-листы для deployment
- [ ] Документированы процедуры incident response
- [ ] Ведётся журнал аудита

**Мониторинг:**
- [ ] Настроены алерты на compliance нарушения
- [ ] Регулярно проверяются результаты сканирования
- [ ] Отслеживаются DORA metrics
- [ ] Периодически проводятся compliance аудиты

**Безопасность:**
- [ ] Секреты хранятся в Variables/Secrets management
- [ ] Включено шифрование артефактов
- [ ] Настроен контрол доступа к средам
- [ ] Регулярно обновляются зависимости
