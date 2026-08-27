# Ansible: структура плейбука

## Определения

**Плейбук (Playbook)** — YAML-файл, содержащий один или несколько «плеев» (`plays`) для описания желаемого состояния системы и оркестрации шагов по его достижению.

**Плей (Play)** — основной строительный блок плейбука. Сопоставляет группу хостов из инвентаря с набором задач, настроек и переменных.

**Задача (Task)** — отдельная атомарная операция, вызывающая конкретный [модуль Ansible](../Modules/ansible_modules_overview.md).

**FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имён и имя коллекции (например, `ansible.builtin.apt` вместо `apt`). Использование FQCN обязательно в современных версиях для исключения конфликтов имен.

**Обработчик (Handler)** — специальная задача, которая выполняется только при получении уведомления (`notify`) от другой задачи и только если состояние системы изменилось (`changed`).

**Теги (Tags)** — метки, позволяющие запускать или исключать определенные части плейбука через CLI.

**Коллекции (Collections)** — формат распространения контента Ansible (модули, роли, плагины). Директива `collections` в плейбуке позволяет использовать модули без указания полного FQCN (не рекомендуется для продакшена).

**Блок (Block)** — логическая группировка задач, позволяющая применять общие директивы (например, `become`, `when`) к набору шагов и обрабатывать ошибки через `rescue` и `always`.

## Базовые концепции

### Структура и современный стандарт

Современный плейбук должен быть максимально декларативным, а вся сложная логика — вынесена в [роли](../ansible_roles.md). Плейбук верхнего уровня часто выступает в роли оркестратора.

```yaml
---
- name: Развертывание веб-приложения
  hosts: web_servers
  become: true
  gather_facts: true
  
  # Определение используемых коллекций
  collections:
    - ansible.builtin
    - community.general

  # Ограничение конкурентности
  serial: "25%"
  max_fail_percentage: 10
  
  # Глобальные теги для всего плея
  tags:
    - provision
    - web

  pre_tasks:
    - name: Проверка доступности API
      ansible.builtin.uri:
        url: https://api.example.com/health
        status_code: 200
      run_once: true

  roles:
    - role: web_server_base
    - role: application_deploy
      vars:
        app_version: "2.1.0"
      tags: [ deploy ]

  tasks:
    - name: Специфичная настройка с обработкой ошибок
      block:
        - name: Применение шаблона конфигурации
          ansible.builtin.template:
            src: custom_config.conf.j2
            dest: /etc/app/custom.conf
            owner: root
            group: root
            mode: '0644'
          notify: Перезапуск приложения
      rescue:
        - name: Откат конфигурации при ошибке
          ansible.builtin.copy:
            src: custom_config.conf.bak
            dest: /etc/app/custom.conf
      always:
        - name: Очистка временных файлов
          ansible.builtin.file:
            path: /tmp/app_config.tmp
            state: absent

  post_tasks:
    - name: Регистрация в мониторинге
      ansible.builtin.uri:
        url: https://mon.example.com/register
        method: POST
        body_format: json
        body:
          host: "{{ ansible_fqdn }}"

  handlers:
    - name: Перезапуск приложения
      ansible.builtin.systemd:
        name: myapp
        state: restarted
```

### Директивы управления выполнением

1.  **Стратегии выполнения (`strategy`)**:
    *   `linear` (по умолчанию): Все хосты завершают одну задачу, прежде чем перейти к следующей. Обеспечивает синхронизацию между хостами.
    *   `free`: Каждый хост проходит через плейбук настолько быстро, насколько может, независимо от других. Используется, когда задачи на разных хостах не зависят друг от друга.
    *   `host_pinned`: Похожа на `free`, но удерживает фиксированное количество хостов в работе (определяется параметром `serial`).
    *   `debug`: Стратегия для отладки. Приостанавливает выполнение перед каждой задачей и позволяет inspect переменные через `vars`.

