# Интеграция Vault с Docker

**Актуально для:** Vault 2.x (стабильная ветка 2.x; текущая версия — 2.1.2, октябрь 2026; примеры привязаны к образу `hashicorp/vault:2.1.1`).

## Определения

**Интеграция Vault с Docker** — совокупность архитектурных паттернов и инструментов для обеспечения безопасности секретов (паролей, ключей, сертификатов) в контейнеризированных средах. Целью интеграции является реализация модели жизненного цикла безопасности (SLM), при которой секреты никогда не сохраняются в образах, слоях Docker или переменных окружения.

**BuildKit Secrets** — механизм Docker, позволяющий безопасно монтировать секреты в процессе сборки образа без их сохранения в итоговых слоях файловой системы.

**Vault Agent (Sidecar)** — вспомогательный контейнер, обеспечивающий автоматическую аутентификацию, получение и ротацию секретов для основного приложения.

**Динамические секреты (Dynamic Secrets)** — учетные данные (пароли БД, сертификаты, токены доступа), генерируемые Vault на момент запроса с ограниченным сроком жизни (TTL) и автоматическим отзывом по истечении аренды (lease). В контексте Docker применяются для баз данных, очередей и внешних API.

**Lease (Аренда)** — время жизни, присвоенное секрету или токену Vault. По истечении `lease_duration` секрет автоматически становится невалидным, а Vault инициирует отзыв (revoke). Для динамических секретов (например, учетных данных БД) аренда определяет окно, в течение которого приложение может использовать секрет до его автоматической ротации.

**Exit After Auth** — режим работы Vault Agent (`exit_after_auth = true`), при котором агент аутентифицируется, рендерит шаблоны и завершает работу. Полезен для одноразовой подготовки секретов перед стартом контейнера; снижает потребление ресурсов по сравнению с постоянным sidecar.

## Основные концепции

### Жизненный цикл секрета в Docker

Процесс интеграции разделяется на две стадии:

1.  **Стадия сборки (Build-time):** Секреты нужны для доступа к приватным репозиториям, пакетам или API провайдеров. Механизм BuildKit `--mount=type=secret` гарантирует, что секрет не попадает в слои образа и невидим в `docker history` или `docker inspect`.
2.  **Стадия выполнения (Runtime):** Приложение получает динамические или статические учетные данные для работы с базами данных, очередями и внешними сервисами. На runtime используется Vault Agent (sidecar) или entrypoint-скрипт, которые поддерживают актуальность секретов через механизм аренды (lease) и автоматического продления (renew).

### Жизненный цикл токена и аренды в Docker-среде

При использовании Vault Agent в Docker контейнере важно понимать три фазы:

1.  **Аутентификация (Login):** Агент получает токен через AppRole или другой метод. Токен имеет `token_ttl` (например, 1 час) и `token_max_ttl`.
2.  **Продление (Renew):** Пока токен валиден, агент автоматически продлевает его. Если Vault недоступен, агент использует персистентный кэш (BoltDB) для перезапуска без повторного логина.
3.  **Отзыв (Revoke):** При истечении `token_max_ttl` или явном отзыве токен становится невалидным. Агент автоматически перелогинивается при восстановлении соединения с Vault.

Для динамических секретов (БД, облачные ресурсы) Vault выдает аренду (`lease_duration`), по истечении которой учетные данные автоматически отзываются. Агент отслеживает `lease_duration` и обновляет секрет до истечения срока.

### Динамические секреты в Docker

Vault может генерировать краткоживущие учетные данные для:
- **Базы данных** (PostgreSQL, MySQL, MongoDB) — уникальный логин/пароль на каждый экземпляр приложения.
- **SSH** — единоразовые сертификаты для доступа к серверам.
- **PKI** — автоматическая выдача и ротация TLS-сертификатов.

В Docker-среде динамические секреты доставляются через Vault Agent в файлы или переменные окружения. Приложение должно уметь переподключаться к ресурсу при смене пароля (graceful reload).

