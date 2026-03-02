# Этап 4: Абстрагирование деталей реализации (Безопасность)

## Практические сценарии

### Ситуация

Платформенная команда решает, что `docker:dind` небезопасен (требует `privileged`) и нужно перейти на более безопасный сборщик — **Kaniko**.

### Решение

Так как все проекты используют централизованный шаблон, достаточно изменить только него.

### Обновление шаблона на Kaniko

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
.docker-build-template:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  variables:
    DOCKERFILE: Dockerfile
    CONTEXT: $CI_PROJECT_DIR
  script:
    - /kaniko/executor
      --context $[[ CONTEXT ]]
      --dockerfile $[[ DOCKERFILE ]]
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
      --cache=true
      --cache-repo=$CI_REGISTRY_IMAGE/cache
```

### Результат для проектов

**Проекты не требуют изменений!** Их `.gitlab-ci.yml` остаются прежними:

```yaml
# .gitlab-ci.yml проекта (без изменений)
include:
  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker-build.yml'

build-my-app:
  extends: .docker-build-template
  variables:
    DOCKERFILE: "app/Dockerfile"  # Можно переопределить
```

### Преимущества

| Преимущество | Описание |
| :--- | :--- |
| **Прозрачное обновление** | Проекты не требуют изменений |
| **Безопасность** | Kaniko не требует привилегированного режима |
| **Кэширование** | Встроенное кэширование слоёв через Kaniko |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Отсутствие типизации** | Нет явного интерфейса для входных параметров |
| **Слабая валидация** | Невозможно валидировать переменные до выполнения |
| **Документирование** | Требуется ручная документация параметров |

## Дополнительная информация

### Связанные документы

- **[Этап 3: Гибкость с extends](./evolution/stage3_extends.md)** — предыдущий этап
- **[Этап 5: CI/CD Components](./evolution/stage5_components.md)** — решение проблем типизации
- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение всех подходов
