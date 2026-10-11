# Интеграция GitLab CI и HashiCorp Vault в Kubernetes

**Актуально для:** GitLab 17.0+, Vault 1.15+, Kubernetes 1.27+

## Определения

**OIDC (OpenID Connect)** — протокол идентификации на базе OAuth 2.0. GitLab выступает в роли OIDC-провайдера, генерируя кратковременные подписанные JWT-токены для каждой задачи пайплайна.

**`id_tokens`** — современный механизм GitLab (стандарт с v17.0+), заменивший устаревший `CI_JOB_JWT`. Позволяет генерировать токены с настраиваемой аудиторией (`aud`), что является обязательным требованием безопасности для современных OIDC-интеграций в 2026 году.

**JWT Auth Method** — метод аутентификации в [HashiCorp Vault](../../../Vault/overview.md), позволяющий внешним системам проходить проверку подлинности на основе проверки цифровой подписи JSON Web Token.

**JWKS (JSON Web Key Set)** — набор публичных ключей, которые OIDC-провайдер (GitLab) публикует по адресу `/-/jwks`. Vault использует эти ключи для проверки подлинности JWT, выданного GitLab.

**Workload Identity Federation (WIF)** — концепция федерации личностей, позволяющая рабочим нагрузкам (workloads) в Kubernetes получать доступ к ресурсам (в данном случае к Vault) без использования статических паролей, основываясь на доверии между провайдером личности (GitLab) и потребителем (Vault).

**Vault Secrets Operator (VSO)** — официальный оператор от HashiCorp (стандарт 2026 года), предназначенный для нативной синхронизации секретов Vault в объекты `Secret` Kubernetes или их прямого внедрения в поды. В контексте CI/CD позволяет автоматизировать доставку секретов в окружения.

**Bound Claims** — набор ограничений в роли Vault (например, `project_id`, `ref`, `namespace_path`), гарантирующий, что токен будет принят только от конкретного проекта или ветки GitLab, предотвращая несанкционированный доступ из других репозиториев.

## Основные концепции

### Цепочка доверия (Zero Trust Workflow)

Интеграция исключает использование долгоживущих статических токенов (Secret Zero) за счет динамического подтверждения личности раннера:

1.  **Генерация:** GitLab создает уникальный JWT для задачи, подписывает его закрытым ключом и передает в среду выполнения как `id_token`.
2.  **Аутентификация:** Задача пайплайна (через CLI или нативную интеграцию) отправляет этот JWT в Vault API (`auth/jwt/login`).
3.  **Валидация:** Vault обращается к GitLab по эндпоинту `/-/jwks`, скачивает публичные ключи и проверяет подлинность подписи JWT.
4.  **Проверка Claims:** Vault сопоставляет метаданные токена (Claims) с правилами, описанными в `bound_claims` роли.
5.  **Авторизация:** При успешной проверке Vault выдает задаче временный токен доступа с правами, определенными политикой (Policy).

### Структура JWT-токена GitLab
Для настройки точных ограничений необходимо понимать содержимое Claims, которые передает GitLab:
*   `iss` (Issuer): URL инстанса GitLab (например, `https://gitlab.com`).
*   `sub` (Subject): Уникальный идентификатор джобы (например, `job_12345`).
*   `aud` (Audience): Целевая аудитория, настраивается в `.gitlab-ci.yml`.
*   `project_id`: Числовой ID проекта.
*   `namespace_path`: Полный путь к группе/проекту (например, `my-org/backend/api-service`).
*   `ref`: Ветка или тег (например, `main`, `v1.2.0`).
*   `ref_protected`: Флаг `true`, если ветка/тег является защищенным.
*   `environment`: Имя окружения в GitLab.

### Преимущества подхода OIDC
*   **Безопасность:** Отсутствие "вечных" секретов в переменных GitLab.
*   **Гранулярность:** Возможность ограничить доступ к секретам на уровне окружения (`environment`) или защищенности ветки.
*   **Автоматизация:** Полная поддержка динамических секретов (базы данных, внешние системы) с коротким TTL.
*   **Аудит:** Vault логирует каждый вход, привязывая его к конкретному проекту и пользователю GitLab.

