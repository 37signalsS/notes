# GitLab Flow: стратегии ветвления и рабочие процессы

**Актуально для:** GitLab 17.x–19.x

## Определения

**GitLab Flow** — это прагматичная стратегия ветвления Git, сочетающая разработку через функциональные ветки (feature branches) с системой отслеживания задач и явным моделированием инфраструктурных окружений. Она является гибким гибридом между GitHub Flow (простота) и Git Flow (структурированность), максимально адаптированным под современные CI/CD процессы GitLab.

**Upstream First (Приоритет основной ветки)** — фундаментальный принцип GitLab Flow. Любое изменение (фича, багфикс) должно сначала попасть в «верхний поток» (ветку `main`), пройти там тестирование, и только после этого оно может быть перенесено (продвинуто) в ветки окружений (`production`) или релизов. Это исключает ситуацию, когда баг исправлен на проде, но забыт в коде следующей версии.

**Environment Promotion (Продвижение по окружениям)** — процесс последовательного слияния изменений из одной долгоживущей ветки окружения в другую (например, `main` → `pre-prod` → `production`). Это обеспечивает контролируемую доставку артефактов.

## Предварительные требования

Перед внедрением GitLab Flow убедитесь, что выполнены минимальные условия:

- **Git** версии не ниже **2.23** — для команды `git switch` (в старых версиях используйте `git checkout -b`). Актуальные версии рекомендуются, так как улучшают работу с `worktree`, partial clone и защитой веток.
- **GitLab** версии **17.x или новее** — для поддержки Pipeline Inputs, Merge Trains и современных `rules`. GitLab Flow требует настройки на уровне группы или проекта.
- **GitLab Runner** — установлен и зарегистрирован с executor, подходящим для вашей инфраструктуры (Docker, Shell, Kubernetes). Для production-деплоев рекомендуется использовать защищённые Runner'ы.
- **Права доступа:** хотя бы один Maintainer для настройки Protected Branches, Protected Environments и Approval Rules.
- **CI/CD пайплайн** — базовый `.gitlab-ci.yml` с стадиями `test` и `build`, проходящий для ветки `main`.
- **Хранилище артефактов** (Registry или внешний) — для продвижения одних и тех же артефактов между окружениями без пересборки.

## Основные концепции

### Архитектура GitLab Flow

GitLab Flow строится вокруг трёх столпов: трассируемость, защищённые окружения и продвижение артефактов.

```
[Issue] → [Feature Branch] → [MR] → [CI Pipeline] → [main]
                                                      │
                                    ┌─────────────────┼─────────────────┐
                                    ▼                 ▼                 ▼
                              [Staging]        [Pre-prod]        [Production]
                              (автодеплой)    (ручной аппрув)   (ручной аппрув)
```

1. **Ветка окружения = состояние окружения.** Каждая долгоживущая ветка (`main`, `staging`, `pre-prod`, `production`) отражает точное состояние соответствующего стенда. Это исключает « drift » между кодом и инфраструктурой.
2. **Продвижение через Merge Request.** Код никогда не правится напрямую в ветках окружений. Любое изменение продвигается через MR с обязательным код-ревью и CI-проверками.
3. **Один артефакт — все окружения.** Артефакт (Docker-образ, пакет), собранный при слиянии в `main`, проходит через все окружения без пересборки. Это гарантирует идентичность кода на всех этапах.
4. **Upstream First.** Багфикс всегда вносится в `main`, а затем переносится в релизные или окруженческие ветки через `git cherry-pick` или MR. Это предотвращает регрессию в следующих версиях.

### 1. Интеграция с задачами (Issues)
Любое изменение начинается с создания Issue. Это обеспечивает полную трассируемость (Traceability): каждый коммит и Merge Request (MR) связан с конкретной бизнес-задачей или техническим багом. Рекомендуется использовать автоматическое закрытие задач через ключевые слова в описании MR (например, `Closes #123`).

