# Ansible — антипаттерны и плохие практики

## Определения

**Антипаттерн в Ansible** — это распространенный, но неэффективный, опасный или трудноподдерживаемый способ решения задачи автоматизации. Антипаттерны ведут к накоплению технического долга, нарушению идемпотентности, снижению безопасности системы и деградации производительности при масштабировании.

**Технический долг автоматизации** — состояние кодовой базы, при котором «быстрые» решения (например, использование `shell` вместо модуля) усложняют будущие изменения и увеличивают вероятность каскадных сбоев.

**Каскадный сбой (Cascade Failure)** — ситуация, при которой ошибка в одной задаче приводит к остановке всех последующих задач из-за отсутствия обработки ошибок или неправильного использования `ignore_errors`.

## Основные концепции

### 1. Нарушение идемпотентности и декларативности

*   **Императивное мышление:** Попытка описать *как* сделать (алгоритм) вместо того, *что* должно быть (состояние). Это превращает Ansible в «распределенный Bash», лишая его преимуществ проверки состояния.
*   **Скрытые изменения (Phantom Changes):** Задачи, возвращающие `changed: true` без реального изменения системы, или наоборот — `ok`, когда система была изменена «под капотом».
*   **Неконтролируемое накопление:** Отсутствие параметра `state: absent` для удаления старых конфигураций, пользователей или пакетов. Система «зарастает» мусором.
*   **Игнорирование `changed_when`:** Использование модулей `shell` или `command` без явного указания условия `changed_when`. Это делает отслеживание изменений невозможным.

### 2. Безопасность и управление доступом

*   **Глобальный Privilege Escalation:** Использование `become: true` на уровне плейбука или хоста без необходимости. Это расширяет поверхность атаки.
*   **Утечка секретов в логи:** Отсутствие директивы `no_log: true` при работе с паролями, токенами или сертификатами. Секреты попадают в stdout и отчеты CI/CD.
*   **Инъекции в логику (CVE-2023-5764):** Использование фигурных скобок `{{ }}` внутри условий `when`. Это не только избыточно, но и позволяет проводить атаки типа Jinja2 injection.
*   **Хранение секретов в group_vars/host_vars:** Размещение паролей и ключей в inventory-файлах, которые могут быть случайно закоммичены в Git.
*   **Использование `--ask-vault-pass` в CI/CD:** Передача пароля vault через интерактивный ввод или переменные окружения вместо переменных окружения vault или интеграции с HashiCorp Vault.

### 3. Производительность и масштабируемость

*   **Fact-Overhead:** Сбор фактов (`gather_facts`) на всех хостах, когда они нужны только для фильтрации в одном месте. На больших инвентарях это может занимать до 70% времени выполнения.
*   **Линейные циклы над тяжелыми модулями:** Выполнение `apt` или `yum` в цикле `loop` для 50 пакетов. Правильный подход — передача списка в один вызов модуля для атомарной работы пакетного менеджера.
*   **Отсутствие лимитов в `until`:** Бесконечные циклы ожидания без `retries` и `delay`, приводящие к зависанию пайплайнов.
*   **Избыточные `serial` и `throttle`:** Использование `serial: 1` для всех задач без необходимости или чрезмерное ограничение параллелизма через `throttle`, что замедляет выполнение без улучшения стабильности.
*   **Неконтролируемое кеширование facts:** Использование `cacheable: yes` в `set_fact` без продумывания TTL и управления кешем, что приводит к работе с устаревшими данными.

### 4. Сложность и поддержка (Maintainability)

*   **Жесткая связанность (Hardcoding):** Прописывание путей, имен пользователей и версий прямо в задачах вместо использования `defaults/main.yml`.
*   **God Roles:** Создание ролей, нарушающих принцип единственной ответственности (Single Responsibility Principle). Роль «webserver», которая также настраивает бэкапы, мониторинг и VPN.
*   **Игнорирование FQCN:** Использование коротких имен (`copy`, `template`). В современных версиях это замедляет поиск модуля и может привести к конфликтам имен при использовании нескольких коллекций.
*   **Глубокие зависимости ролей:** Когда одна роль зависит от другой, которая зависит от третьей, создавая цепочку, которую невозможно переиспользовать или тестировать изолированно.

