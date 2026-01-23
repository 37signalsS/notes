# Ansible: Структура плейбуков

## Определения

**Плейбук (Playbook)**: YAML-файл, который содержит один или несколько "плеев" (`plays`) для описания желаемого состояния системы и шагов по его достижению. Это основной инструмент для оркестрации в Ansible.

**Плей (Play)**: Основной строительный блок плейбука. Плей сопоставляет группу хостов из инвентаря с набором задач, которые на них нужно выполнить.

**Задача (Task)**: Отдельная атомарная операция, выполняемая Ansible (например, установка пакета, копирование файла). Каждая задача вызывает определенный [модуль Ansible](../ansible_common_modules.md).

**Обработчик (Handler)**: Специальная задача, которая выполняется только один раз в конце плея и только после получения уведомления от другой задачи. Используется для таких действий, как перезапуск сервисов.

## Основные концепции

### Структура плея

Каждый плей в плейбуке — это словарь YAML.

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
```

#### Ключевые директивы плея

*   `name`: Описание плея, которое будет отображаться в логах.
*   `hosts`: Целевые хосты или группы из инвентаря.
*   `tasks`: Список задач, выполняемых последовательно.
*   `vars`: Словарь переменных, доступных в рамках плея.
*   `become: true/false`: Указывает, нужно ли повышать привилегии (через `sudo`).
*   `become_user`: Позволяет указать, каким пользователем стать после повышения привилегий (по умолчанию `root`).
    *   **Примечание:** Если `become: true` используется без указания `become_user`, то по умолчанию Ansible попытается стать пользователем `root`. То есть `become: true` эквивалентно `become: true` в сочетании с `become_user: root`.
*   `become_method`: Метод повышения привилегий (по умолчанию `sudo`).
*   `handlers`: Специальные задачи, выполняемые по уведомлению.
*   `roles`: Список [ролей](../ansible_roles.md) для включения в плей. Роли выполняются перед `tasks`.
    ```yaml
    - hosts: webservers
      become: true
      roles:
        - common
        - { role: nginx, nginx_port: 8080 }
    ```

### Переменные и Факты

#### Приоритет переменных

Порядок возрастания приоритета (где переменные могут быть переопределены):

1.  **Роли: `defaults/main.yml`**: Значения "по умолчанию", самый низкий приоритет.
2.  **Инвентарь: `group_vars/`**: Переменные для групп хостов.
3.  **Инвентарь: `host_vars/`**: Переменные для конкретного хоста.
4.  **Факты (ansible_facts)**: Переменные, собранные Ansible о системе.
5.  **Плейбук: `vars` и `vars_files`**: Переменные, определенные непосредственно в плее.
6.  **Роли: `vars/main.yml`**: "Константы" роли, имеют высокий приоритет.
7.  **Командная строка (`--extra-vars` или `-e`)**: Самый высокий приоритет.

#### Магические переменные (Magic Variables)

В Ansible существует категория **особых (special)** или **магических (magic)** переменных. Их ключевая особенность в том, что они **не могут быть заданы или переопределены пользователем**. Ansible всегда сам вычисляет и присваивает им значения в контексте выполнения плейбука.

Это зарезервированные имена, которые предоставляют доступ к важной внутренней информации о процессе выполнения, инвентаре и хостах.

**Ключевые магические переменные:**

*   `inventory_hostname`: Имя хоста, как оно указано в файле инвентаря. Особенно полезно, когда `ansible_host` (IP-адрес для подключения) отличается от инвентарного имени.
*   `hostvars`: Словарь, содержащий все переменные для всех хостов в инвентаре. Позволяет получить доступ к переменным другого хоста (`hostvars['other-server.example.com']['some_variable']`).
*   `group_names`: Список групп, к которым принадлежит текущий хост.
*   `groups`: Словарь, содержащий все группы инвентаря и список хостов в каждой из них.

**Практический пример: синхронизация имени хоста с инвентарем**

Задача: мы хотим, чтобы реальное имя сервера (hostname) соответствовало имени, которое мы задали ему в файле инвентаря.

**Инвентарь:**
```ini
[web]
srv-prod-1 ansible_host=192.168.1.10

