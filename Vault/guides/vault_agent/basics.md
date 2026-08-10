# Vault Agent — определения и базовая конфигурация

## Определения

**Vault Agent** — это клиентский режим работы бинарного файла `vault`, предназначенный для автоматизации взаимодействия приложений с сервером Vault. Он действует как локальный посредник (Proxy/Sidecar), исключая необходимость встраивания логики аутентификации и управления токенами непосредственно в код приложения.

**Vault Proxy (2024+)** — специализированная эволюция агента, выделенная в отдельный исполняемый компонент и ориентированная исключительно на проксирование API-запросов и кэширование статических секретов. В современных архитектурах функциональность проксирования (API Proxy) вынесена из Agent в Proxy, в то время как Agent остается основным инструментом для инъекции секретов в файлы и переменные окружения. Запускается через `vault proxy -config=proxy.hcl` ([официальная документация](https://developer.hashicorp.com/vault/docs/agent-and-proxy/proxy)).

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

  # Поведение при недоступности сервера (по умолчанию: 12 попыток)
  retry {
    num_retries = 5
  }
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

  # Сохранение кэша на диск для выживания при перезапуске (BoltDB, Vault 1.9+)
  # В Kubernetes токен используется как ключ шифрования (AAD)
  persist "kubernetes" {
    path = "/var/lib/vault-agent/cache.db"
    # keep_after_import = true   # не удалять файл после восстановления
    # exit_on_err = true         # выйти при ошибке восстановления кэша
  }
}

# Глобальные настройки движка шаблонов
template_config {
  exit_on_retry_failure = true # выйти при исчерпании попыток, а не циклиться бесконечно
  static_secret_render_interval = "10m" # период перерисовки статических секретов (KV v2)
  max_connections_per_host = 20
}

# Рендеринг шаблонов
template {
  source      = "/etc/app/config.ctmpl"
  destination = "/etc/app/config.json"
  error_on_missing_key = true # «<no value>» вместо отсутствующего ключа — ошибка

  # Ожидание стабилизации при массовых изменениях
  wait {
    min = "2s"
    max = "10s"
  }

  # Команда после обновления файла (deprecated — используйте блок exec ниже;
  # command_timeout по умолчанию 30s)
  # exec {
  #   command = ["systemctl", "reload", "my-app"]
  # }
  command = "kill -HUP $(pgrep my-app)"
}

# Сбор метрик (Prometheus)
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname          = true
}
```

### Синтаксис шаблонов (.ctmpl)

Агент использует синтаксис Go-templates (Consul Template markup). Основная конструкция — `with secret`:

```go-template
# /etc/app/config.ctmpl

# Работа с KV v2 хранилищем (путь содержит /data/)
{{ with secret "secret/data/webapp/db" }}
{
  "db_user": "{{ .Data.data.username }}",
  "db_pass": "{{ .Data.data.password }}"
}
{{ end }}

# Работа с KV v1 хранилищем (путь БЕЗ /data/, значение лежит в .Data.<key>)
{{ with secret "secret/webapp/api-key" }}
api_key = "{{ .Data.value }}"
{{ end }}

# Динамические секреты (база данных)
{{ with secret "database/creds/readonly" }}
db_url = "postgres://{{ .Data.username }}:{{ .Data.password }}@db.local:5432/app"
{{ end }}

# Сертификаты PKI (автоматическая ротация по истечении срока)
{{ with pkiCert "pki/issue/webapp" "common_name=webapp.example.com" }}
tls_cert = "{{ .Data.Certificate }}"
tls_key  = "{{ .Data.PrivateKey }}"
{{ end }}
```

**Ключевые функции и правила:**
*   **KV v1 vs KV v2:** Для KV v1 путь в `with secret` указывается без сегмента `data/`, доступ к значению — через `.Data.<key>`. Для KV v2 путь содержит `data/` (`secret/data/...`), а значения лежат во вложенном поле `.Data.data.<key>`.
*   **`pkiCert` (Vault 1.10+):** Запрашивает сертификат у PKI-движка и автоматически обновляет его по мере приближения срока действия, используя `lease_renewal_threshold`.
*   **`error_on_missing_key`:** Флаг `template`-блока, превращающий отсутствующий ключ из `<no value>` в ошибку (рекомендуется `true`).

### API Proxy и listener

Агент может выступать локальным прокси к Vault: добавление блока `listener` включает **API proxy** — приложение обращается к агенту, а не к серверу напрямую. Прокси использует кэш (если `cache` задан), снижая нагрузку на сервер и управляя ротацией токенов.

```hcl
listener "tcp" {
  address     = "127.0.0.1:8200"
  tls_disable = true
  # require_request_header = true # защита от SSRF: требовать X-Vault-Request: true
}

cache {
  use_auto_auth_token = true
}
```

Для чисто проксирующего сценария (без шаблонов и файлов) официально рекомендуется отдельный компонент [Vault Proxy](https://developer.hashicorp.com/vault/docs/agent-and-proxy/proxy).

### Режим супервизора (env_template + exec)

Позволяет инжектировать секреты напрямую в переменные окружения дочернего процесса, который запускает сам агент (Process Supervisor Mode, Vault 1.15+). Требуется минимум один блок `env_template` и ровно один верхнеуровневый блок `exec`. Режим **несовместим** с обычными file-`template` блоками.

```hcl
env_template "DB_USER" {
  contents            = "{{ with secret \"secret/data/webapp/db\" }}{{ .Data.data.username }}{{ end }}"
  error_on_missing_key = true
}

env_template "DB_PASS" {
  contents            = "{{ with secret \"secret/data/webapp/db\" }}{{ .Data.data.password }}{{ end }}"
  error_on_missing_key = true
}

exec {
  command                   = ["./my-app", "--port=8080"]
  restart_on_secret_changes = "always" # перезапускать дочерний процесс при обновлении секрета
  restart_stop_signal       = "SIGTERM"
}
```

До старта приложения агент дожидается успешного рендеринга всех `env_template`; стандартные потоки (`stdin`/`stdout`/`stderr`) пробрасываются дочернему процессу, а при его выходе агент завершается с тем же кодом.

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
| **Agent Files** | Запись в `.json`, `.yaml`, `.env` через блок `template`. | Стандарт для большинства приложений. |
| **Agent Env** | `env_template` + блок `exec` (Process Supervisor Mode). | Когда приложение не умеет читать файлы и нужны секреты в окружении. |
| **Agent API Proxy** | Локальный `listener` + кэш (блок `cache`). | Когда приложение обращается к Vault API, а прямой доступ нежелателен. |
| **Vault Proxy** | Отдельный бинарник: API-запросы без токена, кэш. | Когда нужна только динамика через SDK/API (без шаблонов). |

### Связанные документы

*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — основной метод для машин (конфигурация для агента).
*   **[Интеграция с Kubernetes](../vault_kubernetes_integration.md)** — использование агента как sidecar.
*   **[Авторизация и политики](../../authorization.md)** — синтаксис прав доступа.
