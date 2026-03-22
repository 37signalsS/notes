# Ansible: Практические примеры структуры плейбуков

## Определения

**Практические примеры структуры плейбуков** — это конкретные сценарии использования Ansible, демонстрирующие различные подходы к организации и написанию плейбуков и ролей.

## Основные концепции

- **Параметризация ролей**: Использование переменных `defaults` и `group_vars` для настройки ролей без изменения их кода.
- **Управление контейнерами**: Использование шаблонов systemd для управления Docker-контейнерами.
- **Переиспользование кода**: Вынос повторяющихся задач в отдельные файлы и роли.

## 1. Параметризация роли (defaults и group_vars)

Пример демонстрирует, как сделать размер swap-файла настраиваемым.

1. **Задача с переменной** (`roles/swap/tasks/main.yml`):

    ```yaml
    - name: Create swap file
      ansible.builtin.shell: "fallocate -l {{ swap_size }} /swapfile"
      args:
        creates: /swapfile
    ```

2. **Значение по умолчанию** (`roles/swap/defaults/main.yml`):

    ```yaml
    swap_size: 1g
    ```

3. **Переопределение для группы** (`group_vars/backup.yml`):

    ```yaml
    swap_size: 2g # Для бэкап-серверов
    ```

**Результат**: Приоритет `group_vars` выше, чем у `defaults`, поэтому для хостов из группы `backup` будет использовано значение `2g`.

## 2. Управление контейнерами Docker через systemd

**Шаблон `container.service.j2`:**

```j2
[Unit]
Description={{ item.name }} container
Requires=docker.service
After=docker.service
[Service]
Restart=always
ExecStartPre=-/usr/bin/docker stop {{ item.name }}
ExecStartPre=-/usr/bin/docker rm {{ item.name }}
ExecStart=/usr/bin/docker run --rm --name {{ item.name }} 
{% if item.ports is defined %}{% for port in item.ports %} -p {{ port }} \ {% endfor %}{% endif %}
    {{ item.image }}
ExecStop=/usr/bin/docker stop {{ item.name }}
[Install]
WantedBy=multi-user.target
```

**Задача Ansible:**

```yaml
- name: Create systemd unit files for containers
  ansible.builtin.template:
    src: container.service.j2
    dest: "/etc/systemd/system/{{ item.name }}.service"
  loop: "{{ containers }}"
  notify: Reload systemd
```

## Дополнительная информация

Основы структуры плейбуков и компоненты описаны в [basics.md](basics.md). Подробнее о структуре и компонентах ролей — в [ansible_roles.md](../ansible_roles.md). Создание динамических конфигураций с Jinja2 — в [ansible_jinja2_templating.md](../ansible_jinja2_templating.md).

Полная информация о приоритетах переменных (`defaults` vs `group_vars`) — в [PlaybookStructure/variables.md](variables.md). Управление переменными в ролях — в [Roles/structure.md](../Roles/structure.md). Более полный пример управления Docker с использованием специализированных модулей — в [examples/example_docker_management.md](../examples/example_docker_management.md).