### Сетевое взаимодействие контейнера с Vault

Контейнер с приложением или Vault Agent должен иметь маршрут до сервера Vault. Варианты сетевых конфигураций:

- **Bridge (по умолчанию):** Контейнеры в одной сети `bridge` видят порты хоста через `host.docker.internal` (Docker Desktop) или IP-адрес хоста. Для нескольких хостов используйте кастомный `bridge` или `overlay`.
- **Overlay (Swarm / Docker Compose with external):** Для распределенных сред контейнеры в overlay-сети могут обращаться к Vault по его внутреннему DNS-имени.
- **Host:** При крайней необходимости (отладка) можно использовать `network_mode: host`, но это нарушает изоляцию и не рекомендуется для production.

Vault Agent внутри контейнера должен использовать IP-адрес или DNS-имя Vault, доступное из сети контейнера. TLS-сертификат Vault (`ca_cert`) монтируется в контейнер агента для проверки подлинности.

### Сравнение методов интеграции

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **BuildKit Secrets** | Монтирование секретов через `--mount=type=secret`. | Сборка образов (CI/CD). |
| **Vault Agent** | Рендеринг шаблонов в общую `tmpfs` директорию. | Продуктивные среды, Docker Compose. |
| **Direct API** | Использование SDK (hvac, vault-ruby) внутри кода. | Сложная динамическая логика. |
| **Entrypoint (Bash)** | Получение секретов через `curl` перед запуском приложения. | Legacy-системы, быстрые прототипы. |
| **Vault Agent (exit_after_auth)** | Агент аутентифицируется, рендерит секреты и завершает работу. | Одноразовая подготовка секретов перед стартом приложения, снижение footprint. |

### Идентификация и аутентификация

Для контейнеров в Docker предпочтительными методами аутентификации являются:

- **OIDC / JWT:** Для CI/CD пайплайнов на self-hosted раннерах (GitLab CI, Jenkins), где Vault доверяет идентификатору раннера через подписанный JWT.
- **AppRole:** Стандартный метод для статических серверов или Docker Compose, использующий `RoleID` и `SecretID`. Подробнее — в [Аутентификации через AppRole](./vault_auth_approle.md).
- **OIDC для GitHub/GitLab Actions:** Платформа выдает короткоживущий JWT, Vault проверяет подпись и выдает токен без статических `SecretID`.

## Практические сценарии

### Сборка образов с использованием BuildKit Secrets

Использование BuildKit предотвращает утечку Vault-токенов в историю слоев образа.

**Пример Dockerfile:**
```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Монтирование секрета только на время выполнения команды RUN.
# required=true: сборка упадёт, если секрет не передан (предотвращает случайную сборку без токена)
RUN --mount=type=secret,id=vault_token,required=true \
    VAULT_TOKEN=$(cat /run/secrets/vault_token) && \
    pip install --index-url https://my-private-repo.com/simple/ my-internal-package
```

**Команда сборки:**
```bash
export VAULT_TOKEN=$(vault login -method=oidc -token-only)
docker build --secret id=vault_token,env=VAULT_TOKEN -t my-secure-app .
docker buildx build --secret id=vault_token,env=VAULT_TOKEN -t my-secure-app . # мультиплатформенная сборка
```

> Файл `/run/secrets/vault_token` существует **только внутри** процесса сборки (`RUN`) и не попадает ни в слои образа, ни в `docker history`. Параметр `required=true` доступен в BuildKit и поддерживается в современных версиях Docker 24+/Buildx.

#### Мультиплатформенная сборка (buildx)

Для сборки образов под несколько архитектур (`linux/amd64`, `linux/arm64`) используйте `docker buildx` с кэшированием:

```bash
# Создание инстанса buildx (если не создан)
docker buildx create --use --name multiarch-builder

# Сборка с кэшированием и секретами
docker buildx build \
  --secret id=vault_token,env=VAULT_TOKEN \
  --cache-from=type=local,src=/tmp/.buildx-cache \
  --cache-to=type=local,dest=/tmp/.buildx-cache \
  --platform linux/amd64,linux/arm64 \
  -t my-secure-app:multiarch .
```

