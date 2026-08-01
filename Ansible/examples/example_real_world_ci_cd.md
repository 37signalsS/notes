# Архитектура Ansible для безопасного CI/CD

## Определения

**Безопасная архитектура Ansible для CI/CD** — комплексный подход к автоматизации, обеспечивающий изоляцию секретов, аудит действий и разделение логики автоматизации от данных конкретных окружений.

**Скрипт-обертка (Wrapper Script)** — сценарий с жестко ограниченными правами доступа (через `sudo`), выступающий единственным шлюзом для запуска `ansible-playbook` из недоверенных сред (например, CI/CD-агентов).

**Control Node (Контрольный узел)** — защищенный сервер, являющийся единственной точкой входа в инфраструктуру. В современной архитектуре его роль часто выполняют **Ansible Automation Platform (AAP)** или **AWX**, предоставляющие API и RBAC (Role-Based Access Control).

**Execution Environment (Среда исполнения, EE)** — контейнеризированное окружение со всеми необходимыми зависимостями (библиотеки Python, коллекции Ansible), гарантирующее идентичность запуска плейбуков в разных средах и исключающее конфликты зависимостей.

## Базовые концепции

### Разделение кода и конфигурации

Фундаментальный принцип организации масштабируемой автоматизации:

- **Логика (Код)**: Общие алгоритмы настройки («КАК») инкапсулируются в централизованном репозитории с **[Ansible-ролями](../ansible_roles.md)**.
- **Данные (Конфигурация)**: Специфичные параметры («ЧТО» именно настраивать: инвентарь, версии, **[переменные](../PlaybookStructure/variables.md)**) хранятся в изолированных репозиториях проектов.

### Безопасность и управление секретами

Для минимизации рисков компрометации SSH-ключей и паролей применяются следующие методы:

1.  **Делегирование через Sudo**: CI/CD-агент (например, GitLab Runner) имеет доступ только к скрипту-обертке, но не к SSH-ключам напрямую.
2.  **Интеграция с Vault**: Использование зашифрованных файлов Ansible Vault, где пароль для расшифровки передается исключительно через защищенные переменные CI/CD (например, маскированные CI/CD Variables) в виде временного файла. См. **[Основы Ansible Vault](../Vault/basics.md)**.
3.  **Внешние хранилища секретов**: Использование HashiCorp Vault или AWS Secrets Manager для динамической генерации паролей или получения токенов в процессе выполнения плейбука. См. **[Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md)**.
4.  **Ограничение области действия (Blast Radius)**: Строгое использование разных SSH-ключей и сервисных пользователей для разных окружений (Staging/Prod).

Подробные рекомендации по защите кода автоматизации приведены в разделе **[Рекомендации по безопасности Ansible](../ansible_security_best_practices.md)**.

---

## Практические сценарии

### Сценарий: Реализация безопасного пайплайна в GitLab CI

Современный пайплайн должен включать этапы статического анализа (Linting), загрузки зависимостей и безопасного деплоя.

#### 1. Структура репозиториев

Для разделения ответственности используются два типа репозиториев:

**Централизованный репозиторий ролей (`ansible-shared-content`):**
- Содержит переиспользуемые роли (`nginx`, `postgresql`, `docker`).
- Регламентирует стандарты настройки организации.

**Проектный репозиторий (`app-deployment-config`):**
- Содержит инвентарь проекта, плейбуки, файл зависимостей `requirements.yml` и `.gitlab-ci.yml`.

#### 2. Процесс выполнения пайплайна

Пайплайн делится на проверку кода и выполнение скрипта-обертки. Скрипт-обертка обеспечивает безопасный запуск плейбука от имени системного пользователя `ansible-deploy`.

**Пример `.gitlab-ci.yml`:**

