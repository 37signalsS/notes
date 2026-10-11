# Практические сценарии использования downstream-пайплайнов

**Актуально для:** GitLab 18.6+ / 19.x

## Определения

**Практические сценарии downstream-пайплайнов** — это набор архитектурных и технических паттернов, реализующих иерархические связи между пайплайнами для декомпозиции монолитных конфигураций, управления микросервисами и обеспечения безопасности процессов развертывания.

Технически сценарии базируются на использовании **Bridge Jobs** (заданий-мостов) и механизмов синхронизации состояний, позволяя строить сложные графы зависимостей как внутри одного проекта (**Parent-Child**), так и между независимыми репозиториями (**Multi-project**).

## Основные концепции

Эффективная реализация практических сценариев в современных версиях GitLab (18.x–19.x) строится на следующих принципах:

- **High Fidelity Mirroring (strategy: mirror):** Гарантирует, что статус родительского задания в точности повторяет состояние дочернего пайплайна. Это критично для автоматизации релизов, когда провал тестов в дочернем проекте должен блокировать деплой в родительском.
- **Декларативные контракты (spec:inputs):** Заменяют неявную передачу переменных на строго типизированный интерфейс. Это предотвращает запуск дочерних пайплайнов с некорректными параметрами и исключает риск инъекций.
- **Модель Zero Trust (CI_JOB_TOKEN):** Обеспечивает безопасность межпроектных взаимодействий через обязательную настройку **Inbound Allowlist**. Доступ к артефактам и API предоставляется только явно авторизованным проектам.

## Практические сценарии

### Сценарий 1: Селективный запуск в монорепозитории (Selective CI)

Паттерн для крупных проектов, где изменение в одном модуле не должно вызывать полный перезапуск CI для всех остальных компонентов.

**Принцип работы:** Использование `rules:changes` совместно с `trigger` позволяет запускать дочерние пайплайны только для измененных директорий.

```yaml
# .gitlab-ci.yml (Родительский)
trigger-auth-service:
  stage: test
  trigger:
    include: services/auth/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - services/auth/**/*
  allow_failure: false # Провал в auth-сервисе блокирует релиз монорепозитория

trigger-billing-service:
  stage: test
  trigger:
    include: services/billing/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - services/billing/**/*
```

### Сценарий 2: Кросс-проектное тестирование зависимостей

Сценарий для библиотек и SDK: выпуск новой версии библиотеки автоматически инициирует проверку совместимости в проектах-потребителях.

**Настройка безопасности:**
1. В проекте-потребителе (`main-app`) перейдите в `Settings > CI/CD > Token Access`.
2. Добавьте проект библиотеки (`shared-lib`) в список **Inbound Allowlist**.

```yaml
# Проект: shared-lib (Upstream)
publish-and-test:
  stage: deploy
  script:
    - npm publish
  trigger:
    project: 'web-apps/main-app'
    branch: main
    strategy: mirror
    forward:
      pipeline_variables: true

# Проект: main-app (Downstream)
integration-tests:
  stage: test
  needs:
    - project: 'group/shared-lib'
      job: 'publish-and-test'
      ref: main
      artifacts: true
  script:
    - npm install
    - npm test
```

### Сценарий 4: CI-driven деплой в Argo CD (GitOps Alternative)

В некоторых инфраструктурах GitLab CI используется как точка входа для динамической доставки манифестов в Argo CD через его REST API. Этот паттерн применяется, когда стандартный GitOps-подход (Argo CD следит за репозиторием) недостаточно гибок для динамической генерации конфигурации.

**Принцип работы:**
1. Upstream-пайплайн собирает артефакт (Helm-чарт, Kustomize overlay, YAML-манифест).
2. Downstream-пайплайн вызывает Argo CD API для синхронизации Application.
3. Argo CD применяет манифест в целевом кластере.

