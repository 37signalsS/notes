# Переменные и секреты GitLab CI/CD

## Определения

*   **Переменные CI/CD** — динамические значения, используемые для управления логикой пайплайна, конфигурацией окружений и передачи параметров между задачами.
*   **Защищенная переменная (`Protected`)** — доступна только в пайплайнах, запущенных для защищенных веток или тегов. Основной механизм защиты продуктовых секретов.
*   **Маскированная переменная (`Masked`)** — значение скрывается в логах (`[MASKED]`). С версии **18.3** применяется автоматически ко всем новым переменным. Требование: минимум 8 символов, отсутствие пробелов.
*   **Скрытая переменная (`Hidden`)** — значение полностью скрыто в интерфейсе и логах. После сохранения просмотр невозможен даже администраторам.
*   **Переменная типа `File`** — содержимое записывается во временный файл на Runner, переменная хранит путь к нему. Идеально для SSH-ключей и сертификатов.
*   **Сырая переменная (`Raw`)** — переменная, для которой отключено автоматическое расширение вложенных ссылок (`expansion`). Гарантирует, что спецсимволы (например, `$`) будут восприняты буквально.
*   **GitLab Secrets Manager** — нативное решение для управления секретами (GA с версии **19.2**), обеспечивающее безопасное хранение, версионирование и инъекцию секретов.
*   **OIDC (OpenID Connect)** — метод аутентификации пайплайна во внешних системах (Vault, Kubernetes, менеджеры секретов) через `ID Tokens`.

## Базовые концепции

### Иерархия и приоритет переменных (Precedence)

В GitLab 19.x действует строгий порядок приоритетов. Если переменная с одним именем определена в нескольких местах, выбирается значение из источника с наивысшим приоритетом (от 1 до 14):

1.  **Script-level variables**: Переменные, определенные внутри блока `script` (`export DB_NAME=test`).
2.  **Trigger variables**: Переданные через API при запуске.
3.  **Manual variables**: Значения, введенные вручную при запуске пайплайна (`Run pipeline`).
4.  **Pipeline execution policy variables**: Заданные в политиках безопасности на уровне группы/инстанса.
5.  **Scheduled variables**: Переменные запланированных запусков.
6.  **Job-level variables**: Определенные внутри задачи в `.gitlab-ci.yml`.
7.  **Included variables**: Переменные из файлов, подключенных через `include`.
8.  **Global variables**: Определенные на верхнем уровне `.gitlab-ci.yml`.
9.  **Project variables**: Заданные в `Settings > CI/CD > Variables` проекта.
10. **Group variables**: Заданные на уровне группы (ближайшая подгруппа имеет приоритет).
11. **Instance variables**: Заданные администратором в `Admin Area`.
12. **Dotenv variables**: Переданные через `artifacts:reports:dotenv`.
13. **Deployment variables**: Специфичные для конкретного окружения (`environment`).
14. **Predefined variables**: Системные переменные GitLab (`CI_COMMIT_SHA`). Имеют самый низкий приоритет.

### UI-конфигурация переменных

С версии **19.x** расширены возможности описания переменных в `.gitlab-ci.yml` для удобства ручного запуска:

*   **`description`**: Текстовое описание переменной, отображаемое в интерфейсе GitLab при запуске пайплайна.
*   **`options`**: Список предустановленных значений (выпадающий список в UI), что минимизирует ошибки ввода.

### Безопасность и управление доступом

#### Защита CI_JOB_TOKEN (GitLab 18.0+)
Доступ через `CI_JOB_TOKEN` ограничен белым списком (**Allowlist**). 
*   **Тонкая настройка прав (Fine-grained Permissions):** С версии **18.3** можно ограничивать область действия токена конкретными правами (`read_registry`, `write_pages` и т.д.).
*   **Git Push (18.4+):** Токен позволяет выполнять `git push` в текущий репозиторий, упрощая автоматическое версионирование.

#### Предотвращение инъекций и расширение (Expansion)
*   **Default Behavior (18.6+):** Автоматическое расширение вложенных ссылок (`$VAR1` внутри `$VAR2`) **отключено**.
*   **Атрибут `raw: true`**: Позволяет явно указать, что значение переменной не должно обрабатываться парсером GitLab. Это критично для паролей или конфигураций, содержащих знак `$`.

