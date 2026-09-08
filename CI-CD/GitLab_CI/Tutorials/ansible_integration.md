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

#### Пример Dockerfile для Ansible в GitLab CI

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    git \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    ansible-core>=2.17.0 \
    ansible-lint>=24.2.0 \
    molecule[docker]

RUN ansible-galaxy collection install \
    community.general \
    community.postgresql \
    ansible.posix \
    -p /usr/share/ansible/collections

RUN mkdir -p /workspace && chmod 777 /workspace

WORKDIR /workspace

ENTRYPOINT ["ansible-playbook"]
```

Сборка и использование:

```bash
# Сборка образа
docker build -t my-registry.com/ansible-runner:latest .

# Пуш в реестр
docker push my-registry.com/ansible-runner:latest

# Локальный запуск плейбука через Docker
docker run --rm \
  -v $(pwd):/workspace \
  -v ~/.ssh/id_rsa:/root/.ssh/id_rsa:ro \
  my-registry.com/ansible-runner:latest \
  site.yml -i inventory/prod.yml
```

#### Сборка Execution Environment через ansible-builder

`ansible-builder` автоматизирует создание EE на основе декларативного YAML-файла:

```yaml
# execution-environment.yml
version: 3

images:
  base_image:
    name: quay.io/ansible/ansible-runner:latest

dependencies:
  ansible_core:
    package_pip: ansible-core>=2.17.0
  ansible_runner:
    package_pip: ansible-runner
  galaxy:
    collections:
      - name: community.general
      - name: community.postgresql
      - name: ansible.posix
  python:
    - psycopg2-binary
    - boto3
  system:
    - git
    - openssh-clients

additional_build_steps:
  append_final:
    - RUN alternatives --set python /usr/bin/python3
```

```bash
# Сборка образа
ansible-builder build -t my-registry.com/ansible-ee:v1.2

# Проверка зависимостей внутри образа
docker run --rm my-registry.com/ansible-ee:v1.2 \
  ansible-galaxy collection list
# → Collection        Version
# → ----------------  -------
# → community.general x.y.z
# → community.postgresql x.y.z
```

#### Использование EE в GitLab CI

```yaml
deploy_with_ee:
  stage: deploy
  image: my-registry.com/ansible-ee:v1.2
  script:
    - ansible-playbook site.yml -i inventory/prod.yml
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

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

## Practical YAML-примеры для GitLab CI

### Пример 1: Полный .gitlab-ci.yml с линтингом, тестированием и деплоем