### Использование Vault Agent в Docker Compose (Sidecar паттерн)

В Docker Compose у приложения нет нативных `initContainer` (в отличие от Kubernetes), поэтому Vault Agent запускается как отдельный сервис, который готовит секреты в общей `tmpfs` области памяти.

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
    # Фиксируйте точный тег вместо latest (anti-pattern)
    image: hashicorp/vault:2.1.1
    cap_add:
      - IPC_LOCK
    volumes:
      - ./agent-config.hcl:/etc/vault/config.hcl:ro
      - secrets-shared:/app/secrets
    command: agent -config=/etc/vault/config.hcl
    environment:
      - VAULT_ADDR=https://vault.example.com:8200
    healthcheck:
      # Проверка, что агент уже отрендерил секрет (иначе app стартует раньше)
      test: ["CMD-SHELL", "test -f /app/secrets/db_password.txt"]
      interval: 2s
      timeout: 2s
      retries: 30

volumes:
  secrets-shared:
    driver_opts:
      type: tmpfs
      device: tmpfs
```

**Пример `agent-config.hcl` (AppRole + шаблон в tmpfs):**
```hcl
exit_after_auth = false

vault {
  address = "https://vault.example.com:8200"
  ca_cert = "/etc/vault/ca.crt"
  retry {
    num_retries = 5
    backoff     = "5s"
  }
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path         = "/etc/vault/role-id"
      secret_id_file_path       = "/etc/vault/secret-id"
      remove_secret_id_file_after_reading = true
    }
  }
  sink "file" {
    config = {
      path = "/tmp/.vault-token"
    }
  }
}

cache {
  use_auto_auth_token = true
}

template {
  destination = "/app/secrets/db_password.txt"
  contents    = "{{ with secret \"secret/data/db\" }}{{ .Data.data.password }}{{ end }}"
  error_on_missing_key = true
}
```

> Контейнер агента хранит `RoleID`/`SecretID` через монтируемые файлы. Параметр `exit_after_auth = true` (вместо `false`) переводит агент в режим «отрендерить шаблоны и выйти» — полезен при одноразовой подготовке секретов в `tmpfs` перед стартом приложения. При `false` агент продолжает работать в фоне и поддерживает секреты актуальными, реагируя на изменения в Vault. Рекомендуется `false` для production-сред, где требуется динамическая ротация.

> **Постоянный кэш (persistent cache):** опция `persist` поддерживает **только** драйвер `kubernetes` (хранит кэш в K8s-секрете через service-account token). В чистом Docker Compose / `docker run` / systemd на bare metal драйвер `kubernetes` недоступен — используйте in-memory `cache` (renewal и кэш токенов в течение жизни процесса агента). Для восстановления после перезапуска полагайтесь на повторный `auto_auth` (AppRole) и перерендер шаблонов.

### Динамические секреты (база данных) в Docker Compose

Vault может выдавать краткоживущие учетные данные для PostgreSQL/MySQL. Агент рендерит секрет и сигнализирует приложению о переподключении.

**Пример `agent-config.hcl` (динамические учетные данные БД):**
```hcl
exit_after_auth = false

vault {
  address = "https://vault.example.com:8200"
  ca_cert = "/etc/vault/ca.crt"
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path         = "/etc/vault/role-id"
      secret_id_file_path       = "/etc/vault/secret-id"
    }
  }
}

