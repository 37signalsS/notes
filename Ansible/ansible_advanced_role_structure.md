# Ansible: Продвинутые паттерны структуры ролей

## Проблема: Дублирование обработчиков и задач

**Сценарий:**
-   Роль `nginx` меняет конфигурацию и вызывает `notify: restart firewall`.
-   Роль `mysql` открывает порт и тоже вызывает `notify: restart firewall`.

В стандартном подходе вам пришлось бы определить обработчик `restart firewall` в обеих ролях, что приводит к дублированию кода.

## Решение: Централизованная "служебная" роль

Паттерн заключается в создании специальной, "ненастоящей" (fake) [роли Ansible](ansible_roles.md), которая сама по себе не применяется к хостам, а служит библиотекой общих компонентов для других ролей. Назовем ее условно `common_components`.

**Структура проекта:**
```
roles/
├── common_components/
│   ├── tasks/
│   │   ├── main.yml      # Пустой или не используется напрямую
│   │   └── setup_repos.yml
│   └── handlers/
│       └── main.yml      # Содержит ВСЕ общие обработчики
├── nginx/
│   ├── tasks/
│   │   └── main.yml
│   └── handlers/
│       └── main.yml      # Делегирует вызов в common_components
└── mysql/
    ├── tasks/
    │   └── main.yml
    └── handlers/
        └── main.yml      # Делегирует вызов в common_components
```

### 1. Централизация обработчиков (`handlers`)

Все общие обработчики, которые могут понадобиться в нескольких ролях, определяются в одном месте.

**Пример `roles/common_components/handlers/main.yml`:**
```yaml
---
- name: restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted

- name: restart firewalld
  ansible.builtin.service:
    name: firewalld
    state: restarted

- name: reload systemd
  ansible.builtin.systemd:
    daemon_reload: yes
```

### 2. Делегирование вызова с помощью `import_tasks`

Теперь каждая роль, которой нужен один из этих обработчиков, не определяет его заново, а просто "импортирует" общий файл.

**Пример `roles/nginx/handlers/main.yml`:**
```yaml
---
- name: Import common handlers
  ansible.builtin.import_tasks: ../../common_components/handlers/main.yml
```
Когда задача в роли `nginx` вызовет `notify: restart firewall`, Ansible найдет этот обработчик в импортированном файле и выполнит его. То же самое произойдет и в роли `mysql`.

**Преимущества:**
-   Все обработчики находятся в одном месте.
-   Нет дублирования кода.
-   Управление всеми сервисами унифицировано.

### 3. Централизация общих задач (`tasks`)

Тот же подход применим и к задачам. Если у вас есть набор шагов, который повторяется в начале многих ролей (например, установка общих репозиториев), его можно вынести в отдельный файл в служебной роли.

**Пример `roles/common_components/tasks/setup_repos.yml`:**
```yaml
---
- name: Add EPEL repository
  ansible.builtin.yum_repository:
    name: epel
    # ...

- name: Add custom company repository
  ansible.builtin.yum_repository:
    name: company-repo
    # ...
```

Затем в `tasks/main.yml` любой другой роли вы можете включить этот файл:
```yaml
# roles/nginx/tasks/main.yml
- name: Setup common repositories
  ansible.builtin.include_tasks: ../../common_components/tasks/setup_repos.yml

# ... остальные задачи для Nginx
```

### 4. Роль для инициализации переменных

Иногда полезно иметь роль, которая выполняется самой первой в [плейбуке](ansible_playbook_structure.md) и ничего не делает, кроме как устанавливает набор глобальных переменных, используемых всеми последующими ролями.

**Пример `roles/init_variables/tasks/main.yml`:**
```yaml
- name: Set distribution-specific variables
  ansible.builtin.set_fact:
    package_manager: "{{ 'apt' if ansible_os_family == 'Debian' else 'yum' }}"
    # ... другие переменные
```
Такая роль выполняется безусловно в начале плейбука для подготовки окружения.
