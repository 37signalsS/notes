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

### Верификация TLS и клиентские сертификаты

Блок `vault` поддерживает двухсторонний TLS (mTLS) для аутентификации клиента на стороне сервера Vault. Это избавляет от необходимости передавать токены через сеть и используется в high-security средах.

```hcl
vault {
  address = "https://vault.example.com:8200"
  ca_cert = "/etc/vault.d/ca.crt"

  # mTLS: клиентский сертификат и ключ
  client_cert = "/etc/vault.d/client.crt"
  client_key  = "/etc/vault.d/client.key"

  # Проверка имени сервера в сертификате (по умолчанию: true)
  tls_verify = true
}
```

Правила:
*   **`ca_cert`:** обязателен в production. Промежуточные и корневые сертификаты можно склеивать в один PEM-файл.
*   **`client_cert`/`client_key`:** используются, если на сервере Vault включен `tls_client_ca_file` и настроен auth method `cert`.
*   **`tls_verify`:** всегда `true` в production. Отключение (`false`) допустимо только для отладки на изолированных стендах.
*   **Альтернатива:** переменные окружения `VAULT_CACERT`, `VAULT_CLIENT_CERT`, `VAULT_CLIENT_KEY`.

### Системный сервис systemd (Bare Metal / VM)

Для запуска агента на выделенном сервере или ВМ создайте unit-файл, аналогичный hardening сервиса Vault.

```ini
# /etc/systemd/system/vault-agent.service
[Unit]
Description=HashiCorp Vault Agent
After=network-online.target vault.service
Wants=vault.service
ConditionFileNotEmpty=/etc/vault.d/agent.hcl

[Service]
Type=simple
User=vault
Group=vault
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
NoNewPrivileges=yes
AmbientCapabilities=CAP_IPC_LOCK
CapabilityBoundingSet=CAP_IPC_LOCK
LimitMEMLOCK=infinity
LimitCORE=0
ExecStart=/usr/bin/vault agent -config=/etc/vault.d/agent.hcl
ExecReload=/bin/kill --signal HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=5
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
```

После создания unit-файла:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vault-agent
sudo systemctl status vault-agent
journalctl -u vault-agent -f
```

Важно: параметры `AmbientCapabilities` и `LimitMEMLOCK` требуют наличия capability `CAP_IPC_LOCK` у бинарного файла:

```bash
sudo setcap cap_ipc_lock=+eip /usr/bin/vault
```

Если `mlock` не требуется (например, в контейнере), добавьте в HCL: `disable_mlock = true`.

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

### Управление кэшем и персистентностью (BoltDB)

Блок `cache` позволяет агенту хранить токены, аренды и секреты в локальной памяти и на диске. Без `cache` агент выполняет сетевой запрос к Vault при каждом рендеринге шаблона.

```hcl
cache {
  use_auto_auth_token = true

  # Персистентный кэш на диске (BoltDB)
  persist "file" {
    path = "/var/lib/vault-agent/cache.db"
    keep_after_import = true   # не удалять файл после импорта кэша
    exit_on_err = true         # завершить работу при ошибке восстановления
  }
}
```

Правила:
*   **`use_auto_auth_token = true`:** аутентифицирует все запросы к Vault от имени агента, исключая необходимость прописывать токен в шаблонах.
*   **`persist "file"`** (Vault 1.15+): сохраняет кэш на диск в формате BoltDB. После перезапуска агент импортирует кэш и продлевает аренды без повторной аутентификации.
*   **`keep_after_import`:** по умолчанию `false`. Если импорт не удался, файл удаляется. В production рекомендуется `true` для ручного анализа.
*   **`exit_on_err`:** по умолчанию `false`. При `true` агент завершается с ненулевым кодом, что позволяет systemd зафиксировать ошибку.
*   **Путь к файлу:** размещайте на разделе, защищенном от swap (отключите swap или используйте `mlock`). В контейнерах используйте `emptyDir` или `hostPath` с `tmpfs`.
*   **Размер:** BoltDB ограничена по объему (десятки МБ). Для сред с большим количеством уникальных секретов мониторьте рост файла.

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

### Пограничные случаи режима супервизора

*   **Неудачный рендеринг при старте:** если хотя бы один `env_template` не может быть рендерен, агент завершается с ошибкой до запуска дочернего процесса. Это защищает от запуска приложения с пустыми или частично заполненными переменными.
*   **`restart_on_secret_changes = "always"`:** при любом изменении секрета дочерний процесс получает сигнал `restart_stop_signal` (по умолчанию `SIGTERM`). Если приложение не обрабатывает `SIGTERM` gracefully, возможна потеря данных. Убедитесь, что приложение корректно завершает активные соединения.
*   **Обработка сигналов агентом:** агент перехватывает `SIGTERM` и передает его дочернему процессу. При получении `SIGINT` (`Ctrl+C`) агент завершается немедленно, не давая дочернему процессу время на graceful shutdown.
*   **Ресурсы:** в режиме супервизора агент является родительским процессом (PID 1). Настройте `restart=on-failure` в systemd или аналогичный оркестратор, чтобы автоматически перезапускать агент при падении.
*   **Логирование:** stdout/stderr агента дублируют stdout/stderr дочернего процесса. При проблемах проверяйте логи самого агента отдельно: `journalctl -u vault-agent` или вывод процесса.

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

### Сценарий 3: Деплой на bare metal через systemd

Агент работает как системный сервис, рендерит секреты в файлы и перезапужает приложение при обновлении.

**Шаг 1.** Создайте конфигурацию `/etc/vault.d/agent.hcl` (см. раздел «Структура конфигурации»).

**Шаг 2.** Создайте unit-файл `/etc/systemd/system/vault-agent.service` (см. раздел «Системный сервис systemd»).

**Шаг 3.** Включите сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vault-agent
sudo systemctl status vault-agent
```

