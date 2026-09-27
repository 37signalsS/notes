# Управление ролями и коллекциями через Ansible Galaxy

## Определения

**Ansible Galaxy** — официальный публичный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита командной строки для поиска, установки и управления контентом Ansible.

**Коллекция (Collection)** — современный стандарт упаковки и распространения контента Ansible (начиная с версии 2.10). Включает в себя роли, модули, плагины и документацию. Коллекции имеют пространство имен (например, `community.docker`). Подробнее о структуре: [ansible_collections_deep_dive.md](../ansible_collections_deep_dive.md).

**Роль (Role)** — логическая единица организации задач, переменных и шаблонов для настройки конкретного компонента системы. Роли могут поставляться как отдельно (Legacy-формат), так и внутри коллекций. Подробнее: [ansible_roles.md](../ansible_roles.md).

**Automation Hub / Private Galaxy** — корпоративные альтернативы публичному Galaxy (например, Red Hat Automation Hub, Pulp, Galaxy NG) для хранения приватного или сертифицированного контента.

**Манифест коллекции (`galaxy.yml`)** — YAML-файл в корне коллекции, содержащий метаданные: имя (`namespace.collection`), версию, зависимости, описание. Этот файл обязателен для сборки и публикации коллекции. Аналог `meta/main.yml` для ролей.

**Пространство имен (`namespace`)** — уникальный префикс коллекции, отражающий авторство или организацию (например, `community`, `ansible`, `myorg`). Имена коллекций всегда в формате `namespace.collection`.

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource` для однозначной идентификации модулей, плагинов или ролей внутри коллекции.

**Artifact** — tar.gz-архив, создаваемый при сборке коллекции (`ansible-galaxy collection build`), содержащий все файлы коллекции с контрольными суммами в `MANIFEST.json`.

**Supply Chain Security** — практики защиты цепочки поставок контента: проверка подписей, контроль версий зависимостей, аудит использованных компонентов. Подробнее о безопасной работе с Galaxy: [ansible_security_best_practices.md](../ansible_security_best_practices.md).

---

## Предварительные требования

### Системные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.21.4 | Ядро Ansible с CLI `ansible-galaxy` |
| **Python** | 3.12+ (Control Node) | Исполнение `ansible-galaxy` и модулей |
| **Python** | 3.9+ (Target Node) | Исполнение модулей на управляемых узлах |
| **Git** | 2.20+ | Работа с Git-источниками в `requirements.yml` |
| **GPG** | 2.2+ | Проверка подписей коллекций (опционально) |

### Проверка окружения

```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible-galaxy --version
# → ansible-galaxy core 2.21.4

python3 --version
# → Python 3.12.x

git --version
# → git version 2.43.x
```

---

## Основные концепции / Архитектура / Принципы работы

### Архитектура Galaxy

Ansible Galaxy состоит из двух частей:
1. **Сервис Galaxy** — веб-интерфейс и REST API для публикации и поиска контента. Хранит артефакты (`.tar.gz`), метаданные и контрольные суммы.
2. **CLI `ansible-galaxy`** — утилита на стороне Control Node, которая взаимодействует с сервисом через API для загрузки артефактов и разрешения зависимостей.

### Жизненный цикл коллекции

```text
Создание → Сборка (build) → Публикация (publish) → Установка (install) → Верификация (verify)
    ↓           ↓                ↓                   ↓                ↓
Инициализация  tar.gz          Galaxy API           ~/.ansible/      GPG-подпись
                artifact         / Automation Hub     collections/     MANIFEST.json
```

Для SRE и sysadmin жизненный цикл критичен при управлении изменениями: каждый этап должен быть проверяемым и воспроизводимым. Фиксация версий в `requirements.yml` обеспечивает детерминированные сборки и упрощает откат при инцидентах.

### Разрешение зависимостей

При установке `ansible-galaxy` выполняет рекурсивный обход зависимостей:
1. Читает `requirements.yml` или запрашивает артефакт по имени.
2. Скачивает `MANIFEST.json` и извлекает зависимости из `galaxy.yml` артефакта.
3. Для каждой зависимости проверяет, установлена ли подходящая версия.
4. Если найдены конфликты версий — завершает установку с ошибкой.

Конфликты зависимостей — частая причина инцидентов в CI/CD. Используйте семантическое версионирование и фиксацию версий для минимизации рисков.

### Приоритет серверов (Server Priority)

При использовании `server_list` Galaxy ищет коллекции в порядке, указанном в `ansible.cfg`:

```ini
[galaxy]
server_list = automation_hub, public_galaxy

