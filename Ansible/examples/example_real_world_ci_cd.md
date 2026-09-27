# Архитектура Ansible для безопасного CI/CD

## Определения

**Безопасная архитектура Ansible для CI/CD** — систематический подход к интеграции автоматизации конфигураций в конвейеры непрерывной интеграции и доставки (CI/CD), обеспечивающий изоляцию секретов, аудит выполнения и строгое разделение логики автоматизации от данных окружений. Архитектура построена на принципах наименьших привилегий (Least Privilege) и недоверенного выполнения (Untrusted Execution).

**Скрипт-обертка (Wrapper Script)** — исполняемый файл с жестко ограниченными правами доступа через `sudo`, выступающий единственным шлюзом для запуска `ansible-playbook` из CI/CD-агентов. Он предотвращает инъекцию произвольных аргументов (например, `--extra-vars`), ограничивает область видимости инвентаря и обеспечивает централизованное аудирование всех запусков.

**Control Node (Контрольный узел)** — защищенный сервер или контейнер Execution Environment, являющийся единственной точкой входа для выполнения автоматизации. В архитектуре CI/CD его роль выполняет изолированный раннер (GitLab Runner) с правами на запуск только скрипта-обертки.

**Execution Environment (Среда исполнения, EE)** — стандартизированный OCI-контейнер, содержащий Ansible Core, коллекции и Python-зависимости. Гарантирует идентичность запуска плейбуков в локальной разработке, CI/CD и production, исключая проблемы "dependency hell".

**OIDC (OpenID Connect) / Workload Identity** — протокол аутентификации, позволяющий CI/CD-пайплайнам получать временные JWT-токены для доступа к HashiCorp Vault без использования статических паролей ("Secret Zero"). Токен подписывается CI-платформой и имеет ограниченный срок жизни.

**AppRole** — метод аутентификации в HashiCorp Vault для машин и скриптов, использующий пару `RoleID` и `SecretID`. Подходит для CI/CD-пайплайнов, где OIDC недоступен, и обеспечивает минимально привилегированный доступ к секретам.

**ansible-lint** — утилита статического анализа плейбуков и ролей Ansible, выявляющая нарушения лучших практик, синтаксические ошибки и потенциальные проблемы безопасности. Используется как блокирующая стадия в CI/CD-пайплайнах.

**no_log** — параметр задачи Ansible, скрывающий чувствительные данные (пароли, ключи, токены) из логов выполнения. Обязателен для всех задач, обрабатывающих секреты.

**Masked Variables** — функция CI/CD-систем, автоматически заменяющая значение защищенной переменной на `[MASKED]` в логах пайплайна для предотвращения утечки учетных данных.

**Protected Runners** — специализированные раннеры CI/CD, доступные только для защищенных веток (main, production), обеспечивающие изоляцию деплоев в production от недоверенных коммитов.

## Базовые концепции

### Архитектура и принципы работы

Безопасная архитектура CI/CD для Ansible строится на четырех уровнях изоляции:

1. **Уровень CI/CD-платформы** — GitLab CI (self-hosted) или аналогичные системы, запускающие пайплайн. Пайплайн не имеет прямого доступа к целевым серверам или секретам.
2. **Уровень Control Node** — защищенный сервер (раннер) с установленным скриптом-оберткой. Все вызовы Ansible проходят через него. Раннер имеет доступ только к одному скрипту через `sudo` и не имеет доступа к SSH-ключам напрямую.
3. **Уровень секретов** — HashiCorp Vault, предоставляющий временные учетные данные через OIDC или AppRole. Статические пароли не хранятся в CI/CD-переменных.
4. **Уровень целевых хостов** — серверы, доступные только по SSH из Control Node. Каждое окружение (staging/production) использует отдельный SSH-ключ и сервисного пользователя.

**Ключевой принцип:** CI/CD-агент вызывает скрипт-обертку → скрипт-обертка вызывает Ansible → Ansible получает секреты из Vault → изменения применяются к целевым хостам. Ни один компонент не имеет прямого доступа ко всему пути.

