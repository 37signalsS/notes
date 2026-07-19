# Основы GitLab CI/CD

## Определения

Иерархия компонентов в GitLab CI/CD строится по принципу «от общего к частному». Подробный глоссарий — в [pipeline_glossary.md](../../Core_Concepts/pipeline_glossary.md).

* **[Pipeline](https://docs.gitlab.com/ci/pipelines/)**: Высокоуровневая структура, определяющая полный цикл CI/CD. Состоит из стадий (Stage) и запускается по событиям (коммит, Merge Request, расписание).
* **[Stage](https://docs.gitlab.com/ci/yaml/stages/)**: Группирует задания (Job) и определяет порядок их выполнения. Задания внутри одной стадии выполняются параллельно, сами стадии — последовательно.
* **[Job](https://docs.gitlab.com/ci/jobs/)**: Минимальная единица работы. Выполняет набор команд (скриптов) для сборки, тестирования или развертывания.
* **[Runner](https://docs.gitlab.com/runner/)**: Приложение, выполняющее задания. Устанавливается на сервер или в контейнер и опрашивает GitLab на предмет новых задач. Настройка — в [gitlab_ci_runners_executors.md](../Advanced/gitlab_ci_runners_executors.md).
* **[Component](https://docs.gitlab.com/ee/ci/components/)**: Переиспользуемая единица конфигурации CI/CD, хранящаяся в **CI/CD Catalog**. Современный стандарт для DRY-подхода.

## Базовые концепции

### Архитектура GitLab CI/CD

Для работы системы необходимы три ключевых компонента (подробнее — в [gitlab_platform_architecture.md](./gitlab_platform_architecture.md)):

1. **GitLab Server** — управляет репозиториями, отслеживает изменения и инициирует пайплайны.
2. **GitLab Runner** — агент, выполняющий задания в различных окружениях:
   * **Docker Executor** — изоляция в контейнерах (стандарт индустрии).
   * **Kubernetes Executor** — запуск заданий в подах K8s.
   * **Shell Executor** — выполнение прямо на хосте (не рекомендуется из-за отсутствия изоляции).
   * **SSH Executor** — подключение к удаленным серверам для деплоя.
3. **`.gitlab-ci.yml`** — конфигурационный файл в корне репозитория.

С версии **19.0** GitLab также включает встроенный **GitLab Secrets Manager** для безопасного хранения переменных и секретов без использования внешних систем (Vault).

```
[Разработчик] --push--> [GitLab Server] --триггер--> [Pipeline]
                                                |
                                                v
                                          [GitLab Runner]
                                          |-- Docker Executor
                                          |-- Kubernetes Executor
                                          |-- Shell Executor
                                          |-- SSH Executor
```

Подробная информация о типах Runner и Executor — в [gitlab_ci_runners_executors.md](../Advanced/gitlab_ci_runners_executors.md). Установка self-hosted GitLab с Runner — в [self_hosted_installation.md](../Tutorials/self_hosted_installation.md).

### Типовые стадии пайплайна

Стандартный жизненный цикл микросервиса включает:

1. **Lint/Check**: Проверка стиля кода и статический анализ безопасности (SAST).
2. **Unit Tests**: Запуск модульных тестов.
3. **Build**: Сборка приложения или создание Docker-образов.
4. **Functional Tests**: Тестирование взаимодействия в изолированной среде.
5. **Push**: Загрузка образов в Registry.
6. **Deploy**: Развертывание в тестовые (Staging) или продуктивные (Production) среды.

### Разница между артефактами и кэшем

| Характеристика | Артефакты (`artifacts`) | Кэш (`cache`) |
| :--- | :--- | :--- |
| **Назначение** | Передача результатов между стадиями одного пайплайна | Ускорение сборки между разными пайплайнами (`node_modules`) |
| **Жизненный цикл** | Удаляются автоматически по `expire_in` | Сохраняются до очистки или истечения TTL |
| **Доступность** | Можно скачать через UI GitLab | Недоступны для ручного скачивания |
| **Хранение** | Централизованно на сервере GitLab | Локально на Runner или в S3 (Distributed Cache) |

### Конфигурация через `.gitlab-ci.yml`

Файл является единой точкой правды для CI/CD.

> **Важно (GitLab 18.x/19.x):** Глобальные ключевые слова `before_script`, `image`, `cache` на верхнем уровне **удалены** или полностью заменены блоком `default`. Используйте [`default`](#структурные-ключевые-слова).

### Ключевые слова для управления пайплайном

#### Структурные настройки

* **`stages`**: Список и порядок стадий.
* **`default`**: Набор общих настроек для всех заданий (образ, скрипты подготовки, кэш).
* **`variables`**: [Переменные окружения](./gitlab_ci_variables_secrets.md). С версии 19.x рекомендуется использовать интеграцию с **GitLab Secrets Manager**.
* **`workflow:rules`**: Глобальные правила запуска всего пайплайна.

#### Параметры заданий

* **`script`**: Обязательный блок с shell-командами.
* **`needs`**: Создает направленный ациклический граф (DAG), позволяя запускать задания сразу после готовности зависимостей, не дожидаясь конца стадии.
* **`rules`**: Условия включения задания в пайплайн (замена устаревшим `only`/`except`).
* **`environment`**: Описание целевой среды для деплоя.

### Взаимосвязь `needs` и `dependencies`

* **`needs`**: Управляет **порядком выполнения** (DAG).
* **`dependencies`**: Управляет **загрузкой артефактов**. Если используется `needs`, то по умолчанию загружаются только артефакты от указанных в нем заданий.

### Механизмы переиспользования

Для соблюдения принципа DRY (Don't Repeat Yourself) используются:

1. **`extends`**: Наследование настроек от скрытых заданий (начинаются с точки, например `.base_job`).
2. **`!reference`**: Копирование конкретных блоков кода из других частей YAML.
3. **`include`**: Подключение внешних файлов или **компонентов из CI/CD Catalog**.

Подробности — в [создании переиспользуемых пайплайнов](../Reusable_Pipelines/overview.md).

## Практические сценарии

### Пример базового пайплайна

```yaml
stages:
  - build
  - test
  - deploy

variables:
  APP_ENV: production

# Настройки по умолчанию (GitLab 18.x+)
default:
  image: python:3.12
  before_script:
    - pip install -r requirements.txt
    # → Installing dependencies...

build_job:
  stage: build
  script:
    - python -m build
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test_job:
  stage: test
  needs: ["build_job"]
  script:
    - pytest -q

deploy_job:
  stage: deploy
  environment:
    name: production
  needs: ["test_job"]
  dependencies: []
  script:
    - ./scripts/deploy.sh $CI_COMMIT_SHORT_SHA
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

## Дополнительная информация

* **CI Lint**: Инструмент проверки синтаксиса в UI GitLab (`CI/CD -> Editor`). Показывает «смерженный» файл со всеми `include`.
* **Pipeline Execution Policies**: Современный способ принудительного выполнения проверок безопасности на уровне группы (заменяет устаревшие Compliance Pipelines).
* **GitLab Duo**: AI-помощник для написания и отладки конфигурации CI/CD через CLI и Web IDE.
* **Стратегия ветвления**: О применении GitLab Flow для эффективной разработки — в [gitlab_flow.md](../Tutorials/gitlab_flow.md).

> **Критичные изменения последних версий:**
>
> * **19.0**: Минимальная версия PostgreSQL — 17. Поддержка Redis 6 прекращена (переход на Redis 7.2 или **Valkey**).
> * **19.2**: **GitLab Secrets Manager** перешел в GA. Планировщик **Scheduled Pipeline Execution Policies** доступен для всех.
> * **18.9**: `include:cache` — кэширование удаленных файлов конфигурации.