```yaml
# upstream-project/.gitlab-ci.yml
trigger_argocd_sync:
  stage: deploy
  trigger:
    project: 'platform/argocd-delivery'
    branch: main
    strategy: mirror
  variables:
    APP_NAME: $CI_PROJECT_NAME
    IMAGE_TAG: $CI_COMMIT_SHORT_SHA
    ENVIRONMENT: production
```

```yaml
# platform/argocd-delivery/.gitlab-ci.yml
sync_to_argocd:
  stage: deploy
  image: curlimages/curl:latest
  script:
    - |
      ARGOCD_TOKEN=$(curl -s -X POST https://argocd.example.com/api/v1/session \
        -d '{"username":"admin","password":"'"$ARGOCD_PASSWORD"'"}' \
        | jq -r '.token')
      
      curl -s -X POST "https://argocd.example.com/api/v1/applications/$APP_NAME/sync" \
        -H "Authorization: Bearer $ARGOCD_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"name":"'"$APP_NAME"'","prune":true,"selfHeal":true}'
  rules:
    - if: $CI_PIPELINE_SOURCE == "trigger"
```

**Преимущества:**
- **Гибкость:** Динамическое изменение параметров деплоя (image tag, replica count) на основе внешних данных.
- **Централизация:** Логика взаимодействия с Argo CD в одном проекте (`platform/argocd-delivery`).
- **Интеграция:** Легко добавить pre-sync проверки (миграции БД, smoke-тесты).

**Недостатки:**
- **Потеря GitOps-прозрачности:** Изменения не отслеживаются через Git-историю Argo CD.
- **Сложность отладки:** Требуется доступ к логам GitLab CI и API Argo CD.
- **Безопасность:** Токен Argo CD должен храниться в переменных проекта или внешнем менеджере секретов.

### Сценарий 5: Динамическое развертывание Review Apps

Создание временных окружений для тестирования каждой ветки (MR) с использованием динамически генерируемой конфигурации.

**Принцип работы:** Первый этап генерирует YAML-файл с уникальными параметрами окружения, второй этап запускает его как дочерний пайплайн.

```yaml
generate-review-env:
  stage: build
  script:
    - python3 scripts/generate_env_ci.py > review-app.yml
  artifacts:
    paths: [review-app.yml]

trigger-review:
  stage: deploy
  trigger:
    include:
      - artifact: review-app.yml
        job: generate-review-env
    strategy: mirror
```

## Дополнительная информация

### Сравнение архитектурных паттернов

| Характеристика | Parent-Child | Multi-project | Dynamic Generation |
| :--- | :---: | :---: | :---: |
| **Репозиторий** | Тот же | Разные | Тот же |
| **Уровень изоляции** | Низкий | Высокий | Средний |
| **Сложность отладки** | Низкая | Средняя | Высокая |
| **Безопасность (Secrets)** | Общая | Раздельная | Общая |
| **Основной кейс** | Монорепозиторий | Микросервисы | Review Apps |

### Диагностика и устранение неполадок