[galaxy_server.automation_hub]
url = https://hub.example.com/api/galaxy/

[galaxy_server.public_galaxy]
url = https://galaxy.ansible.com/
```

Зависимости разрешаются поочередно: если `automation_hub` не содержит нужной коллекции, поиск продолжается на `public_galaxy`.

### Управление кэшем Galaxy

Ansible кэширует метаданные коллекций для ускорения повторных операций. По умолчанию кэш хранится в `~/.ansible/galaxy_cache`.

```ini
# ansible.cfg
[galaxy]
cache_dir = ~/.ansible/galaxy_cache
# Время жизни кэша (секунды), по умолчанию 600
# cache_ttl = 600
```

```bash
# Очистка кэша (удаление каталога)
rm -rf ~/.ansible/galaxy_cache/

# Принудительное обновление без использования кэша
ansible-galaxy collection install community.docker --force
```

### Подписи и Supply Chain Security

Начиная с Ansible 2.13+, Galaxy поддерживает проверку GPG-подписей коллекций. Для production-сред это обязательная практика:

```bash
# Проверка подписи установленной коллекции
ansible-galaxy collection verify community.general

# Установка с указанием ключа
ansible-galaxy collection install my_ns.my_col \
  --keyring ~/.ansible/pubring.kbx
```

Подробнее о политиках подписей и хранения ключей: [ansible_security_best_practices.md](../ansible_security_best_practices.md).

### Работа в изолированных средах (Offline / Air-gapped)

Если управляющий узел не имеет доступа к интернету, используется механизм `download`:

1. **Загрузка на машине с интернетом:**
    ```bash
    # Загрузка по списку требований
    ansible-galaxy collection download -r requirements.yml -p ./offline_deps/
    ```
    Команда скачает `.tar.gz` файлы, их зависимости и создаст локальный `requirements.yml`.

2. **Перенос и установка на целевом узле:**
    ```bash
    ansible-galaxy collection install -r ./offline_deps/requirements.yml -p ./collections/
    ```

Для полностью изолированных сред (air-gapped) требуется локальное зеркало. Подробнее в сценарии 5.

---

## Практические сценарии

### Сценарий 1: Изоляция зависимостей проекта (CI/CD)

В пайплайнах рекомендуется устанавливать роли и коллекции локально в папку проекта, чтобы избежать конфликтов версий и обеспечить воспроизводимость.

**Предварительные требования:**
- Установленный `ansible-core` в CI-контейнере/образе
- Файл `requirements.yml` в корне репозитория

**Конфигурация `ansible.cfg`:**
```ini
[defaults]
roles_path = ./roles
collections_path = ./collections

[galaxy]
cache_dir = ~/.ansible/galaxy_cache
```

**Команда установки в CI:**
```bash
ansible-galaxy install -r requirements.yml -p ./roles/ --force
# → Starting galaxy role install process
# → Starting galaxy collection install process
```

**Пример `.gitlab-ci.yml` с кэшированием:**
```yaml
.ansible_base:
  image: python:3.12-slim
  variables:
    ANSIBLE_COLLECTIONS_PATH: "${CI_PROJECT_DIR}/.ansible/collections"
    ANSIBLE_ROLES_PATH: "${CI_PROJECT_DIR}/.ansible/roles"
  before_script:
    - pip install ansible-core
    - ansible-galaxy install -r requirements.yml
  cache:
    key: ansible-deps
    paths:
      - .ansible/

deploy:
  extends: .ansible_base
  script:
    - ansible-playbook site.yml
