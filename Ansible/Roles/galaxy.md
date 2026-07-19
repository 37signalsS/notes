# Управление ролями с Ansible Galaxy

## Определения

**Ansible Galaxy** — официальный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита CLI (Command Line Interface — интерфейс командной строки) для поиска, обмена и управления контентом Ansible (роли, коллекции).

**Коллекция (Collection)** — структура, содержащая роли, модули, плагины и документацию для работы с экосистемой (например, `community.postgresql`).

**Роль (Role)** — базовая единица переиспользования: предопределенная структура файлов для автоматизации компонента системы. Подробнее: [ansible_roles.md](../ansible_roles.md).

---

## Основные концепции

### Команды управления

**Поиск контента:**

```bash
# Поиск ролей по ключевому слову
ansible-galaxy role search postgresql

# Поиск коллекций
ansible-galaxy collection search community
```

**Создание каркаса роли:**

```bash
ansible-galaxy role init my_new_role  # → роль успешно инициализирована
```

**Установка ролей и коллекций:**

```bash
# Установить роль в директорию по умолчанию
ansible-galaxy role install geerlingguy.postgresql  # → роль установлена в ~/.ansible/roles

# Установить коллекцию
ansible-galaxy collection install community.postgresql  # → коллекция установлена в ~/.ansible/collections

# Установка в конкретный путь (флаг -p)
ansible-galaxy role install geerlingguy.nginx -p ./roles/  # → роль установлена в локальную папку проекта

# Принудительное обновление (флаг -f)
ansible-galaxy role install geerlingguy.postgresql -f  # → существующая роль перезаписана
```

**Просмотр установленных компонентов:**

```bash
ansible-galaxy role list  # → список установленных ролей
ansible-galaxy collection list  # → список установленных коллекций
```

**Проверка целостности коллекции:**

```bash
ansible-galaxy collection verify community.postgresql  # → проверка контрольных сумм файлов коллекции
```

### Управление зависимостями через `requirements.yml`

Лучшая практика — определять все внешние роли и коллекции в файле `requirements.yml`. Начиная с Ansible 2.10, можно объединять роли и коллекции в одном файле.

**Пример `requirements.yml`:**

```yaml
# Роли
roles:
  # 1. Из Ansible Galaxy
  - name: geerlingguy.postgresql
    version: 1.8.0

  # 2. Из Git-репозитория
  - src: https://github.com/geerlingguy/ansible-role-nginx.git
    scm: git
    version: master
    name: nginx

# Коллекции
collections:
  # 3. Из Ansible Galaxy
  - name: community.postgresql
    version: 2.3.0

  # 4. Из Git-репозитория
  - name: https://github.com/ansible-collections/community.docker.git
    type: git
    version: main
```

**Установка зависимостей из файла:**

```bash
# Установка ролей и коллекций одновременно (Ansible 2.10+)
ansible-galaxy install -r requirements.yml

# Явная установка только ролей или только коллекций
ansible-galaxy role install -r requirements.yml
ansible-galaxy collection install -r requirements.yml
```

---

## Практические сценарии

### Сценарий 1: Быстрое развертывание с готовыми ролями

```bash
# Поиск нужной роли
ansible-galaxy role search nginx

# Установка роли от Geerlingguy
ansible-galaxy role install geerlingguy.nginx
```

### Сценарий 2: Изоляция зависимостей проекта (CI/CD)

В CI/CD пайплайнах часто требуется устанавливать роли локально в папку проекта, чтобы не загрязнять системные директории:

```bash
# Установка в локальную папку roles/ внутри проекта
ansible-galaxy install -r requirements.yml -p ./roles/
```

### Сценарий 3: Версионирование и "заморозка" зависимостей

Для обеспечения идентичности окружений на Dev/Prod всегда фиксируйте версии:

```yaml
roles:
  - name: geerlingguy.postgresql
    version: "1.8.0" # Кавычки рекомендуются для версий-строк
```

### Сценарий 4: Интеграция с приватным репозиторием

Для крупных организаций — использование корпоративного Galaxy сервера (например, Automation Hub или Pulp):

```ini
# ansible.cfg
[galaxy]
server_list = my_company_galaxy

[galaxy_server.my_company_galaxy]
url = https://galaxy.mycompany.com/api/
token = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx # Рекомендуется использовать переменные окружения вместо записи в файл
```

---

## Дополнительная информация

### Пути установки и поиск

По умолчанию `ansible-galaxy` устанавливает контент в:

1. `~/.ansible/roles` (или `collections`) — пользовательская директория.
2. `/usr/share/ansible/roles` — системная директория.

**Приоритеты в `ansible.cfg`:**
Установка и поиск ролей зависят от параметра `roles_path`. Если в проекте есть локальная папка `roles`, добавьте её в конфиг:

```ini
[defaults]
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
```

### Тонкая настройка и кэширование

Для ускорения работы в CI/CD можно использовать кэширование коллекций:

```ini
# ansible.cfg
[galaxy]
cache_dir = ~/.ansible/galaxy_cache
token_with_client_auth = True
```

**Полезные переменные окружения:**
- `ANSIBLE_GALAXY_SERVER`: URL сервера Galaxy по умолчанию.
- `ANSIBLE_GALAXY_CACHE_DIR`: Путь к директории кэша.
- `ANSIBLE_GALAXY_TOKEN`: Токен для аутентификации (безопаснее, чем в файле).

### Сравнение с ручным управлением через Git

Альтернативный подход — использование модуля `ansible.builtin.git` для клонирования ролей напрямую в проект. Это полезно для быстрой правки внешних ролей. Подробнее: [git_management.md](git_management.md#сравнение-с-ansible-galaxy).

### Связанные документы

- [Структура роли](structure.md) — стандартная иерархия каталогов
- [Создание и использование ролей](usage.md) — практическое руководство
- [ansible_roles.md](../ansible_roles.md) — общие концепции ролей в Ansible