## Практические сценарии

### Антипаттерны на уровне кода

#### 1. Злоупотребление командами оболочки

Попытка реализовать алгоритмическую логику через `ansible.builtin.shell` или `ansible.builtin.command` вместо использования встроенных декларативных модулей.

**Плохо (Императивный подход — сломает идемпотентность):**
```yaml
- name: Add setting if not exists
  ansible.builtin.shell: |
    if ! grep -q "Setting=true" /etc/app.conf; then
      echo "Setting=true" >> /etc/app.conf
    fi
```

**Хорошо (Декларативный подход):**
```yaml
- name: Ensure setting is present
  ansible.builtin.lineinfile:
    path: /etc/app.conf
    line: "Setting=true"
    state: present
```

#### 2. Инъекции в логику (CVE-2023-5764)

Использование `{{ }}` внутри `when` — избыточно и опасно.

**Плохо (Риск инъекции):**
```yaml
- name: Run task if variable is true
  ansible.builtin.debug:
    msg: "Hello"
  when: "{{ my_var | bool }}"
```

**Хорошо:**
```yaml
- name: Run task if variable is true
  ansible.builtin.debug:
    msg: "Hello"
  when: my_var | bool
```

#### 3. Неэффективные циклы в пакетных менеджерах

Выполнение модуля для каждого элемента вместо передачи всего списка.

**Плохо (Медленно — запускает apt 3 раза):**
```yaml
- name: Install packages
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  loop:
    - nginx
    - git
    - curl
```

**Хорошо (Быстро — запускает apt 1 раз со списком):**
```yaml
- name: Install packages
  ansible.builtin.apt:
    name:
      - nginx
      - git
      - curl
    state: present
```

#### 4. Использование `ignore_errors: true` для «мягкого» падения

Это скрывает реальные проблемы (например, нехватку диска) под видом «ожидаемого сбоя».

**Плохо:**
```yaml
- name: Try to copy config
  ansible.builtin.copy:
    src: config.conf
    dest: /etc/app/
  ignore_errors: true
```

**Хорошо (Использование блоков для логики исключений):**
```yaml
- name: Manage configuration
  block:
    - name: Copy config
      ansible.builtin.copy:
        src: config.conf
        dest: /etc/app/
  rescue:
    - name: Log failure or notify team
      ansible.builtin.debug:
        msg: "Config copy failed, using defaults"
```

#### 5. Неправильное использование `changed_when`

При использовании `shell` или `command` без `changed_changed` невозможно определить, было ли выполнено реальное изменение.

**Плохо:**
```yaml
- name: Check if service is running
  ansible.builtin.command: systemctl is-active nginx
  register: nginx_status
```

**Хорошо:**
```yaml
- name: Check if service is running
  ansible.builtin.command: systemctl is-active nginx
  register: nginx_status
  changed_when: false
  failed_when: nginx_status.rc not in [0, 3]
```

#### 6. Злоупотребление `delegate_to` для логики на контроллере

Использование `delegate_to: localhost` для выполнения операций, которые можно реализовать через action-плагин или `local_action`.

**Плохо:**
```yaml
- name: Get local timestamp
  ansible.builtin.command: date +%s
  delegate_to: localhost
  register: timestamp

- name: Set fact with timestamp
  ansible.builtin.set_fact:
    deploy_time: "{{ timestamp.stdout }}"
```

**Хорошо:**
```yaml
- name: Set deploy timestamp
  ansible.builtin.set_fact:
    deploy_time: "{{ ansible_date_time.epoch }}"
```

### Архитектурные ошибки

#### 1. Засорение `set_fact`

