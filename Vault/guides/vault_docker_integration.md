# Интеграция Vault с Docker

## Определения

**Интеграция Vault с Docker** — совокупность архитектурных паттернов и инструментов для обеспечения безопасности секретов (паролей, ключей, сертификатов) в контейнеризированных средах. Целью интеграции является реализация модели жизненного цикла безопасности (SLM), при которой секреты никогда не сохраняются в образах, слоях Docker или переменных окружения.

**BuildKit Secrets** — механизм Docker, позволяющий безопасно монтировать секреты в процессе сборки образа без их сохранения в итоговых слоях файловой системы.

**Vault Agent (Sidecar)** — вспомогательный контейнер, обеспечивающий автоматическую аутентификацию, получение и ротацию секретов для основного приложения.

## Основные концепции

### Жизненный цикл секрета в Docker

Процесс интеграции разделяется на две стадии:

1.  **Стадия сборки (Build-time):** Секреты нужны для доступа к приватным репозиториям, пакетам или API провайдеров.
2.  **Стадия выполнения (Runtime):** Приложение получает динамические или статические учетные данные для работы с базами данных, очередями и внешними сервисами.

### Сравнение методов интеграции

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **BuildKit Secrets** | Монтирование секретов через `--mount=type=secret`. | Сборка образов (CI/CD). |
| **Vault Agent** | Рендеринг шаблонов в общую `tmpfs` директорию. | Продуктивные среды, Docker Compose. |
| **Direct API** | Использование SDK (hvac, vault-ruby) внутри кода. | Сложная динамическая логика. |
| **Entrypoint (Bash)** | Получение секретов через `curl` перед запуском приложения. | Legacy-системы, быстрые прототипы. |

### Идентификация и аутентификация

Для контейнеров в Docker (в отличие от Kubernetes) предпочтительными методами аутентификации являются:
*   **OIDC / JWT:** Для CI/CD пайплайнов (GitHub Actions, GitLab CI), где Vault доверяет идентификатору раннера.
*   **AppRole:** Стандартный метод для статических серверов или Docker Compose, использующий `RoleID` и `SecretID`.
*   **Cloud Auth (AWS/GCP/Azure):** Если Docker запущен на облачной виртуальной машине, Vault проверяет личность через метаданные инстанса.

## Практические сценарии

### Сборка образов с использованием BuildKit Secrets

Использование BuildKit предотвращает утечку Vault-токенов в историю слоев образа.

**Пример Dockerfile:**
```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Монтирование секрета только на время выполнения команды RUN
RUN --mount=type=secret,id=vault_token \
    VAULT_TOKEN=$(cat /run/secrets/vault_token) && \
    pip install --index-url https://my-private-repo.com/simple/ my-internal-package
```

**Команда сборки:**
```bash
export VAULT_TOKEN=$(vault login -method=oidc -token-only)
docker build --secret id=vault_token,env=VAULT_TOKEN -t my-secure-app .
```

### Использование Vault Agent в Docker Compose (Sidecar паттерн)

В Docker Compose рекомендуется запускать Vault Agent как отдельный сервис, который готовит секреты в общей `tmpfs` области памяти.

**Пример `docker-compose.yml`:**
```yaml
services:
  # Основное приложение
  webapp:
    image: my-app:latest
    volumes:
      - secrets-shared:/app/secrets:ro
    depends_on:
      vault-agent:
        condition: service_healthy

  # Агент Vault
  vault-agent:
    image: hashicorp/vault:latest
    cap_add:
      - IPC_LOCK
    volumes:
      - ./agent-config.hcl:/etc/vault/config.hcl
      - secrets-shared:/app/secrets
    command: agent -config=/etc/vault/config.hcl
    environment:
      - VAULT_ADDR=https://vault.example.com:8200

volumes:
  secrets-shared:
    driver_opts:
      type: tmpfs
      device: tmpfs
```

### Скрипт инициализации (Entrypoint) для Legacy-приложений

Если приложение поддерживает только переменные окружения, используйте скрипт, который получает данные из Vault и выполняет `exec`.

**Пример `entrypoint.sh`:**
```bash
#!/bin/bash
# Аутентификация через AppRole (RoleID и SecretID передаются оркестратором)
TOKEN=$(curl -s --request POST --data "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" $VAULT_ADDR/v1/auth/approle/login | jq -r .auth.client_token)

# Получение секрета
DB_PASSWORD=$(curl -s --header "X-Vault-Token: $TOKEN" $VAULT_ADDR/v1/secret/data/db | jq -r .data.data.password)

export DB_PASSWORD
exec "$@"
```

## Дополнительная информация

### Рекомендации по безопасности

1.  **Использование tmpfs:** Никогда не сохраняйте расшифрованные секреты на физический диск хоста. Используйте `tmpfs` тома Docker.
2.  **Защита памяти (IPC_LOCK):** Всегда добавляйте `cap_add: [IPC_LOCK]` для контейнера с Vault или Агентом, чтобы предотвратить сброс секретов в swap.
3.  **Маскирование переменных:** В CI/CD пайплайнах помечайте переменные как `masked` или `hidden`.
4.  **Сетевая безопасность:** Даже во внутренней сети Docker (`bridge` или `overlay`) трафик к Vault должен быть зашифрован (TLS).

### См. также

*   **[Безопасное управление секретами в Docker](../../Docker/Docker_security/secrets_management.md)** — SSoT по нативным механизмам Docker.
*   **[Vault Agent: основы](./vault_agent/basics.md)** — детальная настройка шаблонов.
*   **[Аутентификация через AppRole](./vault_auth_approle.md)** — детали машинной аутентификации.
*   **[Подход Zero Trust](../zero_trust.md)** — концепция федерации идентичности (WIF).
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему нельзя использовать `ARG` и `ENV` для секретов.
