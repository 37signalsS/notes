# Управление ролями и коллекциями через Ansible Galaxy

## Определения

**Ansible Galaxy** — официальный публичный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита командной строки для поиска, установки и управления контентом Ansible.

**Коллекция (Collection)** — современный стандарт упаковки и распространения контента Ansible (начиная с версии 2.10). Включает в себя роли, модули, плагины и документацию. Коллекции имеют пространство имен (например, `community.docker`).

**Роль (Role)** — логическая единица организации задач, переменных и шаблонов для настройки конкретного компонента системы. Роли могут поставляться как отдельно (Legacy-формат), так и внутри коллекций. Подробнее: [ansible_roles.md](../ansible_roles.md).

**Automation Hub / Private Galaxy** — корпоративные альтернативы публичному Galaxy (например, Red Hat Automation Hub, Pulp, Galaxy NG) для хранения приватного или сертифицированного контента.

**Манифест коллекции (`galaxy.yml`)** — YAML-файл в корне коллекции, содержащий метаданные: имя (`namespace.collection`), версию, зависимости, описание. Этот файл обязателен для сборки и публикации коллекции. Аналог `meta/main.yml` для ролей.

**Пространство имен (`namespace`)** — уникальный префикс коллекции, отражающий авторство или организацию (например, `community`, `ansible`, `myorg`). Имена коллекций всегда в формате `namespace.collection`.

---

## Основные концепции

### Команды управления контентом

Утилита `ansible-galaxy` разделена на два подраздела: `role` (для классических ролей) и `collection` (для коллекций).

#### Работа с ролями (Legacy)
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

#### Работа с коллекциями (Modern)
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
ansible.builtin   2.17.0
```

#### Инициализация и публикация коллекции

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

Лучшая практика — определять все внешние зависимости в одном файле `requirements.yml`. Начиная с Ansible 2.10, роли и коллекции можно объединять в одном файле. В Ansible 2.17 синтаксис позволяет детально описывать источники.

**Пример `requirements.yml`:**
```yaml
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

### Настройка прокси и сертификатов

Для работы через корпоративный прокси или с пользовательскими CA-сертификатами:

```bash
# Через переменные среды
export HTTPS_PROXY=http://proxy.example.com:8080
export HTTP_PROXY=http://proxy.example.com:8080
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Игнорирование проверки SSL (НЕ рекомендуется для продакшена)
ansible-galaxy collection install my_ns.my_col --ignore-certs

# Установка с указанием доверенного CA
ansible-galaxy collection install my_ns.my_col \
  --ca-path /etc/ssl/certs/custom-ca.pem
```

---

## Технические детали и безопасность

### Безопасность и проверка подписей (Signature Verification)

В современных версиях Ansible (2.13+) и особенно в 2.17 проверка подписей является ключевым механизмом защиты цепочки поставок (Supply Chain Security). Подписывается файл `MANIFEST.json`, содержащий контрольные суммы всех файлов коллекции.

1.  **Импорт публичного ключа издателя:**
    ```bash
    gpg --import --no-default-keyring --keyring ~/.ansible/pubring.kbx publisher-key.asc
    ```
2.  **Установка с проверкой подписи:**
    Используйте флаг `--keyring` для указания пути к связке ключей и `--signature` для внешних подписей.
    ```bash
    ansible-galaxy collection install my_ns.my_col \
      --signature https://example.com/signatures/my_col.asc \
      --keyring ~/.ansible/pubring.kbx
    ```
3.  **Верификация установленной коллекции:**
    ```bash
    ansible-galaxy collection verify my_ns.my_col --keyring ~/.ansible/pubring.kbx
    ```

### Работа в изолированных средах (Offline / Air-gapped)

Если управляющий узел не имеет доступа к интернету, используется механизм `download`.

1.  **Загрузка на машине с интернетом:**
    ```bash
    # Загрузка по списку требований
    ansible-galaxy collection download -r requirements.yml -p ./offline_deps/
    ```
    Команда скачает `.tar.gz` файлы, их зависимости и создаст локальный `requirements.yml`.
2.  **Перенос и установка на целевом узле:**
    ```bash
    ansible-galaxy collection install -r ./offline_deps/requirements.yml -p ./collections/
    ```

