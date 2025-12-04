# Ansible: Плейбуки (Playbooks)

Плейбуки являются ядром Ansible и представляют собой YAML-файлы, которые декларативно описывают желаемое состояние системы. Они позволяют оркестрировать сложную последовательность задач на управляемых узлах.

См. также:
*   [Обзор Ansible](ansible_overview.md)
*   [Кроссплатформенные плейбуки Ansible](cross_platform_playbooks.md)
*   [Пример: Развертывание Python-приложения](ansible_python_app_deployment_example.md)

---

## Выполнение плейбуков

В реальных сценариях автоматизации используется не выполнение отдельных команд, а **плейбуки** (playbooks). Сами серверы, на которых нужно выполнять задачи, определяются в файле **инвентаризации** (inventory).

### 1. Запуск плейбука

Для запуска плейбука используется команда `ansible-playbook`.

```bash
ansible-playbook -i inventory.ini --ask-pass playbook.yml
```
**Ключи команды:**
*   `ansible-playbook`: Команда для запуска выполнения плейбука.
*   `-i inventory.ini`: Указывает путь к файлу инвентаризации.
*   `--ask-pass` (или `-k`): Запрашивает пароль для SSH-подключения.
*   `playbook.yml`: Путь к файлу плейбука.


### 2. Анализ вывода выполнения

При запуске плейбука Ansible предоставляет подробный вывод:

**PLAY**
```
PLAY [Install and start nginx] ********************************************
```
Обозначает начало выполнения "плея" (play).

**TASK**
```
TASK [Gathering Facts] ******************************************************
ok: [ws01]

TASK [install nginx] *******************************************************
changed: [ws01]
```
*   `Gathering Facts`: Первая задача по умолчанию для сбора информации (фактов) о системе.
*   `changed`: Означает, что задача внесла изменения в систему (например, установила пакет).
*   `ok`: Означает, что система уже находилась в нужном состоянии, и изменений не потребовалось.

**PLAY RECAP**
```
PLAY RECAP *****************************************************************
ws01                       : ok=5    changed=4    unreachable=0    failed=0
```
Итоговая сводка по всем хостам. `failed > 0` означает, что плейбук не был выполнен успешно.

### 3. Ключевые опции командной строки

Команда `ansible-playbook` имеет множество ключей для гибкого управления.

*   `--inventory` ( `-i`): Указывает путь к файлу инвентаризации.
    ```bash
    ansible-playbook -i /path/to/inventory.ini playbook.yml
    ```
*   `--limit`: Ограничивает выполнение плейбука только указанными хостами или группами.
    ```bash
    # Выполнить только на хосте web1
    ansible-playbook -i inventory.ini --limit web1 playbook.yml
    ```
*   `--diff`: Показывает изменения в файлах в стиле Git `diff`, что полезно для контроля.
*   `--step`: Включает пошаговое выполнение. Перед каждой задачей Ansible будет спрашивать подтверждение (`y`/`n`/`c`).
*   `--force-handlers`: Заставляет выполнять обработчики (`handlers`) даже если плейбук завершился с ошибкой. Рекомендуется для CI/CD.
*   `--become`: Указывает на необходимость повышения привилегий (`sudo`).
*   `--ask-pass` (`-k`): Запрашивает пароль для SSH-подключения.
*   `--ask-become-pass` (`-K`): Запрашивает пароль для повышения привилегий (`sudo`).

---

## Структура плейбука

Плейбук — это список одного или нескольких "плеев" (plays). Каждый плей определяет набор задач для выполнения на определенной группе хостов из файла инвентаризации.

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

### Ключевые директивы

*   `hosts`: Целевые хосты или группы из инвентаря.
*   `tasks`: Список задач, выполняемых последовательно.
*   `vars`: Словарь переменных, доступных в рамках плея.
*   `become: true/false`: Указывает, нужно ли повышать привилегии (через `sudo`).
*   `handlers`: Специальные задачи, выполняемые по уведомлению от других задач (через `notify`).
*   `roles`: Список ролей для включения в плей.

## Переменные и Факты

### Где определять переменные и их приоритет

Переменные в Ansible могут быть определены во множестве мест. Понимание иерархии их приоритетов критически важно. Чем выше уровень в списке, тем выше приоритет — значение переменной на более высоком уровне "перезаписывает" значение с более низкого.

