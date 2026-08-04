# Интеграция GitLab CI и HashiCorp Vault в Kubernetes

## Надежность и актуальность

- **Оценка надежности:** 10 (SSoT + Современные практики GitLab 17.x)
- **Триггеры обновления:** Удаление поддержки `CI_JOB_JWT` в GitLab 18.0, выход мажорных версий Bank-Vaults Operator, изменения в API Vault KV-V2.

## Определения

**OIDC (OpenID Connect)** — протокол идентификации на базе OAuth 2.0. GitLab выступает в роли OIDC-провайдера, подписывая временные токены для задач пайплайна.

**`id_tokens`** — современная замена переменной `CI_JOB_JWT`. Позволяет декларировать аудиторию (aud) и настраивать claims для безопасной аутентификации в Vault. Подробнее см. **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)**.

**JWT Auth Method** — метод аутентификации в [HashiCorp Vault](../../../Vault/overview.md), позволяющий внешним системам проходить проверку подлинности на основе подписи JSON Web Token.

**Bank-Vaults Operator** — Kubernetes-оператор, автоматизирующий деплой, инициализацию и конфигурацию Vault. Обеспечивает автоматическое распечатывание (unseal) через облачные KMS или K8s-секреты.

## Основные концепции

Процесс интеграции строится на цепочке доверия:

1. **Генерация токена:** GitLab создает уникальный подписанный JWT для каждой задачи (блок `id_tokens`).
2. **Аутентификация:** CI-задача отправляет этот токен в Vault.
3. **Валидация:** Vault скачивает публичные ключи GitLab через эндпоинт JWKS (`/-/jwks`) и проверяет подпись токена.
4. **Проверка Claims:** Vault сравнивает данные токена (ID проекта, ветка, статус защиты) с правилами, описанными в `bound_claims` роли.
5. **Выдача токена Vault:** При соответствии условий Vault выдает задаче временный токен доступа с правами, определенными политикой (Policy).

## Практические сценарии

### Шаг 1: Деплой Vault через Bank-Vaults Operator

Использование оператора позволяет декларативно описать не только сам Vault, но и его первоначальную настройку.

1. **Установка оператора:**

    ```bash
    helm repo add banzai-charts https://kubernetes-charts.banzaicloud.com
    helm repo update
    helm install vault-operator banzai-charts/vault-operator --namespace vault --create-namespace
    # → STATUS: deployed
    ```

2. **Применение манифеста экземпляра Vault (`vault-instance.yaml`):**

    ```yaml
    apiVersion: vault.banzaicloud.com/v1alpha1
    kind: Vault
    metadata:
      name: vault
    spec:
      size: 1
      image: vault:1.17.0 # Актуальная стабильная версия
      bankVaultsConfig:
        externalConfig:
          policies:
            - name: gitlab-readonly
              rules: path "secret/data/projects/*" { capabilities = ["read"] }
          auth:
            - type: jwt
              config:
                # Для self-hosted замените на ваш домен
                jwks_url: "https://gitlab.com/-/jwks"
                bound_issuer: "gitlab.com"
    ```
    `kubectl apply -f vault-instance.yaml -n vault`

### Шаг 2: Инициализация и получение Root Token

После деплоя оператор автоматически инициализирует Vault и сохраняет ключи в K8s Secret (если не настроен KMS).

1. **Извлечение токена:**
    ```bash
    VAULT_ROOT_TOKEN=$(kubectl get secret vault-unseal-keys -n vault -o jsonpath='{.data.vault-root}' | base64 --decode)
    echo "Vault Root Token: $VAULT_ROOT_TOKEN"
    # → Vault Root Token: hvs.CAES...
    ```

2. **Проверка статуса внутри пода:**
    ```bash
    kubectl exec -n vault -it vault-0 -- /bin/sh
    
    # Внутри пода:
    export VAULT_ADDR=http://127.0.0.1:8200
    vault login $VAULT_ROOT_TOKEN
    # → Success! You are now authenticated.
    vault status
    # → Key             Value
    # → ---             -----
    # → Sealed          false
    ```