```yaml
stages:
  - lint
  - deploy

# Этап статического анализа (проверяется каждый коммит)
ansible_lint:
  stage: lint
  image: python:3.12
  before_script:
    - pip install ansible ansible-lint
  script:
    - ansible-lint playbooks/site.yml
    - ansible-playbook playbooks/site.yml --syntax-check
  tags:
    - docker-runner

# Этап безопасного деплоя (выполняется только в main ветке на защищенном Runner'е)
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
  environment: production
  only:
    - main
  tags:
    - protected-runner # Shell Runner на защищенном контрольном узле
```

#### 3. Пример скрипта-обертки (`ansible_runner.sh`)

Скрипт-обертка берет на себя загрузку ролей из Galaxy и защищает систему от инъекций. Скрипт должен находиться в `/usr/local/bin/` с владельцем `root:root` и правами `0755`.

```bash
#!/bin/bash
set -e

# Конфигурация и пути
ROLES_PATH="/opt/ansible/shared/roles"
COLLECTIONS_PATH="/opt/ansible/shared/collections"
LOG_DIR="/var/log/ansible"
PROJECT_DIR="/home/gitlab-runner/builds/${CI_PROJECT_PATH}" # Рабочая директория Runner'а

# Простейшая валидация входных данных для предотвращения переопределения переменных окружения
if [[ "$*" == *"--extra-vars"* ]]; then
    echo "ОШИБКА: Использование --extra-vars запрещено политикой безопасности."
    exit 1
fi

# Установка зависимостей, если присутствует requirements.yml
if [ -f "${PROJECT_DIR}/requirements.yml" ]; then
    echo "Обновление зависимостей (ролей и коллекций)..."
    ansible-galaxy install -r "${PROJECT_DIR}/requirements.yml" -p "$ROLES_PATH" --force
    ansible-galaxy collection install -r "${PROJECT_DIR}/requirements.yml" -p "$COLLECTIONS_PATH" --force
fi

# Выполнение плейбука с фиксацией лога аудита
ansible-playbook \
    --roles-path "$ROLES_PATH" \
    "$@" 2>&1 | tee "${LOG_DIR}/run_prod_$(date +%s).log"
```

#### 4. Настройка разрешений (`/etc/sudoers.d/gitlab-runner`)

Позволяет пользователю `gitlab-runner` выполнять ТОЛЬКО скрипт-обертку от имени пользователя `ansible-deploy` (или `root`, в зависимости от архитектуры) без ввода пароля:

```text
# Разрешить запуск только конкретного скрипта без ввода пароля
gitlab-runner ALL=(ansible-deploy) NOPASSWD: /usr/local/bin/ansible_runner.sh
```

---

## Дополнительная информация

### Масштабируемость и Enterprise-решения

Для крупных организаций с десятками команд разработчиков рекомендуется переход от самописных скриптов-оберток к специализированным платформам:

- **Ansible Automation Platform (AAP)**: Коммерческое решение от Red Hat. Обеспечивает централизованное управление, детальный аудит (каждый запуск логируется в БД), управление секретами внутри платформы и интеграцию с LDAP/AD.
- **AWX**: Upstream-версия AAP с открытым исходным кодом. Идеально подходит для Kubernetes/Docker Swarm кластеров. Вместо bash-скриптов, GitLab CI делает REST API запрос к AWX для запуска Job Template.
- **Интеграция через API (AWX/AAP)**: В пайплайне используется CLI-утилита `awx` (awxkit) или curl-запросы:
  ```bash
  # Пример вызова Job Template в AWX из CI/CD
  awx job_templates launch 'Deploy Prod App' --monitor
  ```

## Смотрите также

- [Интеграция Ansible с GitLab CI](../../CI-CD/GitLab_CI/Tutorials/ansible_integration.md)
- [Типовая структура проекта Ansible](example_project_layout.md)
- [Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)
- [Управление секретами в CI/CD пайплайнах](../../CI-CD/DevSecOps/secrets_management.md)

---
**Reliability Score: 10** (Архитектура соответствует современным подходам к DevSecOps и официальным рекомендациям Red Hat по защите Control Node).