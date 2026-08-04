# Интеграция Ansible с GitLab CI/CD

## Надежность и актуальность

- **Оценка надежности:** 10 (SSoT + Проверенные практики)
- **Триггеры обновления:** Выход мажорных версий Ansible (10.x+), изменения в механизмах ID Tokens GitLab, обновление best-practices по безопасности.

## Определения

**Интеграция Ansible с GitLab CI/CD** — это процесс автоматизации управления конфигурациями, подготовки инфраструктуры (Provisioning) и развертывания приложений через выполнение плейбуков Ansible в конвейерах GitLab. Подход реализует парадигму **Infrastructure as Code (IaC)**, обеспечивая версионирование и автоматическое применение изменений.

- **Ansible Control Node (в CI):** Среда выполнения (GitLab Runner), в которой запускаются команды `ansible-playbook`. Может быть shell-окружением, Docker-контейнером или специализированным **Execution Environment (EE)**.
- **Динамический инвентарь (Dynamic Inventory):** Механизм автоматического получения списка хостов из API облачных провайдеров (Yandex Cloud, AWS) или CMDB (NetBox) в момент выполнения пайплайна.
- **CI/CD ID Tokens (JWT):** Современный механизм аутентификации, позволяющий GitLab Runner получать временные права в облаках без использования долгоживущих секретов (паролей, ключей).
- **Артефакты (Artifacts):** Файлы, генерируемые плейбуком (логи, отчеты о состоянии, сгенерированные конфиги), сохраняемые в GitLab для аудита и отладки.

## Основные концепции

### Преимущества интеграции

1. **Идемпотентность и повторяемость:** Гарантия соответствия инфраструктуры коду, исключение ручных правок («дрейф конфигурации»).
2. **Безопасность (Least Privilege):** Доступ к серверам имеет только Runner. Использование **Masked Variables** и временных JWT-токенов минимизирует риски утечки.
3. **Скорость и масштабируемость:** Параллельный деплой на сотни хостов, использование `needs` для ускорения цепочек задач.
4. **Аудит и отслеживаемость:** Полная история изменений с привязкой к коммитам, авторам и результатам выполнения плейбуков.

### Среды выполнения: Docker vs Execution Environments

В современных пайплайнах существует два подхода к подготовке Control Node:

1. **Docker-образы (Custom Images):** Создание `Dockerfile` с установленным `ansible-core`, коллекциями и системными зависимостями (sshpass, git). Быстрый старт, но сложность поддержки при большом количестве коллекций.
2. **Ansible Execution Environments (EE):** Стандартизированные образы, собранные через `ansible-builder`. Включают в себя `ansible-runner`, зависимости Python и системные библиотеки. Позволяют гарантировать идентичность среды выполнения локально и в CI.

### Оптимизация Ansible для GitLab CI

Для повышения производительности и удобства чтения логов в `ansible.cfg` или через переменные окружения рекомендуется:

- `ANSIBLE_FORCE_COLOR: "true"` — принудительное включение цветного вывода в терминале GitLab.
- `ANSIBLE_STDOUT_CALLBACK: "yaml"` — более структурированный и читаемый вывод задач плейбука.
- `ANSIBLE_PIPELINING: "True"` — ускорение выполнения задач за счет сокращения количества SSH-соединений.
- `ANSIBLE_HOST_KEY_CHECKING: "False"` — отключение проверки SSH-ключей для новых эфемерных хостов (использовать с осторожностью).

### Управление секретами: ID Tokens и OIDC

Вместо хранения статических ключей сервисных аккаунтов (например, `YC_SERVICE_ACCOUNT_KEY_FILE`) рекомендуется использовать **ID Tokens**.
GitLab генерирует временный JSON Web Token (JWT), который облачный провайдер обменивает на временные учетные данные. Это исключает хранение секретов в переменных GitLab.

## Практические сценарии

### Сценарий 1: Базовая настройка с кэшированием коллекций

Использование `ansible-core` (минималистичный пакет) и кэширование зависимостей для ускорения пайплайна.

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
    - apt-get update && apt-get install -y git openssh-client
    - pip install ansible-core
    - mkdir -p .ansible/roles .ansible/collections
    - ansible-galaxy collection install -r requirements.yml -p .ansible/collections
    - ansible-galaxy role install -r requirements.yml -p .ansible/roles
```

### Сценарий 2: Деплой в Yandex Cloud через ID Tokens (Без секретов)

Современный метод аутентификации в Yandex Cloud с использованием `id_tokens`.

```yaml
deploy_yc:
  extends: .ansible_base
  id_tokens:
    MY_JWT_TOKEN:
      aud: https://iam.api.cloud.yandex.net/iam/v1/tokens
  script:
    # Обмен JWT на временный IAM-токен
    - export YC_IAM_TOKEN=$(curl -s -X POST -H "Content-Type: application/json" -d "{\"jwt\":\"$MY_JWT_TOKEN\"}" https://iam.api.cloud.yandex.net/iam/v1/tokens | jq -r .iamToken)
    - ansible-playbook -i inventory/prod.yc.yml site.yml
  environment: production
```

### Сценарий 3: Использование ssh-agent для SSH-ключей

Метод с `ssh-agent` чище, чем передача пути через `--private-key`, так как позволяет работать с прокси-хостами (Bastion) и упрощает синтаксис команд.

```yaml
deploy_app:
  stage: deploy
  before_script:
    - eval $(ssh-agent -s)
    - chmod 400 "$SSH_PRIVATE_KEY"
    - ssh-add "$SSH_PRIVATE_KEY"
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - ansible-playbook -i hosts.ini site.yml
```

### Сценарий 4: Тестирование ролей через Molecule

Интеграция тестирования ролей в CI позволяет проверять корректность кода перед деплоем.

```yaml
test_role:
  stage: lint
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - pip install molecule[docker] ansible-core
    - molecule test
    # → PLAY [Destroy] ...
    # → PLAY [Create] ...
    # → PLAY [Converge] ...
    # → PLAY [Verify] ...
```

### Сценарий 5: Обработка критических ошибок (any_errors_fatal)

Для предотвращения «частичного» деплоя (когда на одном сервере деплой прошел, а на другом — нет) используйте настройки в плейбуке или CI.

1. **В плейбуке:**
    ```yaml
    - hosts: all
      any_errors_fatal: true # Остановка всего плейбука при ошибке на ЛЮБОМ хосте
      tasks:
        - name: Critical update
          ansible.builtin.apt: name=nginx state=latest
    ```
2. **В пайплайне:** Используйте `artifacts` для сохранения `deployment_report.json` для последующего анализа причин сбоя.

## Дополнительная информация

### Продвинутые техники

- **ansible-navigator:** Используйте для локальной отладки пайплайнов в тех же образах (EE), что и в GitLab CI.
- **Pull-модель (ansible-pull):** В больших инфраструктурах (1000+ узлов) GitLab Runner может только триггерить `ansible-pull` на целевых узлах, чтобы снять нагрузку с сети.

### Смотрите также

- **[Динамический инвентарь в Ansible](../../../Ansible/dynamic_inventory.md)** — глубокое погружение в плагины для облаков.
- **[Ansible Vault: Практические примеры](../../../Ansible/Vault/examples.md)** — методы шифрования в CI/CD.
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — детали работы с `Masked` и `File` переменными.
- **[Настройка GitLab Runner](../Advanced/gitlab_ci_runners_executors.md)** — оптимизация среды выполнения.
