# GitHub Actions: Переиспользуемые рабочие процессы

Переиспользуемые рабочие процессы (reusable workflows) — это механизм в GitHub Actions, позволяющий одному рабочему процессу вызывать другой. Это ключевой инструмент для соблюдения принципа DRY (Don't Repeat Yourself — не повторяйся), минимизации дублирования кода и централизации логики процессов CI/CD (Continuous Integration / Continuous Deployment — непрерывная интеграция и непрерывное развертывание).

## Определения

- **Reusable Workflow (Переиспользуемый рабочий процесс)**: Рабочий процесс, предназначенный для вызова другими процессами. Определяется с помощью триггера `on: workflow_call`.
- **Caller Workflow (Вызывающий рабочий процесс)**: Рабочий процесс, который инициирует выполнение переиспользуемого процесса через задачу специального типа (`jobs.<job_id>.uses`).

## Основные концепции

### Создание переиспользуемого рабочего процесса

Для того чтобы сделать файл рабочего процесса доступным для вызова, необходимо в секции `on` указать событие `workflow_call`.

- **Входные параметры (`inputs`)**: Позволяют передавать данные из вызывающего процесса. Описываются аналогично параметрам `inputs` для триггера `workflow_dispatch`.
- **Секреты (`secrets`)**: По умолчанию переиспользуемый процесс не имеет доступа к секретам репозитория. Вызывающий процесс должен явно передать их по отдельности или использовать механизм наследования.

**Пример конфигурации (`.github/workflows/reusable-deploy.yml`):**

```yaml
name: Reusable Deployment Logic

on:
  workflow_call:
    inputs:
      target_env:
        description: 'Целевое окружение (staging/production)'
        required: true
        type: string
    secrets:
      api_token:
        description: 'Токен для авторизации деплоя'
        required: true

jobs:
  execute-deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.target_env }}
    steps:
      - name: Deploying to ${{ inputs.target_env }}
        run: |
          echo "Starting deployment process..."
          ./deploy.sh --token ${{ secrets.api_token }}
```

### Механизм вызова

Вызов переиспользуемого процесса осуществляется внутри задачи с помощью ключа `uses`. Вся задача в этом случае делегируется внешнему файлу.

- **`uses`**: Указывает путь к файлу. Формат для внешних репозиториев: `{owner}/{repo}/.github/workflows/{filename}@{ref}`. Для локальных файлов в том же репозитории: `./.github/workflows/{filename}`.
- **`with`**: Используется для передачи значений во входные параметры (`inputs`).
- **`secrets`**: Используется для передачи секретов. Значение `secrets: inherit` автоматически передает все доступные секреты вызывающего процесса в переиспользуемый.

**Пример вызова (`.github/workflows/main-pipeline.yml`):**

```yaml
name: Application Pipeline

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Building artifact..."

  deploy-staging:
    needs: build
    uses: ./.github/workflows/reusable-deploy.yml
    with:
      target_env: 'staging'
    secrets:
      api_token: ${{ secrets.STAGING_TOKEN }}

  deploy-production:
    needs: deploy-staging
    uses: ./.github/workflows/reusable-deploy.yml
    with:
      target_env: 'production'
    secrets: inherit # Наследование всех секретов
```

## Практические сценарии

### Сценарий 1: Централизация стратегий развертывания

В организациях с большим количеством микросервисов создание единого переиспользуемого процесса для развертывания позволяет унифицировать логику деплоя во всех репозиториях. Это упрощает внедрение изменений в инфраструктуру: достаточно обновить один центральный файл.

### Сценарий 2: Унифицированное тестирование и линтинг

Вынос конфигурации матричного тестирования (проверка на разных версиях ОС и сред исполнения) в переиспользуемый файл гарантирует одинаковый уровень качества и соблюдение стандартов во всех проектах компании.

## Дополнительная информация

- **[Оптимизация воркфлоу](./Optimization.md)** — переиспользование как метод ускорения и упрощения CI/CD.
- **[Синтаксис Workflow](./Workflow_Syntax.md)** — подробное описание директив `uses`, `with` и `secrets`.
- **[Матричные сборки](./Matrix_Builds.md)** — комбинирование матриц с переиспользуемыми процессами.
- **[Официальная документация GitHub](https://docs.github.com/en/actions/using-workflows/reusing-workflows)** — детальное руководство по использованию.