template {
  destination = "/app/secrets/db-config.yaml"
  contents    = <<-EOH
    {{- with secret "database/creds/webapp-role" -}}
    DB_HOST={{ .Data.data.host }}
    DB_PORT={{ .Data.data.port }}
    DB_USER={{ .Data.data.username }}
    DB_PASSWORD={{ .Data.data.password }}
    LEASE_DURATION={{ .LeaseData.lease_duration }}
    {{- end -}}
  EOH
  command = ["sh", "-c", "kill -HUP $(pgrep -f my-app)"]
  wait {
    min = "2s"
    max = "10s"
  }
}
```

**Дополнение `docker-compose.yml`:**
```yaml
  webapp:
    image: my-app:latest
    volumes:
      - secrets-shared:/app/secrets:ro
    environment:
      - DB_CONFIG_FILE=/app/secrets/db-config.yaml
    depends_on:
      vault-agent:
        condition: service_healthy
```

> Приложение должно поддерживать перечитывание конфигурации по `SIGHUP` или через механизм watch-файлов. Если приложение не переподключается к БД при смене пароля, используйте внешний скрипт-оркестратор, который получает сигнал от агента и выполняет `pgbouncer reload` или аналогичную операцию.

### Многоступенчатая сборка с BuildKit для CI/CD

Для production-пайплайнов используйте многоступенчатый Dockerfile, чтобы секреты сборки не попадали ни в один из промежуточных слоев:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) && \
    npm ci --only=production

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN --mount=type=secret,id=vault_token,required=true \
    VAULT_TOKEN=$(cat /run/secrets/vault_token) && \
    pip install -r requirements.txt
CMD ["python", "app.py"]
```

**Запуск в CI/CD:**
```bash
docker buildx build \
  --secret id=npm_token,src=$HOME/.npm_token \
  --secret id=vault_token,env=VAULT_TOKEN \
  --target runtime \
  -t my-app:ci-$CI_COMMIT_SHA .
```

### Скрипт инициализации (Entrypoint) для Legacy-приложений

Если приложение поддерживает только переменные окружения, используйте скрипт, который получает данные из Vault и выполняет `exec`.

**Пример `entrypoint.sh`:**
```bash
#!/bin/bash
set -euo pipefail

# Проверка обязательных переменных окружения
: "${VAULT_ADDR:?VAULT_ADDR is required}"
: "${ROLE_ID:?ROLE_ID is required}"
: "${SECRET_ID:?SECRET_ID is required}"

# Аутентификация через AppRole с повторными попытками
TOKEN=""
for i in {1..5}; do
  RESPONSE=$(curl -s --request POST \
    --data "{\"role_id\":\"${ROLE_ID}\",\"secret_id\":\"${SECRET_ID}\"}" \
    "${VAULT_ADDR}/v1/auth/approle/login")
  TOKEN=$(echo "${RESPONSE}" | jq -r '.auth.client_token // empty')
  if [[ -n "${TOKEN}" ]]; then
    break
  fi
  echo "Attempt ${i}: failed to authenticate, retrying in 3s..."
  sleep 3
done

if [[ -z "${TOKEN}" ]]; then
  echo "FATAL: Unable to authenticate with Vault after 5 attempts"
  exit 1
fi

# Получение секрета с проверкой структуры ответа
RESPONSE=$(curl -s --header "X-Vault-Token: ${TOKEN}" \
  "${VAULT_ADDR}/v1/secret/data/db")

DB_PASSWORD=$(echo "${RESPONSE}" | jq -r '.data.data.password // empty')
if [[ -z "${DB_PASSWORD}" ]]; then
  echo "FATAL: Unable to read DB password from Vault"
  exit 1
fi

export DB_PASSWORD

# Очистка чувствительных переменных из окружения
unset ROLE_ID SECRET_ID TOKEN RESPONSE

exec "$@"
```

**Dockerfile для образа с entrypoint:**
```dockerfile
FROM alpine:3.20
RUN apk add --no-cache curl jq
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["my-app"]
```

### Прямая работа через SDK (Direct API)

Когда приложение использует Vault в коде (сложная динамическая логика, Vault KV v2, динамические credentials БД), применяются официальные клиентские библиотеки. Важное правило — секреты не передаются через `ENV`, а читаются через SDK по требованию с коротким TTL.