```

**Пример GitHub Actions:**
```yaml
name: Deploy with Ansible
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Ansible
        run: pip install ansible-core
      - name: Install dependencies
        run: ansible-galaxy install -r requirements.yml -p ./collections/
      - name: Run playbook
        run: ansible-playbook -i inventory site.yml
```

**Валидация:**
```bash
# Проверка установленных зависимостей
ansible-galaxy collection list
# → community.general 9.0.0

ansible-galaxy role list
# → geerlingguy.nginx 3.3.0
```

### Сценарий 2: Интеграция с корпоративным Automation Hub

Настройка доступа к нескольким серверам с приоритетами и проверкой подписей.

**Предварительные требования:**
- URL Automation Hub с валидным SSL-сертификатом
- API-токен или OIDC-клиентские данные
- GPG-ключ для проверки подписей (опционально)

**Конфигурация `ansible.cfg`:**
```ini
[galaxy]
server_list = automation_hub, public_galaxy

[galaxy_server.automation_hub]
url = https://hub.example.com/api/galaxy/
auth_url = https://sso.example.com/auth/realms/ansible/protocol/openid-connect/token
token = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# Обязательная проверка подписей для этого сервера
gpg_keyring = ~/.ansible/pubring.kbx

[galaxy_server.public_galaxy]
url = https://galaxy.ansible.com/
```

**Автоматическое получение токена через SSO:**
```bash
# Получение токена через OIDC (Keycloak / Azure AD)
TOKEN=$(curl -s -d "grant_type=client_credentials" \
  -d "client_id=ansible" \
  -d "client_secret=${CLIENT_SECRET}" \
  ${AUTH_URL} | jq -r '.access_token')

# Установка с токеном
ansible-galaxy collection install my_ns.my_col --token ${TOKEN}
```

**Валидация:**
```bash
# Проверка списка серверов
ansible-galaxy server list
# → automation_hub (configured)
# → public_galaxy (configured)

# Установка с явным указанием сервера
ansible-galaxy collection install my_ns.my_col --server automation_hub
```

### Сценарий 3: Создание и публикация собственного контента

1. **Инициализация:** `ansible-galaxy collection init my_ns.my_col`
2. **Сборка:** `ansible-galaxy collection build` (создает `.tar.gz`).
3. **Публикация:** `ansible-galaxy collection publish my_ns-my_col-1.0.0.tar.gz --api-key <secret>`.

Структура коллекции подробно описана в [ansible_collections_deep_dive.md](../ansible_collections_deep_dive.md). Здесь описывается только workflow публикации.

**Автоматизация публикации в CI/CD:**
```yaml
publish:
  stage: publish
  script:
    - ansible-galaxy collection build --force
    - ansible-galaxy collection publish *.tar.gz --api-key ${GALAXY_API_KEY}
  only:
    - tags
  when: manual
```

**Валидация:**
```bash
# Проверка содержимого артефакта
tar -tzf my_namespace-my_collection-1.0.0.tar.gz
# → galaxy.yml
# → README.md
# → plugins/...

# Проверка manifest
ansible-galaxy collection info my_ns.my_col
```

### Сценарий 4: Аудит и верификация зависимостей (Supply Chain Security)

Для SRE критически важно регулярно проверять установленный контент на соответствие политикам организации.

**Предварительные требования:**
- GPG-ключ для проверки подписей
- Фиксированные версии в `requirements.yml`
- `ansible-lint` с security-профилем

**Проверка подлинности коллекций:**
```bash
# Верификация GPG-подписей всех установленных коллекций
ansible-galaxy collection list | awk 'NR>2 {print $1}' | while read col; do
  ansible-galaxy collection verify "$col"
done

# Проверка на устаревшие версии
ansible-galaxy collection list --outdated
```

**CI-пайплайн аудита:**
```yaml
audit_dependencies:
  stage: verify
  image: python:3.12-slim
  script:
    - pip install ansible-core ansible-lint
    - ansible-galaxy install -r requirements.yml
    - ansible-galaxy collection list --outdated
    - |
      for col in $(ansible-galaxy collection list | awk 'NR>2 {print $1}'); do
        ansible-galaxy collection verify "$col" || exit 1
      done
  allow_failure: true