### Версии и совместимость

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 2.20 | `ansible --version` |
| Python (управление) | 3.10+ | ≥ 3.12 | `python3 --version` |
| Python (целевые хосты) | 3.10+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` |
| ansible-lint | 26.x+ | ≥ 26.8.0 | `ansible-lint --version` |
| ansible-builder | 3.0+ | 3.0+ | `ansible-builder --version` |
| ansible-navigator | 4.x+ | 4.x+ | `ansible-navigator --version` |
| GitLab CI | 16.0+ | 16.0+ | `gitlab-runner --version` |
| HashiCorp Vault | 1.15+ | 1.15+ | `vault --version` |

### Структура репозитория

Рекомендуемая структура для проекта Ansible + CI/CD:

```text
ansible-ci-cd/
├── ansible.cfg
├── requirements.yml               # Зависимости (роли и коллекции)
├── execution-environment.yml      # Конфигурация EE
├── .ansible-lint                  # Правила статического анализа
├── .gitlab-ci.yml                 # Конфигурация GitLab CI
├── inventory/
│   ├── production/
│   │   ├── hosts.yml
│   │   └── group_vars/
│   │       ├── all.yml
│   │       └── vault.yml          # Зашифрованные секреты
│   └── staging/
├── playbooks/
│   ├── site.yml
│   ├── deploy.yml
│   └── rolling_deploy.yml
├── roles/
│   ├── common/
│   ├── nginx/
│   └── postgresql/
└── group_vars/
    └── all/
        └── vault.yml              # Зашифрованные секреты
```

### Разделение кода и конфигурации

Фундаментальный принцип организации масштабируемой автоматизации:

- **Логика (Код):** Общие алгоритмы настройки ("КАК") инкапсулируются в централизованном репозитории с **[Ansible-ролями](../ansible_roles.md)**.
- **Данные (Конфигурация):** Специфичные параметры ("ЧТО" именно настраивать: инвентарь, версии, **[переменные](../PlaybookStructure/variables.md)**) хранятся в изолированных репозиториях проектов.

### Безопасность и управление секретами

Для минимизации рисков компрометации SSH-ключей и паролей применяются следующие методы:

1. **Делегирование через Sudo:** CI/CD-агент (GitLab Runner) имеет доступ только к скрипту-обертке, но не к SSH-ключам напрямую.
2. **Интеграция с Vault:** Использование зашифрованных файлов Ansible Vault, где пароль передается исключительно через защищенные переменные CI/CD (маскированные файловые переменные). См. **[Основы Ansible Vault](../Vault/basics.md)**.
3. **OIDC (Keyless):** Современный стандарт, при котором Vault доверяет JWT-токену, сгенерированному CI-системой, исключая хранение "Secret Zero" в переменных.
4. **AppRole:** Метод аутентификации для сред, где OIDC недоступен. Использует пару `RoleID`/`SecretID` с ограниченным сроком жизни.
5. **Ограничение области действия (Blast Radius):** Строгое использование разных SSH-ключей и сервисных пользователей для разных окружений (Staging/Prod).

### Переменные окружения Ansible в CI/CD

Для повышения производительности и улучшения читаемости логов рекомендуется настраивать переменные окружения:

| Переменная | Описание | Рекомендуемое значение |
|---|---|---|
| `ANSIBLE_FORCE_COLOR` | Принудительное включение цветного вывода | `"true"` |
| `ANSIBLE_STDOUT_CALLBACK` | Формат вывода задач | `"yaml"` или `"debug"` |
| `ANSIBLE_PIPELINING` | Ускорение за счет уменьшения SSH-соединений | `"True"` (требует отключения `requiretty` в sudoers) |
| `ANSIBLE_HOST_KEY_CHECKING` | Проверка SSH-ключей новых хостов | `"False"` (только для доверенных/эфемерных сетей) |
| `ANSIBLE_TIMEOUT` | Таймаут подключения к хостам | `"30"` |
| `ANSIBLE_RETRIES_FILES` | Отключение файлов `.retry` | `"False"` |

### Сравнение CI/CD платформ для Ansible

| Критерий | GitLab CI (Self-hosted) | AWX/AAP |
|---|---|---|
| **Хостинг** | Self-hosted | Self-hosted |
| **OIDC / ID Tokens** | Встроенная поддержка | Встроенная (JWT) |
| **Execution Environments** | Через Docker-образы | Нативная поддержка |
| **Аудит** | История пайплайнов | Детальный аудит (БД) |
| **RBAC** | Ограниченный | Полный (Organizations → Teams → Users) |
| **Стоимость** | Open Source (CE) / Enterprise | Open Source (AWX) / Коммерческая (AAP) |

---

## Практические сценарии

### Сценарий 1: Скрипт-обертка и безопасный деплой в GitLab CI

Самый распространенный паттерн: CI/CD-агент вызывает скрипт-обертку, который выполняет Ansible с жестко ограниченными правами.

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

ansible_lint:
  stage: lint
  image: python:3.12-slim
  before_script:
    - pip install ansible-lint ansible-core
  script:
    - ansible-lint playbooks/ --profile=production -p
    - ansible-playbook playbooks/site.yml --syntax-check
  tags: [docker-runner]

deploy_prod:
  stage: deploy
  variables:
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
  tags: [protected-runner]
```

