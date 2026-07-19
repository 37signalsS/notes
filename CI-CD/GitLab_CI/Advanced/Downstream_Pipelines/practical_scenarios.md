# Практические сценарии использования downstream-пайплайнов

## Определения

**Практические сценарии** — это типовые архитектурные паттерны реализации родительско-дочерних (parent-child) и межпроектных (multi-project) пайплайнов для решения задач автоматизации CI/CD в сложных инфраструктурах.

## Основные концепции

Выбор конкретного сценария зависит от структуры репозиториев и требований к изоляции:
- **Parent-Child:** Идеально для монорепозиториев, декомпозиции сложных `.gitlab-ci.yml` и динамической генерации задач.
- **Multi-project:** Используется для управления зависимостями между разными проектами (например, обновление библиотеки вызывает тесты в приложении) или разделения зон ответственности (код приложения отдельно от инфраструктуры деплоя).

Ключевым преимуществом всех сценариев является использование **`strategy: mirror`** (GitLab 18.6+), которая обеспечивает полную синхронизацию статусов и видимость отчётов в Merge Request.

## Практические сценарии

### Селективный запуск в монорепозитории

Паттерн для запуска независимых дочерних пайплайнов только для изменённых модулей. Это сокращает время выполнения CI и экономит ресурсы раннеров.

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
```

В проекте-потребителе (`main-application`) можно использовать `needs:project` для получения артефактов (например, логов сборки или метаданных версии) из родительского проекта.

### Безопасная передача параметров через Inputs

Использование `inputs` (GitLab 17.7+) вместо переменных обеспечивает типизацию и валидацию данных на входе в дочерний пайплайн.

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

### Сравнительная таблица сценариев

| Сценарий | Тип связи | Ключевая выгода | Рекомендуемая стратегия |
| :--- | :--- | :--- | :--- |
| **Монорепозиторий** | Parent-Child | Экономия времени и ресурсов | `mirror` + `rules:changes` |
| **Микросервисы** | Multi-project | Контроль цепочки поставок | `mirror` |
| **Сложные деплои** | Dynamic Child | Максимальная гибкость | `mirror` |
| **Shared Templates** | Parent-Child | Стандартизация через `inputs` | `mirror` |

### Рекомендации по отладке

1. **Pipeline Graph:** Используйте визуализацию в интерфейсе GitLab для отслеживания связей между upstream и downstream.
2. **Логирование:** В динамических пайплайнах всегда выводите содержимое сгенерированного YAML в лог джобы `generate`.
3. **Interruptible:** Помечайте downstream-задачи как `interruptible: true`, чтобы они автоматически отменялись при поступлении нового коммита в ту же ветку.

---

**Связанные документы:**
- [Определения](./definitions.md) — терминология и типы связей.
- [Лучшие практики](./best_practices.md) — безопасность и оптимизация.
- [Стратегии выполнения](./strategies.md) — детально про `mirror` и `depend`.
- [Динамическая генерация](./dynamic_generation.md) — подробный гайд по программному созданию пайплайнов.