### 2. Feature-ветки для всех изменений
Прямые коммиты в `main` запрещены. Вся работа ведется в кратковременных ветках.
* **Именование:** `feature/ID-description` или `bugfix/ID-description` (где ID — номер задачи).
* **Жизненный цикл:** Создание от `main` → Разработка → MR → Тестирование → Слияние в `main` → Удаление ветки.

### 3. Merge Request (MR) как центр качества
MR в GitLab Flow — это не просто запрос на слияние, а полноценный инструмент контроля:
* **CI/CD Gates:** Пайплайны должны быть «зелеными» перед слиянием. Сюда входят тесты, линтеры и проверки безопасности.
* **Merge Trains:** Механизм, который выстраивает MR в очередь и проверяет их совместимость друг с другом перед фактическим вливанием в `main`. Это гарантирует стабильность основной ветки при высокой интенсивности разработки. Доступно в GitLab Premium и Ultimate.
* **Code Review:** Обязательная проверка кода коллегами.
* **Review Apps:** Динамические окружения, позволяющие увидеть результат работы (например, UI) до слияния в `main`. Требуют настроенного Kubernetes-интегратора или аналогичной инфраструктуры.

#### Merge Trains: детальное описание

Merge Trains — это механизм последовательной интеграции MR, который предотвращает конфликты и обеспечивает стабильность `main`.

**Как работает Merge Train:**
1. Когда первый MR проходит все проверки, он добавляется в очередь
2. Перед слиянием создается временная версия `main` с учетом изменений MR
3. Для этой временной версии запускается отдельный пайплайн проверки
4. Если пайплайн успешен — MR сливается с `main`
5. Если пайплайн завершился неудачно — MR отклоняется и удаляется из очереди
6. Следующий MR в очереди проверяется уже с обновленным `main`

**Конфигурация Merge Trains:**

