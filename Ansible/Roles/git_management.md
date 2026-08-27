# Управление ролями через Git

## Определения

**Управление ролями через Git** — совокупность методов подключения внешних зависимостей (ролей и коллекций) напрямую из Git-репозиториев. Этот подход позволяет использовать приватные наработки, фиксировать конкретные версии кода и обходить ограничения публичного реестра Ansible Galaxy.

**Внешняя роль/коллекция** — компонент автоматизации, исходный код которого хранится в отдельном репозитории. Подключается к основному проекту для обеспечения модульности, версионирования и разделения зон ответственности.

---

## Предварительные требования

### Системные требования

*   **Python:** 3.10+ (Ansible 2.17+) для control node, 3.8+ для target nodes
*   **Git:** 2.20+ (для работы с подмодулями и шallow clone)
*   **Ansible:** 2.10+ для поддержки Git-источников в `requirements.yml`
*   **SSH-клиент:** Для работы с SSH-ключами и known_hosts

### Инструменты

```bash
# Проверка версии Git
git --version

# Проверка версии Ansible
ansible --version

# Проверка SSH-ключа
ssh -T git@github.com

# Тестирование подключения к Git-репозиторию
ssh-keyscan github.com >> ~/.ssh/known_hosts

# Просмотр установленных ролей
ansible-galaxy role list

# Просмотр установленных коллекций
ansible-galaxy collection list
```

---

## Основные концепции

Использование Git как источника правды для ролей является стандартом в Enterprise-средах, где требуется изоляция кода и работа в закрытых контурах.

### 1. Стандарт: `requirements.yml` с Git-источниками

Начиная с Ansible 2.10, файл `requirements.yml` поддерживает установку как ролей, так и коллекций из Git.

#### Параметры конфигурации
*   **`name`**: Имя, под которым роль будет сохранена локально.
*   **`src`**: URL Git-репозитория (SSH или HTTPS). Также поддерживает локальные пути через `file:///`.
*   **`scm`**: Тип системы контроля версий (по умолчанию `git`).
*   **`version`**: Указатель на версию. Может быть:
    *   Именем ветки (`master`, `develop`).
    *   Тегом (`v1.2.0`).
    *   Конкретным хешем коммита (SHA) — **наиболее надежный способ** для Production.

**Пример `requirements.yml` для ролей и коллекций:**
```yaml
# Роли
roles:
  - name: internal.security
    src: git@github.com:myorg/ansible-role-security.git
    version: v2.1.0

# Коллекции (Ansible 2.10+)
collections:
  - name: myorg.internal_tools
    source: https://gitlab.com/myorg/collections/internal_tools.git
    type: git
    version: 8a2f1b3c
```

**Установка:**
```bash
ansible-galaxy install -r requirements.yml
```

### 2. Git Submodules (Подмодули)

Встраивание одного репозитория в другой на уровне файловой системы Git.

*   **Преимущества:** Жесткая фиксация коммита на уровне основного репозитория, отсутствие необходимости запускать `ansible-galaxy` для загрузки кода.
*   **Недостатки:** Сложность управления (нужно инициализировать подмодули после клонирования), проблемы с путями вложенных зависимостей.
*   Подробное описание: **[Git Submodules](../../Git/git_submodules.md)**.

### 3. Git Subtree

Копирование кода внешней роли в дерево основного проекта с сохранением истории.

*   **Особенности:** Код становится частью основного репозитория, что упрощает атомарные коммиты, затрагивающие и логику плейбуков, и код ролей.
*   Подробное описание: **[Git Submodules vs Subtree](../../Git/git_submodules_and_subtree.md)**.

---

## Безопасность и аутентификация в CI/CD

Автоматизация требует бесшовного доступа к приватным репозиториям без интерактивных запросов.

### Проблема Host Key Verification
При первом подключении Git запрашивает подтверждение ключа хоста. В CI/CD это приводит к зависанию.
**Решение:** Предварительное добавление ключей в `known_hosts`.
```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

### Методы аутентификации
1.  **SSH Deploy Keys (Рекомендуется):** Ключи с правами `Read-only` для конкретного репозитория. Безопаснее, чем персональные ключи разработчиков.
2.  **`.netrc` для HTTPS:** Позволяет хранить токены для HTTPS-доступа вне URL.
    ```text
    machine github.com
    login my-token-name
    password ${{ secrets.GITHUB_TOKEN }}
    ```
3.  **GitLab CI_JOB_TOKEN:** Позволяет клонировать проекты внутри одной группы в GitLab. Требует настройки `Job Token Permissions` в настройках проекта.

---

## Практические сценарии

### Сценарий 1: Установка ролей из разных веток для Test/Prod

Использование разных файлов требований для разных окружений или динамическое переопределение версии.

**requirements-prod.yml:**
```yaml
roles:
  - name: app.setup
    src: git@github.com:org/role-app.git
    version: v1.5.0 # Стабильный тег
