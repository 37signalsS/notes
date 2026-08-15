# Управление ролями и коллекциями через Ansible Galaxy

## Определения

**Ansible Galaxy** — официальный публичный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита командной строки для поиска, установки и управления контентом Ansible.

**Коллекция (Collection)** — современный стандарт упаковки и распространения контента Ansible (начиная с версии 2.10). Включает в себя роли, модули, плагины и документацию. Коллекции имеют пространство имен (например, `community.docker`).

**Роль (Role)** — логическая единица организации задач, переменных и шаблонов для настройки конкретного компонента системы. Роли могут поставляться как отдельно (Legacy-формат), так и внутри коллекций. Подробнее: [ansible_roles.md](../ansible_roles.md).

**Automation Hub / Private Galaxy** — корпоративные альтернативы публичному Galaxy (например, Red Hat Automation Hub, Pulp, Galaxy NG) для хранения приватного или сертифицированного контента.

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

### Сценарий 3: Создание и публикация собственного контента

1.  **Инициализация:** `ansible-galaxy collection init my_ns.my_col`
2.  **Сборка:** `ansible-galaxy collection build` (создает `.tar.gz`).
3.  **Публикация:** `ansible-galaxy collection publish my_ns-my_col-1.0.0.tar.gz --api-key <secret>`.

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
*   **Target Nodes:** Официально прекращена поддержка Python 2.7 и 3.6. Требуется **Python 3.7+**.

### Разрешение зависимостей (Dependency Resolution)

При установке коллекций `ansible-galaxy` выполняет рекурсивный поиск. Если две коллекции требуют несовместимые версии общей зависимости, установка завершится ошибкой. Флаг `--no-deps` позволяет игнорировать зависимости, но это не рекомендуется для стабильной работы.

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
- [Ansible: Роли и коллекции](../ansible_roles.md) — обзорная концептуальный документ