Порядок возрастания приоритета:
1.  **Роли: `defaults/main.yml`**: Значения "по умолчанию", самый низкий приоритет.
2.  **Инвентарь: `group_vars/`**: Переменные для групп хостов.
3.  **Инвентарь: `host_vars/`**: Переменные для конкретного хоста.
4.  **Факты (ansible_facts)**: Переменные, собранные Ansible о системе.
5.  **Плейбук: `vars` и `vars_files`**: Переменные, определенные непосредственно в плее.
6.  **Роли: `vars/main.yml`**: "Константы" роли, имеют высокий приоритет.
7.  **Командная строка (`--extra-vars` или `-e`)**: Самый высокий приоритет.

### Практические примеры определения и переопределения

**1. Определение в инвентаре (`hosts.ini`)**

```ini
# Переменные для всех хостов
[all:vars]
test_var=value_for_all

[centos]
192.168.51.3 test_var_host="host_specific" # для конкретного хоста

[centos:vars]
test_var_group="group_specific" # для группы
```

**2. Переопределение через командную строку (высший приоритет)**

```bash
ansible-playbook playbook.yml -e "test_var=overridden_from_cli"
```

### Факты Ansible (Ansible Facts)

На старте каждого плея Ansible по умолчанию выполняет задачу `Gathering Facts`, собирая огромное количество информации (фактов) об управляемой системе: сетевые интерфейсы, ОС, память и т.д.

Эти данные помещаются в переменную-словарь `ansible_facts`. Для удобства создаются "магические" переменные-ярлыки (например, `ansible_os_family` вместо `ansible_facts['os_family']`).

Факты чрезвычайно полезны для создания универсальных, кроссплатформенных плейбуков.

```yaml
- name: Установка Apache на RedHat/CentOS
  ansible.builtin.yum:
    name: httpd
    state: present
  when: ansible_os_family == "RedHat" # Используем факт для условного выполнения
```

Вы можете посмотреть все собранные факты для хоста, выполнив задачу с модулем debug:

```yaml
- name: Показать все факты
  ansible.builtin.debug:
    var: ansible_facts
```

### Лучшие практики ("Дзен Ansible")

1.  **Определяйте переменную в одном месте.** Избегайте многократного переопределения.
2.  **Используйте уникальные префиксы.** Чтобы избежать конфликтов имен между ролями, добавляйте префикс с названием роли или проекта (`my_app_nginx_port: 8080`).
3.  **Избегайте общих имен** (`user`, `port`, `server`).

## Условные конструкции (when)

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
*   **Логическое "ИЛИ" (OR):** Явное ключевое слово `or`.
    ```yaml
    - name: "Выполнить, если система CentOS ИЛИ Ubuntu"
      ansible.builtin.debug:
        msg: "Это RedHat-based или Debian-based система."
      when: ansible_os_family == "RedHat" or ansible_os_family == "Debian"
    ```

## Циклы (loop)

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
> **Примечание о `with_items`:** В старых версиях Ansible для циклов использовалась конструкция `with_items`. Она все еще работает, но `loop` является современным и более гибким стандартом.

### Продвинутые циклы: `until`

Связка `until`, `retries` и `delay` позволяет выполнять задачу до тех пор, пока не будет достигнуто определенное условие.

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

## Включение задач: `include_tasks` vs `import_tasks`

*   `import_tasks` (статическое включение): Содержимое файла вставляется в плейбук на этапе парсинга (до начала выполнения). **Не работает с `loop` и `when`**. Используется для простого структурирования плейбуков.
*   `include_tasks` (динамическое включение): Файл подключается в процессе выполнения. **Работает с `loop` и `when`**. Используется для динамического выбора задач.

```yaml
- name: Включить задачи для Debian-подобных систем
  ansible.builtin.include_tasks: debian.yml
  when: ansible_os_family == "Debian"
```

## Регистрация результатов (register)

Директива `register` позволяет сохранить результат выполнения задачи в переменную, которую можно использовать в `when`.

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

## Обработчики (handlers)

Обработчики — это специальные задачи, которые выполняются **только один раз** в конце плея и только по уведомлению от другой задачи (`notify`). Они идеальны для перезапуска сервисов.

```yaml
tasks:
  - name: Копирование конфигурации Nginx
    ansible.builtin.template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    notify: Restart Nginx # Отправка уведомления

handlers:
  - name: Restart Nginx
    ansible.builtin.service:
      name: nginx
      state: restarted
```
**Преимущества:**
*   **Идемпотентность:** Обработчик вызывается, только если задача реально изменила файлы (`changed`).
*   **Эффективность:** Даже если 10 задач отправят уведомление, обработчик выполнится только один раз.

## Делегирование задач (delegate_to)

Позволяет выполнить задачу на другой машине (чаще всего `localhost`), а не на целевом хосте. Классический пример — поиск локальных файлов, которые нужно скопировать на удаленный хост.

