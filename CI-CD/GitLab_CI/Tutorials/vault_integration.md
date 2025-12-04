# Практическое руководство: Интеграция GitLab CI с HashiCorp Vault

Хранение секретов (паролей, токенов, ключей) является критически важной частью безопасности CI/CD. Это руководство демонстрирует современный подход к управлению секретами с использованием HashiCorp Vault, интегрированного с GitLab CI. Пайплайны будут получать секреты динамически во время выполнения, не храня их в переменных GitLab.

См. также:
*   [Подробное руководство: Интеграция Vault с GitLab CI на Kubernetes](../Vault/vault_gitlab_integration_kubernetes.md)
*   [GitLab CI как конструктор Workflow](./gitlab_ci_workflow_constructor.md)
*   [Стратегии интеграции GitLab CI с Kubernetes](./gitlab_kubernetes_integration_strategies.md)

---

## Часть 1: Установка и настройка Vault в Kubernetes

Мы развернем Vault в кластере Kubernetes с помощью оператора Banzai Cloud.

### 1.1. Развертывание оператора и Vault
1.  **Добавьте Helm-репозиторий Banzai Cloud:**
    ```bash
    helm repo add banzai-charts https://kubernetes-charts.banzaicloud.com
    helm repo update
    ```
2.  **Установите Vault Operator:**
    ```bash
    helm install vault-operator banzai-charts/vault-operator --create-namespace --namespace vault
    ```
3.  **Создайте манифест для Vault:**
    Создайте файл `vault-instance.yaml` для описания нашего экземпляра Vault. Обратите внимание на `externalConfig`, который настроит Ingress для доступа к UI.

    ```yaml
    # vault-instance.yaml
    apiVersion: vault.banzaicloud.com/v1alpha1
    kind: Vault
    metadata:
      name: vault
    spec:
      size: 1
      image: vault:1.10.3
      bankVaultsConfig:
        externalConfig:
          policies:
            - name: allow_all
              rules: path "*" { policy = "write" }
          auth:
            - type: kubernetes
              roles:
                - name: default
                  bound_service_account_names:
                    - default
                  bound_service_account_namespaces:
                    - "*"
                  policies:
                    - allow_all
                  ttl: 1h
      externalConfig:
        service:
          type: ClusterIP
        ingress:
          enabled: true
          # Замените на ваш домен
          hosts:
            - host: vault.YOUR_STUDENT_ID.example.com 
              paths: [/]
    ```
4.  **Примените манифест:**
    ```bash
    kubectl apply -f vault-instance.yaml -n vault
    ```
    Дождитесь, пока поды Vault перейдут в состояние `Running`.

### 1.2. Получение доступа к Vault
1.  **Получите Root Token:**
    ```bash
    kubectl get secret vault-unseal-keys -n vault -o jsonpath={.data.vault-root} | base64 --decode
    ```
    Сохраните этот токен.
2.  **Войдите в UI:** Откройте в браузере `http://vault.YOUR_STUDENT_ID.example.com` и войдите, используя полученный root-токен.
3.  **Войдите в CLI:** Для удобства дальнейшей настройки получим доступ к поду, в котором уже есть `vault` CLI.
    ```bash
    kubectl exec -n vault -it vault-0 -- /bin/sh
    # Внутри пода
    export VAULT_ADDR=http://127.0.0.1:8200
    # Используйте ваш root токен
    vault login <YOUR_VAULT_ROOT_TOKEN> 
    ```

## Часть 2: Настройка JWT-аутентификации для GitLab

Теперь настроим Vault так, чтобы он доверял токенам, которые генерирует GitLab для своих CI/CD задач.

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
    Роль связывает JWT-токен от GitLab с политикой в Vault на основе атрибутов (claims) токена.
    *   Найдите **Project ID** вашего GitLab проекта (на главной странице проекта).

    ```sh
    # Роль для staging-веток
    vault write auth/jwt/role/my-project-staging \
        role_type="jwt" \
        policies="my-project-staging" \
        bound_claims_type="glob" \
        bound_claims='{"project_id": "YOUR_PROJECT_ID", "ref_type": "branch", "ref": "staging/*"}' \
        user_claim="user_email" \
        ttl="1m"

    # Роль для защищенной main-ветки (production)
    vault write auth/jwt/role/my-project-production \
        role_type="jwt" \
        policies="my-project-production" \
        bound_claims='{"project_id": "YOUR_PROJECT_ID", "ref_type": "branch", "ref": "main", "ref_protected": "true"}' \
        user_claim="user_email" \
        ttl="1m"
    ```
4.  **Настройте JWT Auth Method:**
    Укажите Vault, как проверять подлинность JWT-токенов от вашего GitLab.
    ```sh
    vault write auth/jwt/config jwks_url="https://gitlab.com/-/jwks" bound_issuer="gitlab.com"
    ```
    (Замените `gitlab.com` на адрес вашего self-hosted инстанса, если необходимо).
5.  **Загрузите секреты в Vault:**
    ```sh
    vault kv put secret/my-project/staging db_password="staging_password_123"
    vault kv put secret/my-project/production db_password="production_secret_password_!@#"
    ```

## Часть 3: Настройка `.gitlab-ci.yml`

Теперь настроим пайплайн для получения секрета.

```yaml
stages:
  - get-secrets

get-secrets-job:
  stage: get-secrets
  image: vault:latest # Используем официальный образ Vault
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  script:
    - echo "Branch: $CI_COMMIT_BRANCH, Protected: $CI_COMMIT_BRANCH_PROTECTED"
    
    # Экспортируем переменные для аутентификации в Vault
    - export VAULT_ADDR="http://vault.YOUR_STUDENT_ID.example.com"
    - export VAULT_AUTH_ROLE="my-project-production"
    - export VAULT_JWT_TOKEN="$CI_JOB_JWT_V2_TOKEN" # Используем JWT токен от GitLab
    
    # Аутентификация и чтение секрета
    - vault login -method=jwt -no-print role="$VAULT_AUTH_ROLE" jwt="$VAULT_JWT_TOKEN"
    - export PROD_PASSWORD=$(vault kv get -field=db_password secret/my-project/production)
    
    # Демонстрация того, что секрет получен
    - echo "Successfully fetched production password."
    - echo "The password is: $PROD_PASSWORD"

    # Попытка прочитать секрет, к которому нет доступа
    - echo "Trying to fetch staging password (should fail)..."
    - export STAGING_PASSWORD=$(vault kv get -field=db_password secret/my-project/staging) || echo "Permission denied, as expected."

```

### Пояснения к пайплайну:
-   **`image: vault:latest`**: Используется образ, содержащий CLI для Vault.
-   **`CI_JOB_JWT_V2_TOKEN`**: Это специальная предопределенная переменная, содержащая JWT-токен, который идентифицирует текущую задачу.
-   **`vault login -method=jwt ...`**: Команда для аутентификации в Vault с использованием JWT токена. Vault проверит токен, найдет подходящую роль (на основе Project ID, ветки и т.д.) и выдаст временный токен Vault с привязанными политиками.
-   **`vault kv get ...`**: Команда для чтения секрета. Она будет успешной только в том случае, если политика, привязанная к роли, разрешает доступ к этому пути.

После запуска этого пайплайна на ветке `main` в логах вы увидите, что пароль для `production` был успешно получен, а попытка получить пароль для `staging` завершилась ошибкой "permission denied", что подтверждает корректную работу модели безопасности.