```yaml
# .gitlab-ci.yml — полный пайплайн Ansible + GitLab CI

stages:
  - lint
  - test
  - build
  - deploy_staging
  - test_staging
  - deploy_production

variables:
  ANSIBLE_FORCE_COLOR: "true"
  ANSIBLE_STDOUT_CALLBACK: "yaml"
  PY_COLORS: "1"
  ANSIBLE_HOST_KEY_CHECKING: "False"

# Линтинг плейбуков
ansible_lint:
  stage: lint
  image: python:3.12-slim
  before_script:
    - pip install ansible-lint ansible-core
  script:
    - ansible-lint playbooks/ --profile=production -p
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Синтаксическая проверка плейбуков
syntax_check:
  stage: lint
  image: python:3.12-slim
  before_script:
    - pip install ansible-core
  script:
    - ansible-playbook playbooks/site.yml --syntax-check
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Тестирование ролей через Molecule
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
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Сборка Execution Environment
build_ee:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  before_script:
    - apk add --no-cache python3 py3-pip
    - pip install ansible-builder
  script:
    - ansible-builder build -t $CI_REGISTRY_IMAGE/ansible-ee:$CI_COMMIT_SHA
    - docker push $CI_REGISTRY_IMAGE/ansible-ee:$CI_COMMIT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Деплой в Staging
deploy_staging:
  stage: deploy_staging
  image: $CI_REGISTRY_IMAGE/ansible-ee:$CI_COMMIT_SHA
  script:
    - ansible-playbook playbooks/site.yml -i inventory/staging/hosts.yml
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Smoke-тесты на Staging
smoke_tests:
  stage: test_staging
  image: python:3.12-slim
  script:
    - pip install requests pytest
    - pytest tests/smoke/ --base-url=https://staging.myapp.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Деплой в Production
deploy_production:
  stage: deploy_production
  image: $CI_REGISTRY_IMAGE/ansible-ee:$CI_COMMIT_SHA
  script:
    - ansible-playbook playbooks/site.yml -i inventory/production/hosts.yml
  environment:
    name: production
    url: https://myapp.com
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Пример 2: Multi-host parallel deploy с health check

```yaml
# playbooks/rolling_deploy.yml
---
- name: Rolling Deploy с проверкой здоровья
  hosts: webservers
  serial: 1
  max_fail_percentage: 0
  become: true

  vars:
    app_version: "{{ lookup('env', 'APP_VERSION') | default('latest') }}"
    health_check_url: "http://{{ ansible_host }}:{{ http_port }}/health"
    health_check_retries: 10
    health_check_delay: 5

  pre_tasks:
    - name: Отключение от балансировщика
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/disable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      ignore_errors: true

    - name: Ожидание завершения активных соединений
      ansible.builtin.command: sleep 30
      args:
        creates: /tmp/.drain_complete

  tasks:
    - name: Остановка сервиса
      ansible.builtin.service:
        name: "{{ app_service_name }}"
        state: stopped

    - name: Развёртывание новой версии
      ansible.builtin.copy:
        src: "artifacts/app_v{{ app_version }}/"
        dest: "{{ app_install_dir }}/"
        owner: "{{ app_user }}"
        group: "{{ app_group }}"
        mode: "0644"

    - name: Запуск сервиса
      ansible.builtin.service:
        name: "{{ app_service_name }}"
        state: started

    - name: Health check после деплоя
      ansible.builtin.uri:
        url: "{{ health_check_url }}"
        status_code: 200
      register: health
      retries: "{{ health_check_retries }}"
      delay: "{{ health_check_delay }}"
      until: health.status == 200

    - name: Включение на балансировщике
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      when: health.status == 200

  post_tasks:
    - name: Маркировка завершения
      ansible.builtin.file:
        path: /tmp/.drain_complete
        state: touch
```

```yaml
# GitLab CI для multi-host parallel deploy
deploy_rolling:
  stage: deploy_production
  image: my-registry.com/ansible-ee:v1.2
  script:
    - |
      ansible-playbook playbooks/rolling_deploy.yml \
        -i inventory/production/hosts.yml \
        --extra-vars "app_version=$CI_COMMIT_SHA"
  environment:
    name: production
    url: https://myapp.com
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Пример 3: Canary Deployment через Ansible + GitLab CI

```yaml
# playbooks/canary_deploy.yml
---
- name: Canary Deployment
  hosts: localhost
  connection: local
  gather_facts: false

  vars:
    canary_host: "{{ groups['webservers'][0] }}"
    canary_weight: 10
    full_weight: 100
    error_threshold: 0.01

  tasks:
    - name: Установка веса canary
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/upstream/{{ upstream_name }}/weight/{{ canary_weight }}"
        method: PUT
      register: canary_weight_result

    - name: Развёртывание на canary
      ansible.builtin.include_tasks: deploy_single.yml
      vars:
        target_host: "{{ canary_host }}"

    - name: Мониторинг canary (5 минут)
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/upstream/{{ upstream_name }}/metrics"
        return_content: true
      register: canary_metrics
      until: >
        'error_rate' in canary_metrics.content and
        canary_metrics.content.split('error_rate')[1].split()[0]|float < error_threshold
      retries: 30
      delay: 10

    - name: Полное развёртывание
      ansible.builtin.include_tasks: deploy_all.yml
      when: canary_metrics is success

    - name: Восстановление полного веса
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/upstream/{{ upstream_name }}/weight/{{ full_weight }}"
        method: PUT
      when: canary_metrics is success

    - name: Откат canary при ошибке
      block:
        - name: Восстановление предыдущей версии на canary
          ansible.builtin.include_tasks: rollback_single.yml
          vars:
            target_host: "{{ canary_host }}"

        - name: Восстановление полного веса
          ansible.builtin.uri:
            url: "http://{{ lb_host }}/api/upstream/{{ upstream_name }}/weight/{{ full_weight }}"
            method: PUT
      when: canary_metrics is failed
```

