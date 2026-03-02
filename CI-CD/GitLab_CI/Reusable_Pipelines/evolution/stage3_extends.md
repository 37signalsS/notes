# Этап 3: Гибкость с помощью `extends`

## Практические сценарии

### Решение

Превратить задачу в шаблоне в "скрытую" (начинающуюся с точки) и наследовать её в проекте через `extends`, добавляя специфичные настройки.

### Обновлённый шаблон

**Репозиторий:** `group/ci-templates`

**Файл:** `docker-build.yml`

```yaml
# ci-templates/docker-build.yml
.docker-build-template:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build
        --build-arg CI_JOB_TOKEN=${CI_JOB_TOKEN}
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
        .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

### Использование в проекте с кастомизацией

```yaml
# .gitlab-ci.yml проекта
include:
  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker-build.yml'

stages:
  - build

build-my-app:
  extends: .docker-build-template
  variables:
    DOCKER_BUILDKIT: "1"  # Добавляем специфичную переменную
    IMAGE_NAME: "my-app"
  before_script:
    - echo "Custom step before building"  # Добавляем свой шаг
    - npm install  # Специфичная подготовка
```

### Результат

| Преимущество | Описание |
| :--- | :--- |
| **Централизация** | Общая логика в одном месте |
| **Гибкость** | Каждый проект может добавлять свои переменные, `before_script`, `after_script` |
| **DRY** | Нет дублирования основной логики |

### Новые проблемы

| Проблема | Описание |
| :--- | :--- |
| **Безопасность** | `docker:dind` требует привилегированного режима (`privileged`) |
| **Сложность обновления** | При изменении шаблона все проекты получают изменения немедленно |

## Дополнительная информация

### Связанные документы

- **[Этап 2: Централизация с include](./evolution/stage2_include.md)** — предыдущий этап
- **[Этап 4: Абстрагирование (Kaniko)](./evolution/stage4_kaniko.md)** — решение проблемы безопасности
- **[Механизм `extends`](./extends_keyword.md)** — наследование конфигураций