#### 3. Пример скрипта-обертки (`/usr/local/bin/ansible_runner.sh`)

Скрипт должен находиться в `/usr/local/bin/` с владельцем `root:root` и правами `0755`.

```bash
#!/bin/bash
set -euo pipefail

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

**Валидация:**

```bash
# Проверка прав скрипта-обертки
ls -la /usr/local/bin/ansible_runner.sh
# → -rwxr-xr-x 1 root root 1024 ... /usr/local/bin/ansible_runner.sh

# Проверка sudoers
sudo -l -U gitlab-runner
# → User gitlab-runner may run the following commands on this host:
# → (ansible-deploy) NOPASSWD: /usr/local/bin/ansible_runner.sh

# Проверка блокировки --extra-vars
sudo -u ansible-deploy /usr/local/bin/ansible_runner.sh --playbook site.yml --extra-vars "test=1"
# → ОШИБКА: Использование --extra-vars запрещено политикой безопасности.
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `sudo: no tty present and no askpass program specified` | GitLab Runner не имеет доступа к sudo | Убедитесь, что файл `/etc/sudoers.d/gitlab-runner` существует и содержит правильное правило. |
| `ERROR! the role 'xxx' was not found` | Роли не установлены на Runner | Проверьте, что `requirements.yml` корректен и `ansible-galaxy install` выполняется в скрипте-обертке. |
| `Vault password error` | Неверный пароль или переменная не определена | Проверьте переменную `VAULT_PASSWORD_PROD` в настройках GitLab CI/CD. |
| `Permission denied: ansible_runner.sh` | Скрипт не имеет прав на выполнение | `sudo chmod +x /usr/local/bin/ansible_runner.sh` и `sudo chown root:root`. |

### Сценарий 2: Сборка Execution Environment через ansible-builder

Для проектов, требующих кастомных зависимостей, рекомендуется собирать собственный EE.

#### 1. Конфигурация `execution-environment.yml`

```yaml
version: 3

images:
  base_image:
    name: registry.example.com/ansible/ansible-runner:latest

dependencies:
  ansible_core:
    package_pip: ansible-core>=2.20.0
  ansible_runner:
    package_pip: ansible-runner
  galaxy:
    collections:
      - name: community.general
      - name: community.postgresql
      - name: ansible.posix
  python:
    - psycopg2-binary
  system:
    - git
    - openssh-clients

additional_build_steps:
  append_final:
    - RUN alternatives --set python /usr/bin/python3
```

#### 2. Сборка образа

```bash
# Сборка локально
ansible-builder build -t registry.example.com/ansible-ee:v1.2

# Проверка содержимого образа
ansible-runner container list
# → IMAGE ID     IMAGE NAME
# → abc123def45  registry.example.com/ansible-ee:v1.2
```

