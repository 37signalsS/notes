### 3. Модули для управления службами (сервисами)

#### `ansible.builtin.systemd`

Более современный и предпочтительный модуль для систем, использующих `systemd`. Предоставляет дополнительные возможности, которых нет в `service`. Ключевое преимущество — опция `daemon_reload: yes`, которая выполняет команду `systemctl daemon-reload`. Это необходимо после создания или изменения `unit`-файлов сервисов, чтобы `systemd` узнал о них. Модуль `service` этого делать не умеет.

```yaml
- name: Reload systemd to apply new unit files
  ansible.builtin.systemd:
    daemon_reload: yes

- name: Restart service httpd, and sleep for 5 seconds
  ansible.builtin.systemd:
    name: httpd
    state: restarted
```

### 4. Модули для системной конфигурации

#### `ansible.builtin.timezone`

Управляет системным часовым поясом.

```yaml
- name: Set timezone to Europe/Moscow
  ansible.builtin.timezone:
    name: Europe/Moscow
```

#### `ansible.builtin.hostname`

Управляет именем хоста (hostname) системы.

```yaml
- name: Set hostname to 'webserver01'
  ansible.builtin.hostname:
    name: webserver01

- name: Set hostname based on inventory name
  ansible.builtin.hostname:
    name: "{{ inventory_hostname }}"
```
