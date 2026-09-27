# Ansible: Модули управления выполнением и контролем потока

## Определения

**Модули управления выполнением** — группа псевдо-модулей и директив Ansible, которые не выполняют действий на управляемых хостах, а управляют логикой выполнения плейбука: динамическим включением задач и ролей, делегированием, циклами, условиями и повторными попытками.

**Динамическое включение (Dynamic Inclusion)** — механизмы `include_tasks`, `include_role`, `import_tasks`, `import_role`, которые позволяют включать задачи и роли во время выполнения плейбука на основе условий, переменных или результатов предыдущих задач.

**Делегирование (`delegate_to`)** — механизм выполнения задачи на другом хосте, а не на текущем целевом. Используется для операций, которые должны выполняться на контрольном узле, на балансировщике или между двумя удаленными хостами.

**Loop control** — механизмы управления итерациями в циклах Ansible: `loop_control`, `until`/`retries`/`delay`, фильтры `flatten`, `subelements`, `zip`, `product`, `indexed_items`.

**Асинхронное выполнение (`async`/`poll`)** — механизм запуска долгих операций в фоне с возможностью проверки статуса через `async_status`.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ | 2.15 — минимальная поддерживаемая версия; 2.21 — текущий стабильный релиз (сентябрь 2026) |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]
```

## Архитектура и принципы работы

Модули управления выполнением operate на уровне контроллера Ansible, а не на управляемых хостах. Их работа делится на три фазы:

### 1. Фаза парсинга (Static resolution)

Во время парсинга плейбука Ansible обрабатывает статические директивы:
- `import_tasks` — задачи включаются в плейбук до начала выполнения
- `import_role` — роль подключается до начала выполнения
- `import_playbook` — внешний плейбук встраивается в текущий

Статические включения поддерживают теги и переменные на уровне плейбука, но не могут зависеть от runtime-значений.

### 2. Фаза выполнения (Dynamic resolution)

Во время выполнения плейбука обрабатываются динамические директивы:
- `include_tasks` — задачи подключаются на лету
- `include_role` — роль подключается на лету
- Динамические хосты (`add_host`, `group_by`)

Динамические включения поддерживают `when`, `loop`, переменные из `register` и `set_fact`, но теги не передаются во вложенные задачи автоматически.

### 3. Фаза контроля выполнения (Execution control)

На этом уровне работают псевдо-модули и директивы:
- `ansible.builtin.meta` — управление handlers, завершение выполнения, сброс ошибок
- `delegate_to` / `run_once` — перераспределение задач
- `until`/`retries`/`delay` — повторные попытки
- `async`/`poll` — асинхронное выполнение
- `loop_control` — тонкая настройка циклов

### Взаимодействие с handlers

Handlers запускаются автоматически в определенных точках выполнения:
- После секции `tasks` плейбука
- После `pre_tasks` и `post_tasks`
- После завершения роли
- После `meta: flush_handlers`

`meta: flush_handlers` принудительно запускает все уведомленные handlers в текущий момент, что критично при необходимости применить изменения до продолжения выполнения.

## Основные концепции

### Динамическое включение задач и ролей

**`ansible.builtin.include_tasks`** — включает задачи из внешнего файла во время выполнения. Включение происходит динамически, на момент выполнения задачи.
```yaml
- name: "Включение задач конфигурации"
  ansible.builtin.include_tasks: configure.yml
  when: app_enabled | default(false)
```

**`ansible.builtin.import_tasks`** — импортирует задачи из внешнего файла во время парсинга плейбука. Импорт статический, происходит до начала выполнения.
```yaml
- name: "Импорт задач безопасности"
  ansible.builtin.import_tasks: security.yml
```

**`ansible.builtin.include_role`** — включает роль во время выполнения. Позволяет передавать параметры динамически.
```yaml
- name: "Включение роли веб-сервера"
  ansible.builtin.include_role:
    name: webserver
  vars:
    server_type: "{{ detected_server }}"
  when: deploy_web | default(false)
```

**`ansible.builtin.import_role`** — импортирует роль во время парсинга. Статический импорт.
```yaml
- name: "Импорт базовой роли"
  ansible.builtin.import_role:
    name: common
```

**`ansible.builtin.import_playbook`** — импортирует другой плейбук. Позволяет разбивать крупные плейбуки на части.
```yaml
- name: "Импорт плейбука развертывания"
  ansible.builtin.import_playbook: deploy.yml
