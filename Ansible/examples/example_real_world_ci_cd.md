# Архитектура Ansible для безопасного CI/CD

## Определения

**Безопасная архитектура Ansible для CI/CD** — комплексный подход к автоматизации, обеспечивающий изоляцию секретов, аудит действий и разделение логики автоматизации от данных конкретных окружений.

**Скрипт-обертка (Wrapper Script)** — сценарий с жестко ограниченными правами доступа (через `sudo`), выступающий единственным шлюзом для запуска `ansible-playbook` из недоверенных сред (например, CI/CD-агентов). Он предотвращает инъекцию произвольных аргументов и ограничивает область видимости инвентаря.

**Control Node (Контрольный узел)** — защищенный сервер, являющийся единственной точкой входа в инфраструктуру. В современной архитектуре его роль часто выполняют **[Ansible Automation Platform (AAP)](../ansible-automation-platform.md)** или **AWX**, предоставляющие API и RBAC (Role-Based Access Control).

**Execution Environment (Среда исполнения, EE)** — контейнеризированное окружение (образ), содержащее Ansible Core, коллекции и Python-зависимости. Гарантирует идентичность запуска плейбуков в разных средах и исключает конфликты библиотек.

**OIDC (OpenID Connect) / Workload Identity** — протокол аутентификации, позволяющий CI/CD-пайплайнам (GitLab CI, GitHub Actions) получать временные токены доступа к менеджерам секретов (HashiCorp Vault) или облачным провайдерам без использования статических паролей.

**ansible-lint** — утилита статического анализа плейбуков и ролей Ansible, выявляющая нарушения最佳实践, синтаксические ошибки и потенциальные проблемы безопасности. Используется как блокирующая стадия в CI/CD-пайплайнах.

**no_log** — параметр задачи Ansible, скрывающий чувствительные данные (пароли, ключи) из логов выполнения. Обязателен для задач, обрабатывающих секреты.

**Masked Variables** — функция CI/CD-систем (GitLab CI, GitHub Actions), автоматически заменяющая значение защищенной переменной на `[MASKED]` в логах пайплайна.

**Protected Runners** — специализированные GitLab Runner, доступные только для веток с ограниченным доступом (main, production), обеспечивающие изоляцию от сторонних коммитов.

## Базовые концепции

### Предварительные требования

#### Версии и совместимость

- **Ansible Core**: 2.15 или выше (рекомендуется 2.17+ для полной поддержки Execution Environments).
- **ansible-builder**: 3.0+ (для сборки EE через `execution-environment.yml` v3).
- **ansible-lint**: 24.2+ (для статического анализа плейбуков).
- **Python на целевых хостах**: 3.7 или выше.
- **GitLab CI**: 16.0+ (для поддержки `id_tokens` и OIDC).
- **GitHub Actions**: `actions/checkout@v4`, `hashicorp/vault-action@v3`.

#### Структура репозитория

Рекомендуемая структура для проекта Ansible + CI/CD:

```text
ansible-ci-cd/
├── ansible.cfg
├── inventory/
│   ├── production/
│   │   ├── hosts.yml
│   │   └── group_vars/
│   │       ├── all.yml
│   │       └── vault.yml          # Зашифрованные секреты
│   └── staging/
├── playbooks/
│   ├── site.yml
│   └── deploy.yml
├── roles/
│   ├── common/
│   ├── nginx/
│   └── postgresql/
├── requirements.yml               # Зависимости (роли и коллекции)
├── execution-environment.yml      # Конфигурация EE
├── .ansible-lint                  # Правила статического анализа
├── .gitlab-ci.yml                 # Конфигурация GitLab CI
└── .github/
    └── workflows/
        └── deploy.yml             # Конфигурация GitHub Actions
```

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

| Критерий | GitLab CI | GitHub Actions | AWX/AAP |
|---|---|---|---|
| **Хостинг** | Self-hosted / SaaS | SaaS | Self-hosted |
| **OIDC / ID Tokens** | Встроенная поддержка | Через `id-token: write` | Встроенная (JWT) |
| **Execution Environments** | Через Docker-образы | Через Docker-образы | Нативная поддержка |
| **Аудит** | История пайплайнов | История работ | Детальный аудит (БД) |
| **RBAC** | Ограниченный | Ограниченный | Полный (Organizations → Teams → Users) |
| **Стоимость** | Free / Premium | Free / Teams | Open Source (AWX) / Коммерческая (AAP) |

---

## Практические сценарии

### Сценарий 3: Сборка и использование Execution Environment через ansible-builder

