# GitHub Actions: Управление секретами

Управление секретами в GitHub Actions позволяет безопасно хранить и использовать конфиденциальную информацию (пароли, API-ключи, токены доступа) в процессах автоматизации. Секреты шифруются на стороне GitHub и передаются исполнителю (runner) только в момент необходимости.

## Определения

- **GitHub Actions Secrets (Секреты)** — зашифрованные переменные среды, создаваемые на уровне организации, репозитория или конкретного окружения.
- **Маскирование (Masking)** — автоматический процесс замены значений секретов на символы `***` в логах выполнения воркфлоу для предотвращения их случайного раскрытия.
- **GITHUB_TOKEN** — временный токен безопасности, автоматически создаваемый GitHub для каждой задачи (job) для аутентификации в API (Application Programming Interface) GitHub.

## Основные концепции

### Уровни хранения секретов

Секреты организованы иерархически, что позволяет гибко управлять доступом к ним:

1. **Repository secrets (Секреты репозитория)**: Доступны для всех рабочих процессов в рамках конкретного репозитория. Настраиваются в `Settings → Secrets and variables → Actions`.
2. **Environment secrets (Секреты окружения)**: Привязаны к конкретному [окружению](./Environment_Limitations.md) (например, `production` или `staging`). Это позволяет использовать одинаковые имена переменных с разными значениями для разных сред.
3. **Organization secrets (Секреты организации)**: Позволяют совместно использовать общие конфиденциальные данные (например, ключи к корпоративному облаку) в нескольких репозиториях организации.

### Безопасность и ограничения

- **Одностороннее шифрование**: После создания секрета его значение невозможно просмотреть в интерфейсе GitHub; можно только обновить или удалить его.
- **Автоматическое маскирование**: Если значение секрета попадает в стандартный вывод (stdout) или поток ошибок (stderr), GitHub Actions автоматически заменяет его на маскировочные символы.
- **Доступ в Fork-репозиториях**: По умолчанию секреты недоступны для рабочих процессов, запускаемых из форков (forks) сторонними пользователями, для защиты от кражи учетных данных через вредоносные Pull Request.

## Практические сценарии

### Использование секрета для SSH-доступа

Для выполнения команд на удаленном сервере через SSH (Secure Shell) необходимо передать закрытый ключ и адрес хоста в соответствующие шаги.

```yaml
name: Remote Deployment

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Execute remote commands
        env:
          PRIVATE_KEY: ${{ secrets.SERVER_SSH_KEY }}
          HOST_ADDR: ${{ secrets.SERVER_HOST }}
        run: |
          echo "$PRIVATE_KEY" > deploy_key
          chmod 600 deploy_key
          ssh -i deploy_key -o StrictHostKeyChecking=no user@$HOST_ADDR "cd /app && ./update.sh"
```

### Разделение секретов по окружениям

Использование разных API-токенов для тестовой и промышленной сред через параметр `environment`.

```yaml
jobs:
  deploy-to-staging:
    runs-on: ubuntu-latest
    environment: staging # Используются секреты окружения staging
    steps:
      - name: Run staging deploy
        env:
          TOKEN: ${{ secrets.API_TOKEN }}
        run: ./deploy.sh --env staging

  deploy-to-production:
    runs-on: ubuntu-latest
    needs: deploy-to-staging
    environment: production # Используются секреты окружения production
    steps:
      - name: Run production deploy
        env:
          TOKEN: ${{ secrets.API_TOKEN }}
        run: ./deploy.sh --env production
```

### Принцип минимальных прав (Least Privilege)

Согласно общим [принципам управления секретами в CI/CD](../CI-CD/DevSecOps/secrets_management.md), каждая задача должна иметь доступ только к необходимому минимуму данных. В GitHub Actions это реализуется через изоляцию задач и привязку к окружениям.

**Пример безопасного разделения:**

```yaml
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    # Задача тестов не имеет доступа к продовым секретам
    steps:
      - uses: actions/checkout@v4
      - run: npm test

  deploy-prod:
    runs-on: ubuntu-latest
    needs: unit-tests
    environment: production # Изолированный доступ к секретам + возможное одобрение
    steps:
      - uses: actions/checkout@v4
      - name: Production deployment
        env:
          CLOUDFLARE_TOKEN: ${{ secrets.CF_API_TOKEN }}
        run: ./publish.sh
```

В данном примере, если в процессе тестирования произойдет сбой или компрометация окружения, секрет `CF_API_TOKEN` останется в безопасности, так как он доступен только задаче `deploy-prod`.

## Дополнительная информация

- **[Синтаксис Workflow](./Workflow_Syntax.md)** — использование контекста `secrets`.
- **[Переиспользуемые воркфлоу](./Reusable_Workflows.md)** — передача секретов между процессами.
- **[Принципы управления секретами в CI/CD](../CI-CD/DevSecOps/secrets_management.md)** — общетеоретическая база.
- **[Официальная документация GitHub](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)** — детальное руководство от разработчиков.