```yaml
# Включение Merge Trains в настройках проекта:
# Settings > General > Merge requests > Merge method = Merge commit
# Settings > General > Merge requests > Enable merge trains

# Пример .gitlab-ci.yml с поддержкой Merge Trains:
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stages:
  - test
  - build
  - deploy

unit_tests:
  stage: test
  script:
    - make test
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

build:
  stage: build
  script:
    - make build
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Преимущества Merge Trains:**
- Предотвращает «broken main» — каждый MR проверяется в контексте будущего состояния main
- Ускоряет интеграцию — MR проверяются параллельно в очереди
- Экономит ресурсы — отменяет проверку MR, если предыдущий MR провалился

#### Review Apps: детальное описание

Подробное описание архитектуры, конфигурации и сценариев настройки Review Apps в Kubernetes см. в **[Review Apps и динамические окружения](./kubernetes_review_apps.md)**.

### 4. Защита ресурсов (Protected Branches & Environments)
* **Protected Branches:** Основные ветки (`main`, `production`, `stable-*`) защищены от прямого пуша и удаления. Слияние возможно только через MR и при прохождении всех проверок.
* **Protected Environments:** Ограничение прав на деплой в критические окружения (Staging, Production). Даже если код влит в ветку, деплой может требовать ручного подтверждения (Approval Rules) от ответственных лиц. Доступно в GitLab Premium и Ultimate.

### 5. Гигиена истории
* **Squash and Merge:** Рекомендуется объединять множество мелких коммитов ветки в один при слиянии в `main`, чтобы сохранить историю чистой и линейной.
* **Conventional Commits:** Использование стандартизированных сообщений коммитов (`feat:`, `fix:`, `chore:`) для автоматизации генерации Changelog и управления версиями.

---

## Сравнение GitLab Flow с другими стратегиями ветвления

### Краткая сравнительная таблица

| Критерий | GitLab Flow | GitHub Flow | Git Flow | Trunk-Based |
| :--- | :--- | :--- | :--- | :--- |
| **Сложность** | Средняя | Низкая | Высокая | Средняя |
| **Частота релизов** | Средняя/CD | Постоянная (CD) | Редкая (релизы) | Очень высокая |
| **Требования к CI/CD** | Средние (Multi-stage) | Высокие (проверка PR) | Низкие (ручная работа) | Максимальные |
| **Ветки окружений** | Да (main, staging, prod) | Нет | Да (develop, release) | Нет |
| **Protected Environments** | Да (встроено) | Через Actions | Ручная настройка | Через Feature Flags |
| **Merge Trains** | Да (встроено) | Нет | Нет | Нет |
| **Review Apps** | Да (встроено) | Через Actions | Нет | Нет |
| **Основная ниша** | Банки, MedTech, Комплаенс | SaaS, Web, Open Source | Desktop, Mobile, Enterprise | Высокотехнологичные стартапы |
| **Рекомендуемое слияние** | Merge между env | Squash | Merge `--no-ff` | Rebase / FF |
| **Доля рынка** | 10-15% | 40-50% | ~20% | 20-30% |

### Когда выбирать GitLab Flow

**GitLab Flow идеально подходит когда:**
- Требуется жесткий контроль продвижения по окружениям (staging → pre-prod → production)
- Есть регуляторные требования (банки, MedTech, GovTech)
- Нужна полная трассируемость от Issue до деплоя
- Команда работает с защищенными окружениями (Protected Environments)
- Требуется аудит всех изменений и одобрений

**GitHub Flow лучше подходит когда:**
- Нужна максимальная скорость доставки (SaaS, Web)
- Команда зрелая и доверяет автоматическим проверкам
- Нет жестких регуляторных требований
- Достаточно одного окружения (production)

**Git Flow лучше подходит когда:**
- Есть четкий цикл релизов (версии 1.0, 2.0, 3.0)
- Требуется поддержка множества версий продукта
- Релизы происходят редко (раз в месяц/квартал)
- Нужны Release Candidate ветки для стабилизации

**Trunk-Based Development лучше подходит когда:**
- Команда обладает высокой зрелостью
- Есть мощный CI/CD с качественными Quality Gates
- Используются Feature Flags для управления функционалом
- Приоритет — максимальная скорость интеграции

### Влияние на CI/CD пайплайны

GitLab Flow диктует особые требования к структуре пайплайнов:

1. **Multi-stage пайплайны:** Каждая ветка окружения должна иметь свой набор задач (jobs) для тестирования и деплоя
2. **Manual Approval Gates:** Возможность добавления ручных проверок перед деплом в критические окружения
3. **Environment-specific переменные:** Разные значения переменных для каждого окружения (staging vs production)
4. **Conditional jobs:** Запуск задач в зависимости от ветки или окружения
5. **Promotion логика:** Автоматическое продвижение артефактов между ветками окружений

---

## Практические сценарии

### Сценарий 1: Базовый GitLab Flow (Continuous Deployment)
Идеально подходит для SaaS-решений, где `main` всегда готова к деплою в Production.

#### 1. Создание ветки и работа
```bash
# Обновление локального main
git checkout main
git pull origin main

# Создание ветки под задачу #123
git checkout -b feature/123-user-auth
# → Switched to a new branch 'feature/123-user-auth'

# Работа с кодом и фиксация (Conventional Commits)
git add .
git commit -m "feat(auth): add google oauth2 provider"
# → [feature/123-user-auth abc1234] feat(auth): add google oauth2 provider
```

#### 2. Отправка и создание MR
```bash
git push -u origin feature/123-user-auth
# → Branch 'feature/123-user-auth' set up to track remote branch from 'origin'.
```
*В UI GitLab создается MR. После прохождения тестов и ревью нажимается **Squash and Merge**. GitLab CI автоматически развертывает изменения на Production.*

#### Валидация
```bash
# Проверка, что ветка удалена после слияния
git branch -r | grep feature/123-user-auth
# → (пустой вывод — ветка удалена)

