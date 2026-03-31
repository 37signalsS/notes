# GitHub Actions: Переиспользуемые воркфлоу (Reusable Workflows)

Переиспользуемые воркфлоу — это механизм в GitHub Actions, который позволяет одному воркфлоу вызывать другой. Это ключевой инструмент для соблюдения принципа DRY (Don't Repeat Yourself), уменьшения дублирования кода и централизации логики CI/CD.

## Определения

- **Reusable Workflow (Переиспользуемый воркфлоу)**: Воркфлоу, который может быть вызван другим воркфлоу. Он определяется с помощью триггера `on: { workflow_call }`.
- **Caller Workflow (Вызывающий воркфлоу)**: Воркфлоу, который использует задачу специального типа (`jobs.<job_id>.uses`) для вызова переиспользуемого воркфлоу.

## Основные концепции

### Создание переиспользуемого воркфлоу

Чтобы сделать воркфлоу переиспользуемым, нужно в секции `on` указать `workflow_call`.

- **Входные параметры (`inputs`)**: Позволяют передавать данные из вызывающего воркфлоу в переиспользуемый. Аналогичны `with` для `actions`.
- **Секреты (`secrets`)**: По умолчанию переиспользуемый воркфлоу не имеет доступа к секретам. Вызывающий воркфлоу должен явно передать их с помощью `secrets: inherit` или передать каждый секрет по отдельности.

**Пример (`.github/workflows/reusable-deploy.yml`):**

```yaml
name: Reusable Deploy

on:
  workflow_call:
    inputs:
      environment:
        description: 'Среда для развертывания (staging/production)'
        required: true
        type: string
    secrets:
      deploy_token:
        description: 'Токен для деплоя'
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - name: Deploy to ${{ inputs.environment }}
        run: |
          echo "Starting deployment..."
          # Используем переданный секрет
          ./deploy-script.sh --token ${{ secrets.deploy_token }}
```

### Вызов переиспользуемого воркфлоу

Вызов осуществляется внутри задачи (`job`) с помощью ключа `uses`. Вся задача посвящена вызову одного воркфлоу.

- **`uses`**: Указывает путь к файлу переиспользуемого воркфлоу в формате `{owner}/{repo}/.github/workflows/{filename}@{ref}`. Если воркфлоу находится в том же репозитории, можно использовать локальный путь `./.github/workflows/{filename}`.
- **`with`**: Передает значения для `inputs`.
- **`secrets`**: Передает секреты. `secrets: inherit` — самый простой способ передать все секреты вызывающего воркфлоу.

**Пример (`.github/workflows/main-ci.yml`):**

```yaml
name: Main CI

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Building project..."
      # ... шаги сборки

  # Задача, вызывающая переиспользуемый воркфлоу
  deploy-to-staging:
    needs: build
    uses: ./.github/workflows/reusable-deploy.yml
    with:
      environment: 'staging'
    secrets:
      deploy_token: ${{ secrets.STAGING_DEPLOY_TOKEN }}

  # Еще один вызов для другой среды
  deploy-to-prod:
    needs: deploy-to-staging
    uses: ./.github/workflows/reusable-deploy.yml
    with:
      environment: 'production'
    secrets: inherit # Передаем все секреты
```

## Практические сценарии

### Сценарий 1: Централизованный деплой

Компания имеет десятки микросервисов. Вместо того чтобы копировать логику деплоя в каждый репозиторий, создается один центральный репозиторий с переиспользуемым воркфлоу `org-deploy`. Каждый микросервис вызывает его, передавая имя приложения и версию.

### Сценарий 2: Общая матрица тестирования

Логика запуска тестов на разных версиях Python и ОС вынесена в `reusable-testing.yml`. Разные проекты (например, бэкенд и CLI-утилита) могут вызывать этот воркфлоу, чтобы гарантировать одинаковый уровень тестового покрытия.

## Дополнительная информация

Переиспользование как техника оптимизации в **[Оптимизация воркфлоу](./Optimization.md)**, синтаксис `uses`, `with`, `secrets` в **[Синтаксис Workflow](./Workflow_Syntax.md)**. Официальная документация: [Reusing workflows](https://docs.github.com/en/actions/using-workflows/reusing-workflows).
