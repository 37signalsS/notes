# Управление ролями через Git

## Определения

**Управление ролями через Git** — совокупность методов подключения внешних зависимостей (ролей и коллекций) напрямую из Git-репозиториев. Этот подход позволяет использовать приватные наработки, фиксировать конкретные версии кода и обходить ограничения публичного реестра Ansible Galaxy.

**Внешняя роль/коллекция** — компонент автоматизации, исходный код которого хранится в отдельном репозитории. Подключается к основному проекту для обеспечения модульности, версионирования и разделения зон ответственности.

**Git-источник** — источник зависимости, указанный в `requirements.yml` через `src` (роли) или `source` (коллекции) с `type: git`.

**Шаллоу-клон (shallow clone)** — клонирование репозитория с ограничением глубины истории (`--depth=1`), применяемое автоматически для веток и HEAD при установке через `ansible-galaxy`.

---

## Предварительные требования

### Системные требования

*   **Python:** 3.9+ (совместимость с ansible-core 2.18+)
*   **Git:** 2.20+ (для работы с подмодулями и shallow clone)
*   **Ansible:** 2.10+ для поддержки Git-источников в `requirements.yml`
*   **SSH-клиент:** Для работы с SSH-ключами и `known_hosts`

### Инструменты

```bash
# Проверка версии Git
git --version
# → git version 2.43.0

# Проверка версии Ansible
ansible --version
# → ansible-core 2.21.x

# Проверка SSH-ключа
ssh -T git@github.com
# → Hi myorg! You've successfully authenticated...

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

### Архитектура и жизненный цикл

Управление зависимостями через Git включает несколько этапов от объявления до установки:

1. **Объявление** — разработчик указывает Git-источник в `requirements.yml` (роли или коллекции).
2. **Разрешение** — `ansible-galaxy` читает `requirements.yml`, определяет тип источника (`git`, `galaxy`, `file`).
3. **Клонирование** — для Git-источников выполняется `git clone` в временную директорию. Для тегов и коммитов используется полный клон; для веток и HEAD — автоматический `--depth=1` (shallow clone).
4. **Чекаут версии** — выполняется `git checkout <version>` в клонированном репозитории.
5. **Копирование** — содержимое репозитория копируется в `roles_path` (для ролей) или `collections_paths` (для коллекций) под указанным именем.
6. **Инсталляция** — роль/коллекция становится доступной для выполнения плейбуков.
7. **Очистка** — временная директория с клонированным репозиторием удаляется.

**Порядок разрешения источников:**
*   Если в `requirements.yml` указан `type: git` — приоритет у Git-источника.
*   Если `type: galaxy` или опущен — используется Galaxy API.
*   Локальные пути (`file://`) обрабатываются без клонирования.

**Взаимодействие с `roles_path` и `collections_paths`:**
*   Git-роли всегда устанавливаются в каталог, указанный через `-p` или `ANSIBLE_ROLES_PATH`.
*   Если путь не указан, используется значение по умолчанию (`~/.ansible/roles/`).
*   Коллекции из Git устанавливаются аналогично в `~/.ansible/collections/ansible_collections/`.

### Принципы работы ansible-galaxy с Git

При установке из Git `ansible-galaxy` выполняет следующие действия:

1. Создает временную директорию для клонирования.
2. Выполняет `git clone` с опциями, зависящими от типа версии:
   *   Ветка/HEAD: `git clone --depth=1 --branch=<version> <url> <tmpdir>`
   *   Тег: `git clone <url> <tmpdir>` + `git checkout tags/<version>`
   *   SHA: `git clone <url> <tmpdir>` + `git checkout <sha>`
3. Копирует содержимое репозитория в целевую директорию.
4. Удаляет временную директорию.

**Важно:** Для тегов и конкретных SHA используется полный клон, так как Git не позволяет получить отдельный тег без полной истории. Это влияет на скорость установки для больших репозиториев.

### Специфика установки коллекций из Git

Коллекции из Git имеют особенности:
*   Используют ключ `source` вместо `src` для указания URL.
*   Требуют указания `type: git`.
*   Поддерживают семантические диапазоны версий: `>=2.0.0,<3.0.0`.
*   После установки коллекция регистрируется в `collections_paths` и становится доступной через FQCN.

### Специфика установки ролей из Git

Роли из Git имеют особенности:
*   Используют ключ `src` для указания URL.
*   Устанавливаются в `roles_path` под именем, указанным в `name`.
*   Поддерживают теги, ветки и SHA.
*   Для роли внутри коллекции можно использовать FQCN: `namespace.collection.role_name`.

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

### Сценарий 3: Установка с shallow clone для ускорения

Для больших репозиториев shallow clone применяется автоматически для веток и HEAD. Для тегов и конкретных SHA используется полный клон.

```yaml
roles:
  - name: large_role
    src: git@github.com:org/large-role.git
    version: v2.0.0
```

