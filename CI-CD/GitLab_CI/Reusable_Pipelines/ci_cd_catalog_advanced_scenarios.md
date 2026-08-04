# GitLab CI: Каталог компонентов — продвинутые сценарии

## Определения

**Продвинутый сценарий** — сложные архитектурные паттерны использования CI/CD Components, включая миграцию с legacy-подходов, управление монорепозиториями, многоуровневые цепочки зависимостей (chaining), стратегии постепенного внедрения и методы глубокой отладки.

---

## Практические сценарии

### Сценарий 6: Миграция с include:project на компоненты

**До (Legacy — include:project):**
Пайплайны зависят от файлов в ветках, что затрудняет контроль версий и аудит.
```yaml
include:
  - project: 'group/ci-templates'
    file: '/docker-build.yml'
    ref: main # Нет версионирования, риск внезапного падения при обновлении
```

**После (Modern — include:component):**
Использование компонентов с SemVer обеспечивает стабильность и строгий контракт параметров.
```yaml
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.5.0'
    inputs:
      image: docker:27.0
      push_registry: true
```

**Шаги миграции:**
1.  **Спецификация:** Создайте `.gitlab-ci.yml` с блоком `spec:inputs` в репозитории шаблона.
2.  **Инкапсуляция:** Замените глобальные переменные внутри заданий на интерполяцию `$[[ inputs.* ]]`.
3.  **Релиз:** Создайте тег SemVer (v1.0.0) и соответствующий GitLab Release.
4.  **Проверка:** Используйте `glab ci lint --show-expanded` для подтверждения корректности.
5.  **Очистка:** После перевода всех проектов удалите старые файлы шаблонов.

### Сценарий 7: Компонент для монорепозитория

Эффективное управление сборкой в монорепозиториях через селективный запуск заданий.

```yaml
# templates/module-builder.yml
spec:
  inputs:
    module_path:
      type: string
      description: "Относительный путь к директории модуля"
    build_command:
      default: "make build"
      type: string
---
build-changed-module:
  stage: build
  image: golang:1.24
  script:
    - cd $[[ inputs.module_path ]]
    - $[[ inputs.build_command ]]
  rules:
    - changes:
        - $[[ inputs.module_path ]]/**/*
      when: on_success
    - when: never # Игнорировать, если изменений в директории нет
```

**Применение в проекте:**
```yaml
include:
  - component: '$CI_SERVER_FQDN/org/module-builder@1.2.0'
    inputs:
      module_path: services/api
      build_command: go build ./...

  - component: '$CI_SERVER_FQDN/org/module-builder@1.2.0'
    inputs:
      module_path: services/web
      build_command: npm run build
```

### Сценарий 8: Валидация через options и regex

Использование `options` превращает входные данные в каскадные списки в UI GitLab (Run Pipeline), а `regex` обеспечивает защиту от инъекций и некорректных строк.

```yaml
spec:
  inputs:
    deploy_environment:
      type: string
      options: [dev, staging, prod]
    replicas:
      type: number
      regex: '^[1-5]$' # Ограничение от 1 до 5 инстансов
    require_approval:
      type: boolean
      default: false
---
deploy_job:
  stage: deploy
  script:
    - echo "Deploying to $[[ inputs.deploy_environment ]] with $[[ inputs.replicas ]] nodes"
  rules:
    - if: '$[[ inputs.deploy_environment ]] == "prod" && $[[ inputs.require_approval ]] == true'
      when: manual
      allow_failure: false
    - if: '$[[ inputs.deploy_environment ]] != "prod"'
      when: on_success
```

### Сценарий 9: Цепочка компонентов (Component Chaining)

Компоненты могут выступать в роли оркестраторов, последовательно подключая другие компоненты для формирования стандартного пайплайна компании.

```yaml
# templates/standard-pipeline.yml
spec:
  inputs:
    app_name:
      type: string
    environment:
      type: string
      default: dev
---
include:
  - component: '$CI_SERVER_FQDN/org/linter@2.0.0'
  - component: '$CI_SERVER_FQDN/org/test-runner@1.8.0'
    inputs:
      coverage: true
  - component: '$CI_SERVER_FQDN/org/docker-builder@3.1.0'
    inputs:
      image_name: $[[ inputs.app_name ]]
  - component: '$CI_SERVER_FQDN/org/deployer@4.0.0'
    inputs:
      env: $[[ inputs.environment ]]
```
> **Важно:** каждый вложенный компонент учитывается в системном лимите 150 `include`.

### Сценарий 10: Постепенное внедрение (Rollout) через условия

Стратегия безопасного обновления критической инфраструктуры (например, линтеров или систем сборки).