2.  **Пакетная обработка (`serial`)**: Позволяет обновлять хосты частями (число или проценты). Критично для Rolling Updates. Пример:
    ```yaml
    serial: "30%"       # Обновлять 30% хостов за раз
    serial: 2            # Обновлять по 2 хоста
    serial: [1, 5, "50%"] # Первый хост, затем 5, затем 50% (постепенное увеличение)
    ```
    При использовании `serial` Ansible последовательно обрабатывает каждую «пачку» хостов, что позволяет обнаружить ошибки на ранней стадии и остановить обновление до того, как пострадает весь кластер.

3.  **Контроль ошибок**:
    *   `any_errors_fatal: true`: Прекращает выполнение на всех хостах, если хотя бы один упал. Используется для критичных операций (миграция БД).
    *   `max_fail_percentage`: Порог падений (целое число 0-100), после которого весь плей останавливается. Работает только с `serial`.
    *   `ignore_errors: true`: Продолжает выполнение, даже если задача завершилась с ошибкой. Задача помечается как `failed`, но плей продолжается.
    *   `ignore_unreachable: true`: Игнорирует ошибки недостижимости хостов (SSH-timeout, network failure). Отличается от `ignore_errors`: хост помечается как `unreachable`, а не `failed`.
    *   `errors` (в блоке): Позволяет определить собственный обработчик ошибок для блока задач:
    ```yaml
    block:
      - name: Критичная операция
        ansible.builtin.command: /usr/bin/critical_op
    rescue:
      - name: Восстановление
        ansible.builtin.command: /usr/bin/recover
    always:
      - name: Очистка
        ansible.builtin.file: path=/tmp/op state=absent
    ```

4.  **Ограничения (`throttle` / `run_once`)**:
    *   `throttle`: Лимит конкурентных задач для конкретного шага (например, чтобы не перегрузить API БД). Работает совместно с `forks` в `ansible.cfg`.
    *   `run_once`: Выполняет задачу только на одном хосте из всей группы. Результат доступен через `hostvars[inventory_hostname]` для остальных хостов.

5.  **Тегирование (`tags`)**:
    *   Могут задаваться на уровне Play, Task, Block или Role.
    *   Теги на уровне Play наследуются всеми задачами внутри.
    *   Специальные теги:
        *   `always` (по умолчанию): Задача выполняется всегда, если не исключена явно через `--skip-tags`.
        *   `never`: Задача выполняется только если указан явно через `--tags never`.
        *   `debug`, `assert`, `meta`: Задачи этих типов имеют тег `always` по умолчанию.
    *   Примеры использования в CLI:
    ```bash
    ansible-playbook site.yml --tags "deploy,config"     # Только задачи с этими тегами
    ansible-playbook site.yml --skip-tags "never"         # Все кроме задач с тегом never
    ansible-playbook site.yml --list-tags                 # Показать все доступные теги
    ansible-playbook site.yml --list-tasks                # Показать все задачи
    ```

6.  **Проверка изменений (`check_mode` / `diff`)**:
    *   `check_mode: true` (на уровне задачи): Принудительно выполняет задачу в режиме проверки (dry-run), даже если плейбук запущен без `--check`.
    *   `check_mode: false` (на уровне задачи): Принудительно выполняет задачу с реальными изменениями, даже если плейбук запущен с `--check`. Используется для задач, которые нельзя проверить (например, `ansible.builtin.raw`).
    *   `--check` (CLI): Запуск всего плейбука в режиме проверки. Ansible покажет, какие изменения были бы сделаны, но не применяет их.
    *   `--diff` (CLI): Показывает разницу между текущим и целевым состоянием файлов. Работает с модулями `copy`, `template`, `file` и др.

7.  **Управление состоянием задач**:
    *   `changed_when`: Позволяет переопределить условие, при котором задача считается «изменившей» систему. Пример:
    ```yaml
    - name: Проверка версии пакета
      ansible.builtin.command: dpkg -l nginx
      register: dpkg_result
      changed_when: "'ii  nginx' not in dpkg_result.stdout"
      # Задача не будет помечена как changed, даже если команда выполнена
    ```
    *   `failed_when`: Позволяет определить собственное условие ошибки:
    ```yaml
    - name: Проверка свободного места
      ansible.builtin.command: df -h /
      register: disk_check
      failed_when: "'95%' in disk_check.stdout"
      # Ошибка только если занято > 95%
    ```