---

## Практические сценарии

### Сценарий 1: Изоляция зависимостей проекта (CI/CD)

В пайплайнах рекомендуется устанавливать роли и коллекции локально в папку проекта, чтобы избежать конфликтов версий и обеспечить воспроизводимость.

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

### Сценарий 2: Интеграция с корпоративным Automation Hub

Настройка доступа к нескольким серверам с приоритетами и проверкой подписей.

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

### Сценарий 3: Создание и публикация собственного контента

1.  **Инициализация:** `ansible-galaxy collection init my_ns.my_col`
2.  **Сборка:** `ansible-galaxy collection build` (создает `.tar.gz`).
3.  **Публикация:** `ansible-galaxy collection publish my_ns-my_col-1.0.0.tar.gz --api-key <secret>`.

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

### Сценарий 4: Установка коллекций для Execution Environments

При использовании Execution Environments (EE) зависимости коллекций описываются в `execution-environment.yml`, а не в `requirements.yml`.

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
```

Детальная информация — в [Execution Environments](../ansible-execution-environments.md).

---

## Troubleshooting

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
[galaxy_server]
url = https://mirror.example.com/galaxy/
```

---

## Best Practices

### Безопасность

1. **Проверка подписей:** Всегда используйте `ansible-galaxy collection verify` после установки критических коллекций.
2. **Фиксация версий:** Никогда не используйте `version: latest` в `requirements.yml` — это может привести к непредсказуемым обновлениям.
3. **Локальное зеркалирование:** В продакшен-средах разверните приватный Galaxy (Pulp, Galaxy NG) для полного контроля над контентом.
4. **Авторизация:** Используйте API-токены вместо логинов/паролей для публикации контента.

### Управление зависимостями

1. **Один `requirements.yml`:** Определяйте все зависимости (роли + коллекции) в одном файле проекта.
2. **Диапазоны версий:** Используйте семантическое версионирование: `community.general: ">=9.0.0,<10.0.0"`.
3. **Изоляция проектов:** Устанавливайте зависимости локально (`-p ./roles/`), а не глобально.
4. **Регулярные обновления:** Периодически проверяйте обновления через `ansible-galaxy collection list --outdated`.

### CI/CD

1. **Кэширование:** Кэшируйте `~/.ansible/` в CI для ускорения сборок.
2. **Идемпотентность:** Используйте `--force` для гарантированной переустановки.
3. **Валидация:** Запускайте `ansible-galaxy collection verify` как шаг проверки.
4. **Версионирование артефактов:** Сохраняйте `requirements.yml` в version control.

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

**Требования:** Настроенная SSH-ключ или Git- credentials.

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

### Удаление устаревшего контента

```bash
# Просмотр всех установленных коллекций с версиями
ansible-galaxy collection list

# Удаление конкретной коллекции
ansible-galaxy collection uninstall community.docker

# Удаление всех коллекций (ОСТОРОЖНО!)
ansible-galaxy collection uninstall --all
```

---

## Дополнительная информация

### Пути поиска и приоритеты

Ansible разрешает пути к контенту в следующем порядке:
1.  **Проектные пути:** Указанные в `ansible.cfg` в корне проекта (`roles_path`, `collections_path`).
2.  **Переменные среды:** `ANSIBLE_ROLES_PATH`, `ANSIBLE_COLLECTIONS_PATHS`.
3.  **Пользовательские:** `~/.ansible/roles`, `~/.ansible/collections`.
4.  **Системные:** `/usr/share/ansible/roles`, `/usr/share/ansible/collections`.

### Системные требования (Ansible 2.17+)

*   **Control Node:** Требуется **Python 3.10+**.
*   **Target Nodes:** Официально прекращена поддержка Python 2.7 и 3.6. Требуется **Python 3.8+** (для Ansible 2.18+).

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

Подробнее: **[Управление ролями через Git](git_management.md)**.

### См. также

- [Создание и использование ролей](usage.md) — технические детали подключения в плейбуках
- [Структура роли](structure.md) — описание каталогов и meta-файлов
- [Управление через Git](git_management.md) — альтернативный подход к управлению зависимостям
- [Execution Environments](../ansible-execution-environments.md) — контейнеризированные среды для Ansible
