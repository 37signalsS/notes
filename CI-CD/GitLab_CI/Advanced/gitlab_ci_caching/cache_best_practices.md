# Лучшие практики кэширования в GitLab CI

## Рекомендации по использованию кэша

### 1. Используйте ключи по файлам зависимостей

**Рекомендуется:**
```yaml
cache:
  key:
    files:
      - package-lock.json
  paths:
    - node_modules/
```

**Не рекомендуется:**
```yaml
cache:
  key: "global-cache"  # Кэш не будет обновляться при изменении зависимостей
  paths:
    - node_modules/
```

### 2. Разделяйте кэш для разных задач

```yaml
build:
  cache:
    key: "build-cache"
    paths:
      - .npm/
      - .cache/

test:
  cache:
    key: "test-cache"
    paths:
      - .jest-cache/
```

### 3. Используйте правильную политику

```yaml
# Задача, которая обновляет зависимости
install:
  cache:
    policy: pull-push

# Задача, которая только использует кэш
lint:
  cache:
    policy: pull
```

### 4. Кэшируйте только необходимые файлы

**Рекомендуется:**
```yaml
cache:
  paths:
    - node_modules/
    - .npm/
    - vendor/
```

**Не рекомендуется:**
```yaml
cache:
  paths:
    - .git/          # Не нужно, Git уже есть
    - dist/          # Это артефакт, а не кэш
    - "*.log"        # Логи не нужны
```

## Troubleshooting

### Кэш не загружается

**Проблема:** Задача не находит кэш.

**Возможные причины:**
1. Неправильный ключ кэша
2. Кэш был удалён
3. Разные Runner'ы (кэш локален для Runner)

**Решение:**
```yaml
# Проверьте ключ
cache:
  key: "$CI_COMMIT_REF_SLUG"  # Должен совпадать с задачей, создавшей кэш
```

### Кэш устарел

**Проблема:** Зависимости не обновляются.

**Решение:**
```yaml
# Используйте ключ по файлам зависимостей
cache:
  key:
    files:
      - package-lock.json
```

### Кэш слишком большой

**Проблема:** Долгая загрузка/выгрузка кэша.

**Решение:**
```yaml
# Исключите лишние файлы
cache:
  paths:
    - node_modules/
  exclude:
    - node_modules/**/*.md
    - node_modules/**/test/
```

## Очистка кэша

### Через GitLab UI

1. Перейдите в **Build → Cache**
2. Нажмите **Remove caches**

### Через API

```bash
curl --request DELETE --header "PRIVATE-TOKEN: <your_token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/cache"
```

### Автоматическая очистка по расписанию

```yaml
# Задача для очистки кэша раз в неделю
cleanup_cache:
  stage: .pre
  script:
    - echo "Cleaning cache"
  cache:
    key: "old-cache"
    paths: []
    policy: push
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

## Связанные документы

- **[Кэширование и артефакты — Обзор](./caching_overview.md)** — общая информация
- **[Ключи кэша](./cache_keys.md)** — типы ключей, политики
- **[Артефакты](./artifacts.md)** — конфигурация артефактов
- **[Сценарии кэширования](./cache_scenarios.md)** — практические примеры
