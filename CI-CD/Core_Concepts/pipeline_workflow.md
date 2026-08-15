# Типичный поток пайплайна

---
**Reliability Score: 10/10** (SSoT + Проверено по стандартам 2026 года)
**Freshness: 2026-08**
---

## Определения

- **Поток пайплайна (Pipeline Workflow)** — последовательность этапов и задач, выполняемых для автоматизированной доставки кода от момента фиксации (commit) до развертывания в продуктивной среде.

- **Quality Gates (Ворота качества)** — автоматизированные проверки на определенных этапах пайплайна (например, порог покрытия тестами, отсутствие критических уязвимостей или превышение бюджета FinOps), непрохождение которых блокирует дальнейшее продвижение изменений.

- **DAG (Directed Acyclic Graph)** — механизм в CI/CD, позволяющий запускать задачи на основе их зависимостей, а не только по завершении целого этапа, что значительно ускоряет выполнение пайплайна.

- **Эфемерные окружения (Ephemeral Environments)** — временные изолированные среды, создаваемые пайплайном «на лету» для тестирования конкретной ветки или Merge Request.

## Основные концепции

### Принципы эффективного пайплайна (2026)

1. **Fail-Fast (Падай быстро)**
   Самые быстрые и критичные проверки (линтеры, Unit-тесты) выполняются первыми.
2. **Параллелизм и DAG**
   Использование графа зависимостей (`needs`) вместо жестких стадий для минимизации времени ожидания.
3. **Иммутабельность и SBOM**
   Артефакт (Docker-образ) собирается один раз с генерацией программного счета материалов (**SBOM**).
4. **OIDC-First (Identity-based Auth)**
   Отказ от статических секретов в пользу временных токенов через OpenID Connect для взаимодействия с облаками (AWS, GCP) и Vault.
5. **Shift-Left Security & FinOps**
   Интеграция сканеров безопасности и оценки стоимости инфраструктурных изменений на самых ранних этапах.

### Каноническая структура (Lifecycle 2026)

Современный пайплайн объединяет разработку, безопасность и управление затратами:

1. **Валидация (Validate/Lint)**
   - Линтинг кода, Docker-файлов и IaC-манифестов.
   - Проверка секретов (**Secret Detection**).
2. **Тестирование (Test)**
   - Unit-тесты и расчет покрытия.
   - Интеграционные тесты с использованием **Testcontainers**.
3. **Сборка и Аттестация (Build & Attest)**
   - Сборка образа, генерация **SBOM** и подпись артефакта (SLSA).
4. **Безопасность (Security Scan)**
   - SCA (анализ зависимостей) и статический анализ безопасности (**SAST**).
   - Проверка уязвимостей в образе по базе CVE.
5. **Финансовый контроль (FinOps Gate)**
   - Оценка стоимости изменений (например, через `infracost`) для Terraform/K8s ресурсов.
6. **Развертывание в Preview (Preview Deploy)**
    - Создание эфемерного окружения для Merge Request.
    - Запуск **DAST** и **E2E** тестов.
7. **Верификация после слияния (Post-merge Verification):**
    - Повторный запуск пайплайна после объединения PR с основной веткой.
    - **Важность:** Гарантирует, что изменения из разных веток (например, Feature A и Feature B), успешно прошедшие CI изолированно, корректно работают вместе после интеграции в `main`.
8. **Продуктивное развертывание (Production Deploy)**
    - Развертывание через GitOps или Blue-Green стратегии.
    - **Агентная верификация (Agentic Verification):** AI-агенты проверяют состояние системы и бизнес-метрики после деплоя для принятия решения о роллбэке.

## Практические сценарии

### Пример комплексного пайплайна (GitLab CI 2026)

```yaml
stages:
  - validate
  - test
  - build
  - security
  - deploy-preview
  - deploy-prod

variables:
  IMAGE_TAG: "${CI_COMMIT_SHORT_SHA}"

# Использование кэша для ускорения зависимостей
default:
  cache:
    key: files-hash
    paths:
      - .npm/
      - vendor/

# 1. Валидация
lint:
  stage: validate
  script:
    - golangci-lint run ./...
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# 2. Тестирование с DAG
unit_tests:
  stage: test
  script:
    - go test -coverprofile=coverage.out ./...
  artifacts:
    reports:
      junit: report.xml

# 3. Сборка с генерацией SBOM
build_and_sbom:
  stage: build
  needs: ["unit_tests"]
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - # Получение временных кредов через OIDC
    - syft . -o cyclonedx-json=sbom.json
    - docker build -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .
  artifacts:
    paths: [sbom.json]

# 4. Безопасность и SCA
security_scan:
  stage: security
  needs: ["build_and_sbom"]
  script:
    - trivy image --exit-code 1 --severity CRITICAL $CI_REGISTRY_IMAGE:$IMAGE_TAG
    - trivy sbom sbom.json

# 5. Эфемерное окружение (только для MR)
review_app:
  stage: deploy-preview
  script:
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./chart
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    on_stop: stop_review
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# 6. Прод (с ручным подтверждением)
deploy_prod:
  stage: deploy-prod
  when: manual
  script:
    - ./deploy.sh production $IMAGE_TAG
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Дополнительная информация

- **Жизненный цикл разработки:** [SDLC — Обзор и фазы](./sdlc_overview.md).
- **Глоссарий терминов:** [Определения Jobs, Stages, Runners](./pipeline_glossary.md).
- **Метрики эффективности:** [Метрики DORA (Lead Time, CFR)](./dora_metrics.md).
- **Безопасность CI/CD:** [DevSecOps: Обзор](../DevSecOps/devsecops_overview.md).
- **Инфраструктурные затраты:** [FinOps в DevOps](../../Concepts/sre_concepts_main.md).
- **Стратегии развертывания:** [Rolling Update, Canary, Blue-Green](./deployment_strategies.md).
- **GitOps подход:** [Пример GitOps-пайплайна](../../GitOps/gitops_pipeline_example.md).