## Практические сценарии

### Предварительные требования

**Инфраструктура:**
- **Kubernetes:** Кластер версии 1.27+ с доступом через `kubectl`.
- **Vault:** Версия 1.15+ (HA-кластер с Raft рекомендуется для production).
- **GitLab:** Версия 17.0+ (для поддержки `id_tokens`).
- **Helm:** Версии 3.12+ для управления чартами.
- **DNS:** Vault должен быть доступен по имени `vault.example.com` из подов Kubernetes и из GitLab Runner'ов.

**Переменные CI/CD (Settings > CI/CD > Variables):**
| Переменная | Тип | Назначение |
| :--- | :--- | :--- |
| `VAULT_ADDR` | Variable | URL Vault сервера (например, `https://vault.example.com`). |
| `VAULT_AUTH_ROLE` | Variable | Имя роли JWT-аутентификации в Vault. |
| `SSH_PRIVATE_KEY` | **File** | Приватный ключ для доступа к серверу Vault (если Self-hosted). |

**Базовые знания:**
- Основы HashiCorp Vault: политики, роли, KV v2.
- Основы Kubernetes: Deployment, Service, Secret, RBAC.
- Основы GitLab CI/CD: stages, variables, id_tokens.

### Шаг 1: Развертывание Vault в Kubernetes

В 2026 году стандартом является использование официального Helm-чарта `hashicorp/vault` с включенным Injector и VSO.

 1.  **Установка через Helm:**
     ```bash
     helm repo add hashicorp https://helm.releases.hashicorp.com
     helm install vault hashicorp/vault \
       --namespace vault --create-namespace \
       --set "injector.enabled=true" \
       --set "server.ha.enabled=true" \
       --set "server.ha.raft.enabled=true"
     ```

     **Валидация:**
     ```bash
     kubectl get pods -n vault -l app.kubernetes.io/name=vault
     kubectl get svc -n vault
     kubectl exec -n vault vault-0 -- vault status -format=json | jq '.cluster_id, .sealed, .ha_enabled'
     ```

 2.  **Альтернатива: Bank-Vaults Operator**
     Если требуется глубокая декларативная настройка через Custom Resources, используйте Bank-Vaults:
     ```yaml
     # vault-instance.yaml (фрагмент конфигурации JWT)
     auth:
       - type: jwt
         config:
           jwks_url: "https://gitlab.example.com/-/jwks"
           bound_issuer: "https://gitlab.example.com"
     ```

### Шаг 2: Настройка JWT-аутентификации (CLI)

Выполните настройку на стороне сервера Vault для установления доверия с GitLab.

1.  **Включение метода и привязка к JWKS:**
    ```bash
    vault auth enable jwt

    vault write auth/jwt/config \
        jwks_url="https://gitlab.example.com/-/jwks" \
        bound_issuer="https://gitlab.example.com"
    ```

2.  **Создание политики доступа:**
    ```bash
    vault policy write gitlab-app-policy - <<EOF
    path "secret/data/projects/my-app/common" { capabilities = ["read"] }
    path "secret/data/projects/my-app/production/*" { capabilities = ["read"] }
    EOF
    ```

3.  **Создание роли с гранулярными ограничениями:**
    Использование `namespace_path` предотвращает доступ из других групп в рамках одного инстанса GitLab.

    ```bash
    vault write auth/jwt/role/gitlab-prod-role \
        role_type="jwt" \
        policies="gitlab-app-policy" \
        token_ttl="15m" \
        bound_claims_type="glob" \
        bound_claims='{
            "namespace_path": "my-org/backend/api-service",
            "ref_protected": "true",
            "ref": "main",
            "environment": "production"
        }' \
        user_claim="user_email"
    ```

     **Валидация:**
     ```bash
     vault read auth/jwt/role/gitlab-prod-role
     vault policy read gitlab-app-policy
     ```

