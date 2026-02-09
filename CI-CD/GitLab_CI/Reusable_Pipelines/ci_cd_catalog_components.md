# GitLab CI: Каталог Компонентов (CI/CD Catalog)

### Основные концепции

#### CI/CD Catalog (Components) — Современный подход к переиспользованию

CI/CD Catalog — наиболее современный и рекомендуемый подход GitLab. Он позволяет создавать версионируемые **компоненты** — полноценные, изолированные блоки CI/CD логики, которые можно публиковать в общем каталоге и использовать в проектах.

**Основные преимущества компонентов над традиционными `include` шаблонами:**

1. **Явное версионирование:** Каждый компонент имеет свою версию (например, `@1.0`, `@~1.0`, `@stable`), обеспечивая стабильность и предсказуемость.
2. **Строго типизированные интерфейсы (`spec:inputs`):** Компоненты могут определять входные параметры с указанием типа, значений по умолчанию и регулярных выражений для валидации, создавая четкий API.
3. **Повышенная изоляция:** Компоненты спроектированы как самостоятельные блоки, что способствует лучшей модульности.
4. **Улучшенное обнаружение и управление:** Компоненты публикуются в централизованном каталоге GitLab, что упрощает их поиск и использование.
5. **Автоматическая документация:** Каталог может автоматически генерировать документацию.

**Структура компонента:**
Компонент обычно состоит из файла `template.yml` (основная логика CI/CD) и файла `gitlab-ci.yml` (метаданные и `spec:inputs`).

### Практические сценарии

#### Сценарий 3: Использование CI/CD Catalog (Components)

**Пример использования компонента (в файле `.gitlab-ci.yml` проекта):**

```yaml
include:
  - component: '$CI_SERVER_HOST/my-group/my-component/my-build-component@1.0.0'
    inputs:
      stage: build
      target_branch: main
      enable_cache: true
      dockerfile_path: "app/Dockerfile"
```

**Пример определения компонента (`gitlab-ci.yml` и `template.yml` в репозитории компонента):**

```yaml
# gitlab-ci.yml (в репозитории компонента 'my-build-component')
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage for the build job."
    target_branch:
      type: string
      default: main
      description: "The branch to trigger the build on."
      regex: '^(main|develop|feature/.*)$' # Валидация через regex
    enable_cache:
      type: boolean
      default: true
      description: "Enable Docker layer caching."

---

# template.yml (основная логика компонента)
# Использует переменные, переданные через `inputs`
build-component-job:
  stage: $[[ inputs.stage ]]
  rules:
    - if: '$CI_COMMIT_BRANCH == $[[ inputs.target_branch ]]'
  script:
    - echo "Building image for stage: $[[ inputs.stage ]]"
    - if [[ "$[[ inputs.enable_cache ]]" == "true" ]]; then echo "Cache enabled."; fi
    - docker build -f $[[ inputs.dockerfile_path ]] .
  # ... остальная логика сборки ...
```