| Ошибка | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Downstream pipeline could not be created` | Ошибка в Allowlist (Zero Trust) или неверный путь к проекту. | Проверьте `Token Access` в настройках целевого проекта. |
| `Artifact not found for trigger` | Генератор не сохранил файл или задача упала. | Проверьте секцию `artifacts` в задаче-генераторе. |
| `Status stuck in Running` | Downstream ждет ручного подтверждения (`manual`) при `strategy: mirror`. | Нажмите кнопку в дочернем пайплайне или используйте асинхронный триггер. |
| `Security reports missing` | Не используется `strategy: mirror`. | Агрегация отчетов требует синхронной стратегии (GitLab 18.9+). |

### Рекомендации по эксплуатации

1. **Визуализация (Pipeline Graph):** В интерфейсе GitLab 18.x+ синхронные связи подсвечиваются особым цветом. Используйте граф для анализа критического пути.
2. **Лимиты вложенности:** Не забывайте о жестком лимите в **2 уровня** вложенности триггеров. Для сложных цепочек используйте Pipeline Triggers API.
3.  **Оптимизация ресурсов:** Используйте `interruptible: true` для downstream-задач, если они могут быть безопасно отменены при появлении нового коммита в родительской ветке.

## Edge Cases и известные проблемы (по сценариям)

- **Selective CI: неверный `changes` pattern** — слишком широкий pattern запускает лишние сервисы; слишком узкий — пропускает нужные. Решение: тестируйте pattern в MR через GitLab UI, используйте диз. deny-list вместе с allow-list.
- **Cross-project: несовместимые версии GitLab** — upstream и downstream на разных версиях могут иметь разные наборы `spec:inputs` или стратегий. Решение: синхронизируйте версии или используйте минимальный общий набор фич.
- **Argo CD: потеря связи между GitLab и Argo CD API** — если Argo CD недоступен, downstream-пайплайн завершится ошибкой. Решение: добавьте retry с экспоненциальной задержкой и fallback на ручной деплой.
- **Review Apps: "зombie" окружения** — если cleanup job не выполнился, временные окружения остаются в кластере. Решение: добавьте TTL на namespace или scheduled cleanup.
- **`needs:pipeline` с integer ID** — GitLab парсит numeric pipeline ID как integer, но ожидает string. Решение: заключайте ID в кавычки: `pipeline: "$UPSTREAM_PIPELINE_ID"`.
- **`parallel:matrix` + `mirror` в cross-project** — Bridge Job ожидает завершения всех инстансов матрицы. При >5 инстансах возможен deadlock. Решение: разбейте на отдельные триггеры или используйте `depend`.

### SRE: Инцидент-респонс

При расследовании инцидента в downstream-пайплайнах:

1. Определите статус Bridge Jobs в upstream-проекте:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges" | \
     jq '.[] | {id, name, status, downstream_pipeline}'
   # → [{"id": 101, "name": "trigger-billing-service", "status": "failed", "downstream_pipeline": {"id": 456}}]
   ```

2. Для cross-project сценариев проверьте статус downstream-проекта:
   ```bash
   curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$DOWNSTREAM_ID/pipelines/$DOWNSTREAM_PIPELINE_ID" | \
     jq '{id, status, ref, finished_at}'
   # → {"id": 456, "status": "success", "ref": "main", "finished_at": "2026-09-28T10:00:00Z"}
   ```

3. Для Argo CD сценариев проверьте статус Application через Argo CD API:
   ```bash
   curl --header "Authorization: Bearer $ARGOCD_TOKEN" \
     "https://argocd.example.com/api/v1/applications/$APP_NAME" | \
     jq '.status.health.status, .status.operationState.phase'
   # → "Healthy", "Succeeded"
   ```

4. Для Review Apps проверьте namespace в Kubernetes:
   ```bash
   kubectl get namespaces -l app=review-app
   # → NAME             STATUS   AGE
   # → review-123       Active   2h
   ```

5. При массовом падении downstream-пайплайнов проверьте:
   - Inbound Allowlist в целевом проекте.
   - Статус `CI_JOB_TOKEN` и Fine-grained Permissions (GitLab 18.3+).
   - Версии GitLab в upstream и downstream проектах.

6. Документируйте паттерн инцидента: какой проект-источник, какой проект-цель, какая стратегия, какие переменные передавались, время возникновения.

### Compliance и аудит

- **Аудит триггеров:** Все cross-project триггеры должны быть явно настроены через Inbound Allowlist. Регулярно ревьюьте список разрешенных проектов в `Settings > CI/CD > Token Access`.
- **Версионирование артефактов:** Для Review Apps и Argo CD deployments храните манифесты с уникальными именами, включающими `$CI_PIPELINE_ID` или `$CI_COMMIT_SHORT_SHA`. Это обеспечивает traceability и предотвращает перезапись.
- **Approve для production:** Используйте `when: manual` + `allow_failure: false` для production деплоев через cross-project триггеры. Это гарантирует, что деплой требует явного подтверждения.
- **Сегрегация duties:** Разделите права на изменение cross-project триггеров (DevOps team) и права на запуск пайплайнов (CI/CD). Это предотвращает несанкционированную модификацию конфигурации.
- **Аудит Security Reports:** При использовании `strategy: mirror` агрегация SAST/DAST/SBOM работает с GitLab 18.9+. Убедитесь, что downstream-проекты имеют совместимую версию GitLab.