```

**requirements-dev.yml:**
```yaml
roles:
  - name: app.setup
    src: git@github.com:org/role-app.git
    version: feature/new-logic # Ветка разработки
```

### Сценарий 2: Локальная разработка и переопределение пути

Если вы разрабатываете роль локально и хотите протестировать её в составе проекта, не отправляя коммит в Git:

```yaml
roles:
  - name: my_role
    src: file:///Users/mac/work/my_role
```

### Сценарий 3: Установка с шallow clone для ускорения

Для больших репозиториев используйте шallow clone для ускорения установки:

```bash
# В requirements.yml
roles:
  - name: large_role
    src: git@github.com:org/large-role.git
    version: v2.0.0
    # Шallow clone автоматически при version: тег или SHA
```

**Настройка в ansible.cfg:**
```ini
[galaxy]
# Автоматический шallow clone для Git-источников
# Работает с версиями 2.10+
```

### Сценарий 4: Использование разных веток для development/production

Стратегия ветвления для разных окружений:

**requirements-dev.yml:**
```yaml
roles:
  - name: app.setup
    src: git@github.com:org/role-app.git
    version: develop  # Ветка разработки

  - name: lib.common
    src: git@github.com:org/role-common.git
    version: feature/new-utils  # Feature ветка
```

**requirements-prod.yml:**
```yaml
roles:
  - name: app.setup
    src: git@github.com:org/role-app.git
    version: main  # Основная ветка

  - name: lib.common
    src: git@github.com:org/role-common.git
    version: v1.2.0  # Стабильный тег
```

### Сценарий 5: CI/CD pipeline с Git-ролями

Интеграция в Jenkins/GitLab CI/GitHub Actions:

**GitLab CI пример:**
```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - deploy

ansible-lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint roles/
    - ansible-lint playbooks/

ansible-test:
  stage: test
  image: cytopia/ansible:2.14
  before_script:
    - ansible-galaxy install -r requirements.yml
    - ansible-galaxy collection install -r requirements.yml
  script:
    - ansible-playbook playbooks/test.yml --check

ansible-deploy:
  stage: deploy
  image: cytopia/ansible:2.14
  only:
    - main
  before_script:
    - ansible-galaxy install -r requirements.yml
  script:
    - ansible-playbook playbooks/deploy.yml
```

**GitHub Actions пример:**
```yaml
# .github/workflows/ansible.yml
name: Ansible CI
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install ansible-lint
      - run: ansible-lint roles/

  deploy:
    needs: lint
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install ansible
      - run: ansible-galaxy install -r requirements.yml
      - run: ansible-playbook playbooks/deploy.yml
```

### Сценарий 6: Версионирование ролей с использованием Git

Стратегия версионирования для ролей:

```bash
# Создание нового тега
git tag -a v1.2.0 -m "Release 1.2.0: Added new security features"
git push origin v1.2.0

# Использование семантического версионирования
# MAJOR.MINOR.PATCH
# MAJOR: Breaking changes
# MINOR: New features (backward compatible)
# PATCH: Bug fixes (backward compatible)
```

**Пример использования тегов в requirements.yml:**
```yaml
roles:
  - name: security.hardening
    src: git@github.com:org/role-security.git
    version: v2.1.0  # Точная версия
    # Или диапазон версий (для коллекций):
    # version: ">=2.0.0,<3.0.0"
```

### Сценарий 7: Кеширование Git-ролей в CI/CD

Оптимизация времени сборки за счет кеширования:

```yaml
# GitLab CI с кешированием
ansible-deploy:
  stage: deploy
  image: cytopia/ansible:2.14
  cache:
    key: ansible-roles
    paths:
      - ~/.ansible/roles/
      - ~/.ansible/collections/
  before_script:
    - ansible-galaxy install -r requirements.yml
    - ansible-galaxy collection install -r requirements.yml
  script:
    - ansible-playbook playbooks/deploy.yml
```

### Сценарий 8: Использование Git Submodules для монолитных проектов

Когда роли и плейбуки находятся в одном репозитории:

```bash
# Добавление подмодуля с ролью
git submodule add git@github.com:org/role-common.git roles/lib_common

# Инициализация после клонирования
git clone --recursive <repo-url>
# Или
git submodule update --init --recursive

