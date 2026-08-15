# Архитектура Ansible для безопасного CI/CD

## Определения

**Безопасная архитектура Ansible для CI/CD** — комплексный подход к автоматизации, обеспечивающий изоляцию секретов, аудит действий и разделение логики автоматизации от данных конкретных окружений.

**Скрипт-обертка (Wrapper Script)** — сценарий с жестко ограниченными правами доступа (через `sudo`), выступающий единственным шлюзом для запуска `ansible-playbook` из недоверенных сред (например, CI/CD-агентов). Он предотвращает инъекцию произвольных аргументов и ограничивает область видимости инвентаря.

**Control Node (Контрольный узел)** — защищенный сервер, являющийся единственной точкой входа в инфраструктуру. В современной архитектуре его роль часто выполняют **[Ansible Automation Platform (AAP)](../ansible-automation-platform.md)** или **AWX**, предоставляющие API и RBAC (Role-Based Access Control).

**Execution Environment (Среда исполнения, EE)** — контейнеризированное окружение (образ), содержащее Ansible Core, коллекции и Python-зависимости. Гарантирует идентичность запуска плейбуков в разных средах и исключает конфликты библиотек.

**OIDC (OpenID Connect) / Workload Identity** — протокол аутентификации, позволяющий CI/CD-пайплайнам (GitLab CI, GitHub Actions) получать временные токены доступа к менеджерам секретов (HashiCorp Vault) или облачным провайдерам без использования статических паролей.

## Базовые концепции

### Разделение кода и конфигурации

Фундаментальный принцип организации масштабируемой автоматизации:

- **Логика (Код)**: Общие алгоритмы настройки («КАК») инкапсулируются в централизованном репозитории с **[Ansible-ролями](../ansible_roles.md)**.
- **Данные (Конфигурация)**: Специфичные параметры («ЧТО» именно настраивать: инвентарь, версии, **[переменные](../PlaybookStructure/variables.md)**) хранятся в изолированных репозиториях проектов.

### Безопасность и управление секретами

Для минимизации рисков компрометации SSH-ключей и паролей применяются следующие методы:

1.  **Делегирование через Sudo**: CI/CD-агент (например, GitLab Runner) имеет доступ только к скрипту-обертке, но не к SSH-ключам напрямую.
2.  **Интеграция с Vault**: Использование зашифрованных файлов Ansible Vault, где пароль передается исключительно через защищенные переменные CI/CD (например, маскированные `id_tokens` или временные файлы). См. **[Основы Ansible Vault](../Vault/basics.md)**.
3.  **Использование OIDC (Keyless)**: Современный стандарт, при котором Vault доверяет JWT-токену, сгенерированному CI-системой, исключая хранение "Secret Zero" (мастер-пароля) в переменных.
4.  **Внешние хранилища секретов**: Использование HashiCorp Vault или AWS Secrets Manager для динамической генерации паролей или получения токенов в процессе выполнения. См. **[Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md)**.
5.  **Ограничение области действия (Blast Radius)**: Строгое использование разных SSH-ключей и сервисных пользователей для разных окружений (Staging/Prod).

---

## Практические сценарии

### Сценарий 1: Реализация безопасного пайплайна в GitLab CI

Современный пайплайн включает этапы линтинга, проверки синтаксиса и безопасного деплоя через скрипт-обертку.

#### 1. Структура репозиториев

**Централизованный репозиторий ролей (`ansible-shared-content`):**
- Содержит переиспользуемые роли (`nginx`, `postgresql`, `docker`).
- Регламентирует стандарты настройки организации.

**Проектный репозиторий (`app-deployment-config`):**
- Содержит инвентарь проекта, плейбуки, файл зависимостей `requirements.yml` и `.gitlab-ci.yml`.

#### 2. Пример `.gitlab-ci.yml`

```yaml
stages:
  - lint
  - deploy

# Этап статического анализа
ansible_lint:
  stage: lint
  image: quay.io/ansible/creator-ee:latest
  script:
    - ansible-lint playbooks/site.yml
    - ansible-playbook playbooks/site.yml --syntax-check
  tags: [docker-runner]

# Этап безопасного деплоя
deploy_prod:
  stage: deploy
  variables:
    # Имя файла, куда GitLab CI сохранит значение защищенной переменной $VAULT_PASSWORD_PROD
    VAULT_PASS_FILE: "/tmp/.vault_pass_${CI_JOB_ID}"
  before_script:
    - echo "$VAULT_PASSWORD_PROD" > $VAULT_PASS_FILE
    - chmod 600 $VAULT_PASS_FILE
  script:
    - sudo /usr/local/bin/ansible_runner.sh --playbook playbooks/site.yml --limit production --vault-password-file $VAULT_PASS_FILE
  after_script:
    - rm -f $VAULT_PASS_FILE
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  tags: [protected-runner] # Shell Runner на защищенном контрольном узле
```

