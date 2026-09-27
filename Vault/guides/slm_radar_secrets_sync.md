# SLM, Vault Radar и Secrets Sync

## Определения

**SLM (Security Lifecycle Management / Secret Lifecycle Management)** — современный подход Vault (версии 1.16+, 2.0+), выходящий за рамки простого хранения секретов. SLM включает обнаружение утечек, централизованное управление, автоматическую ротацию и синхронизацию секретов с внешними системами.

**Vault Radar** — инструмент Vault для автоматического сканирования инфраструктуры (Git, вики, мессенджеры, объектные хранилища, логи) с целью обнаружения активных (валидных) секретов. Приоритизирует находки по критичности и может импортировать секреты в Vault для дальнейшей ротации.

**Secrets Sync** — механизм Vault Enterprise для автоматической репликации секретов из Vault во внешние корпоративные системы управления секретами и оркестраторы (GitHub, Vercel, AWS Secrets Manager и др.). Изменение секрета в Vault распространяется на целевые платформы в реальном времени.

**Hub-and-spoke модель** — архитектура Secrets Sync, где Vault выступает центральным хабом, а целевые системы — спицами. Vault является system of record для всех секретов.

**Continuous Discovery** — непрерывный процесс поиска секретов в инфраструктуре. Vault Radar сканирует все новые репозитории, логи и системы по расписанию.

**Secret Inventory** — инвентаризация всех секретов в организации, включая местоположение, возраст, доступ и критичность.

## Основные концепции

### Жизненный цикл секрета в SLM

```
Обнаружение → Классификация → Хранение → Ротация → Синхронизация → Аудит
     ↑                                                                 |
     └─────────────────────────────────────────────────────────────────┘
```

1. **Обнаружение (Discovery):** Vault Radar сканирует инфраструктуру и находит секреты.
2. **Классификация:** Определение критичности и типа секрета.
3. **Хранение (Storage):** Импорт секрета в Vault с назначением политик доступа.
4. **Ротация:** Автоматическая или полуавтоматическая замена секрета.
5. **Синхронизация (Sync):** Распространение секрета во внешние системы через Secrets Sync.
6. **Аудит:** Фиксация всех операций в audit логах.

### Vault Radar

| Функция | Описание |
| :--- | :--- |
| **Сканирование Git** | Поиск секретов в репозиториях, включая историю коммитов |
| **Сканирование вики** | Поиск в Confluence, Notion и других системах документации |
| **Сканирование мессенджеров** | Поиск в Slack, Teams, Telegram |
| **Сканирование хранилищ** | Поиск в S3, GCS, Azure Blob |
| **Сканирование логов** | Поиск в ELK, Loki, CloudWatch |
| **Приоритизация** | Классификация находок по критичности (P0-P3) |
| **Импорт в Vault** | Автоматическое перемещение найденных секретов в Vault |

### Secrets Sync

| Функция | Описание |
| :--- | :--- |
| **Hub-and-spoke** | Vault как центральный хаб, целевые системы как спицы |
| **Real-time sync** | Изменение секрета в Vault мгновенно распространяется |
| **Directional sync** | Направленная синхронизация (Vault → внешняя система) |
| **Transformation** | Трансформация формата секрета под требования целевой системы |

## Практические сценарии

### Сценарий 1: Настройка Vault Radar

#### Конфигурация

```hcl
# vault-radar.hcl
server {
  enabled = true
  address = "0.0.0.0:8200"
}

# Сканирование Git репозиториев
scanner "git" {
  enabled = true
  repositories = [
    "https://github.com/example/repo1",
    "https://github.com/example/repo2"
  ]
  branch = "main"
  depth = 100
}

# Сканирование Slack
scanner "slack" {
  enabled = true
  channels = ["#general", "#ops"]
  token = "xoxb-..."
}

# Приоритизация
priority {
  high = ["api_key", "password", "secret"]
  medium = ["token", "certificate"]
  low = ["config", "settings"]
}
```

#### Запуск сканирования

```bash
# Ручной запуск сканирования
vault radar scan

# Плановое сканирование (cron)
vault radar scan --schedule="0 2 * * *"

# Просмотр результатов
vault radar findings list
# → ID          Severity   Type    Location
# → 1a2b3c4d    high       password  git:example/repo1:config.py:42
# → 5e6f7g8h    medium     api_key   slack:#general
```

