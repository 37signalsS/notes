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

# Создание каркаса роли
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

# Проверка целостности (контрольных сумм) установленной коллекции
ansible-galaxy collection verify community.docker

# Просмотр установленных коллекций
ansible-galaxy collection list
```

### Управление зависимостями через `requirements.yml`

Лучшая практика — определять все внешние зависимости в файле `requirements.yml`. Начиная с Ansible 2.10, роли и коллекции можно объединять в одном файле.

**Пример `requirements.yml`:**
```yaml
# Роли
roles:
  # 1. Из Ansible Galaxy
  - name: geerlingguy.postgresql
    version: "1.8.0" # Всегда фиксируйте версии

  # 2. Из Git-репозитория
  - src: https://github.com/geerlingguy/ansible-role-nginx.git
    scm: git
    version: master
    name: nginx

# Коллекции
collections:
  # 3. Из Ansible Galaxy
  - name: community.general
    version: ">=9.0.0"

  # 4. Из Git-репозитория
  - name: https://github.com/ansible-collections/community.docker.git
    type: git
    version: main

  # 5. С проверкой подписи
  - name: my_namespace.secure_collection
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

Для предотвращения подмены контента (Supply Chain Security) Ansible поддерживает проверку GPG-подписей.

1.  **Импорт публичного ключа издателя:**
    ```bash
    gpg --import --no-default-keyring --keyring ~/.ansible/pubring.kbx publisher-key.asc
    ```
2.  **Установка с проверкой:**
    Используйте флаг `--keyring` для указания пути к связке ключей.
    ```bash
    ansible-galaxy collection install my_ns.my_col --keyring ~/.ansible/pubring.kbx
    ```
3.  **Верификация уже установленной коллекции:**
    ```bash
    ansible-galaxy collection verify my_ns.my_col --keyring ~/.ansible/pubring.kbx
    ```

### Работа в изолированных средах (Offline / Air-gapped)

Если управляющий узел не имеет доступа к интернету, используйте механизм `download`.

1.  **Загрузка на машине с интернетом:**
    ```bash
    ansible-galaxy collection download community.crypto -p ./offline_collections/
    ```
    Команда скачает `.tar.gz` файлы, их зависимости и создаст локальный `requirements.yml`.
2.  **Перенос и установка на целевом узле:**
    ```bash
    ansible-galaxy collection install -r ./offline_collections/requirements.yml -p ./collections/
    ```

---

## Практические сценарии

### Сценарий 1: Изоляция зависимостей проекта (CI/CD)

В пайплайнах рекомендуется устанавливать роли и коллекции локально в папку проекта, чтобы избежать конфликтов версий.

**Конфигурация `ansible.cfg`:**
```ini
[defaults]
roles_path = ./roles
collections_path = ./collections
```

**Команда установки:**
```bash
ansible-galaxy install -r requirements.yml -p ./roles/
```

### Сценарий 2: Интеграция с приватным репозиторием (Automation Hub)

Настройка доступа к корпоративному серверу через токены в `ansible.cfg`.

```ini
[galaxy]
server_list = automation_hub, release_galaxy

[galaxy_server.automation_hub]
url = https://console.redhat.com/api/automation-hub/
auth_url = https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token
token = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx # Безопаснее использовать ANSIBLE_GALAXY_TOKEN

[galaxy_server.release_galaxy]
url = https://galaxy.ansible.com/
```

### Сценарий 3: Создание и публикация собственного контента

1.  **Инициализация:** `ansible-galaxy collection init my_ns.my_col`.
2.  **Сборка:** `ansible-galaxy collection build` (создает `.tar.gz`).
3.  **Публикация:** `ansible-galaxy collection publish my_ns-my_col-1.0.0.tar.gz --api-key <secret>`.

---

## Дополнительная информация

### Пути установки и поиск

Ansible ищет контент в следующем порядке:
1.  Пути из `ansible.cfg` (`roles_path`, `collections_path`).
2.  Переменные окружения `ANSIBLE_ROLES_PATH`, `ANSIBLE_COLLECTIONS_PATHS`.
3.  Пути по умолчанию:
    - `~/.ansible/roles` (пользовательские).
    - `/usr/share/ansible/roles` (системные).

### Кэширование и квоты

Для ускорения работы в CI/CD можно включить кэширование:
```ini
[galaxy]
cache_dir = ~/.ansible/galaxy_cache
```

**Полезные переменные окружения:**
- `ANSIBLE_GALAXY_SERVER_LIST`: Список серверов.
- `ANSIBLE_GALAXY_TOKEN`: Токен аутентификации.

### Сравнение с ручным управлением через Git

Альтернатива Galaxy — использование модуля `ansible.builtin.git` или Git Submodules. Это полезно для быстрой правки внешних ролей "на месте", но усложняет управление версиями коллекций. Подробнее: [git_management.md](git_management.md#сравнение-с-ansible-galaxy).

### См. также

- [Создание и использование ролей](usage.md) — технические детали подключения
- [Структура роли](structure.md) — описание каталогов и meta-файлов
- [ansible_roles.md](../ansible_roles.md) — обзорная статья о ролях и коллекциях
