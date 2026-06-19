# Паттерн "Utility Role"

## Определения

**Паттерн "Utility Role"** — подход к организации [ролей Ansible](../ansible_roles.md), при котором создается служебная роль, не предназначенная для прямого применения на хостах. Её цель — быть центральной библиотекой общих компонентов (задач и обработчиков) для переиспользования в других ролях. Решает проблему дублирования кода.

## Основные концепции

Ключевая идея — вынос повторяющегося кода в одно место. Вместо определения одинаковых задач и обработчиков в нескольких ролях (`nginx`, `mysql`), они создаются один раз в служебной роли (например, `common_components`), затем импортируются из других ролей.

Для включения компонентов используются модули `import_tasks` и `include_tasks`. Подробное описание различий между статическим (`import`) и динамическим (`include`) включением, а также рекомендации по их выбору находятся в [продвинутых возможностях плейбуков](../PlaybookStructure/advanced.md).

## Практические сценарии

### 1. Централизация обработчиков (Handlers)

Все общие обработчики (`restart nginx`, `reload systemd` и т.д.) помещаются в `common_components/handlers/main.yml`.

**`roles/common_components/handlers/main.yml`:**

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

Другие роли, например `nginx`, импортируют их для использования.

**`roles/nginx/handlers/main.yml`:**

```yaml
---
- name: Import common handlers
  ansible.builtin.import_tasks: ../../common_components/handlers/main.yml
```

Теперь `notify: restart firewalld` из любой роли будет вызывать централизованный обработчик.

### 2. Централизация общих задач (Tasks)

Повторяющиеся задачи, такие как настройка репозиториев, выносятся в `common_components/tasks/`.

**`roles/common_components/tasks/setup_repos.yml`:**

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

Затем они динамически включаются в нужных ролях.

**`roles/nginx/tasks/main.yml`:**

```yaml
# roles/nginx/tasks/main.yml
- name: Setup common repositories
  ansible.builtin.include_tasks: ../../common_components/tasks/setup_repos.yml

# ... остальные задачи для Nginx
```

### 3. Роль для инициализации переменных

Еще один вариант — создать роль, которая выполняется первой и задает глобальные переменные для всех последующих ролей.

**`roles/init_variables/tasks/main.yml`:**

```yaml
- name: Set distribution-specific variables
  ansible.builtin.set_fact:
    package_manager: "{{ 'apt' if ansible_facts['os_family'] == 'Debian' else 'yum' }}"
    # ... другие переменные
```

## Дополнительная информация

См. также [основы ролей](../ansible_roles.md), [кроссплатформенные плейбуки](../CrossPlatform/concepts.md), [антипаттерны](../ansible_bad_practices.md).
