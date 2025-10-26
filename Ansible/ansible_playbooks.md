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

---

## Отладка плейбуков

### Повышение уровня детализации (`-v`, `-vvv`)

Это первый и самый простой шаг. Флаги `-v` (verbose) увеличивают количество выводимой информации.

*   `-v`: Показывает базовый результат выполнения каждого таска.
*   `-vv`: Более подробно, полезно для просмотра значений переменных.
*   `-vvv`: Максимальная детализация. Показывает детали SSH-соединения, пути к временным файлам на удаленных хостах.
*   `-vvvv`: Включает логирование на уровне соединения (очень много вывода).

```bash
ansible-playbook my_playbook.yml -vvv
```

### Режим проверки (`--check`)

Запускает плейбук в режиме "сухого прогона" (dry run). Ansible покажет, какие изменения **были бы** внесены, но не будет выполнять их на самом деле.

```bash
ansible-playbook my_playbook.yml --check
```
**Ограничение:** Режим проверки не может предсказать сбои, которые зависят от реального выполнения предыдущих шагов.

### Модуль `debug`

Позволяет выводить значения переменных или кастомные сообщения прямо во время выполнения плейбука. Это основной инструмент для проверки состояния и значений.

```yaml
- name: Print variable value
  debug:
    var: my_variable

- name: Print custom message
  debug:
    msg: "The user is {{ user_name }} and home dir is {{ home_dir }}"
```

### Пошаговое выполнение (`--step`)

Запускает плейбук в интерактивном режиме. Перед выполнением каждого таска Ansible будет спрашивать вашего подтверждения (`y/n/c`). Это позволяет дойти до проблемного места и проанализировать ситуацию.

```bash
ansible-playbook my_playbook.yml --step
```

### Ограничение выполнения

*   `--limit <хост или группа>`: Запускает плейбук только на указанных хостах. Полезно для отладки проблемы на конкретной машине.
    ```bash
    ansible-playbook my_playbook.yml --limit webserver1.example.com
    ```
*   `--start-at-task <имя таска>`: Начинает выполнение плейбука с указанного таска. Экономит время, если проблема возникает в середине или конце большого плейбука.
    ```bash
    ansible-playbook my_playbook.yml --start-at-task "Install nginx"
    ```

### Модули `fail` и `assert`

*   **`fail`**: Принудительно останавливает выполнение плейбука с ошибкой, если определенное условие истинно.
    ```yaml
    - name: Stop if Java is not installed
      fail:
        msg: "Java is not installed, but it is required."
      when: java_version_result.stdout == ""
    ```
*   **`assert`**: Проверяет, что определенные условия (инварианты) выполняются. Если нет — плейбук падает с ошибкой.
    ```yaml
    - name: Assert that the service is running
      assert:
        that:
          - service_status.status == 'running'
        fail_msg: "Service is not running!"
        success_msg: "Service is running as expected."
    ```

---

## Обработка ошибок

### `ignore_errors: true`

Позволяет продолжить выполнение плея, даже если задача завершилась с ошибкой. Полезно для некритичных операций.

```yaml
- name: Удаление временного файла (не падать, если его нет)
  file:
    path: /tmp/temp_file.txt
    state: absent
  ignore_errors: true
```

### `block`, `rescue`, `always`

Это аналог конструкции `try...catch...finally` в программировании.

*   **`block`**: Основной блок задач. Если любая из них провалится, выполнение перейдет в блок `rescue`.
*   **`rescue`**: Блок задач, который выполняется **только если** в `block` произошла ошибка. Используется для восстановления или логирования.
*   **`always`**: Блок, который выполняется **всегда** в конце, независимо от того, была ли ошибка.

```yaml
- name: Попытка выполнить рискованную операцию с восстановлением
  block:
    - name: Попытка запуска экспериментального сервиса
      service:
        name: experimental-service
        state: started

  rescue:
    - name: Если запуск не удался, вывести сообщение
      debug:
        msg: "Сервис experimental-service не запустился. Продолжаем без него."

  always:
    - name: Эта задача выполняется всегда
      debug:
        msg: "Завершение блока рискованной операции."
```

### `failed_when`

Позволяет переопределить стандартные условия сбоя задачи. По умолчанию, ненулевой код возврата команды означает ошибку. `failed_when` позволяет вам определить сбой по содержимому вывода или другим условиям.

```yaml
- name: Проверить, что команда не вернула определенный текст
  command: /usr/bin/my_script.sh
  register: script_result
  # Провалить задачу, если в выводе есть слово 'ERROR'
  failed_when: "'ERROR' in script_result.stdout"
```

### `changed_when`

Позволяет переопределить, когда задача считается "измененной" (`changed`). Многие команды (`shell`, `command`) по умолчанию всегда сообщают об изменении. `changed_when: false` — частый способ сделать их идемпотентными в отчетах.

```yaml
- name: Проверить наличие файла (это действие не меняет систему)
  command: ls /path/to/file.conf
  register: file_check
  changed_when: false # Не помечать как 'changed'
```
