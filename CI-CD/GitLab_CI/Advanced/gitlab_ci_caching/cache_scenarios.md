# Практические сценарии кэширования

## Сценарий 1: Кэширование NPM-зависимостей (рекомендуемый подход)

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
    policy: pull-push  # Эта задача обновляет кэш

test_job:
  stage: test
  script:
    - npm run test
  cache:
    <<: *global_cache
    policy: pull  # Только использует
```

## Сценарий 2: Раздельные кэши для разных компонентов

```yaml
# Максимум 4 кэша на задачу
test:
  cache:
    # Кэш для Ruby-зависимостей
    - key:
        files:
          - Gemfile.lock
      paths:
        - vendor/ruby
      policy: pull-push
    
    # Кэш для JavaScript-зависимостей
    - key:
        files:
          - yarn.lock
      paths:
        - .yarn-cache/
      policy: pull-push
    
    # Кэш для Python-зависимостей
    - key:
        files:
          - requirements.txt
      paths:
        - .venv/
      policy: pull
```

## Сценарий 3: Общий кэш для всех веток

```yaml
# Опасно для production! Используйте только в доверенной среде
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

⚠️ **Предупреждение:** Отключение разделения кэшей — риск безопасности.

## Сценарий 4: Кэширование в монорепозитории

```yaml
# Разные кэши для разных сервисов
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

## Связанные документы

- [Основные концепции](./cache_concepts.md)
- [Лучшие практики](./cache_best_practices.md)
