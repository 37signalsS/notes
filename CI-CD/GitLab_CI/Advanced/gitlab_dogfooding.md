# GitLab Dogfooding

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Dogfooding (Поедание своей же собачьей еды)** — практика использования собственного продукта для разработки и эксплуатации этого продукта. GitLab использует GitLab для разработки GitLab.
* **Upstream-First** — принцип разработки, при котором все изменения сначала вносятся в основную ветку (upstream) и только потом попадают в downstream-инсталляции.
* **Downstream (Даунстрим)** — инсталляция GitLab, используемая внутри компании (self-hosted или SaaS).
* **Upstream (Апстрим)** — основная ветка разработки GitLab (gitlab.com/gitlab-org/gitlab).
* **Staging Instance** — тестовая инсталляция GitLab, используемая для валидации новых версий перед обновлением production.
* **Production Instance** — рабочая инстанция GitLab, используемая командой.
* **Canary Deployment** — постепенный rollout новых версий на подмножестве пользователей.
* **Feature Flags** — механизм включения/выключения функциональности без деплоя.
* **Self-Hosted GitLab** — инстанция GitLab, развёрнутая на собственной инфраструктуре.
* **GitLab.com** — официальная SaaS-версия GitLab, управляемая GitLab Inc.
* **Merge Request (MR) Pipeline** — пайплайн, запускаемый для валидации MR перед слиянием.
* **Pipeline for Merged Results (PMR)** — пайплайн, запускаемый для результата слияния MR с target branch.

## Предварительные требования

### Версии и поддержка

* **GitLab:** 17.x–19.x (Omnibus, Docker, Helm)
* **PostgreSQL:** 17+ (минимально поддерживаемая версия для GitLab 19.0+)
* **Valkey/Redis:** Valkey 7.2+ или Redis 7.2+ (начиная с GitLab 19.0 поддержка Redis 6 удалена)
* **Ruby:** 3.2+ (для сборки и тестирования GitLab)
* **Node.js:** 20+ (для сборки фронтенда)
* **Docker:** 24+ (если используется DinD для сборки образов)

### Инфраструктура

| Компонент | Минимум | Рекомендация Production |
|:---|:---|:---|
| CPU | 4 vCPU | 8+ vCPU |
| RAM | 16 ГБ | 32+ ГБ |
| Диск | 100 ГБ SSD | 500+ ГБ NVMe |
| Сеть | 1 Гбит/с | 10 Гбит/с с низкой задержкой |

### Необходимые знания

- Структура GitLab CI/CD, стадии (stages) и правила запуска (`rules`)
- Основы GitLab CI/CD Variables и Protected/Masked переменные
- Принципы trunk-based development и Merge Request workflow
- Базовое понимание Docker, Kubernetes Namespaces, Services и Ingress (для сценариев с кластером)
- Основы администрирования Linux: systemd, логирование, сетевые порты

### Сетевые требования

- Порты 80/443 (HTTP/HTTPS), 22/2222 (SSH/Git)
- DNS-записи для `gitlab.example.com`, `staging.gitlab.com`
- Доступность upstream `gitlab.com/gitlab-org/gitlab` для mirroring
- Firewall-правила, ограничивающие доступ к dogfooding окружению

## Основные концепции

### Архитектура dogfooding в GitLab

GitLab использует собственную платформу для разработки, тестирования и эксплуатации:

```
┌─────────────────────────────────────────────────────────────┐
│                    GitLab.com (SaaS)                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ gitlab.com/gitlab-org/gitlab (Upstream)                 │ │
│  │ - Разработка GitLab                                      │ │
│  │ - Merge Request Pipelines                                │ │
│  │ - E2E Tests                                              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                        ▲                                     │
│                        │ Dogfooding                          │
│                        ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ staging.gitlab.com                                       │ │
│  │ - Валидация новых версий                                 │ │
│  │ - Canary deployments                                     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                        ▲                                     │
│                        │ Production mirror                   │
│                        ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ production.gitlab.com                                    │ │
│  │ - Рабочая инстанция для GitLab Inc.                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Уровни dogfooding

| Уровень | Описание | Применение |
|:---|:---|:---|
| **L0: Local development** | Использование GitLab локально для разработки | Разработчики |
| **L1: CI/CD** | Использование GitLab CI/CD для сборки и тестирования GitLab | Инженеры |
| **L2: Staging** | Тестирование новых версий на staging-инстансе | QA team |
| **L3: Production** | Использование GitLab для работы с GitLab | Вся компания |
| **L4: External** | Предоставление GitLab.com как продукта клиентам | GitLab Inc. |

### Принципы upstream-first

1. **Все изменения в upstream:** все патчи, фиксы, фичи сначала попадают в gitlab-org/gitlab.
2. **CI/CD для CI/CD:** GitLab CI используется для сборки и тестирования самого GitLab.
3. **E2E на production-like:** end-to-end тесты запускаются на окружении, максимально приближённом к production.
4. **Canary releases:** новые версии сначала развёртываются на canary-инстансе.
5. **Rollback plan:** каждый релиз имеет готовый план отката.

## Практические сценарии

### Сценарий 1: Настройка dogfooding окружения

```bash
# 1. Создание группировки для dogfooding
# В GitLab UI: Create a group → "dogfooding"

# 2. Настройка проекта для разработки GitLab
# Импорт репозитория GitLab в собственный GitLab
# git clone https://gitlab.com/gitlab-org/gitlab.git
# cd gitlab
# git remote add self-hosted https://gitlab.example.com/group/gitlab.git
# git push self-hosted main

# 3. Настройка CI/CD переменных
# В Settings → CI/CD → Variables:
# - GITLAB_TOKEN (для доступа к API)
# - DATABASE_URL (подключение к БД)
# - REDIS_URL (подключение к Redis)
# - OBJECT_STORE_ENABLED (S3 для артефактов)

# 4. Настройка runners
# Использование того же runner'а, что и для production workloads
# Или отдельный runner для dogfooding workloads
```

### Сценарий 2: CI/CD для сборки GitLab

```yaml
# .gitlab-ci.yml (в репозитории gitlab-org/gitlab)

stages:
  - setup
  - validate
  - build
  - test
  - e2e
  - deploy

# Валидация миграций БД
validate_migrations:
  stage: validate
  image: ruby:3.2
  script:
    - bundle install
    - bundle exec rake db:migrate:status
  rules:
    - changes:
        - db/migrate/**/*
      if: $CI_COMMIT_BRANCH == "main" || $CI_PIPELINE_SOURCE == "merge_request_event"

# Сборка Docker образа
build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Unit tests
unit_tests:
  stage: test
  image: ruby:3.2
  script:
    - bundle install
    - bundle exec rake test:units
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  cache:
    key: "${CI_COMMIT_REF_SLUG}-vendor"
    paths:
      - vendor/

# Integration tests
integration_tests:
  stage: test
  image: ruby:3.2
  services:
    - postgres:17
    - redis:7.2
  variables:
    POSTGRES_DB: gitlab_test
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
    REDIS_URL: redis://redis:6379
  script:
    - bundle install
    - bundle exec rake test:integration
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# E2E tests
e2e_tests:
  stage: e2e
  image: ruby:3.2
  script:
    - bundle install
    - bundle exec rake test:e2e
  environment:
    name: e2e
    url: https://staging.gitlab.com
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

# Deploy to staging
deploy_staging:
  stage: deploy
  image: ruby:3.2
  script:
    - ./scripts/deploy staging
  environment:
    name: staging
    url: https://staging.gitlab.com
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  when: manual
```

### Сценарий 3: E2E тестирование на production-like окружении

```yaml
# .gitlab-ci.yml

stages:
  - e2e

# E2E тесты на staging
e2e_staging:
  stage: e2e
  image: registry.gitlab.com/gitlab-org/gitlab:e2e
  services:
    - selenium/standalone-chrome:latest
  variables:
    SELENIUM_HOST: selenium
    GITLAB_URL: https://staging.gitlab.com
    SIGN_IN_DISABLED: "true"
  script:
    - bundle exec rake qa:test:staging
  environment:
    name: staging
    url: https://staging.gitlab.com
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

