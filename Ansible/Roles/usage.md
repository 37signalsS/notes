# Создание и использование ролей Ansible

## Определения

**Создание роли** — процесс разработки новой роли Ansible: от инициализации структуры каталогов до наполнения задачами, переменными и шаблонами.

**Использование роли** — применение роли в плейбуке через директиву `roles:` для автоматизации настройки целевых хостов.

## Основные концепции

### Создание каркаса роли

Утилита `ansible-galaxy` автоматически создает полную структуру директорий для новой роли:

```bash
# Создает директорию my_new_role со всеми стандартными каталогами
ansible-galaxy role init my_new_role  # → роль успешно инициализирована
```

Подробнее о структуре каталогов — в [structure.md](structure.md).

### Наполнение роли логикой

Основная работа происходит в файле `tasks/main.yml` — точке входа роли.

**Пример: роль `set_time`**

1. **Создаем роль:**

    ```bash
    ansible-galaxy role init set_time
    ```

2. **Добавляем задачу в `roles/set_time/tasks/main.yml`:**

    ```yaml
    ---
    # tasks file for set_time
    - name: Set timezone to Europe/Moscow
      ansible.builtin.timezone:
        name: Europe/Moscow
    ```

    > **Важно:** Не удаляйте `---` в начале файла — это маркер начала YAML (YAML Ain't Markup Language) документа.

3. **Добавляем переменные по умолчанию в `defaults/main.yml`:**

    ```yaml
    ---
    timezone: Europe/Moscow
    ```

4. **Модифицируем задачу для использования переменной:**

    ```yaml
    - name: Set timezone
      ansible.builtin.timezone:
        name: "{{ timezone }}"
    ```

### Подключение роли в плейбуке

Роли применяются к хостам с помощью ключевого слова `roles` в плейбуке. Ansible автоматически ищет роли в директории `roles/` рядом с плейбуком.

**Базовый пример:**

```yaml
---
- name: Configure servers
  hosts: webservers
  become: true
  roles:
    - set_time
```

## Практические сценарии

### Сценарий 1: Простое подключение роли

```yaml
- name: Apply common role
  hosts: all
  roles:
    - common
```

### Сценарий 2: Подключение роли с параметрами

Передача переменных в роль для настройки:

```yaml
- name: Configure Nginx with custom settings
  hosts: webservers
  roles:
    - role: nginx
      nginx_port: 8080
      nginx_worker_processes: 8
```

### Сценарий 3: Подключение с тегами

Использование тегов для выборочного выполнения:

```yaml
- name: Deploy application stack
  hosts: webservers
  roles:
    - role: my_app.memcached
      port: 11211
      tags: ["cache", "memcached"]
    
    - role: my_app.redis
      port: 6379
      tags: ["cache", "redis"]
```

Запуск только кэширования:

```bash
ansible-playbook deploy.yml --tags "cache"  # → выполнение задач с тегом cache
```

### Сценарий 4: Условное подключение роли

Использование `when:` для применения роли к определенным хостам:

```yaml
- name: Deploy database
  hosts: all
  roles:
    - role: postgresql
      when: db_type == "postgresql"
    
    - role: mysql
      when: db_type == "mysql"
```

### Сценарий 5: Подключение внешней роли из Galaxy

```yaml
- name: Setup web server
  hosts: webservers
  roles:
    - geerlingguy.nginx       # Роль из Ansible Galaxy
    - geerlingguy.php         # Ещё одна внешняя роль
```

Предварительная установка:

```bash
ansible-galaxy role install geerlingguy.nginx geerlingguy.php  # → роли установлены в ~/.ansible/roles
```

Подробнее — в [galaxy.md](galaxy.md).

### Сценарий 6: Полная параметризация через group_vars

**Структура проекта:**

```
project/
├── group_vars/
│   └── webservers.yml
├── roles/
│   └── nginx/
└── playbook.yml
```

**`group_vars/webservers.yml`:**

```yaml
nginx_port: 80
nginx_worker_processes: auto
nginx_server_name: example.com
```

**`playbook.yml`:**

```yaml
- name: Configure webservers
  hosts: webservers
  roles:
    - nginx
```

Роль автоматически получит переменные из `group_vars`.

---

## Дополнительная информация

### Приоритет переменных при использовании ролей

Переменные, переданные роли напрямую в плейбуке, имеют более высокий приоритет, чем значения из `defaults/main.yml` роли.

```yaml
roles:
  - role: nginx
    nginx_port: 8080  # Переопределит значение из defaults
```

Полная иерархия приоритетов — в [PlaybookStructure/variables.md](../PlaybookStructure/variables.md).

### Распространенные ошибки

1. **Отсутствие `---` в начале файлов задач** — может привести к ошибкам парсинга YAML
2. **Неправильный путь к роли** — Ansible ищет роли в `roles/` относительно плейбука или в путях из `ansible.cfg`
3. **Жестко заданные значения в задачах** — используйте переменные из `defaults/main.yml`

### Связанные документы

- [Структура роли](structure.md) — стандартная структура каталогов
- [Компоненты роли](../ansible_roles.md) — базовые концепции и определения
- [Стратегии и паттерны](strategies.md) — рекомендации по проектированию ролей