**Настройка в ansible.cfg:**
```ini
[galaxy]
# Автоматический shallow clone для Git-источников
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

Интеграция в GitLab CI/GitHub Actions:

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

### Сценарий 11: Установка роли напрямую из Git-URL

Можно установить роль напрямую из Git-URL без `requirements.yml`:

```bash
# Установка одной роли из Git
ansible-galaxy role install git+https://github.com/myorg/ansible-role-nginx.git,v1.0.0

# Установка коллекции из Git
ansible-galaxy collection install git+https://github.com/myorg/ansible-collection-net.git,v2.1.0

# С указанием пути установки
ansible-galaxy role install git+https://github.com/myorg/ansible-role-nginx.git,v1.0.0 -p ./roles
```

### Сценарий 12: Откат роли к предыдущей версии

Процедура быстрого отката при инциденте:

```bash
# Шаг 1: Фиксация текущей версии в Git
git add requirements.yml
git commit -m "chore: lock roles to v1.5.0"
git tag -a rollback-point -m "Rollback point before upgrade"

# Шаг 2: Откат requirements.yml к предыдущему рабочему состоянию
git checkout HEAD~1 -- requirements.yml

# Шаг 3: Принудительная переустановка
ansible-galaxy install -r requirements.yml --force

# Шаг 4: Валидация
ansible-playbook playbooks/deploy.yml --check
```

---

## Операции и команды

| Команда | Назначение | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| `ansible-galaxy role install -r requirements.yml` | Установка ролей из Git/Galaxy | `-p <path>`, `--force` | `ansible-galaxy role install -r requirements.yml -p ./roles --force` |
| `ansible-galaxy collection install -r requirements.yml` | Установка коллекций | `--force-with-deps`, `-p <path>` | `ansible-galaxy collection install -r requirements.yml --force-with-deps` |
| `ansible-galaxy install -r requirements.yml` | Установка всех зависимостей | `-p <path>`, `--force` | `ansible-galaxy install -r requirements.yml -p ./roles` |
| `ansible-galaxy role install <git-url>` | Установка роли напрямую из Git | `-p <path>`, `--force` | `ansible-galaxy role install git+https://github.com/org/role.git,v1.0.0` |
| `ansible-galaxy collection install <git-url>` | Установка коллекции напрямую из Git | `-p <path>`, `--force-with-deps` | `ansible-galaxy collection install git+https://github.com/org/collection.git,v1.0.0` |
| `ansible-galaxy role remove <name>` | Удаление роли из `roles_path` | — | `ansible-galaxy role remove myorg.nginx` |
| `ansible-galaxy role list` | Список установленных ролей | `-p <path>` | `ansible-galaxy role list -p ./roles` |
| `ansible-galaxy collection list` | Список установленных коллекций | `-p <path>` | `ansible-galaxy collection list` |
| `ansible-galaxy collection list --outdated` | Поиск устаревших коллекций | — | `ansible-galaxy collection list --outdated` |
| `git ls-remote --tags <url>` | Просмотр доступных тегов | — | `git ls-remote --tags git@github.com:org/role.git` |
| `git ls-remote --heads <url>` | Просмотр доступных веток | — | `git ls-remote --heads git@github.com:org/role.git` |
| `git submodule update --init --recursive` | Инициализация подмодулей | — | `git submodule update --init --recursive` |

**Expected output:**
```bash
# Установка роли из Git
$ ansible-galaxy role install -r requirements.yml
# → Starting galaxy role install process
# → - extracting myorg.nginx to /Users/mac/ansible/roles/myorg.nginx
# → - myorg.nginx (v1.2.0) was installed successfully

# Просмотр тегов
$ git ls-remote --tags git@github.com:org/role.git
# → <hash>	refs/tags/v1.0.0
# → <hash>	refs/tags/v1.0.0^{}
# → <hash>	refs/tags/v2.0.0
```

---

## Безопасность и аутентификация

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

## Troubleshooting

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

**Причина:** SSH-ключ хоста не добавлен в `known_hosts`.

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

#### Проблема: Git clone timeout или медленная загрузка

**Причина:** Большой репозиторий, слабое сетевое соединение или блокировка firewall.

**Решение:**
```bash
# Shallow clone автоматически применяется для веток и HEAD
# Для тегов и коммитов используется полный клон
ansible-galaxy install -r requirements.yml

# Проверка скорости clone
time git clone --depth=1 git@github.com:org/large-role.git /tmp/test-clone

# Для очень больших репозиториев используйте bundle clone
git clone --filter=blob:none --no-checkout git@github.com:org/large-role.git
```

#### Проблема: Конфликт между ролью из Galaxy и ролью из Git с одинаковым именем

**Причина:** Оба источника предоставляют роль с одинаковым FQCN, и Ansible выбирает первый найденный в `roles_path`.