#### 3. Использование в GitLab CI

```yaml
deploy_ee:
  stage: deploy
  image: registry.example.com/ansible-ee:v1.2
  script:
    - ansible-playbook /workspace/site.yml -i /workspace/inventory/prod.yml
  tags: [protected-runner]
```

**Валидация:**

```bash
# Проверка сборки
ansible-builder build --tag my-ee:test --container-runtime podman
# → Complete! Build Python or System package dependencies... DONE
# → Complete! Build Collection dependencies... DONE

# Проверка зависимостей внутри образа
podman run --rm registry.example.com/ansible-ee:v1.2 \
  ansible-galaxy collection list
# → Collection        Version
# → ----------------  -------
# → community.general x.y.z
# → community.postgresql x.y.z

# Проверка версии Ansible Core
podman run --rm registry.example.com/ansible-ee:v1.2 \
  ansible --version
# → ansible [core 2.20.x]
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `ERROR: Cannot find collection` | Коллекция не указана в `execution-environment.yml` | Добавьте коллекцию в секцию `dependencies.galaxy.collections`. |
| `pip install failed` | Конфликт версий Python-пакетов | Используйте `requirements.txt` для явного указания версий. |
| `Container image build failed` | Нет доступа к базовому образу | Проверьте доступность внутреннего registry или используйте альтернативный базовый образ. |

### Сценарий 3: Локальная отладка через ansible-navigator

Для обеспечения идентичности среды выполнения между локальной разработкой и CI/CD используйте `ansible-navigator`.

```bash
# Установка
pip install ansible-navigator

# Запуск плейбука в EE
ansible-navigator run playbooks/site.yml \
  --ee-image registry.example.com/ansible-ee:v1.2 \
  --ee-enable \
  --mode stdout

# Интерактивный режим (TUI)
ansible-navigator run playbooks/site.yml \
  --ee-image registry.example.com/ansible-ee:v1.2 \
  --ee-enable \
  --mode interactive

# Просмотр содержимого EE
ansible-navigator container list
ansible-navigator collection list
ansible-navigator requirements list --ee-image registry.example.com/ansible-ee:v1.2
```

**Валидация:**

```bash
# Проверка версии
ansible-navigator --version
# → ansible-navigator 4.x.x

# Проверка конфигурации
ansible-navigator configuration dump --mode stdout | grep container_engine
# → container_engine='podman'
```

### Сценарий 4: Обработка ошибок и восстановление в CI/CD

Для предотвращения частичного деплоя и обеспечения консистентности инфраструктуры.

#### 1. В плейбуке: `any_errors_fatal` и `block/rescue/always`

```yaml
- hosts: web_servers
  any_errors_fatal: true
  tasks:
    - name: Критическая миграция
      block:
        - name: Выполнение миграции
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;"
          become_user: postgres

        - name: Перезапуск приложения
          ansible.builtin.systemd:
            name: myapp
            state: restarted

      rescue:
        - name: Откат при ошибке
          community.postgresql.postgresql_query:
            db: "{{ db_name }}"
            query: "ALTER TABLE users DROP COLUMN IF EXISTS email;"
          become_user: postgres

      always:
        - name: Сбор логов
          ansible.builtin.fetch:
            src: /var/log/myapp/app.log
            dest: "logs/{{ inventory_hostname }}/"
            flat: true
          ignore_errors: true
```

#### 2. В CI/CD: артефакты и уведомления

```yaml
deploy_prod:
  script:
    - ansible-playbook site.yml --extra-vars "ansible_callback_whitelist=json"
  artifacts:
    paths:
      - deployment_report.json
      - logs/
    when: always
    expire_in: 7 days
  after_script:
    - |
      if [ "$CI_JOB_STATUS" == "failed" ]; then
        curl -X POST "$SLACK_WEBHOOK" \
          -d "{\"text\": \"FAILED: $CI_PIPELINE_URL\"}"
      fi
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| Частичный деплой (некоторые хосты обновлены) | Нет `any_errors_fatal` или `serial` | Добавьте `any_errors_fatal: true` или `serial: 1` для последовательного обновления. |
| Артефакты не собираются | Артефакты в `after_script` при ошибке | Используйте `when: always` для `artifacts`. |
| Уведомление не отправляется | `SLACK_WEBHOOK` не определен | Проверьте переменную в настройках CI/CD. |

