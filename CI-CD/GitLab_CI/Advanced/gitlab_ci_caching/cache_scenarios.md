# Практические сценарии кэширования в GitLab CI

## Определения

**Практический сценарий кэширования** — типовая конфигурация кэширования для распространённых задач разработки (управление зависимостями, монорепозитории, контейнерные сборки).

**Якорь YAML (`&` / `*`)** — механизм переиспользования конфигурации в GitLab CI через `&anchor_name` (объявление) и `*anchor_name` (ссылка).

## Основные концепции

### Принципы построения сценариев

1. **Используйте якоря YAML** для переиспользования конфигурации кэша между задачами
2. **Настраивайте политики** (`pull`, `push`, `pull-push`) для каждой задачи отдельно
3. **Кэшируйте по файлам зависимостей** для автоматического обновления кэша
4. **Разделяйте кэши** для разных типов зависимостей (npm, pip, maven)

### Ограничения

- Максимум 4 кэша на задачу
- Размер кэша ограничен настройками сервера GitLab
- Кэш для защищённых веток изолирован по умолчанию

### Переменные окружения для кэширования

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `CI_PROJECT_DIR` | Корневая директория проекта | `/builds/group/project` |
| `CI_COMMIT_REF_SLUG` | Нормализованное имя ветки | `feature-my-branch` |
| `CI_DEFAULT_BRANCH` | Имя основной ветки | `main` |

## Практические сценарии

### Сценарий 1: Кэширование NPM-зависимостей

Рекомендуемый подход для Node.js-проектов:

```yaml
variables:
  npm_config_cache: "$CI_PROJECT_DIR/.npm"

default:
  cache: &global_cache
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
      - .npm/
    policy: pull

install_dependencies:
  stage: build
  script:
    - npm ci --cache .npm --prefer-offline
  cache:
    <<: *global_cache
    policy: pull-push

test_job:
  stage: test
  script:
    - npm run test
  cache:
    <<: *global_cache
    policy: pull
```

**Ключевые моменты:**

- `npm ci --prefer-offline` использует локальный кэш
- `install_dependencies` обновляет кэш (`pull-push`)
- `test_job` только читает кэш (`pull`)

### Сценарий 2: Раздельные кэши для разных компонентов

Для проектов с несколькими типами зависимостей:

```yaml
test:
  cache:
    - key:
        files:
          - Gemfile.lock
      paths:
        - vendor/ruby
      policy: pull-push

    - key:
        files:
          - yarn.lock
      paths:
        - .yarn-cache/
      policy: pull-push

    - key:
        files:
          - requirements.txt
      paths:
        - .venv/
      policy: pull
```

**Ключевые моменты:**

- До 4 кэшей на задачу
- Отдельные ключи для каждого типа зависимостей
- Разные политики для разных задач

### Сценарий 3: Общий кэш для всех веток

⚠️ **Предупреждение:** Используйте только в доверенной среде.

```yaml
cache:
  key: global-cache
  paths:
    - .m2/repository/
```

**Настройка в UI GitLab:**

1. Settings → CI/CD
2. General pipelines
3. Снимите галочку **Use separate caches for protected branches**
4. Save changes

**Риск безопасности:** Разные разработчики могут получить доступ к кэшу друг друга.

### Сценарий 4: Кэширование в монорепозитории

Для проектов с несколькими сервисами:

```yaml
# Общий кэш для всех сервисов
cache:
  key:
    files:
      - services/frontend/package-lock.json
      - services/backend/requirements.txt
  paths:
    - services/frontend/node_modules/
    - services/backend/.venv/

# Или раздельные кэши
cache-frontend:
  key:
    files:
      - services/frontend/package-lock.json
  paths:
    - services/frontend/node_modules/

cache-backend:
  key:
    files:
      - services/backend/requirements.txt
  paths:
    - services/backend/.venv/
```

**Ключевые моменты:**

- Раздельные кэши уменьшают размер каждого кэша
- Общий кэш упрощает конфигурацию

### Сценарий 5: Кэширование слоев Docker

Ускорение сборки Docker-образов через переиспользование слоев:

```yaml
build_image:
  stage: build
  image: docker:20.10.16
  services:
    - docker:20.10.16-dind
  variables:
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG
    CACHE_IMAGE_TAG: $CI_REGISTRY_IMAGE:latest
  script:
    - docker pull $CACHE_IMAGE_TAG || true
    - docker build --cache-from $CACHE_IMAGE_TAG -t $IMAGE_TAG -t $CACHE_IMAGE_TAG .
    - docker push $IMAGE_TAG
    - docker push $CACHE_IMAGE_TAG
```

**Стратегия:**

1. `docker pull` загружает последний образ для использования как кэш
2. `docker build --cache-from` использует слои из загруженного образа
3. `docker push` сохраняет новый образ для следующих сборок

**Ключевые моменты:**

- GitLab CI `cache` не используется напрямую
- Docker-демон управляет кэшированием слоев
- Работает с `shell` и `docker` executor'ами

## Дополнительная информация

### Связанные документы

Ключи и политики: [ключи кэша](./cache_keys.md), рекомендации: [лучшие практики](./cache_best_practices.md), концепции: [обзор кэширования](./caching_overview.md), конфигурация артефактов: [артефакты GitLab CI](./gitlab_ci_artifacts.md).