```

**Различия include vs import:**
- `import_*`: статический, выполняется при парсинге, теги видны в подзадачах.
- `include_*`: динамический, выполняется во время выполнения, теги не передаются вложенным задачам.
- **Рекомендация**: Используйте `import_*` для фиксированной структуры, `include_*` для условной логики.

### Псевдо-модуль `ansible.builtin.meta`

**`ansible.builtin.meta`** — управляет выполнением плейбука на уровне контроллера. Поддерживаемые команды:

| Команда | Добавлено в | Назначение |
| :--- | :--- | :--- |
| `flush_handlers` | 2.0 | Принудительно запустить все уведомленные handlers |
| `refresh_inventory` | 2.0 | Перезагрузить inventory (полезно после `add_host`) |
| `clear_facts` | 2.1 | Очистить факты для хостов плейбука |
| `clear_host_errors` | 2.1 | Сбросить состояние failed для хостов |
| `end_play` | 2.2 | Завершить выполнение плейбука без ошибки |
| `end_host` | 2.8 | Завершить выполнение для текущего хоста без ошибки |
| `reset_connection` | 2.3 | Разорвать persistent-соединение (SSH control persist) |
| `end_batch` | 2.12 | Завершить текущий батч (при `serial`) без ошибки |
| `end_role` | 2.18 | Завершить выполнение роли без ошибки; handlers роли продолжают работать |
| `noop` | 2.0 | Ничего не делать; в основном используется внутренне |

```yaml
# Очистка ошибок хоста
- name: "Сброс ошибок хоста"
  ansible.builtin.meta: clear_host_errors

# Принудительный вызов handlers
- name: "Применение handlers"
  ansible.builtin.meta: flush_handlers

# Завершение выполнения на текущем хосте
- name: "Пропуск остальных задач"
  ansible.builtin.meta: end_host

# Завершение выполнения на всех хостах
- name: "Завершение плейбука"
  ansible.builtin.meta: end_play
```

### Делегирование и динамические хосты

**`delegate_to`** — выполняет задачу на указанном хосте вместо текущего целевого. Работает на уровне задачи, не всего плейбука.
```yaml
- name: "Регистрация в балансировщике"
  community.general.haproxy:
    host: "{{ inventory_hostname }}"
    backend: app_backend
    state: enabled
  delegate_to: "{{ groups['load_balancer'][0] }}"
```

**`run_once`** — выполняет задачу только один раз на всем плейбуке, а не на каждом хосте.
```yaml
- name: "Создание резервной копии БД"
  ansible.builtin.command: /opt/scripts/backup.sh
  run_once: yes
  delegate_to: "{{ groups['backup_server'][0] }}"
```

**`local_action`** — синоним `delegate_to: localhost`.
```yaml
- name: "Создание файла на контрольном узле"
  ansible.builtin.copy:
    content: "{{ inventory_hostname }}"
    dest: "/tmp/{{ inventory_hostname }}.txt"
  delegate_to: localhost
```

**`delegate_facts`** — позволяет сохранить факты, собранные с целевого хоста, у делегированного хоста (например, у балансировщика). Используется совместно с `delegate_to: true`.
```yaml
- name: "Сбор фактов с удаленного хоста"
  ansible.builtin.setup:
  delegate_to: "{{ target_host }}"
  delegate_facts: true
```

### Динамическое создание хостов

**`ansible.builtin.add_host`** — добавляет хост в inventory во время выполнения.
```yaml
- name: "Добавление нового сервера в inventory"
  ansible.builtin.add_host:
    name: "{{ new_server_ip }}"
    groups: newly_provisioned
    ansible_user: deploy
    ansible_ssh_private_key_file: /home/deploy/.ssh/id_rsa
```

**`ansible.builtin.group_by`** — группирует хосты на основе критерия.
```yaml
- name: "Группировка хостов по ОС"
  ansible.builtin.group_by:
    key: "os_{{ ansible_distribution | lower }}"
```

### Управление циклами

**`loop_control`** — управляет поведением цикла.
```yaml
- name: "Создание пользователей с метками"
  ansible.builtin.user:
    name: "{{ item.name }}"
    state: present
  loop: "{{ users }}"
  loop_control:
    label: "Создание пользователя {{ item.name }}"
    pause: 5
