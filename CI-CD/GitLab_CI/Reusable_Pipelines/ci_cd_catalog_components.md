# GitLab CI: Каталог компонентов (CI/CD Catalog)

## Определения

**CI/CD Catalog (Components)** — современный подход GitLab к переиспользованию конфигураций, позволяющий создавать версионируемые, типизированные и публикуемые в общем каталоге компоненты. Это изолированные блоки CI/CD логики с явным интерфейсом взаимодействия.

**Компонент** — автономный YAML-файл или директория в репозитории, содержащая конфигурацию GitLab CI и метаданные входных параметров.

**`spec:inputs`** — декларативное описание "публичного интерфейса" компонента, определяющее типы данных, значения по умолчанию и правила валидации входных параметров.

**Интерполяция** — механизм подстановки переданных значений параметров в конфигурацию компонента через синтаксис `$[[ inputs.<name> ]]`.

## Основные концепции

### Сравнение компонентов и механизма `include`

Компоненты являются эволюцией традиционного подхода `include:project`, предлагая строгую структуру и расширенный контроль.

| Критерий | `include:project` | CI/CD Catalog (Components) |
| :--- | :--- | :--- |
| **Версионирование** | Теги, ветки, SHA | **SemVer** (обязательно для публикации) |
| **Типизация** | Нет (только строки) | **Да** (`spec:inputs` с проверкой типов) |
| **Валидация** | Только синтаксис YAML | **Полная** (проверка обязательных входов) |
| **Документация** | Ручная (README.md) | **Автоматическая** (из `spec:inputs`) |
| **Изоляция** | Средняя | **Высокая** (самодостаточные блоки) |

### Архитектура компонента

Проект-компонент может иметь разную структуру в зависимости от сложности.

**Вариант 1: Одиночный файл** (простые компоненты)

```text
component-repo/
└── .gitlab-ci.yml          # Интерфейс (spec:inputs) + логика задания
```

**Вариант 2: Директория с шаблонами** (для нескольких компонентов в одном репо)

```text
component-repo/
├── .gitlab-ci.yml          # Общие метаданные
└── templates/
    └── build.yml           # Основная логика компонента
```

### Синтаксис `spec:inputs`

Директива `spec:inputs` позволяет задавать типы данных (`string`, `number`, `boolean`) и проверять значения через регулярные выражения.

```yaml
spec:
  inputs:
    stage:
      default: test
      type: string
    parallel_limit:
      type: number
      default: 1
    enable_feature:
      type: boolean
      default: false
    environment:
      type: string
      regex: '^(dev|prod)$'
---
# Конец секции спецификации, далее следует логика YAML
```

**Особенности:**

- Если параметров нет, блок `spec:` должен присутствовать в виде `spec: ---`.
- Параметры без `default` являются обязательными при подключении.

### Механизм интерполяции

Интерполяция `$[[ inputs.<name> ]]` происходит на этапе компиляции пайплайна, что гарантирует подстановку значений до начала выполнения заданий.

```yaml
test_job:
  stage: $[[ inputs.stage ]]
  script:
    - echo "Running in $[[ inputs.environment ]]"
```

## Практические сценарии

### Сценарий 1: Подключение компонента из официального каталога

Использование стандартных инструментов (например, Secret Detection) с фиксированной версией.

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/security/secret-detection@1.0.0'
    inputs:
      stage: security
      scan_path: './src'
```

### Сценарий 2: Создание собственного Docker-компонента

Универсальный шаблон для сборки образов в организации.

**Репозиторий компонента (`group/ci-components/docker-build`):**

```yaml
spec:
  inputs:
    stage:
      default: build
    dockerfile:
      default: Dockerfile
---
build_image:
  stage: $[[ inputs.stage ]]
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -f $[[ inputs.dockerfile ]] -t $CI_REGISTRY_IMAGE .
```

### Сценарий 3: Компонент для полного жизненного цикла (Multi-job)

Компоненты могут содержать связанные цепочки заданий.

```yaml
# templates/nodejs-pipeline.yml
spec:
  inputs:
    node_version:
      default: "20"
---
install:
  stage: .pre
  image: node:$[[ inputs.node_version ]]
  script:
    - npm ci

test:
  stage: test
  image: node:$[[ inputs.node_version ]]
  script:
    - npm test
  needs: [install]
```

### Сценарий 4: Управление стратегией обновлений

Выбор между стабильностью и автоматическим получением исправлений.

```yaml
include:
  # 1. Фиксированная версия (рекомендуется для production)
  - component: '$CI_SERVER_FQDN/group/component@1.0.0'

  # 2. Мажорная версия (автообновление минорных версий)
  - component: '$CI_SERVER_FQDN/group/component@1'

  # 3. Последняя версия (только для тестирования)
  - component: '$CI_SERVER_FQDN/group/component@~latest'
```

### Сценарий 5: Валидация входных данных через regex

```yaml
spec:
  inputs:
    replicas:
      type: number
      regex: '^[1-5]$' # Ограничение от 1 до 5 реплик
---
deploy:
  script:
    - echo "Deploying $[[ inputs.replicas ]] units"
```

## Дополнительная информация

- **[Ограничения каталога](./ci_cd_catalog_limits.md)** — лимиты вложенности, лимиты на проект и запрещённые ключи.
- **[Справочная информация](./ci_cd_catalog_reference.md)** — API, CLI, отладка ошибок и история версий GitLab.
- **[Продвинутые сценарии](./ci_cd_catalog_advanced_scenarios.md)** — сложные случаи миграции и динамических пайплайнов.

### Смотрите также

- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [Обзор переиспользуемых пайплайнов](./overview.md)
- [Механизм include](./include_keyword.md)
