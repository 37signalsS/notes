### Определения

- **Аутентификация по JWT (JWT Auth Method)**: Метод аутентификации в [HashiCorp Vault](../../Vault/overview.md), который позволяет внешним системам, таким как GitLab, проходить аутентификацию с помощью стандарта JSON Web Token (JWT).
- **OpenID Connect (OIDC)**: Протокол идентификации на базе OAuth 2.0. Подробнее см. в [OpenID Connect (OIDC)](../../../Security/Concepts/authentication_vs_authorization.md#протоколы-и-стандарты). GitLab может выступать в роли OIDC-провайдера.
- **`CI_JOB_JWT_V2_TOKEN`**: Предопределенная переменная в GitLab CI, которая содержит короткоживущий, OIDC-совместимый JWT-токен. Этот токен уникален для каждой CI/CD-задачи и содержит набор "заявлений" (`claims`), описывающих контекст выполнения (ID проекта, имя ветки, тип ссылки и т.д.).

### Основные концепции

1. **Генерация токена**: Для каждой запущенной CI/CD-задачи GitLab генерирует уникальный JWT-токен и помещает его в переменную `CI_JOB_JWT_V2_TOKEN`.
2. **Аутентификация в Vault**: CI-задача отправляет этот токен в Vault, используя метод аутентификации JWT.
3. **Валидация токена**: Vault получает токен и выполняет проверку его подлинности. Для этого он обращается по публичному адресу (`JWKS URL`) GitLab, чтобы получить ключ, которым был подписан токен.
4. **Проверка привязок (Claims)**: После подтверждения подлинности Vault анализирует "заявления" (`claims`) внутри токена. В Vault заранее настраиваются **роли**, которые связывают определенный набор `claims` с **политиками доступа**.
5. **Выдача токена Vault**: Если `claims` из JWT соответствуют условиям, заданным в роли (например, `project_id`, `ref_type: branch`, `ref: main`), Vault генерирует и возвращает CI-задаче новый, короткоживущий **токен Vault**.
6. **Получение секрета**: CI-задача использует полученный токен Vault для выполнения запросов к секретам. Политики, привязанные к роли, строго ограничивают, какие именно секреты может читать или изменять данная задача.

### Практические сценарии

#### Настройка интеграции GitLab CI и Vault в Kubernetes

##### Шаг 1: Развертывание Vault в Kubernetes

Мы развернем Vault с помощью [**Helm**](../../Kubernetes/ToolsUtilities/helm_overview.md) и [**Bank-Vaults Operator**](https://bank-vaults.dev/).

1. **Добавьте Helm-репозиторий и установите оператор:**

    ```bash
    helm repo add banzai-charts https://kubernetes-charts.banzaicloud.com
    helm repo update
    helm install vault-operator banzai-charts/vault-operator --create-namespace --namespace vault
    ```

2. **Создайте и примените манифест для экземпляра Vault:**
    Создайте файл `vault-instance.yaml`. `externalConfig` настроит [Ingress](../../Kubernetes/Networking/Ingress/overview.md) для доступа к UI. Замените `vault.your-domain.com` на ваш домен.

    ```yaml
    # vault-instance.yaml
    apiVersion: vault.banzaicloud.com/v1alpha1
    kind: Vault
    metadata:
      name: vault
    spec:
      size: 1
      image: vault:1.10.3 # Рекомендуется использовать актуальную версию
      bankVaultsConfig:
        externalConfig:
          policies:
            - name: allow_all
              rules: path "*" { policy = "write" } # Демо-политика. В production используйте строгие политики.
          auth:
            - type: kubernetes
              roles:
                - name: default
                  bound_service_account_names: ["default"]
                  bound_service_account_namespaces: ["*"]
                  policies: ["allow_all"]
                  ttl: 1h
      externalConfig:
        service:
          type: ClusterIP
        ingress:
          enabled: true
          hosts:
            - host: vault.your-domain.com # <-- ЗАМЕНИТЬ НА ВАШ ДОМЕН
              paths: [/]
    ```

    ```bash
    kubectl apply -f vault-instance.yaml -n vault
    ```

3. **Получите Root Token и войдите в Vault:**
    Этот токен нужен для первоначальной настройки.

    ```bash
    # Получаем токен
    VAULT_ROOT_TOKEN=$(kubectl get secret vault-unseal-keys -n vault -o jsonpath='{.data.vault-root}' | base64 --decode)
    echo "Vault Root Token: $VAULT_ROOT_TOKEN"

    # Подключаемся к поду для выполнения команд
    kubectl exec -n vault -it vault-0 -- /bin/sh

    # Внутри пода:
    export VAULT_ADDR=http://127.0.0.1:8200
    vault login $VAULT_ROOT_TOKEN
    vault status
    ```

##### Шаг 2: Настройка JWT-аутентификации для GitLab

Настроим Vault так, чтобы он доверял токенам от GitLab.

1. **Включите метод JWT-аутентификации:**

    ```sh
    vault auth enable jwt
    ```

2. **Настройте конечную точку JWT:**
    Укажите Vault, как проверять подлинность JWT-токенов от вашего GitLab.

    ```sh
    # Для gitlab.com
    vault write auth/jwt/config jwks_url="https://gitlab.com/-/jwks" bound_issuer="gitlab.com"
    # Для self-hosted GitLab замените gitlab.com на адрес вашего инстанса
    ```

3. **Создайте политики доступа:**
    Политики определяют, к каким путям в Vault будет доступ.

    ```sh
    # Политика для staging (только чтение)
    vault policy write my-project-staging - <<EOF
    path "secret/data/my-project/staging" {
      capabilities = ["read"]
    }
    EOF

    # Политика для production (только чтение)
    vault policy write my-project-production - <<EOF
    path "secret/data/my-project/production" {
      capabilities = ["read"]
    }
    EOF
    ```

4. **Создайте роли:**
    Роль связывает JWT-токен от GitLab с политикой в Vault на основе `claims`.
    *Найдите **Project ID** вашего GitLab проекта (на главной странице проекта).*

    ```sh
    # Роль для любых веток, начинающихся со "staging/"
    vault write auth/jwt/role/my-project-staging \
        role_type="jwt" \
        policies="my-project-staging" \
        bound_claims_type="glob" \
        bound_claims='{"project_id": "YOUR_PROJECT_ID", "ref_type": "branch", "ref": "staging/*"}' \
        user_claim="user_email" \
        ttl="5m"

    # Роль для защищенной ветки 'main' (production)
    vault write auth/jwt/role/my-project-production \
        role_type="jwt" \
        policies="my-project-production" \
        bound_claims='{"project_id": "YOUR_PROJECT_ID", "ref_type": "branch", "ref": "main", "ref_protected": "true"}' \
        user_claim="user_email" \
        ttl="5m"
    ```

5. **Загрузите тестовые секреты:**

    ```sh
    vault kv put secret/my-project/staging db_password="staging_password_123"
    vault kv put secret/my-project/production db_password="!production_secret_@#$"
    ```

##### Шаг 3: Настройка `.gitlab-ci.yml` для получения секретов

```yaml
stages:
  - get-secrets

# Эта задача будет выполняться только для защищенной ветки 'main'
get-production-secrets:
  stage: get-secrets
  image: vault:latest # Используем официальный образ Vault с CLI
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" && $CI_COMMIT_BRANCH_PROTECTED == "true"'
  script:
    - echo "Fetching secrets for production from branch: $CI_COMMIT_BRANCH..."
    
    # Указываем адрес нашего Vault
    - export VAULT_ADDR="http://vault.your-domain.com"
    
    # Аутентификация в Vault с помощью JWT токена от GitLab
    # Vault вернет временный токен с политикой 'my-project-production'
    - vault login -method=jwt -no-print \
        role="my-project-production" \
        jwt="$CI_JOB_JWT_V2_TOKEN"
    
    # Чтение секрета
    - export PROD_PASSWORD=$(vault kv get -field=db_password secret/my-project/production)
    
    # Демонстрация того, что секрет получен
    - echo "Successfully fetched production password."
    # - echo "The password is: $PROD_PASSWORD" # В реальных пайплайнах так делать не стоит!

    # Попытка прочитать секрет, к которому нет доступа (завершится ошибкой)
    - echo "Trying to fetch staging password (should fail)..."
    - vault kv get -field=db_password secret/my-project/staging || echo "Permission denied, as expected."
```

После запуска этого пайплайна на ветке `main` в логах вы увидите, что пароль для `production` был успешно получен, а попытка получить пароль для `staging` завершилась ошибкой **permission denied**, что подтверждает корректную работу модели безопасности.

### Дополнительная информация

- **Безопасность `bound_claims`**: Поле `bound_claims` является ключевым для безопасности. Всегда указывайте как минимум `project_id`, чтобы гарантировать, что токен не будет использован из другого проекта. Дополнительные `claims` (`ref`, `ref_type`, `ref_protected`) усиливают гранулярность доступа.
- **Аудит с `user_claim`**: Поле `user_claim="user_email"` указывает Vault использовать email пользователя, инициировавшего пайплайн, в качестве идентификатора для логов аудита. Это упрощает отслеживание, кто именно получил доступ к секрету.
- **Helm-чарты Vault**: В данном руководстве используется оператор от Banzai Cloud. Существует также официальный Helm-чарт от HashiCorp (`hashicorp/vault`), который является более предпочтительным для новых установок, так как поддерживается непосредственно разработчиками Vault.
- **Self-Hosted GitLab**: При использовании собственного экземпляра GitLab не забудьте заменить `https://gitlab.com` на ваш домен в параметре `jwks_url` и `bound_issuer` при настройке JWT-аутентификации.