#### Импорт найденных секретов в Vault

```bash
# Импорт конкретного секрета
vault radar findings import 1a2b3c4d \
    --path=secret/data/imported/git-repo1-password \
    --policy=imported-policy

# Массовый импорт всех high-severity находок
vault radar findings import --severity=high
```

### Сценарий 2: Настройка Secrets Sync

#### Конфигурация синхронизации с GitHub

```bash
# Создание подключения к GitHub
vault write sys/sync/connections/github \
    auth_method="github" \
    access_token="ghp_..." \
    organization="example-org"

# Создание правила синхронизации
vault write sys/sync/rules/github-secrets \
    connection="github" \
    source="secret/data/myapp/*" \
    destination="github/org/example-org/variables" \
    transformation="github-actions"
```

#### Синхронизация с AWS Secrets Manager

```bash
# Создание подключения к AWS
vault write sys/sync/connections/aws \
    auth_method="aws" \
    access_key_id="AKIA..." \
    secret_access_key="..." \
    region="us-east-1"

# Создание правила синхронизации
vault write sys/sync/rules/aws-secrets \
    connection="aws" \
    source="secret/data/myapp/*" \
    destination="aws:secretsmanager:us-east-1:123456789012:secret:myapp/" \
    transformation="aws-secrets-manager"
```

#### Мониторинг синхронизации

```bash
# Проверка статуса синхронизации
vault read sys/sync/rules/github-secrets/status
# → last_sync    2026-09-24T12:00:00Z
# → status       success
# → errors       0

# Просмотр ошибок
vault read sys/sync/rules/github-secrets/errors
```

### Сценарий 3: Интеграция с CI/CD

Секреты из Vault автоматически синхронизируются в GitHub Actions Variables:

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Get secrets from Vault
        env:
          VAULT_ADDR: https://vault.example.com:8200
          VAULT_TOKEN: ${{ secrets.VAULT_TOKEN }}
        run: |
          DB_PASSWORD=$(vault kv get -field=password secret/myapp/db)
          echo "DB_PASSWORD=$DB_PASSWORD" >> $GITHUB_ENV
      
      - name: Deploy
        run: ./deploy.sh
```

### Сценарий 4: Compliance и отчетность

#### Отчет по секретам

```bash
# Инвентаризация всех секретов
vault kv list -namespace=prod secret/
vault kv list -namespace=staging secret/

# Поиск устаревших секретов
vault radar findings list --severity=high --status=active
```

#### Автоматическая ротация импортированных секретов

```bash
# Создание политики ротации для импортированных секретов
vault write sys/rotate/policy/imported-secrets \
    path="secret/data/imported/*" \
    interval="24h" \
    notify="slack:#security"

# Запуск ротации
vault write sys/rotate/run imported-secrets
```

## Лучшие практики

1. **Continuous Discovery:** Настройте Vault Radar на регулярное сканирование всей инфраструктуры.
2. **Приоритизация:** Фокусируйтесь на high-severity находках (пароли, API-ключи).
3. **Автоматический импорт:** Настройте автоматический импорт найденных секретов в Vault.
4. **Hub-and-spoke:** Используйте Vault как system of record для всех секретов.
5. **Real-time sync:** Настройте Secrets Sync для распространения секретов в целевые системы.
6. **Audit:** Включите audit device для отслеживания всех операций SLM.
7. **Обучение:** Обучите команды использовать Vault вместо хранения секретов в Git/вики.

## Ограничения и известные проблемы

- **Enterprise функции:** Vault Radar и Secrets Sync доступны только в Vault Enterprise.
- **Сканирование:** Vault Radar сканирует только подключенные репозитории и системы.
- **Синхронизация:** Secrets Sync поддерживает ограниченное количество целевых систем.
- **Производительность:** Сканирование больших репозиториев может занимать много времени.
- **Точность:** Vault Radar может давать ложноположительные результаты. Требуется ручная проверка.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и SLM.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему Secret Sprawl опасен.
*   **[Zero Trust](../zero_trust.md)** — роль SLM в архитектуре нулевого доверия.
*   [Официальная документация Vault Radar](https://developer.hashicorp.com/vault/docs/enterprise/radar)
*   [Официальная документация Secrets Sync](https://developer.hashicorp.com/vault/docs/enterprise/secrets-sync)
