# GitLab CI: Каталог компонентов — продвинутые сценарии

## Определения

**Продвинутый сценарий** — сложные паттерны использования CI/CD Components: миграция, монорепозитории, вложенные компоненты, устранение неисправностей (troubleshooting).

---

## Практические сценарии

### Сценарий 6: Миграция с include:project на компоненты

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

1. Создайте `.gitlab-ci.yml` с `spec:inputs` в репозитории шаблона.
2. Добавьте интерполяцию `$[[ inputs.* ]]` вместо переменных.
3. Создайте тег SemVer и релиз.
4. Обновите проекты-потребители на `include:component`.
5. Удалите старые файлы шаблонов.

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

### Сценарий 8: Компонент с использованием валидации через options

Использование `options` предпочтительнее `regex` для фиксированных списков значений, так как это обеспечивает лучшую валидацию в UI.

```yaml
spec:
  inputs:
    deploy_environment:
      type: string
      options: [dev, staging, prod]
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

> **Важно:** каждый компонент в цепочке учитывается в лимите 150 `include`.

### Сценарий 10: Постепенное внедрение (Rollout) компонентов

```yaml
# Постепенный переход на новую версию компонента через условия в правилах
include:
  # 90% проектов используют стабильную версию
  - component: '$CI_SERVER_FQDN/group/ci-components/test-runner@1.0.0'
  
  # 10% проектов тестируют новую версию
  - component: '$CI_SERVER_FQDN/group/ci-components/test-runner@2.0.0-beta'
    rules:
      - if: '$CI_PROJECT_ID == "123" || $CI_PROJECT_ID == "456"'
```

**Стратегия внедрения:**

| Этап | Охват | Версия | Действие |
| :--- | :--- | :--- | :--- |
| 1 | 5% | `@2.0.0-beta` | Тестирование на dev-проектах |
| 2 | 25% | `@2.0.0-rc` | Расширенное тестирование |
| 3 | 100% | `@2.0.0` | Полный релиз |

### Сценарий 11: Устранение неисправностей (Troubleshooting)

**Проблема: компонент не загружается**

```bash
# 1. Проверка доступности компонента через API
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/ci/components"

# 2. Валидация конфигурации через GitLab CLI
glab ci lint --show-expanded

# 3. Проверка тега и содержимого в репозитории
git tag -l | grep "v1.0"
git show v1.0.0:.gitlab-ci.yml | head -20
```

**Проблема: ошибка валидации для inputs**

```bash
# Проверка типов данных. Ошибка: expected string, got number.
# Решение: всегда оборачивайте числовые значения в кавычки в YAML, 
# если тип в spec указан как string.
inputs:
  node_version: "20"
```

**Проблема: превышен лимит include**

```bash
# Подсчёт количества include после раскрытия всех файлов
glab ci lint --show-expanded 2>&1 | grep -c "include:"

# Оптимизация: объединение компонентов. 
# Один компонент с несколькими заданиями считается за 1 include.
```

### Сценарий 12: Лучшие практики (Best practices)

1. **Фиксация версий.** Используйте полные версии (SemVer) для production и минорные/latest только для разработки.
   * Рекомендуется: `@1.2.3`
   * Избегайте: `@latest`

2. **Документирование.** Каждый input должен иметь `description`.

3. **Валидация.** Используйте `options` для перечислений и `regex` для сложных строк.

4. **Тестирование.** Проверяйте компоненты в изолированном проекте перед публикацией в основной каталог.

### Сценарий 13: Вложенные компоненты (Nested components)

Компоненты могут включать другие компоненты. Важно помнить, что входы (inputs) родительского компонента должны быть явно переданы дочернему.

```yaml
# templates/parent.yml
spec:
  inputs:
    stage_name:
      default: test
---
include:
  - component: $CI_SERVER_FQDN/my-org/sub-component@1.0.0
    inputs:
      target_stage: $[[ inputs.stage_name ]] # Явная передача входа дочернему компоненту
```

### Сценарий 14: Глобальные входы пайплайна (Pipeline-wide inputs)

Начиная с GitLab 17.11, можно определять `spec:inputs` прямо в основном файле `.gitlab-ci.yml`. Это позволяет создавать структурированный интерфейс запуска пайплайна (с выпадающими списками и чекбоксами) вместо обычных текстовых переменных.

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    deploy_target:
      options: [staging, production]
      default: staging
    run_tests:
      type: boolean
      default: true

---
include:
  - component: $CI_SERVER_FQDN/org/deploy-comp@1.0.0
    inputs:
      env: $[[ inputs.deploy_target ]]
```

---

## Справочная информация

### Чек-лист перед публикацией компонента

- [ ] Секция `spec:inputs` заполнена и валидна.
- [ ] Все входы имеют осмысленное `description`.
- [ ] Типы данных (`string`, `boolean`, `number`, `array`) соответствуют использованию.
- [ ] Добавлена валидация через `regex` или `options`.
- [ ] Компонент проходит проверку через `glab ci lint`.
- [ ] Создан тег SemVer (vX.Y.Z) и GitLab Release.
- [ ] Проект имеет корректный уровень видимости (Public/Internal).

### Внешние ресурсы

- [Документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [Каталог компонентов GitLab](https://gitlab.com/explore/catalog)

---

## Связанные документы

- **Основной документ:** [GitLab CI: Каталог компонентов](./ci_cd_catalog_components.md)
- [GitLab CI: Ограничения каталога](./ci_cd_catalog_limits.md)
- [GitLab CI: Справочник по каталогу](./ci_cd_catalog_reference.md)