```

**`until`/`retries`/`delay`** — повторное выполнение задачи до успеха.
```yaml
- name: "Ожидание запуска сервиса"
  ansible.builtin.uri:
    url: "http://{{ inventory_hostname }}:8080/health"
    status_code: 200
  register: health_check
  until: health_check.status == 200
  retries: 30
  delay: 10
```

**Асинхронное выполнение (`async`/`poll`)** — запуск долгих операций в фоне с последующей проверкой статуса.
```yaml
- name: "Запуск долгой операции"
  ansible.builtin.shell: /opt/scripts/long_task.sh
  async: 3600
  poll: 0
  register: long_job

- name: "Ожидание завершения"
  ansible.builtin.async_status:
    jid: "{{ long_job.ansible_job_id }}"
  register: job_status
  until: job_status.finished
  retries: 60
  delay: 10
```

**Фильтры для сложных циклов:**
- `flatten`: Выравнивание вложенных списков.
- `subelements`: Итерация по вложенным структурам.
- `zip`: Объединение нескольких списков.
- `product`: Декартово произведение списков.
- `indexed_items`: Итерация с индексом.

```yaml
- name: "Настройка пользователей и SSH-ключей"
  ansible.builtin.authorized_key:
    user: "{{ item.0.name }}"
    key: "{{ item.1 }}"
  loop: "{{ users | subelements('ssh_keys') }}"
```

## Операции и команды

### Директивы управления выполнением

| Директива | Уровень | Тип | Назначение |
| :--- | :--- | :--- | :--- |
| `import_tasks` | задача | static | Импорт задач из файла на этапе парсинга |
| `include_tasks` | задача | dynamic | Динамическое включение задач на этапе выполнения |
| `import_role` | задача | static | Импорт роли на этапе парсинга |
| `include_role` | задача | dynamic | Динамическое включение роли на этапе выполнения |
| `import_playbook` | play | static | Включение внешнего плейбука на этапе парсинга |
| `delegate_to` | задача | — | Выполнение задачи на указанном хосте |
| `delegate_facts` | задача | bool | Сохранять факты у делегированного хоста |
| `run_once` | задача | bool | Выполнить задачу только один раз на батч |
| `local_action` | задача | — | Синоним `delegate_to: localhost` |
| `async` | задача | int | Максимальное время выполнения в секундах |
| `poll` | задача | int | 0 — запустить в фоне; >0 — опрашивать статус |
| `until` | задача | expr | Условие успешного завершения |
| `retries` | задача | int | Количество попыток |
| `delay` | задача | int | Задержка между попытками в секундах |
| `loop_control.label` | задача | str | Кастомная метка для вывода |
| `loop_control.pause` | задача | int | Пауза между итерациями в секундах |
| `loop_control.index_var` | задача | str | Имя переменной для индекса |
| `serial` | play | int / list | Размер батча для rolling updates |
| `force_handlers` | play | bool | Запускать handlers даже при ошибках |

### Псевдо-модуль `ansible.builtin.meta` — параметры

| Параметр | Добавлено | Назначение |
| :--- | :--- | :--- |
| `flush_handlers` | 2.0 | Принудительно запустить handlers |
| `refresh_inventory` | 2.0 | Перезагрузить inventory |
| `clear_facts` | 2.1 | Очистить факты хостов |
| `clear_host_errors` | 2.1 | Сбросить failed-состояние хостов |
| `end_play` | 2.2 | Завершить плейбук без ошибки |
| `reset_connection` | 2.3 | Разорвать SSH-соединение |
| `end_host` | 2.8 | Завершить выполнение для текущего хоста |
| `end_batch` | 2.12 | Завершить текущий батч (с `serial`) |
| `end_role` | 2.18 | Завершить роль без ошибки |
| `noop` | 2.0 | Ничего не делать |

### Фильтры для циклов

| Фильтр | Назначение | Пример |
| :--- | :--- | :--- |
| `flatten` | Выравнивание вложенных списков | `{{ nested | flatten }}` |
| `subelements` | Итерация по вложенным структурам | `{{ users | subelements('ssh_keys') }}` |
| `zip` | Объединение списков по индексам | `{{ list1 | zip(list2) | list }}` |
| `product` | Декартово произведение | `{{ list1 | product(list2) | list }}` |
| `indexed_items` | Итерация с индексом | `loop: "{{ items | enumerate(start=1) }}"` |

## Практические сценарии

### Сценарий 1: Динамическое включение задач по условию

```yaml
- name: "Выбор конфигурации по ОС"
  ansible.builtin.include_tasks: "{{ ansible_os_family }}.yml"
  when: app_enabled | default(false)

