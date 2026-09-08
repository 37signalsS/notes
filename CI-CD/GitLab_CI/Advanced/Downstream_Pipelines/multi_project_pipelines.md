# Межпроектные пайплайны (Multi-project Pipelines)

## Определения

**Межпроектный пайплайн (Multi-project Pipeline)** — это тип downstream-пайплайна, который запускается в отдельном проекте GitLab. 

Этот механизм служит архитектурным мостом между независимыми репозиториями, позволяя:
- Связывать жизненные циклы разных компонентов (например, запуск тестов приложения при обновлении общей библиотеки).
- Разделять зоны ответственности и права доступа (например, отделение кода приложения от кода инфраструктурного деплоя).
- Строить сложные цепочки поставки (Supply Chain) в микросервисных архитектурах.

Технически реализация опирается на **Bridge Job** (задание-мост) в родительском проекте, которое отправляет API-запрос на создание пайплайна в целевом проекте через внутреннюю шину событий GitLab.

## Основные концепции

### Ключевые характеристики

- **Инициация:** Запускается через директиву `trigger:project` в YAML или программно через Pipeline Triggers API.
- **Изоляция:** Выполняется полностью в контексте целевого проекта. Используются Runner'ы, переменные и права доступа (Job Token), настроенные в проекте-получателе.
- **Вложенность:** При использовании директивы `trigger` лимит составляет **2 уровня**. Прямые вызовы через API не имеют жесткого лимита вложенности, но требуют осторожности для предотвращения бесконечных циклов.
- **Синхронизация (High Fidelity):** С версии GitLab 18.6 стратегия `mirror` позволяет родительскому заданию принимать финальный статус дочернего процесса (включая `manual` и `skipped`).
- **Агрегация отчетов (18.9+):** При использовании `strategy: mirror` результаты тестов (JUnit) и безопасности (SAST, DAST, SBOM) из дочернего проекта могут отображаться непосредственно в Merge Request родительского проекта.

### Безопасность и модель Zero Trust (v18.x)

В современных версиях GitLab (18.0+) безопасность межпроектных взаимодействий строится на модели **Zero Trust**. По умолчанию доступ одного проекта к другому через `CI_JOB_TOKEN` запрещен.

1.  **Inbound Allowlist (Обязательно):** Чтобы Проект А мог запустить триггер или скачать артефакты из Проекта Б, Проект Б должен явно добавить Проект А в список разрешенных. 
    *Путь: `Settings > CI/CD > Job Token Permissions > Allow access to the following projects`.*
2.  **Fine-grained Permissions (v18.3+):** Возможность ограничивать области действия токена (`scopes`). Например, можно разрешить проекту-инициатору только запуск пайплайнов, но запретить чтение реестра контейнеров.
3.  **Исключение PAT/Deploy Tokens:** Использование `CI_JOB_TOKEN` является стандартом. Передача персональных токенов доступа (PAT) через переменные считается небезопасной практикой и должна быть исключена.

### Наследование переменных

При межпроектном вызове действуют правила строгой изоляции:
- **Переменные проекта/группы** родителя НЕ наследуются. Передаются только те значения, которые указаны в блоке `trigger:variables` или проброшены через `trigger:forward`.
- **Маскированные секреты:** При передаче через триггер свойство маскирования (Masked) может быть потеряно, если в целевом проекте не настроено идентичное правило маскировки.
- **Приоритет:** Переменные, переданные через триггер, становятся переменными уровня пайплайна в целевом проекте и имеют высший приоритет выполнения.

Подробности см. в документе **[Наследование переменных](./variable_inheritance.md)**.

### API-триггеры и управление через curl

Помимо YAML-директивы `trigger:project`, межпроектные пайплайны можно запускать программно через Pipeline Triggers API:

```bash
# Запуск downstream-пайплайна через API
curl --request POST \
  --header "PRIVATE-TOKEN: $TRIGGER_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/trigger/pipeline" \
  --form "ref=main" \
  --form "variables[SERVICE_ID]=auth-api" \
  --form "variables[IMAGE_TAG]=v1.0"
```

**Контроль версий шаблонов:** API-триггеры позволяют явно указать `ref` дочернего пайплайна, что критично для pin-версий инфраструктурных конфигураций.

## Практические сценарии

### Сценарий 1: Синхронизация жизненного цикла через mirror

Наиболее надежный паттерн для критических обновлений, когда родительский пайплайн должен остановиться при ошибке в дочернем проекте.