# E2E тесты на production mirror
e2e_production_mirror:
  stage: e2e
  image: registry.gitlab.com/gitlab-org/gitlab:e2e
  services:
    - selenium/standalone-chrome:latest
  variables:
    SELENIUM_HOST: selenium
    GITLAB_URL: https://gitlab.com
    SIGN_IN_DISABLED: "true"
  script:
    - bundle exec rake qa:test:production
  environment:
    name: production-mirror
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  when: manual
```

### Сценарий 4: Canary deployment нового функционала

```yaml
# .gitlab-ci.yml

stages:
  - deploy-canary
  - monitor
  - deploy-production

# Deploy canary (5% пользователей)
deploy_canary:
  stage: deploy-canary
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f k8s/canary.yaml
    - kubectl set image deployment/gitlab-workhorse \
        gitlab-workhorse=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA \
        -n gitlab
  environment:
    name: production-canary
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  when: manual

# Мониторинг canary (error rate, latency)
monitor_canary:
  stage: monitor
  image: curlimages/curl:latest
  script:
    - |
      # Проверка error rate
      ERROR_RATE=$(curl -s "http://prometheus.gitlab.svc:9090/api/v1/query?query=rate(gitlab_http_request_total{status=~\"5..\"}[5m])" | jq '.data.result[0].value[1]')
      if (( $(echo "$ERROR_RATE > 0.01" | bc -l) )); then
        echo "Error rate too high: $ERROR_RATE"
        exit 1
      fi

      # Проверка latency p95
      LATENCY_P95=$(curl -s "http://prometheus.gitlab.svc:9090/api/v1/query?query=histogram_quantile(0.95, rate(gitlab_http_request_duration_seconds_bucket[5m]))" | jq '.data.result[0].value[1]')
      if (( $(echo "$LATENCY_P95 > 1" | bc -l) )); then
        echo "Latency too high: $LATENCY_P95"
        exit 1
      fi
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  when: manual

# Full rollout
deploy_production:
  stage: deploy-production
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f k8s/production.yaml
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  when: manual
```

### Сценарий 5: Использование GitLab для разработки GitLab

```yaml
# .gitlab-ci.yml

stages:
  - lint
  - test
  - build
  - package

# RuboCop lint
rubocop:
  stage: lint
  image: ruby:3.2
  script:
    - bundle install
    - bundle exec rubocop
  cache:
    key: "${CI_COMMIT_REF_SLUG}-rubocop"
    paths:
      - vendor/bundle

# ESLint для фронтенда
eslint:
  stage: lint
  image: node:20
  script:
    - cd app/assets/javascripts
    - npm ci
    - npm run lint
  rules:
    - changes:
        - app/assets/javascripts/**/*

# RSpec tests
rspec:
  stage: test
  image: ruby:3.2
  services:
    - postgres:17
    - redis:7.2
  script:
    - bundle install
    - bundle exec rake db:create db:schema:load
    - bundle exec rspec
  cache:
    key: "${CI_COMMIT_REF_SLUG}-vendor"
    paths:
      - vendor/

# Build package
build_package:
  stage: build
  image: ruby:3.2
  script:
    - bundle exec rake pkg:build
  artifacts:
    paths:
      - gitlab-*.tar.gz
  rules:
    - if: $CI_COMMIT_TAG
```

### Сценарий 6: Feature Flags для dogfooding

```yaml
# .gitlab-ci.yml

stages:
  - deploy
  - feature_flag

# Deploy with feature flag off
deploy:
  stage: deploy
  script:
    - ./deploy.sh
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

# Enable feature flag for internal users
enable_feature_flag:
  stage: feature_flag
  script:
    - |
      curl --request PUT \
        --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{"enabled": true, "strategy": "user_percentage", "percentage": 10}' \
        "https://gitlab.example.com/api/v4/feature_flags/my_feature"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  when: manual