#### OIDC и Secretless-подход
Для интеграции с внешними хранилищами секретов (Vault, менеджеры секретов) рекомендуется OIDC. Это позволяет Runner'у получать временный токен доступа на основе `ID Token`, исключая хранение долгоживущих секретов.

#### Программное управление переменными (API)
Переменные проекта и группы могут создаваться, обновляться и удаляться программно через **GitLab REST API**. Это позволяет реализовать сценарии динамической переконфигурации инфраструктуры (например, ротация ключей внешним сервисом или изменение лимитов нагрузки на основе данных мониторинга). Подробные примеры вызовов и сценарии автоматизации описаны в SSoT: **[Программная автоматизация: API и Webhooks](../Advanced/api_and_webhooks_automation.md)**.

## Практические сценарии

### Сценарий 1: Работа с переменными типа File (SSH)

Использование для SSH-ключей. Переменная `SSH_KEY` настроена как `File` и `Protected`.

```yaml
deploy:
  stage: deploy
  script:
    - chmod 400 "$SSH_KEY"
    - ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no user@remote-host "deploy.sh"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 2: Тонкая настройка прав CI_JOB_TOKEN

Ограничение прав токена для повышения безопасности пайплайна.

```yaml
publish_docs:
  stage: deploy
  permissions:
    contents: read
    pages: write
  script:
    - deploy_to_pages.sh --token "$CI_JOB_TOKEN"
```

### Сценарий 3: Интеграция с GitLab Secrets Manager

Нативное использование секретов без env-переменных (версия 19.2+).

```yaml
database_migration:
  stage: deploy
  secrets:
    DB_PASSWORD:
      vault: production/database/password  # Путь во встроенном хранилище
  script:
    - ./migrate.sh --password "$DB_PASSWORD"
```

### Сценарий 4: Аутентификация в Vault через OIDC (ID Tokens)

Безопасное получение секретов из внешнего Vault.

```yaml
get_vault_secrets:
  stage: .pre
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  variables:
    VAULT_ADDR: "https://vault.example.com:8200"
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=my-role jwt=$VAULT_ID_TOKEN)
    - vault kv get -field=apikey secret/my-service > apikey.txt
  artifacts:
    paths:
      - apikey.txt
```

### Сценарий 5: Переменные для ручного запуска с опциями (UI)

Создание удобного интерфейса для выбора параметров деплоя.

```yaml
variables:
  DEPLOY_ENV:
    description: "Выберите целевое окружение для деплоя"
    value: "staging"
    options:
      - "staging"
      - "production"
      - "testing"

deploy_task:
  stage: deploy
  script:
    - echo "Deploying to $DEPLOY_ENV"
  rules:
    - if: $CI_PIPELINE_SOURCE == "web"
```

### Сценарий 6: Использование сырых переменных (Raw)

Предотвращение нежелательного расширения символов в сложных паролях.

```yaml
variables:
  COMPLEX_PASSWORD:
    value: "pass$$word$123"
    raw: true  # Знак $ не будет интерпретирован как ссылка на переменную

test_connection:
  stage: test
  script:
    - ./check_auth.sh --password "$COMPLEX_PASSWORD"
```

### Сценарий 7: Автоматическая ротация секретов

Пайплайн для периодической ротации паролей и ключей с использованием GitLab API.

```yaml
stages:
  - rotate
  - verify

variables:
  VAULT_ADDR: "https://vault.example.com:8200"

rotate_db_password:
  stage: rotate
  image: vault:latest
  script:
    # Генерация нового пароля
    - NEW_PASSWORD=$(vault operator raft snapshot save -tls-skip-verify 2>/dev/null | head -c 32)
    
    # Обновление пароля в Vault
    - vault kv put secret/database/password password="$NEW_PASSWORD"
    
    # Обновление переменной в GitLab через API
    - |
      curl --request PUT \
        --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
        --header "Content-Type: application/json" \
        --data "{\"value\": \"${NEW_PASSWORD}\", \"masked\": true, \"protected\": true}" \
        "https://gitlab.example.com/api/v4/projects/${CI_PROJECT_ID}/variables/DB_PASSWORD"
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  variables:
    GITLAB_API_TOKEN: $GITLAB_MAINTAINER_TOKEN

verify_rotation:
  stage: verify
  script:
    # Проверка доступности БД с новым паролем
    - psql "postgresql://user:${DB_PASSWORD}@db-host:5432/mydb" -c "SELECT 1;"
  needs:
    - rotate_db_password