### Шаг 3: Интеграция с Vault Secrets Operator (VSO)

VSO позволяет CI/CD пайплайну не только читать секреты, но и управлять их жизненным циклом в кластере.

1.  **Синхронизация секрета для приложения:**
    Пайплайн может создать (через Helm или kubectl) ресурс `VaultStaticSecret`, который VSO превратит в нативный Kubernetes Secret.

    ```yaml
    apiVersion: secrets.hashicorp.com/v1beta1
    kind: VaultStaticSecret
    metadata:
      name: my-app-db-secret
    spec:
      mount: secret
      type: kv-v2
      path: projects/my-app/production/db
      refreshAfter: 1h
      destination:
        name: db-credentials # Имя секрета в K8s
        create: true
    ```

     **Валидация:**
     ```bash
     kubectl apply -f vault-static-secret.yaml -n <namespace>
     kubectl get vaultstaticsecret -n <namespace>
     kubectl get secret db-credentials -n <namespace>
     kubectl logs -l app.kubernetes.io/name=vault-secrets-operator -n vault --tail=50
     ```

 2.  **Преимущество:** Приложение в K8s работает с нативным Secret, а VSO обеспечивает его ротацию без участия GitLab Runner.

### Шаг 4: Настройка GitLab CI пайплайна

С версии 17.0+ используется нативная интеграция, которая автоматически маскирует секреты в логах.

**`.gitlab-ci.yml`:**
```yaml
variables:
  VAULT_ADDR: "https://vault.example.com"
  VAULT_AUTH_ROLE: "gitlab-prod-role"

deploy_production:
  stage: deploy
  image: alpine:latest
  id_tokens:
    # Генерация OIDC токена. aud должен совпадать с bound_issuer в Vault
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  secrets:
    # Автоматическая подстановка секрета в переменную DB_PASSWORD
    DB_PASSWORD:
      vault: secret/data/projects/my-app/db_config/password@secret
      token: $VAULT_ID_TOKEN
  script:
    - echo "Выполняется деплой..."
    # Переменная $DB_PASSWORD доступна и замаскирована в выводе
    - ./deploy.sh --pass $DB_PASSWORD
  rules:
    - if: $CI_COMMIT_BRANCH == "main" && $CI_COMMIT_REF_PROTECTED == "true"
  tags: [docker-runner]
```

**Сценарий с использованием CLI (для сложной логики):**
```yaml
get_secrets_cli:
  image: hashicorp/vault:latest
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=$VAULT_AUTH_ROLE jwt=$VAULT_ID_TOKEN)
    - vault kv get -format=json secret/projects/my-app/db_config > secrets.json
    ```

     **Валидация:**
     ```bash
     # В логах пайплайна ищите:
     # - Masked variables: DB_PASSWORD
     # - Job succeeded
     kubectl get pods -n <namespace> -l app=my-app
     vault token lookup $VAULT_TOKEN | jq '.data.policies, .data.lease_duration'
     ```

 ## Технические нюансы и Безопасность

### Изоляция через Bound Claims
Использование `ref_protected: "true"` гарантирует, что секреты не будут доступны разработчикам в их личных ветках (feature-ветках) без прохождения код-ревью и слияния в защищенную ветку. Это фундаментальный принцип Zero Trust в CI/CD.

### Управление временем жизни (TTL)
Для CI/CD задач рекомендуется устанавливать минимально возможный `token_ttl` (например, 15-30 минут).
*   **Batch Tokens:** В высоконагруженных средах рассмотрите использование `token_type="batch"` для уменьшения нагрузки на базу данных Vault (такие токены не записываются на диск).
*   **Max TTL:** Убедитесь, что `max_ttl` роли не позволяет продлевать токен дольше, чем длится самый долгий пайплайн.
### Аудит и мониторинг

Vault записывает метаданные OIDC в свои аудит-логи. Вы можете отследить, какая именно джоба GitLab (`job_id`) получила конкретный секрет, проанализировав поле `auth.metadata`.

