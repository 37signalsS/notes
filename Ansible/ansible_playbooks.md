# Ansible: Плейбуки (Playbooks)

Плейбуки являются ядром Ansible и представляют собой YAML-файлы, которые декларативно описывают желаемое состояние системы. Они позволяют оркестрировать сложную последовательность задач на управляемых узлах.

См. также: [Обзор Ansible](ansible_overview.md)

## Структура плейбука

Плейбук — это список одного или нескольких "плеев" (plays). Каждый плей определяет набор задач для выполнения на определенной группе хостов.

```yaml
---
- name: Play 1 - Настройка веб-серверов
  hosts: webservers
  become: true
  vars:
    http_port: 80
  tasks:
    - name: Установка Nginx
      apt:
        name: nginx
        state: present
  handlers:
    - name: Перезапуск Nginx
      service:
        name: nginx
        state: restarted

- name: Play 2 - Настройка баз данных
  hosts: db_servers
  become: true
  tasks:
    # ... задачи для баз данных
```

## Ключевые директивы

*   `hosts`: Определяет целевые хосты или группы из файла инвентаризации.
*   `tasks`: Список задач, которые выполняются последовательно.
*   `vars`: Словарь переменных, доступных в рамках плея.
*   `become: true/false`: Указывает, нужно ли повышать привилегии (например, через `sudo`).
*   `handlers`: Специальные задачи, которые выполняются только по уведомлению от других задач (через директиву `notify`).
*   `roles`: Список ролей для включения в плей.

## Переменные (Variables)

Переменные позволяют делать плейбуки гибкими и переиспользуемыми.

*   **Определение в плейбуке:**
    ```yaml
    vars:
      package_name: nginx
    ```
*   **Использование в задачах:**
    ```yaml
    - name: Установка пакета
      apt:
        name: "{{ package_name }}"
        state: present
    ```

## Условные конструкции (`when`)

Директива `when` позволяет выполнять задачу только при выполнении определенного условия.

```yaml
- name: Установка Apache на Debian/Ubuntu
  apt:
    name: apache2
    state: present
  when: ansible_os_family == "Debian"

- name: Установка Apache на RedHat/CentOS
  yum:
    name: httpd
    state: present
  when: ansible_os_family == "RedHat"
```

## Циклы (`loop`)

Циклы позволяют выполнять одну и ту же задачу несколько раз с разными данными.

*   **Простой список:**
    ```yaml
    - name: Создание нескольких пользователей
      user:
        name: "{{ item }}"
        state: present
      loop:
        - alice
        - bob
        - carol
    ```

*   **Список словарей:**
    ```yaml
    - name: Установка нескольких пакетов
      apt:
        name: "{{ item.name }}"
        state: "{{ item.state }}"
      loop:
        - { name: 'nginx', state: 'present' }
        - { name: 'htop', state: 'present' }
        - { name: 'vim', state: 'latest' }
    ```

## Обработчики (`handlers`)

Обработчики — это задачи, которые запускаются только один раз в конце плея, если на них было отправлено уведомление. Они идеально подходят для перезапуска служб.

```yaml
tasks:
  - name: Копирование конфигурации Nginx
    template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    notify: Restart Nginx # Отправка уведомления

handlers:
  - name: Restart Nginx
    service:
      name: nginx
      state: restarted
```