```

### Сценарий 8: Управление секретами для Terraform

Безопасная передача учетных данных Terraform через переменные окружения.

```yaml
stages:
  - plan
  - apply

.terraform_base:
  image: hashicorp/terraform:1.9
  before_script:
    - cd terraform/
    - terraform init -backend-config="backend.hcl"
  variables:
    # Секреты передаются через переменные окружения
    TF_VAR_db_password: $DB_PASSWORD
    TF_VAR_api_key: $API_KEY

terraform_plan:
  extends: .terraform_base
  stage: plan
  script:
    - terraform plan -out=tfplan -var-file="production.tfvars"
  artifacts:
    paths:
      - terraform/tfplan
    expire_in: 1 day
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

terraform_apply:
  extends: .terraform_base
  stage: apply
  script:
    - terraform apply -auto-approve tfplan
  dependencies:
    - terraform_plan
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 9: Интеграция с Ansible Vault

Использование Ansible Vault для управления секретами в playbooks.

```yaml
stages:
  - lint
  - deploy

ansible_lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/

ansible_deploy:
  stage: deploy
  image: cytopia/ansible:2.14
  before_script:
    - pip install ansible
    - pip install molecule
  script:
    # Пароль Ansible Vault передается через переменную
    - echo "$ANSIBLE_VAULT_PASSWORD" > .vault_pass
    - chmod 600 .vault_pass
    
    # Запуск playbook с расшифровкой секретов
    - ansible-playbook -i inventory/production \
        --vault-password-file .vault_pass \
        playbooks/deploy.yml
    
    # Очистка
    - rm -f .vault_pass
  after_script:
    - rm -f .vault_pass
  variables:
    ANSIBLE_VAULT_PASSWORD: $VAULT_PASSWORD
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 10: Мониторинг и алертинг на основе переменных

Настройка мониторинга с динамическими параметрами из переменных GitLab.

```yaml
stages:
  - configure
  - deploy

configure_monitoring:
  stage: configure
  image: grafana/grafana:latest
  script:
    # Обновление datasource в Grafana через API
    - |
      curl -X POST \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${GRAFANA_API_KEY}" \
        --data '{
          "name": "Prometheus",
          "type": "prometheus",
          "url": "'"${PROMETHEUS_URL}"'",
          "access": "proxy",
          "isDefault": true
        }' \
        "https://grafana.example.com/api/datasources"
  variables:
    GRAFANA_API_KEY: $GRAFANA_ADMIN_KEY
    PROMETHEUS_URL: "http://prometheus:9090"

deploy_alerts:
  stage: deploy
  image: grafana/grafana:latest
  script:
    # Импорт дашборда из JSON
    - |
      curl -X POST \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${GRAFANA_API_KEY}" \
        --data @monitoring/dashboards/k8s-cluster.json \
        "https://grafana.example.com/api/dashboards/db"
  needs:
    - configure_monitoring
  variables:
    GRAFANA_API_KEY: $GRAFANA_ADMIN_KEY
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Дополнительная информация

