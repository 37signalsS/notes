# GitLab CI: Каталог компонентов — продвинутые сценарии

## Определения

**Продвинутый сценарий** — комплексный архитектурный паттерн использования CI/CD Components, выходящий за рамки базового импорта. Включает в себя миграцию крупномасштабных систем, управление монорепозиториями, многоуровневое каскадное подключение (chaining), стратегии безопасного развертывания новых версий и глубокую интеграцию с корпоративными политиками безопасности.

**Инкапсуляция логики** — принцип проектирования, при котором внутренние детали реализации (Bash-команды, Docker-образы) скрыты за декларативным интерфейсом `spec:inputs`, что снижает когнитивную нагрузку на разработчиков.

## Основные концепции

### Фазы интерполяции и область видимости

Для проектирования сложных систем необходимо учитывать жизненный цикл разрешения YAML-конфигурации:
1.  **Разрешение `include`**: GitLab собирает все файлы (компоненты, шаблоны, локальные файлы).
2.  **Интерполяция `inputs`**: Значения подставляются во все блоки кода. 
    *   *Важно:* Теги `!reference` разрешаются **после** инпутов, поэтому передать `inputs` внутрь ссылки `!reference` напрямую невозможно.
3.  **Обработка `variables`**: Инициализируются переменные. Значения из `inputs` уже доступны для использования внутри блока `variables`.
4.  **Разрешение `extends` и `!reference`**: Выполняется финальное слияние структур и вставка фрагментов кода.

### Безопасность и цепочка поставок (Supply Chain Security)

Компоненты каталога обеспечивают уровень защиты Enterprise-класса:
-   **Изоляция контекста**: Интерполяция `$[[ inputs.* ]]` выполняется в изолированной области видимости, исключая конфликты имен между независимыми модулями.
-   **Контроль версий**: Поддержка Commit SHA (`@abc123de...`) гарантирует неизменность кода компонента и защищает от атак типа «отравление тега».
-   **Интеграция с OIDC**: Использование `id_tokens` внутри компонентов позволяет реализовать Zero Trust аутентификацию в облаках без долгоживущих секретов.

---

## Практические сценарии

### Сценарий 1: Миграция с include:project на компоненты

**До (Legacy):** Пайплайны зависят от веток (например, `main`), что делает их нестабильными.
```yaml
include:
  - project: 'group/ci-templates'
    file: '/docker-build.yml'
    ref: main
```

**После (Modern):** Использование компонентов с SemVer и типизированными входами.
```yaml
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.5.0'
    inputs:
      image: docker:27.0
      push_registry: true
```

**Алгоритм миграции:**
1.  **Спецификация**: Создайте блок `spec:inputs` в исходном шаблоне.
2.  **Рефакторинг**: Замените обращения к переменным `$VAR` на интерполяцию `$[[ inputs.var ]]`.
3.  **Релиз**: Создайте тег SemVer (v1.0.0) и GitLab Release.
4.  **Проверка**: Используйте `glab ci lint --show-expanded` для подтверждения корректности.

### Сценарий 2: Компонент для монорепозитория (Selective CI)

Эффективное управление сборкой через селективный запуск заданий на основе путей.

```yaml
# templates/module-builder.yml
spec:
  inputs:
    module_path:
      type: string
    build_command:
      default: "make build"
---
build-module:
  stage: build
  script:
    - cd $[[ inputs.module_path ]]
    - $[[ inputs.build_command ]]
  rules:
    - changes:
        - $[[ inputs.module_path ]]/**/*
```

### Сценарий 3: Глубокая валидация через options и regex

Использование `options` создает выпадающие списки в UI GitLab, а `regex` защищает от некорректных строк.

```yaml
spec:
  inputs:
    deploy_env:
      type: string
      options: [dev, staging, prod]
    replicas:
      type: number
      regex: '^[1-5]$' # Ограничение от 1 до 5 инстансов
---
deploy_job:
  script:
    - echo "Deploying $[[ inputs.replicas ]] nodes to $[[ inputs.deploy_env ]]"
```

### Сценарий 4: Цепочка компонентов (Component Chaining)

Создание «золотых пайплайнов» организации путем каскадного подключения модулей.