Использование `set_fact` для статических данных, которые не меняются во время выполнения. Это затрудняет отладку и переопределение.

**Рекомендация:** Используйте `vars`, `defaults/main.yml` или `group_vars`. `set_fact` предназначен только для данных, полученных динамически во время выполнения плейбука (например, вывод команды).

#### 2. Глобальный `become: true`

Установка повышения привилегий на уровне всего Playbook.

**Последствия:** Повышается риск случайного изменения системных файлов при выполнении «безопасных» задач (например, `debug` или `uri`).
**Рекомендация:** Указывайте `become: true` только для конкретных задач или блоков, требующих прав root.

#### 3. Неправильный приоритет переменных

Использование `group_vars` для данных, которые должны переопределяться для конкретного хоста, или `host_vars` для данных общих для группы.

**Приоритет переменных (от низшего к высшему):**
1. `defaults/main.yml` (роли)
2. `vars/main.yml` (роли)
3. `group_vars/all`
4. `group_vars/сгруппа`
5. `inventory`
6. `play vars`
7. `host_vars`
8. `set_fact`
9. `extra vars` (`-e`)

**Плохо:**
```yaml
# group_vars/web.yml — специфичные настройки для web-сервера
http_port: 8080
max_clients: 200
```

**Хорошо:**
```yaml
# group_vars/web.yml — общие настройки для всех web-серверов
ansible_http_port: 80

# host_vars/web01.yml — специфичные настройки для конкретного хоста
http_port: 8080
max_clients: 200
```

#### 4. Игнорирование `serial` при обновлении серверов

Обновление всех серверов одновременно вместо поэтапного (canary) подхода.

**Плохо:**
```yaml
- hosts: webservers
  tasks:
    - name: Update packages
      ansible.builtin.apt:
        upgrade: dist
        update_cache: yes
```

**Хорошо:**
```yaml
- hosts: webservers
  serial: 1  # Поэтапное обновление по одному серверу
  tasks:
    - name: Update packages
      ansible.builtin.apt:
        upgrade: dist
        update_cache: yes
    - name: Verify service
      ansible.builtin.uri:
        url: "http://localhost:{{ http_port }}/health"
        status_code: 200
      retries: 10
      delay: 5
```

#### 5. Неправильная обработка ошибок в блоках

Использование `block/rescue/always` без учёта вложенных исключений и ошибок.

**Плохо:**
```yaml
- block:
    - name: Dangerous operation
      ansible.builtin.shell: rm -rf /var/log/old/*
  rescue:
    - name: Ignore errors
      ansible.builtin.debug:
        msg: "Error occurred"
  always:
    - name: Continue anyway
      ansible.builtin.debug:
        msg: "Continuing"
```

**Хорошо:**
```yaml
- block:
    - name: Dangerous operation
      ansible.builtin.shell: rm -rf /var/log/old/*
      register: cleanup_result
      failed_when: cleanup_result.rc not in [0, 1]
  rescue:
    - name: Handle specific error
      ansible.builtin.debug:
        msg: "Cleanup failed: {{ cleanup_result.stderr }}"
    - name: Notify team
      ansible.builtin.uri:
        url: "{{ slack_webhook }}"
        method: POST
        body: '{"text": "Cleanup failed on {{ inventory_hostname }}"}'
        body_format: json
  always:
    - name: Verify disk space
      ansible.builtin.command: df -h /
      register: disk_free
```

### Антипаттерны управления тегами

#### 1. Теги для логики вместо категоризации

Использование тегов для управления порядком выполнения задач вместо структурирования плейбука.

**Плохо:**
```yaml
- name: Task 1
  ansible.builtin.debug:
    msg: "First"
  tags: always

- name: Task 2
  ansible.builtin.debug:
    msg: "Second"
  tags: always
```

**Хорошо:**
```yaml
- name: Installation tasks
  block:
    - name: Install packages
      ansible.builtin.apt:
        name: nginx
  tags:
    - install

- name: Configuration tasks
  block:
    - name: Configure nginx
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
  tags:
    - config
```

