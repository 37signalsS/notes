# Практические сценарии использования downstream-пайплайнов

## Определения

**Практические сценарии** — это архитектурные паттерны реализации родительско-дочерних (parent-child) и межпроектных (multi-project) связей. Эти сценарии позволяют декомпозировать монолитные конфигурации, управлять зависимостями микросервисов и обеспечивать изоляцию критических процессов (например, деплоя) в выделенных проектах.

## Основные концепции

Эффективность downstream-пайплайнов в современных версиях GitLab (18.6+) базируется на трех столпах:
1. **High Fidelity Mirroring:** Использование `strategy: mirror` для полной синхронизации жизненного цикла. Upstream-задание не просто ждет завершения, а в точности повторяет статус дочернего процесса (включая `manual` и `skipped`).
2. **Типизация контрактов:** Переход от неявных переменных к блоку `spec:inputs`, что гарантирует валидность входных данных до момента запуска.
3. **Безопасность Zero Trust:** Настройка межпроектного взаимодействия через **Inbound Allowlist** для защиты артефактов и API.

**Важно:** Использование `strategy: mirror` является обязательным требованием для агрегации **Security Reports** (SAST, DAST, SBOM) из дочерних пайплайнов в интерфейс Merge Request родительского проекта (GitLab 18.9+).

## Практические сценарии

### Селективный запуск в монорепозитории

Паттерн для запуска независимых дочерних пайплайнов только для изменённых модулей. Это сокращает время выполнения CI и экономит ресурсы Runner-слотов.

```yaml
# .gitlab-ci.yml (Родительский)
trigger-auth-service:
  stage: test
  trigger:
    include: services/auth/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - services/auth/**/*
  allow_failure: false # Ошибка в сервисе блокирует весь пайплайн

trigger-billing-service:
  stage: test
  trigger:
    include: services/billing/.gitlab-ci.yml
    strategy: mirror
  rules:
    - changes:
        - services/billing/**/*
```

### Кросс-проектное тестирование зависимостей

Сценарий, при котором публикация новой версии общей библиотеки инициирует проверку в проекте-потребителе.

```yaml
# Проект: shared-library (Upstream)
publish-and-trigger:
  stage: deploy
  script:
    - npm publish
  trigger:
    project: 'web-apps/main-application'
    branch: main
    strategy: mirror

# Проект: main-application (Consumer)
# Для работы этого сценария shared-library должен быть добавлен 
# в Inbound Allowlist в настройках CI/CD main-application.
integration-tests:
  stage: test
  needs:
    - project: 'shared-library'
      job: 'publish-and-trigger'
      ref: main
      artifacts: true # Получение метаданных новой версии
  script:
    - npm install
    - npm test
```

### Безопасная передача параметров через Inputs

Использование `inputs` (GitLab 17.7+) вместо переменных обеспечивает типизацию и валидацию данных на входе в дочерний пайплайн. Это предотвращает запуск дочернего процесса с некорректными данными.

```yaml
# .gitlab-ci.yml (Родительский)
deploy-to-env:
  stage: deploy
  trigger:
    include:
      - local: ci/deploy-template.yml
    inputs:
      target_environment: "production"
      force_deploy: true
    strategy: mirror
```

### Изоляция чувствительных данных (Secure Forwarding)

Сценарий для предотвращения утечки глобальных переменных родительского проекта в дочерние пайплайны. Это критично при работе с внешними библиотеками или мультипроектными цепочками.

```yaml
# .gitlab-ci.yml (Upstream)
variables:
  SENSITIVE_GLOBAL_VAR: "secret-data"

trigger-secure-child:
  stage: test
  trigger:
    include: child-config.yml
    forward:
      yaml_variables: false     # Не передавать SENSITIVE_GLOBAL_VAR
      pipeline_variables: true  # Передать только переменные запуска (Web UI/API)
    strategy: mirror
```

### Динамическое развёртывание Review Apps

Сценарий с генерацией конфигурации "на лету" для создания эфемерных окружений на основе метаданных ветки или внешних API.

```yaml
generate-deploy-config:
  stage: build
  script:
    - python3 scripts/generate_env_ci.py > deploy-config.yml
  artifacts:
    paths: [deploy-config.yml]

trigger-review-app:
  stage: deploy
  trigger:
    include:
      - artifact: deploy-config.yml
        job: generate-deploy-config
    strategy: mirror
```

## Дополнительная информация

### Сравнительный анализ паттернов

| Паттерн | Приоритетная связь | Изоляция контекста | Агрегация отчетов |
| :--- | :--- | :--- | :--- |
| **Монорепозиторий** | Parent-Child | Частичная (общий проект) | **Полная** (через mirror) |
| **Библиотеки/Микросервисы** | Multi-project | **Высокая** (разные проекты) | Требует Inbound Allowlist |
| **Infrastructure as Code** | Multi-project | **Максимальная** | Только статус завершения |
| **CI/CD Components** | Parent-Child | Полная (через inputs) | Автоматическая (17.x+) |

### Рекомендации по отладке и эксплуатации

1.  **Pipeline Graph:** Используйте визуализацию в интерфейсе GitLab для отслеживания связей. В 18.x+ синхронные связи (`mirror`) подсвечиваются особым образом.
2.  **Проверка токенов:** Если артефакты не скачиваются, проверьте область действия `CI_JOB_TOKEN` и настройки **Job Token Permissions**.
3.  **Логирование Dynamic Child:** Всегда выводите сгенерированный YAML-файл в `stdout` перед его использованием как артефакта, чтобы упростить поиск синтаксических ошибок.
4.  **Interruptible:** Для экономии ресурсов помечайте downstream-задачи как `interruptible: true`, если деплой в них не является атомарным.

---

**Связанные документы:**
- **[Определения](./definitions.md)** — терминология и типы связей.
- **[Лучшие практики](./best_practices.md)** — безопасность и оптимизация триггеров.
- **[Стратегии выполнения](./strategies.md)** — детально про `mirror` и `depend`.
- **[Динамическая генерация](./dynamic_generation.md)** — подробный гайд по программному созданию пайплайнов.

---

**Надёжность:** 10 (SSoT + Документация GitLab 18.x–19.x)
**Свежесть:** GitLab 19.2 (2026)
**Триггеры обновления:** Изменения в логике `forward`, новые типы агрегации отчетов, изменения лимитов вложенности.