```yaml
# GitLab CI для canary deployment
canary_deploy:
  stage: deploy_canary
  image: my-registry.com/ansible-ee:v1.2
  script:
    - ansible-playbook playbooks/canary_deploy.yml -i inventory/production/hosts.yml
  environment:
    name: canary
    url: https://canary.myapp.com
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Пример 4: Деплой через ansible-pull (Pull-модель)

```yaml
# .gitlab-ci.yml — триггер ansible-pull на целевых узлах
stages:
  - deploy

trigger_pull:
  stage: deploy
  image: alpine:3.19
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - |
      for host in $SERVER_LIST; do
        echo "Triggering ansible-pull on $host..."
        ssh deploy@$host "sudo systemctl start ansible-pull.service"
      done
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  tags:
    - protected-runner
```

### Пример 5: Деплой с Vault и динамическими секретами

```yaml
# playbooks/deploy_with_vault.yml
---
- name: Deploy с использованием Vault
  hosts: app_servers
  become: true

  vars:
    vault_addr: "https://vault.internal.example.com"
    vault_role: "deploy-production"

  tasks:
    - name: Получение секретов из Vault
      ansible.builtin.uri:
        url: "{{ vault_addr }}/v1/auth/approle/login"
        method: POST
        body_format: json
        body:
          role_id: "{{ lookup('env', 'VAULT_ROLE_ID') }}"
          secret_id: "{{ lookup('env', 'VAULT_SECRET_ID') }}"
        status_code: 200
      register: vault_auth
      no_log: true

    - name: Получение database credentials
      ansible.builtin.uri:
        url: "{{ vault_addr }}/v1/secret/data/database"
        method: GET
        headers:
          X-Vault-Token: "{{ vault_auth.json.auth.client_token }}"
        status_code: 200
      register: db_creds
      no_log: true

    - name: Развёртывание конфигурации
      ansible.builtin.template:
        src: templates/database.yml.j2
        dest: /opt/app/config/database.yml
        owner: app
        group: app
        mode: "0600"
      vars:
        db_host: "{{ db_creds.json.data.data.host }}"
        db_pass: "{{ db_creds.json.data.data.password }}"
      no_log: true

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: myapp
        state: restarted
```

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

## GitLab CI Inputs для управления Ansible

GitLab CI Inputs (`spec:inputs`) — механизм типизации параметров, заменяющий свободные переменные на структурированные элементы интерфейса с валидацией на этапе компиляции. Подробности синтаксиса, типов данных и ограничений см. в SSoT **[Переменные и лучшие практики](../Advanced/workflow_rules/variables_best_practices.md)**.

### Выбор окружения и плейбука через Inputs

В монорепозиториях с множеством плейбуков и инвентарей Inputs позволяют организовать Self-Service запуск для инженеров без прямого доступа к конфигурации CI.

```yaml
# .gitlab-ci.yml — корневой файл с spec:inputs
spec:
  inputs:
    deploy_env:
      type: string
      default: test
      options: [test, stage, production]
      description: "Целевое окружение"
    playbook_name:
      type: string
      default: site.yml
      options: [site.yml, db.yml, app.yml]
      description: "Имя плейбука для выполнения"
    target_hosts:
      type: string
      default: "all"
      description: "Группа хостов из инвентаря (--limit)"
    run_lint:
      type: boolean
      default: true
      description: "Запускать ansible-lint перед выполнением"

stages:
  - lint
  - deploy

.deploy_template:
  stage: deploy
  script:
    - ansible-playbook playbooks/$[[ inputs.playbook_name ]] \
        -i inventory/$[[ inputs.deploy_env ]}/hosts.yml \
        --limit "$[[ inputs.target_hosts ]]"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_job:
  extends: .deploy_template
  environment:
    name: $[[ inputs.deploy_env ]]
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Условная логика и валидация

Inputs поддерживают `options` и `regex`, что исключает ошибки конфигурации при ручном запуске. В GitLab 19.x+ встроенная валидация на этапе компиляции предотвращает передачу невалидных значений.