Для проектов, требующих кастомных зависимостей, рекомендуется собирать собственный EE.

#### 1. Конфигурация `execution-environment.yml`

```yaml
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

#### 2. Сборка образа

```bash
# Сборка локально
ansible-builder build -t my-registry.com/ansible-ee:v1.2

# Проверка содержимого образа
ansible-runner container list
# → IMAGE ID     IMAGE NAME
# → abc123def45  my-registry.com/ansible-ee:v1.2

# Пуш в реестр
docker push my-registry.com/ansible-ee:v1.2
```

#### 3. Использование в CI/CD (GitLab CI)

```yaml
deploy_ee:
  stage: deploy
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - docker pull my-registry.com/ansible-ee:v1.2
    - docker run --rm -v $(pwd):/workspace my-registry.com/ansible-ee:v1.2
        ansible-playbook /workspace/site.yml -i /workspace/inventory/prod.yml
  tags: [protected-runner]
```

**Валидация:**

```bash
# Проверка сборки
ansible-builder build --tag my-ee:test --container-runtime docker
# → Complete! Build Python or System package dependencies... DONE
# → Complete! Build Collection dependencies... DONE

# Проверка зависимостей внутри образа
docker run --rm my-registry.com/ansible-ee:v1.2 \
  ansible-galaxy collection list
# → Collection        Version
# → ----------------  -------
# → community.general x.y.z
# → community.postgresql x.y.z

# Проверка версии Ansible Core
docker run --rm my-registry.com/ansible-ee:v1.2 \
  ansible --version
# → ansible [core 2.17.x]
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `ERROR: Cannot find collection` | Коллекция не указана в `execution-environment.yml` | Добавьте коллекцию в секцию `dependencies.ansible_collections.galaxy.collections`. |
| `pip install failed` | Конфликт версий Python-пакетов | Используйте `requirements.txt` для явного указания версий. |
| `Container image build failed` | Нет доступа к реестру базового образа | Проверьте доступность `quay.io` или используйте альтернативный registry. |

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

**Валидация:**

```bash
# Проверка синтаксиса плейбука
ansible-playbook playbooks/site.yml --syntax-check
# → playbook: playbooks/site.yml

# Статический анализ
ansible-lint playbooks/site.yml
# →Passed: 0 failure(s), 0 warning(s) on 12 tasks.

# Проверка прав скрипта-обертки
ls -la /usr/local/bin/ansible_runner.sh
# → -rwxr-xr-x 1 root root 1024 ... /usr/local/bin/ansible_runner.sh

# Проверка sudoers
sudo -l -U gitlab-runner
# → User gitlab-runner may run the following commands on this host:
# → (ansible-deploy) NOPASSWD: /usr/local/bin/ansible_runner.sh
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `sudo: no tty present and no askpass program specified` | GitLab Runner не имеет доступа к sudo | Убедитесь, что файл `/etc/sudoers.d/gitlab-runner` существует и содержит правильное правило. |
| `ERROR! the role 'xxx' was not found` | Роли не установлены на Runner | Проверьте, что `requirements.yml` корректен и `ansible-galaxy install` выполняется в `before_script`. |
| `Vault password error` | Неверный пароль или переменная не определена | Проверьте переменную `VAULT_PASSWORD_PROD` в GitLab CI/CD Settings → CI/CD → Variables. |
| `Permission denied: ansible_runner.sh` | Скрипт не имеет прав на выполнение | `sudo chmod +x /usr/local/bin/ansible_runner.sh` и `sudo chown root:root /usr/local/bin/ansible_runner.sh`. |

### Сценарий 2: Использование Execution Environments в GitHub Actions

Если политика безопасности позволяет запуск из облачного CI, используйте контейнеризированные среды (EE).

#### 1. Базовый пример `.github/workflows/deploy.yml`

```yaml
name: Ansible EE Deploy
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run ansible-lint
        run: |
          pip install ansible-lint
          ansible-lint playbooks/site.yml

  deploy:
    needs: lint
    runs-on: ubuntu-latest
    container:
      image: my-registry.com/ansible-ee:v1.2
    steps:
      - uses: actions/checkout@v4
      - name: Run Playbook
        run: |
          ansible-playbook site.yml -i inventory/prod.yml --vault-password-file <(echo "${{ secrets.VAULT_PASS }}")
        env:
          ANSIBLE_HOST_KEY_CHECKING: "False"
          ANSIBLE_FORCE_COLOR: "true"