### Иерархия выполнения (Order of Operations)

Ansible строго следует порядку выполнения секций внутри плея. Обработчики (`handlers`) запускаются автоматически после каждой секции, если задачи в этой секции сообщили об изменениях (`changed`):

1.  **`pre_tasks`**: Проверки и подготовка до выполнения ролей.
2.  **`handlers`**: Запускаются все обработчики, уведомленные в `pre_tasks`.
3.  **`roles`**: Основная логика, упакованная в модульные блоки.
4.  **`tasks`**: Специфичные для конкретного плея действия (выполняются вместе с ролями в контексте порядка обработчиков).
5.  **`handlers`**: Запускаются все обработчики, уведомленные в `roles` и `tasks`.
6.  **`post_tasks`**: Финальные штрихи (регистрация в балансировщиках, мониторинге).
7.  **`handlers`**: Запускаются все обработчики, уведомленные в `post_tasks`.

*Примечание:* Использование `meta: flush_handlers` позволяет принудительно запустить все накопленные обработчики в любой момент внутри секции задач.

### Статическое и динамическое подключение

Структура плейбука может меняться в зависимости от способа подключения внешних файлов:
*   **Static (`import_*`)**: Задачи импортируются на этапе парсинга плейбука. Они ведут себя так, будто прописаны в основном файле. Нельзя использовать переменные из инвентаря для выбора имени файла.
*   **Dynamic (`include_*`)**: Задачи подключаются в момент выполнения. Позволяет использовать условия (`when`) и переменные для выбора подключаемых файлов.

### Приоритеты и переменные

Внутри плейбука переменные могут определяться на разных уровнях. Подробная иерархия приоритетов описана в разделе [Переменные и факты](variables.md). Основные директивы определения переменных:

*   `vars`: Статические переменные плея. Определяются в YAML-словаре или списке файлов:
    ```yaml
    vars:
      app_version: "2.1.0"
      db_host: "db.example.com"
    vars_files:
      - "vars/{{ ansible_facts['os_family'] }}.yml"
      - "vars/secrets.yml"  # Может быть зашифрован Vault
    ```

*   `vars_prompt`: Интерактивный запрос данных у пользователя при запуске. Позволяет запрашивать пароли, версии и другие параметры:
    ```yaml
    vars_prompt:
      - name: deploy_version
        prompt: "Введите версию для деплоя"
        default: "latest"
        private: false  # Отображать ввод

      - name: db_password
        prompt: "Пароль базы данных"
        private: true   # Скрыть ввод
        encrypt: sha512_crypt  # Зашифровать (для Ansible Vault)
        confirm: true    # Запросить подтверждение
    ```

*   `extra_vars` (CLI): Переменные, переданные через командную строку. Имеют **абсолютный приоритет** над всеми другими переменными:
    ```bash
    ansible-playbook site.yml -e "app_version=3.0.0 env=production"
    ansible-playbook site.yml -e @vars/override.yml  # Из файла
    ```

*   `environment`: Определение переменных окружения для задач. Полезно для настройки прокси, путей или специфичных переменных приложения:
    ```yaml
    environment:
      http_proxy: "http://proxy.example.com:3128"
      https_proxy: "http://proxy.example.com:3128"
      no_proxy: "localhost,127.0.0.1,.internal"
      PYTHONPATH: "/opt/app/lib"
    ```

*   `register`: Сохранение результата выполнения задачи в переменную для дальнейшего использования. Объект результата содержит поля `stdout`, `stderr`, `rc` (код возврата), `changed` и другие:
    ```yaml
    - name: Получить список файлов
      ansible.builtin.command: ls -la /etc/
      register: etc_files

    - name: Показать результат
      ansible.builtin.debug:
        var: etc_files.stdout_lines  # Список строк вывода
    ```