```yaml
- name: Find .war files on the control node
  ansible.builtin.find:
    paths: /path/to/local/artifacts
    patterns: "*.war"
  delegate_to: localhost # Выполнить эту задачу на машине, где запущен ansible
  register: found_artifacts
```

## Секции `pre_tasks` и `post_tasks`

*   `pre_tasks`: Блок задач, выполняемый **до** всех ролей. Полезен для предварительных проверок или установки зависимостей, необходимых для самих ролей.
*   `post_tasks`: Блок задач, выполняемый **после** всех ролей и их обработчиков. Идеален для финальных действий, например, перезагрузки сервера после обновления ядра.

```yaml
post_tasks:
  - name: Restart server after kernel upgrade
    ansible.builtin.shell: "sleep 10 && shutdown -r now"
    async: 1
    poll: 0
    when: kernel_updated is defined and kernel_updated
```

## Стратегии и параллелизм

*   `forks`: Количество одновременных процессов. Увеличивает скорость выполнения. Задается в `ansible.cfg` или через `--forks`. Значение по умолчанию — 5.

```bash
ansible-playbook -i inventory.ini playbook.yml --forks=10
```

*   `async`(максимальное время в секундах, которое задача может выполняться в фоновом режиме) и `poll`(интервал в секундах, с которым Ansible будет проверять статус задачи). `poll: 0` Ansible не будет ждать завершения задачи и сразу перейдет к следующей ("fire and forget")..
*   `throttle`: Позволяет ограничить количество хостов, на которых одновременно выполняется одна конкретная задача.

## Теги (Tags)

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
*   `always`: Задача выполняется всегда (за исключением случаев, когда вы явно ее пропускаете через --skip-tags).
*   `never`: Задача не выполняется, если не указать ее тег явно (--tags never).

## Отладка плейбуков

*   `-v, -vvv`: Увеличение уровня детализации вывода.
*   `--syntax-check`: Проверка синтаксиса YAML.
*   `--check`: "Сухой прогон" (dry run) без внесения реальных изменений.
*   `debug`: Модуль для вывода значений переменных или сообщений.

    ```yaml
    - name: Print variable value
      ansible.builtin.debug:
        var: my_variable
    ```
*   `--step`: Интерактивное пошаговое выполнение, перед выполнением каждого таска Ansible будет спрашивать вашего подтверждения (y/n/c).
*   `debugger`: Ключевое слово для вызова интерактивного отладчика на конкретной задаче.
    ```yaml
    - name: Моя задача с отладчиком
      ansible.builtin.command: some_command
      debugger: on_failed # Вызывать отладчик при сбое
    ```
*   `--limit`: Ограничение выполнения на конкретном хосте.
*   `--start-at-task`: Начало выполнения с указанной задачи.

Режимы работы debugger:

    always: Отладчик вызывается всегда, независимо от статуса задачи.
    never: Отключает отладчик для данной задачи, даже если он включен глобально.
    on_failed: Отладчик вызывается только в случае сбоя задачи.
    on_unreachable: Отладчик вызывается, если хост недоступен.
    on_skipped: Отладчик вызывается, если задача была пропущена.

## Обработка ошибок

*   `ignore_errors: true`: Продолжить выполнение, даже если задача упала.
*   `block, rescue, always`: Аналог `try...catch...finally`.
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
*   `failed_when`: Переопределение условий сбоя задачи.
    ```yaml
    - name: Проверить вывод скрипта
      command: /usr/bin/my_script.sh
      register: script_result
      failed_when: "'ERROR' in script_result.stdout"
    ```
*   `changed_when`: Переопределение условий, когда задача считается "измененной". `changed_when: false` часто используется, чтобы сделать команды идемпотентными в отчетах.

---

## Примеры

### Управление контейнерами Docker через systemd

```yaml
# Шаблон container.service.j2
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

[Install]
WantedBy=multi-user.target
```
```yaml
# Задачи Ansible
- name: Create systemd unit files for containers
  ansible.builtin.template:
    src: container.service.j2
    dest: "/etc/systemd/system/{{ item.name }}.service"
  loop: "{{ containers }}"
  notify: Reload systemd
```

### Управление Python-приложением (Gunicorn) через systemd

```yaml
# Шаблон gunicorn.service.j2
[Unit]
Description=Gunicorn instance to serve {{ app_name }}
After=network.target

[Service]
User={{ service_user }}
Group={{ service_group }}
WorkingDirectory={{ app_path }}
ExecStart={{ app_path }}/venv/bin/gunicorn --workers 3 --bind unix:{{ app_path }}/{{ app_name }}.sock -m 007 wsgi:app
```

Такой подход позволяет централизованно и декларативно управлять жизненным циклом приложений и контейнеров.

```