```yaml
include:
  # 90% проектов остаются на стабильной версии
  - component: '$CI_SERVER_FQDN/org/security-scan@1.5.0'
    rules:
      - if: '$CI_PROJECT_ID % 10 != 0'
  
  # 10% проектов тестируют Release Candidate (ID оканчивается на 0)
  - component: '$CI_SERVER_FQDN/org/security-scan@2.0.0-rc1'
    rules:
      - if: '$CI_PROJECT_ID % 10 == 0'
```

### Сценарий 11: Устранение неисправностей (Troubleshooting)

**Проблема 1: Компонент не загружается (Error 404)**
*   **Диагностика:** Проверьте доступность через API:
    `curl --header "PRIVATE-TOKEN: <token>" "https://gitlab.example.com/api/v4/projects/<project_id>/ci/components"`
*   **Решение:** Убедитесь, что файл находится в папке `templates/`, а тег в Git соответствует SemVer.

**Проблема 2: Ошибка валидации inputs**
*   **Симптом:** `expected string, got number`.
*   **Решение:** Всегда оборачивайте числовые значения в кавычки в YAML (например, `node_version: "22"`), если в `spec` указан тип `string`.

**Проблема 3: Превышен лимит include**
*   **Диагностика:** Подсчитайте количество вхождений через GitLab CLI:
    `glab ci lint --show-expanded | grep -c "include:"`
*   **Решение:** Объединяйте мелкие компоненты или используйте `!reference` для вставки скриптов без создания новых файлов.

### Сценарий 12: Лучшие практики (Best Practices)

1.  **Фиксация версий (Security):** В продакшене используйте **Commit SHA** (`@e3262fdb...`) для защиты от подмены тегов (Supply Chain Security).
2.  **Документирование:** Каждый `input` должен иметь `description`. Поле `README.md` в корне репозитория автоматически парсится интерфейсом каталога.
3.  **Атомарность:** Один компонент должен решать одну задачу. Не создавайте монолитные шаблоны на тысячи строк.
4.  **Тестирование:** Создавайте папку `tests/` в репозитории компонента и запускайте проверку через `glab ci lint` перед каждым релизом.

### Сценарий 13: Вложенные компоненты (Nested Components)

Компоненты могут включать другие компоненты. Входы родительского компонента необходимо явно передавать дочернему.

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
      target_stage: $[[ inputs.stage_name ]] # Проброс входа вниз по иерархии
```

### Сценарий 14: Глобальные входы пайплайна (Pipeline-wide inputs)

С версии GitLab 17.11 механизм `spec:inputs` можно использовать в корневом `.gitlab-ci.yml` проекта для создания динамических форм запуска.

```yaml
# .gitlab-ci.yml (Корневой файл проекта)
spec:
  inputs:
    deploy_target:
      options: [staging, production]
      default: staging
    run_security_scans:
      type: boolean
      default: true
---
include:
  - component: $CI_SERVER_FQDN/org/deploy-comp@1.0.0
    inputs:
      env: $[[ inputs.deploy_target ]]
```

### Сценарий 15: Интерполяция контекста (v18.6+)

Компоненты могут динамически адаптироваться к собственной версии или имени без передачи параметров из вызывающего пайплайна.

| Переменная | Описание |
| :--- | :--- |
| `$[[ component.name ]]` | Имя текущего компонента. |
| `$[[ component.version ]]` | Версия (тег или SHA), указанная при подключении. |
| `$[[ component.sha ]]` | Полный хеш коммита компонента. |

**Пример:** Автоматический выбор версии образа инструментов, соответствующей версии компонента.
```yaml
build:
  image: custom-registry/ci-tools:$[[ component.version ]]
  script:
    - run-build.sh
```

---

## Справочная информация

### Чек-лист перед публикацией компонента

- [ ] Секция `spec:inputs` заполнена и синтаксически верна.
- [ ] Все входы имеют подробное описание в поле `description`.
- [ ] Типы данных (`string`, `boolean`, `number`, `array`) соответствуют использованию в коде.
- [ ] Добавлена строгая валидация через `regex` или `options`.
- [ ] Компонент прошел проверку через `glab ci lint --show-expanded`.
- [ ] Создан тег в формате SemVer (vX.Y.Z) и GitLab Release.
- [ ] Проект помечен как «Catalog resource» в настройках видимости.

### Внешние ресурсы

- [GitLab Docs: CI/CD Components advanced patterns](https://docs.gitlab.com/ee/ci/components/index.html)
- [GitLab Docs: Pipeline execution policies](https://docs.gitlab.com/ee/user/application_security/policies/pipeline_execution_policies.html)

---

## Связанные документы

- **[GitLab CI: Каталог компонентов](./ci_cd_catalog_components.md)** — архитектура и базовый синтаксис.
- **[Ограничения каталога компонентов](./ci_cd_catalog_limits.md)** — системные лимиты и запрещенные ключи.
- **[Справочная информация по каталогу](./ci_cd_catalog_reference.md)** — API, CLI и история изменений.