```

### Сценарий 5: Зеркалирование и снапшоты для изолированных сред

Для полностью изолированных сред (air-gapped) требуется локальное зеркало.

**Предварительные требования:**
- Pulp / Galaxy NG / Pulpcore развернут в закрытом контуре
- Сертификаты для доступа к зеркалу

**Настройка зеркала в `ansible.cfg`:**
```ini
[galaxy]
server_list = mirror, public_galaxy

[galaxy_server.mirror]
url = https://mirror.internal/api/galaxy/
# token не требуется для чтения, если настроен anonymous access

[galaxy_server.public_galaxy]
url = https://galaxy.ansible.com/
```

**Синхронизация с зеркалом:**
```bash
# На машине с доступом к публичному Galaxy
ansible-galaxy collection download community.docker -p ./sync/
ansible-galaxy collection download community.general -p ./sync/

# Загрузка в приватный реестр (через API Pulp)
# или копирование tar.gz на файловый сервер
```

### Сценарий 6: Управление изменениями и откат контента

При обновлении коллекций в production-среде SRE должен иметь возможность быстрого отката.

**Стратегия:**
1. Фиксируйте текущий `requirements.yml` в Git перед обновлением.
2. Обновляйте в staging, затем прогоняйте smoke-тесты.
3. При успехе — обновляйте production.

```bash
# Создание снапшота текущих зависимостей
cp requirements.yml requirements.yml.backup
git add requirements.yml.backup
git commit -m "chore: snapshot Galaxy dependencies before update"

# Обновление
ansible-galaxy collection install community.general --upgrade

# При проблемах — откат
cp requirements.yml.backup requirements.yml
ansible-galaxy collection install -r requirements.yml --force-with-deps
```

### Сценарий 7: Установка зависимостей для Execution Environments

При использовании Execution Environments (EE) зависимости коллекций описываются в `execution-environment.yml`, а не в `requirements.yml`.

**Предварительные требования:**
- Установленный `ansible-builder`
- Доступ к registry (quay.io, Docker Hub)

**Файл `execution-environment.yml`:**
```yaml
version: 3
build_arg_defaults:
  ansible_runner_image: quay.io/ansible/creator-ee:latest
dependencies:
  galaxy: requirements.yml         # Коллекции и роли из Galaxy
  python: requirements.txt         # Python-библиотеки
  system: []                       # Системные пакеты
options:
  package_manager: pip
```

**Сборка EE:**
```bash
ansible-builder build -t my-custom-ee:latest
# → Step 1/5 : FROM quay.io/ansible/creator-ee:latest
# → Step 2/5 : COPY requirements.yml /build/requirements.yml
# → ...
# → Successfully tagged my-custom-ee:latest
```

Детальная информация — в [Execution Environments](../ansible-execution-environments.md).

---

## Операции и команды

Утилита `ansible-galaxy` разделена на два подраздела: `role` (для классических ролей) и `collection` (для коллекций).

### Работа с ролями (Legacy)

```bash
# Поиск ролей по ключевому слову
ansible-galaxy role search postgresql

# Создание каркаса роли со стандартной структурой
ansible-galaxy role init my_new_role

# Установка роли (по умолчанию в ~/.ansible/roles)
ansible-galaxy role install geerlingguy.postgresql

# Установка в конкретный путь (флаг -p)
ansible-galaxy role install geerlingguy.nginx -p ./roles/

# Принудительное обновление (флаг -f)
ansible-galaxy role install geerlingguy.postgresql -f

# Список установленных ролей
ansible-galaxy role list
```

### Работа с коллекциями (Modern)

```bash
# Поиск коллекций
ansible-galaxy collection search community

# Установка коллекции (по умолчанию в ~/.ansible/collections)
ansible-galaxy collection install community.postgresql

# Установка/обновление до последней версии
ansible-galaxy collection install community.docker --upgrade

# Проверка целостности и подписи установленной коллекции
ansible-galaxy collection verify community.docker

