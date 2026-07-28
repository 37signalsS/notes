# Vault Agent — определения и базовая конфигурация

## Определения

**Vault Agent** — это клиентский режим работы бинарного файла `vault`, предназначенный для автоматизации взаимодействия приложений с сервером Vault. Он действует как локальный посредник (Proxy/Sidecar), исключая необходимость встраивания логики аутентификации и управления токенами непосредственно в код приложения.

**Vault Proxy (2024+)** — специализированная эволюция агента, ориентированная исключительно на проксирование API-запросов и кэширование статических секретов. В современных архитектурах функциональность проксирования (API Proxy) вынесена из Agent в Proxy, в то время как Agent остается основным инструментом для инъекции секретов в файлы и переменные окружения.

### Ключевые задачи агента

1.  **Auto-Auth (Автоматическая аутентификация):** Самостоятельный вход в Vault через настроенные методы (AppRole, Kubernetes, AWS и др.).
2.  **Управление жизненным циклом токена:** Кэширование, автоматическое продление (renew) и перевыпуск токена при истечении.
3.  **Рендеринг секретов (Templating):** Запрос секретов и их запись в конфигурационные файлы приложения через движок [Consul Template](https://github.com/hashicorp/consul-template).
4.  **Бесшовная ротация:** Выполнение команд (например, `SIGHUP` приложению) после обновления секрета в файле, что позволяет обновлять пароли без перезапуска сервиса.
5.  **Persistent Caching (1.15+):** Сохранение токенов и аренды секретов в локальной базе данных (BoltDB), что позволяет агенту восстанавливать состояние после перезапуска без повторной аутентификации.

## Основные концепции

Конфигурация агента описывается в файле формата HCL.

### Структура конфигурации (agent.hcl)

```hcl
# /etc/vault.d/agent.hcl

pid_file = "/var/run/vault-agent.pid"

vault {
  address = "https://vault.example.com:8200"
  # Настройка TLS для связи с сервером
  ca_cert = "/etc/vault.d/ca.crt"
}

# Автоматическая аутентификация
auto_auth {
  method "approle" {
    config = {
      role_id_file_path = "/etc/vault.d/.role_id"
      secret_id_file_path = "/etc/vault.d/.secret_id"
      # Удалять secret_id после прочтения для безопасности
      remove_secret_id_file_after_reading = true
    }
  }

  # Куда сохранять полученный токен (необязательно)
  sink "file" {
    config = {
      path = "/etc/vault.d/.vault-token"
    }
  }
}

# Кэширование и персистентность
cache {
  use_auto_auth_token = true
  
  # Сохранение кэша на диск для выживания при перезапуске
  persistent_cache {
    enabled = true
    path    = "/var/lib/vault-agent/cache.db"
  }
}

# Рендеринг шаблонов
template {
  source      = "/etc/app/config.ctmpl"
  destination = "/etc/app/config.json"
  
  # Ожидание стабилизации при массовых изменениях
  wait {
    min = "2s"
    max = "10s"
  }
  
  # Команда после обновления файла
  command = "kill -HUP $(pgrep my-app)"
}

# Сбор метрик (Prometheus)
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname          = true
}
```

### Синтаксис шаблонов (.ctmpl)

Агент использует синтаксис Go-templates. Основная конструкция — `with secret`:

```go-template
# /etc/app/config.ctmpl

# Работа с KV v2 хранилищем
{{ with secret "secret/data/webapp/db" }}
{
  "db_user": "{{ .Data.data.username }}",
  "db_pass": "{{ .Data.data.password }}"
}
{{ end }}

# Динамические секреты (база данных)
{{ with secret "database/creds/readonly" }}
db_url = "postgres://{{ .Data.username }}:{{ .Data.password }}@db.local:5432/app"
{{ end }}
```

### Метод env_template (Новое)

Позволяет инжектировать секреты напрямую в переменные окружения дочернего процесса, который запускает сам агент (режим Supervisor).

## Практические сценарии

### Сценарий 1: Ротация API-ключей без простоя

1.  **Обновление:** В Vault обновляется значение `secret/data/api-key`.
2.  **Обнаружение:** Агент видит изменение (через подписку или опрос).
3.  **Рендеринг:** Агент переписывает файл `/app/config.yaml`.
4.  **Уведомление:** Агент выполняет `command = "systemctl reload webapp"`.
5.  **Результат:** Приложение читает новый ключ из файла без прерывания сессий пользователей.

### Сценарий 2: Использование в CI/CD (Short-lived)

Для задач сборки или деплоя агент должен получить токен, выполнить работу и завершиться.

```hcl
auto_auth {
  # Завершить работу агента сразу после успешного получения токена
  exit_after_auth = true
  method "jwt" {
    config = {
      role = "ci-runner"
      path = "/var/run/secrets/ci-token"
    }
  }
}
```

### Пример: Настройка прав для AppRole

Для работы агента роль в Vault должна иметь соответствующие политики.

```bash
# 1. Создаем политику 'agent-policy.hcl'
path "secret/data/webapp/*" {
  capabilities = ["read"]
}

# 2. Применяем политику
vault policy write webapp-reader agent-policy.hcl

# 3. Привязываем к роли AppRole
vault write auth/approle/role/webapp-role \
    token_policies="webapp-reader" \
    token_ttl="1h"
```

## Дополнительная информация

### Отладка: Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | Недостаточно прав в политике Vault. | Проверьте `capabilities` и наличие `data/` в пути для KV v2. |
| `failed to unwrap` | Оберточный токен (wrapping) уже использован. | Убедитесь, что только один процесс (Agent) делает unwrap. |
| `vault.address` not set | Не указан адрес сервера. | Проверьте блок `vault { address = ... }` или переменную `VAULT_ADDR`. |

### Сравнение методов доставки

| Метод | Механизм | Когда использовать |
| :--- | :--- | :--- |
| **Agent Files** | Запись в `.json`, `.yaml`, `.env` | Стандарт для большинства приложений. |
| **Agent Env** | `env_template` + Supervisor | Когда приложение не умеет читать файлы. |
| **Vault Proxy** | API-запросы без токена | Когда приложению нужна динамика (через SDK). |

### Связанные документы

*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — основной метод для машин.
*   **[Интеграция с Kubernetes](../vault_kubernetes_integration.md)** — использование агента как sidecar.
*   **[Авторизация и политики](../../authorization.md)** — синтаксис прав доступа.
*   **[Vault Proxy](https://developer.hashicorp.com/vault/docs/proxy)** — документация по выделенному прокси-серверу.