## Практические сценарии

### Сценарий 1: Rolling Update с проверкой (Canary-style)

Использование `serial` для постепенного обновления парка серверов. При ошибке на первом хосте обновление остальных не продолжается.

```yaml
- name: Обновление кластера БД
  hosts: db_nodes
  become: true
  serial: 1  # Сначала один хост, затем остальные
  any_errors_fatal: true

  tasks:
    - name: Установка новой версии
      ansible.builtin.package:
        name: my-db-engine
        state: latest
      notify: Рестарт БД

    - name: Проверка работоспособности после обновления
      ansible.builtin.wait_for:
        port: 5432
        state: started
        timeout: 30

    - name: Проверка репликации
      ansible.builtin.command: psql -U postgres -c "SELECT pg_is_in_recovery();"
      register: replication_status
      changed_when: false

  handlers:
    - name: Рестарт БД
      ansible.builtin.systemd:
        name: postgresql
        state: restarted
```

**Валидация:**
```bash
ansible-playbook site.yml --check --diff  # Режим проверки
ansible-playbook site.yml --limit db_nodes[0]  # Только первый хост
ansible-playbook site.yml --list-tasks  # Просмотр задач без выполнения
```

### Сценарий 2: Bootstrap с установкой Python

Использование `gather_facts: false` и `raw` для первичной подготовки «голых» систем. Модуль `raw` работает без Python и не является идемпотентным.

```yaml
- name: Первичная подготовка (Bootstrap)
  hosts: new_nodes
  gather_facts: false
  become: true

  tasks:
    - name: Установка Python3 на Ubuntu/Debian
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      changed_when: false

    - name: Установка Python3 на RHEL/CentOS
      ansible.builtin.raw: yum install -y python3
      when: ansible_facts['os_family'] is not defined  # До сбора фактов
      changed_when: false

    - name: Сбор фактов после установки Python
      ansible.builtin.setup:  # Принудительный сбор фактов
```

**Примечание:** После выполнения `raw` факты не собраны. Используйте `ansible.builtin.setup` для явного сбора перед последующими задачами.

### Сценарий 3: Атомарные изменения с использованием блоков

Использование `block/rescue/always` для группировки связанных изменений и обеспечения отката при ошибке. Механика:
- `block`: Основные задачи. Если хотя одна завершается с ошибкой, управление переходит в `rescue`.
- `rescue`: Задачи отката. Выполняются только при ошибке в `block`.
- `always`: Задачи очистки. Выполняются всегда, независимо от результата.

```yaml
- name: Обновление конфигурации Nginx
  hosts: web_servers
  become: true

  tasks:
    - name: Применение новой конфигурации
      block:
        - name: Копирование конфига
          ansible.builtin.copy:
            src: nginx.conf
            dest: /etc/nginx/nginx.conf
            validate: /usr/sbin/nginx -t  # Валидация перед применением

        - name: Перезапуск Nginx
          ansible.builtin.systemd:
            name: nginx
            state: reloaded
      rescue:
        - name: Логирование ошибки
          ansible.builtin.debug:
            msg: "Ошибка при обновлении Nginx. Откат к предыдущей версии."

        - name: Восстановление старого конфига
          ansible.builtin.copy:
            src: nginx.conf.bak
            dest: /etc/nginx/nginx.conf

        - name: Перезапуск с восстановленным конфигом
          ansible.builtin.systemd:
            name: nginx
            state: restarted
      always:
        - name: Очистка временных файлов
          ansible.builtin.file:
            path: /tmp/nginx_config.tmp
            state: absent
```

### Сценарий 4: Динамическое подключение задач по ОС

Использование `include_tasks` с переменными для выбора файла задач в зависимости от типа операционной системы. Демонстрирует гибкость динамического включения.