**Шаг 4.** Проверьте рендеринг:

```bash
cat /etc/app/config.json
# → {"db_user":"admin","db_pass":"s3cret"}

# Проверьте статус аутентификации
vault token lookup
# → token renewal window, policies, TTL
```

### Сценарий 4: Автоматическая аутентификация через различные методы

Auto-Auth поддерживает все стандартные auth-методы Vault. Ниже — минимальные конфигурации для распространенных on-prem сценариев.

**AppRole (рекомендуется для машин):**

```hcl
auto_auth {
  method "approle" {
    config = {
      role_id_file_path = "/etc/vault.d/.role_id"
      secret_id_file_path = "/etc/vault.d/.secret_id"
      remove_secret_id_file_after_reading = true
    }
  }
  sink "file" { config = { path = "/etc/vault.d/.vault-token" } }
}
```

**JWT с локальным файлом токена (OIDC, GitHub Actions, CI):**

```hcl
auto_auth {
  method "jwt" {
    config = {
      role = "ci-runner"
      path = "/var/run/secrets/ci-token" # файл с JWT
    }
  }
}
```

**Kubernetes (внутри кластера):**

```hcl
auto_auth {
  method "kubernetes" {
    config = {
      role = "webapp-role"
      token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    }
  }
}
```

**LDAP (учетная запись сервиса):**

```hcl
auto_auth {
  method "ldap" {
    config = {
      username = "vault-agent"
      password = "file:/etc/vault.d/.ldap-pass"
    }
  }
}
```

**Сертификаты (mTLS):**

```hcl
auto_auth {
  method "cert" {
    config = {
      name = "webapp"
    }
  }
}
```

После конфигурирования auth-метода привяжите к роли соответствующую политику (см. [Авторизация и политики](../../authorization.md)).

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
| `connection refused` / `no such host` | Vault недоступен или DNS не разрешается. | Проверьте сетевое соединение (`curl -k $VAULT_ADDR/v1/sys/health`) и firewall. |
| `certificate signed by unknown authority` | Сертификат Vault не подписан доверенным CA. | Укажите правильный `ca_cert` или добавьте корневой сертификат в trust store. |
| `lease is not renewable` | Аренда секрета не поддерживает продление. | Убедитесь, что у секрета есть `renewable=true` (например, динамические секреты БД поддерживают, статические — нет). |
| `missing field Data` | Неверный синтаксис шаблона для версии KV. | Для KV v1 используйте `.Data.<key>`, для KV v2 — `.Data.data.<key>`. |
| `error_on_missing_key` triggered | Ключ отсутствует в секрете или путь указан неверно. | Проверьте путь secret и наличие поля через `vault kv get`. |
| `permission denied` на `cache.db` | Нет прав на запись в директорию кэша. | Установите владельца `User=vault` на каталог и файл, проверьте `umask`. |
| `context canceled` / `request timed out` | Превышен таймаут запроса к Vault. | Увеличьте `timeout` в блоке `vault { ... }` (по умолчанию 60s) или настройте `retry`. |
| `agent failed to start after auth` | Ошибка в шаблоне или недоступность секрета после аутентификации. | Запустите с `-log-level=debug`, проверьте синтаксис `.ctmpl` и права на пути. |
| `token lookup self failed` | Токен истек или был отозван. | Проверьте `token_ttl` политики и `renew` агентом. Убедитесь, что Vault сервер доступен. |
| `signal: killed` | Агент получил SIGKILL (OOM или внешнее убийство). | Проверьте `dmesg` и логи systemd на предмет `oom-kill`. Увеличьте `LimitMEMLOCK` или `memory.limit_in_bytes`. |

