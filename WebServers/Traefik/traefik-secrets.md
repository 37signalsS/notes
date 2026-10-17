# Управление секретами в Traefik: Vault, переменные окружения, Kubernetes и Docker

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6; совместимость с v2.11)

---

## Определения

- **Secret Management (Управление секретами)** — совокупность процессов и инструментов для безопасного хранения, доставки, ротации и аудита конфиденциальных данных (паролей, токенов API, приватных ключей TLS, htpasswd-хешей) без их раскрытия в открытом виде в системе контроля версий или логах.
- **Dynamic Configuration Templating** — встроенный в файловый провайдер Traefik (`providers.file`) механизм выполнения шаблонов Go (`text/template`), позволяющий динамически подставлять значения переменных окружения (функция `env`) в момент загрузки или перезагрузки файлов конфигурации.
- **Vault Agent** — легковесный клиентский процесс HashiCorp Vault, предназначенный для аутентификации приложений (через AppRole, TLS-сертификаты или Kubernetes ServiceAccount), управления жизненным циклом токенов и рендеринга шаблонов Consul-Template на локальную файловую систему.
- **Vault PKI ACME Engine** — компонент подсистемы PKI в HashiCorp Vault, реализующий серверный интерфейс протокола ACME (RFC 8555). Позволяет встроенному клиенту ACME в Traefik получать и автоматически продлевать X.509 сертификаты от внутреннего корпоративного CA без установки дополнительных агентов.
- **External Secrets Operator (ESO)** — оператор Kubernetes, осуществляющий одностороннюю синхронизацию секретов из внешних систем (HashiCorp Vault, локальные хранилища) в нативные ресурсы `Secret` кластера Kubernetes (`kubernetes.io/tls`, `kubernetes.io/basic-auth`, `Opaque`).
- **External Account Binding (EAB)** — механизм спецификации ACME (RFC 8555 §7.3.4), связывающий учетную запись ACME-клиента с предварительно созданной учетной записью в центре сертификации при помощи пары идентификатора (`kid`) и криптографического ключа (`hmacKey`).
- **`usersFile`** — директива статической или динамической конфигурации Traefik (в middleware `basicAuth` и `digestAuth`), указывающая абсолютный путь к локальному файлу учетных записей в формате `htpasswd`.
- **tmpfs (RAM-диск)** — временная файловая система Linux, хранящаяся исключительно в оперативной памяти (VFS), используемая для исключения записи расшифрованных секретов на физические диски или swap-разделы.

---

## Базовые концепции и архитектура

### Архитектурный статус: отсутствие нативного провайдера `providers.vault`

> [!IMPORTANT]
> В ядре Traefik **отсутствует** встроенный провайдер вида `providers.vault` и прямой резолвер `certificatesResolvers.<name>.vault`. Попытка указать подобные директивы приводит к фатальной ошибке парсинга конфигурации на этапе запуска: `field not found, node: vault`.