#### Интеграция аудита Vault с GitLab Audit Events

Для полной трассируемости доступа к секретам сопоставьте аудит-логи Vault с событиями GitLab:

1.  **Vault Audit Log (JSON):** Включите JSON-аудит в Vault:
    ```bash
    vault audit enable file file_path=/var/log/vault/audit.log log_format=json
    ```
    В логах ищите поля:
    - `auth.metadata.job_id` — ID задачи GitLab.
    - `auth.metadata.project_path` — путь проекта GitLab.
    - `auth.metadata.ref` — ветка/тег.
    - `auth.metadata.namespace_path` — группа/пространство имен GitLab.

2.  **GitLab Audit Events:** Включите аудит доступа к переменным и CI/CD в `Settings > CI/CD > Audit events`.

3.  **Корреляция:** Сопоставляйте события по `job_id` и `project_path`. Это позволяет ответить на вопросы:
    - Какая задача получила секрет `secret/prod/db`?
    - Кто запустил задачу (автор MR/push)?
    - Из какой ветки был запущен?

**Пример корреляции:**
```bash
# Vault audit log (JSON)
grep "secret/data/projects/my-app/production/db" /var/log/vault/audit.log | jq '.auth.metadata'

# → {"job_id": "12345", "project_path": "my-org/backend/api-service", "ref": "main", "namespace_path": "my-org/backend"}

# GitLab audit event
grep "12345" /var/log/gitlab/audit_json.log | jq '.details'

# → {"job_id": 12345, "pipeline_id": 456, "user": "deploy-bot", "action": "run_job"}
```

#### Архитектура GitLab Runner

Для production-сред GitLab Runner рекомендуется разворачивать на выделенных узлах Kubernetes с использованием **Kubernetes Executor**. Это обеспечивает изоляцию задач, автоматическое масштабирование и короткий жизненный цикл подов.

```yaml
# values.yaml для gitlab-runner Helm-чарта
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "ubuntu:22.04"
        privileged = false
        cpu_limit = "1000m"
        memory_limit = "2Gi"
        service_account = "gitlab-runner"
        namespace = "gitlab-runners"
        poll_interval = 5
        cache_dir = "/cache"
```

**Важно для SRE:** Используйте отдельный ServiceAccount для раннера с минимальными привилегиями. Настройте NetworkPolicy, разрешающую только egress к GitLab API, Vault и реестру контейнеров.

#### Мониторинг и алертинг

Экспортируйте метрики Vault в Prometheus и настройте алерты:

```bash
# В конфигурации Vault (config.hcl):
telemetry {
  prometheus_retention_time = "30s"
  disable_hostname = true
}
```

**Ключевые алерты:**
- `VaultSealed` — кластер Vault находится в sealed-состоянии дольше 60 секунд
- `VaultHighTokenCount` — количество активных токенов превышает порог
- `VaultJWTValidationErrors` — ошибки валидации JWT от GitLab
- `GitLabRunnerDown` — раннер недоступен для задач
- `VaultStaticSecretDesync` — VSO не может синхронизировать секрет

#### Инцидент-респонс

При подозрении на компрометацию секретов:
1.  Отзовите все токены роли: `vault write -f auth/jwt/role/<role>/token/revoke`
2.  Проверьте аудит-лог Vault на предмет неавторизованного доступа: `vault audit list`
3.  Ротация секретов в Vault через `vault kv metadata put` с новыми версиями
4.  Проверьте, что compromised токены больше не валидны через `vault token lookup`

#### Аудит доступа

Проводите регулярный аудит политик Vault и ролей JWT:
```bash
# Список всех политик
vault policy list

# Проверка, какие политики привязаны к роли JWT
vault read auth/jwt/role/gitlab-prod-role

# Аудит секретов проекта
vault kv list secret/data/projects/my-app/
```