---

## Операции и команды

### Основные команды управления проектом

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml --syntax-check` | Проверка синтаксиса YAML | `ansible-playbook playbooks/site.yml --syntax-check` |
| `ansible-playbook playbook.yml --check --diff` | Dry-run с показом изменений | `ansible-playbook playbooks/site.yml --check --diff` |
| `ansible-playbook playbook.yml --list-tasks` | Просмотр задач без выполнения | `ansible-playbook playbooks/site.yml --list-tasks` |
| `ansible-playbook playbook.yml --list-tags` | Просмотр тегов | `ansible-playbook playbooks/site.yml --list-tags` |
| `ansible-playbook playbook.yml --list-hosts` | Просмотр хостов | `ansible-playbook playbooks/site.yml --list-hosts` |
| `ansible-playbook playbook.yml --step` | Пошаговое выполнение | `ansible-playbook playbooks/site.yml --step` |
| `ansible-playbook playbook.yml --start-at-task` | Запуск с конкретной задачи | `ansible-playbook playbooks/site.yml --start-at-task="Deploy"` |
| `ansible-inventory --graph` | Визуализация инвентаря | `ansible-inventory -i environments/prod/hosts.yml --graph` |
| `ansible-inventory --host` | Переменные хоста | `ansible-inventory -i environments/prod/hosts.yml --host web1` |
| `ansible <host> -m setup` | Сбор фактов | `ansible web1 -m setup -a "filter=ansible_distribution"` |
| `ansible <host> -m debug` | Просмотр переменной | `ansible web1 -m debug -a "var=my_var"` |
| `ansible <host> -m ping` | Проверка доступности | `ansible all -m ping` |

### Команды для работы с секретами

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-vault create <file>` | Создание зашифрованного файла | `ansible-vault create group_vars/all/vault.yml` |
| `ansible-vault edit <file>` | Редактирование зашифрованного файла | `ansible-vault edit group_vars/all/vault.yml` |
| `ansible-vault encrypt <file>` | Зашифровывает существующий файл | `ansible-vault encrypt group_vars/prod/vault.yml` |
| `ansible-vault decrypt <file>` | Расшифровывает файл | `ansible-vault decrypt group_vars/prod/vault.yml --ask-vault-pass` |
| `ansible-vault view <file>` | Просмотр содержимого без записи | `ansible-vault view group_vars/prod/vault.yml --vault-password-file .vault_pass` |
| `ansible-vault encrypt_string` | Шифрование отдельной строки | `ansible-vault encrypt_string 'secret' --name 'db_password'` |

### Команды специфичные для Execution Environment

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-builder build` | Сборка EE образа | `ansible-builder build -t registry.example.com/ansible-ee:v1.2` |
| `ansible-builder create` | Генерация Dockerfile без сборки | `ansible-builder create --output-dir ./containerfiles` |
| `ansible-navigator run` | Запуск плейбука в EE | `ansible-navigator run playbooks/site.yml --ee-enable` |
| `ansible-navigator collection list` | Просмотр коллекций в EE | `ansible-navigator collection list --ee-image registry.example.com/ansible-ee:v1.2` |
| `podman images` | Список локальных образов | `podman images | grep ansible-ee` |
| `podman inspect` | Детали образа | `podman inspect registry.example.com/ansible-ee:v1.2` |

### Валидация качества кода

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml --syntax-check` | Проверка синтаксиса YAML | `ansible-playbook playbooks/site.yml --syntax-check` |
| `ansible-lint playbooks/` | Проверка качества кода | `ansible-lint playbooks/ --profile=production` |
| `ansible-lint --fix` | Автоисправление нарушений | `ansible-lint playbooks/ --fix` |
| `yamllint .` | Проверка синтаксиса YAML | `yamllint .` |