# Проверка статуса пайплайна
glab ci status
# → pipeline #456 passed for abc1234

# Проверка, что деплой прошёл
glab env list
# → production: deployed abc1234
```

---

### Сценарий 2: GitLab Flow с ветками окружений (Continuous Delivery)
Используется, когда деплой в Production требует ручного подтверждения или проходит через цепочку тестовых стендов.

1.  **Ветка `main`**: Соответствует окружению **Staging**. Все фичи вливаются сюда первыми.
2.  **Ветка `pre-prod`** (опционально): Для приемочного тестирования (UAT).
3.  **Ветка `production`**: Соответствует боевому окружению (**Production**).

#### Алгоритм продвижения (Promotion):
Код никогда не правится напрямую в ветках окружений.
1. Фича вливается в `main`.
2. После стабилизации на Staging создается MR из `main` в `pre-prod`.
3. После успешного UAT создается MR из `pre-prod` в `production`.
4. Слияние в `production` является триггером для деплоя на прод.

#### Валидация
```bash
# Проверка, что ветки окружений защищены
git branch -r | grep -E 'main|staging|pre-prod|production'
# → origin/main
# → origin/staging
# → origin/pre-prod
# → origin/production

# Проверка, что MR из main → staging создан и пайплайн зелёный
glab mr list --source-branch main --target-branch staging
# → !12  Deploy to staging  [main → staging]  pipeline:passed

# Проверка статусов окружений
glab env list
# → staging: deployed abc1234
# → pre-production: deployed abc1234
# → production: deployed abc1234
```

---

### Сценарий 3: GitLab Flow с ветками релизов (Versioned Software)
Для мобильных приложений, библиотек или коробочного ПО, требующего поддержки нескольких версий одновременно.

1.  Все изменения вливаются в `main`.
2.  Для выпуска версии `2.3` создается ветка `2-3-stable` от `main`.
3.  **Багфикс в релизе (Upstream First):**
    *   Ошибка исправляется в `main`.
    *   Исправление переносится в `2-3-stable` через `git cherry-pick`.
    *   Это гарантирует, что исправление не будет забыто в следующей версии (в `main`).

#### Валидация
```bash
# Проверка, что стабильная ветка создана от текущего main
git log --oneline --graph --all | grep 2-3-stable
# → * a1b2c3d (HEAD -> 2-3-stable) Release 2.3.0

# Проверка cherry-pick: коммит присутствует и в main, и в stable
git log --oneline main | grep <commit_hash>
git log --oneline 2-3-stable | grep <commit_hash>
# → (хэш найден в обеих ветках)

# Создание тега релиза
git checkout 2-3-stable
git tag -a v2.3.1 -m "Hotfix 2.3.1"
git push origin v2.3.1
# → * [new tag]         v2.3.1 -> v2.3.1
```

---

## Practical YAML-примеры для GitLab CI

### Пример 1: Базовый .gitlab-ci.yml для GitLab Flow (CD)

```yaml
# .gitlab-ci.yml для GitLab Flow с непрерывной доставкой

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_TAG

stages:
  - test
  - build
  - security
  - deploy

variables:
  DOCKER_REGISTRY: registry.example.com
  IMAGE_NAME: myapp

# Тесты для MR и main
unit_tests:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pytest tests/unit/ --cov=src --cov-report=xml
    - coverage report --fail-under=80
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

integration_tests:
  stage: test
  image: python:3.12
  services:
    - postgres:15
    - redis:7
  variables:
    POSTGRES_DB: test_db
    POSTGRES_USER: test_user
    POSTGRES_PASSWORD: test_password
    DATABASE_URL: postgresql://test_user:test_password@postgres/test_db
    REDIS_URL: redis://redis:6379
  script:
    - pip install -r requirements.txt
    - pytest tests/integration/ -v
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Сборка Docker образа
build:
  stage: build
  image: docker:24-dind
  services:
    - docker:24-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build -t $CI_REGISTRY_IMAGE/$CI_COMMIT_REF_SLUG:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE/$CI_COMMIT_REF_SLUG:$CI_COMMIT_SHA
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Безопасность
sast:
  stage: security
  include:
    - template: Security/SAST.gitlab-ci.yml