[backup]
bckp-1 ansible_host=192.168.1.20
```

**Задача в роли `set_hostname`:**

Мы используем модуль `ansible.builtin.hostname` и передаем ему магическую переменную `inventory_hostname`.

```yaml
# roles/set_hostname/tasks/main.yml
- name: Set hostname based on inventory name
  ansible.builtin.hostname:
    name: "{{ inventory_hostname }}"
```

При выполнении этой задачи на хосте `192.168.1.10` его имя будет изменено на `srv-prod-1`. На хосте `192.168.1.20` — на `bckp-1`. Таким образом, магическая переменная позволяет легко получить доступ к метаданным инвентаря для каждого конкретного хоста.

#### Факты Ansible (Ansible Facts)

На старте каждого плея Ansible по умолчанию собирает информацию (факты) об управляемой системе: сетевые интерфейсы, ОС, память и т.д. Эти данные помещаются в переменную `ansible_facts` и чрезвычайно полезны для создания кроссплатформенных плейбуков.

```yaml
- name: Установка Apache на RedHat/CentOS
  ansible.builtin.yum:
    name: httpd
    state: present
  when: ansible_os_family == "RedHat" # Используем факт для условного выполнения
```

#### Лучшие практики ("Дзен Ansible")

1.  **Определяйте переменную в одном месте.** Избегайте многократного переопределения.
2.  **Используйте уникальные префиксы.** Чтобы избежать конфликтов имен между ролями, добавляйте префикс с названием роли (`my_app_nginx_port: 8080`).
3.  **Избегайте общих имен** (`user`, `port`, `server`).

### Практический пример: параметризация роли с помощью defaults и group_vars

Рассмотрим, как работает приоритет переменных на реальном примере. Предположим, мы создаем [роль](../ansible_roles.md) `swap` для управления файлом подкачки, и мы хотим, чтобы его размер был настраиваемым.

**1. Задача с переменной**

В файле `roles/swap/tasks/main.yml` мы используем переменную `swap_size` для указания размера файла.

```yaml
# roles/swap/tasks/main.yml
- name: Create swap file
  ansible.builtin.shell: "fallocate -l {{ swap_size }} /swapfile"
  args:
    creates: /swapfile
```

Если запустить плейбук сейчас, он завершится с ошибкой, так как переменная `swap_size` нигде не определена.

**2. Задание значения по умолчанию**

Чтобы сделать роль переиспользуемой, мы задаем значение по умолчанию в `roles/swap/defaults/main.yml`. Это значение будет использоваться, если переменная не переопределена где-либо еще.

```yaml
# roles/swap/defaults/main.yml
---
swap_size: 1g
```

Теперь роль будет работать и по умолчанию создавать swap-файл размером 1 ГБ.

**3. Переопределение для разных окружений через `group_vars`**

Предположим, у нас в инвентаре есть две группы серверов: `web` (продакшн) и `backup` (стейджинг), и мы хотим разные размеры swap-файла для них.

Мы создаем каталог `group_vars` рядом с нашим инвентарем или плейбуком:

```
├── group_vars/
│   ├── web.yml
│   └── backup.yml
├── inventory
└── playbook.yml
```

Теперь мы определяем переменную `swap_size` в каждом файле:

```yaml
# group_vars/web.yml
---
swap_size: 1g # Для продакшн-серверов
```

```yaml
# group_vars/backup.yml
---
swap_size: 2g # Для бэкап-серверов
```

**Результат:**

При запуске плейбука на группе `web`, Ansible будет использовать `swap_size: 1g`. При запуске на группе `backup`, он будет использовать `swap_size: 2g`.

Этот пример наглядно демонстрирует **приоритет переменных**: значение из `group_vars/` является более приоритетным, чем значение из `roles/defaults/main.yml`.

> **Лучшая практика:** Избегайте создания одного большого файла `group_vars/all.yml` для всех переменных. Гораздо лучше создавать отдельные файлы для каждой группы хостов. Это делает конфигурацию более чистой, управляемой и позволяет легко отслеживать, какие переменные к какой группе относятся.

### Использование фактов в условиях

В том же примере мы можем сделать задачу идемпотентной, проверяя факт о системе — наличие уже активного swap.

```yaml
# roles/swap/tasks/main.yml
- name: Enable swap
  ansible.builtin.shell: "swapon /swapfile"
  when: ansible_facts.swapfree_mb == 0 # Выполнить команду, только если свободный swap равен 0