```

#### 2. Продвинутый пример с OIDC и Vault

```yaml
name: Secure Ansible Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write    # Обязательно для OIDC
      contents: read
    container:
      image: my-registry.com/ansible-ee:v1.2
    steps:
      - uses: actions/checkout@v4

      - name: Import Secrets from Vault
        uses: hashicorp/vault-action@v3
        with:
          url: https://vault.internal.corp
          role: ci-role
          method: jwt
          secrets: |
            kv/data/production/db password | DB_PASSWORD
            kv/data/production/ssh_key | SSH_PRIVATE_KEY

      - name: Setup SSH
        run: |
          mkdir -p ~/.ssh
          echo "$SSH_PRIVATE_KEY" > ~/.ssh/id_rsa
          chmod 600 ~/.ssh/id_rsa

      - name: Run Playbook
        run: |
          ansible-playbook site.yml -i inventory/prod.yml
        env:
          ANSIBLE_HOST_KEY_CHECKING: "False"
          ANSIBLE_PRIVATE_KEY_FILE: "~/.ssh/id_rsa"

      - name: Cleanup
        if: always()
        run: rm -rf ~/.ssh
```

**Валидация:**

```bash
# Проверка синтаксиса workflow
act --list  # или GitHub CLI: gh workflow view deploy.yml

# Локальная проверка плейбука (в Execution Environment)
docker run --rm -v $(pwd):/workspace my-registry.com/ansible-ee:v1.2 \
  ansible-playbook /workspace/site.yml --syntax-check

# Проверка OIDC-токена (GitHub CLI)
gh api /repos/{owner}/{repo}/actions/runs/{run_id}/jobs
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| `Error: OIDC token not available` | Отсутствует `id-token: write` в permissions | Добавьте `permissions: id-token: write` в job или workflow. |
| `Vault: permission denied` | OIDC-entionPolicy не разрешает GitHub Actions | Обновите Vault Policy для роли `ci-role` ( bound_claims ). |
| `Container image not found` | EE-образ не доступен из GitHub Actions | Убедитесь, что реестр образов доступен (Docker Hub, GHCR, приватный). |

### Сценарий 4: Локальная отладка через ansible-navigator

Для обеспечения идентичности среды выполнения между локальной разработкой и CI/CD используйте `ansible-navigator`.

```bash
# Установка
pip install ansible-navigator

# Запуск плейбука в EE
ansible-navigator run playbooks/site.yml \
  --ee-image my-registry.com/ansible-ee:v1.2 \
  --ee-enable \
  --mode stdout

# Интерактивный режим (TUI)
ansible-navigator run playbooks/site.yml \
  --ee-image my-registry.com/ansible-ee:v1.2 \
  --ee-enable \
  --mode interactive

# Просмотр содержимого EE
ansible-navigator container list
ansible-navigator collection list
ansible-navigator requirements list --ee-image my-registry.com/ansible-ee:v1.2
```

**Валидация:**

```bash
# Проверка версии
ansible-navigator --version
# → ansible-navigator 4.x.x

# Проверка конфигурации
ansible-navigator configuration dump --mode stdout | grep container_engine
# → container_engine='docker'
```

### Сценарий 5: Обработка ошибок и восстановление в CI/CD

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
# GitLab CI
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

# GitHub Actions
- name: Upload artifacts
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: deployment-logs
    path: logs/
    retention-days: 7
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|---|---|---|
| Частичный деплой (некоторые хосты обновлены) | Нет `any_errors_fatal` или `serial` | Добавьте `any_errors_fatal: true` или `serial: 1` для последовательного обновления. |
| Артефакты не собираются | Артефакты в `after_script` при ошибке | Используйте `when: always` для `artifacts`. |
| Уведомление не отправляется | `SLACK_WEBHOOK` не определен | Проверьте переменную в CI/CD Settings. |

---

## Дополнительная информация

### Лучшие практики

1. **Изоляция секретов**: Никогда не храните SSH-ключи, пароли или API-токены в Git-репозитории. Используйте **[Ansible Vault](../Vault/basics.md)** или внешние менеджеры секретов.
2. **Идемпотентность**: Все плейбуки должны быть идемпотентными — повторные запуски не должны вызывать нежелательных изменений.
3. **Статический анализ**: Внедрите `ansible-lint` как блокирующую стадию пайплайна.
4. **Валидация перед деплоем**: Всегда выполняйте `--syntax-check` и `--check` (dry-run) перед реальным развертыванием.
5. **Минимальные привилегии**: Используйте `become: true` только для конкретных задач, а не для всего плейбука.
6. **Логирование**: Включайте `ANSIBLE_STDOUT_CALLBACK: yaml` для читаемых логов.
7. **Тестирование**: Используйте Molecule для тестирования ролей перед интеграцией в CI/CD.
8. **Ротация ключей**: Регулярно ротируйте SSH-ключи, пароли Vault и API-токены.
9. **Эфемерные раннеры**: Для максимальной безопасности используйте контейнеризированные раннеры, уничтожаемые после каждого запуска.