dependency_scanning:
  stage: security
  include:
    - template: Security/Dependency-Scanning.gitlab-ci.yml

secret_detection:
  stage: security
  include:
    - template: Security/Secret-Detection.gitlab-ci.yml

# Деплой в Staging (main ветка)
deploy_staging:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context staging
    - helm upgrade --install myapp ./chart
      --namespace staging
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
      --set ingress.host=staging.myapp.com
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Деплой в Production (только с main через MR)
deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context production
    - helm upgrade --install myapp ./chart
      --namespace production
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
      --set ingress.host=myapp.com
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  needs:
    - deploy_staging
```

### Пример 2: GitLab Flow с ветками окружений (Continuous Delivery)

```yaml
# .gitlab-ci.yml для GitLab Flow с ветками окружений
# main → staging → pre-prod → production

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_BRANCH == "staging"
    - if: $CI_COMMIT_BRANCH == "pre-prod"
    - if: $CI_COMMIT_BRANCH == "production"

stages:
  - test
  - build
  - deploy_staging
  - test_staging
  - deploy_pre_prod
  - test_pre_prod
  - deploy_production

variables:
  DOCKER_REGISTRY: registry.example.com

# Тесты для всех MR
unit_tests:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pytest tests/unit/ --cov=src
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Сборка Docker образа
build:
  stage: build
  image: docker:24-dind
  services:
    - docker:24-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Деплой в Staging (автоматически при слиянии в main)
deploy_staging:
  stage: deploy_staging
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context staging
    - helm upgrade --install myapp ./chart
      --namespace staging
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Тесты на Staging
smoke_tests_staging:
  stage: test_staging
  image: python:3.12
  script:
    - pip install requests pytest
    - pytest tests/smoke/ --base-url=https://staging.myapp.com
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == "staging"

# Деплой в Pre-prod (только с staging через MR)
deploy_pre_prod:
  stage: deploy_pre_prod
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context pre-prod
    - helm upgrade --install myapp ./chart
      --namespace pre-prod
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
  environment:
    name: pre-production
    url: https://pre-prod.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == "staging"
      when: manual
  needs:
    - smoke_tests_staging

# Тесты на Pre-prod
smoke_tests_pre_prod:
  stage: test_pre_prod
  image: python:3.12
  script:
    - pip install requests pytest
    - pytest tests/smoke/ --base-url=https://pre-prod.myapp.com
  environment:
    name: pre-production
    url: https://pre-prod.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == "pre-prod"

# Деплой в Production (только с pre-prod через MR)
deploy_production:
  stage: deploy_production
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context production
    - helm upgrade --install myapp ./chart
      --namespace production
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == "pre-prod"
      when: manual
  needs:
    - smoke_tests_pre_prod
```

### Пример 3: GitLab Flow с ветками релизов (Versioned Software)

```yaml
# .gitlab-ci.yml для GitLab Flow с ветками релизов
# main → 2-3-stable → релиз

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_BRANCH =~ /^.*-stable$/
    - if: $CI_COMMIT_TAG

stages:
  - test
  - build
  - deploy
  - release

variables:
  DOCKER_REGISTRY: registry.example.com

# Тесты для всех MR
unit_tests:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pytest tests/unit/ --cov=src
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Сборка Docker образа
build:
  stage: build
  image: docker:27-dind
  services:
    - docker:27-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Деплой в Development (main ветка)
deploy_development:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context development
    - helm upgrade --install myapp ./chart
      --namespace development
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
  environment:
    name: development
    url: https://dev.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Деплой в Staging (стабильные ветки)
deploy_staging:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context staging
    - helm upgrade --install myapp ./chart
      --namespace staging
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_SHA
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH =~ /^.*-stable$/