### Работа с Self-hosted GitLab
Если GitLab находится за корпоративным Firewall, Vault должен иметь сетевой доступ к `https://gitlab.example.com/-/jwks`. 
*   При использовании **Self-signed сертификатов** добавьте корневой CA GitLab в доверенное хранилище подов Vault (`/etc/ssl/certs/`).
*   Если сетевой доступ невозможен, ключи JWKS можно настроить статически через `jwt_validation_pubkeys`, но это потребует ручного обновления при ротации ключей в GitLab.

### Проблема Secret Zero
Интеграция через OIDC полностью устраняет необходимость передачи "первого секрета" (например, статического токена Vault) в переменные GitLab. Идентификатором раннера является сам факт его запуска внутри доверенного контекста GitLab.

#### Практические рекомендации sysadmin

**Бэкап и восстановление:**
- Регулярно создавайте снапшоты Raft: `vault operator raft snapshot save /backup/vault-$(date +%F).db`
- Храните recovery keys и unseal keys в sекретаре вне кластера (например, на защищённом хосте или в физическом сейфе)
- Тестируйте восстановление из снапшота на стенде не реже одного раза в квартал

**Жизненный цикл раннера:**
- Ротируйте регистрационные токены GitLab Runner: `gitlab-runner verify --delete-runners` и повторная регистрация
- Настраивайте `concurrent` и `limit` в `config.toml` для контроля параллелизма
- Используйте `request_concurrency` для предотвращения DDOS-подобных нагрузок на Vault

**Доступ и комплаенс:**
- Ведите реестр ролей JWT и политик Vault (например, в защищённом wiki или as-code в репозитории)
- Назначайте минимум привилегий (least privilege) на уровне Bound Claims и политик
- Периодически пересматривайте `bound_claims` — удаляйте неиспользуемые роли

## Устранение неисправностей (Troubleshooting)

### Отладка JWT-токена
Если вы получаете `403 Forbidden`, первым шагом проверьте содержимое токена, который генерирует GitLab:
1.  Временно добавьте `echo $VAULT_ID_TOKEN | cut -d. -f2 | base64 -d` в скрипт пайплайна (осторожно: это раскроет Claims в логах).
2.  Скопируйте вывод на `jwt.io` и проверьте, совпадают ли значения `project_id`, `namespace_path` и `ref` с тем, что ожидается в `bound_claims` роли Vault.

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **403: permission denied** | Несоответствие Bound Claims | Проверьте `namespace_path` и `ref`. Убедитесь, что используется `bound_claims_type="glob"` для масок. |
| **Claim "iss" is invalid** | Несовпадение `bound_issuer` | Убедитесь, что в конфигурации Vault указан точный URL GitLab (включая https и отсутствие слеша в конце). |
| **JWKS fetch failed** | Vault не видит GitLab по сети | Проверьте DNS и Firewall внутри пода Vault. Используйте `kubectl exec vault-0 -- curl -v https://gitlab.example.com/-/jwks`. |
| **Token audience mismatch** | `aud` не совпадает | Значение `aud` в `.gitlab-ci.yml` должно строго совпадать с настроенным `audience` в Vault. |
| **Secret injection failed** | Ошибка в пути секрета | Проверьте, что в пути указано `data/` (для KV-V2) и правильный mount point (например, `@secret`). |
| **Vault is sealed** | Vault находится в sealed-состоянии | Выполните `vault operator unseal` на каждом ноде кластера (минимум 3 ключа для HA). |
| **ServiceAccount не найден** | Неверный namespace или имя SA в Vault | Проверьте: `vault read auth/kubernetes/role/<role>`. Убедитесь, что `bound_service_account_names` и `bound_service_account_namespaces` совпадают. |
| **VSO не обновляет секрет** | Ошибка в VaultStaticSecret CR | Проверьте логи: `kubectl logs -l app.kubernetes.io/name=vault-secrets-operator`. Состояние CR: `kubectl get vaultstaticsecrets -A`. |
| **Certificate verify failed** | Self-signed сертификат Vault | Добавьте CA Vault в доверенное хранилище GitLab Runner или используйте `VAULT_CACERT` в переменных окружения. |
| **Lease not found** | Динамический секрет истёк | Проверьте TTL роли: `vault read auth/jwt/role/<role>`. Увеличьте `token_ttl` или используйте `renewable=true`. |
| **Permission denied (VSO)** | VaultAuth CR не привязан к роли | Убедитесь, что `vaultConnectionRef`, `mount` и `role` в VaultAuth совпадают с настройками Vault. |
| **CI_JOB_JWT deprecated** | Используется устаревший токен | Замените `CI_JOB_JWT` на `id_tokens` (стандарт с v17.0+). Старый токен удалён в GitLab 18.0. |
| **Vault high latency** | Перегрузка Vault или сетевые задержки | Проверьте `vault status` и метрики. Увеличьте ресурсы пода Vault. Для CI/CD используйте batch tokens. |
| **GitLab Runner permission denied** | У Runner нет доступа к Vault namespace или SA | Проверьте RBAC: `kubectl auth can-i list pods --as=system:serviceaccount:gitlab-runners:gitlab-runner`. |
| **Token lookup failed** | Токен истёк или был отозван | JWT-токены CI/CD короткоживущие. Убедитесь, что пайплайн не кэширует `VAULT_TOKEN` между stages. |
| **Vault static secret drift** | Секрет в K8s устарел | Проверьте `refreshAfter` в VaultStaticSecret CR. Убедитесь, что VSO имеет сетевой доступ к Vault API. |