### Очистка и откат

- **Откат cross-project триггера:** Для временного отключения используйте `rules: []` в Bridge Job. Это безопаснее, чем удаление конфигурации, так как сохраняет историю изменений.
- **Очистка Review Apps:** Добавьте scheduled job для удаления окружений старше N дней. Используйте `kubectl delete namespace review-<id>` или Argo CD Application deletion.
- **Откат Argo CD sync:** Используйте `argocd app rollback <app-name> <revision>` через API или UI. Храните revision history в Argo CD.
- **Очистка зависших Bridge Jobs:** Если Bridge Job завис в `running` после отката деплоя, перезапустите downstream-пайплайн или отмените Bridge Job через API.
- **Валидация после отката:** После отката триггера проверяйте, что upstream-пайплайн не пытается запустить отключенный триггер, и что downstream-проект остается в стабильном состоянии.

### Disaster Recovery

- **Fallback для Review Apps:** Если генератор не работает, используйте статический `.gitlab-ci.yml` с ручным указанием environments. Это позволяет продолжить тестирование MR даже при сбое генерации.
- **Fallback для Argo CD:** Если Argo CD API недоступен, заархивируйте манифесты и деплойте вручную через `kubectl apply`. Храните последний рабочий манифест в артефактах.
- **Восстановление cross-project связи:** Если Allowlist сброшен, добавьте проект обратно в `Settings > CI/CD > Token Access` и перезапустите пайплайн. Проверьте, что `CI_JOB_TOKEN` имеет нужные scopes.
- **Аварийный запуск без триггеров:** Для критичных сервисов подготовьте inline-конфигурацию или используйте Pipeline Triggers API для запуска downstream-пайплайна в обход Bridge Job.
- **Резервное копирование конфигураций:** Храните `.gitlab-ci.yml` и дочерние конфигурации в отдельном репозитории или артефакте. Это позволяет быстро восстановить пайплайн при потере ветки.

### Self-managed инсталляции

- **Резервные Runner'ы:** Для cross-project триггеров настройте Runner'ы с высокой доступностью. Bridge Job блокирует concurrency-слот при `mirror`, поэтому недостаток Runner'ов приводит к deadlock.
- **Мониторинг Sidekiq:** Мониторьте очередь `create_downstream_pipeline` на задержки. При высокой нагрузке увеличьте количество воркеров Sidekiq.
- **Резервное копирование базы данных:** Регулярно выполняйте backup PostgreSQL. Метаданные пайплайнов и Bridge Jobs хранятся в таблицах `ci_bridges`, `ci_pipelines` и `ci_builds`.
- **Версионирование GitLab:** Убедитесь, что все проекты в цепочке используют совместимые версии GitLab. Использование `spec:inputs` требует GitLab 17.0+, а агрегация Security Reports — 18.9+.
- **Резервное копирование реестра контейнеров:** Для cross-project сценариев, передающих артефакты, настройте репликацию Container Registry. Потеря артефактов означает невозможность запуска downstream-пайплайнов.

## См. также

- **[Определения Downstream-пайплайнов](./definitions.md)** — база и терминология.
- **[Лучшие практики](./best_practices.md)** — паттерны безопасности и Zero Trust.
- **[Стратегии выполнения](./strategies.md)** — управление жизненным циклом через `mirror`.
- **[Динамическая генерация](./dynamic_generation.md)** — подробный гайд по программному созданию пайплайнов.