```yaml
- name: Настройка сервера
  hosts: all_servers
  become: true

  tasks:
    - name: Определение типа ОС
      ansible.builtin.debug:
        msg: "ОС: {{ ansible_facts['os_family'] }}"

    - name: Подключение задач для Debian/Ubuntu
      ansible.builtin.include_tasks: debian.yml
      when: ansible_facts['os_family'] == "Debian"

    - name: Подключение задач для RedHat/CentOS
      ansible.builtin.include_tasks: redhat.yml
      when: ansible_facts['os_family'] == "RedHat"
```

**Файл `debian.yml`:**
```yaml
---
- name: Обновление apt-кэша
  ansible.builtin.apt:
    update_cache: true
    cache_valid_time: 3600

- name: Установка пакетов
  ansible.builtin.apt:
    name:
      - nginx
      - python3-pip
    state: present
```

### Сценарий 5: Отладка плейбука (Debug)

Использование `debug` и `assert` для проверки переменных и условий во время выполнения. Полезно при разработке и отладке сложных плейбуков.

```yaml
- name: Отладка конфигурации
  hosts: localhost
  gather_facts: false

  vars:
    target_env: "production"
    app_port: 8080

  tasks:
    - name: Вывод всех переменных
      ansible.builtin.debug:
        var: hostvars[inventory_hostname]

    - name: Проверка обязательных переменных
      ansible.builtin.assert:
        that:
          - target_env is defined
          - target_env | length > 0
          - app_port is number
          - app_port | int >= 1024
        fail_msg: "Не все обязательные переменные определены или некорректны"
        success_msg: "Все переменные корректны"

    - name: Условный вывод
      ansible.builtin.debug:
        msg: "Целевое окружение: {{ target_env }}"
      when: target_env == "production"
```

## Валидация и отладка

### Статический анализ

Перед запуском плейбука рекомендуется выполнить статическую проверку:

```bash
ansible-playbook site.yml --syntax-check
# → Проверка синтаксиса YAML и структуры плейбука

ansible-lint site.yml
# → Проверка по правилам ansible-lint (рекомендуется настроить в CI)
```

### Просмотр без выполнения

```bash
ansible-playbook site.yml --list-tasks
# → Показать все задачи без выполнения

ansible-playbook site.yml --list-tags
# → Показать все доступные теги

ansible-playbook site.yml --list-hosts
# → Показать хосты, затронутые плейбуком

ansible-playbook site.yml --limit webservers
# → Ограничить выполнение конкретной группой
```

### Режим проверки и отладки

```bash
ansible-playbook site.yml --check
# → Dry-run: показать какие изменения были бы сделаны

ansible-playbook site.yml --check --diff
# → Dry-run с показом разницы в файлах

ansible-playbook site.yml --step
# → Пошаговое выполнение с интерактивным подтверждением каждой задачи

ansible-playbook site.yml --start-at-task="Установка пакетов"
# → Начать выполнение с указанной задачи

ansible-playbook site.yml -vvv
# → Подробный вывод (максимальная детализация -vvvv)

ansible-playbook site.yml --force-handlers
# → Выполнить обработчики даже при ошибке плейбука
```

### Отладка переменных

```yaml
- name: Вывод переменных для отладки
  ansible.builtin.debug:
    var: my_variable       # Вывести значение переменной

- name: Вывод сообщения
  ansible.builtin.debug:
    msg: "Значение: {{ my_variable }}"

- name: Вывод всех фактов хоста
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]
```

### Проверка подключения

```bash
ansible all -m ping -i inventory.ini
# → Проверить доступность всех хостов

ansible web_servers -m setup -i inventory.ini
# → Собрать факты о хостах группы web_servers
```

## Типичные ошибки и troubleshooting

### Ошибка: "Module failed to set locale"

**Причина:** Отсутствуют локали на целевом хосте.

**Решение:**
```yaml
- name: Установка локалей
  ansible.builtin.locale_gen:
    name: en_US.UTF-8
    state: present
```

### Ошибка: "UNREACHABLE: Failed to connect to the host via ssh"