```

### Управление ходом выполнения

#### Условные конструкции (when)

Директива `when` позволяет выполнять задачу только при выполнении определенного условия.

*   **Логическое "И" (AND):** Список условий. Задача выполнится, только если все условия истинны.

    ```yaml
    - name: "Перезагрузить сервис только если включено и были изменения"
      ansible.builtin.systemd:
        name: my_service
        state: reloaded
      when:
        - my_service_enabled
        - config_result is changed
    ```
*   **Логическое "ИЛИ" (OR):**
    ```yaml
    - name: "Выполнить, если система CentOS ИЛИ Ubuntu"
      ansible.builtin.debug:
        msg: "Это RedHat-based или Debian-based система."
      when: ansible_os_family == "RedHat" or ansible_os_family == "Debian"
    ```

#### Циклы (loop)

Циклы позволяют выполнять одну и ту же задачу несколько раз с разными данными.

*   **Простой список:**
    ```yaml
    - name: Создание нескольких пользователей
      ansible.builtin.user:
        name: "{{ item }}"
        state: present
      loop: [alice, bob]
    ```
*   **Список словарей:**
    ```yaml
    - name: Установка нескольких пакетов
      ansible.builtin.apt:
        name: "{{ item.name }}"
        state: "{{ item.state }}"
      loop:
        - { name: 'nginx', state: 'present' }
        - { name: 'htop', state: 'latest' }
    ```
> **Примечание:** В старых версиях использовалась конструкция `with_items`. `loop` является современным и более гибким стандартом.

#### Регистрация результатов (register)

Директива `register` сохраняет результат выполнения задачи в переменную. Это часто используется вместе с `when` для условного выполнения последующих задач.

```yaml
- name: "Сгенерировать конфигурационный файл"
  ansible.builtin.template:
    src: whitelist.j2
    dest: /etc/myapp/whitelist.conf
  register: whitelist_config # Создает переменную whitelist_config, которая будет содержать всю информацию о выполнении задачи

- name: "Перезагрузить сервис, только если конфиг изменился"
  ansible.builtin.service:
    name: myapp
    state: reloaded
  when: whitelist_config is changed # Проверяем статус 'changed' следующая задача выполнится только в том случае, если предыдущая задача (template) внесла изменения в файл и вернула статус changed
```

### Обработчики (handlers)

Обработчики — это специальные задачи, которые выполняются **только один раз** в конце плея и только по уведомлению от другой задачи (`notify`). Они идеальны для перезапуска сервисов, обеспечивая идемпотентность и эффективность.

```yaml
tasks:
  - name: Копирование конфигурации Nginx
    ansible.builtin.template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    notify: Restart Nginx # Отправка уведомления

handlers:
  - name: Restart Nginx # Только при получении это уведомления выполняеться следующее
    ansible.builtin.service:
      name: nginx
      state: restarted
```

### Обработка ошибок

*   `ignore_errors: true`: Продолжить выполнение, даже если задача завершилась сбоем.
*   `block, rescue, always`: Аналог `try...catch...finally` для обработки ошибок на уровне задач.
    ```yaml
    block:
      - name: Попытка запуска экспериментального сервиса
        # ...
    rescue:
      - name: Если запуск не удался, вывести сообщение
        # ...
    always:
      - name: Эта задача выполняется всегда
        # ...
    ```
*   `failed_when`: Позволяет переопределить условия, при которых задача считается проваленной.
    ```yaml
    - name: Проверить вывод скрипта
      command: /usr/bin/my_script.sh
      register: script_result
      failed_when: "'ERROR' in script_result.stdout"
    ```
*   `changed_when`: Позволяет переопределить условия, когда задача считается "измененной". `changed_when: false` часто используется, чтобы сделать команды идемпотентными в отчетах.

## Практические сценарии и продвинутое использование

### Структурирование плейбуков

*   `import_tasks` (статическое включение): Содержимое файла вставляется в плейбук на этапе парсинга (до начала выполнения). **Не работает с `loop` и `when`**. Используется для простой декомпозиции плейбуков.
*   `include_tasks` (динамическое включение): Файл подключается в процессе выполнения. **Работает с `loop` и `when`**. Используется для динамического выбора задач в зависимости от условий.

```yaml
- name: Включить задачи для Debian-подобных систем
  ansible.builtin.include_tasks: debian.yml
  when: ansible_os_family == "Debian"
