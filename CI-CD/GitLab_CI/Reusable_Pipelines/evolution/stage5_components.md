# Этап 5: Зрелость — CI/CD Catalog Components

## Практические сценарии

### Решение

Переход на CI/CD Components с явным интерфейсом (`spec:inputs`), версионированием через Semver и публикацией в каталоге.

### Создание компонента

**Репозиторий:** `group/ci-components/docker-build`

**Структура:**
```
docker-build/
├── .gitlab-ci.yml          # spec:inputs + метаданные
└── templates/
    └── build.yml           # Основная логика
```

**Файл:** `.gitlab-ci.yml` (метаданные компонента)

```yaml
# .gitlab-ci.yml компонента
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage name"
    
    dockerfile:
      default: Dockerfile
      type: string
      description: "Path to Dockerfile"
    
    context:
      default: $CI_PROJECT_DIR
      type: string
      description: "Build context path"
    
    enable_cache:
      default: true
      type: boolean
      description: "Enable Kaniko caching"
    
    cache_repo:
      default: $CI_REGISTRY_IMAGE/cache
      type: string
      description: "Cache repository"

---
# Основная логика компонента (templates/build.yml)
docker-build-job:
  stage: $[[ inputs.stage ]]
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context $[[ inputs.context ]]
      --dockerfile $[[ inputs.dockerfile ]]
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
      --cache=$[[ inputs.enable_cache ]]
      --cache-repo=$[[ inputs.cache_repo ]]
```

### Публикация в каталог

**Создание релиза:**
```bash
# Создание тега с SemVer
git tag -a v1.0.0 -m "Initial release of docker-build component"
git push origin v1.0.0

# Или через GitLab UI: Releases → New release
```

**CI для автоматического релиза:**
```yaml
# .gitlab-ci.yml компонента (добавление release job)
release:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/release-cli:latest
  rules:
    - if: $CI_COMMIT_TAG
  release:
    tag_name: $CI_COMMIT_TAG
    name: "Release $CI_COMMIT_TAG"
    description: "docker-build component $CI_COMMIT_TAG"
```

### Использование компонента в проекте

```yaml
# .gitlab-ci.yml проекта
include:
  - component: '$CI_SERVER_FQDN/group/ci-components/docker-build@1.0.0'
    inputs:
      stage: build
      dockerfile: app/Dockerfile
      context: $CI_PROJECT_DIR
      enable_cache: true
      cache_repo: $CI_REGISTRY_IMAGE/cache
```

### Преимущества Components

| Преимущество | Описание |
| :--- | :--- |
| **Типизация** | Явные типы параметров (string, boolean, number) |
| **Валидация** | Автоматическая валидация inputs через CI Lint |
| **Документация** | Автоматическая генерация из `description` |
| **Версионирование** | Semver с поддержкой частичных версий (`@1.0`, `@1`) |
| **Каталог** | Видимость в UI GitLab, поиск компонентов |
| **Изоляция** | Полная самодостаточность компонента |

## Дополнительная информация

### Связанные документы

- **[Этап 4: Абстрагирование (Kaniko)](./evolution/stage4_kaniko.md)** — предыдущий этап
- **[CI/CD Catalog](./ci_cd_catalog_components.md)** — создание компонентов
- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение всех подходов

### Внешние ресурсы

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [GitLab CI Best Practices](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5)