# Обновление подмодуля
cd roles/lib_common
git fetch
git checkout v1.2.0
cd ../..
git add roles/lib_common
git commit -m "Update lib_common to v1.2.0"
```

### Сценарий 9: Миграция с Ansible Galaxy на Git

Пошаговая миграция существующих ролей:

```bash
# Шаг 1: Экспорт текущих зависимостей
ansible-galaxy role list --format json > current_roles.json

# Шаг 2: Создание requirements.yml из установленных ролей
# (автоматически через скрипт или вручную)

# Шаг 3: Клонирование ролей в Git
for role in $(ansible-galaxy role list --format json | jq -r '.[].name'); do
  echo "Cloning $role..."
  # Клонировать в отдельный репозиторий
done

# Шаг 4: Обновление requirements.yml на Git-источники
# Заменить ссылки на Galaxy на Git URL

# Шаг 5: Тестирование
ansible-galaxy install -r requirements.yml
ansible-playbook site.yml --check
```

### Сценарий 10: Работа с приватными GitLab/GitHub Enterprise

Настройка для корпоративных Git-серверов:

```yaml
# requirements.yml для GitLab
roles:
  - name: internal.security
    src: git@gitlab.internal.com:myorg/ansible-role-security.git
    version: v1.0.0

collections:
  - name: https://gitlab.internal.com/myorg/collections/internal_tools.git
    type: git
    version: main
```

**Настройка SSH для корпоративного сервера:**
```bash
# ~/.ssh/config
Host gitlab.internal.com
  HostName gitlab.internal.com
  User git
  IdentityFile ~/.ssh/id_rsa_gitlab
  StrictHostKeyChecking no
```

---

## Дополнительная информация

### Monorepo vs Polyrepo

**Monorepo (Один репозиторий):**
```text
ansible-project/
├── playbooks/
├── roles/
│   ├── web_server/
│   ├── db_server/
│   └── monitoring/
├── collections/
├── requirements.yml
└── inventory/
```

**Polyrepo (Отдельные репозитории):**
```text
# Каждая роль в отдельном репозитории
ansible-role-web-server/
ansible-role-db-server/
ansible-role-monitoring/

# Основной проект ссылается на них через requirements.yml
```

**Сравнение:**
| Критерий | Monorepo | Polyrepo |
| :--- | :--- | :--- |
| **Простота разработки** | Высокая (всё в одном месте) | Средняя (много репозиториев) |
| **Изоляция** | Низкая (все видят все изменения) | Высокая (изолированные изменения) |
| **Версионирование** | Сложнее (общая история) | Проще (отдельные теги) |
| **CI/CD** | Проще (один pipeline) | Сложнее (много pipeline) |
| **Масштабируемость** | Средняя | Высокая |
| **Рекомендация** | Малые/средние проекты | Крупные Enterprise проекты |

### Сравнение методов управления

| Критерий | `requirements.yml` (Git) | Git Submodules | Git Subtree |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая | Средняя | Высокая |
| **Изоляция кода** | Полная (каталог в `.gitignore`) | Ссылка на коммит | Код в репозитории |
| **CI/CD дружелюбность** | Высокая | Требует `submodule update` | Максимальная |
| **Модификация роли** | Требует отдельного клона | Возможна на месте | Удобна (Subtree push) |
| **Лучший выбор** | **Стандарт индустрии** | Для монолитов | Для совместной правки |

### Troubleshooting

#### Проблема: Role not found (specific version)

**Причина:** Тег или ветка не существует в репозитории.

**Решение:**
```bash
# Просмотр доступных тегов
git ls-remote --tags git@github.com:org/role.git

# Просмотр доступных веток
git ls-remote --heads git@github.com:org/role.git

# Проверка прав доступа
ssh -T git@github.com
```

#### Проблема: Host key verification failed

**Причина:** SSH-ключ хоста не добавлен в known_hosts.

**Решение:**
```bash
# Добавление ключа
ssh-keyscan github.com >> ~/.ssh/known_hosts

# Или отключение проверки (НЕ рекомендуется для production)
ssh -o StrictHostKeyChecking=no git@github.com
```

#### Проблема: Permission denied (publickey)

**Причина:** SSH-ключ не настроен или не добавлен в Git-сервис.

**Решение:**
```bash
# Проверка SSH-ключа
ssh -T git@github.com

# Добавление ключа в ssh-agent
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa

# Просмотр текущих ключей
ssh-add -l
```

#### Проблема: Submodule not initialized

**Причина:** Подмодули не инициализированы после клонирования.

**Решение:**
```bash
# Инициализация подмодулей
git submodule update --init --recursive