```

## Валидация dogfooding окружения

### Проверка после обновления staging

```bash
# 1. Health check
curl -s https://staging.gitlab.com/-/ready
curl -s https://staging.gitlab.com/-/health

# 2. Проверка версии
curl -s https://staging.gitlab.com/-/version

# 3. Smoke-тест: создать MR, запустить пайплайн
# В GitLab UI: Create a test MR → verify pipeline passes

# 4. E2E-проверка (если настроено)
curl -s "https://staging.gitlab.com/api/v4/application/statistics"
```

### Критерии готовности к production deploy

* Все E2E-тесты прошли успешно на staging.
* Нет критичных алертов в мониторинге (Prometheus/Grafana).
* Error rate < 0.1% в течение 30 минут после canary deploy.
* Latency p95 < 1s для критичных endpoints.
* Sidekiq queue size < 1000.
* Gitaly latency < 1s.

## Операции и команды

### Проверка dogfooding окружения

```bash
# Проверка версии GitLab
curl -s https://gitlab.example.com/-/version

# Проверка здоровья
curl -s https://gitlab.example.com/-/ready
curl -s https://gitlab.example.com/-/health

# Проверка компонентов
sudo gitlab-ctl status
```

### Управление пайплайнами

```bash
# Просмотр пайплайнов
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/pipelines"

# Запуск пайплайна
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/pipeline"

# Отмена пайплайна
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/pipelines/:pipeline_id/cancel"
```

### Feature Flags

```bash
# Список feature flags
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/feature_flags"

# Включение feature flag
curl --request PUT \
  --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{"enabled": true}' \
  "https://gitlab.example.com/api/v4/feature_flags/my_feature"

# Выключение feature flag
curl --request PUT \
  --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{"enabled": false}' \
  "https://gitlab.example.com/api/v4/feature_flags/my_feature"
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| CI/CD для GitLab падает | Недостаточно ресурсов на runner'ах | Масштабируйте runner'ы, оптимизируйте jobs |
| Staging не репрезентативен | Различия в конфигурации | Используйте Infrastructure as Code для обеих сред |
| Canary deployment сбоит | Недостаточный мониторинг | Улучшите алерты, добавьте кастомные метрики |
| Feature flag не работает | Неправильная стратегия | Проверьте стратегию rollout, убедитесь в корректности UI |
| Downstream не синхронизируется | Пропущены upstream-изменения | Настройте автоматический mirroring |
| MR pipeline падает на валидации миграций | Несовместимость миграций с новой версией БД | Запустите `bundle exec rake db:migrate:status` локально. Убедитесь, что миграции идемпотентны. |
| Staging не репрезентативен | Расхождение конфигурации или данных с production | Используйте Infrastructure as Code. Синхронизируйте `gitlab.rb` и переменные окружения. |
| Canary deployment не раскрывается | Не настроены rollout conditions или нет метрик | Проверьте `environment/action` правила. Настройте Prometheus alerts. |
| Утечка данных production в dogfooding | Отсутствует анонимизация при синхронизации | Используйте synthetic data. Настройте маскирование PII в репозиториях и артефактах. |
| Runner'ы перегружены при сборке GitLab | Сборка GitLab ресурсоёмкая | Выделите dedicated powerful runners. Используйте `resource_group` для исключения параллельных сборок. |
| Feature flag срабатывает для всех пользователей | Неправильная `strategy` или `percentage` | Проверьте стратегию rollout. Для dogfooding используйте `user_ids` или `group` с внутренними пользователями. |
| GitLab.com rate limit при использовании API | Превышен лимит запросов | Используйте `CI_JOB_TOKEN` вместо PAT. Настройте exponential backoff. |

## Граничные случаи

### Расхождения upstream и downstream

При использовании патчей или кастомных изменений в downstream возникает риск расхождения с upstream. Рекомендации:

* Все изменения вносите в upstream (`gitlab-org/gitlab`), а не в downstream.
* Если патч критичен и не может ждать релиза — используйте `git cherry-pick` с последующим revert после вливания upstream.
* Настройте автоматический mirroring с upstream для своевременного получения изменений.

### Нестабильность staging при быстрых изменениях

Staging может стать нестабильным при частых обновлениях upstream. Рекомендации:

* Используйте отдельный staging для каждой ветки upstream (например, `staging-ee`, `staging-ce`).
* Ограничьте auto-deploy в staging только успешными пайплайнами с PMR.
* Настройте автоматический откат staging при критических алертах.

### Переполнение ресурсов runner'ов

Сборка GitLab — одна из самых ресурсоёмких задач. Рекомендации:

* Используйте dedicated runners с ≥ 16 vCPU и 32 ГБ RAM для сборки GitLab.
* Настройте `resource_group` для исключения параллельных сборок.
* Используйте S3/MinIO для кэширования зависимостей (Bundler, npm).
* Ограничьте количество параллельных джоб на runner'е.

### SSL/TLS для внутренних сервисов

Dogfooding окружение часто использует самоподписанные сертификаты или внутренний CA. Рекомендации:

* Настройте доверенный внутренний CA и разверните корневой сертификат на всех runner'ах.
* Используйте `SSL_CERT_FILE` переменную окружения для указания CA bundle.
* Проверяйте срок действия сертификатов автоматически (например, через `certbot renew` + monitoring).

### Ограничения GitLab API

GitLab.com и self-hosted инстансы имеют rate limits. Рекомендации:

* Для автоматизации используйте `CI_JOB_TOKEN` вместо PAT — он имеет более высокие лимиты и автоматически истекает.
* Реализуйте exponential backoff при 429 ответах.
* Кешируйте ответы API там, где это возможно.

## Лучшие практики

### Организация

* **Dedicated group:** создайте отдельную группировку для dogfooding проектов.
* **Separate runners:** используйте отдельные runner'ы для dogfooding workloads.
* **Mirroring:** настройте автоматическое mirroring из upstream.
* **Documentation:** документируйте процессы dogfooding.

### CI/CD

* **Upstream-first:** все изменения сначала в upstream.
* **Trunk-based development:** используйте короткоживущие feature branches и PMR (Pipeline for Merged Results) для валидации интеграции.
* **E2E coverage:** поддерживайте высокий процент E2E тестов, включая QA-сценарии GitLab Inc.
* **Resource isolation:** dogfooding runner'ы должны быть отделены от production runner'ов для предотвращения contention.
* **Smoke tests:** автоматизируйте smoke-проверку после каждого deploy в staging (health, readiness, MR pipeline).
* **Canary releases:** используйте canary deployment для новых версий с error budget.
* **Rollback plan:** имейте готовый план отката для каждого релиза. Автоматизируйте откат при превышении error budget.
* **Monitoring:** мониторьте все уровни dogfooding окружения (GitLab, runners, БД, кэш).

### Безопасность

* **Isolation:** dogfooding окружение должно быть изолировано от production (отдельный VLAN, firewall rules).
* **Access control:** ограничьте доступ к dogfooding окружению. Используйте LDAP/SAML для аутентификации.
* **Data anonymization:** не используйте production-данные в dogfooding. Используйте synthetic data или маскирование PII.
* **Audit logging:** включите audit log для всех изменений в dogfooding окружении. Архивируйте логи в отдельное хранилище.
* **Secret management:** используйте GitLab CI/CD Protected/Masked variables или HashiCorp Vault. Не хардкодьте секреты в `.gitlab-ci.yml`.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[CI/CD Cost Optimization](../Advanced/cicd_cost_optimization.md)** — оптимизация затрат CI/CD
* **[Мониторинг и метрики GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг

### Внешние ресурсы

* [GitLab Handbook: Dogfooding](https://about.gitlab.com/handbook/engineering/development/enablement/dogfooding/)
* [GitLab Direction](https://about.gitlab.com/direction/)
* [GitLab Self-Managed Instance](https://gitlab.com/gitlab-org/gitlab)