**Пример на Python (`hvac`):**
```python
import hvac
import os

client = hvac.Client(
    url=os.environ["VAULT_ADDR"],
    token=os.environ["VAULT_TOKEN"],  # токен подставляется через Vault Agent или AppRole
)

# Чтение KV v2 (mount point secret)
secret = client.secrets.kv.v2.read_secret_version(path="apps/my-service/db", mount_point="secret")["data"]["data"]
db_password = secret["password"]
```

> В продакшене замените жёсткий `token` на [AppRole](./vault_auth_approle.md) или Vault Agent: SDK получит короткоживущий токен только на время выполнения операции, а не на всё время жизни процесса.

### Vault Agent как systemd-сервис на хосте Docker

Для физических серверов или ВМ, где Docker запускается напрямую (без оркестратора), Vault Agent разворачивается как systemd-сервис, который рендерит секреты в файлы, монтируемые в контейнеры через `bind mount`.

**Шаг 1.** Создайте конфигурацию `/etc/vault.d/agent.hcl`:
```hcl
vault {
  address = "https://vault.example.com:8200"
  ca_cert = "/etc/vault.d/ca.crt"
  retry {
    num_retries = 5
    backoff     = "5s"
  }
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path               = "/etc/vault.d/role-id"
      secret_id_file_path             = "/etc/vault.d/secret-id"
      remove_secret_id_file_after_reading = true
    }
  }
  sink "file" {
    config = {
      path = "/etc/vault.d/.vault-token"
    }
  }
}

cache {
  use_auto_auth_token = true
}

template {
  destination = "/etc/vault/secrets/webapp/db_password.txt"
  contents    = "{{ with secret \"secret/data/webapp/db\" }}{{ .Data.data.password }}{{ end }}"
  error_on_missing_key = true
}
```

**Шаг 2.** Создайте unit-файл `/etc/systemd/system/vault-agent.service`:
```ini
[Unit]
Description=HashiCorp Vault Agent
After=network-online.target
Wants=network-online.target
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

**Шаг 3.** Включите сервис и проверьте статус:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vault-agent
sudo systemctl status vault-agent
journalctl -u vault-agent -f
```

**Шаг 4.** Монтируйте секреты в Docker Compose:
```yaml
services:
  webapp:
    image: my-app:latest
    volumes:
      - /etc/vault/secrets/webapp:/app/secrets:ro
```

> Параметр `AmbientCapabilities=CAP_IPC_LOCK` и `LimitMEMLOCK=infinity` предотвращают сброс секретов в swap. В контейнере добавьте `cap_add: [IPC_LOCK]`. Если `mlock` недоступен, добавьте в HCL: `disable_mlock = true`.

> **Persistent cache:** `persist` доступен **только** в Kubernetes (K8s-секрет через service-account token). Для bare-metal/ВМ без Kubernetes используйте in-memory `cache` + AppRole `auto_auth`; для восстановления после restart полагайтесь на повторный логин и перерендер шаблонов.

### Проверка запуска: Single container режим (docker run)

Для проверки конфигурации без Docker Compose агент можно запустить разово:

```bash
docker run --rm --cap-add=IPC_LOCK \
  -e VAULT_ADDR=https://vault.example.com:8200 \
  -v $PWD/agent-config.hcl:/etc/vault/config.hcl:ro \
  -v $PWD/role-id:/etc/vault/role-id:ro \
  -v $PWD/secret-id:/etc/vault/secret-id:ro \
  -v secrets-shared:/app/secrets \
  hashicorp/vault:2.1.1 agent -config=/etc/vault/config.hcl
```

### Валидация и проверка корректности работы

После запуска контейнера с приложением или агента убедитесь, что секреты доставлены корректно:

```bash
# 1. Проверка доступности Vault
curl -sk https://vault.example.com:8200/v1/sys/health
# → {"initialized":true,"sealed":false,"version":"2.1.1"}

# 2. Проверка рендеринга секретов внутри контейнера
docker exec -it <webapp_container> cat /app/secrets/db_password.txt
# → s3cureP@ssw0rd

# 3. Проверка прав на файлы секретов
docker exec -it <webapp_container> ls -la /app/secrets/
# → -rw-r--r-- 1 root root 128 Sep 20 12:00 db_password.txt

# 4. Проверка логов Vault Agent
docker logs vault-agent
# → 2026-09-20T12:00:00.000Z [INFO]  auth.handler: authentication successful, sending token to sinks

# 5. Проверка, что секрет не попал в историю слоев
docker history my-secure-app
# → секреты отсутствуют в выводе

# 6. Проверка переменных окружения (не должно быть секретов)
docker exec -it <webapp_container> env | grep -i password
# → (пусто)
```

### Диагностика и типичные ошибки

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` при аутентификации | Роль AppRole не существует или `SecretID` неверен/истек. | Проверьте `vault read auth/approle/role/<role>`, убедитесь в валидности `SecretID` и CIDR-ограничениях. |
| `connection refused` / `no such host` | Vault недоступен или DNS не разрешается из контейнера. | Проверьте сетевое соединение: `docker exec <container> nslookup vault.example.com`. |
| `certificate signed by unknown authority` | Сертификат Vault не подписан доверенным CA. | Укажите `ca_cert` в конфигурации агента или переменной `VAULT_CACERT`. |
| `error_on_missing_key` triggered | В шаблоне используется ключ, которого нет в секрете. | Проверьте путь secret и наличие поля через `vault kv get secret/data/db`. |
| `lease is not renewable` | Аренда секрета не поддерживает продление. | Нормально для `batch` токенов; используйте `service` токен, если требуется продление. |
| `agent failed to start after auth` | Ошибка в шаблоне или недоступность секрета после аутентификации. | Запустите с `-log-level=debug`, проверьте синтаксис HCL и права на пути. |
| Секрет не обновляется в файле | Vault недоступен для renew, или `static_secret_render_interval` не настроен. | Проверьте доступность Vault, настройте `template_config { static_secret_render_interval = "10m" }`. |
| `CrashLoopBackOff` (если в Compose) | Неправильные права на файлы `role-id`/`secret-id` или неверный путь в HCL. | Проверьте права: `chmod 600 role-id secret-id`, убедитесь в правильности путей в конфиге. |
| Приложение стартует раньше секретов | Healthcheck агента не настроен или `depends_on` отсутствует. | Добавьте `healthcheck` в сервис агента и `condition: service_healthy` в `depends_on`. |
| `token lookup self failed` | Токен истек или был отозван. | Проверьте `token_ttl` политики и работу renew в агенте. Убедитесь, что Vault сервер доступен. |
| `persist` / кэш не восстанавливается после restart | Драйвер `persist` — `kubernetes` only; в Docker Compose / bare-metal токен не сохраняется на диск. | Используйте in-memory `cache` + AppRole `auto_auth` для перелогина; для сохранения токена между рестартами монтируйте `sink "file" { path = "/app/secrets/.vault-token" }` в общий `tmpfs`/bind-volume с `chmod 600`. |

### Очистка и откат изменений

При необходимости удалить развернутые контейнеры и секреты:

```bash
# Остановка и удаление контейнеров, сетей, томов
docker compose down -v

# Удаление именованного тома с секретами (если не используется -v)
docker volume rm <project>_secrets-shared

# Отзыв активных токенов AppRole
vault token revoke -mode=path auth/approle/login

# Уничтожение активных SecretID
vault list auth/approle/role/<role>/secret-id
vault write auth/approle/role/<role>/secret-id/destroy \
  secret_id_accessor="<accessor>"