**Решение:**
```bash
# Просмотр порядка поиска ролей
ansible-config dump | grep ROLES_PATH
# → DEFAULT_ROLES_PATH(env: ANSIBLE_ROLES_PATH) = ['/Users/mac/.ansible/roles', '/usr/share/ansible/roles']

# Явное указание приоритета через переменную окружения
export ANSIBLE_ROLES_PATH=./roles:~/.ansible/roles

# Или используйте уникальные имена (namespace) в requirements.yml
```

#### Проблема: Submodule и Git-источник в одном проекте

**Причина:** Подмодуль и роль из Git имеют пересекающиеся зависимости или конфликтуют по пути.

**Решение:**
```bash
# Разделите каталоги: подмодули в ./vendor/, Git-роли в ./roles/
# Инициализируйте подмодули до установки ролей
git submodule update --init --recursive
ansible-galaxy install -r requirements.yml -p ./roles
```

#### Проблема: Ветка или тег не найдены

**Причина:** Указанная версия (ветка/тег/хеш) отсутствует в репозитории или изменена.

**Решение:**
```bash
# Просмотр доступных тегов
git ls-remote --tags git@github.com:org/role.git
# → <hash>	refs/tags/v1.0.0
# → <hash>	refs/tags/v1.0.0^{}
# → <hash>	refs/tags/v2.0.0

# Просмотр доступных веток
git ls-remote --heads git@github.com:org/role.git
# → <hash>	refs/heads/main
# → <hash>	refs/heads/develop

# Проверка прав доступа
ssh -T git@github.com
# → Hi myorg! You've successfully authenticated...
```

---

## Best Practices

### Управление версиями

1. **Используйте семантическое версионирование:** MAJOR.MINOR.PATCH
2. **Фиксируйте версии:** Всегда указывайте конкретные теги или SHA в production
3. **Используйте ветки для разработки:** `develop`, `feature/*`
4. **Создавайте теги для релизов:** Не используйте `master`/`main` в production

### Безопасность

1. **Используйте SSH Deploy Keys:** Не персональные ключи разработчиков
2. **Ограничивайте права доступа:** Read-only для production ключей
3. **Храните секреты в Vault:** Не в requirements.yml
4. **Проверяйте подписи коллекций:** Используйте `signatures` для Ansible 2.17+

### Производительность

1. **Используйте shallow clone:** Для больших репозиториев
2. **Кешируйте в CI/CD:** Сохраняйте `~/.ansible/roles/` между сборками
3. **Параллельная установка:** `ansible-galaxy install -r requirements.yml` уже оптимизирована
4. **Ограничивайте глубину clone:** Если нужна только конкретная версия

### Организация кода

1. **Разделяйте роли и плейбуки:** Используйте отдельные репозитории для крупных проектов
2. **Документируйте зависимости:** В README.md каждой роли
3. **Используйте .gitignore:** Исключайте `*.retry`, `*.pyc`, `__pycache__`
4. **Создавайте Makefile:** Для частых команд установки и тестирования

### Стратегия обновления зависимостей

1. **Изолированное тестирование:** Обновляйте зависимости в отдельной ветке, запускайте `ansible-playbook --check` и `ansible-lint`.
2. **Поэтапный rollout:** Сначала обновите в dev/staging, затем в production.
3. **Фиксация после валидации:** После успешного тестирования зафиксируйте новый тег или SHA в `requirements.yml`.
4. **Автоматизация уведомлений:** Используйте `ansible-galaxy collection list --outdated` или GitHub Dependabot для отслеживания обновлений.
5. **Откат:** Сохраняйте предыдущий рабочий `requirements.yml` в Git для быстрого отката.

### Change Management

1. **Внедряйте approval gates:** Изменения в `requirements.yml` должны проходить через pull request с обязательным review.
2. **Документируйте изменения:** Ведите changelog для каждой версии роли.
3. **Тестируйте перед мержем:** Запускайте `ansible-playbook --check` и `ansible-lint` в CI.
4. **Используйте语义化 версионирование:** Позволяет предсказать совместимость обновлений.

### Observability и Audit

1. **Логируйте установку зависимостей:** В CI/CD сохраняйте вывод `ansible-galaxy install` в артефакты сборки.
2. **Аудит версий:** Периодически сравнивайте установленные версии с `requirements.yml`.
3. **Мониторинг изменений:** Настройте алерты на неавторизованные изменения в `requirements.yml`.
4. **Верификация целостности:** Используйте `ansible-galaxy collection verify` для проверки подписей коллекций.

### Disaster Recovery

1. **Резервное копирование requirements.yml:** Храните в отдельном репозитории или хранилище.
2. **Локальный кеш:** Поддерживайте локальный кеш ролей для случаев недоступности Git.
3. **Документированные процедуры отката:** Четко опишите шаги для отката на предыдущую версию.
4. **Тестирование восстановления:** Периодически проверяйте возможность восстановления из резервных копий.

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