# Деплой в Production (теги релизов)
deploy_production:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context production
    - helm upgrade --install myapp ./chart
      --namespace production
      --set image.repository=$CI_REGISTRY_IMAGE
      --set image.tag=$CI_COMMIT_TAG
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/

# Создание релиза в GitLab
create_release:
  stage: release
  image: registry.gitlab.com/gitlab-org/release-cli:v1.16.2
  script:
    - echo "Creating release for $CI_COMMIT_TAG"
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "Release $CI_COMMIT_TAG deployed to production"
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
```

---

## Команды и операции

### GitLab CLI (`glab`)

```bash
# Создать Merge Request
glab mr create -f -w
# → https://gitlab.com/user/repo/-/merge_requests/45

# Список MR
glab mr list
# → !45  Add logging  (feature/logs)

# Одобрение MR
glab mr approve 45
# → Approved Merge Request !45

# Слияние MR
glab mr merge 45 --squash --yes
# → Merged Merge Request !45

# Просмотр пайплайна
glab ci status
# → pipeline #456 passed for abc1234

# Список окружений
glab env list
# → staging: deployed abc1234
# → production: deployed abc1234

# Откат окружения
glab env rollback production
# → Rolled back production to previous deployment
```

### Git Flow-специфичные Git-команды

```bash
# Продвижение кода через MR из main → pre-prod → production
git checkout main
git pull origin main
git checkout -b promote/v2.3.1

# После деплоя на pre-prod и aproval:
git checkout production
git merge --no-ff promote/v2.3.1
git push origin production

# Cherry-pick багфикса в стабильную ветку
git checkout 2-3-stable
git cherry-pick <commit_hash>
git push origin 2-3-stable

# Проверка, что коммит присутствует в обеих ветках
git branch --contains <commit_hash>
# → main
# → 2-3-stable
```

### Управление окружениями через GitLab API

```bash
# Получить список окружений
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<id>/environments"

# Экспорт/импорт окружений для бэкапа
glab api projects/<id>/environments | jq '.[] | .name'
```

## Дополнительная информация

### Антипаттерны при использовании GitLab Flow
*   **Долгоживущие ветки:** Хранение feature-веток неделями без слияния приводит к «аду конфликтов».
*   **Hotfix в обход main:** Исправление бага напрямую в релизной ветке или в `production`. Это гарантирует возвращение бага в следующем релизе.
*   **Отсутствие CI в Merge Request:** Если тесты запускаются только после слияния, стратегия теряет защитную функцию.
*   **Прямое редактирование веток окружений:** Изменения должны продвигаться только через MR, а не через прямой пуш в `staging` или `production`.
*   **Отсутствие Protected Environments:** Без настройки защитных прав на окружения любой разработчик может задеплоить изменения в production.

### Rollback стратегии в GitLab Flow

GitLab Flow подразумевает строгое управление откатами через Git History и GitLab UI.

#### Rollback через Helm (Kubernetes)

```yaml
# .gitlab-ci.yml для rollback
rollback_production:
  stage: rollback
  image: bitnami/kubectl:1.31
  script:
    - kubectl config use-context production
    - helm rollback myapp --namespace production
    - kubectl rollout status deployment/myapp -n production
  environment:
    name: production
    url: https://myapp.com
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

#### Rollback через Git History

```bash
# 1. Найти коммит до проблемного изменения
git log --oneline -10

# 2. Откатить изменения через revert
git revert <problematic_commit_hash>

# 3. Push изменений
git push origin main

# GitLab CI автоматически задеплоит откат через пайплайн
```

#### Rollback через GitLab UI

1. Перейти в **Operate > Environments**
2. Выбрать целевое окружение (production)
3. Нажать **Rollback** или выбрать предыдущий деплой
4. Подтвердить откат

## Troubleshooting

#### Проблема 1: Merge Train не запускается