#### 3. Пример скрипта-обертки (`ansible_runner.sh`)

Скрипт должен находиться в `/usr/local/bin/` с владельцем `root:root` и правами `0755`.

```bash
#!/bin/bash
set -e

# Конфигурация
ROLES_PATH="/opt/ansible/shared/roles"
COLLECTIONS_PATH="/opt/ansible/shared/collections"
LOG_DIR="/var/log/ansible"
PROJECT_DIR="/home/gitlab-runner/builds/${CI_PROJECT_PATH}"

# Валидация аргументов
if [[ "$*" == *"--extra-vars"* ]]; then
    echo "ОШИБКА: Использование --extra-vars запрещено политикой безопасности."
    exit 1
fi

# Установка зависимостей (Idempotent)
if [ -f "${PROJECT_DIR}/requirements.yml" ]; then
    ansible-galaxy install -r "${PROJECT_DIR}/requirements.yml" -p "$ROLES_PATH"
    ansible-galaxy collection install -r "${PROJECT_DIR}/requirements.yml" -p "$COLLECTIONS_PATH"
fi

# Выполнение с аудитом
ansible-playbook \
    --roles-path "$ROLES_PATH" \
    "$@" 2>&1 | tee "${LOG_DIR}/run_$(date +%Y%m%d_%H%M%S).log"
```

#### 4. Настройка разрешений (`/etc/sudoers.d/gitlab-runner`)

```text
# Разрешить запуск только конкретного скрипта без ввода пароля
gitlab-runner ALL=(ansible-deploy) NOPASSWD: /usr/local/bin/ansible_runner.sh
```

### Сценарий 2: Использование Execution Environments в GitHub Actions

Если политика безопасности позволяет запуск из облачного CI, используйте контейнеризированные среды (EE).

**Пример `.github/workflows/deploy.yml`:**

```yaml
name: Ansible EE Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    container:
      image: my-registry.com/ansible-ee:v1.2
    steps:
      - uses: actions/checkout@v4
      - name: Run Playbook
        run: |
          # Использование OIDC токена для расшифровки Vault (концептуально)
          ansible-playbook site.yml -i inventory/prod.yml --vault-password-file <(echo "${{ secrets.VAULT_PASS }}")
        env:
          ANSIBLE_HOST_KEY_CHECKING: "False"
```

---

## Дополнительная информация

### Управление средами исполнения (EE)

Для создания EE используется утилита `ansible-builder`. Это позволяет зафиксировать версии всех зависимостей.

**Пример `execution-environment.yml`:**
```yaml
version: 3
images:
  base_image:
    name: quay.io/fedora/fedora:latest
dependencies:
  ansible_core:
    package_pip: ansible-core==2.17
  ansible_collections:
    - name: community.postgresql
  python:
    - psycopg2-binary
```

### Масштабируемость и Enterprise-решения

Для крупных организаций рекомендуется переход к специализированным платформам (см. подробнее **[Ansible Automation Platform (AAP)](../ansible-automation-platform.md)**):

- **Ansible Automation Platform (AAP)**: Коммерческое решение от Red Hat. Обеспечивает централизованное управление, детальный аудит (каждый запуск логируется в БД), управление секретами внутри платформы и интеграцию с LDAP/AD.
- **AWX**: Upstream-версия AAP с открытым исходным кодом. Вместо bash-скриптов, CI/CD делает REST API запрос к AWX для запуска Job Template:
  ```bash
  # Пример вызова Job Template в AWX из CI/CD
  awx job_templates launch 'Deploy Prod App' --monitor
  ```

## Смотрите также

- [Интеграция Ansible с GitLab CI](../../CI-CD/GitLab_CI/Tutorials/ansible_integration.md)
- [Типовая структура проекта Ansible](example_project_layout.md)
- [Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)
- [Управление секретами в CI/CD пайплайнах](../../CI-CD/DevSecOps/secrets_management.md)
- [Ansible Execution Environments (Official)](https://docs.ansible.com/ansible/latest/getting_started_ee/index.html)