# Просмотр установленных коллекций
ansible-galaxy collection list

# Просмотр коллекций в конкретном пути
ansible-galaxy collection list -p ./collections/
```

**Пример вывода `ansible-galaxy collection list`:**

```text
Collection        Version
----------------- -------
community.docker  4.1.0
community.general 9.0.0
ansible.builtin   2.21.0
```

### Справочная таблица команд

| Команда | Назначение | Ключевые флаги |
| :--- | :--- | :--- |
| `ansible-galaxy role search <query>` | Поиск ролей по ключевому слову | `--author`, `--galaxy` |
| `ansible-galaxy role init <name>` | Создание каркаса роли | — |
| `ansible-galaxy role install <name>` | Установка роли | `-p <path>`, `-f`, `-r <file>` |
| `ansible-galaxy role list` | Список установленных ролей | `-p <path>` |
| `ansible-galaxy role remove <name>` | Удаление роли из `roles_path` | — |
| `ansible-galaxy collection search <query>` | Поиск коллекций | `--galaxy` |
| `ansible-galaxy collection install <name>` | Установка коллекции | `--upgrade`, `-p <path>`, `-r <file>`, `--force-with-deps`, `--no-deps` |
| `ansible-galaxy collection verify <name>` | Проверка целостности/подписи | `--keyring <path>` |
| `ansible-galaxy collection list` | Список установленных коллекций | `-p <path>`, `--outdated` |
| `ansible-galaxy collection build` | Сборка `.tar.gz` артефакта | `--force` |
| `ansible-galaxy collection publish <file>` | Публикация на Galaxy | `--api-key`, `--server` |
| `ansible-galaxy collection download` | Загрузка для офлайн-сред | `-r <file>`, `-p <path>` |
| `ansible-galaxy collection info <name>` | Информация о коллекции | `--offline` |
| `ansible-galaxy server list` | Список настроенных серверов | — |
| `ansible-galaxy install -r <file>` | Установка всех зависимостей | `-p <path>`, `--force` |

### Инициализация и публикация коллекции

```bash
# Создание каркаса коллекции
ansible-galaxy collection init my_namespace.my_collection

# Сборка tar.gz-архива для публикации
ansible-galaxy collection build

# Публикация на Galaxy
ansible-galaxy collection publish my_namespace-my_collection-1.0.0.tar.gz --api-key <API_KEY>
```

**Структура, создаваемая `collection init`:**

```text
my_collection/
├── galaxy.yml           # Манифест коллекции (обязателен)
├── README.md            # Документация
├── meta/
│   └── runtime.yml      # Маппинг deprecated-модулей
├── plugins/
│   ├── modules/         # Модули
│   ├── filter/          # Фильтры Jinja2
│   ├── lookup/          # Lookup-плагины
│   ├── callback/        # Callback-плагины
│   ├── connection/      # Плагины подключения
│   ├── module_utils/    # Утилиты для модулей
│   └── test/            # Тесты плагинов
├── roles/
│   └── my_role/         # Роли внутри коллекции
├── playbooks/           # Playbooks коллекции
└── tests/
    ├── sanity/          # Тесты целостности
    ├── integration/     # Интеграционные тесты
    └── unit/            # Юнит-тесты
```

**Пример `galaxy.yml`:**

```yaml
namespace: my_namespace
name: my_collection
version: 1.0.0
description: Описание моей коллекции
license:
  - MIT
authors:
  - Имя Автора
dependencies:
  community.general: ">=9.0.0"   # Зависимости от других коллекций
repository: https://github.com/myorg/my_collection
documentation: https://myorg.github.io/my_collection
homepage: https://github.com/myorg/my_collection
issues: https://github.com/myorg/my_collection/issues
build_ignore:
  - tests/
  - .git/
