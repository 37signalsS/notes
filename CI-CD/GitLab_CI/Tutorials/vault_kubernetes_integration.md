# Интеграция GitLab CI и HashiCorp Vault в Kubernetes

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
*   **Автоматизация:** Полная поддержка динамических секретов (базы данных, облачные ключи) с коротким TTL.
*   **Аудит:** Vault логирует каждый вход, привязывая его к конкретному проекту и пользователю GitLab.

## Практические сценарии

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

## Технические нюансы и Безопасность

### Изоляция через Bound Claims
Использование `ref_protected: "true"` гарантирует, что секреты не будут доступны разработчикам в их личных ветках (feature-ветках) без прохождения код-ревью и слияния в защищенную ветку. Это фундаментальный принцип Zero Trust в CI/CD.

### Управление временем жизни (TTL)
Для CI/CD задач рекомендуется устанавливать минимально возможный `token_ttl` (например, 15-30 минут).
*   **Batch Tokens:** В высоконагруженных средах рассмотрите использование `token_type="batch"` для уменьшения нагрузки на базу данных Vault (такие токены не записываются на диск).
*   **Max TTL:** Убедитесь, что `max_ttl` роли не позволяет продлевать токен дольше, чем длится самый долгий пайплайн.

### Аудит и мониторинг
Vault записывает метаданные OIDC в свои аудит-логи. Вы можете отследить, какая именно джоба GitLab (`job_id`) получила конкретный секрет, проанализировав поле `auth.metadata`.

### Работа с Self-hosted GitLab
Если GitLab находится за корпоративным Firewall, Vault должен иметь сетевой доступ к `https://gitlab.example.com/-/jwks`. 
*   При использовании **Self-signed сертификатов** добавьте корневой CA GitLab в доверенное хранилище подов Vault (`/etc/ssl/certs/`).
*   Если сетевой доступ невозможен, ключи JWKS можно настроить статически через `jwt_validation_pubkeys`, но это потребует ручного обновления при ротации ключей в GitLab.

### Проблема Secret Zero
Интеграция через OIDC полностью устраняет необходимость передачи "первого секрета" (например, статического токена Vault) в переменные GitLab. Идентификатором раннера является сам факт его запуска внутри доверенного контекста GitLab.

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

## Дополнительная информация

### Смотрите также

- **[Интеграция Vault с Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md)** — основной SSoT по работе Vault в K8s (VSO, CSI, Injector).
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — подробнее об `id_tokens` и маскировании данных.
- **[Официальная документация GitLab: Vault Integration](https://docs.gitlab.com/ee/ci/secrets/hashicorp_vault.html)**
