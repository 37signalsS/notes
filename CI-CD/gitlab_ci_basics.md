# Основы GitLab CI/CD

Это руководство представляет собой введение в настройку и использование GitLab CI/CD, фокусируясь на основных концепциях и структуре файла `.gitlab-ci.yml`.

См. также:
*   [CI/CD: Основные концепции](./pipeline.md)
*   [GitLab CI как конструктор Workflow](./gitlab_ci_workflow_constructor.md)

## 1. Файл `.gitlab-ci.yml`

Конфигурация пайплайна в GitLab CI/CD определяется с помощью файла `.gitlab-ci.yml`, который должен находиться в корне вашего репозитория.

### 1.1. Именование и формат

*   **Имя файла:** `.gitlab-ci.yml` (обязательно).
*   **Формат:** YAML.
*   **Отступы:** Используйте пробелы вместо табуляции для отступов, как того требует синтаксис YAML.

GitLab автоматически распознает этот файл и активирует CI/CD для вашего проекта.

### 1.2. Основные концепции

Файл `.gitlab-ci.yml` состоит из следующих ключевых элементов:

*   **Этапы (Stages):**
    *   `stages:` Определяют последовательность выполнения групп задач (jobs).
    *   Задачи внутри одной стадии могут выполняться параллельно, но следующая стадия начнется только после успешного завершения всех задач предыдущей.
    *   Пример: `lint`, `test`, `build`, `deploy`.

*   **Задачи (Jobs):**
    *   `job_name:` — это отдельные рабочие процессы.
    *   Каждая задача должна иметь уникальное имя. Избегайте использования зарезервированных слов GitLab (например, `stages`, `script`) в качестве названий задач.
    *   Задачи привязываются к определенным этапам.

*   **Скрипты (Script):**
    *   `script:` — это директива, которая содержит одну или несколько shell-команд, выполняемых Runner'ом для данной задачи.
    *   Команды выполняются последовательно. Если какая-либо команда завершается неудачей, вся задача (job) помечается как неуспешная.

**Простой пример структуры `.gitlab-ci.yml`:**

```yaml
stages:
  - build
  - test

build_job:
  stage: build
  script:
    - echo "Performing build..."
    - build_command

test_job_lint:
  stage: test
  script:
    - echo "Running linter..."
    - linter_command

test_job_unit:
  stage: test
  script:
    - echo "Running unit tests..."
    - unit_test_command
```

## 2. Инструменты для проверки и переменные

### 2.1. Встроенный линтер

GitLab предоставляет встроенный линтер для проверки синтаксиса вашего `.gitlab-ci.yml` файла. Это помогает выявлять тривиальные ошибки на ранних этапах. Его можно найти в веб-интерфейсе GitLab в разделе **Pipelines -> CI Lint**.

### 2.2. Встроенные переменные

GitLab CI/CD включает множество встроенных переменных, которые предоставляют информацию о текущем пайплайне, репозитории, коммите и других контекстных данных. Эти переменные могут быть использованы для придания динамичности и уникальности сборкам, а также для других целей. Подробнее о переменных будет рассказано в отдельной теме.

---

Для более подробной и исчерпывающей информации о возможностях конфигурационного файла GitLab CI/CD всегда рекомендуется обращаться к официальной [документации GitLab](https://docs.gitlab.com/ee/ci/yaml/).

---

### Полезные ссылки

*   **Extends**: [документация](https://docs.gitlab.com/ee/ci/yaml/#extends)
*   **YAML якоря**: [оптимизация YAML](https://docs.gitlab.com/ee/ci/yaml/yaml_optimization.html#yaml-anchors-for-scripts)
*   **Multi-project (downstream) pipelines**: [документация](https://docs.gitlab.com/ee/ci/pipelines/multi_project_pipelines.html)
*   **Rules**: [управление выполнением jobs](https://docs.gitlab.com/ee/ci/jobs/job_control.html)
*   **Only/Except**: [управление выполнением jobs (старый синтаксис)](https://docs.gitlab.com/ee/ci/jobs/job_control.html#specify-when-jobs-run-with-only-and-except)
*   **Changes**: [примеры с only/changes и except/changes](https://docs.gitlab.com/ee/ci/jobs/job_control.html#onlychanges-exceptchanges-examples)
*   **Переменные**: [создание кастомных переменных](https://docs.gitlab.com/ee/ci/variables/#create-a-custom-cicd-variable-in-the-gitlab-ciyml-file)
*   **Пайплайны и стадии**: [документация](https://docs.gitlab.com/ee/ci/pipelines/)
*   **Jobs**: [документация](https://docs.gitlab.com/ee/ci/jobs/)
*   **Хороший пример для монорепозитория (eng)**: [how-to.dev](https://how-to.dev/howto-set-up-monorepo-build-in-gitlab-ci)