```

### Управление зависимостями через `requirements.yml`

Лучшая практика — определять все внешние зависимости в одном файле `requirements.yml`. Начиная с Ansible 2.10, роли и коллекции можно объединять в одном файле. В Ansible 2.17+ синтаксис позволяет детально описывать источники и подписи.

**Пример `requirements.yml`:**

```yaml
---
# Роли
roles:
  # 1. Из Ansible Galaxy с фиксацией версии
  - name: geerlingguy.postgresql
    version: "1.8.0"

  # 2. Из Git-репозитория (Legacy синтаксис)
  - src: https://github.com/geerlingguy/ansible-role-nginx.git
    scm: git
    version: master
    name: nginx

# Коллекции
collections:
  # 3. Из Ansible Galaxy с диапазоном версий
  - name: community.general
    version: ">=9.0.0"

  # 4. Из Git-репозитория (Modern синтаксис)
  - name: https://github.com/ansible-collections/community.docker.git
    type: git
    version: main

  # 5. С проверкой подписи (Ansible 2.17+)
  - name: my_namespace.secure_collection
    version: "1.0.0"
    signatures:
      - https://example.com/signatures/manifest.json.asc
```

**Установка зависимостей:**

```bash
# Установка всего содержимого (рекомендуется)
ansible-galaxy install -r requirements.yml

# Явная установка только ролей или коллекций
ansible-galaxy role install -r requirements.yml
ansible-galaxy collection install -r requirements.yml

# Принудительное обновление с зависимостями
ansible-galaxy collection install -r requirements.yml --force-with-deps
```

---

## Устранение неполадок

### Ошибка: "No valid repositories found"

**Причина:** Неправильный URL сервера Galaxy или проблемы с сетью.

**Решение:**
```bash
# Проверка доступности сервера
curl -I https://galaxy.ansible.com/

# Проверка конфигурации серверов
ansible-galaxy server list

# Сброс конфигурации
unset ANSIBLE_GALAXY_SERVER_LIST
```

### Ошибка: "Could not find a requirements.yml file"

**Причина:** Файл `requirements.yml` отсутствует в текущей директории или не указан путь.

**Решение:**
```bash
# Указание явного пути
ansible-galaxy install -r /path/to/requirements.yml

# Проверка наличия файла
ls -la requirements.yml
```

### Ошибка: "Collection already installed"

**Причина:** Коллекция уже установлена, и нет флага обновления.

**Решение:**
```bash
# Принудительное обновление
ansible-galaxy collection install community.docker --force

# Обновление только если доступна более новая версия
ansible-galaxy collection install community.docker --upgrade
```

### Ошибка: "Failed to import the collection"

**Причина:** Несовместимая структура коллекции или поврежденные файлы.

**Решение:**
```bash
# Удаление и переустановка
ansible-galaxy collection uninstall community.docker
ansible-galaxy collection install community.docker

# Проверка целостности
ansible-galaxy collection verify community.docker
```

### Ошибка: "Permission denied" при установке

**Причина:** Недостаточные права на запись в директорию установки.

**Решение:**
```bash
# Установка в пользовательскую директорию
ansible-galaxy collection install community.docker -p ~/.ansible/collections

# Или исправление прав (не рекомендуется для системных директорий)
sudo chown -R $(whoami) ~/.ansible/
```

### Ошибка: "Conflict detected" при разрешении зависимостей

**Причина:** Две зависимости требуют несовместимые версии одной коллекции.

**Диагностика:**
```bash
# Просмотр установленных версий
ansible-galaxy collection list

# Проверка дерева зависимостей
pip install pipdeptree
pipdeptree --warn silence
```

**Решение:**
```yaml
# Фиксация совместимой версии в requirements.yml
collections:
  - name: community.docker
    version: "3.10.0"  # Точная версия, удовлетворяющая обеим зависимостям
```

### Медленная загрузка коллекций

**Причина:** Медленное соединение или отсутствие кэширования.

**Решение:**
```bash
# Включение кэширования в ansible.cfg
[galaxy]
cache_dir = ~/.ansible/galaxy_cache
cache_ttl = 3600

# Использование зеркала (если доступно)
# В ansible.cfg:
[galaxy_server.mirror]
url = https://mirror.internal/api/galaxy/
```

### Ошибка: "Collection signature verification failed"

**Причина:** Коллекция повреждена, подменена или отсутствует GPG-ключ.

**Решение:**
```bash
# Переустановка с явным указанием ключа
ansible-galaxy collection install community.docker \
  --keyring ~/.ansible/pubring.kbx