**Причина:** Отключена опция Merge Trains в настройках проекта или не хватает тарифа.

**Решение:**
1. **Settings > General > Merge requests**
2. Включить **Enable merge trains**
3. Убедиться, что выбран правильный метод слияния (Merge commit или Semi-linear merge)
4. **Важно:** Merge Trains доступны только в GitLab Premium и Ultimate. Для бесплатного тарифа используйте стандартный Merge Request pipeline с проверками.

#### Проблема 2: Review App не удаляется после закрытия MR

**Причина:** Отсутствует задача `stop_review_app` с `action: stop` или не настроен `on_stop`.

**Решение:**
```yaml
# Добавить в .gitlab-ci.yml
stop_review_app:
  stage: deploy
  script:
    - kubectl delete namespace review-$CI_MERGE_REQUEST_IID --ignore-not-found
  environment:
    name: review/$CI_MERGE_REQUEST_IID
    action: stop
  when: manual
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

#### Проблема 3: Деплой в production блокируется

**Причина:** Protected Environment требует Approval Rules, но у текущего пользователя нет прав.

**Решение:**
1. **Settings > CI/CD > Environments**
2. Выбрать **production**
3. Настроить **Approval Rules**:
   - Добавить пользователей или группы
   - Установить количество требуемых одобрений
4. Убедиться, что вы назначены как Approver

#### Проблема 4: Пайплайн не запускается для ветки окружений

**Причина:** Отсутствует правило `workflow:rules` для данной ветки или конфликт правил.

**Решение:**
```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_BRANCH == "staging"
    - if: $CI_COMMIT_BRANCH == "production"
```

#### Проблема 5: Cherry-pick не применяется к stable ветке

**Причина:** Конфликт или неверный формат команды.

**Решение:**
```bash
# Правильный порядок cherry-pick
git checkout 2-3-stable
git cherry-pick <commit_hash>

# Если конфликт
git cherry-pick --continue

# Автоматический cherry-pick через GitLab CI
# Используйте переменную CI_COMMIT_SHA для автоматизации
```

#### Проблема 6: Артефакт пересобирается при продвижении по окружениям

**Причина:** В `.gitlab-ci.yml` используется `rules` с `if: $CI_COMMIT_BRANCH`, что запускает новую сборку на каждой ветке.

**Решение:** Используйте один и тот же артефакт, собранный в `main`, и продвигайте его через `needs` и `dependencies` или внешний Registry без пересборки.

#### Проблема 7: Защищённый Runner недоступен для production-деплоя

**Причина:** Runner не помечен как `protected`, а ветка `production` защищена.

**Решение:**
1. В настройках Runner добавить тег `protected`
2. В задаче деплоя указать `tags: [protected]`
3. Убедиться, что Runner зарегистрирован с `--locked=true`

#### Проблема 8: Approval Rule не срабатывает для Protected Environment

**Причина:** Правило настроено на группу, но пользователь не состоит в ней, или включен режим `Prevent approval by author`.

**Решение:**
1. Проверить membership в группе/проекте
2. Отключить **Prevent approval by author** если автор MR должен быть able to approve
3. Проверить, что не включен **Prevent approval by committers** если нужен внешний аппрув

### Аудит через Merge Requests

Каждое изменение проходит через MR с полной историей:
- Кто создал MR
- Кто провел Code Review
- Какие проверки прошли
- Кто одобрил деплой
- Время всех операций

#### Pipeline Execution Policies

Принудительные проверки на уровне группы/проекта:

```yaml
# Пример Pipeline Execution Policy
# Настройка через Settings > CI/CD > Pipeline execution policies

