# Кэширование и артефакты в GitLab CI/CD

## Определения

**Кэширование в GitLab CI** — механизм сохранения файлов и директорий между запусками задач или пайплайнов для ускорения сборки за счёт повторного использования зависимостей (`node_modules`, `.m2`, `vendor`).

**Артефакты в GitLab CI** — файлы или директории, сохраняемые после выполнения задачи и передаваемые между стадиями пайплайна для доставки результатов сборки.

**Распределённый кэш** — механизм хранения кэша в централизованном хранилище (S3, GCS), доступном всем Runner'ам проекта.

### Сравнение кэша и артефактов

| Признак | Кэш (`cache`) | Артефакты (`artifacts`) |
| :--- | :--- | :--- |
| **Назначение** | Ускорение задач (зависимости) | Передача результатов между стадиями |
| **Гарантия** | Не гарантируется. Runner может удалить в любой момент | Гарантируются. Хранятся на сервере GitLab |
| **Область** | По умолчанию — для всего проекта. Можно настроить для задачи или ветки | Только для конкретной задачи. Передаются в последующие стадии |
| **Хранение** | Локально на Runner + S3 (распределённый кэш) | На сервере GitLab |
| **Срок жизни** | Бессрочно (до ручной очистки) | 30 дней по умолчанию (`expire_in`) |
| **Скорость** | Быстрее (локально на Runner) | Медленнее (загрузка/скачивание) |

**Важно:** Для критически важных файлов используйте артефакты. Кэш может быть удалён в любой момент.

## Основные концепции

### Архитектура кэширования

Кэширование в GitLab CI работает на двух уровнях:

1. **Локальное хранилище** — кэш сохраняется в директории Runner'а. Доступен только задачам на этом Runner'е.
2. **Распределённое хранилище** — кэш загружается в объектное хранилище (S3, GCS). Доступен всем Runner'ам проекта.

### Жизненный цикл кэша

1. **Создание** — задача выполняет `cache:policy: pull-push` или `push`, кэш архивируется и сохраняется.
2. **Поиск** — при запуске задачи GitLab ищет кэш по ключу (основной → fallback).
3. **Загрузка** — кэш распаковывается в рабочую директорию перед выполнением `script`.
4. **Обновление** — после успешного выполнения кэш перезаписывается (при `pull-push`).
5. **Очистка** — вручную через UI/API или автоматически при переполнении.

### Хранение кэша

| Тип Runner | Путь по умолчанию |
| :--- | :--- |
| Shell | `/home/gitlab-runner/cache/<user>/<project>/<key>/cache.zip` |
| Docker | `/var/lib/docker/volumes/<id>/_data/<user>/<project>/<key>/cache.zip` |
| Docker Machine (autoscale) | Как Docker + загрузка в S3 |

**Важно:** Все кэши задачи архивируются в один `cache.zip`. Разные задачи с одинаковым ключом перезаписывают кэш друг друга.

### Когда использовать кэш

- Зависимости (`npm install`, `pip install`, `mvn dependency:resolve`)
- Временные файлы компиляции (`.o`, `.class`, `__pycache__`)
- Файлы, которые могут быть воссозданы

### Когда использовать артефакты

- Передача файлов между стадиями (сборка → тесты → деплой)
- Результаты сборки (бинарники, пакеты, отчёты)
- Файлы для публикации (Docker-образ, deb/rpm пакет, релизный архив)

### Ограничения

- Максимум 4 кэша на задачу
- Размер кэша ограничен настройками сервера (по умолчанию 100 МБ)
- Кэш не гарантируется — может быть удалён в любой момент

## Практические сценарии

### Сценарий 1: Комбинация кэша и артефактов

Кэш ускоряет установку зависимостей, артефакты передают результаты сборки:

```yaml
build:
  stage: build
  script:
    - npm ci
    - npm run build
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
    policy: pull-push
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test:
  stage: test
  script:
    - npm test
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
    policy: pull
  dependencies:
    - build
  artifacts:
    reports:
      junit: test-results.xml
```

### Сценарий 2: Кэширование NPM-зависимостей

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
    - npm test
  cache:
    <<: *global_cache
    policy: pull
```

### Сценарий 3: Раздельные кэши для разных компонентов

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

### Сценарий 4: Отчёты о тестах и покрытии

```yaml
test:
  stage: test
  script:
    - pytest --junitxml=test-results.xml --cov=app --cov-report=xml
  artifacts:
    paths:
      - test-results/
    reports:
      junit: test-results.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 week
```

## Дополнительная информация

### Настройка распределённого кэша

Для включения распределённого кэша требуется конфигурация Runner'а:

```toml
# /etc/gitlab-runner/config.toml
[runners.cache]
  Type = "s3"
  Shared = true
  [runners.cache.s3]
    ServerAddress = "s3.amazonaws.com"
    BucketName = "gitlab-runner-cache"
    Insecure = false
```

### Очистка кэша

**Через UI:**

1. Перейдите в **Build → Cache** в интерфейсе GitLab
2. Нажмите **Remove caches**

**Через API:**

```bash
curl --request DELETE --header "PRIVATE-TOKEN: <your_token>" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/cache"
```

### Рекомендации

1. Используйте ключи по файлам зависимостей для автоматического обновления кэша
2. Разделяйте кэш для разных типов зависимостей (npm, pip, maven)
3. Не кэшируйте файлы, которые могут содержать секреты или чувствительные данные
4. Для артефактов всегда устанавливайте `expire_in`, кроме релизных сборок
5. Используйте распределённый кэш для больших команд и нескольких Runner'ов

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Кэш не загружается | Неправильный ключ | Проверьте совпадение ключа между задачами |
| Кэш устарел | Статический ключ | Используйте ключи по файлам зависимостей |
| Долгая загрузка | Большой размер кэша | Исключите лишние файлы через `exclude` |
| Артефакты не передаются | Нет `dependencies` | Проверьте зависимости между задачами |

### Связанные документы

- [Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md) — базовые концепции.
- [Продвинутые рабочие процессы](./gitlab_ci_advanced_workflow.md) — оптимизация пайплайнов с `needs`.