# Или принудительная переустановка (если политика позволяет)
ansible-galaxy collection install community.docker --force
```

### Ошибка: "Version not found" при установке из Git

**Причина:** Указанный тег, ветка или коммит не существует в репозитории.

**Решение:**
```bash
# Просмотр доступных тегов
git ls-remote --tags git@github.com:org/role.git

# Просмотр доступных веток
git ls-remote --heads git@github.com:org/role.git

# Проверка прав доступа
ssh -T git@github.com
```

Подробнее о работе с Git-источниками: [git_management.md](../Roles/git_management.md).

---

## Best Practices

### Безопасность и Supply Chain

1. **Проверка подписей:** Всегда используйте `ansible-galaxy collection verify` после установки критических коллекций. Подробнее о Supply Chain Security — в [ansible_security_best_practices.md](../ansible_security_best_practices.md).
2. **Фиксация версий:** Никогда не используйте `version: latest` в `requirements.yml` — это может привести к непредсказуемым обновлениям. Используйте семантические диапазоны: `>=9.0.0,<10.0.0`.
3. **Локальное зеркалирование:** В продакшен-средах разверните приватный Galaxy (Pulp, Galaxy NG) для полного контроля над контентом.
4. **Авторизация:** Используйте API-токены вместо логинов/паролей для публикации контента.
5. **no_log:** Задачи с секретами должны иметь `no_log: true`. Подробнее — в [ansible_security_best_practices.md](../ansible_security_best_practices.md).

### Управление зависимостями

1. **Один `requirements.yml`:** Определяйте все зависимости (роли + коллекции) в одном файле проекта.
2. **Диапазоны версий:** Используйте семантическое версионирование: `community.general: ">=9.0.0,<10.0.0"`.
3. **Изоляция проектов:** Устанавливайте зависимости локально (`-p ./roles/` или `-p ./collections/`), а не глобально.
4. **Регулярные обновления:** Периодически проверяйте обновления через `ansible-galaxy collection list --outdated`.
5. **Блокировка зависимостей:** Для CI/CD фиксируйте точные версии в `requirements.yml` и проверяйте их в Git.
6. **Снапшоты перед обновлением:** Сохраняйте текущий `requirements.yml` перед обновлением для быстрого отката.

### CI/CD и Change Management

1. **Кэширование:** Кэшируйте `~/.ansible/` в CI для ускорения сборок.
2. **Идемпотентность:** Используйте `--force` для гарантированной переустановки в CI.
3. **Валидация:** Запускайте `ansible-galaxy collection verify` как шаг проверки.
4. **Версионирование артефактов:** Сохраняйте `requirements.yml` в version control.
5. **Стейджинг:** Обновляйте зависимости сначала в dev/staging, затем в production.

### SRE и Operations

1. **Наблюдаемость:** Включайте callback-плагины для логирования установки зависимостей в SIEM/ELK.
2. **Аудит:** Периодически запускайте `ansible-galaxy collection list --outdated` и проверяйте подписи.
3. **Документация:** Ведомляйте `requirements.yml` и политики версионирования в реестре знаний.
4. **Откат:** Поддерживайте процедуру быстрого отката `requirements.yml` при инцидентах.
5. **Изоляция:** Используйте локальные пути (`-p ./collections/`) в CI для воспроизводимости.

---

## Edge Cases

### Установка из приватного Git-репозитория

```yaml
# requirements.yml
collections:
  - name: https://github.com/myorg/private-collection.git
    type: git
    version: v1.0.0
    # Для SSH:
    # src: git@github.com:myorg/private-collection.git