### Шаг 3: Настройка JWT-аутентификации для GitLab

Если вы настраиваете Vault вручную (без блока `externalConfig` оператора), выполните следующие команды.

1. **Включение метода и создание политики:**
    ```bash
    vault auth enable jwt
    
    vault policy write gitlab-project-policy - <<EOF
    path "secret/data/projects/my-app/*" {
      capabilities = ["read"]
    }
    EOF
    ```

2. **Создание роли с жесткими Bound Claims:**
    Роль связывает проект GitLab с политикой Vault.

    ```bash
    vault write auth/jwt/role/my-project-prod \
        role_type="jwt" \
        policies="gitlab-project-policy" \
        token_ttl="10m" \
        bound_claims='{"project_id": "YOUR_PROJECT_ID", "ref_protected": "true", "ref": "main"}' \
        user_claim="user_email"
    # → Success! Data written to: auth/jwt/role/my-project-prod
    ```

3. **Запись секретов:**
    ```bash
    vault kv put secret/projects/my-app/db_config password="super-secret-pass"
    ```

### Шаг 4: Настройка GitLab CI пайплайна

С версии **GitLab 17.0** рекомендуется использовать нативную интеграцию через ключ `secrets`.

```yaml
# .gitlab-ci.yml
variables:
  VAULT_ADDR: "https://vault.example.com"
  VAULT_AUTH_ROLE: "my-project-prod"

deploy_production:
  stage: deploy
  image: alpine:latest
  id_tokens:
    # Генерируем современный OIDC токен
    VAULT_ID_TOKEN:
      aud: https://vault.example.com # Должно совпадать с bound_issuer или aud в Vault
  secrets:
    # Автоматическая инъекция секрета в переменную DB_PASSWORD
    DB_PASSWORD:
      vault: secret/data/projects/my-app/db_config/password@secret
      token: $VAULT_ID_TOKEN
  script:
    - echo "Развертывание приложения..."
    # GitLab автоматически маскирует $DB_PASSWORD в логах
    - ./deploy.sh --pass $DB_PASSWORD
  rules:
    - if: $CI_COMMIT_BRANCH == "main" && $CI_COMMIT_REF_PROTECTED == "true"
```

**Альтернатива (через CLI):** Если вам нужна сложная логика обработки секретов.
```yaml
get_secrets_cli:
  image: vault:latest
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - vault login -method=jwt role=$VAULT_AUTH_ROLE jwt=$VAULT_ID_TOKEN
    - vault kv get -format=json secret/projects/my-app/db_config > secrets.json
```

## Технические нюансы и Безопасность

### Изоляция через Bound Claims

**Критически важно:** Никогда не создавайте роль без `project_id`. В противном случае любой пользователь вашего инстанса GitLab сможет получить ваши секреты, создав свой проект и указав имя вашей роли.
- `ref_protected: "true"` — гарантирует, что секреты доступны только в ветках, где код прошел ревью и защищен от изменений рядовыми разработчиками.

### Доступ к JWKS в Self-Hosted средах

Если GitLab находится за Firewall, Vault должен иметь сетевой доступ к эндпоинту `/-/jwks`. Если вы используете самоподписанные сертификаты:
1. Добавьте CA в системное хранилище пода Vault.
2. Или укажите публичные ключи GitLab статически через параметр `jwt_validation_pubkeys` (не рекомендуется из-за сложности ротации).

### Проблема Secret Zero

Интеграция через JWT/OIDC полностью решает проблему "первого секрета". Раннеру не нужно передавать пароли для входа в Vault — его личность подтверждается цифровой подписью GitLab.

## Дополнительная информация

### Смотрите также

- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — основы работы с чувствительными данными.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — настройка Агента и CI/CD Tunnel.
- **[Обзор HashiCorp Vault](../../../Vault/overview.md)** — архитектура и движки секретов.
- **[Официальная документация GitLab: Vault Integration](https://docs.gitlab.com/ee/ci/secrets/hashicorp_vault.html)**
