# Практическое руководство: Интеграция GitLab CI с HashiCorp Vault в Kubernetes

## 1. Основные концепции

Интеграция основана на механизме аутентификации **JWT (JSON Web Token)**.
1.  Для каждой задачи GitLab CI генерирует уникальный, короткоживущий токен (`CI_JOB_JWT_V2_TOKEN`), содержащий атрибуты (claims) о проекте, ветке и т.д.
2.  [**HashiCorp Vault**](../../Vault/overview.md) настраивается для доверия этим токенам.
3.  На основе атрибутов токена Vault выдает временный собственный токен с привязанной политикой, которая разрешает доступ только к строго определенным секретам.

---

## 2. Часть 1: Развертывание Vault в Kubernetes

Мы развернем Vault в [**кластере Kubernetes**](../../Kubernetes/kubernetes_overview.md) с помощью [**Helm**](../../Kubernetes/ToolsUtilities/helm_overview.md) и [**Operator**](../../Kubernetes/Concepts/kubernetes_operators.md).

### 2.1. Развертывание оператора и Vault

1.  **Добавьте Helm-репозиторий Banzai Cloud:**
    ```bash
    helm repo add banzai-charts https://kubernetes-charts.banzaicloud.com
    helm repo update
    ```
2.  **Установите Vault Operator:**
    Это создаст оператор в отдельном [namespace](../../Kubernetes/Base/namespace.md) `vault`.
    ```bash
    helm install vault-operator banzai-charts/vault-operator --create-namespace --namespace vault
    ```
3.  **Создайте манифест для экземпляра Vault:**
    Создайте файл `vault-instance.yaml`. `externalConfig` настроит [Ingress](../../Kubernetes/Networking/ingress.md) для доступа к UI. Замените `vault.your-domain.com` на ваш домен.

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
            # Для простоты примера создаем политику с полным доступом.
            # В реальных проектах используйте более строгие политики.
            - name: allow_all
              rules: path "*" { policy = "write" }
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
4.  **Примените манифест:**
    ```bash
    kubectl apply -f vault-instance.yaml -n vault
    ```
    Дождитесь, пока под `vault-0` перейдет в состояние `Running`.

### 2.2. Получение доступа к Vault

1.  **Получите Root Token:**
    Этот токен нужен для первоначальной настройки. Извлекается он из [секрета Kubernetes](../../Kubernetes/Base/secret.md).
    ```bash
    kubectl get secret vault-unseal-keys -n vault -o jsonpath='{.data.vault-root}' | base64 --decode
    ```
    **Надежно сохраните этот токен!**
2.  **Войдите в UI и CLI:**
    *   **UI:** Откройте в браузере `http://vault.your-domain.com` и войдите, используя полученный root-токен.
    *   **CLI:** Для удобства дальнейшей настройки подключитесь к поду Vault.
    ```bash
    kubectl exec -n vault -it vault-0 -- /bin/sh
    # Внутри пода:
    export VAULT_ADDR=http://127.0.0.1:8200
    vault login <YOUR_VAULT_ROOT_TOKEN> # Используйте ваш root токен
    vault status # Проверьте статус
    ```

---

## 3. Часть 2: Настройка JWT-аутентификации для GitLab

Настроим Vault так, чтобы он доверял токенам, которые генерирует GitLab.

1.  **Включите метод JWT-аутентификации:**
    ```sh
    vault auth enable jwt
    ```
2.  **Создайте политики доступа:**
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
3.  **Создайте роли:**
    Роль связывает JWT-токен от GitLab с политикой в Vault на основе атрибутов (`claims`) токена.
    *   Найдите **Project ID** вашего GitLab проекта (на главной странице проекта).

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
    *`bound_claims`* — ключевое поле, которое гарантирует, что только задачи из определенного проекта и ветки получат доступ.

4.  **Настройте конечную точку JWT:**
    Укажите Vault, как проверять подлинность JWT-токенов от вашего GitLab.
    ```sh
    # Для gitlab.com
    vault write auth/jwt/config jwks_url="https://gitlab.com/-/jwks" bound_issuer="gitlab.com"
    # Для self-hosted GitLab замените gitlab.com на адрес вашего инстанса
    ```
5.  **Загрузите и проверьте секреты:**
    ```sh
    vault kv put secret/my-project/staging db_password="staging_password_123"
    vault kv put secret/my-project/production db_password="!production_secret_@#$"

    # Проверка
    vault kv get -field=db_password secret/my-project/production
    ```

---

## 4. Часть 3: Настройка `.gitlab-ci.yml`

```yaml
stages:
  - get-secrets

# Этот job будет выполняться только для защищенной ветки 'main'
get-production-secrets:
  stage: get-secrets
  image: vault:latest # Используем официальный образ Vault с CLI
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" && $CI_COMMIT_BRANCH_PROTECTED == "true"'
  script:
    - echo "Branch: $CI_COMMIT_BRANCH, Protected: $CI_COMMIT_BRANCH_PROTECTED"
    - echo "Fetching secrets for production..."
    
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
    - echo "The password is: $PROD_PASSWORD" # В реальных пайплайнах так делать не стоит!

    # Попытка прочитать секрет, к которому нет доступа (завершится ошибкой)
    - echo "Trying to fetch staging password (should fail)..."
    - vault kv get -field=db_password secret/my-project/staging || echo "Permission denied, as expected."

```

### Пояснения к пайплайну:
-   **`image: vault:latest`**: Используется готовый образ, содержащий CLI для Vault.
-   **`CI_JOB_JWT_V2_TOKEN`**: Специальная переменная GitLab, содержащая OIDC-совместимый JWT-токен, который идентифицирует текущую задачу.
-   **`vault login -method=jwt ...`**: Команда для безопасной аутентификации. Vault проверит токен, найдет подходящую роль (`my-project-production`) и выдаст временный токен Vault с привязанными к ней политиками.
-   **`vault kv get ...`**: Команда для чтения секрета. Она будет успешной только в том случае, если политика разрешает доступ к этому пути.

После запуска этого пайплайна на ветке `main` в логах вы увидите, что пароль для `production` был успешно получен, а попытка получить пароль для `staging` завершилась ошибкой **permission denied**, что подтверждает корректную работу модели безопасности.