```

**Требования:** Настроенная SSH-ключ или Git-credentials. Подробнее — в [Управление через Git](../Roles/git_management.md).

### Конфликт имен между Galaxy и локальной коллекцией

Если локальная коллекция имеет то же имя, что и установленная через Galaxy, приоритет определяется путями в `ansible.cfg`:

```ini
[defaults]
# Локальные пути имеют приоритет над глобальными
collections_path = ./collections:~/.ansible/collections
```

### Установка конкретной версии роли из коллекции

```yaml
# requirements.yml
collections:
  - name: community.general
    version: "9.0.0"

roles:
  # Роль внутри коллекции
  - name: community.general.docker_install
    # Автоматически определит коллекцию как источник
```

### Pre-release версии

По умолчанию `ansible-galaxy` игнорирует pre-release версии. Для их установки используйте точное совпадение:

```bash
# Установка pre-release версии
ansible-galaxy collection install my_ns.my_col==1.0.0-beta.1
```

### Удаление устаревшего контента

```bash
# Просмотр всех установленных коллекций с версиями
ansible-galaxy collection list

# Удаление конкретной коллекции
ansible-galaxy collection uninstall community.docker

# Удаление всех коллекций (ОСТОРОЖНО!)
ansible-galaxy collection uninstall --all
```

### Заморозка зависимостей (Frozen Dependencies)

Начиная с Ansible 2.18+, можно создавать снапшоты зависимостей:

```bash
# Генерация frozen requirements
ansible-galaxy collection list --format yaml > frozen_requirements.yml

# Восстановление из снапшота
ansible-galaxy collection install -r frozen_requirements.yml
```

### Ограничение пропускной способности в CI

```bash
# Установка с ограничением скорости (если поддерживается)
ansible-galaxy collection install community.general \
  --timeout 30 \
  --retries 3
```

---

## Дополнительная информация

### Пути поиска и приоритеты

Ansible разрешает пути к контенту в следующем порядке:
1.  **Проектные пути:** Указанные в `ansible.cfg` в корне проекта (`roles_path`, `collections_path`).
2.  **Переменные среды:** `ANSIBLE_ROLES_PATH`, `ANSIBLE_COLLECTIONS_PATHS`.
3.  **Пользовательские:** `~/.ansible/roles`, `~/.ansible/collections`.
4.  **Системные:** `/usr/share/ansible/roles`, `/usr/share/ansible/collections`.

### Системные требования (Ansible 2.21+)

*   **Control Node:** Требуется **Python 3.12+**.
*   **Target Nodes:** Официально прекращена поддержка Python 2.7 и 3.6. Требуется **Python 3.9+** (для Ansible 2.21+).

### Разрешение зависимостей (Dependency Resolution)

При установке коллекций `ansible-galaxy` выполняет рекурсивный поиск. Если две коллекции требуют несовместимые версии общей зависимости, установка завершится ошибкой. Флаг `--no-deps` позволяет игнорировать зависимости, но это не рекомендуется для стабильной работы.

```bash
# Пример ошибки конфликта зависимостей
ERROR! Conflict detected "community.docker >= 3.0.0" (requested by my.collection)
and "community.docker < 4.0.0" (requested by other.collection)

# Решение: указание конкретной версии в requirements.yml
collections:
  - name: community.docker
    version: "3.10.0"  # Точная версия, удовлетворяющая обеим зависимостям
```

### Сравнение с ручным управлением через Git

| Критерий | Ansible Galaxy / `requirements.yml` | Git Submodules / Manual |
| :--- | :--- | :--- |
| **Удобство** | Высокое (одна команда для всех зависимостей) | Низкое (ручное обновление каждого репо) |
| **Версионирование** | Семантическое (1.2.0, >=2.0) | По хэшам или веткам Git |
| **Коллекции** | Полная поддержка | Ограниченная (требует спец. структуры) |
| **Безопасность** | Проверка подписей GPG | Проверка SSH/HTTPS ключей |

Подробнее: **[Управление ролями через Git](../Roles/git_management.md)**.

### См. также

- [Ansible Collections: создание и управление](../ansible_collections_deep_dive.md) — углубленное руководство по коллекциям
- [Управление ролями через Git](../Roles/git_management.md) — альтернативный подход к управлению зависимостями
- [Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md) — Supply Chain Security и проверка подписей