# tasks/Debian.yml
- name: "Установка на Debian"
  ansible.builtin.apt:
    name: nginx
    state: present

# tasks/RedHat.yml
- name: "Установка на RHEL"
  ansible.builtin.dnf:
    name: nginx
    state: present
```

### Сценарий 2: Делегирование и run_once

```yaml
- name: "Создание резервной копии"
  ansible.builtin.command: /opt/scripts/backup.sh
  run_once: yes
  delegate_to: "{{ groups['backup_server'][0] }}"

- name: "Ожидание завершения бэкапа"
  ansible.builtin.async_status:
    jid: "{{ backup_job.ansible_job_id }}"
  register: backup_status
  until: backup_status.finished
  retries: 60
  delay: 10
  run_once: yes
  delegate_to: "{{ groups['backup_server'][0] }}"
```

### Сценарий 3: Добавление хостов и группировка

```yaml
- name: "Развертывание новых серверов"
  hosts: localhost
  gather_facts: no
  tasks:
    - name: "Получение списка новых серверов из API"
      ansible.builtin.uri:
        url: "https://api.example.com/servers/new"
        return_content: yes
      register: api_response

    - name: "Добавление серверов в inventory"
      ansible.builtin.add_host:
        name: "{{ item.ip }}"
        groups: newly_provisioned
        ansible_user: deploy
        ansible_ssh_private_key_file: /home/deploy/.ssh/id_rsa
      loop: "{{ api_response.json.servers }}"

    - name: "Группировка по окружению"
      ansible.builtin.group_by:
        key: "env_{{ item.env }}"
      loop: "{{ api_response.json.servers }}"
```

### Сценарий 4: Сложные циклы с subelements

```yaml
- name: "Настройка SSH-ключей для пользователей"
  hosts: all
  become: yes
  vars:
    users:
      - name: deploy
        ssh_keys:
          - "ssh-ed25519 AAAA... deploy@ci"
          - "ssh-ed25519 BBBB... deploy@backup"
      - name: monitor
        ssh_keys:
          - "ssh-ed25519 CCCC... monitor@zabbix"
  tasks:
    - name: "Создание пользователей"
      ansible.builtin.user:
        name: "{{ item.0.name }}"
        state: present
        create_home: yes
      loop: "{{ users | subelements('ssh_keys') }}"

    - name: "Добавление SSH-ключей"
      ansible.posix.authorized_key:
        user: "{{ item.0.name }}"
        key: "{{ item.1 }}"
        state: present
      loop: "{{ users | subelements('ssh_keys') }}"
```

### Сценарий 5: Асинхронная задача с контролем статуса

```yaml
- name: "Запуск обновления пакетов"
  ansible.builtin.apt:
    update_cache: yes
    upgrade: dist
  async: 1800
  poll: 0
  register: update_job
  run_once: yes

- name: "Ожидание завершения обновления"
  ansible.builtin.async_status:
    jid: "{{ update_job.ansible_job_id }}"
  register: update_status
  until: update_status.finished
  retries: 180
  delay: 10
  run_once: yes
```

### Сценарий 6: Использование meta: end_role в роли

```yaml
# roles/db_setup/tasks/main.yml
- name: "Проверка необходимости настройки"
  ansible.builtin.stat:
    path: /etc/postgresql/16/main/postgresql.conf
  register: pg_conf

- name: "Завершение роли если БД уже настроена"
  ansible.builtin.meta: end_role
  when: pg_conf.stat.exists

- name: "Продолжение настройки БД"
  ansible.builtin.lineinfile:
    path: /etc/postgresql/16/main/postgresql.conf
    regexp: "^listen_addresses"
    line: "listen_addresses = '{{ db_listen_address }}'"
