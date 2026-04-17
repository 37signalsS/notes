# Управление секретами в GitHub Actions

## Определения

**GitHub Actions Secrets** — это зашифрованные переменные, которые можно создавать в организации, репозитории или окружении репозитория. Они позволяют хранить конфиденциальные данные, такие как токены, ключи API и учетные данные, и безопасно использовать их в воркфлоу GitHub Actions.

## Основные концепции

Секреты хранятся на стороне GitHub и передаются в runner только в момент выполнения задачи. GitHub Actions автоматически маскирует значения секретов в логах выполнения, предотвращая их случайную утечку. Если в лог попадает строка, точно совпадающая со значением секрета, GitHub заменяет ее на `***`.

### Уровни хранения секретов

1. **Repository secrets:** Доступны для всех воркфлоу в репозитории. Настраиваются в `Settings → Secrets and variables → Actions`.
2. **Environment secrets:** Секреты, привязанные к конкретному [окружению](../Environments.md) (например, `production`, `staging`). Позволяют использовать разные учетные данные для разных окружений.
3. **Organization secrets:** Доступны для выбранных репозиториев внутри организации.

## Практические сценарии

### Использование секрета в воркфлоу

Секреты передаются в шаги воркфлоу через контекст `secrets`.

**Пример воркфлоу для деплоя с использованием SSH-ключа:**

```yaml
name: Deploy to VPS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to VPS
        env:
          SSH_KEY: ${{ secrets.VPS_SSH_KEY }}
          VPS_HOST: ${{ secrets.VPS_HOST }}
        run: |
          echo "$SSH_KEY" > /tmp/deploy_key
          chmod 600 /tmp/deploy_key
          ssh -i /tmp/deploy_key -o StrictHostKeyChecking=no user@$VPS_HOST "cd /app && git pull && systemctl restart app"

```

**Ключевые моменты:**

- `$``{{ secrets.VPS_SSH_KEY }}`: Так происходит доступ к секрету. GitHub никогда не выведет его значение в лог.
- Секрет используется для создания временного файла ключа, который удаляется после завершения работы runner'а.

### Использование секретов для разных окружений

Для разделения секретов между `staging` и `production` используются окружения (`environments`).

```yaml
jobs:
  deploy-staging:
    runs-on: ubuntu-latest
    environment: staging # У этого окружения свой набор секретов
    steps:
      - name: Deploy to staging server
        env:
          API_TOKEN: ${{ secrets.STAGING_API_TOKEN }}
        run: ./deploy.sh
  
  deploy-prod:
    runs-on: ubuntu-latest
    environment: production # А у этого — свой
    needs: deploy-staging
    steps:
      - name: Deploy to production server
        env:
          API_TOKEN: ${{ secrets.PRODUCTION_API_TOKEN }}
        run: ./deploy.sh
```

## Дополнительная информация

- [Синтаксис воркфлоу](./Workflow_Syntax.md)
- [Переиспользуемые воркфлоу](./Reusable_Workflows.md)
- [Официальная документация по секретам](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)
