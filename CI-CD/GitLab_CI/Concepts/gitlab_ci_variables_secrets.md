# Переменные и секреты GitLab CI

## Определения

* **Переменные CI/CD** — это динамические значения, которые можно передавать в Pipeline GitLab CI/CD для управления его поведением, конфигурацией или для хранения конфиденциальных данных (Secrets).
* **Защищенная переменная (`Protected`)** — переменная, доступная только в Pipeline, запускаемых для защищенных Branch или Tag. Используется для хранения Secrets, связанных с Production-средами.
* **Маскированная переменная (`Masked`)** — переменная, значение которой скрывается в логах выполнения Job. Для маскирования значение должно быть однострочным, без пробелов и длиной не менее 8 символов.
* **Скрытая переменная (`Hidden`)** — переменная, значение которой скрыто в UI (Settings > CI/CD > Variables) и в логах. Доступно в GitLab 17.4+ (GA в 17.6).
* **Переменная типа `File`** — переменная, содержимое которой GitLab Runner записывает во временный файл, а сама переменная хранит путь к этому файлу. Используется для многострочных Secrets, таких как SSH-ключи.
* **Предопределенные переменные** — набор переменных, которые GitLab автоматически предоставляет в каждом Pipeline (`CI_COMMIT_BRANCH`, `CI_PROJECT_NAME` и т.д.).
* **Внешние хранилища секретов** — сторонние системы (например, HashiCorp Vault), используемые для безопасного централизованного хранения Secrets. Интеграция описана в [Интеграция GitLab CI с HashiCorp Vault](../Tutorials/vault_kubernetes_integration.md).

## Основные концепции

### Объявление и атрибуты переменных

Переменные определяются в настройках проекта (`Settings > CI/CD > Variables`) и могут иметь следующие характеристики:

* **Типы переменных:**
  * **`Variable`**: Стандартная пара "ключ-значение", передаваемая как переменная окружения.
  * **`File`**: Содержимое переменной сохраняется во временный файл на Runner, а в Pipeline передается путь к этому файлу. Идеально для сертификатов и ключей. Недоступно для переменных в `.gitlab-ci.yml` (только через UI).

* **Атрибуты переменных:**
  * **`Protected`**: Ограничивает доступ к переменной только для Pipeline в защищенных Branch или Tag.
  * **`Masked`**: Скрывает значение переменной в логах. Требует, чтобы значение было однострочным, без пробелов и длиной минимум 8 символов. Маскирование применяется только к сырому значению. Если изменить Pipeline, добавив команду кодирования переменной (например, `echo $SECRET | base64`), закодированное значение попадёт в логи.
  * **`Hidden`** (GitLab 17.4+): Скрывает значение в UI и логах. Только при создании — нельзя обновить существующую переменную. После сохранения значение нельзя просмотреть в UI.

> **Важно (GitLab 18.3+):** По умолчанию все новые переменные создаются с атрибутом `Masked`.

### Интеграция с внешними хранилищами (Secret-Zero)

При интеграции с внешними системами, такими как HashiCorp Vault или AWS Secrets Manager, возникает проблема "нулевого секрета" (Secret-Zero): как Pipeline аутентифицироваться в хранилище, не имея изначально секрета для доступа?

Эту проблему решает механизм **аутентификации по JWT (JSON Web Token)**. GitLab для каждой Job генерирует уникальный, короткоживущий токен `CI_JOB_TOKEN`. Внешнее хранилище настраивается так, чтобы доверять этим токенам, проверяя их атрибуты (claims), такие как:

* `project_id`: ID проекта.
* `ref`: Имя Branch или Tag.
* `ref_protected`: Является ли Branch защищенной (`true`/`false`).

Это позволяет Pipeline безопасно получать Secrets "на лету" (just-in-time), не храня долгоживущих учетных данных в переменных CI/CD.

### Предопределенные переменные GitLab CI

GitLab автоматически инжектирует множество предопределенных переменных, начинающихся с префикса `CI_`. Они предоставляют Context о текущем Pipeline, Commit и проекте.

**Наиболее часто используемые:**

* `CI_COMMIT_BRANCH`: Имя текущей Branch.
* `CI_COMMIT_SHORT_SHA`: Короткий хеш (8 символов) текущего Commit. Используется для уникального Tagging Docker-образов, что гарантирует связь между версией кода и собранным артефактом.
* `CI_REGISTRY_IMAGE`: Полный URL Docker-образа во встроенном Container Registry GitLab. Формат: `gitlab.example.com/namespace/project`.
* `CI_PROJECT_NAME`: Имя текущего проекта.
* `CI_PIPELINE_ID`: Уникальный идентификатор текущего Pipeline.
* `CI_JOB_TOKEN`: Временный токен для аутентификации при взаимодействии с GitLab API или Container Registry.

## Практические сценарии

### Сценарий 1: Использование разных типов переменных

**Настройка переменных в `Settings > CI/CD > Variables`:**

1. `PROD_SERVER_IP` (Variable): `192.168.1.100`
2. `PROD_API_TOKEN` (Variable, Masked): `MySuperSecretApiTokenValue`
3. `PROD_SSH_KEY` (File, Protected): `-----BEGIN RSA PRIVATE KEY...`