```

### Выполнение задач на других хостах (delegate_to)

Позволяет выполнить задачу на другой машине (чаще всего `localhost`), а не на целевом хосте.

```yaml
- name: Find .war files on the control node
  ansible.builtin.find:
    paths: /path/to/local/artifacts
    patterns: "*.war"
  delegate_to: localhost # Выполнить эту задачу на машине, где запущен ansible
  register: found_artifacts
```

### Порядок выполнения: pre_tasks и post_tasks

*   `pre_tasks`: Блок задач, выполняемый **до** всех ролей. Полезен для предварительных проверок.
*   `post_tasks`: Блок задач, выполняемый **после** всех ролей и их обработчиков. Идеален для финальных действий, например, перезагрузки сервера.

```yaml
post_tasks:
  - name: Restart server after kernel upgrade
    ansible.builtin.shell: "sleep 10 && shutdown -r now"
    async: 1
    poll: 0
    when: kernel_updated is defined and kernel_updated
```

### Оптимизация и параллелизм

*   `forks`: Количество одновременных процессов. Увеличивает скорость выполнения. Задается в `ansible.cfg` или через `--forks`. Значение по умолчанию — 5.
*   `async` и `poll`: Позволяют выполнять длительные задачи в фоновом режиме. `poll: 0` означает "запустить и забыть".
*   `throttle`: Ограничивает количество хостов, на которых одновременно выполняется одна конкретная задача.
*   `until`: Позволяет выполнять задачу в цикле до тех пор, пока не будет выполнено условие.

    ```yaml
    - name: Wait for service to be ready
      ansible.builtin.uri:
        url: http://localhost:8080/health
        status_code: 200
      register: health_check_result
      until: health_check_result.status == 200
      retries: 10 # Количество попыток
      delay: 5    # Пауза в секундах между попытками
    ```

### Отладка плейбуков

*   `-v, -vvv`: Увеличение уровня детализации вывода.
*   `--syntax-check`: Проверка синтаксиса YAML.
*   `--check`: "Сухой прогон" (dry run) без внесения реальных изменений.
*   `debug`: Модуль для вывода значений переменных или сообщений.
*   `--step`: Интерактивное пошаговое выполнение.
*   `debugger`: Ключевое слово для вызова интерактивного отладчика на конкретной задаче при определенных условиях (`on_failed`, `always` и т.д.).
*   `--limit`: Ограничение выполнения на конкретном хосте.
*   `--start-at-task`: Начало выполнения с указанной задачи.

### Примеры

#### Управление контейнерами Docker через systemd

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
ExecStart=/usr/bin/docker run --rm --name {{ item.name }} \
{% if item.ports is defined %}
    {% for port in item.ports %} -p {{ port }} \ {% endfor %}
{% endif %}
    {{ item.image }}
ExecStop=/usr/bin/docker stop {{ item.name }}

[Install] WantedBy=multi-user.target
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

#### Управление Python-приложением (Gunicorn) через systemd

**Шаблон `gunicorn.service.j2`:**
```j2
[Unit]
Description=Gunicorn instance to serve {{ app_name }}
After=network.target

[Service]
User={{ service_user }}
Group={{ service_group }}
WorkingDirectory={{ app_path }}
ExecStart={{ app_path }}/venv/bin/gunicorn --workers 3 --bind unix:{{ app_path }}/{{ app_name }}.sock -m 007 wsgi:app
```

## Дополнительная информация

### Теги (Tags)

Теги позволяют выборочно запускать или пропускать части плейбука.

```yaml
tasks:
  - name: Install base packages
    ansible.builtin.apt:
      name: htop
    tags: [packages]

  - name: Configure nginx
    ansible.builtin.template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    tags: [configuration]
```
**Запуск:**
```bash
# Запустить только задачи с тегом 'configuration'
ansible-playbook my_playbook.yml --tags configuration

# Запустить все, КРОМЕ задач с тегом 'deploy'
ansible-playbook my_playbook.yml --skip-tags deploy
```
*   `always`: Задача выполняется всегда (кроме случаев явного пропуска через `--skip-tags`).
*   `never`: Задача не выполняется, если не указать ее тег явно (`--tags never`).