```yaml
spec:
  inputs:
    environment:
      type: string
      options: [test, stage, production]
    database_target:
      type: string
      options: [primary, replica, both]
      description: "Цель деплоя БД"
    skip_migration:
      type: boolean
      default: false
    migration_version:
      type: number
      description: "Версия миграции"
```

### Динамические пути к секретам через Inputs

Inputs позволяют безопасно конструировать пути в HashiCorp Vault, исключая жестко прописанные адреса и ошибки ручного ввода.

```yaml
spec:
  inputs:
    environment:
      type: string
      options: [test, stage, production]
    server_role:
      type: string
      options: [app, db, cache, lb]
      description: "Роль сервера в инфраструктуре"

get_secret:
  stage: deploy
  script:
    - |
      VAULT_PATH="secret/$[[ inputs.environment ]]/$[[ inputs.server_role ]]"
      curl -H "X-Vault-Token: $VAULT_TOKEN" \
        "$VAULT_ADDR/v1/$VAULT_PATH" | jq -r '.data'
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Шаблонизация и Include в монорепозитории

Для крупных репозиториев с множеством плейбуков конфигурацию разбивают на файлы с последующим `include`. Inputs интерполируются во всех включаемых файлах, что позволяет параметризировать окружение на уровне шаблонов.

```yaml
# .gitlab-ci.yml (корень)
spec:
  inputs:
    deploy_env:
      type: string
      default: test
      options: [test, stage, production]

include:
  - local: '/templates/lint.yml'
  - local: '/templates/deploy-$[[ inputs.deploy_env ]].yml'
  - project: 'infrastructure/gitlab-templates'
    ref: 'main'
    file: '/templates/security-gates.yml'
```

### Шаблон с рекурсивным Include

Альтернативный подход к централизованному управлению CI: удаленный шаблон, который возвращает управление обратно в проект. Это позволяет сочетать безопасность корпоративного шаблона с гибкостью локальных переопределений.

```yaml
# В репозитории проекта .gitlab-ci.yml:
include:
  - remote: 'https://gitlab.example.com/infrastructure/ci-templates/-/raw/main/ansible-base.yml'

# В ansible-base.yml (удаленный репозиторий):
spec:
  inputs:
    deploy_env:
      type: string
      default: test

stages:
  - lint
  - deploy

# ... базовые джобы ...

# Рекурсия: возвращаем управление проекту,
# чтобы он мог добавить свои джобы поверх шаблона
include:
  - local: '.gitlab-ci.local.yml'
```

Проект оставляет `.gitlab-ci.local.yml` пустым или с собственными джобами. Полная конфигурация пайплайна видна в Pipeline Editor (`View merged YAML`), что позволяет инженерам вносить изменения, не имея прав на редактирование корпоративного шаблона. При попытке изменить удаленный include GitLab отклоняет пул-реквест, так как основная логика хранится в защищенном репозитории.

### Тестирование плейбуков через сервисы DinD

Для проверки плейбуков на разных операционных системах без выделенных хостов используются несколько сервисов Docker-in-Docker в одной задаче. Ansible запускается в контейнере Runner, а целевые ОС — как сервисы с алиасами, которые указываются в инвентаре.

```yaml
test_playbook_multi_os:
  stage: test
  image: docker:24.0
  services:
    - name: docker:24.0-dind
      alias: docker
    - name: ubuntu:22.04
      alias: target-ubuntu
    - name: rockylinux:9
      alias: target-rocky
  variables:
    DOCKER_HOST: tcp://docker:2375
  before_script:
    - apk add --no-cache python3 py3-pip git openssh-client
    - pip install ansible-core ansible-lint
  script:
    - ansible-playbook playbooks/test.yml -i inventory/test.ini \
        --limit "target-ubuntu,target-rocky"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Важно:** Контейнеры-цели должны иметь запущенный SSH-сервер, сгенерированные хосты-ключи и добавленный публичный ключ Runner в `authorized_keys`. Для упрощения в эфемерных контейнерах можно настроить `ansible.builtin.connection: docker` в инвентаре, отказавшись от SSH.

