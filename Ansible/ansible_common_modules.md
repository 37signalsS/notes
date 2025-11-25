# Ansible: Обзор часто используемых модулей

Ansible имеет огромное количество модулей для решения самых разных задач. Однако в 95% случаев для повседневной автоматизации используется небольшой набор ключевых модулей.

---

### 1. Модули для управления пакетами

#### `ansible.builtin.yum_repository`
Управляет YUM-репозиториями в системах на базе Red Hat (CentOS, Fedora).

```yaml
- name: Add EPEL Repository
  ansible.builtin.yum_repository:
    name: epel
    description: EPEL YUM repo
    baseurl: https://download.fedoraproject.org/pub/epel/$releasever/$basearch/
```

#### `ansible.builtin.yum`
Управляет пакетами (установка, обновление, удаление) с помощью менеджера пакетов YUM.

```yaml
- name: Install the latest version of Apache
  ansible.builtin.yum:
    name: httpd
    state: latest
```

#### `ansible.builtin.apt`
Аналог `yum` для систем на базе Debian/Ubuntu.

```yaml
- name: Install the latest version of Nginx
  ansible.builtin.apt:
    name: nginx
    state: latest
    update_cache: yes
```

---

### 2. Модули для управления файлами

#### `ansible.builtin.file`
Управляет файлами, символическими ссылками и каталогами.

```yaml
- name: Create a directory if it does not exist
  ansible.builtin.file:
    path: /etc/some_directory
    state: directory
    mode: '0755'

- name: Remove a file
  ansible.builtin.file:
    path: /etc/foo.conf
    state: absent
```

#### `ansible.builtin.template`
Создает файл на целевом хосте на основе [шаблона Jinja2](../ansible_jinja2_templating.md). Это основной способ управления конфигурационными файлами.

```yaml
- name: Create a configuration file from a template
  ansible.builtin.template:
    src: templates/httpd.conf.j2
    dest: /etc/httpd/conf/httpd.conf
```
Модуль обрабатывает переменные и логику в `.j2` файле и создает на сервере статический `.conf` файл.

---

### 3. Модули для управления службами (сервисами)

#### `ansible.builtin.service`
Основной модуль для управления службами в системах с `SysV-init` или `systemd`.

```yaml
- name: Start and enable httpd service
  ansible.builtin.service:
    name: httpd
    state: started
    enabled: yes
```

#### `ansible.builtin.systemd`
Более современный и предпочтительный модуль для систем, использующих `systemd`. Предоставляет дополнительные возможности, которых нет в `service`.

```yaml
- name: Reload systemd to apply new unit files
  ansible.builtin.systemd:
    daemon_reload: yes

- name: Restart service httpd, and sleep for 5 seconds
  ansible.builtin.systemd:
    name: httpd
    state: restarted
```
Ключевое преимущество — опция `daemon_reload: yes`, которая выполняет команду `systemctl daemon-reload`. Это необходимо после создания или изменения `unit`-файлов сервисов, чтобы `systemd` узнал о них. Модуль `service` этого делать не умеет.

---
См. также:
*   [Ansible: Плейбуки](ansible_playbooks.md)
*   [Шаблонизация Jinja2](ansible_jinja2_templating.md)