---

## Устранение типичных неполадок

### Проблема: Роль не найдена при вызову

**Симптом:** `ERROR! the role 'geerlingguy.postgresql' was not found`.

**Решение:**
```bash
# Проверка установленных ролей
ansible-galaxy role list

# Установка роли
ansible-galaxy role install geerlingguy.postgresql

# Проверка структуры роли
ls -la roles/geerlingguy.postgresql/
# → defaults/ handlers/ tasks/ templates/ meta/ files/
```

### Проблема: Драйвер Python не найден

**Симптом:** `ERROR! No module named 'psycopg2'`.

**Решение:**
```bash
# Установка драйвера на целевой хост (Debian/Ubuntu)
ansible postgres -m ansible.builtin.apt -a "name=python3-psycopg2 state=present" --become

# Установка драйвера на целевой хост (RHEL)
ansible postgres -m ansible.builtin.yum -a "name=python3-psycopg2 state=present" --become

# Установка драйвера на контроллер
pip install "psycopg[binary]"
```

### Проблема: Vault password file не найден

**Симптом:** `ERROR! A Vault password is required` или `Decryption failed`.

**Решение:**
```bash
# Проверка зашифрованного файла
ansible-vault view group_vars/all/vault.yml --ask-vault-pass

# Проверка Vault ID в заголовке
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Запуск с правильным Vault ID
ansible-playbook site.yml --vault-id prod@.vault_pass
```

### Проблема: Задачи выполняются дважды (нарушение идемпотентности)

**Симптом:** Повторные запуски показывают `changed` там, где ожидается `ok`.

**Решение:**
```bash
# Проверка идемпотентности
ansible-playbook playbooks/site.yml --check --diff

# Второй запуск должен показать changed=0
ansible-playbook playbooks/site.yml 2>&1 | grep "changed="
# → localhost                  : ok=XX   changed=0    unreachable=0    failed=0
```

### Проблема: Обработчик не выполняется

**Симптом:** `notify: Restart PostgreSQL` не срабатывает при изменении конфигурации.

**Решение:**
```bash
# Проверка, что notify привязан к задаче
# В плейбуке:
# - name: Копирование конфигурации
#   ansible.builtin.template:
#     src: postgresql.conf.j2
#     dest: /etc/postgresql/16/main/postgresql.conf
#   notify: Restart PostgreSQL   # ← Должно быть на одном уровне с задачей

# Проверка обработчиков
ansible-playbook playbooks/site.yml --list-handlers

# Принудительный запуск обработчиков
ansible-playbook playbooks/site.yml --handlers-first
```

### Проблема: Деплой останавливается на первом хосте

**Симптом:** Плейбук завершается с ошибкой после первого неудачного хоста, остальные хосты не обрабатываются.

**Решение:**
```yaml
# Добавьте serial и/или max_fail_percentage
- hosts: webservers
  serial: "25%"
  max_fail_percentage: 10
  strategy: linear
  tasks:
    - name: Deploy
      ansible.builtin.include_tasks: deploy.yml
```

### Проблема: EE-образ не собирается

**Симптом:** `Container image build failed` или `Cannot find collection`.

**Решение:**
```bash
# Проверка базового образа
podman pull registry.example.com/ansible/ansible-runner:latest

# Проверка конфигурации EE
ansible-builder create --output-dir ./containerfiles

# Проверка Dockerfile
cat containerfiles/Dockerfile
```

---

## Рекомендации

### Best Practices