### Типичные ошибки и устранение неполадок

| Проблема | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `UNREACHABLE! Failed to connect to the host via ssh` | SSH-ключ отсутствует или неверный | Проверьте `ssh-agent` и ключи на Runner | Убедитесь, что ключ добавлен в `ssh-agent` и `known_hosts` настроен. |
| `Vault password error` | Неверный пароль или переменная не определена | Проверьте переменную в CI/CD Settings | Убедитесь, что переменная `VAULT_PASS` или `VAULT_PASSWORD_PROD` определена и зашифрована. |
| `The role 'xxx' was not found` | Роли не установлены | Проверьте `requirements.yml` и `before_script` | Добавьте `ansible-galaxy install -r requirements.yml` в `before_script`. |
| `Permission denied: ansible_runner.sh` | Нет прав на выполнение скрипта | `ls -la /usr/local/bin/ansible_runner.sh` | `sudo chmod +x` и `sudo chown root:root` скрипт. |
| `ERROR! the field 'become_user' is not allowed` | Опечатка в имени параметра | Проверьте YAML-синтаксис | Исправьте `become_user` (должно быть через подчеркивание). |
| `Timeout expired` | Сетевые проблемы или долгий запуск | Проверьте `ANSIBLE_TIMEOUT` и `ansible_timeout` | Увеличьте таймаут или оптимизируйте плейбук. |

### Граничные случаи и ограничения

1. **Windows-хосты**: Ansible поддерживает Windows через WinRM, но требует дополнительной настройки (PowerShell Remoting, сертификаты). Рекомендуется использовать отдельные Execution Environments для Windows.
2. **Большие инфраструктуры (1000+ хостов)**: Используйте `ansible-pull` с расписанием или стратегию `free` для параллельного выполнения.
3. **Приватные реестры образов**: Убедитесь, что CI/CD-агент имеет аутентификацию для доступа к приватным реестрам (Docker Hub, GHCR, Quay).
4. **Сетевые ограничения**: Если Control Node не имеет прямого доступа к хостам, используйте SSH-туннели или ProxyJump.
5. **Версионирование Ansible**: Разные проекты могут требовать разные версии Ansible Core. Используйте EE для изоляции версий.
6. **Одновременные деплои**: Используйте `resource_group` (GitLab CI) или `concurrency` (GitHub Actions) для предотвращения race conditions.

### Тестирование плейбуков перед production

1. **Syntax Check**: `ansible-playbook playbook.yml --syntax-check`
2. **Check Mode (Dry Run)**: `ansible-playbook playbook.yml --check --diff`
3. **Limit Hosts**: `ansible-playbook playbook.yml --limit staging`
4. **Verbose Mode**: `ansible-playbook playbook.yml -vvv` для детальной отладки
5. **Molecule Test**: `molecule test` для интеграционного тестирования ролей
6. **ansible-navigator**: `ansible-navigator run playbook.yml --ee-enable` для проверки в EE

### Масштабируемость и Enterprise-решения

Для крупных организаций рекомендуется переход к специализированным платформам (см. подробнее **[Ansible Automation Platform (AAP)](../ansible-automation-platform.md)**):

- **Ansible Automation Platform (AAP)**: Коммерческое решение от Red Hat. Обеспечивает централизованное управление, детальный аудит (каждый запуск логируется в БД), управление секретами внутри платформы и интеграцию с LDAP/AD. Включает Execution Nodes для масштабирования вычислительных мощностей.
- **AWX**: Upstream-версия AAP с открытым исходным кодом. Вместо bash-скриптов, CI/CD делает REST API запрос к AWX для запуска Job Template:
  ```bash
  # Пример вызова Job Template в AWX из CI/CD
  curl -H "Authorization: Bearer $AWX_TOKEN" \
       -X POST "$AWX_HOST/api/v2/job_templates/$ID/launch/"
  ```

## Смотрите также

- [Интеграция Ansible с GitLab CI](../../CI-CD/GitLab_CI/Tutorials/ansible_integration.md)
- [Типовая структура проекта Ansible](example_project_layout.md)
- [Рекомендации по безопасности в Ansible](../ansible_security_best_practices.md)
- [Среды выполнения Ansible (Execution Environments)](../ansible-execution-environments.md)