# Все пайплайны должны включать:
# - SAST проверку
# - Secret Detection
# - Code Coverage > 80%
# - Manual Approval для production
```

#### Audit Events

GitLab предоставляет аудит-события для отслеживания:
- Деплоев в production
- Изменений Protected Environments
- Merge Requests с одобрениями
- Изменений Pipeline Execution Policies

### Интеграция с DevOps инструментами

#### GitLab Flow + ArgoCD

```yaml
# .gitlab-ci.yml для интеграции с ArgoCD
deploy_argocd:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    # Обновление манифестов ArgoCD
    - kubectl patch application myapp -n argocd
      --type merge
      -p '{"spec":{"source":{"targetRevision":"'$CI_COMMIT_SHA'"}}}'
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

#### GitLab Flow + Helm

```yaml
# .gitlab-ci.yml для Helm
helm_deploy:
  stage: deploy
  image: alpine/helm:3.16
  script:
    - helm upgrade --install myapp ./chart
      --namespace production
      --set image.tag=$CI_COMMIT_SHA
      --values values-production.yaml
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

#### GitLab Flow + Kubernetes

```yaml
# .gitlab-ci.yml для Kubernetes
kubectl_deploy:
  stage: deploy
  image: bitnami/kubectl:1.31
  script:
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/myapp -n production
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Лучшие практики

*   **Feature Flags:** Используйте переключатели функционала, чтобы вливать незавершенный код в `main` без риска для пользователей. Это позволяет сократить время жизни веток.
*   **DevSecOps:** Интегрируйте SAST/DAST сканирование и поиск секретов на этапе MR. GitLab Flow позволяет блокировать небезопасный код до попадания в `main`.
*   **Автоматизация Cherry-picking:** Используйте GitLab CI или ботов для автоматического переноса коммитов с меткой `backport` в стабильные ветки.
*   **Compliance Pipelines:** Настройте принудительные проверки на уровне группы, чтобы гарантировать соблюдение флоу во всех проектах.
*   **Один артефакт — все окружения:** Собирайте артефакт один раз (при слиянии в `main` или создании тега) и продвигайте его без пересборки. Это исключает drift между окружениями.
*   **Защита веток и окружений:** Включите Branch Protection для `main` и `production`. Настройте Protected Environments с Approval Rules для production-деплоев.
*   **Короткоживущие ветки:** Сливайте feature-ветки как можно быстрее (в пределах 1–2 дней). Долгоживущие ветки приводят к «аду конфликтов».
*   **Conventional Commits:** Используйте префиксы `feat:`, `fix:`, `chore:`, `docs:` — они упрощают автогенерацию changelog и понимание истории.
*   **Squash and Merge:** Для `main` рекомендуется squash-слияние, чтобы сохранить историю чистой. Для веток окружений — обычный merge, чтобы сохранить контекст продвижения.
*   **Мониторинг пайплайнов:** Отслеживайте Pipeline Success Rate (цель ≥ 95%) и Pipeline Duration p95 (цель < 15 мин). Настройте алерты на падение success rate.
*   **Резервное копирование конфигурации:** Храните `.gitlab-ci.yml` и все инфраструктурные манифесты в Git. Используйте MR для любых изменений пайплайна.

### Смотрите также
*   **[Обзор рабочих процессов в Git](../../../Git/git_workflows.md)** — сравнение с Git Flow и GitHub Flow.
*   **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — принципы работы пайплайнов.
*   **[Review Apps и динамические окружения](./kubernetes_review_apps.md)** — настройка сред для MR.
*   **[Окружения и деплой в GitLab](../Concepts/environments_and_deployments.md)** — детальная настройка прав доступа и Approval Rules.
*   **[Git Branching](../../../Git/git_branching.md)** — стратегии ветвления и конвенции именования.
*   **[Развёртывание и откаты](../../Core_Concepts/deployment_strategies.md)** — стратегии Blue/Green, Canary, Feature Flags.
*   **[Feature Toggles](../../Testing/feature_toggles/overview.md)** — управление функционалом через флаги.
*   **[GitLab CI/CD Advanced](../Advanced/gitlab_ci_advanced_workflow.md)** — продвинутые рабочие процессы (DAG, OIDC, SLSA).