1. **Храните секреты в Vault:** Никогда не коммитьте пароли в открытом виде. Используйте `ansible-vault` с защищенным хранилищем паролей или внешние менеджеры секретов.
2. **Используйте FQCN:** Всегда указывайте полные имена модулей (`community.postgresql.postgresql_db` вместо `postgresql_db`) для совместимости между версиями Ansible и коллекций.
3. **Настраивайте `no_log: true`** для задач с секретами. Это предотвращает утечку данных в логи CI/CD.
4. **Проверяйте идемпотентность:** Второй запуск плейбука не должен вносить изменения (`changed=0`). Это подтверждает корректность декларативного подхода.
5. **Используйте `block/rescue/always`** вместо `ignore_errors: true` для осмысленной обработки ошибок.
6. **Документируйте переменные** в `README.md` проекта или в `defaults/main.yml` роли с комментариями.
7. **Выносите логику в роли:** Для повторного использования настройка сервисов должна быть оформлена как роль. Подробнее: **[Ansible: Роли](../ansible_roles.md)**.
8. **Используйте Execution Environments:** Для гарантии идентичности сред разработки и CI/CD. Подробнее: **[Среды выполнения Ansible](../ansible-execution-environments.md)**.
9. **Используйте `--check --diff`** перед первым запуском в production. Это позволяет увидеть точные изменения без риска.
10. **Валидируйте конфигурацию:** Всегда проверяйте синтаксис YAML и плейбуков через `ansible-playbook --syntax-check` и `ansible-lint`.

### Безопасность

- **Управление секретами:** Для защиты конфиденциальных данных (пароли, TLS-ключи) всегда используйте шифрование. Подробнее: **[Основы Ansible Vault](../Vault/basics.md)** и **[Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)**.
- **Минимизация привилегий:** Используйте `become_user: postgres` (или другой специализированный пользователь) для задач управления БД, чтобы не выполнять команды от имени суперпользователя ОС (`root`) внутри СУБД.
- **Изоляция CI/CD:** Используйте Protected Runners для production-деплоев. Разные окружения должны использовать разные SSH-ключи и сервисных пользователей.
- **Аудит:** Включайте детальное логирование всех запусков Ansible через callback-плагины (например, `json` или `yaml`).
- **Верификация зависимостей:** Проверяйте GPG-подписи коллекций и ролей, устанавливаемых через `ansible-galaxy`.

### Производительность и стабильность

- **Execution Environments:** Используйте EE для изоляции зависимостей и гарантии воспроизводимости запусков.
- **Параллельное выполнение:** Настройте `forks` в `ansible.cfg` (по умолчанию 5) в соответствии с мощностью Control Node.
- **Check Mode:** Модули Ansible поддерживают `check_mode`. Используйте `--check` для предварительной проверки изменений.
- **Кэширование зависимостей:** В CI/CD кэшируйте каталоги `.ansible/roles` и `.ansible/collections` для ускорения последующих запусков.
- **Connection Pipelining:** Включите `ANSIBLE_PIPELINING=True` для уменьшения количества SSH-соединений (требует отключения `requiretty` в sudoers).

---

## Дополнительная информация

### Смотрите также

- **[Интеграция Ansible с GitLab CI](../../CI-CD/GitLab_CI/Tutorials/ansible_integration.md)** — детальные паттерны GitLab CI: dynamic inventory, Vault, Inputs, rollback стратегии.
- **[Среды выполнения Ansible (Execution Environments)](../ansible-execution-environments.md)** — подробное руководство по созданию и использованию EE.
- **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)** — защита Control Node, управление секретами, CI/CD-интеграция.
- **[Event-Driven Ansible](../event-driven-ansible.md)** — автоматизация на основе событий с использованием EDA.

### Дополнительный сценарий: Интеграция Event-Driven Ansible (EDA) в CI/CD

EDA позволяет запускать плейбуки в ответ на события из внешних систем (GitHub/GitLab webhooks, Prometheus alerts, изменения в CMDB). В контексте CI/CD это обеспечивает автоматический деплой при мерже PR или срабатывании алертов.

