# Управление ролями с Ansible Galaxy

## Определения

**Ansible Galaxy** — официальный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита CLI (Command Line Interface — интерфейс командной строки) для поиска, обмена и управления контентом Ansible (роли, коллекции).

**Коллекция (Collection)** — структура, содержащая роли, модули, плагины и документацию для работы с экосистемой (например, `community.postgresql`).

**Роль (Role)** — базовая единица переиспользования: предопределенная структура файлов для автоматизации компонента системы. Подробнее: [ansible_roles.md](../ansible_roles.md).

---

## Основные концепции

### Команды управления

**Создание каркаса роли:**

```bash
ansible-galaxy role init my_new_role  # → роль успешно инициализирована
```

**Установка ролей и коллекций:**

```bash
# Установить роль
ansible-galaxy role install geerlingguy.postgresql  # → роль установлена в ~/.ansible/roles

# Установить коллекцию
ansible-galaxy collection install community.postgresql  # → коллекция установлена в ~/.ansible/collections
```

**Просмотр установленных компонентов:**

```bash
ansible-galaxy role list  # → список установленных ролей
ansible-galaxy collection list  # → список установленных коллекций
```

### Управление зависимостями через `requirements.yml`

Лучшая практика — определять все внешние роли и коллекции в файле `requirements.yml`.

**Пример `requirements.yml`:**

```yaml
roles:
  # 1. Установка роли из Ansible Galaxy
  - name: geerlingguy.postgresql
    version: 1.8.0 # Можно указать версию

  # 2. Установка роли из Git-репозитория
  - src: https://github.com/geerlingguy/ansible-role-nginx.git
    scm: git  # SCM (Source Control Management — управление версиями исходного кода)
    name: nginx # Имя, которое будет у роли локально

collections:
  # 3. Установка коллекции из Ansible Galaxy
  - name: community.postgresql
    version: 2.3.0

  # 4. Установка коллекции из Git-репозитория
  - name: https://github.com/ansible-collections/community.docker.git
    type: git
    version: main # Ветка, тег или коммит
```

**Установка зависимостей из файла:**

```bash
# Установить роли
ansible-galaxy role install -r requirements.yml  # → установка ролей по списку

# Установить коллекции
ansible-galaxy collection install -r requirements.yml  # → установка коллекций по списку
```

---

## Практические сценарии

### Сценарий 1: Быстрое развертывание с готовыми ролями

```bash
# Установка роли PostgreSQL от сообщества
ansible-galaxy role install geerlingguy.postgresql  # → роль установлена
```

### Сценарий 2: Версионирование зависимостей

Для воспроизводимости сборок фиксируйте версии в `requirements.yml`:

```yaml
roles:
  - name: geerlingguy.postgresql
    version: 1.8.0

collections:
  - name: community.postgresql
    version: 2.3.0
```

### Сценарий 3: Интеграция с приватным репозиторием

Для крупных организаций — развертывание приватного сервера Galaxy:

```ini
# ansible.cfg
[galaxy]
server_list = my_company_galaxy

[galaxy_server.my_company_galaxy]
url = https://galaxy.mycompany.com/
```

---

## Дополнительная информация

### Пути установки

По умолчанию `ansible-galaxy` устанавливает контент в:

- `~/.ansible/` — пользовательская директория
- Системные директории — при установке с правами root

Пути можно переопределить в `ansible.cfg`.

### Сравнение с ручным управлением через Git

Альтернативный подход — использование модуля `ansible.builtin.git` для клонирования ролей. См. [git_management.md](git_management.md#сравнение-с-ansible-galaxy).

### Связанные документы

- [Структура роли](structure.md) — стандартная структура каталогов роли
- [Создание и использование ролей](usage.md) — практическое руководство
- [Стратегии и паттерны](strategies.md) — рекомендации по проектированию ролей