# Удаление роли (если тестовая)
vault delete auth/approle/role/<role>
```

### Сравнение с нативными Docker Secrets

| Критерий | Docker Secrets (Swarm/Compose) | Vault + Docker |
| :--- | :--- | :--- |
| **Хранение** | Шифрование в Raft (Swarm) или файлы на диске (Compose). | Централизованное хранилище с аудитом и динамической генерацией. |
| **Динамика** | Статические секреты, обновляются вручную. | Краткоживущие секреты (TTL), автоматическая ротация. |
| **Аудит** | Ограниченный (логи Swarm). | Полный аудит всех операций (чтение, запись, аутентификация). |
| **Аутентификация** | На основе TLS-сертификатов узлов. | AppRole, OIDC, Kubernetes, LDAP, mTLS. |
| **Ротация** | Вручную через `docker secret update`. | Автоматически по истечении lease или изменению в Vault. |
| **Масштабирование** | Swarm-кластер. | Любая среда: Docker, Kubernetes, bare metal, VM. |

## Безопасность и сеть

### Рекомендации по безопасности

1.  **Использование tmpfs:** Никогда не сохраняйте расшифрованные секреты на физический диск хоста. Используйте `tmpfs` тома Docker.
2.  **Защита памяти (IPC_LOCK):** Всегда добавляйте `cap_add: [IPC_LOCK]` для контейнера с Vault или Агентом, чтобы предотвратить сброс секретов в swap. В systemd-сервисе используйте `AmbientCapabilities=CAP_IPC_LOCK` и `LimitMEMLOCK=infinity`.
3.  **Маскирование переменных:** В CI/CD пайплайнах помечайте переменные как `masked` или `hidden`.
4.  **Сетевая безопасность:** Даже во внутренней сети Docker (`bridge` или `overlay`) трафик к Vault должен быть зашифрован (TLS). Используйте `ca_cert` в конфигурации агента и отключайте `tls_skip_verify`.
5.  **Права на файлы:** Файлы `role-id` и `secret-id` должны иметь права `0600` и принадлежать пользователю `vault:vault`. В контейнере монтируйте их как `readOnly`.
6.  **Фиксированные версии образов:** Используйте точные теги образов (например, `hashicorp/vault:2.1.1`), а не `latest`, для воспроизводимости развертываний.
7.  **Отключение swap:** На хосте выполните `sudo swapoff -a` или используйте `mlock`, чтобы секреты не попали в swap-раздел.

### Конфигурация слушателя Vault (listener) для Docker

Если Vault развернут на том же хосте, где запускаются контейнеры, настройте `listener` для приема подключений из Docker-сети:

```hcl
# /etc/vault.d/server.hcl
storage "raft" {
  path    = "/vault/data"
  node_id = "vault-node-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/etc/vault.d/tls/vault.crt"
  tls_key_file  = "/etc/vault.d/tls/vault.key"
  tls_client_ca_file = "/etc/vault.d/tls/ca.crt"
}

api_addr     = "https://vault.example.com:8200"
cluster_addr = "https://vault.example.com:8201"
```

### mTLS между агентом и Vault

Для high-security сред настройте двухсторонний TLS (mTLS), чтобы агент аутентифицировался на сервере Vault сертификатом, а не только токеном:

```hcl
vault {
  address     = "https://vault.example.com:8200"
  ca_cert     = "/etc/vault/ca.crt"
  client_cert = "/etc/vault/client.crt"
  client_key  = "/etc/vault/client.key"
  tls_verify  = true
}
```

Сертификаты монтируются в контейнер агента через секреты Docker или bind mount с правами `0400`.

### См. также

*   **[Безопасное управление секретами в Docker](../../Docker/Docker_security/secrets_management.md)** — основной раздел по нативным механизмам Docker (Compose, Swarm, BuildKit).
*   **[Vault Agent: основы](./vault_agent/basics.md)** — детальная настройка шаблонов и Auto-Auth.
*   **[Аутентификация через AppRole](./vault_auth_approle.md)** — детали машинной аутентификации (RoleID/SecretID).
*   **[Vault Agent Sidecar — динамическое обновление конфигурации](./vault_agent/sidecar_pattern.md)** — паттерны sidecar, диагностика и мониторинг.