### Безопасность монорепозитория Ansible

При объединении плейбуков нескольких команд в одном репозитории применяются следующие контроли:

1. **Защита веток:** `main`/`master` защищены, прямые пуши запрещены. Изменения проходят через MR с обязательным approve.
2. **Protected Runners для Production:** Джобы деплоя на production помечены `tags: [protected-runner]`, что ограничивает их запуск только выделенными раннерами с доступом к продакшен-сегменту.
3. **Централизованный Include:** Чтение CI-конфигурации через `include: remote` из защищенного репозитория исключает возможность инъекции кода через форк.
4. **Минимизация прав:** Раннер для тестов не имеет доступа к production-секретам (Environment Scoped Variables). Маскированные переменные с флагом `Protected` недоступны в пушах из feature-веток.

## Troubleshooting

### Проблема 1: SSH-ключ не работает в GitLab CI

**Причина:** SSH-ключ содержит passphrase или неправильно отформатирован.

**Решение:**
```yaml
deploy_ssh:
  before_script:
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - ssh -T git@gitlab.example.com
```

**Проверка:**
```bash
# Публичный ключ должен быть добавлен на целевом сервере
ssh -T git@gitlab.example.com
# → Welcome to GitLab, @username!
```

### Проблема 2: Плейбук не находит роли

**Причина:** Неправильно настроены пути к ролям или не установлены зависимости.

**Решение:**
```yaml
variables:
  ANSIBLE_ROLES_PATH: "${CI_PROJECT_DIR}/.ansible/roles"
  ANSIBLE_COLLECTIONS_PATH: "${CI_PROJECT_DIR}/.ansible/collections"

before_script:
  - ansible-galaxy install -r requirements.yml -p .ansible/roles
  - ansible-galaxy collection install -r requirements.yml -p .ansible/collections
```

**Проверка:**
```bash
ansible-galaxy role list
# → ROLE_PATHS:
# → /builds/project/.ansible/roles
```

### Проблема 3: Ansible-lint падает в CI

**Причина:** Используются устаревшие модули или отсутствуют FQCN (Fully Qualified Collection Names).

**Решение:**
```yaml
# ansible-lint.yml
profile: production
exclude_paths:
  - .ansible/
  - molecule/

rules:
  - fqcn[action-core]: 1
  - fqcn[action]: 1
  - no-free-form: 1
```

**Проверка:**
```bash
ansible-lint playbooks/site.yml --profile=production -p
# → Passed: 45, Failed: 0
```

### Проблема 4: Деплой останавливается на первом хосте

**Причина:** Используется `strategy: linear` без `serial` или с `max_fail_percentage: 0`.

**Решение:**
```yaml
- hosts: webservers
  serial: "25%"
  max_fail_percentage: 10  # Допустимо до 10% ошибок
  strategy: linear
  tasks:
    - name: Deploy
      ansible.builtin.include_tasks: deploy.yml
```

### Проблема 5: Health check не проходит после деплоя

**Причина:** Сервис еще не успел запуститься или health check URL неправильный.

**Решение:**
```yaml
- name: Health check с увеличенным таймаутом
  ansible.builtin.uri:
    url: "http://{{ ansible_host }}:{{ http_port }}/health"
    status_code: 200
  register: health
  retries: 20
  delay: 10
  until: health.status == 200
```

### Проблема 6: Vault password file не найден

**Причина:** Переменная `ANSIBLE_VAULT_PASSWORD_FILE` не передана или файл не создан.

**Решение:**
```yaml
deploy_vault:
  variables:
    ANSIBLE_VAULT_PASSWORD_FILE: "/tmp/vault_pass"
  before_script:
    - echo "$VAULT_PASSWORD" > /tmp/vault_pass
    - chmod 600 /tmp/vault_pass
  script:
    - ansible-playbook site.yml --vault-password-file /tmp/vault_pass
  after_script:
    - rm -f /tmp/vault_pass
```

### Проблема 7: CI-пайплайн не запускается для ветки

**Причина:** Отсутствует `workflow:rules` или ветка не в списке разрешенных.

**Решение:**
```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_BRANCH == "staging"
```

---

