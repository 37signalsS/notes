# Vault Agent — определения и базовая конфигурация

**Актуально для:** Vault 1.15+ (Process Supervisor Mode, Vault Proxy, persistent cache; совместим с 2.x)

## Определения

**Vault Agent** — это клиентский режим работы бинарного файла `vault`, предназначенный для автоматизации взаимодействия приложений с сервером Vault. Он действует как локальный посредник (Proxy/Sidecar), исключая необходимость встраивания логики аутентификации и управления токенами непосредственно в код приложения.

**Vault Proxy (Vault 1.15+)** — специализированная эволюция агента, выделенная в отдельный исполняемый компонент и ориентированная исключительно на проксирование API-запросов и кэширование статических секретов. В современных архитектурах функциональность проксирования (API Proxy) вынесена из Agent в Proxy, в то время как Agent остается основным инструментом для инъекции секретов в файлы и переменные окружения. Запускается через `vault proxy -config=proxy.hcl` ([официальная документация](https://developer.hashicorp.com/vault/docs/agent-and-proxy/proxy)).

> **Статус:** Встроенный API Proxy в Vault Agent **deprecated** и **планируется к удалению** (срок поддержки — Q2 2026). Для новых развёртываний используйте Vault Proxy.

### Ключевые задачи агента

1.  **Auto-Auth (Автоматическая аутентификация):** Самостоятельный вход в Vault через настроенные методы (AppRole, Kubernetes, AWS и др.).
2.  **Управление жизненным циклом токена:** Кэширование, автоматическое продление (renew) и перевыпуск токена при истечении.
3.  **Рендеринг секретов (Templating):** Запрос секретов и их запись в конфигурационные файлы приложения через движок [Consul Template](https://github.com/hashicorp/consul-template); отдельное руководство — [consul-template](../consul-template.md).
4.  **Бесшовная ротация:** Выполнение команд (например, `SIGHUP` приложению) после обновления секрета в файле, что позволяет обновлять пароли без перезапуска сервиса.
5.  **Persistent Caching (1.15+):** Сохранение токенов и аренды секретов в локальном кэше (BoltDB), что позволяет агенту восстанавливать состояние после перезапуска без повторной аутентификации.

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
# persist поддерживает только тип "kubernetes" (требует SA-токен).
# См. раздел «Управление кэшем и персистентностью» для обходных путей.
cache {
  use_auto_auth_token = true
}

# Глобальные настройки движка шаблонов
template_config {
  exit_on_retry_failure = true # выйти при исчерпании попыток, а не циклиться бесконечно
  static_secret_render_interval = "10m" # период перерисовки статических секретов (KV v2)
  max_connections_per_host = 20
  # lease_renewal_threshold = 0.9 — доля lease duration для перезапроса dynamic-секретов
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
ExecStart=/usr/bin/vault agent \
  -config=/etc/vault.d/agent.hcl \
  -log-level=info \
  -log-file=/var/log/vault-agent/agent.log \
  -log-rotate-max-files=5 \
  -log-rotate-duration=24h
ExecReload=/bin/kill --signal HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=5
TimeoutStartSec=30
StartLimitBurst=3
StartLimitIntervalSec=10

[Install]
WantedBy=multi-user.target
```

> **Vault 2.0.2+:** в контейнерах `CAP_IPC_LOCK` больше не требуется — бинарник Vault не имеет этой capability на этапе сборки. Операторы контейнеров должны установить `disable_mlock = true` в конфигурации. На bare metal / VM `CAP_IPC_LOCK` и `LimitMEMLOCK=infinity` по-прежнему применяются.

После создания unit-файла:

```bash
sudo mkdir -p /var/log/vault-agent
sudo chown vault:vault /var/log/vault-agent
sudo chmod 0750 /var/log/vault-agent

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

Для управления логами через systemd используйте journald:

```ini
# /etc/systemd/journald.conf.d/vault-agent.conf
[Journal]
MaxRetentionSec=7day
MaxSize=100M
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

> **Важно:** Встроенный API Proxy в Agent **deprecated** (см. выше). Для чисто проксирующих сценариев используйте отдельный компонент [Vault Proxy](https://developer.hashicorp.com/vault/docs/agent-and-proxy/proxy).

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

### Управление кэшем и персистентностью (BoltDB)

Блок `cache` позволяет агенту хранить токены, аренды и секреты в локальной памяти и на диске. Без `cache` агент выполняет сетевой запрос к Vault при каждом рендеринге шаблона.

```hcl
cache {
  use_auto_auth_token = true

  # Персистентный кэш на диске (BoltDB)
  # Тип "kubernetes" требует service account token (K8s).
  persist "kubernetes" {
    path = "/var/lib/vault-agent/cache.db"
    keep_after_import = true   # не удалять файл после импорта кэша
    exit_on_err = true         # завершить работу при ошибке восстановления
  }
}
```

Правила:
*   **`use_auto_auth_token = true`:** аутентифицирует все запросы к Vault от имени агента, исключая необходимость прописывать токен в шаблонах.
*   **`persist` (Vault 1.15+):** сохраняет кэш на диск в формате BoltDB. После перезапуска агент импортирует кэш и продлевает аренды без повторной аутентификации. **Поддерживается только тип `kubernetes`** (требует K8s service account token). Для on-prem / bare metal используйте обходной путь: создайте статичный файл-токен и укажите путь к нему через `service_account_token_file` (см. [issue #26265](https://github.com/hashicorp/vault/issues/26265)).
*   **`keep_after_import`:** по умолчанию `false`. Если импорт не удался, файл удаляется. В production рекомендуется `true` для ручного анализа.
*   **`exit_on_err`:** по умолчанию **`true`**. При `true` агент завершается с ненулевым кодом, что позволяет systemd зафиксировать ошибку.
*   **Путь к файлу:** размещайте на разделе, защищенном от swap (отключите swap или используйте `mlock`). В контейнерах используйте `emptyDir` или `hostPath` с `tmpfs`.
*   **Размер:** BoltDB ограничена по объему (десятки МБ). Для сред с большим количеством уникальных секретов мониторьте рост файла.
*   **Важно:** персистентный кэш сохраняет **только leased secrets** (токены, динамические секреты). Статические секреты (KV v2) при восстановлении перезапрашиваются из Vault.

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

Агент работает как системный сервис, рендерит секреты в файлы и перезапускает приложение при обновлении.

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

Подробности метода, фильтры и маппинг групп на политики — [Vault: аутентификация через LDAP](../vault-auth-ldap.md).

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

Для работы агента роль в Vault должен иметь соответствующие политики.

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

## Операции и команды

### Команды управления службой

```bash
# Старт/остановка/перезагрузка
sudo systemctl start vault-agent
sudo systemctl stop vault-agent
sudo systemctl reload vault-agent    # отправка SIGHUP — перезагрузка конфигурации

# Проверка статуса и логов
sudo systemctl status vault-agent
journalctl -u vault-agent --no-pager -n 100
journalctl -u vault-agent -f

# Проверка рендеринга
cat /etc/app/config.json
# → {"db_user":"admin","db_pass":"s3cret"}
```

### Флаги командной строки `vault agent`

| Флаг | Описание | По умолчанию |
| :--- | :--- | :--- |
| `-config` | Путь к HCL-файлу или директории с конфигами | обязательно |
| `-exit-after-auth` | Завершить работу после успешной аутентификации | `false` |
| `-log-level` | Уровень логирования: `trace`/`debug`/`info`/`warn`/`err` | `info` |
| `-log-format` | Формат логов: `standard`/`json` | `standard` |
| `-log-file` | Путь для записи логов в файл | `./agent.log` |
| `-log-rotate-bytes` | Размер файла в байтах для ротации | не установлен |
| `-log-rotate-duration` | Интервал ротации логов | `24h` |
| `-log-rotate-max-files` | Кол-во архивов для хранения (0 — не удалять, -1 — удалять все) | `0` |
| `-address` | Адрес Vault сервера | `https://127.0.0.1:8200` |
| `-ca-cert` | Путь к CA-сертификату | — |
| `-client-cert` | Путь к клиентскому сертификату | — |
| `-client-key` | Путь к клиентскому ключу | — |

### Проверка статуса аутентификации

```bash
# Токен, полученный агентом, доступен для проверки
VAULT_TOKEN=$(cat /etc/vault.d/.vault-token)

# Инспекция токена: политики, TTL, renewable
export VAULT_TOKEN
vault token lookup
# → Ключ                Значение
#   path                cubbyhole/
#   policies            [webapp-reader]
#   ttl                 3600
#   renewable           true

# Проверка здоровья Vault (через агент или напрямую)
curl -k https://vault.example.com:8200/v1/sys/health
# → {"sealed":false,"initialized":true,"standby":false,"performance_standby":false,"replication_performance_mode":"disabled","replication_dr_mode":"disabled","server_time_offset":0}
```

### Ручное управление кэшем

```bash
# Агент использует BoltDB-файл для кэша. Для ручного анализа:
# 1. Остановите агент
sudo systemctl stop vault-agent

# 2. Проверьте размер файла кэша
ls -lh /var/lib/vault-agent/cache.db

# 3. При необходимости удалите кэш для чистого старта
rm -f /var/lib/vault-agent/cache.db

# 4. Запустите агент
sudo systemctl start vault-agent
```

## Устранение неполадок

### Типовые ошибки

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

### Отладка и диагностика

```bash
# Запуск с debug-логированием
vault agent -config=/etc/vault.d/agent.hcl -log-level=debug

# Запуск с JSON-логами для парсинга в лог-агрегатор
vault agent -config=/etc/vault.d/agent.hcl -log-level=info -log-format=json

# Проверка синтаксиса конфигурации
vault agent -config=/etc/vault.d/agent.hcl -log-level=info &
sleep 2
# Если агент стартовал без ошибок — синтаксис корректен
kill %1

# Проверка TLS-соединения
openssl s_client -connect vault.example.com:8200 -CAfile /etc/vault.d/ca.crt
```

## Лучшие практики

### Безопасность файловой системы

*   **Директории с секретами:** размещайте на `tmpfs` (в памяти), чтобы секреты не попадали на диск. Пример для systemd: `PrivateTmp=yes` + монтирование секретов в `/run/secrets`.
*   **Права на файлы:** директория с `agent.hcl` и `cache.db` должна принадлежать пользователю `vault:vault`, права `0600` на конфиг и `0640` на кэш.
*   **Очистка временных файлов:** секрет ID (`secret_id_file_path`) должен удаляться после прочтения (`remove_secret_id_file_after_reading = true`).
*   **Swap:** отключите swap на хосте (`sudo swapoff -a`) или используйте `mlock`, чтобы секреты не попали в swap-раздел.
*   **Запрет на встроенный token sink:** если приложение читает токен из файла, ограничьте права на этот файл (0600), иначе любой пользователь системы получит доступ к Vault.

### Управление логами и аудит

*   **Ротация логов:** используйте встроенные флаги `-log-rotate-bytes`, `-log-rotate-duration`, `-log-rotate-max-files`, либо journald:
  ```ini
  # /etc/systemd/journald.conf.d/vault-agent.conf
  [Journal]
  MaxRetentionSec=7day
  MaxSize=100M
  ```
*   **JSON-формат:** включайте `-log-format=json` для удобного парсинга в ELK/Fluentd/Loki.
*   **Не логируйте секреты:** агент не выводит значения секретов в логи, но убедитесь, что отладочный лог не попадает в публичные хранилища логов.

### Ограничения и известные проблемы

*   **Нет атомарного обновления нескольких шаблонов:** при массовом изменении секретов агент обновляет файлы последовательно. Кратковременно приложение может видеть несогласованное состояние. Используйте блок `wait` для стабилизации.
*   **Один `exec` на конфиг:** в режиме супервизора допускается ровно один блок `exec`. Для запуска нескольких процессов используйте процесс-менеджер (например, `s6` или `runit`) внутри `exec`.
*   **BoltDB и NFS:** хранить `cache.db` на NFS-разделе нельзя — BoltDB не поддерживает распределенные блокировки.
*   **Ручное управление токеном:** если агент пишет токен в файл (`sink "file"`), не изменяйте этот файл вручную — агент перезапишет его при следующем renew.
*   **Версия агента:** используйте версию, совместимую с версией сервера Vault (minor version difference допустима, major — нет).
*   **Persistent Cache — только Kubernetes:** тип `persist "kubernetes"` требует service account token. Для on-prem обходной путь — создать статичный токен и использовать его как `service_account_token_file` (см. [issue #26265](https://github.com/hashicorp/vault/issues/26265)).
*   **Персистентный кэш не сохраняет KV v2:** только leased secrets (токены, dynamic credentials) сохраняются в кэше. Статические KV v2 секреты при перезапуске перезапрашиваются.

### Метрики Prometheus и мониторинг

Агент экспортирует метрики на эндпоинте `/v1/metrics` (по умолчанию на `127.0.0.1:9102` при включенном `telemetry`). Ключевые метрики для SRE:

```hcl
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname          = true
}

# Метрики экспортируются на отдельный listener
listener "tcp" {
  address     = "127.0.0.1:9102"
  tls_disable = true
  telemetry {
    unauthenticated_metrics_access = false  # требовать аутентификацию для /v1/metrics
  }
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

### Сравнение методов доставки

| Метод | Механизм | Когда использовать |
| :--- | :--- | :--- |
| **Agent Files** | Запись в `.json`, `.yaml`, `.env` через блок `template`. | Стандарт для большинства приложений. |
| **Agent Env** | `env_template` + блок `exec` (Process Supervisor Mode). | Когда приложение не умеет читать файлы и нужны секреты в окружении. |
| **Agent API Proxy** | Локальный `listener` + кэш (блок `cache`). | **Deprecated** — используйте Vault Proxy. |
| **Vault Proxy** | Отдельный бинарник: API-запросы без токена, кэш. | Когда нужна только динамика через SDK/API (без шаблонов). |

## Дополнительная информация

### Связанные документы

*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — основной метод для машин (конфигурация для агента).
*   **[Интеграция с Kubernetes](../vault_kubernetes_integration.md)** — использование агента как sidecar.
*   **[Авторизация и политики](../../authorization.md)** — синтаксис прав доступа.