### Метрики Prometheus и мониторинг

Агент экспортирует метрики на эндпоинте `/v1/metrics` (по умолчанию на `127.0.0.1:9102` при включенном `telemetry`). Ключевые метрики для SRE:

```hcl
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname          = true
  unauthenticated_metrics_access = false # зафиксировать 127.0.0.1
}
```

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `vault.agent.auth.token.renewal.success` | Успешное продление токена. | Отсутствие метрики в течение `2 × token_ttl` — критично. |
| `vault.agent.auth.token.renewal.failure` | Неудача продления токена. | >0 за 5 минут — проверьте сеть и права. |
| `vault.agent.template.render.success` | Успешный рендеринг шаблона. | Отсутствие метрики — секрет не обновляется. |
| `vault.agent.template.render.failure` | Ошибка рендеринга. | >0 — проблема с синтаксисом или доступом к секрету. |
| `vault.agent.cache.hit` / `vault.agent.cache.miss` | Попадания/промахи кэша. | Рост `miss` — возможно, кэш маловат или секреты слишком разнообразны. |
| `vault.agent.barrier.create` / `vault.agent.barrier.open` | Время открытия/создания BoltDB. | Рост времени — проблема с диском или блокировками. |

Для production рекомендуется увеличить `prometheus_retention_time` до `5m` и экспортировать метрики через отдельный listener:

```hcl
telemetry {
  prometheus_retention_time = "5m"
  disable_hostname          = true
}

listener "tcp" {
  address = "127.0.0.1:9102"
  tls_disable = true
}
```

### Безопасность файловой системы

*   **Директории с секретами:** размещайте на `tmpfs` (в памяти), чтобы секреты не попадали на диск. Пример для systemd: `PrivateTmp=yes` + монтирование секретов в `/run/secrets`.
*   **Права на файлы:** директория с `agent.hcl` и `cache.db` должна принадлежать пользователю `vault:vault`, права `0600` на конфиг и `0640` на кэш.
*   **Очистка временных файлов:** секрет ID (`secret_id_file_path`) должен удаляться после прочтения (`remove_secret_id_file_after_reading = true`).
*   **Swap:** отключите swap на хосте (`sudo swapoff -a`) или используйте `mlock`, чтобы секреты не попали в swap-раздел.
*   **Запрет на встроенный token sink:** если приложение читает токен из файла, ограничьте права на этот файл (0600), иначе любой пользователь системы получит доступ к Vault.

### Ограничения и известные проблемы

*   **Нет атомарного обновления нескольких шаблонов:** при массовом изменении секретов агент обновляет файлы последовательно. Кратковременно приложение может видеть несогласованное состояние. Используйте блок `wait` для стабилизации.
*   **Один `exec` на конфиг:** в режиме супервизора допускается ровно один блок `exec`. Для запуска нескольких процессов используйте процесс-менеджер (например, `s6` или `runit`) внутри `exec`.
*   **BoltDB и NFS:** хранить `cache.db` на NFS-разделе нельзя — BoltDB не поддерживает распределенные блокировки.
*   **Ручное управление токеном:** если агент пишет токен в файл (`sink "file"`), не изменяйте этот файл вручную — агент перезапишет его при следующем renew.
*   **Версия агента:** используйте версию, совместимую с версией сервера Vault (minor version difference допустима, major — нет).

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