#### 2. Пропуск критических задач через `--skip-tags`

Использование `--skip-tags` для пропуска задач, которые должны выполняться всегда.

**Плохо:**
```yaml
- name: Security hardening
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    line: "PermitRootLogin no"
  tags:
    - security
```

**Хорошо:**
```yaml
- name: Security hardening
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    line: "PermitRootLogin no"
  tags:
    - always  # Эта задача должна выполняться всегда
```

### Антипаттерны работы с хендлерами

#### 1. Хендлеры без `notify`

Определение хендлеров без использования `notify` в задачах.

**Плохо:**
```yaml
- name: Restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
  # Нет notify — хендлер никогда не сработает
```

**Хорошо:**
```yaml
- name: Update nginx config
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: Restart nginx

- name: Restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
  listen: "restart web services"  # Альтернативный способ через listen
```

#### 2. Использование `meta: flush_handlers` без необходимости

Принудительная очистка хендлеров в середине плейбука, что приводит к избыточным перезапускам.

**Плохо:**
```yaml
- name: Configure nginx
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: Restart nginx

- meta: flush_handlers  # Принудительный перезапуск — часто избыточен

- name: Deploy application
  ansible.builtin.copy:
    src: app/
    dest: /var/www/html/
```

**Хорошо:**
```yaml
- name: Configure nginx
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: Restart nginx

- name: Deploy application
  ansible.builtin.copy:
    src: app/
    dest: /var/www/html/
  # Хендлер сработает автоматически в конце play
```

### Антипаттерны работы с переменными

#### 1. Использование `include_vars` для статических данных

Загрузка статических переменных из файлов во время выполнения вместо использования `vars_files` или `defaults`.

**Плохо:**
```yaml
- name: Load static variables
  ansible.builtin.include_vars:
    file: static_config.yml
```

**Хорошо:**
```yaml
- name: Load static variables
  hosts: all
  vars_files:
    - static_config.yml
```

#### 2. Некорректное использование `{{ }}` в `set_fact`

Лишний рендеринг переменных, которые уже являются строками.

**Плохо:**
```yaml
- name: Set fact
  ansible.builtin.set_fact:
    my_var: "{{ some_var }}"
```

**Хорошо:**
```yaml
- name: Set fact
  ansible.builtin.set_fact:
    my_var: "{{ some_var }}"  # Только если нужен рендеринг шаблона
    # Или без скобок, если передача строки:
    my_var: "{{ some_var }}"
```

### Антипаттерны асинхронного выполнения

#### 1. Использование `async` без проверки статуса

Запуск асинхронных задач без `poll` или проверки `async_status`.

**Плохо:**
```yaml
- name: Long running task
  ansible.builtin.command: /opt/long_task.sh
  async: 3600
  poll: 0
  # Задача запущена, но результат не проверяется
```

**Хорошо:**
```yaml
- name: Long running task
  ansible.builtin.command: /opt/long_task.sh
  async: 3600
  poll: 0
  register: long_task

- name: Wait for task to complete
  ansible.builtin.async_status:
    jid: "{{ long_task.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
```

#### 2. Чрезмерное использование `poll: 0`

Запуск множества асинхронных задач без ограничения параллелизма.

**Плохо:**
```yaml
- name: Run multiple tasks
  ansible.builtin.command: "/opt/task_{{ item }}.sh"
  loop: "{{ range(0, 100) | list }}"
  async: 3600
  poll: 0
  # 100 задач запущены одновременно — перегрузка сети
```

**Хорошо:**
```yaml
- name: Run tasks with throttling
  ansible.builtin.command: "/opt/task_{{ item }}.sh"
  loop: "{{ range(0, 100) | list }}"
  async: 3600
  poll: 5
  throttle: 10  # Максимум 10 параллельных задач
```

