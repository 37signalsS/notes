# Лучшие практики и устранение неполадок

## Лучшие практики (2025-2026)

### 1. Организация раннеров

| Конфигурация | Рекомендация |
| :--- | :--- |
| Один раннер | Гарантирует доступность кэша между задачами |
| Несколько раннеров | Включите распределённый кэш (S3) |
| Автомасштабирование | Обязательно с распределённым кэшем |

### 2. Стратегии ключей

```yaml
# ✅ Рекомендуется: ключ по файлам зависимостей
cache:
  key:
    files:
      - package-lock.json
  paths:
    - node_modules/

# ✅ Для веток: разные кэши
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - vendor/

# ✅ Fallback keys для ускорения feature-веток
cache:
  key:
    files:
      - Gemfile.lock
  fallback_keys:
    - cache-$CI_DEFAULT_BRANCH
    - cache-main
  paths:
    - vendor/ruby

# ⚠️ Избегайте: одинаковые ключи для разных путей
cache:
  key: same-key  # Конфликт!
  paths:
    - public/    # Задача A
    - vendor/    # Задача B — перезапишет кэш A
```

### 3. Управление размером кэша

Исключайте ненужные файлы:

```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - node_modules/
  untracked: false  # Не включать неотслеживаемые файлы
```

### 4. Очистка кэша

**Способ 1:** Измените `cache:key` в `.gitlab-ci.yml`

**Способ 2:** Через UI GitLab:
1. Build → Pipelines
2. Clear runner caches

⚠️ При ручной очистке индекс кэша инкрементируется (`cache-<index>`). Старые файлы не удаляются автоматически.

### 5. Политики кэширования

```yaml
# Глобальная политика по умолчанию
default:
  cache: &global_cache
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - node_modules/
    policy: pull-push

# Задачи сборки обновляют кэш
install_deps:
  stage: build
  script:
    - npm ci
  cache:
    <<: *global_cache
    policy: pull-push

# Тесты только читают кэш (быстрее, нет записи)
test:
  stage: test
  script:
    - npm test
  cache:
    <<: *global_cache
    policy: pull
```

### 6. Новые возможности GitLab 17+

- **`files_commits`** — ключ кэша на основе хешей коммитов файлов зависимостей
- **Улучшенная валидация** — предупреждения о некорректных конфигурациях кэша
- **Оптимизация S3** — ускоренная загрузка/выгрузка для распределённых раннеров

## Хранение кэша

| Тип раннера | Путь по умолчанию |
| :--- | :--- |
| Shell | `/home/gitlab-runner/cache/<user>/<project>/<key>/cache.zip` |
| Docker | `/var/lib/docker/volumes/<id>/_data/<user>/<project>/<key>/cache.zip` |
| Docker Machine (autoscale) | Как Docker + загрузка в S3 |

⚠️ **Важно:** Все кэши задачи архивируются в один `cache.zip`. Разные задачи с одинаковым ключом перезаписывают кэш друг друга.

## Устранение неполадок

| Проблема | Решение |
| :--- | :--- |
| Несколько раннеров без общего кэша | Включите распределённый кэш (S3) |
| Автомасштабирование без S3 | Настройте распределённый кэш |
| Нехватка места на диске/S3 | Очистите место вручную |
| Одинаковые ключи для разных путей | Используйте разные ключи |
| Concurrent-раннеры теряют кэш | Настройте общую точку монтирования или S3 |

**Пример конфликта кэшей:**

```yaml
# ❌ Неправильно
job_a:
  cache:
    key: same-key
    paths:
      - public/

job_b:
  cache:
    key: same-key
    paths:
      - vendor/  # Перезапишет кэш задачи A

# ✅ Правильно
job_a:
  cache:
    key: keyA
    paths:
      - public/

job_b:
  cache:
    key: keyB
    paths:
      - vendor/
```

## Отключение кэша для задачи

```yaml
job:
  cache: []  # Полное отключение
```

## Связанные документы

- [Основные концепции](./cache_concepts.md)
- [Сценарии кэширования](./cache_scenarios.md)