**Job в `.gitlab-ci.yml`:**

```yaml
deploy_production:
  stage: deploy
  script:
    - echo "Deploying to server $PROD_SERVER_IP"
    - echo "API Token is $PROD_API_TOKEN" # В логе будет [MASKED]
    - |
      # Настраиваем SSH-ключ из переменной типа File
      chmod 600 "$PROD_SSH_KEY"
      ssh -i "$PROD_SSH_KEY" user@"$PROD_SERVER_IP" "hostname"
  rules:
    - if: $CI_COMMIT_BRANCH == 'main' # 'main' является защищенной Branch
```

**Результат:**

* Job запустится только для Branch `main`, так как `PROD_SSH_KEY` — защищенная переменная.
* В логах Pipeline вместо значения `PROD_API_TOKEN` будет отображаться `[MASKED]`.
* SSH-ключ будет безопасно использован для подключения к серверу.

### Сценарий 2: Динамическое Tagging Docker-образа

Этот сценарий использует предопределенные переменные для создания уникального и информативного Tag для Docker-образа.

```yaml
build_image:
  stage: build
  image: docker:20.10
  services:
    - docker:20.10-dind
  script:
    - |
      # Формируем Tag из имени Branch и короткого хеша Commit
      if [ -n "$CI_COMMIT_TAG" ]; then
        TAG="$CI_COMMIT_TAG"
      else
        TAG="$CI_COMMIT_REF_SLUG-$CI_COMMIT_SHORT_SHA"
      fi
    - docker build -t "$CI_REGISTRY_IMAGE:$TAG" .
    - docker push "$CI_REGISTRY_IMAGE:$TAG"
```

**Результат:**

* Для Branch `feature/new-login` с Commit `a1b2c3d4` будет создан Tag `feature-new-login-a1b2c3d4`.
* Для Git-Tag `v1.2.0` будет создан Docker-Tag `v1.2.0`.

### Сценарий 3: Расшифровка Secrets с помощью ansible-vault

Этот метод позволяет хранить Secrets в зашифрованном виде прямо в Repository.

**Настройка:**

1. Создайте файл с Secrets и зашифруйте его: `ansible-vault encrypt secrets.yml`.
2. В `Settings > CI/CD > Variables` добавьте переменную `VAULT_PASSWORD` со значением пароля от `ansible-vault`.

**Job в `.gitlab-ci.yml`:**

```yaml
use_secrets:
  stage: test
  image: ansible/ansible:latest
  script:
    # 1. Расшифровываем файл с Secrets "на лету"
    - ansible-vault view secrets.yml --vault-password-file <(echo "$VAULT_PASSWORD") > decrypted_secrets.txt
    # 2. Используем расшифрованные данные
    - grep "api_key" decrypted_secrets.txt
```

**Результат:**

* Secrets остаются зашифрованными в Repository.
* Пароль для расшифровки надежно хранится в переменных GitLab CI.
* Расшифровка происходит только во время выполнения Pipeline в изолированной среде Runner.

### Сценарий 4: Использование переменной типа File для CA-сертификата

При работе с внутренними сервисами (например, Docker-реестром Harbor), использующими TLS с сертификатами от собственного центра сертификации (CA), необходимо, чтобы клиенты в CI/CD-Pipeline доверяли этому CA.

**Настройка:**

1. В `Settings > CI/CD > Variables` добавьте переменную `CUSTOM_CA_CERT` типа `File`.
2. В значение переменной вставьте содержимое публичного ключа вашего CA (`ca.crt`).

**Job в `.gitlab-ci.yml` (пример для Docker):**

```yaml
build_with_custom_ca:
  stage: build
  image: docker:20.10
  services:
    - docker:20.10-dind
  before_script:
    # Docker daemon (dind) и клиент Docker должны доверять вашему CA
    # $CUSTOM_CA_CERT содержит путь к временному файлу с сертификатом
    - mkdir -p /etc/docker/certs.d/harbor.your-domain.com
    - cp "$CUSTOM_CA_CERT" /etc/docker/certs.d/harbor.your-domain.com/ca.crt
    - docker login -u $HARBOR_USER -p $HARBOR_PASSWORD harbor.your-domain.com
  script:
    - docker build -t harbor.your-domain.com/my-project/my-image:latest .
    - docker push harbor.your-domain.com/my-project/my-image:latest
```

**Результат:**

* Переменная `CUSTOM_CA_CERT` типа `File` предоставляет безопасный и удобный способ передачи многострочного сертификата в Pipeline.
* Клиентские утилиты (`docker`, `curl`, `kaniko` и др.) могут быть настроены на использование этого сертификата для установления доверенных TLS-соединений.

## Дополнительная информация

* **[Интеграция GitLab CI с HashiCorp Vault](../Tutorials/vault_kubernetes_integration.md)** — безопасное управление динамическими секретами.
* **[Управление секретами в CI/CD](../../DevSecOps/secrets_management.md)** — общие концепции и лучшие практики DevSecOps.
* **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** — чего следует избегать при работе с конфиденциальными данными.

> **Критичные изменения GitLab 18.x:**
>
> * **18.3**: Переменные по умолчанию маскируются (`Masked` вместо `Visible`).
> * **18.6**: `expand variable reference` отключён по умолчанию.