**Причина:** Нет SSH-доступа к хосту. Возможные решения:
1. Проверьте SSH-ключ и настройки `ansible.cfg` (`remote_user`, `private_key_file`).
2. Убедитесь, что хост доступен по сети: `ping host` и `ssh user@host`.
3. Проверьте SSH-authorized_keys на целевом хосте.

### Ошибка: "Failed to lock apt" или "Could not get lock"

**Причина:** Параллельный доступ к apt (другой процесс или плейбук).

**Решение:**
```yaml
- name: Установка пакетов с ожиданием блокировки
  ansible.builtin.apt:
    name: nginx
    state: present
    lock_timeout: 30  # Ожидать блокировки до 30 секунд
```

### Ошибка: "The field 'become' is not allowed"

**Причина:** Использование директивы `become` в неподходящем уровне (например, внутри задачи вместо плея).

**Решение:** `become` задается на уровне Play или Task:
```yaml
- name: Пример
  hosts: all
  become: true  # На уровне Play
  tasks:
    - name: Задача с become
      ansible.builtin.command: /usr/bin/privileged_op
      become: true  # На уровне Task (если become: false на уровне Play)
```

### Ошибка: "Variables are not allowed on the from line for import_tasks"

**Причина:** Попытка использовать переменные в `import_tasks` (статическое включение).

**Решение:** Используйте `include_tasks` (динамическое включение):
```yaml
# НЕПРАВИЛЬНО
- ansible.builtin.import_tasks: "{{ os_family }}_tasks.yml"

# ПРАВИЛЬНО
- ansible.builtin.include_tasks: "{{ os_family }}_tasks.yml"
```

### Ошибка: "No handler found"

**Причина:** Обработчик вызван через `notify`, но не определен в секции `handlers`.

**Решение:** Убедитесь, что имя обработчика в `notify` совпадает с именем в `handlers`. Обработчики определяются отдельно и выполняются только один раз.

## Лучшие практики

### Структура плейбука

1. **Один плей = одна цель.** Не смешивайте установку, конфигурацию и деплой в одном плее.
2. **Плейбуки-оркестраторы.** Верхнеуровневые плейбуки должны вызывать роли через `import_playbook` или `roles`, а не содержать задачи напрямую.
3. **FQCN.** Всегда используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`).
4. **Идиоматичность.** Используйте специализированные модули вместо `shell`/`command` для обеспечения идемпотентности.

### Переменные

5. **`defaults/` для ролей.** Значения по умолчанию определяйте в `roles/x/defaults/main.yml` — это самый низкий приоритет и легко переопределяется.
6. **`group_vars/` для окружений.** Конфигурации окружений храните в `group_vars/`.
7. **Избегайте магических чисел.** Выносите числовые значения в переменные с осмысленными именами.

### Безопасность

8. **`no_log: true`.** Скрывайте задачи, содержащие пароли, ключи API и другие секреты.
9. **Vault для секретов.** Используйте `ansible-vault encrypt` для зашифровки файлов с секретами.
10. **`become` только когда необходимо.** Не поднимайте привилегии на весь плейбук, если это не требуется для каждой задачи.

### Производительность

11. **`gather_facts: false`.** Отключайте сбор фактов, если они не используются.
12. **`serial` для больших инвентарей.** Используйте пакетную обработку для контроля нагрузки.
13. **`pipelining = true`.** Включите в `ansible.cfg` для ускорения выполнения (требуется `requiretty` в sudoers).

### Отладка

14. **`--syntax-check`.** Всегда проверяйте синтаксис перед запуском.
15. **`--check --diff`.** Используйте dry-run перед реальными изменениями.
16. **`debug` и `assert`.** Проверяйте переменные и условия в плейбуках.

## Дополнительная информация

* [Управление ходом выполнения](flow_control.md) — условия `when`, циклы и подробный разбор блоков.
* [Переменные и факты](variables.md) — детальная иерархия приоритетов и использование `ansible_facts`.
* [Продвинутые возможности плейбуков](advanced.md) — делегирование (`delegate_to`), асинхронные задачи и отладка.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — как не стоит организовывать структуру проекта.