```yaml
# templates/standard-pipeline.yml
spec:
  inputs:
    app_name: { type: string }
---
include:
  - component: '$CI_SERVER_FQDN/org/linter@2.0.0'
  - component: '$CI_SERVER_FQDN/org/docker-builder@3.1.0'
    inputs: { image_name: $[[ inputs.app_name ]] }
```
> *Внимание:* Каждый вложенный компонент учитывается в лимите 150 `include`.

### Сценарий 5: Постепенное внедрение (Rollout) через условия

Безопасное тестирование новых версий критических инструментов на части проектов.

```yaml
include:
  # 90% проектов на стабильной версии
  - component: '$CI_SERVER_FQDN/org/security-scan@1.5.0'
    rules:
      - if: '$CI_PROJECT_ID % 10 != 0'
  # 10% проектов тестируют RC
  - component: '$CI_SERVER_FQDN/org/security-scan@2.0.0-rc1'
    rules:
      - if: '$CI_PROJECT_ID % 10 == 0'
```

### Сценарий 6: Вложенные компоненты (Nested Components)

Явная передача параметров по иерархии вложенности.

```yaml
# templates/parent.yml
spec:
  inputs: { stage_name: { default: test } }
---
include:
  - component: $CI_SERVER_FQDN/my-org/child@1.0.0
    inputs: { target_stage: $[[ inputs.stage_name ]] }
```

### Сценарий 7: Глобальные входы пайплайна (v17.11+)

Создание динамических форм запуска в корневом `.gitlab-ci.yml` проекта.

```yaml
# .gitlab-ci.yml
spec:
  inputs:
    target_cluster:
      options: [k8s-eu, k8s-us]
      default: k8s-eu
---
include:
  - component: $CI_SERVER_FQDN/org/k8s-deploy@1.0.0
    inputs: { cluster: $[[ inputs.target_cluster ]] }
```

### Сценарий 8: Контекстная адаптация (v18.6+)

Компонент автоматически определяет версию инструментов на основе собственной версии.

```yaml
# templates/scanner.yml
run-scan:
  image: custom-registry/scanner:$[[ component.version ]]
  script:
    - scanner-cli --path .
```

---

## Валидация и устранение неисправностей

### Диагностика типичных ошибок

| Проблема | Причина | Способ решения |
| :--- | :--- | :--- |
| **Error 404** | Неверный путь или проект не «Catalog resource». | Проверьте настройки Visibility и путь к файлу в `templates/`. |
| **Input validation error** | Ошибка типа (string вместо number). | Оборачивайте числа в кавычки в YAML, если в `spec` указан тип `string`. |
| **Exceeded max includes** | Слишком глубокая вложенность (лимит 150). | Используйте `!reference` для переиспользования кода внутри одного файла. |
| **Interpolation failed** | Ошибка синтаксиса `$[[ ]]`. | Проверьте закрывающие скобки и отсутствие циклов в инпутах. |

### Инструменты отладки
- **`glab ci lint --show-expanded`**: Основной инструмент Senior-инженера для проверки итогового YAML.
- **Pipeline Editor**: Вкладка «View merged YAML» в Web UI.

---

## Лучшие практики

1.  **Атомарность**: Один компонент — одна логическая задача.
2.  **Версионирование (Security)**: В продакшене используйте **Commit SHA** вместо тегов для защиты Supply Chain.
3.  **Документирование**: Каждый `input` должен иметь `description`. Поле `README.md` обязательно.
4.  **Тестирование**: Создавайте папку `tests/` в репозитории компонента и запускайте проверку перед каждым релизом.

---

## Справочная информация

### Чек-лист перед публикацией
- [ ] Секция `spec:inputs` заполнена и синтаксически верна.
- [ ] Добавлена валидация через `regex` или `options`.
- [ ] Компонент прошел проверку через `glab ci lint --show-expanded`.
- [ ] Проект помечен как «Catalog resource».
- [ ] Создан релиз с тегом SemVer.

### Внешние ресурсы
- [GitLab Docs: CI/CD Components advanced patterns](https://docs.gitlab.com/ee/ci/components/index.html)
- [GitLab Docs: Pipeline execution policies](https://docs.gitlab.com/ee/user/application_security/policies/pipeline_execution_policies.html)

### Связанные документы
- **[GitLab CI: Каталог компонентов](./ci_cd_catalog_components.md)** — база и синтаксис.
- **[Ограничения каталога компонентов](./ci_cd_catalog_limits.md)** — системные лимиты.
- **[Справочная информация по каталогу](./ci_cd_catalog_reference.md)** — API и CLI.