## Лучшие практики (Best Practices)

**Безопасность:**
- Используйте Bound Claims с `ref_protected: "true"` — секреты должны быть доступны только из защищённых веток (main, release/*).
- Никогда не передавайте статические токены Vault через переменные GitLab — используйте OIDC или JWT Auth Method.
- Включите аудит Vault: `vault audit enable file file_path=/var/log/vault/audit.log`.
- Регулярно ротируйте ключи JWKS в GitLab (автоматически каждые 90 дней).
- Используйте `token_ttl` не более 30 минут для CI/CD задач.

**Производительность:**
- Используйте `token_type="batch"` для высоконагруженных сред — batch tokens не записываются на диск.
- Кэшируйте секреты на стороне приложения, но не дольше TTL токена.
- Для VSO настройте `refreshAfter` не чаще 1 раза в час — избегайте нагрузки на Vault.
- Используйте KV v2 вместо KV v1 — поддержка версионирования и rollback.

**Надёжность:**
- Разверните Vault в HA-режиме (минимум 3 ноды для Raft) — это обеспечивает отказоустойчивость.
- Настройте `max_ttl` роли в соответствии с длительностью самого долгого пайплайна.
- Используйте `backup` для Raft: `vault operator raft snapshot save backup.db`.
- Тестируйте интеграцию в staging перед продакшеном.
- Настройте PodDisruptionBudget для Vault: `minAvailable: 2` для HA-кластера из 3 реплик.
- Используйте Liveness и Readiness probes для пода Vault с соответствующими порогами (`initialDelaySeconds`, `failureThreshold`).

**Мониторинг:**
- Экспортируйте метрики Vault в Prometheus: `vault telemetry { prometheus_retention_time = "30s" }`.
- Мониторьте количество активных токенов: `vault token lookup -format=json | jq '.data.num_uses'`.
- Настраивайте алерты на sealed Vault и failed login attempts.
- Мониторьте доступность GitLab Runner'ов через Prometheus exporter или встроенные метрики GitLab.
- Ведите SLO на доступность Vault API (например, 99.9% uptime для `GET /v1/sys/health`).

## Очистка и откат (Cleanup)

**Отзыв токена Vault (если скомпрометирован):**
```bash
# Отзыв конкретного токена по accessor
vault token revoke -accessor <token_accessor>

# Отзыв всех токенов роли
vault write -f auth/jwt/role/<role>/token/revoke

# Полная очистка сессий
vault token revoke -accessor $(vault token lookup -format=json | jq -r '.data.accessor')
```

**Удаление роли JWT-аутентификации:**
```bash
# Удаление роли
vault delete auth/jwt/role/<role>

# Отключение метода аутентификации
vault auth disable jwt/

# Удаление политики
vault policy delete gitlab-app-policy
```

**Откат VSO-ресурсов:**
```bash
# Удаление VaultStaticSecret
kubectl delete vaultstaticsecret <name> -n <namespace>

# Откат через Helm
helm rollback vault-secrets-operator -n vault

# Остановка оператора
helm uninstall vault-secrets-operator -n vault
```

**Очистка GitLab CI/CD:**
```bash
# Удаление переменных Vault через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/variables/VAULT_ADDR"

# Удаление всех секретов проекта из Vault
vault kv delete -versions=0 secret/projects/<project-path>/
```

## Граничные случаи (Edge Cases)

**Несколько Kubernetes-кластеров:**
- Используйте разные `bound_service_account_namespaces` в роли Vault для каждого кластера.
- Или создайте отдельные роли Vault для каждого кластера с уникальными Bound Claims.

**Vault Namespaces (Enterprise):**
- В Vault Enterprise используйте `namespace` в URL: `VAULT_NAMESPACE=team-a`.
- Bound Claims должны включать `namespace_path` GitLab для изоляции между командами.

**Мульти-Tenant GitLab:**
- Для нескольких инстансов GitLab (self-hosted + gitlab.com) настройте разные `bound_issuer` в разных ролях Vault.
- Используйте `bound_claims_type="glob"` для масок: `"namespace_path": "my-org/*"`.

**Работа с dockertless Runner'ами:**
- Если GitLab Runner работает на Kubernetes Executor, OIDC-токен доступен напрямую в поде.
- Если Runner на Docker Executor — пробросьте `VAULT_ADDR` как переменную окружения.

**Высокая нагрузка:**
- При >100 задачах в минуту используйте `token_type="batch"` и увеличьте `max_ttl`.
- Настройте `vault telemetry` для мониторинга latency JWT-валидации.

**Версионирование Vault:**
- При обновлении Vault (например, 1.14 → 1.15) выполняйте `vault operator migrate` перед обновлением.
- Не пропускайте major-версии — миграции могут быть несовместимы.

**Восстановление после сбоя (Disaster Recovery):**
- Поддерживайте SLA на восстановление Vault: RTO < 30 минут, RPO < 5 минут.
- Храните снапшоты Raft в объектном хранилище или на отдельном физическом носителе.
- Автоматизируйте процесс unseal через Ansible или HashiCorp Sentinel при разворачивании нового кластера.

**Аудит и соответствие (Compliance):**
- Включите audit device в Vault для соответствия SOC2/PCI-DSS: `vault audit enable file file_path=/var/log/vault/audit.log`
- Настройте log rotation для audit-логов (logrotate или аналоги).
- Регулярно проверяйте, что `bound_claims` актуальны и не содержат устаревших путей проектов.

**Сеть и DNS:**
- Используйте внутренний DNS (CoreDNS) для разрешения `vault.vault.svc.cluster.local` внутри кластера.
- Настройте NetworkPolicy для namespace `vault`, разрешающую только необходимые порты (8200, 8201).
- Проверяйте egress-правила для раннеров: они должны иметь доступ к GitLab API и Vault API.

## Дополнительная информация

### Смотрите также

- **[Интеграция Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md)** — основной SSoT по работе Vault в K8s (VSO, CSI, Injector, Sidecar).
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — подробнее об `id_tokens`, маскировании и OIDC.
- **[Vault Agent Injector](../../../Vault/guides/vault_agent/injector.md)** — автоматическое внедрение sidecar для секретов.
- **[Zero Trust Architecture](../../../Vault/zero_trust.md)** — принципы Zero Trust в управлении секретами.
- **[ArgoCD + Vault Integration](../../../GitOps/ArgoCD/argocd_vault_integration.md)** — синхронизация секретов через ArgoCD.
- **[Официальная документация GitLab: Vault Integration](https://docs.gitlab.com/ee/ci/secrets/hashicorp_vault.html)**