```yaml
# Проект: app-service
trigger-infrastructure-deploy:
  stage: deploy
  trigger:
    project: 'ops/terraform-deploy'
    branch: main
    strategy: mirror # Родитель примет статус деплоя
  variables:
    SERVICE_ID: "auth-api"
    IMAGE_TAG: $CI_COMMIT_SHORT_SHA
```

### Сценарий 2: Кросс-проектные артефакты (needs:project)

Получение результатов сборки из другого проекта без использования `curl` и API-токенов.

```yaml
# Проект: performance-tests (Downstream)
# Требует добавления 'apps/main-api' в Inbound Allowlist
load-testing:
  stage: test
  needs:
    - project: 'apps/main-api'
      job: 'build-binary'
      ref: main
      artifacts: true
  script:
    - ./bin/app --benchmark
```

### Сценарий 3: Подписка на пайплайны (Pipeline Subscriptions)

Инвертированный триггер: Downstream проект автоматически запускается при обновлении Upstream проекта.
- **Где настроить:** `Settings > CI/CD > Pipeline subscriptions`.
- **Ограничение:** Работает только для **веток по умолчанию** (default branches).
- **Применение:** Автоматическая пересборка Docker-образа приложения при обновлении базового образа в другом репозитории.

```yaml
# Проект: shared-base-images (Upstream)
# При успешном пайплайне в main, автоматически запустится downstream
build-base-image:
  stage: build
  script:
    - docker build -t base-image:$CI_COMMIT_SHA .
    - docker push base-image:$CI_COMMIT_SHA

# Проект: app-service (Downstream, настроен через Pipeline Subscriptions)
# Автоматически запустится при обновлении shared-base-images/main
rebuild-with-new-base:
  stage: build
  script:
    - docker build --build-arg BASE_IMAGE=base-image:$CI_COMMIT_SHA .
```

### Сценарий 4: Microservice orchestration (fan-out/fan-in)

Параллельный триггер нескольких downstream-проектов с агрегацией результатов. Используется для координации зависимостей между микросервисами.

```yaml
# Проект: orchestrator
trigger-auth-service:
  stage: test
  trigger:
    project: 'backend/auth-service'
    branch: main
    strategy: mirror
  variables:
    DEPENDENCY_VERSION: $CI_COMMIT_SHA

trigger-billing-service:
  stage: test
  trigger:
    project: 'backend/billing-service'
    branch: main
    strategy: mirror
  variables:
    DEPENDENCY_VERSION: $CI_COMMIT_SHA

integration-test:
  stage: deploy
  script:
    - ./run-integration-tests.sh
  needs:
    - trigger-auth-service
    - trigger-billing-service
```

**Важно:** При `parallel:matrix` совместно с `strategy: mirror` Bridge Job ждет завершения **всех** инстансов матрицы. Общий статус будет `failed`, если хотя бы один инстанс упал.

### Сценарий 5: Infrastructure provisioning через multi-project

Разделение ответственности: DevOps-команда управляет Terraform-конфигурацией, application-команда запускает деплой.

```yaml
# Проект: app-service
trigger-infra-provision:
  stage: deploy
  trigger:
    project: 'infra/terraform-deploy'
    branch: main
    strategy: mirror
  variables:
    TF_ACTION: apply
    SERVICE_NAME: auth-api
    ENVIRONMENT: production

# Проект: infra/terraform-deploy
provision:
  script:
    - cd environments/$ENVIRONMENT
    - terraform init
    - terraform apply -auto-approve -var="service_name=$SERVICE_NAME"
  when: manual
  allow_failure: false
```

### Сценарий 6: Compliance и audit (разделение прав)

Паттерн для организаций с жесткими требованиями compliance: код приложения и код инфраструктуры находятся в разных проектах с разными правами доступа.

```yaml
# Проект: app-service (разработчики не имеют доступа к инфраструктуре)
trigger-compliance-check:
  stage: test
  trigger:
    project: 'compliance/security-scan'
    branch: main
    strategy: mirror
  variables:
    APP_REPO: $CI_PROJECT_PATH
    COMMIT_SHA: $CI_COMMIT_SHA

# Проект: compliance/security-scan (только DevOps/SRE)
sast-scan:
  script:
    - run-sast-scanner --project $APP_REPO --ref $COMMIT_SHA
  artifacts:
    reports:
      sast: gl-sast-report.json
dast-scan:
  script:
    - run-dast-scanner --project $APP_REPO --ref $COMMIT_SHA
  artifacts:
    reports:
      dast: gl-dast-report.json
```