HashiCorp Vault не предоставляет интерфейс распределенного Key-Value хранилища с поддержкой протоколов long-polling или gRPC-stream (в отличие от Consul KV или etcd), а является специализированным сервером криптографии и аудита. По этой причине интеграция Traefik с Vault строится на базе проверенных архитектурных паттернов:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        HashiCorp Vault Cluster                         │
│  ┌────────────────────────┐              ┌──────────────────────────┐  │
│  │   KV v2 Secrets Engine │              │   PKI Engine (ACME API)  │  │
│  └───────────┬────────────┘              └────────────┬─────────────┘  │
└──────────────┼────────────────────────────────────────┼────────────────┘
               │                                        │
     Паттерн A: Push / Render                  Паттерн B: RFC 8555
               │                                        │
  ┌────────────┴────────────┐                           │
  │ Vault Agent / ESO / VSO │                           │
  └────────────┬────────────┘                           │
               ▼                                        ▼
   Локальный файл / K8s Secret             Встроенный ACME Client
  ┌───────────────────────────┐            ┌───────────────────────────┐
  │ /etc/traefik/dynamic/*.yml│            │ certificatesResolvers     │
  │ /run/secrets/users.auth   │            │   .myresolver.acme        │
  └────────────┬──────────────┘            └────────────┬──────────────┘
               │                                        │
               ▼ (providers.file.watch = true)          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       Traefik Core (Data Plane)                        │
│         Dynamic Routing Graph / TLS Termination / Middlewares          │
└────────────────────────────────────────────────────────────────────────┘
```

### Сравнение паттернов доставки секретов

| Паттерн | Область применения | Источник секрета | Механизм обновления в Traefik | Преимущества | Риски / Ограничения |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Go Templating + Env** | Bare-Metal, Systemd, Standalone Docker | Переменные окружения процесса | Перезапуск процесса Traefik | Простота реализации, отсутствие внешних агентов | Секреты видны в окружении процесса; смена требует рестарта |
| **Vault Agent / Daemon** | Bare-Metal, On-Premise VM | HashiCorp Vault (KV v1/v2, PKI) | Файловый вотчер (`providers.file.watch: true`) | Zero-Downtime ротация, автоматическое обновление токенов Vault | Необходимость поддержки локального демона Vault Agent |
| **Vault PKI через ACME** | Внутренние сети, Bare-Metal, On-Premise | HashiCorp Vault PKI ACME endpoint | Встроенный цикл продления ACME (Lego) | Нативная автоматическая ротация сертификатов без сторонних утилит | Требует настройки ACME-адаптера в Vault и доверия к Root CA |
| **External Secrets Operator** | Kubernetes On-Premise | HashiCorp Vault KV | Traefik K8s CRD Provider (отслеживание изменений `Secret`) | Декларативный GitOps, нативная интеграция с RBAC Kubernetes | Задержка синхронизации (`refreshInterval`), накладные расходы на оператор |
| **Docker / Swarm Secrets** | Docker Swarm, Docker Compose | Движок Docker Swarm / Compose | Монтирование в `/run/secrets/` + `usersFile` | Секреты хранятся в памяти контейнера (`tmpfs`), не попадают в образ | Обновление секрета в Swarm требует редеплоя сервиса |

### Жизненный цикл ротации и Hot-Reload

Traefik проектировался для непрерывной маршрутизации входящего трафика. Механизм применения обновленных секретов различается в зависимости от точки монтирования:

1. **Файловый провайдер (`providers.file`):** При изменении файлов в каталоге `directory` механизм inotify генерирует событие файловой системы. Параметр `providersThrottleDuration` (по умолчанию `2s`) группирует серию быстрых записей (debouncing) и выполняет атомарную перекомпиляцию внутреннего графа роутеров без разрыва активных TCP-сессий.
2. **Параметр `usersFile` в `basicAuth` / `digestAuth`:** Файл перечитывается Traefik при каждом обновлении динамической конфигурации, в которую он включен. Если изменен только сам файл на диске без модификации dynamic YAML, Traefik v3 автоматически обнаруживает изменение содержимого файла учетных записей.
3. **Сертификаты ACME:** Встроенный клиент отслеживает дату истечения (`NotAfter`) сертификата в хранилище (файл `acme.json`) и автоматически инициирует ACME-диалог продления за 30 дней до окончания срока действия.
4. **Kubernetes Secrets:** Traefik Kubernetes Provider подписан на события API-сервера через Watch API. При обновлении ресурса `Secret`, на который ссылается `Middleware` или `IngressRoute`, конфигурация роутера обновляется в оперативной памяти без рестарта подов Traefik.

### Модель безопасности и защита от утечек

При эксплуатации Traefik в production-средах действуют жесткие правила изоляции секретов:

- **Исключение аргументов командной строки:** Запрещено передавать секреты через CLI-флаги процесса (например, `--certificatesresolvers.le.acme.eab.hmacencoded=...`), так как аргументы видны любому локальному пользователю через команду `ps aux` и псевдофайловую систему `/proc/<pid>/cmdline`. Секреты должны передаваться исключительно через файл окружения `EnvironmentFile` с правами `0600` или через монтируемые файлы.
- **Хранение в памяти (`tmpfs`):** Все расшифрованные агентами секреты должны генерироваться на RAM-дисках (например, `/run/traefik/secrets/` или `/dev/shm/`), чтобы исключить сохранение конфиденциальных данных на энергонезависимых носителях или в swap-памяти.
- **Фильтрация логов:** По умолчанию Traefik не выводит значения секретов в логи уровня `INFO` и `WARN`. Однако включение уровня `DEBUG` может приводить к раскрытию заголовков запросов. Для защиты журналов доступа необходимо настраивать явное маскирование чувствительных HTTP-заголовков (`Authorization`, `Cookie`, `Proxy-Authorization`).

---

## Практические сценарии и пошаговая настройка

### Сценарий 1: Инъекция переменных окружения и Go-шаблоны (Bare-Metal / Systemd)

Использование встроенного движка Go-шаблонов в `providers.file` для подстановки хеша BasicAuth без фиксации секрета в Git-репозитории.

#### Шаг 1: Подготовка изолированного файла переменных окружения

Создайте файл `/etc/traefik/traefik.env` с ограниченным доступом только для пользователя `traefik`:

```bash
# Генерация надежного bcrypt-хеша пароля для пользователя "admin"
htpasswd -n -b -B -C 10 admin "Secret_Password_2026!"
# → admin:$2y$10$WkL9.sB1...kO8Z0e

# Запись в защищенный файл переменных окружения
sudo bash -c 'cat > /etc/traefik/traefik.env << "EOF"
TRAEFIK_DASHBOARD_AUTH=admin:$2y$10$WkL9.sB12qE5iQv3kO8Z0eq5mK8.P1X...
EOF'

# Установка жестких прав доступа (только чтение владельцем)
sudo chown root:traefik /etc/traefik/traefik.env
sudo chmod 0640 /etc/traefik/traefik.env
```

#### Шаг 2: Настройка Systemd Unit с загрузкой окружения

Отредактируйте сервис `/etc/systemd/system/traefik.service`:

```ini
[Unit]
Description=Traefik Edge Proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=traefik
Group=traefik
EnvironmentFile=/etc/traefik/traefik.env
ExecStart=/usr/local/bin/traefik --configFile=/etc/traefik/traefik.yml
Restart=always
RestartSec=5s

# Изоляция процесса в ОС
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/etc/traefik/acme /var/log/traefik
ReadOnlyPaths=/etc/traefik
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

#### Шаг 3: Динамическая конфигурация с функцией `env`

Создайте динамический файл `/etc/traefik/dynamic/auth-middleware.yml`:

```yaml
http:
  middlewares:
    dashboard-auth:
      basicAuth:
        users:
          - '{{ env "TRAEFIK_DASHBOARD_AUTH" }}'

  routers:
    traefik-dashboard:
      rule: "Host(`traefik.internal.corp`) && (PathPrefix(`/api`) || PathPrefix(`/dashboard`))"
      entryPoints:
        - "websecure"
      service: "api@internal"
      middlewares:
        - "dashboard-auth"
      tls: {}
```

---

### Сценарий 2: HashiCorp Vault Agent как локальный генератор секретов (Bare-Metal / VM)

Надежный паттерн для On-Premise инфраструктуры: Vault Agent локально проходит аутентификацию по методу AppRole, непрерывно поддерживает валидность токена и рендерит секреты в динамическую директорию Traefik на RAM-диске.

```
┌─────────────────┐  AppRole Auth (RoleID/SecretID)   ┌─────────────────┐
│                 │ ────────────────────────────────► │                 │
│                 │ ◄──────────────────────────────── │ HashiCorp Vault │
│   Vault Agent   │  Lease Token & KV v2 Data         │   (On-Premise)  │
│                 │                                   └─────────────────┘
│  Render Engine  │
└────────┬────────┘
         │ Атомарная запись на RAM-диск (tmpfs)
         ▼
 ┌──────────────────────────────────────┐
 │ /run/traefik/dynamic/vault-auth.yml  │ ◄─── Traefik providers.file (inotify watch)
 │ /run/traefik/certs/upstream.key      │
 └──────────────────────────────────────┘
```

#### Шаг 1: Настройка политики и роли в HashiCorp Vault

Выполните на сервере Vault:

```bash
# Создание политики доступа к секретам Traefik
vault policy write traefik-ingress - <<'EOF'
path "kv/data/production/traefik/*" {
  capabilities = ["read"]
}
EOF
# → Success! Uploaded policy: traefik-ingress

# Создание роли AppRole с ограниченным TTL токена
vault write auth/approle/role/traefik-agent \
    secret_id_ttl=8760h \
    token_ttl=1h \
    token_max_ttl=4h \
    token_policies="traefik-ingress"
# → Success! Data written to: auth/approle/role/traefik-agent

# Получение RoleID и генерация SecretID
vault read -field=role_id auth/approle/role/traefik-agent/role-id > /tmp/role_id
vault write -f -field=secret_id auth/approle/role/traefik-agent/secret-id > /tmp/secret_id

# Добавление секрета BasicAuth в хранилище KV v2
vault kv put kv/production/traefik/auth \
    htpasswd_admin="admin:$2y$10$e8wY8b4l5nQv6sP7t8u9v.1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o"
# → Key              Value
# → ---              -----
# → created_time     2026-10-17T20:45:00Z
```

#### Шаг 2: Конфигурация Vault Agent на сервере Traefik

Разместите RoleID и SecretID в `/etc/vault-agent/`:

```bash
sudo mkdir -p /etc/vault-agent /run/traefik/dynamic
sudo chown -R vault:vault /etc/vault-agent
sudo chmod 0700 /etc/vault-agent
```

Создайте конфигурацию `/etc/vault-agent/agent.hcl`:

```hcl
pid_file = "/run/vault-agent.pid"

vault {
  address = "https://vault.internal.corp:8200"
  ca_cert = "/etc/ssl/certs/corporate-root-ca.pem"
}

auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path   = "/etc/vault-agent/role_id"
      secret_id_file_path = "/etc/vault-agent/secret_id"
      remove_secret_id_file_after_reading = false
    }
  }

  sink "file" {
    config = {
      path = "/run/vault-agent/vault-token"
      mode = 0600
    }
  }
}

template {
  destination = "/run/traefik/dynamic/vault-auth.yml"
  perms       = 0640
  contents    = <<EOF
http:
  middlewares:
    vault-basic-auth:
      basicAuth:
        users:
          {{ with secret "kv/data/production/traefik/auth" }}
          - "{{ .Data.data.htpasswd_admin }}"
          {{ end }}
EOF
}
```

#### Шаг 3: Настройка статической конфигурации Traefik для чтения из tmpfs

В `/etc/traefik/traefik.yml`:

```yaml
providers:
  file:
    directory: "/run/traefik/dynamic"
    watch: true
```

При ротации секрета в Vault демон Vault Agent автоматически обновит файл в `/run/traefik/dynamic/vault-auth.yml`, а Traefik мгновенно применит новый пароль без перезапуска процесса.

---

### Сценарий 3: Интеграция Traefik с Vault PKI через ACME (RFC 8555)

HashiCorp Vault версии 1.4+ умеет выступать в роли ACME-сервера для встроенного PKI Secrets Engine. Traefik использует свой нативный ACME-резолвер для автоматического заказа и ротации внутренних TLS-сертификатов.

#### Шаг 1: Настройка ACME в Vault PKI

Выполните на сервере HashiCorp Vault:

```bash
# Включение и первичная настройка промежуточного PKI
vault secrets enable -path=pki_int pki
vault secrets tune -max-lease-ttl=8760h pki_int

# Настройка URL кластера для AIA
vault write pki_int/config/cluster \
    path="https://vault.internal.corp:8200/v1/pki_int" \
    aia_path="https://vault.internal.corp:8200/v1/pki_int"

# Создание роли выпуска сертификатов
vault write pki_int/roles/internal-services \
    allowed_domains="internal.corp,*.internal.corp" \
    allow_subdomains=true \
    max_ttl=720h \
    require_cn=false

# Включение ACME интерфейса с привязкой к созданной роли
vault write pki_int/config/acme \
    enabled=true \
    default_directory_policy="role:internal-services" \
    eab_policy="always-required" \
    allowed_roles="internal-services"
# → Success! Data written to: pki_int/config/acme

# Генерация учетных данных EAB (External Account Binding) для Traefik
vault write -f pki_int/acme/new-eab
# → Key          Value
# → ---          -----
# → hmac_key     k9Z7x...P4q1
# → id           c2d847b2-11e2-45a1-9a7f-09e87b643210
```

#### Шаг 2: Настройка статической конфигурации Traefik

В `/etc/traefik/traefik.yml`:

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: "websecure"
          scheme: "https"
  websecure:
    address: ":443"

certificatesResolvers:
  vault-internal-ca:
    acme:
      email: "sre-alerts@internal.corp"
      # Точка входа ACME-каталога Vault PKI
      caServer: "https://vault.internal.corp:8200/v1/pki_int/acme/directory"
      storage: "/etc/traefik/acme/vault-pki.json"
      tlsChallenge: {}
      # Параметры EAB, выданные Vault
      eab:
        kid: "c2d847b2-11e2-45a1-9a7f-09e87b643210"
        hmacEncoded: "k9Z7x...P4q1"
```

> [!TIP]
> Чтобы Traefik доверял CA-серверу Vault при HTTPS-рукопожатии с эндпоинтом ACME, корневой сертификат корпоративного CA должен быть добавлен в системное доверенное хранилище ОС (`update-ca-certificates` в Debian/Ubuntu или `update-ca-trust` в RHEL) либо передан через переменную окружения `LEGO_CA_CERTIFICATES=/etc/ssl/certs/corporate-root-ca.pem`.

#### Шаг 3: Маршрутизация с автоматическим сертификатом

В динамической конфигурации `/etc/traefik/dynamic/services.yml`:

```yaml
http:
  routers:
    billing-api:
      rule: "Host(`billing.internal.corp`)"
      entryPoints:
        - "websecure"
      service: "billing-service"
      tls:
        certResolver: "vault-internal-ca"

  services:
    billing-service:
      loadBalancer:
        servers:
          - url: "http://10.20.30.40:8080"
```

---

### Сценарий 4: Kubernetes On-Premise: External Secrets Operator (ESO) + Traefik Middleware

В Kubernetes-кластерах на Bare-Metal секреты синхронизируются из внешнего Vault в стандартные `Secret` Kubernetes с помощью ESO, после чего подключаются к ресурсам Traefik CRD.

```
┌─────────────────────┐
│ HashiCorp Vault     │
│ (kv/data/k8s/auth)  │
└──────────┬──────────┘
           │ Vault Kubernetes Auth
           ▼
┌────────────────────────────────────────────────────────┐
│ External Secrets Operator (ClusterSecretStore)         │
│ Synchronizes secret every 1h (refreshInterval)         │
└──────────────────────────┬─────────────────────────────┘
                           │ Creates / Updates
                           ▼
┌────────────────────────────────────────────────────────┐
│ Kubernetes Secret: "edge-admin-credentials"            │
│ namespace: traefik                                     │
│ data.users: base64(admin:$2y$10$...)                   │
└──────────────────────────┬─────────────────────────────┘
                           │ References via spec.basicAuth.secret
                           ▼
┌────────────────────────────────────────────────────────┐
│ Traefik CRD: Middleware (basicAuth)                    │
│ Traefik watches Secret events via K8s API              │
└────────────────────────────────────────────────────────┘
```

#### Шаг 1: Определение ClusterSecretStore и ExternalSecret

```yaml
# cluster-secret-store.yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: onprem-vault
spec:
  provider:
    vault:
      server: "https://vault.internal.corp:8200"
      path: "kv"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "traefik-ingress-controller"
          serviceAccountRef:
            name: eso-service-account
            namespace: external-secrets
---
# external-secret-traefik-auth.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: edge-admin-credentials
  namespace: traefik
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onprem-vault
  target:
    name: edge-admin-credentials
    creationPolicy: Owner
  data:
    - secretKey: users
      remoteRef:
        key: k8s/production/traefik
        property: htpasswd_content
```

#### Шаг 2: Подключение секрета к Traefik Middleware

```yaml
# middleware-auth.yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: edge-basic-auth
  namespace: traefik
spec:
  basicAuth:
    # Имя Kubernetes Secret, созданного ESO
    secret: edge-admin-credentials
---
# ingressroute-secure.yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: secure-app
  namespace: traefik
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`admin.internal.corp`)
      kind: Rule
      middlewares:
        - name: edge-basic-auth
          namespace: traefik
      services:
        - name: internal-dashboard-svc
          port: 8080
  tls:
    secretName: internal-corp-wildcard-tls
```

---

### Сценарий 5: Docker Swarm и Standalone Compose Secrets

В Docker Compose и Swarm секреты монтируются ядром контейнеризации в виртуальную файловую систему `tmpfs` по пути `/run/secrets/<secret_name>` с правами только на чтение.

#### Пример для `docker-compose.yml`:

```yaml
services:
  traefik:
    image: traefik:v3.6
    restart: always
    command:
      - "--providers.file.directory=/etc/traefik/dynamic"
      - "--providers.file.watch=true"
      - "--entrypoints.websecure.address=:443"
    ports:
      - "443:443"
    volumes:
      - /etc/traefik/dynamic:/etc/traefik/dynamic:ro
    secrets:
      - basic_auth_users
      - server_tls_cert
      - server_tls_key

secrets:
  basic_auth_users:
    file: ./secrets/users.htpasswd
  server_tls_cert:
    file: ./secrets/tls.crt
  server_tls_key:
    file: ./secrets/tls.key
```

Динамическая конфигурация `/etc/traefik/dynamic/tls-and-auth.yml`:

```yaml
http:
  middlewares:
    swarm-auth:
      basicAuth:
        # Прямое указание смонтированного файла секрета Docker
        usersFile: "/run/secrets/basic_auth_users"

  routers:
    app-router:
      rule: "Host(`secure.internal.corp`)"
      entryPoints:
        - "websecure"
      service: "app-service"
      middlewares:
        - "swarm-auth"

tls:
  certificates:
    - certFile: "/run/secrets/server_tls_cert"
      keyFile: "/run/secrets/server_tls_key"
```

---

## Операции и диагностика

### Команды генерации и проверки секретов

```bash
# 1. Генерация безопасного bcrypt-хеша для BasicAuth (рекомендуемая задержка Cost=10)
htpasswd -n -b -B -C 10 monitoring_agent "Sup3rS3cur3P@ss"
# → monitoring_agent:$2y$10$7Z...xY.

# 2. Проверка соответствия пароля ранее сгенерированному htpasswd-хешу
echo "Sup3rS3cur3P@ss" | htpasswd -v -b -B /etc/traefik/auth/users.htpasswd monitoring_agent
# → Password for user monitoring_agent correct.

# 3. Аудит прав доступа к файлам секретов Traefik на локальном узле
stat -c "%a %U:%G %n" /etc/traefik/traefik.env /etc/traefik/acme/acme.json /run/secrets/*
# → 640 root:traefik /etc/traefik/traefik.env
# → 600 traefik:traefik /etc/traefik/acme/acme.json
# → 400 traefik:traefik /run/secrets/basic_auth_users

# 4. Проверка командной строки запущенного процесса Traefik на факт случайной утечки секретов
tr '\0' '\n' < /proc/$(pgrep -o traefik)/cmdline | grep -E "token|pass|secret|key"
# → (Вывод должен быть абсолютно пустым. Если обнаружены токены — немедленно удалите их из CLI флагов)

# 5. Проверка доступности ACME-директории Vault PKI через локальный cURL с валидацией CA
curl -s --cacert /etc/ssl/certs/corporate-root-ca.pem \
     https://vault.internal.corp:8200/v1/pki_int/acme/directory | jq .
# → {
# →   "newAccount": "https://vault.internal.corp:8200/v1/pki_int/acme/new-account",
# →   "newNonce": "https://vault.internal.corp:8200/v1/pki_int/acme/new-nonce",
# →   "newOrder": "https://vault.internal.corp:8200/v1/pki_int/acme/new-order"
# → }

# 6. Проверка статуса синхронизации секрета в Kubernetes через External Secrets Operator
kubectl get externalsecret edge-admin-credentials -n traefik -o wide
# → NAME                     STORE          REFRESH   STATUS         READY
# → edge-admin-credentials   onprem-vault   1h        SecretSynced   True

# 7. Декодирование содержимого созданного секрета Kubernetes для контроля формата
kubectl get secret edge-admin-credentials -n traefik -o jsonpath="{.data.users}" | base64 -d
# → admin:$2y$10$WkL9.sB12qE5iQv3kO8Z0eq5mK8.P1X...
```

---

## Устранение неисправностей

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **HTTP 401 Unauthorized на любые учетные данные в BasicAuth** | 1. Символ `$` в хеше интерпретирован оболочкой или Docker Compose как переменная.<br>2. Формат хеша не поддерживается (MD5/SHA1 вместо bcrypt/apr1). | Изучите логи Traefik: `grep -i "basicauth" /var/log/traefik/traefik.log`. Наличие строки `password does not match` или `malformed entry`. | В файлах Docker Compose экранируйте знак доллара двойным символом `$$` (например, `admin:$$2y$$10$$...`). Генерируйте хеши через `htpasswd -B` (bcrypt). |
| **Traefik не видит изменения в `usersFile`** | Символическая ссылка (symlink) была перезаписана текстовым редактором с изменением inode без генерации inotify modify event. | Проверьте inode файла: `ls -i /etc/traefik/auth/users.htpasswd` до и после редактирования. | При использовании атомарной перезаписи файлов направляйте уведомление или перезаписывайте содержимое потоком: `cat new.txt > users.htpasswd` (сохраняет inode). |
| **Ошибка ACME: `acme: error: 400 :: urn:ietf:params:acme:error:externalAccountRequired`** | Сервер Vault PKI настроен с политикой `eab_policy="always-required"`, но в `traefik.yml` отсутствуют параметры `eab.kid` / `eab.hmacEncoded`. | В логе Traefik: `Error while renewing certificate from ACME: external account binding required`. | Сгенерируйте токен EAB в Vault командой `vault write -f pki/acme/new-eab` и пропишите `kid` и `hmacEncoded` в блок резолвера. |
| **ACME не может верифицировать сертификат Vault: `x509: certificate signed by unknown authority`** | Внутренний CA Vault подписан локальным центром сертификации, отсутствующим в доверенном хранилище Go-рантайма Traefik. | Лог Traefik содержит: `Get "https://vault.../directory": x509: certificate signed by unknown authority`. | Передайте путь к корневому сертификату через переменную окружения `LEGO_CA_CERTIFICATES=/path/to/ca.crt` в сервисе Traefik либо добавьте CA в доверенные ОС (`update-ca-certificates`). |
| **ExternalSecret находится в статусе `SecretSyncedError`** | 1. Истек срок действия Vault Token/AppRole SecretID.<br>2. Указан неверный путь к ключу в Vault KV v2 (пропущен префикс `data/`). | Выполните `kubectl describe externalsecret <name> -n traefik`. В секции Status изучите поле `Message`. | Для KV v2 в настройках ESO убедитесь, что параметр `version: "v2"` активен, а в `remoteRef.key` указан правильный путь без избыточного сегмента `data/`. Обновите SecretID в кластере. |
| **Утечка секретов в журналы доступа access.log** | Трафик содержит токен авторизации или пароль в строке запроса (Query Params) либо заголовке `Authorization`. | Запустите поиск по access-логу: `grep -E "Bearer|basic" /var/log/traefik/access.log`. | Настройте фильтрацию полей в статической конфигурации: задайте `accesslog.fields.headers.names: Authorization: drop` и используйте `keep` только для безопасных заголовков. |

---

## Рекомендации и Best Practices

1. **Никогда не коммитьте секреты в Git:** Все пароли, приватные ключи, токены и htpasswd-файлы должны быть внесены в `.gitignore`. В репозитории хранятся исключительно шаблоны конфигураций с плейсхолдерами (`.example`).
2. **Принцип минимальных привилегий в Vault:** Токены и роли AppRole, выделяемые для Traefik или Vault Agent, должны иметь права исключительно на операцию `read` на строго определенные пути (`path "kv/data/production/traefik/*"`). Запрещайте права `write`, `delete` и доступ к корню хранилища.
3. **Безопасное хранение локальных файлов (`0600` / `0400`):** Файлы `acme.json`, сертификаты и файлы `usersFile` должны принадлежать системному пользователю `traefik:traefik` с правами доступа `chmod 0600` (чтение/запись только владельцу) или `chmod 0400` (только чтение). Traefik аварийно завершает работу, если права на `acme.json` превышают `0600`.
4. **Размещение в RAM (tmpfs):** При использовании связок с внешними агентами (Vault Agent, Consul-Template) монтируйте директорию вывода секретов как файловую систему в оперативной памяти (`tmpfs`). Это предотвратит утечку конфиденциальных данных на диск при создании резервных копий дисковых томов.
5. **Маскирование в логах доступа:** В production-средах всегда явно настраивайте секцию `accessLog` для исключения логирования конфиденциальных заголовков:
   ```yaml
   accessLog:
     filePath: "/var/log/traefik/access.log"
     format: "json"
     fields:
       defaultMode: keep
       headers:
         defaultMode: keep
         names:
           Authorization: drop
           Cookie: drop
           Set-Cookie: drop
           X-Auth-Token: drop
   ```
6. **Регулярная ротация и аудит токенов:** Токены Vault для агентов должны создаваться с ограниченным сроком жизни (TTL 1-4 часа) и механизмом регулярного продления (renewable). Настройте мониторинг времени жизни токенов через Prometheus метрики Vault.

---

## Дополнительная информация

- [Обзор архитектуры Traefik](./traefik_overview.md) — точки входа, провайдеры конфигурации и жизненный цикл роутинга.
- [Провайдеры распределенных KV-хранилищ](./traefik-providers-kv-stores.md) — интеграция с Consul KV, etcd, Redis и ZooKeeper.
- [Безопасность и Middleware](./traefik-middlewares-security.md) — детальная настройка BasicAuth, DigestAuth, ForwardAuth и IP-фильтрации.
- [Интеграция с cert-manager и Let's Encrypt](./traefik-cert-manager-ingressroute-tls.md) — управление сертификатами в Kubernetes через IngressRoute.
- [TLS Options и mTLS](./traefik-tls-options.md) — настройка шифрования, взаимной аутентификации и доверенных Root CA.
- [Харденинг безопасности Traefik](./traefik-security-hardening.md) — рекомендации по изоляции процессов, CIS benchmarks и защите сети.
- [Интеграция Vault Agent в Kubernetes](../../Vault/guides/vault_agent/injector.md) — автоматическое внедрение секретов через Webhook.
- [Sidecar-паттерн Vault Agent](../../Vault/guides/vault_agent/sidecar_pattern.md) — организация sidecar-контейнеров для ротации учетных данных.
- [Vault PKI и cert-manager](../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/vault_integration.md) — выпуск внутренних сертификатов через Vault Issuer.
