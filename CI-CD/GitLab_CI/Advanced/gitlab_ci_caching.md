# Кэширование в GitLab CI/CD

## Определения

**Кэширование в GitLab CI** — механизм сохранения файлов и директорий между запусками задач или пайплайнов. Основная цель — ускорение сборки за счёт повторного использования зависимостей (`node_modules`, `vendor/`, `.m2/`).

**Кэш vs. Артефакты**

| Признак | Кэш (`cache`) | Артефакты (`artifacts`) |
| :--- | :--- | :--- |
| **Назначение** | Ускорение задач (зависимости) | Передача результатов между стадиями |
| **Гарантия** | **Не гарантируется.** Runner может удалить в любой момент | **Гарантируются.** Хранятся на сервере GitLab |
| **Область** | По умолчанию — для всего проекта. Можно настроить для задачи или ветки | Только для конкретной задачи. Передаются в последующие стадии |
| **Хранение** | Локально на Runner + S3 (распределённый кэш) | На сервере GitLab |
| **Срок жизни** | Бессрочно (до ручной очистки) | 30 дней по умолчанию (`expire_in`) |
| **Скорость** | Быстрее (локально на Runner) | Медленнее (загрузка/скачивание) |

**Важно:** Для критически важных файлов используйте [артефакты](../Concepts/gitlab_ci_basics.md#artifacts).

## Основные концепции

### Ключ кэша (`cache:key`)

Ключ определяет уникальность кэша. При изменении ключа GitLab создаёт новый кэш.

#### Типы ключей

**1. Статический ключ:**
```yaml
cache:
  key: "global-npm-cache"
  paths:
    - node_modules/
```

**2. Динамический ключ (переменные):**
```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG"  # Разный кэш для каждой ветки
  paths:
    - vendor/
```

**3. Ключ по файлам зависимостей (рекомендуется):**
```yaml
cache:
  key:
    files:
      - package-lock.json
      - Gemfile.lock
  paths:
    - node_modules/
    - vendor/ruby
```

**4. Ключ по коммитам файлов:**
```yaml
cache:
  key:
    files_commits:
      - package.json
      - requirements.txt
  paths:
    - dependencies/
```

#### Суффиксы ключей

Для защищённых веток GitLab автоматически добавляет суффиксы:

| Сценарий | Суффикс |
| :--- | :--- |
| Защищённая ветка + роль Maintainer/Owner | `-protected` |
| Незащищённая ветка или роль Developer | `-non_protected` |

**Пример:** `main-protected` vs `feature-non_protected`

### Политики кэширования (`cache:policy`)

| Политика | Описание | Когда использовать |
| :--- | :--- | :--- |
| `pull-push` (по умолчанию) | Загружает и сохраняет кэш | Задачи, которые обновляют зависимости |
| `pull` | Только загружает, не сохраняет | Задачи, которые только потребляют кэш (тесты) |
| `push` | Только сохраняет, не загружает | Задачи, которые только создают кэш |

**Пример переопределения политики:**

```yaml
default:
  cache: &global_cache
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - node_modules/
    policy: pull-push

install_deps:
  stage: build
  script:
    - npm ci
  cache:
    <<: *global_cache
    policy: pull-push  # Обновляет кэш

test:
  stage: test
  script:
    - npm test
  cache:
    <<: *global_cache
    policy: pull  # Только использует кэш
```

### Резервные ключи (Fallback Keys)

Fallback keys позволяют использовать резервный кэш, если основной не найден:

```yaml
test:
  cache:
    - key: cache-$CI_COMMIT_REF_SLUG
      fallback_keys:
        - cache-$CI_DEFAULT_BRANCH
        - cache-main
      paths:
        - vendor/ruby
```

**Порядок поиска:**
1. `cache-$CI_COMMIT_REF_SLUG`
2. `cache-$CI_DEFAULT_BRANCH`
3. `cache-main`
4. Без кэша → создание нового

**Глобальный fallback:**
```yaml
variables:
  CACHE_FALLBACK_KEY: fallback-key

job:
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - binaries/
```

## Практические сценарии

### Сценарий 1: Кэширование NPM-зависимостей (рекомендуемый подход)

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

### Сценарий 2: Раздельные кэши для разных компонентов

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

### Сценарий 3: Общий кэш для всех веток

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

### Сценарий 4: Кэширование в монорепозитории

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

## Дополнительная информация

### Лучшие практики (2025-2026)

#### 1. Организация раннеров

| Конфигурация | Рекомендация |
| :--- | :--- |
| Один раннер | Гарантирует доступность кэша между задачами |
| Несколько раннеров | Включите распределённый кэш (S3) |
| Автомасштабирование | Обязательно с распределённым кэшем |

#### 2. Стратегии ключей

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

#### 3. Управление размером кэша

Исключайте ненужные файлы:

```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - node_modules/
  untracked: false  # Не включать неотслеживаемые файлы
```

#### 4. Очистка кэша

**Способ 1:** Измените `cache:key` в `.gitlab-ci.yml`

**Способ 2:** Через UI GitLab:
1. Build → Pipelines
2. Clear runner caches

⚠️ При ручной очистке индекс кэша инкрементируется (`cache-<index>`). Старые файлы не удаляются автоматически.

#### 5. Политики кэширования

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

#### 6. Новые возможности GitLab 17+

- **`files_commits`** — ключ кэша на основе хешей коммитов файлов зависимостей
- **Улучшенная валидация** — предупреждения о некорректных конфигурациях кэша
- **Оптимизация S3** — ускоренная загрузка/выгрузка для распределённых раннеров

### Хранение кэша

| Тип раннера | Путь по умолчанию |
| :--- | :--- |
| Shell | `/home/gitlab-runner/cache/<user>/<project>/<key>/cache.zip` |
| Docker | `/var/lib/docker/volumes/<id>/_data/<user>/<project>/<key>/cache.zip` |
| Docker Machine (autoscale) | Как Docker + загрузка в S3 |

⚠️ **Важно:** Все кэши задачи архивируются в один `cache.zip`. Разные задачи с одинаковым ключом перезаписывают кэш друг друга.

### Устранение неполадок

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

### Отключение кэша для задачи

```yaml
job:
  cache: []  # Полное отключение
```

## Связанные документы

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — артефакты и базовые концепции
- **[Продвинутые рабочие процессы](./gitlab_ci_advanced_workflow.md)** — оптимизация пайплайнов с `needs`
- **[Исполнители (Runners)](./gitlab_ci_runners_executors.md)** — настройка распределённого кэша
