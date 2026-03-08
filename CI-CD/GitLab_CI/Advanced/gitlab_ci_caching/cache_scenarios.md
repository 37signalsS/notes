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

## Сценарий 5: Кэширование слоев Docker

Цель этого подхода — ускорить команду `docker build` за счет переиспользования слоев из ранее собранных образов. GitLab CI `cache` здесь напрямую не используется для хранения слоев, но он является частью общего паттерна.

**Стратегия:**

1. На предыдущем шаге CI/CD образ был собран и помещен в Docker Registry с тегом коммита и, возможно, тегом `latest`.
2. Текущая задача сборки сначала пытается вытянуть (`docker pull`) образ с тегом `latest` (или тегом основной ветки), чтобы Docker-демон мог использовать его слои в качестве кэша.
3. `docker build` запускается с флагом `--cache-from`, указывающим на этот "кэширующий" образ.
4. Новый образ сохраняется в Registry, становясь кэшем для следующей сборки.

```yaml
build_image:
  stage: build
  image: docker:20.10.16
  services:
    - docker:20.10.16-dind
  variables:
    # Имя образа
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG
    # Образ, который будет использоваться как кэш
    CACHE_IMAGE_TAG: $CI_REGISTRY_IMAGE:latest
  script:
    # Попытаться вытянуть последний образ для использования в качестве кэша.
    # allow_failure: true, так как на первой сборке этого образа еще не будет.
    - docker pull $CACHE_IMAGE_TAG || true
    
    # Собрать новый образ, используя старый как кэш
    - docker build 
        --cache-from $CACHE_IMAGE_TAG 
        -t $IMAGE_TAG 
        -t $CACHE_IMAGE_TAG .

    # Загрузить новый образ в Registry
    - docker push $IMAGE_TAG
    - docker push $CACHE_IMAGE_TAG
```

Этот паттерн эффективно работает как с `shell`, так и с `docker` executor'ами, поскольку основную работу по кэшированию выполняет сам Docker-демон, а не механизм кэша GitLab CI.

## Связанные документы

- [Основные концепции](./cache_concepts.md)
- [Лучшие практики](./cache_best_practices.md)