```

## Типичные ошибки и диагностика

### Ошибки при работе с динамическим включением

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR! 'include_role' is not a valid attribute` | Версия Ansible < 2.9 | Обновите до Ansible 2.9+ |
| `ERROR! Conflicting action 'import_role' with 'when'` | Условие `when` на уровне плейбука вместе с `import_role` | Вынесите `when` внутрь задачи |
| `ERROR! No such file` при `include_tasks` | Неверный путь к файлу задач | Проверьте относительный путь от `tasks/` |
| Переменная не видна в `include_tasks` | `include_tasks` динамическое и может не видеть `register`/`set_fact` | Используйте `include_tasks` вместо `import_tasks` или передавайте переменные явно |
| `end_role` вызывает завершение всего плейбука | Неправильное использование вне роли или в handler | Используйте `end_role` только внутри задачи роли |

### Ошибки при делегировании

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `delegate_to` обращается к неверному окружению | Хост задан явно, но не существует в текущем инвентаре | Проверьте наличие хоста: `ansible-inventory -i inventories/prod --graph` |
| Хост остаётся в состоянии `failed` после отката | Ошибка не очищена | Используйте `meta: clear_host_errors` в блоке `rescue` перед повторной попыткой |
| Delegation через bastion не работает | Отсутствует проброс SSH-агента | Добавьте `ForwardAgent yes` в SSH config |

### Ошибки при циклах и повторных попытках

| Ошибка / Сиymptom | Причина | Решение |
| :--- | :--- | :--- |
| Цикл выполняется бесконечно | `until` всегда ложно или `retries` = 0 | Убедитесь, что условие может выполниться; `retries` ≥ 1 |
| `until` не реагирует на изменения | Проверяется не тот факт | Используйте `register` и проверяйте нужное поле ответа |
| Медленное выполнение из-за `delay` | Слишком большая задержка между попытками | Настройте `delay` согласно SLA; для health-check используйте 5-10s |
| Дублирование элементов в цикле | `flatten` не применен к вложенному списку | Примените `flatten` перед `loop` |

### Диагностика

```bash
# Проверка доступности делегированного хоста
ansible -i inventories/prod load_balancer -m ping

# Проверка inventory после add_host
ansible-inventory -i inventories/prod --graph

# Проверка статуса асинхронной задачи
ansible -i inventories/prod all -m async_status -a "jid=<job_id>"
```

## Рекомендации

1. **Выбор между import и include**: используйте `import_*` для статической структуры, где логика не меняется между запусками. Используйте `include_*` когда нужно включать файлы по условию или с разными переменными.

2. **Делегирование**: `delegate_to` работает на уровне задачи. Если нужно делегировать все задачи плейбука — используйте `hosts: localhost`. Для делегирования между двумя удаленными хостами через bastion настройте `ForwardAgent yes`.

3. **Асинхронные операции**: используйте `async` + `poll: 0` для долгих задач (>10 минут). Всегда добавляйте проверку через `async_status` с `until`/`retries`/`delay`. Указывайте `run_once` при запуске на единственном хосте.

4. **Handlers**: `flush_handlers` используйте только когда нужно применить изменения немедленно (например, обновление конфигурации с последующим рестартом сервиса). По умолчанию handlers запускаются автоматически в конце плейбука.

5. **end_role**: используйте для досрочного завершения роли при обнаружении, что дальнейшие действия не нужны (например, ПО уже установлено). Не используйте `end_role` вне роли или в handlers — это вызовет ошибку.

6. **Группировка**: `group_by` изменяет inventory во время выполнения. Новые группы доступны только в последующих задачах, но не в текущем плейбуке автоматически. Для немедленного использования создавайте задачи с `delegate_to: localhost` или используйте `add_host` с параметром `groups`.

7. **Безопасность**: при работе с `add_host` проверяйте входные данные. Динамическое добавление хостов из внешних API требует валидации IP-адресов и ограничения групп до минимума необходимых.

8. **Совместимость**: `end_batch` требует Ansible 2.12+, `end_role` — 2.18+. При разработке плагинов или ролей для разных окружений проверяйте минимальную версию.

## Дополнительная информация

- **[Ansible Playbook Structure](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_reuse.html)** — документация по включениям.
- **[Ansible Delegation](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_delegation.html)** — документация по делегированию.
- **[Ansible Loops](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_loops.html)** — документация по циклам.
- **[Dynamic Inventory](https://docs.ansible.com/ansible/latest/inventory_guide/intro_dynamic_inventory.html)** — руководство по динамическому инвентарю.
- **[ansible.builtin.meta module](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/meta_module.html)** — полный справочник параметров `meta`.