# Или клонирование с подмодулями
git clone --recursive <repo-url>

# Обновление подмодулей
git submodule update --remote
```

#### Проблема: Cache issues в CI/CD

**Причина:** Устаревшее кеш ролей в CI/CD.

**Решение:**
```bash
# Очистка кеша
rm -rf ~/.ansible/roles/*
rm -rf ~/.ansible/collections/*

# Принудительная установка
ansible-galaxy install -r requirements.yml --force

# Использование --force для конкретной роли
ansible-galaxy install geerlingguy.nginx --force
```

#### Проблема: Версия роли не обновляется

**Причина:** Кеш или приоритет путей.

**Решение:**
```bash
# Просмотр путей поиска ролей
ansible --verbose

# Очистка кеша
rm -rf ~/.ansible/roles/*

# Установка с явным указанием пути
ansible-galaxy install -r requirements.yml -p ./roles --force
```

### Best Practices

#### Управление версиями

1. **Используйте семантическое версионирование:** MAJOR.MINOR.PATCH
2. **Фиксируйте версии:** Всегда указывайте конкретные теги или SHA в production
3. **Используйте ветки для разработки:** `develop`, `feature/*`
4. **Создавайте теги для релизов:** Не используйте `master`/`main` в production

#### Безопасность

1. **Используйте SSH Deploy Keys:** Не персональные ключи разработчиков
2. **Ограничивайте права доступа:** Read-only для production ключей
3. **Храните секреты в Vault:** Не в requirements.yml
4. **Проверяйте подписи коллекций:** Используйте `signatures` дляAnsible 2.17+

#### Производительность

1. **Используйте shallow clone:** Для больших репозиториев
2. **Кешируйте в CI/CD:** Сохраняйте `~/.ansible/roles/` между сборками
3. **Параллельная установка:** `ansible-galaxy install -r requirements.yml` уже оптимизирована
4. **Ограничивайте глубину clone:** Если нужна только конкретная версия

#### Организация кода

1. **Разделяйте роли и плейбуки:** Используйте отдельные репозитории для крупных проектов
2. **Документируйте зависимости:** В README.md каждой роли
3. **Используйте .gitignore:** Исключайте `*.retry`, `*.pyc`, `__pycache__`
4. **Создавайте Makefile:** Для частых команд установки и тестирования

### Edge Cases

#### Роли с одинаковыми именами из разных источников

```yaml
# Решение: использование namespace
roles:
  - name: myorg.nginx  # Роль из вашего Git-репозитория
    src: git@github.com:myorg/role-nginx.git
    version: v1.0.0

  - name: geerlingguy.nginx  # Роль из Ansible Galaxy
    version: "3.1.0"
```

#### Конфликт версий зависимостей

```yaml
# Проблема: Role A требует v1.0.0, Role B требует v2.0.0
# Решение: вынос общих зависимостей в основной requirements.yml

roles:
  # Общая зависимость с фиксированной версией
  - name: common.utils
    src: git@github.com:org/role-common.git
    version: v1.5.0

  # Role A и Role B используют общую роль
```

#### Работа с forks (форками)

```yaml
# Использование форка вместо оригинала
roles:
  - name: custom.nginx
    src: git@github.com:myorg/ansible-role-nginx.git  # Ваш форк
    version: my-patch-branch  # Ваша ветка с изменениями
```

#### Локальная разработка с несколькими ролями

```bash
# Скрипт для локальной разработки
#!/bin/bash
# dev-setup.sh

# Установка ролей из Git
ansible-galaxy install -r requirements-dev.yml

# Переопределение конкретных ролей на локальные копии
export ANSIBLE_ROLES_PATH=./roles:$HOME/.ansible/roles

# Запуск с локальными ролями
ansible-playbook site.yml -e "role_path=./roles"
```

#### Работа с зашифрованными секретами в Git

```yaml
# Использование Ansible Vault с Git
# requirements.yml
roles:
  - name: secure.vault
    src: git@github.com:org/role-vault.git
    version: v1.0.0

# Установка и расшифровка
ansible-galaxy install -r requirements.yml
ansible-vault decrypt roles/secure.vault/defaults/main.yml --vault-password-file ~/.vault_pass
```

### См. также

- [Управление через Ansible Galaxy](galaxy.md) — основы работы с зависимостями.
- [Структура роли](structure.md) — требования к содержимому ролей.
- [Git Submodules — подмодули](../../Git/git_submodules.md) — SSoT по подмодулям Git.