## Rollback стратегии в контексте Ansible + GitLab CI

### Rollback через block/rescue в плейбуке

```yaml
- name: Deploy с автоматическим откатом
  hosts: app_servers
  become: true
  tasks:
    - name: Сохранение текущей версии
      ansible.builtin.copy:
        src: "{{ app_install_dir }}/"
        dest: "/tmp/backup/"
        remote_src: true
      ignore_errors: true

    - name: Развёртывание новой версии
      block:
        - name: Копирование файлов
          ansible.builtin.copy:
            src: "artifacts/app_v{{ app_version }}/"
            dest: "{{ app_install_dir }}/"

        - name: Перезапуск сервиса
          ansible.builtin.service:
            name: "{{ app_service_name }}"
            state: restarted

        - name: Health check
          ansible.builtin.uri:
            url: "http://{{ ansible_host }}:{{ http_port }}/health"
            status_code: 200
          retries: 10
          delay: 5

      rescue:
        - name: Откат на предыдущую версию
          ansible.builtin.copy:
            src: "/tmp/backup/"
            dest: "{{ app_install_dir }}/"
            remote_src: true

        - name: Перезапуск предыдущей версии
          ansible.builtin.service:
            name: "{{ app_service_name }}"
            state: restarted
```

### Rollback через Git revert + пере деплой

```yaml
# .gitlab-ci.yml
rollback:
  stage: rollback
  image: my-registry.com/ansible-ee:v1.2
  script:
    - git config user.email "ci@gitlab.internal"
    - git config user.name "GitLab CI"
    - git revert HEAD --no-edit
    - git push origin $CI_COMMIT_BRANCH
    - ansible-playbook playbooks/site.yml -i inventory/production/hosts.yml
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Rollback через Helm (для Kubernetes)

```yaml
helm_rollback:
  stage: rollback
  image: alpine/helm:latest
  script:
    - helm rollback myapp --namespace production
    - kubectl rollout status deployment/myapp -n production
  when: manual
```

---

## Compliance и аудит

### Аудит через GitLab CI + Ansible

Каждое выполнение Ansible через GitLab CI фиксирует:
- Кто запустил пайплайн
- Какой коммит был использован
- Какие переменные были переданы
- Результат выполнения плейбука
- Время начала и окончания

```yaml
# Генерация JSON-отчета для аудита
deploy_with_audit:
  stage: deploy
  script:
    - |
      ansible-playbook playbooks/site.yml \
        -i inventory/production/hosts.yml \
        --extra-vars "ansible_callback_whitelist=json" \
        -e "gitlab_user=$GITLAB_USER_LOGIN" \
        -e "gitlab_commit=$CI_COMMIT_SHA" \
        2>&1 | tee deployment_report.json
  artifacts:
    paths:
      - deployment_report.json
    when: always
    expire_in: 90 days
```

### Pipeline Execution Policies

Принудительные проверки на уровне группы GitLab:
- ansible-lint (stage: lint)
- syntax_check (stage: lint)
- Molecule тесты (stage: test)
- Health check после деплоя
- Manual approval для production

### Masked Variables для секретов

```
# В GitLab CI Variables (Settings > CI/CD > Variables):
# VAULT_ROLE_ID — Masked, Protected
# VAULT_SECRET_ID — Masked, Protected, File type
# SSH_PRIVATE_KEY — Masked, Protected, File type
# DEPLOY_TOKEN — Masked, Protected
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

- **[Execution Environments в Ansible](../../../Ansible/ansible-execution-environments.md)** — подробное руководство по созданию и использованию EE.
- **[Стратегии деплоя в Ansible](../../../Ansible/ansible_deployment_strategies.md)** — rolling updates, canary, blue-green и rollback стратегии.
- **[Ansible Vault: Практические примеры](../../../Ansible/Vault/examples.md)** — методы шифрования секретов в CI/CD.
- **[Динамический инвентарь в Ansible](../../../Ansible/dynamic_inventory.md)** — плагины для автоматического получения списка хостов.
- **[Безопасная архитектура для CI/CD](../../../Ansible/examples/example_real_world_ci_cd.md)** — скрипты-обертки, OIDC и защита Control Node.
