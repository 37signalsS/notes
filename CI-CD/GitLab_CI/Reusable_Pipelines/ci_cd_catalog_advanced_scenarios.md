# GitLab CI: Каталог Компонентов — Продвинутые сценарии

## Определения

**Продвинутый сценарий** — сложные паттерны использования CI/CD Components: миграция, монорепозитории, цепочки компонентов, troubleshooting.

---

## Практические сценарии

### Сценарий 6: Миграция с `include:project` на компоненты

**До (include:project):**

```yaml
include:
  - project: 'group/ci-templates'
    file: '/docker-build.yml'
    ref: main  # Нет версионирования!
```

**После (component):**

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.0.0'
    inputs:
      image: docker:24.0
      push_registry: true
```

**Шаги миграции:**

1. Создайте `.gitlab-ci.yml` с `spec:inputs` в репозитории шаблона
2. Добавьте интерполяцию `$[[ inputs.* ]]` вместо переменных
3. Создайте тег SemVer и релиз
4. Обновите проекты-потребители на `include:component`
5. Удалите старые файлы шаблонов

### Сценарий 7: Компонент для монорепозитория

```yaml
# Компонент для сборки только изменённых модулей
spec:
  inputs:
    module_path:
      type: string
      description: "Path to the module"
    build_command:
      default: "make build"
      type: string

---
build-changed-module:
  stage: build
  image: golang:1.21
  script:
    - cd $[[ inputs.module_path ]]
    - $[[ inputs.build_command ]]
  rules:
    - changes:
        - $[[ inputs.module_path ]]/**/*
      when: on_success
    - when: never  # Не запускать, если нет изменений
```

**Использование в монорепозитории:**

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/module-builder@1.0.0'
    inputs:
      module_path: services/api
      build_command: go build ./...

  - component: '$CI_SERVER_FQDN/group/ci-components/module-builder@1.0.0'
    inputs:
      module_path: services/web
      build_command: npm run build
```

### Сценарий 8: Компонент с условной логикой

```yaml
spec:
  inputs:
    deploy_environment:
      type: string
      regex: '^(dev|staging|prod)$'
    require_approval:
      type: boolean
      default: false

---
deploy_job:
  stage: deploy
  script:
    - echo "Deploying to $[[ inputs.deploy_environment ]]"
    - kubectl apply -f k8s/$[[ inputs.deploy_environment ]]/
  rules:
    # Для prod всегда требуется ручное подтверждение
    - if: '$[[ inputs.deploy_environment ]] == "prod" && $[[ inputs.require_approval ]] == true'
      when: manual
      allow_failure: false
    
    # Для dev/staging — автоматически
    - if: '$[[ inputs.deploy_environment ]] != "prod"'
      when: on_success
```

### Сценарий 9: Цепочка компонентов (component chaining)

```yaml
# Компонент оркестрации пайплайна
spec:
  inputs:
    app_name:
      type: string
    environment:
      type: string
      default: dev

---
# Включаем другие компоненты последовательно
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/linter@1.0.0'
    inputs:
      language: go
  
  - component: '$CI_SERVER_FQDN/group/ci-components/test-runner@1.0.0'
    inputs:
      coverage: true
  
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-builder@1.0.0'
    inputs:
      image_name: $[[ inputs.app_name ]]
  
  - component: '$CI_SERVER_FQDN/group/ci-components/deployer@1.0.0'
    inputs:
      environment: $[[ inputs.environment ]]
```

> **Важно:** каждый компонент в цепочке учитывается в лимите 150 include.

### Сценарий 10: A/B тестирование компонентов

```yaml
# Постепенный переход на новую версию компонента
include:
  # 90% проектов используют стабильную версию
  - component: '$CI_SERVER_FQDN/group/ci-components/test-runner@1.0.0'
  
  # 10% проектов тестируют новую версию (через переменную)
  - component: '$CI_SERVER_FQDN/group/ci-components/test-runner@2.0.0-beta'
    rules:
      - if: '$CI_PROJECT_ID == "123" || $CI_PROJECT_ID == "456"'  # Только тестовые проекты
```