-   **[Основы GitLab CI/CD](./gitlab_ci_basics.md)** — база по стадиям и архитектуре.
-   **[Программная автоматизация: API и Webhooks](../Advanced/api_and_webhooks_automation.md)** — SSoT по программному управлению и обратной связи.
-   **[Интеграция с HashiCorp Vault](../Tutorials/vault_kubernetes_integration.md)** — детальное руководство по JWT/OIDC.
*   **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — методология и общие принципы.
*   **[Предопределенные переменные GitLab](https://docs.gitlab.com/ee/ci/variables/predefined_variables.html)** — полный официальный список.

> **Критичные изменения последних версий:**
>
> *   **19.2**: **GitLab Secrets Manager** перешел в GA. Расширен аудит доступа.
> *   **19.0**: Минимальная версия для использования нативного Secrets Manager.
> *   **18.6**: Изменено поведение по умолчанию для расширения вложенных переменных (теперь отключено).
> *   **18.3**: Автоматическое маскирование всех новых переменных и тонкие настройки прав для `CI_JOB_TOKEN`.
> *   **18.0**: Введен обязательный Allowlist для межпроектного использования `CI_JOB_TOKEN`.

## Диагностика и устранение неполадок

### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Variable hidden` | Переменная с таким именем уже существует в другом уровне (группа, инстанс) | Проверьте иерархию переменных (§ Иерархия и приоритет переменных). Удалите дубликат или переименуйте. |
| `CI_JOB_TOKEN` 403 Forbidden | Целевой проект не добавлен в Inbound Allowlist | Перейдите в Settings -> CI/CD -> Token Access и добавьте проект-источник в список разрешенных. |
| `Masked variable must not contain newlines` | Маскированная переменная содержит символы перевода строки | Используйте `File` тип переменной для многострочных данных. |
| `Variable value is invalid` | Невалидные символы в имени или значении переменной | Используйте только латинские буквы, цифры и нижнее подчеркивание в имени. Значение не должно содержать `=` в начале. |
| `Vault connection refused` | Vault недоступен или неверный адрес | Проверьте `VAULT_ADDR`, убедитесь что Vault запущен и доступен из сети Runner. |
| `OIDC token validation failed` | Неверный `aud` (audience) или истекший токен | Проверьте соответствие `aud` в `id_tokens` и настройках OIDC-провайдера (Vault, Kubernetes). |

### Методы диагностики

#### Просмотр переменных в пайплайне

```yaml
debug_env:
  stage: .pre
  script:
    # Вывод всех переменных (осторожно с секретами!)
    - env | sort
    
    # Просмотр конкретной переменной
    - echo "Current branch: $CI_COMMIT_BRANCH"
    - echo "Deploy target: $DEPLOY_ENV"
    
    # Проверка, задана ли переменная
    - |
      if [ -z "$DB_PASSWORD" ]; then
        echo "ERROR: DB_PASSWORD is not set"
        exit 1
      fi
```

#### Использование CI Lint для проверки переменных

```bash
# Проверка конфигурации через API
curl --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
  --header "Content-Type: application/json" \
  --data '{"content": "'"$(cat .gitlab-ci.yml)"'"}' \
  "https://gitlab.example.com/api/v4/ci/lint"
```

#### Проверка доступа к Secrets Manager

```yaml
check_secrets:
  stage: .pre
  script:
    - |
      echo "Testing Secrets Manager access..."
      # Попытка получения секрета (если доступен)
      if [ -n "$SECRETS_MANAGER_TOKEN" ]; then
        echo "Secrets Manager token is available"
      else
        echo "Warning: Secrets Manager not configured"
      fi
```

## Лучшие практики

### Безопасность

1. **Never commit secrets**: Никогда не коммитьте секреты в репозиторий. Используйте Variables или Secrets Manager.
2. **Use Masked + Protected**: Для критичных секретов включайте оба флага (`Masked` и `Protected`).
3. **Least Privilege**: Используйте минимально необходимые права для `CI_JOB_TOKEN` через Fine-grained Permissions.
4. **OIDC over Static Secrets**: Предпочитайте OIDC (`id_tokens`) хранению долгоживущих секретов в переменных.
5. **Audit Variables**: Регулярно проверяйте переменные проекта и группы на соответствие политикам безопасности.

### Организация

1. **Use Group Variables**: Общие секреты выносите на уровень группы, а не проекта.
2. **Environment Scoping**: Используйте `environment_scope` для изоляции секретов разных окружений.
3. **Descriptive Names**: Используйте понятные имена переменных (`DB_PASSWORD`, не `VAR1`).
4. **Document Variables**: Добавляйте `description` для переменных, используемых в UI.
5. **Version Sensitive Data**: Для секретов, требующих ротации, используйте `expires_at` (Secrets Manager).

### Производительность

1. **Cache Dependencies**: Кэшируйте зависимости (pip, npm, go mod) для ускорения сборки.
2. **Use `needs`**: Запускайте задачи параллельно через DAG вместо последовательного выполнения.
3. **Artifacts Cleanup**: Настройте `expire_in` для артефактов, чтобы не переполнять хранилище.
4. **Distributed Cache**: Используйте S3-compatible хранилище для кэша в кластере Runner.

### Отладка

1. **CI_DEBUG_TRACE**: Включайте только при необходимости (увеличивает размер логов).
2. **`gitlab-runner exec`**: Тестируйте конфигурацию локально перед коммитом.
3. **Lint Before Push**: Используйте CI Lint (UI или API) для проверки синтаксиса.
4. **Temporary Variables**: Для отладки создавайте переменные с `expires_at`.