```yaml
---
# playbooks/event_driven_deploy.yml
- name: Деплой при событии из EDA
  hosts: production
  become: true
  vars:
    app_version: "{{ event_data.tag | default('latest') }}"
    deploy_reason: "{{ event_data.reason | default('manual') }}"

  tasks:
    - name: Логирование причины деплоя
      ansible.builtin.debug:
        msg: "Deploy triggered by: {{ deploy_reason }}, version: {{ app_version }}"

    - name: Скачивание артефакта
      ansible.builtin.get_url:
        url: "https://releases.example.com/app-{{ app_version }}.tar.gz"
        dest: /tmp/app-{{ app_version }}.tar.gz

    - name: Распаковка артефакта
      ansible.builtin.unarchive:
        src: /tmp/app-{{ app_version }}.tar.gz
        dest: /opt/app
        remote_src: yes

    - name: Перезапуск приложения
      ansible.builtin.service:
        name: app
        state: restarted

    - name: Проверка работоспособности
      ansible.builtin.uri:
        url: http://localhost/health
        status_code: 200
        timeout: 10
      register: health_check
      until: health_check.status == 200
      retries: 30
      delay: 2
```

**Пример правила EDA (eda-rulebook.yml):**

```yaml
---
- name: Deploy on GitLab merge
  hosts: all
  sources:
    - name: gitlab
      type: gitlab
      config:
        webhook_url: "https://eda.internal/webhook"
        token: "{{ vault_gitlab_token }}"
        events:
          - Merge Request Hook
          - Push Hook
          - Tag Push Hook

  rules:
    - name: Deploy on merge to main
      condition: event.payload.object_attributes.target_branch == "main"
      action:
        run_playbook:
          name: playbooks/event_driven_deploy.yml
          extra_vars:
            event_data: "{{ event }}"

    - name: Deploy on tag
      condition: event.payload.ref == "refs/tags/v*"
      action:
        run_playbook:
          name: playbooks/event_driven_deploy.yml
          extra_vars:
            event_data:
              tag: "{{ event.payload.ref | regex_replace('refs/tags/', '') }}"
              reason: "tag_push"
```

**Запуск EDA Rulebook Agent:**

```bash
# Установка EDA
pip install ansible-rulebook

# Запуск rulebook
ansible-rulebook --rulebook eda-rulebook.yml --inventory inventory/prod/hosts.yml --vault-id prod@.vault_pass

# Или через systemd
cat > /etc/systemd/system/eda-agent.service << 'EOF'
[Unit]
Description=Ansible EDA Agent
After=network.target

[Service]
ExecStart=/usr/local/bin/ansible-rulebook --rulebook /etc/ansible/eda-rulebook.yml --inventory /etc/ansible/inventory/prod/hosts.yml
Restart=always
RestartSec=5
Environment="ANSIBLE_VAULT_PASSWORD_FILE=/etc/ansible/.vault_pass"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now eda-agent
```

**Валидация:**

```bash
# Проверка статуса EDA Agent
systemctl status eda-agent
# → active (running)

# Отправка тестового события
curl -X POST https://eda.internal/webhook \
  -H "Content-Type: application/json" \
  -d '{"event_name": "Push Hook", "ref": "refs/heads/main"}'

# Проверка логов
journalctl -u eda-agent -f
# → показывает обработку события и запуск плейбука

# Проверка выполнения плейбука
# → TASK [Логирование причины деплоя]
# → ok: [web1] => {
# →     "msg": "Deploy triggered by: tag_push, version: v1.2.0"
# → }
```

### Именование и организации

- **Плейбуки:** Используйте префиксы `01_`, `02_` в `playbooks/` для визуализации порядка развертывания.
- **Переменные:** Всегда используйте префиксы ролей (например, `postgresql_port`), чтобы избежать конфликтов при слиянии переменных из разных источников.
- **Тегирование:** Используйте `tags` для избирательного выполнения задач (например, `tags: ['backup', 'maintenance']`).

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Несколько `ansible.cfg` | Конфликт настроек | Ansible использует ближайший `ansible.cfg` к плейбуку; не создавайте дубли. |
| Windows-контрольный узел | Некоторые модули не работают | Используйте WSL2 или Linux-контрольный узел. |
| Параллельный запуск | Файловые конфликты | Используйте `serial` в плейбуке или `forks` в `ansible.cfg`. |
| Vault и CI/CD | Пароль Vault недоступен | Передавайте через защищенные файловые переменные CI/CD с маскированием. |
| Большие инвентари | Медленная загрузка | Используйте динамический инвентарь или `yaml` вместо `ini` формата. |