**Стратегия rollout:**

| Этап | Охват | Версия | Действие |
| :--- | :--- | :--- | :--- |
| 1 | 5% | `@2.0.0-beta` | Тестирование на dev-проектах |
| 2 | 25% | `@2.0.0-rc` | Расширенное тестирование |
| 3 | 100% | `@2.0.0` | Полный релиз |

### Сценарий 11: Отладка и troubleshooting

**Проблема:** компонент не загружается

```bash
# 1. Проверка доступности компонента
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/ci/components"

# 2. Валидация конфигурации
gitlab-ci lint --project=group/project --show-expanded

# 3. Проверка тега
git tag -l | grep "v1.0"
git show v1.0.0:.gitlab-ci.yml | head -20
```

**Проблема:** validation failed для inputs

```bash
# Проверка типов данных
# Ошибка: expected string, got number
# Решение: обернуть число в кавычки
inputs:
  node_version: "20"  # Было: 20 (без кавычек)
```

**Проблема:** превышен лимит include

```bash
# Подсчёт количества include
gitlab-ci lint --project=group/project --show-expanded 2>&1 | grep -c "include:"

# Оптимизация: объединить компоненты
# Было: 3 компонента по 5 jobs каждый = 15 include
# Стало: 1 компонент с 15 jobs = 1 include
```

### Сценарий 12: Best practices для production

**1. Фиксируйте полные версии:**

```yaml
# ✅ Хорошо
- component: '$CI_SERVER_FQDN/group/component@1.2.3'

# ⚠️ Допустимо только для dev
- component: '$CI_SERVER_FQDN/group/component@1.2'

# ❌ Избегайте в production
- component: '$CI_SERVER_FQDN/group/component@~latest'
```

**2. Документируйте inputs:**

```yaml
spec:
  inputs:
    image:
      type: string
      default: "docker:24.0"
      description: "Docker image для сборки (формат: image:tag)"
      regex: '^[\w\-\.]+:\d+\.\d+$'  # Валидация формата
    
    enable_cache:
      type: boolean
      default: true
      description: |
        Включить кэширование зависимостей.
        Отключите для чистой сборки.
```

**3. Тестируйте компонент перед релизом:**

```yaml
# .gitlab-ci.yml в репозитории компонента
test-component:
  stage: test
  script:
    - gitlab-ci lint --project=$CI_PROJECT_PATH
    - echo "Component validation passed"

release:
  stage: deploy
  needs: test-component  # Релиз только после успешного теста
  rules:
    - if: $CI_COMMIT_TAG
```

**4. Используйте semantic-release для автоматизации:**

```yaml
semantic-release:
  stage: release
  image: node:20
  script:
    - npm install -g semantic-release
    - npx semantic-release
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

---

## Справочная информация

### Чек-лист перед публикацией компонента

- [ ] `spec:inputs` заполнен и валиден
- [ ] Все inputs имеют `description`
- [ ] Типы данных соответствуют использованию
- [ ] `regex` валидация добавлена для строковых полей
- [ ] Компонент проходит `gitlab-ci lint`
- [ ] Создан тег SemVer (vX.Y.Z)
- [ ] Создан GitLab Release
- [ ] Проект видим для потребителей
- [ ] Документация обновлена

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [GitLab Components Catalog](https://gitlab.com/explore/catalog)
- [Примеры компонентов GitLab](https://gitlab.com/gitlab-org/ci-cd/components)

---

## Связанные документы

- **SSoT:** [GitLab CI: Каталог Компонентов](./ci_cd_catalog_components.md)
- [Ограничения](./ci_cd_catalog_limits.md)
- [Справочная информация](./ci_cd_catalog_reference.md)
- [Механизм include](./include_keyword.md)
