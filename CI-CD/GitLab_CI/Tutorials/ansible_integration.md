# Интеграция Ansible с GitLab CI/CD

## Определения

**Интеграция Ansible с GitLab CI/CD** — это процесс автоматизации управления конфигурациями, подготовки инфраструктуры (Provisioning) и развертывания приложений через выполнение плейбуков Ansible в конвейерах GitLab. Подход реализует парадигму **Infrastructure as Code (IaC)**, обеспечивая версионирование, аудит и повторяемость изменений.

- **Ansible Control Node (в CI):** Среда выполнения (GitLab Runner), в которой запускаются команды `ansible-playbook`. В современных пайплайнах это Docker-контейнер или специализированный **[Execution Environment (EE)](../../../Ansible/ansible-execution-environments.md)**.
- **Динамический инвентарь (Dynamic Inventory):** Механизм автоматического получения списка хостов из API облачных провайдеров (Yandex Cloud, AWS, GCP) или систем учета (NetBox) непосредственно в момент выполнения пайплайна.
- **CI/CD ID Tokens (JWT):** Современный механизм аутентификации, позволяющий GitLab Runner получать временные права доступа к облачным ресурсам или менеджерам секретов без использования долгоживущих паролей и ключей.
- **Артефакты (Artifacts):** Файлы, генерируемые плейбуком (отчеты о состоянии, логи изменений, сгенерированные конфигурации), которые сохраняются в GitLab для аудита и отладки.

## Основные концепции

### Преимущества интеграции

1.  **Идемпотентность и повторяемость:** Гарантия соответствия инфраструктуры коду, исключение ручных правок («дрейф конфигурации»).
2.  **Безопасность (Least Privilege):** Доступ к серверам имеет только Runner. Использование **Masked Variables** и временных JWT-токенов минимизирует риски утечки учетных данных.
3.  **Скорость и масштабируемость:** Параллельное выполнение задач на множестве хостов и использование `needs` для оптимизации графа выполнения пайплайна.
4.  **Аудит и отслеживаемость:** Полная история изменений с привязкой к коммитам, авторам и результатам выполнения плейбуков в UI GitLab.

### Среды выполнения: Docker vs Execution Environments

1.  **Docker-образы (Custom Images):** Создание `Dockerfile` с установленным `ansible-core`, необходимыми коллекциями и системными зависимостями (sshpass, git). Этот метод прост для старта, но требует ручного обновления образа при изменении зависимостей.
2.  **Ansible Execution Environments (EE):** Стандартизированные образы, собранные через `ansible-builder`. Они включают в себя движок, коллекции и зависимости Python/системы. EE гарантируют идентичность среды выполнения локально и в CI, что критично для сложных проектов.

### Оптимизация Ansible для GitLab CI

Для повышения производительности и улучшения читаемости логов в GitLab рекомендуется настраивать `ansible.cfg` или использовать переменные окружения:

- `ANSIBLE_FORCE_COLOR: "true"` — принудительное включение цветного вывода в терминале GitLab.
- `ANSIBLE_STDOUT_CALLBACK: "yaml"` — структурированный и читаемый вывод задач плейбука (вместо длинных строк JSON).
- `ANSIBLE_PIPELINING: "True"` — ускорение выполнения задач за счет уменьшения количества SSH-соединений (требует отключения `requiretty` в `/etc/sudoers` на хостах).
- `ANSIBLE_HOST_KEY_CHECKING: "False"` — отключение проверки SSH-ключей для новых хостов (использовать только в доверенных/эфемерных сегментах сети).

### Управление секретами: ID Tokens и OIDC

Вместо хранения статических ключей сервисных аккаунтов рекомендуется использовать **ID Tokens**.
GitLab генерирует временный JSON Web Token (JWT), который облачный провайдер (например, Yandex Cloud или HashiCorp Vault) обменивает на временные учетные данные. Это полностью исключает хранение секретов в переменных проекта.

---

## Практические сценарии

### Сценарий 1: Базовая настройка с кэшированием зависимостей

Использование `ansible-core` и кэширование установленных ролей/коллекций для ускорения последующих запусков.

```yaml
.ansible_base:
  image: python:3.12-slim
  variables:
    ANSIBLE_COLLECTIONS_PATH: "${CI_PROJECT_DIR}/.ansible/collections"
    ANSIBLE_ROLES_PATH: "${CI_PROJECT_DIR}/.ansible/roles"
    ANSIBLE_FORCE_COLOR: "true"
    PY_COLORS: "1"
  cache:
    key: "ansible-v1-${CI_COMMIT_REF_SLUG}"
    paths:
      - .ansible/
  before_script:
    - apt-get update && apt-get install -y git openssh-client jq
    - pip install ansible-core ansible-lint
    - mkdir -p .ansible/roles .ansible/collections
    - if [ -f "requirements.yml" ]; then
        ansible-galaxy install -r requirements.yml -p .ansible/roles;
        ansible-galaxy collection install -r requirements.yml -p .ansible/collections;
      fi
```