## Инструменты контроля качества

### Статический анализ с `ansible-lint`

`ansible-lint` — обязательный инструмент для выявления антипаттернов в CI/CD.

| Правило | Описание | Почему это важно |
| :--- | :--- | :--- |
| `fqcn` | Требование полных имен модулей | Исключает конфликты между коллекциями. |
| `no-changed-when` | Отсутствие `changed_when` в `shell` | Обеспечивает корректность отчетов об изменениях. |
| `command-instead-of-module` | Использование shell вместо модуля | Повышает надежность и идемпотентность. |
| `no-handler` | Запуск сервиса без хендлера | Предотвращает лишние перезапуски служб. |
| `var-naming` | Некорректные имена переменных | Улучшает читаемость и предотвращает переопределения. |
| `yaml[truthy]` | Использование `yes/no` вместо `true/false` | Единообразие стиля и читаемость. |
| `name[template]` | Использование шаблонов в именах задач | Затрудняет поиск задач и чтение логов. |
| `no-free-form` | Свободная форма команд в `shell`/`command` | Улучшает безопасность и читаемость. |
| `schema` | Нарушение схемы плейбука | Предотвращает синтаксические ошибки. |
| `args[module]` | Некорректные аргументы модуля | Выявляет опечатки и неизвестные параметры. |
| `yaml[comments]` | Отсутствие пробела после `#` в комментариях | Стандартизация форматирования. |
| `no-same-owner` | Использование `owner` без необходимости | Предотвращает нежелательные изменения владельца файлов. |

### Ручная проверка (Code Review)

При проверке чужого кода всегда задавайте вопросы:
1. Будет ли этот код работать корректно при втором запуске? (Идемпотентность)
2. Что произойдет, если выполнение прервется посередине? (Транзакционность)
3. Не попадут ли секреты в логи CI/CD? (`no_log`)
4. Есть ли обработка ошибок для критических задач? (block/rescue)
5. Используются ли FQCN для всех модулей?
6. Правильно ли настроен приоритет переменных?

### Автоматизация проверок

```bash
# Проверка синтаксиса плейбука
ansible-playbook playbook.yml --syntax-check

# Проверка с ansible-lint
ansible-lint playbook.yml

# Проверка конкретного правила
ansible-lint -R rules/ playbook.yml

# Проверка ролей
ansible-lint roles/my_role/

# Проверка в CI/CD (GitHub Actions)
# - uses: ansible/ansible-lint-action@main
#   with:
#     playbook: playbook.yml
```

## Типовые ошибки и их решение (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `changed: true` без реальных изменений | Отсутствие `changed_when` | Добавьте `changed_when: false` или условие проверки |
| `fatal: ... UNREACHABLE!` | Проблемы с SSH-доступом | Проверьте inventory, SSH-ключи и настройки `ansible.cfg` |
| `Permission denied` | Нехватка `become: true` | Добавьте `become: true` только для нужных задач |
| `Jinja2 undefined error` | Переменная не определена | Проверьте приоритет переменных и их наличие в inventory |
| `Module failed` | Ошибка в аргументах модуля | Проверьте синтаксис YAML и типы данных аргументов |
| `No variable found` | Неправильное имя переменной | Используйте `ansible.builtin.debug` для отладки |
| `Handler not triggered` | Отсутствие `notify` | Убедитесь, что задача имеет `notify: Handler Name` |
| `Infinite loop in until` | Отсутствие `retries` и `delay` | Добавьте `retries: N` и `delay: M` в цикл `until` |

## Дополнительная информация

### Смотрите также

- [Основные концепции Ansible](./ansible_core_concepts.md) — фундаментальные принципы: идемпотентность и push-модель.
- [Безопасность в Ansible](./ansible_security_best_practices.md) — управление пользователями, sudo и Ansible Vault.
- [Тестирование с Molecule](./ansible_testing_with_molecule.md) — проверка инфраструктурного кода в изолированных средах.