### Сценарий 7: Shared Libraries как триггер

Автоматическая пересборка всех зависимых проектов при обновлении общей библиотеки. Используется в combo с Pipeline Subscriptions.

```yaml
# Проект: shared-lib (библиотека)
build-lib:
  stage: build
  script:
    - npm publish
  only:
    - main

# Проект: app-service (настроен через Pipeline Subscriptions на shared-lib)
rebuild-app:
  stage: build
  trigger:
    project: 'shared-lib/app-rebuild-trigger'
    branch: main
  variables:
    LIB_VERSION: $CI_COMMIT_SHA
```

## Технические нюансы и ограничения

-   **Риск Runner Deadlock:** Каждое родительское задание со стратегией `mirror` или `depend` занимает слот Runner'а всё время ожидания. При массовых триггерах между десятками проектов это может полностью парализовать очередь задач.
-   **Циклические зависимости:** GitLab имеет встроенные механизмы защиты, но при использовании API-вызовов риск создания бесконечной цепочки `A -> B -> A` сохраняется.
-   **Таймауты:** Таймаут родительской Bridge Job должен быть больше суммарного времени выполнения дочернего пайплайна.
-   **Лимит вложенности:** При использовании `trigger:project` максимальная глубина — **2 уровня**. Для более глубоких иерархий используйте Pipeline Triggers API.
-   **`needs` + `trigger` несовместимость:** Bridge Job не может быть зависимостью для других задач. Если задача использует `trigger`, она не может иметь `needs`.
-   **Fine-grained Permissions и scope:** При настройке Fine-grained Permissions (18.3+) убедитесь, что scope `api` или `read_api` включен для целевых операций (чтение артефактов, запуск пайплайнов).

## Диагностика и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `403 Forbidden` при запуске | Проект-инициатор не добавлен в Inbound Allowlist. | Добавьте upstream-проект в `Job Token Permissions` целевого проекта. |
| `Downstream pipeline not found` | Опечатка в пути к проекту или ветка не существует. | Проверьте путь (формат `group/subgroup/project`) и наличие ветки. |
| `Status stuck in Running` | Дочерний пайплайн ждет ручного подтверждения. | Нажмите кнопку в дочернем пайплайне или уберите `strategy: mirror`. |
| Артефакты не скачиваются | `CI_JOB_TOKEN` не имеет прав `read_api`. | Проверьте скоупы в Fine-grained Permissions (v18.3+). |
| `Downstream pipeline could not be created` | Неверный синтаксис YAML или отсутствует Allowlist. | Проверьте дочерний файл через CI Lint и настройки Token Access. |
| Deadlock при массовых триггерах | Все слоты Runner'а заняты Bridge Jobs. | Увеличьте `concurrency` или выделите отдельные Runner'ы для Bridge Jobs. |
| Циклическая зависимость `A -> B -> A` | API-триггер создал бесконечный цикл. | В GitLab есть встроенная защита, но проверьте цепочку триггеров вручную. |

## Рекомендации по эксплуатации

1. **Настраивайте Inbound Allowlist** для каждого проекта, который получает триггеры — это обязательно для GitLab 18.0+.
2. **Используйте Fine-grained Permissions** (18.3+) для ограничения scope `CI_JOB_TOKEN` только необходимыми правами.
3. **Избегайте PAT** — передача персональных токенов через переменные небезопасна. Используйте `CI_JOB_TOKEN` или `id_tokens` (OIDC).
4. **Мониторьте Bridge Jobs** через API (`GET /api/v4/projects/:id/pipelines/:pipeline_id/bridges`) для раннего обнаружения deadlock.
5. **Валидируйте конфигурацию** через `glab ci lint` перед коммитом в YAML-файлы downstream-проектов.
6. **Используйте `strategy: mirror`** для критических процессов (деплой, security-сканирование).
7. **Разделяйте зоны ответственности** — application-команда не должна иметь доступ к infrastructure-проектам.
8. **Настройте `interruptible: false`** для критических downstream-пайплайнов, чтобы предотвратить их отмену при auto-cancel родителя.

## См. также

- **[Определения Downstream-пайплайнов](./definitions.md)** — общая терминология.
- **[Лучшие практики](./best_practices.md)** — паттерны проектирования и оптимизация.
- **[Родительско-дочерние пайплайны](./parent_child_pipelines.md)** — декомпозиция внутри одного проекта.
- **[Стратегии выполнения](./strategies.md)** — детали работы `mirror` и `depend`.