### Сценарий 2: Деплой в Yandex Cloud через ID Tokens

Современный метод беспарольной аутентификации.

```yaml
deploy_yc:
  extends: .ansible_base
  id_tokens:
    MY_JWT_TOKEN:
      aud: https://iam.api.cloud.yandex.net/iam/v1/tokens
  script:
    # Обмен JWT на временный IAM-токен
    - export YC_IAM_TOKEN=$(curl -s -X POST -H "Content-Type: application/json" -d "{\"jwt\":\"$MY_JWT_TOKEN\"}" https://iam.api.cloud.yandex.net/iam/v1/tokens | jq -r .iamToken)
    - ansible-playbook -i inventory/prod.yc.yml playbooks/site.yml
  environment: production
```

### Сценарий 3: Использование ssh-agent для управления ключами

Безопасная передача SSH-ключей без сохранения их на диск раннера.

```yaml
deploy_ssh_agent:
  extends: .ansible_base
  before_script:
    - !reference [.ansible_base, before_script]
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - ansible-playbook -i inventory/hosts.ini playbooks/site.yml
```

### Сценарий 4: Тестирование ролей через Molecule

Интеграция тестирования ролей с использованием Docker-in-Docker (DinD).

```yaml
test_molecule:
  stage: test
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - apk add --no-cache python3 py3-pip git openssh-client
    - pip install molecule[docker] ansible-core
    - molecule test
```

### Сценарий 5: Обработка критических ошибок (any_errors_fatal)

Для предотвращения частичного деплоя и неконсистентности инфраструктуры.

1.  **В плейбуке:**
    ```yaml
    - hosts: web_servers
      any_errors_fatal: true # Остановка на всех хостах, если один упал
      tasks:
        - name: Update application
          ansible.builtin.include_tasks: update.yml
    ```
2.  **В CI:** Используйте `artifacts` для сохранения отчетов.
    ```yaml
    deploy:
      script:
        - ansible-playbook site.yml --extra-vars "ansible_callback_whitelist=json"
      artifacts:
        paths:
          - deployment_report.json
        when: always
    ```

### Сценарий 6: Безопасный Ansible Vault (Тип File)

Передача пароля Vault через защищенную переменную типа File.

```yaml
deploy_vault:
  variables:
    ANSIBLE_VAULT_PASSWORD_FILE: "$VAULT_PASS_FILE"
  script:
    - ansible-playbook site.yml --vault-password-file "$ANSIBLE_VAULT_PASSWORD_FILE"
```

---

## Дополнительная информация

### Продвинутые техники

- **ansible-navigator:** Используйте для локальной отладки пайплайнов в тех же Execution Environments, что используются в GitLab CI. Это минимизирует ошибки типа "у меня работает, а в CI — нет".
- **Pull-модель (ansible-pull):** Для экстремально больших инфраструктур (1000+ узлов) GitLab CI может выступать триггером, который запускает `ansible-pull` на целевых узлах через SSH или расписание. Это снимает нагрузку с Control Node.
- **Ansible Automation Platform (AAP) / AWX:** Интеграция через API. Пайплайн GitLab CI отправляет запрос на запуск Job Template в AWX/AAP, передавая нужные переменные. Это обеспечивает централизованный аудит и RBAC.
  ```bash
  curl -H "Authorization: Bearer $AWX_TOKEN" -X POST "$AWX_HOST/api/v2/job_templates/$ID/launch/"
  ```

### Рекомендации по безопасности

- **no_log: true:** Обязательно используйте в задачах, обрабатывающих пароли, API-ключи и другие секреты.
- **Статический анализ:** Внедрите `ansible-lint` как блокирующую стадию пайплайна для обеспечения качества кода.
- **Изоляция:** Используйте разные раннеры (Protected Runners) для стадий деплоя на Production.

### Смотрите также

- **[Динамический инвентарь в Ansible](../../../Ansible/dynamic_inventory.md)** — глубокое погружение в плагины для облаков.
- **[Ansible Vault: Практические примеры](../../../Ansible/Vault/examples.md)** — методы шифрования в CI/CD.
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — детали работы с `Masked` и `File` переменными.
- **[Настройка GitLab Runner](../Advanced/gitlab_ci_runners_executors.md)** — оптимизация среды выполнения.
- **[Безопасная архитектура для CI/CD](../../../Ansible/examples/example_real_world_ci_cd.md)** — использование скриптов-оберток и защищенных Control Nodes.
