# Основные концепции Ansible

## Определения

- **Декларативность (Declarative Approach)** — основной подход Ansible, при котором описывается *желаемое состояние* системы (например, «пакет Nginx должен быть установлен»), а движок сам определяет необходимые действия для достижения этого состояния, учитывая текущий статус. См. подробнее: **[Декларативное управление](../../Concepts/configuration_management_models.md)**.
- **Идемпотентность (Idempotency)** — фундаментальный принцип, гарантирующий, что повторное выполнение операции не изменит систему, если она уже находится в целевом состоянии. Это позволяет безопасно запускать автоматизацию неограниченное количество раз без риска побочных эффектов. Большинство стандартных модулей Ansible идемпотентны по своей природе. См. глубокую теорию: **[Идемпотентность](../../Concepts/idempotency.md)**.
- **Узел управления (Control Node)** — машина, на которой установлен Ansible и с которой запускаются команды. Требует Unix-подобную ОС (Linux, macOS, WSL2) и установленный интерпретатор Python. Подробнее: [Введение в Ansible](./ansible_introduction.md).
- **Управляемые узлы (Managed Nodes)** — целевые серверы и сетевые устройства, которыми управляет Ansible. Для большинства модулей на Linux требуется Python, на Windows — PowerShell. Подробнее: [Введение в Ansible](./ansible_introduction.md).
- **FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource` (например, `ansible.builtin.copy`, `community.general.docker_image`). Использование FQCN является обязательным стандартом в современном Ansible (с версии 2.10) для предотвращения конфликтов имен и обеспечения предсказуемости выполнения кода.
- **Факты (Facts)** — системные переменные, автоматически собираемые модулем `ansible.builtin.setup` перед выполнением задач (IP-адреса, ОС, архитектура CPU, смонтированные диски). Доступны через словарь `ansible_facts`. Факты кэшируются между запусками — см. раздел [Кэширование фактов](#кэширование-фактов) ниже.
- **Магические переменные (Magic Variables)** — зарезервированные внутренние переменные Ansible, значения которых вычисляются движком автоматически и не могут быть переопределены пользователем. Ключевые: `inventory_hostname`, `group_names`, `hostvars`, `ansible_facts`, `play_hosts`, `groups`.
- **set_fact** — модуль, создающий или переопределяющий переменные во время выполнения плейбука. Значения сохраняются на уровне хоста и доступны во всех последующих задачах текущего плея. Имеют приоритет выше role vars и play vars.
- **delegate_facts** — механизм, позволяющий собранные факты хоста сохранить у делегированного хоста (например, балансировщика) вместо целевого. Используется совместно с `delegate_to`.
- **no_log** — директива, предотвращающая запись чувствительных данных (пароли, токены, ключи) в лог Ansible. При `no_log: true` ни stdout, ни stderr задачи не попадают в вывод. Критично для безопасности.
- **Become** — механизм повышения привилегий, позволяющий выполнять задачи от имени другого пользователя (обычно `root`) через `sudo`, `su`, `pbrun` или другие методы. Настраивается через директивы `become: true`, `become_method`, `become_user`.
- **Плагин подключения (Connection Plugin)** — низкоуровневый компонент, реализующий способ связи с узлом. Стандартные: `ssh` (по умолчанию для Linux), `local` (выполнение на Control Node), `docker`, `winrm`, `psrp`, `network_cli`.

**SRE/DevOps-контекст:**
- **MTTR (Mean Time To Repair/Recovery)** — среднее время восстановления после сбоя. Идемпотентность и обработка ошибок в Ansible напрямую снижают MTTR за счет предсказуемости поведения и быстрого rollback.
- **Configuration Drift** — расхождение между фактическим состоянием инфраструктуры и декларативным описанием в Ansible. Приводит к "зоопарку" конфигураций и увеличению MTTR.
- **Change Failure Rate** — процент изменений, приведших к сбою. Хорошо структурированные плейбуки с обработкой ошибок и canary-подходом снижают этот показатель.
- **Blast Radius** — масштаб последствий при сбое автоматизации. Ограничение `serial`, `throttle` и `max_fail_percentage` сужают радиус поражения.

## Архитектура и модели взаимодействия

### Влияние антипаттернов на операционную деятельность (SRE/DevOps)

Антипаттерны Ansible напрямую влияют на ключевые операционные метрики:

- **Увеличение MTTR:** Непредсказуемое поведение плейбуков, отсутствие обработки ошибок и неидемпотентность усложняют диагностику и восстановление после инцидентов.
- **Потеря наблюдаемости (Observability):** Отсутствие `changed_when`, скрытые изменения и неструктурированные логи не позволяют коррелировать изменения Ansible с инцидентами мониторинга.
- **Снижение пропускной способности изменений (Change Capacity):** Каскадные сбои и необходимость ручного вмешательства замедляют деплои и увеличивают риск batch-изменений.
- **Нарушение SLA/SLO:** Непредсказуемое время выполнения, отсутствие throttling и контроля параллелизма приводят к превышению временных рамок обслуживания.
- **Compliance-риски:** Отсутствие аудита изменений, неконтролируемый `become` и хранение секретов в Git нарушают требования SOC2, PCI-DSS, HIPAA и внутренние политики безопасности.

### Модели Push и Pull

- **Push-модель (Стандартная):** Управляющий узел (**Control Node**) инициирует соединение с хостами по протоколу **SSH** (Linux/Unix) или **WinRM/PSRP** (Windows). Это исключает необходимость установки тяжелых агентов на целевые системы (Agentless). Преимущества: централизованный контроль, мгновенное применение изменений, отсутствие дополнительного ПО на managed nodes.
- **Pull-модель:** Альтернативный режим, при котором хосты самостоятельно запрашивают конфигурацию из центрального репозитория через [Ansible Pull](./ansible_pull.md). Удобно для инфраструктур с динамическим масштабированием и нестабильным подключением. Каждый хост периодически (через cron/timer) клонирует Git-репозиторий и применяет плейбук `local.yml`.

### Ad-hoc команды (Императивный режим)

**Ad-hoc команды** — это быстрые одноразовые задачи, выполняемые в терминале напрямую без написания плейбука. Они оптимальны для первичной проверки связи, сбора данных или массового выполнения простых команд.

*Синтаксис:*
```bash
ansible <pattern> -m <module> -a "<arguments>"
```

*Примеры:*
```bash
# Проверка доступности всех хостов
ansible all -m ansible.builtin.ping
# → web1.example.com | SUCCESS => { "ping": "pong" }
# → db1.example.com | SUCCESS => { "ping": "pong" }

# Сбор фактов о хостах группы webservers
ansible webservers -m ansible.builtin.setup -a "filter=ansible_distribution*"
# → web1.example.com | SUCCESS => { "ansible_facts": { "ansible_distribution": "Ubuntu" } }

# Установка пакета на все хосты
ansible webservers -m ansible.builtin.apt -a "name=nginx state=present" --become

# Копирование файла
ansible all -m ansible.builtin.copy -a "src=/etc/hosts dest=/tmp/hosts mode=0644"

# Запуск произвольной команды
ansible dbservers -m ansible.builtin.command -a "systemctl status postgresql"

# Перезапуск сервиса
ansible webservers -m ansible.builtin.service -a "name=nginx state=restarted" --become

# Просмотр переменных хоста
ansible-inventory --host web1.example.com
# → { "ansible_host": "10.0.0.1", "http_port": 80 }

# Просмотр всей структуры инвентаря
ansible-inventory --list --yaml
```

### Конфигурация Ansible (ansible.cfg)

Ansible ищет файл конфигурации в строгом порядке приоритета и использует **первый найденный**:

1.  **Переменная `ANSIBLE_CONFIG`** — путь к конкретному файлу.
2.  **`ansible.cfg` в текущем рабочем каталоге** — рекомендуемый подход (Project-level).
3.  **`~/.ansible.cfg`** — настройки пользователя (User-level).
4.  **`/etc/ansible/ansible.cfg`** — системный конфиг по умолчанию (System-level).

**Ключевые разделы:**
```ini
[defaults]
inventory = ./inventory.ini
roles_path = ./roles:/etc/ansible/roles
remote_user = deploy
host_key_checking = False
forks = 10
timeout = 30
gathering = smart
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
pipelining = True
control_path = /tmp/ansible-%%h-%%r
retries = 3
ssh_args = -o ControlMaster=auto -o ControlPersist=60s

[inventory]
enable_plugins = host_list, script, yaml, ini, auto
```

## Ключевые компоненты

### Инвентарь (Inventory)

Инвентарь — это список управляемых узлов, сгруппированных по назначению (например, `web`, `db`).

- **Статический инвентарь:** Файлы в форматах **YAML** или **INI**. Позволяют жестко прописывать IP-адреса, порты и групповые переменные.

**Пример INI-инвентаря:**
```ini
[webservers]
web1.example.com ansible_host=10.0.0.1
web2.example.com ansible_host=10.0.0.2

[dbservers]
db1.example.com ansible_host=10.0.1.1 http_port=5432

[production:children]
webservers
dbservers

[all:vars]
ansible_user=deploy
ansible_python_interpreter=/usr/bin/python3
```

**Пример YAML-инвентаря:**
```yaml
all:
  children:
    webservers:
      hosts:
        web1.example.com:
          ansible_host: 10.0.0.1
        web2.example.com:
          ansible_host: 10.0.0.2
      vars:
        http_port: 80
    dbservers:
      hosts:
        db1.example.com:
          ansible_host: 10.0.1.1
    production:
      children:
        webservers:
        dbservers:
  vars:
    ansible_user: deploy
```

- **Динамический инвентарь:** Плагины, получающие список хостов из внешних систем (NetBox, Foreman, Consul, Proxmox). Современный стандарт требует использования **Inventory Plugins** вместо устаревших скриптов. См. [Динамический инвентарь](./dynamic_inventory.md).

**SRE-контекст:** Инвентарь — это источник истины для управления конфигурациями. Грязный инвентарь (устаревшие хосты, неактуальные переменные) — частая причина инцидентов. Регулярный аудит инвентаря, группировка по назначению (`production`, `staging`, `emergency`) и явное указание owner/service позволяют быстро локализовать проблему при инциденте.

**Управление инвентарем из CLI:**
```bash
# Просмотр всех хостов
ansible-inventory --list

# Просмотр графа групп
ansible-inventory --graph

# Просмотр переменных конкретного хоста
ansible-inventory --host web1.example.com

# Просмотр переменных группы
ansible-inventory --list | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['_meta']['hostvars']['web1.example.com'], indent=2))"
```

### Переменные и области видимости (Variable Scopes)

Переменные позволяют параметризовать конфигурации. Ansible поддерживает сложную систему приоритетов (**22 уровня**), где переменные командной строки (`extra vars`) имеют наивысший приоритет.

**Основные области видимости (от низшего к высшему):**
1.  **Role defaults** — значения по умолчанию в `roles/x/defaults/main.yml`.
2.  **Inventory vars (group)** — переменные группы в `group_vars/all.yml`.
3.  **Inventory vars (host)** — переменные хоста в `host_vars/host1.yml`.
4.  **Play** — переменные, определенные в самом плейбуке через `vars:`.
5.  **Role vars** — переменные роли в `roles/x/vars/main.yml`.
6.  **Include vars** — загруженные через `include_vars` в задаче.
7.  **Set facts / registered** — переменные, созданные через `set_fact` или `register`.
8.  **Extra vars** — переменные из CLI (`-e "var=value"`). **Абсолютный приоритет.**

> **Правило:** `extra_vars` (уровень 10) имеют наивысший приоритет и переопределяют всё остальное.

Подробнее: [Переменные и факты](./PlaybookStructure/variables.md).

### Плейбуки (Playbooks)

Плейбук — это YAML-файл, описывающий сценарии автоматизации. Он состоит из «плеев» (**Plays**), которые связывают группы хостов из инвентаря с набором задач. Задачи выполняются последовательно сверху вниз.

**Минимальный плейбук:**
```yaml
---
- name: Обновление и настройка серверов
  hosts: webservers
  become: true
  gather_facts: true
  tasks:
    - name: Установка Nginx
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: true
      notify: Restart Nginx

    - name: Копирование конфигурации
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        owner: root
        group: root
        mode: '0644'
      notify: Restart Nginx

    - name: Убедиться, что Nginx запущен
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true

  handlers:
    - name: Restart Nginx
      ansible.builtin.service:
        name: nginx
        state: restarted
```

Подробнее: [Выполнение плейбуков](./ansible_playbook_execution.md), [Структура плейбуков](./PlaybookStructure/basics.md).

### Модули и плагины

Современный Ansible (2.10+) требует использовать полное имя ресурса (**FQCN**), например: `ansible.builtin.copy` вместо `copy`. Это предотвращает конфликты имен между коллекциями. Подробнее см. **[Обзор модулей](./Modules/ansible_modules_overview.md)**.

| Критерий | Модули (Modules) | Плагины (Plugins) |
| :--- | :--- | :--- |
| **Место исполнения** | **Управляемый хост** (копируются и запускаются) | **Контрольный узел** (выполняются внутри процесса Ansible) |
| **Жизненный цикл** | Краткосрочный (удаляются после выполнения задачи) | Постоянный (загружены на время работы процесса) |
| **Назначение** | Изменение состояния системы (декларативность) | Расширение внутренней логики (связь, фильтры, парсинг). См. **[Action-плагины](./ansible-action-plugins.md)**. |

> **Примечание:** Модули для сетевого оборудования (Cisco, Juniper) обычно выполняются на **контрольном узле** через API, используя плагины связи `local` или `network_cli`. См. [Сетевая автоматизация](./ansible_network_automation.md).

**Классификация плагинов по месту исполнения:**
- **На Control Node:** Connection, Lookup, Filter, Callback, Inventory, Strategy, Shell.
- **На Managed Node:** Module (копируются и выполняются удалённо).

#### Типы плагинов
* **Connection:** Протоколы связи с хостами (`ssh`, `local`, `docker`, `winrm`, `psrp`, `network_cli`).
* **Lookup:** Получение данных из внешних источников (файлы, переменные окружения, Vault, DNS) прямо на Control Node.
* **Filter:** Преобразование данных внутри шаблонов Jinja2.
* **Callback:** Перехват событий Ansible для логирования или уведомлений. Подробнее: **[Разработка Callback-плагинов](./ansible-callback-plugins.md)**.
* **Inventory:** Плагины для динамического формирования списка хостов.
* **Strategy:** Алгоритмы распределения задач между хостами (`linear`, `free`, `host_pinned`).
* **Shell:** Оболочки для выполнения команд на managed nodes (`sh`, `powershell`, `cmd`).

### Роли и коллекции

- **Роли (Roles):** Метод организации задач, переменных, файлов и шаблонов в независимые блоки для их многократного переиспользования. Роль фокусируется на конкретном сервисе (например, MySQL). См. [Ansible: Роли](./ansible_roles.md).
- **Коллекции (Collections):** Современный стандарт упаковки и распространения контента. Коллекция может включать в себя множество ролей, модулей и плагинов. См. [Ansible Galaxy](./Roles/galaxy.md).

- **Event-Driven Ansible (EDA):** Движок реактивной автоматизации (`ansible-rulebook`), позволяющий обрабатывать события и выполнять действия. См. **[Event-Driven Ansible (EDA)](./event-driven-ansible.md)**.

### Обработчики (Handlers)

Задачи, выполняемые только при получении уведомления (`notify`) от задачи, статус которой изменился (`changed`).

**Ключевые особенности:**
- **Дедупликация:** Выполняются ровно один раз в самом конце плея в порядке их определения в файле обработчиков, независимо от того, сколько задач отправили им уведомление.
- **Условные обработчики:** Можно ограничить выполнение через `when`.
- **Принудительное выполнение:** `--force-handlers` выполняет обработчики даже при ошибке плейбука.

**Пример:**
```yaml
---
- name: Настройка Nginx
  hosts: webservers
  become: true
  tasks:
    - name: Копирование конфигурации
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
      notify: Reload Nginx

    - name: Проверка синтаксиса конфига
      ansible.builtin.command: nginx -t
      register: nginx_test
      changed_when: false

    - name: Перезапуск только при успехе
      ansible.builtin.service:
        name: nginx
        state: restarted
      when: nginx_test.rc == 0

  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
      when: nginx_test.rc == 0
```

Подробнее: [Основы структуры плейбуков](./PlaybookStructure/basics.md).

### Сбор фактов (Facts)

Автоматический сбор системных переменных перед выполнением задач. Реализуется модулем `ansible.builtin.setup`.

**Управление сбором фактов:**
```yaml
---
- name: Примеры управления фактами
  hosts: all
  gather_facts: true          # Включить сбор (по умолчанию true)
  gather_subset: '!all,min'   # Только базовые факты
  gather_timeout: 15          # Таймаут сбора (секунды)
  tasks:
    - name: Показать распределение ОС
      ansible.builtin.debug:
        var: ansible_facts['ansible_distribution']

    - name: Показать все IP-адреса хоста
      ansible.builtin.debug:
        var: ansible_facts['ansible_all_ipv4_addresses']

    - name: Показать размер оперативной памяти
      ansible.builtin.debug:
        msg: "RAM: {{ ansible_facts['ansible_memtotal_mb'] }} MB"
```

### Кэширование фактов

Для ускорения повторных запусков факты можно сохранять во внешнее хранилище:
```ini
# ansible.cfg
[defaults]
gathering = smart
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400  # 24 часа
```

Подробнее: [Переменные и факты](./PlaybookStructure/variables.md).

### Шаблонизация (Jinja2)

Использование шаблонов для создания динамических конфигураций на основе переменных и логики Python.

**Пример шаблона nginx.conf.j2:**
```jinja2
worker_processes {{ ansible_facts['processor']['cores'] }};

events {
    worker_connections {{ nginx_worker_connections | default(1024) }};
}

http {
    server {
        listen {{ http_port | default(80) }};
        server_name {{ server_name }};

        {% if ssl_enabled | default(false) %}
        listen 443 ssl;
        ssl_certificate /etc/ssl/{{ server_name }}.crt;
        {% endif %}
    }
}
```

Подробнее: [Ansible: Jinja2](./ansible_jinja_templating.md).

### Стратегии выполнения (Strategies)

Определяют, как Ansible распределяет задачи между хостами:

| Стратегия | Поведение | Когда использовать |
| :--- | :--- | :--- |
| **Linear** (по умолчанию) | Все хосты завершают текущую задачу, прежде чем группа перейдет к следующей | Большинство сценариев; предсказуемый порядок |
| **Free** | Каждый хост проходит плейбук максимально быстро и независимо | Когда хосты выполняют разные по времени задачи |
| **Serial** | Хосты обрабатываются пачками (например, по 2 или по 10%) | Rolling Updates, поэтапное развертывание |
| **Host Pinned** | Хост остается в текущем слоте до завершения своего сценария | Большие кластеры, контроль параллелизма |

**Пример использования стратегий:**
```yaml
---
# Serial: поэтапное развертывание (25% хостов за раз)
- name: Rolling Update Nginx
  hosts: webservers
  serial: "25%"
  max_fail_percentage: 10
  strategy: linear
  tasks:
    - name: Обновление пакетов
      ansible.builtin.apt:
        name: nginx
        state: latest
        update_cache: true

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: nginx
        state: restarted

    - name: Проверка здоровья
      ansible.builtin.uri:
        url: "http://localhost:{{ http_port | default(80) }}/health"
        status_code: 200
      retries: 5
      delay: 5
```

Подробнее: [Директивы управления выполнением](./PlaybookStructure/basics.md#директивы-управления-выполнением).

### Среды выполнения (Execution Environments)

Современный подход (рекомендован с Ansible 2.11+), использующий OCI-совместимые контейнеры для изоляции зависимостей. Гарантирует, что плейбук будет выполнен с одинаковыми версиями коллекций и Python-библиотек на любой машине.

**Пример:**
```bash
# Запуск через ansible-navigator
ansible-navigator run site.yml -i inventory.ini --mode stdout

# Просмотр доступных EE
ansible-navigator images list

# Сборка кастомного EE
ansible-builder build -t my-custom-ee:latest
```

*   **[Ansible Execution Environments — подробное руководство](./ansible-execution-environments.md)**.
*   **ansible-builder:** Инструмент для сборки образов EE.
*   **ansible-navigator:** Интерфейс для запуска и отладки автоматизации в EE.


## Практические сценарии

### Полный плейбук: развёртывание и настройка приложения

Комплексный пример, демонстрирующий взаимодействие всех ключевых компонентов:

```yaml
---
- name: Развёртывание Web-приложения
  hosts: webservers
  become: true
  gather_facts: true
  vars:
    app_name: myapp
    app_port: 8080
    app_user: deploy
    deploy_dir: /opt/{{ app_name }}
    nginx_worker_processes: "{{ ansible_facts['processor']['cores'] }}"

  tasks:
    # --- Подготовка системы ---
    - name: Создание пользователя приложения
      ansible.builtin.user:
        name: "{{ app_user }}"
        system: true
        shell: /bin/false
        home: "{{ deploy_dir }}"
        create_home: false

    - name: Установка системных зависимостей
      ansible.builtin.apt:
        name:
          - python3
          - python3-pip
          - nginx
          - git
        state: present
        update_cache: true
      tags: [system]

    # --- Развёртывание кода ---
    - name: Создание директории деплоя
      ansible.builtin.file:
        path: "{{ deploy_dir }}"
        state: directory
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0755'
      tags: [deploy]

    - name: Клонирование репозитория
      ansible.builtin.git:
        repo: "https://github.com/example/{{ app_name }}.git"
        dest: "{{ deploy_dir }}"
        version: "{{ app_version | default('main') }}"
      become_user: "{{ app_user }}"
      register: git_result
      notify: Restart App
      tags: [deploy]

    - name: Установка Python-зависимостей
      ansible.builtin.pip:
        requirements: "{{ deploy_dir }}/requirements.txt"
        virtualenv: "{{ deploy_dir }}/venv"
        virtualenv_command: python3 -m venv
      become_user: "{{ app_user }}"
      when: git_result.changed
      tags: [deploy]

    # --- Конфигурация ---
    - name: Генерация конфигурации приложения
      ansible.builtin.template:
        src: app_config.j2
        dest: "{{ deploy_dir }}/config.yml"
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0640'
      notify: Restart App
      tags: [config]

    - name: Генерация systemd-юнита
      ansible.builtin.template:
        src: app.service.j2
        dest: /etc/systemd/system/{{ app_name }}.service
        mode: '0644'
      notify:
        - Reload Systemd
        - Restart App
      tags: [config]

    # --- Nginx ---
    - name: Генерация конфигурации Nginx
      ansible.builtin.template:
        src: nginx_app.j2
        dest: /etc/nginx/sites-available/{{ app_name }}
        mode: '0644'
      notify: Reload Nginx
      tags: [nginx]

    - name: Активация сайта Nginx
      ansible.builtin.file:
        src: /etc/nginx/sites-available/{{ app_name }}
        dest: /etc/nginx/sites-enabled/{{ app_name }}
        state: link
      notify: Reload Nginx
      tags: [nginx]

    - name: Удаление дефолтного сайта
      ansible.builtin.file:
        path: /etc/nginx/sites-enabled/default
        state: absent
      notify: Reload Nginx
      tags: [nginx]

    # --- Финализация ---
    - name: Запуск и автозапуск приложения
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: started
        enabled: true
      tags: [service]

    - name: Проверка доступности приложения
      ansible.builtin.uri:
        url: "http://localhost:{{ app_port }}/health"
        status_code: 200
      register: health_check
      retries: 10
      delay: 5
      until: health_check.status == 200
      tags: [verify]

  handlers:
    - name: Reload Systemd
      ansible.builtin.systemd:
        daemon_reload: true

    - name: Restart App
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: restarted

    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

**Запуск и проверка:**
```bash
# Синтаксис и проверка
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml --check --diff

# Запуск с тегами (только конфигурация)
ansible-playbook site.yml --tags config

# Запуск с extra-vars
ansible-playbook site.yml -e "app_version=2.1.0"

# Запуск с ограничением по хостам
ansible-playbook site.yml --limit "web1.example.com"
```

### Производственные сценарии (SRE/DevOps)

#### Canary-деплой с автоматическим health-check

Ограничиваем радиус поражения при сбое, разворачивая изменения на небольшом проценте хостов:

```yaml
---
- name: Canary deployment Nginx
  hosts: webservers
  serial: "10%"
  max_fail_percentage: 5
  gather_facts: true
  tasks:
    - name: Deploy new config
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
      notify: Reload Nginx
      tags: [canary, deploy]

    - name: Health check after deploy
      ansible.builtin.uri:
        url: "http://localhost:{{ http_port | default(80) }}/health"
        status_code: 200
        timeout: 10
      register: health
      retries: 10
      delay: 5
      until: health.status == 200
      tags: [canary, verify]

    - name: Rollback on health check failure
      ansible.builtin.service:
        name: nginx
        state: restarted
      when: health.status != 200
      tags: [canary, rollback]
```

#### Configuration drift как операционный инцидент

Drift — не просто техническое отклонение, а инцидент, требующий MTTR-подхода:

```yaml
---
- name: Incident response: configuration drift
  hosts: all
  become: true
  serial: "50"
  gather_facts: false
  tasks:
    - name: Create incident ticket (local log)
      ansible.builtin.copy:
        content: |
          INCIDENT: Configuration drift detected on {{ inventory_hostname }}
          Severity: P1
          Owner: ops-team
          Timestamp: {{ ansible_date_time.iso8601 }}
        dest: "/var/log/incidents/drift_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0640"
      delegate_to: localhost

    - name: Backup current state
      ansible.builtin.archive:
        path:
          - /etc/nginx/nginx.conf
          - /etc/ssh/sshd_config
        dest: "/var/backups/pre_remediation_{{ inventory_hostname }}_{{ ansible_date_time.iso8601 | regex_replace(':','') }}.tar.gz"
        format: gz

    - name: Apply baseline (remediation)
      ansible.builtin.include_role:
        name: baseline_config

    - name: Verify remediation
      ansible.builtin.command:
        cmd: "ansible-playbook site.yml --check --limit {{ inventory_hostname }}"
      register: verify
      delegate_to: localhost
      changed_when: false
```

#### Снижение MTTR: откатный сценарий (rollback)

Каждый production-плейбук должен иметь откатный сценарий. Подробные примеры и стратегии: **[Стратегии отката (rollback) в Ansible](../examples/ansible_rollback_strategies.md)**.

```

### Анализ изменений (Check & Diff)

Безопасное тестирование автоматизации:
- **Check Mode (`--check`):** «Сухой запуск». Ansible проверяет, какие изменения были бы внесены, не меняя состояние системы.
- **Diff Mode (`--diff`):** Показывает разницу (diff) в текстовых файлах конфигурации в формате unified diff (аналогично `git diff`): строки с `-` — удалены, строки с `+` — добавлены.

> **Важное ограничение:** Check Mode — это сильный сигнал, но не строгая гарантия. Поддержка зависит от модуля: декларативные модули (`file`, `template`, `apt`) корректно сравнивают состояние, а модули `command` и `shell` по умолчанию пропускаются в `--check`. Для принудительного выполнения команд в check mode используйте `check_mode: false`. Результат реального применения может отличаться от предсказания.

```bash
# Полная проверка перед продакшеном
ansible-playbook -i inventories/prod site.yml --check --diff --limit webservers

# Проверка конкретной задачи
ansible-playbook site.yml --check --diff --start-at-task "Копирование конфигурации"
```

### Обнаружение дрейфа конфигурации (Drift)

**Configuration drift** — отклонение реального состояния сервера от описанного в коде (IaC). Ansible автоматически обнаруживает и исправляет дрейф при каждом запуске благодаря механизму идемпотентности. Если система уже соответствует коду, задача вернет статус `ok`.

#### Простое обнаружение дрейфа

```bash
# Проверка текущего состояния без изменений
ansible-playbook site.yml --check --diff 2>&1 | tee drift_report_$(date +%Y%m%d).log

# Анализ: задачи со статусом changed = потенциальный дрейф
grep "changed:" drift_report_20240115.log
```

#### Массовое обнаружение дрейфа на 500+ серверах

```yaml
---
- name: Configuration drift detection
  hosts: all
  become: true
  serial: "100"  # 100 хостов за раз для контроля нагрузки
  gather_facts: false
  tasks:
    - name: Check critical file states
      ansible.builtin.stat:
        path: "{{ item }}"
      register: file_states
      loop:
        - /etc/nginx/nginx.conf
        - /etc/ssh/sshd_config
        - /etc/security/pwquality.conf
        - /etc/sysctl.conf

    - name: Compare with expected checksums
      ansible.builtin.fail:
        msg: >-
          DRIFT DETECTED on {{ inventory_hostname }}:
          {{ item.item }} expected={{ item.stat.checksum }}
          but current state differs. Run remediation playbook.
      loop: "{{ file_states.results }}"
      when: >
        expected_checksums[item.item] is defined and
        item.stat.checksum != expected_checksums[item.item]
      vars:
        expected_checksums:
          /etc/nginx/nginx.conf: "abc123..."
          /etc/ssh/sshd_config: "def456..."

    - name: Generate drift report
      ansible.builtin.copy:
        content: |
          Host: {{ inventory_hostname }}
          Timestamp: {{ ansible_date_time.iso8601 }}
          {% for item in file_states.results %}
          {{ item.item }}: {{ item.stat.checksum }}
          {% endfor %}
        dest: "/var/log/drift_report_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0644"
      when: file_states.results | selectattr('changed') | list | length > 0
```

#### Централизованный сбор отчётов о дрейфе

```yaml
---
- name: Collect drift reports from all hosts
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Gather drift reports
      ansible.builtin.find:
        paths: /var/log
        patterns: "drift_report_*.log"
      delegate_to: "{{ item }}"
      register: report_files
      loop: "{{ groups['all'] }}"
      ignore_errors: true

    - name: Aggregate drift data
      ansible.builtin.set_fact:
        drifted_hosts: >-
          {% set drifted = [] %}
          {% for host in groups['all'] %}
          {% if hostvars[host].drift_report is defined and
                'DRIFT' in hostvars[host].drift_report %}
          {% set drifted = drifted + [host] %}
          {% endif %}
          {% endfor %}
          {{ drifted }}

    - name: Send drift alert
      ansible.builtin.copy:
        content: |
          DRIFT ALERT: Configuration drift detected on {{ drifted_hosts | length }} hosts
          Hosts: {{ drifted_hosts | join(', ') }}
          Timestamp: {{ ansible_date_time.iso8601 }}
        dest: "/var/log/drift_alert_{{ ansible_date_time.date }}.log"
        mode: "0644"
      when: drifted_hosts | length > 0
      delegate_to: localhost

    - name: Send drift notification (local mail)
      ansible.builtin.shell: |
        echo "Configuration drift detected on {{ drifted_hosts | length }} hosts" | \
        mail -s "DRIFT ALERT" ops-team@localhost
      when: drifted_hosts | length > 0
      delegate_to: localhost

    - name: Trigger remediation if drift detected
      ansible.builtin.include_tasks: remediate_drift.yml
      when: drifted_hosts | length > 0
```

#### Автоматическая коррекция (remediation)

```yaml
---
- name: Automated drift remediation
  hosts: drifted
  become: true
  serial: "10%"  # Катомное исправление
  tasks:
    - name: Backup current configs before remediation
      ansible.builtin.archive:
        path:
          - /etc/nginx/nginx.conf
          - /etc/ssh/sshd_config
        dest: "/root/pre_remediation_backup_{{ ansible_date_time.iso8601 }}.tar.gz"
        format: gz

    - name: Apply desired state
      ansible.builtin.include_role:
        name: baseline_config

    - name: Verify remediation
      ansible.builtin.command:
        cmd: "ansible-playbook site.yml --check --limit {{ inventory_hostname }}"
      register: verify_result
      delegate_to: localhost
      changed_when: false

    - name: Report remediation status
      ansible.builtin.copy:
        content: |
          REMEDIATION REPORT: Drift remediated on {{ inventory_hostname }}
          Status: {{ verify_result.rc == 0 }}
          Timestamp: {{ ansible_date_time.iso8601 }}
        dest: "/var/log/drift_remediation_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0644"
      delegate_to: localhost

    - name: Send remediation notification (local mail)
      ansible.builtin.shell: |
        echo "Drift remediated on {{ inventory_hostname }}: {{ verify_result.rc == 0 }}" | \
        mail -s "REMEDIATION REPORT" ops-team@localhost
      delegate_to: localhost
```

### Начальная загрузка хостов (Bootstrapping)

Если на Linux-хосте отсутствует Python, стандартные модули не сработают. В этом случае используется модуль **`ansible.builtin.raw`**, который выполняет команды напрямую через SSH.

```yaml
---
- name: Play 1 - Bootstrap Python
  hosts: all
  become: true
  gather_facts: false
  tasks:
    - name: Install Python3
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      changed_when: false

    - name: Verify Python
      ansible.builtin.raw: python3 --version
      register: python_check
      changed_when: false

    - name: Show Python version
      ansible.builtin.debug:
        var: python_check.stdout_lines

- name: Play 2 - Main Configuration
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Verify connection
      ansible.builtin.ping: {}
      # → "ping": "pong"
```

**Bootstrapping для разных ОС:**
```yaml
# CentOS/RHEL
- name: Install Python3 (CentOS)
  ansible.builtin.raw: yum install -y python3
  when: ansible_facts['os_family'] == "RedHat"

# Alpine Linux
- name: Install Python3 (Alpine)
  ansible.builtin.raw: apk add python3
  when: ansible_facts['distribution'] == "Alpine"

# Amazon Linux
- name: Install Python3 (Amazon Linux)
  ansible.builtin.raw: yum install -y python3
  when: ansible_facts['distribution'] == "Amazon"
```

### Использование переменных в реальном плейбуке

Демонстрация различных способов определения и использования переменных:

```yaml
---
- name: Демонстрация переменных
  hosts: webservers
  become: true

  # Переменные плейбука
  vars:
    http_port: 80
    max_clients: 200
    app_env: production

  # Переменные из файла
  vars_files:
    - "vars/{{ ansible_facts['distribution'] | lower }}.yml"

  tasks:
    # Доступ к переменным через {{ }}
    - name: Показать конфигурацию
      ansible.builtin.debug:
        msg: >
          Порт: {{ http_port }},
          Макс. клиентов: {{ max_clients }},
          Окружение: {{ app_env }},
          ОС: {{ ansible_facts['distribution'] }}

    # Регистрация результата задачи
    - name: Получить информацию о системе
      ansible.builtin.setup:
        filter: ansible_memtotal_mb
      register: mem_result

    - name: Показать память
      ansible.builtin.debug:
        var: mem_result.ansible_facts.ansible_memtotal_mb

    # Динамическое создание переменных (set_fact)
    - name: Установить вычисляемую переменную
      ansible.builtin.set_fact:
        recommended_workers: "{{ (ansible_facts['processor']['cores'] * 2) | int }}"
        cacheable: true  # Сохранить в fact cache

    - name: Показать рекомендованное значение
      ansible.builtin.debug:
        msg: "Рекомендуемое число воркеров: {{ recommended_workers }}"

    # Условная логика на основе переменных
    - name: Настройка для production
      ansible.builtin.lineinfile:
        path: /etc/app/config
        regexp: '^LOG_LEVEL='
        line: 'LOG_LEVEL=warning'
      when: app_env == "production"

    - name: Настройка для development
      ansible.builtin.lineinfile:
        path: /etc/app/config
        regexp: '^LOG_LEVEL='
        line: 'LOG_LEVEL=debug'
      when: app_env == "development"

    # Цикл (loop)
    - name: Создание пользователей
      ansible.builtin.user:
        name: "{{ item.name }}"
        groups: "{{ item.groups | join(',') }}"
        state: present
      loop:
        - { name: "alice", groups: ["admin", "developers"] }
        - { name: "bob", groups: ["developers"] }
        - { name: "charlie", groups: ["audit"] }

    # Цикл с until (повтор до успеха)
    - name: Ожидание доступности сервиса
      ansible.builtin.uri:
        url: "http://localhost:{{ http_port }}/health"
        status_code: 200
      register: result
      until: result.status == 200
      retries: 5
      delay: 10
```

### Стратегии выполнения: сравнение

**Linear (по умолчанию):**
```yaml
---
- name: Linear Strategy
  hosts: webservers
  strategy: linear
  serial: 1  # По одному хосту
  tasks:
    - name: Долгая задача
      ansible.builtin.command: /opt/scripts/long_task.sh
    - name: Быстрая задача
      ansible.builtin.ping:
# Результат: Один хост выполняет обе задачи, затем следующий
# web1: long_task → ping
# web2: long_task → ping (после web1)
```

**Free:**
```yaml
---
- name: Free Strategy
  hosts: webservers
  strategy: free
  tasks:
    - name: Долгая задача
      ansible.builtin.command: /opt/scripts/long_task.sh
    - name: Быстрая задача
      ansible.builtin.ping:
# Результат: Каждый хост движется максимально быстро
# web1: long_task → ping
# web2: ping → long_task (если ping выполнился быстрее)
```

**Serial (Rolling Update):**
```yaml
---
- name: Rolling Update
  hosts: webservers
  serial: "30%"  # 30% хостов за раз
  max_fail_percentage: 10  # Допустимо до 10% ошибок
  tasks:
    - name: Обновление пакетов
      ansible.builtin.apt:
        name: "*"
        state: latest
        update_cache: true
      register: update_result

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: nginx
        state: restarted

    - name: Проверка здоровья
      ansible.builtin.uri:
        url: http://localhost/health
        status_code: 200
      retries: 10
      delay: 5
# Результат: 30% → проверка → следующие 30% → ...
```

### Идемпотентность: глубокий анализ

**Определение идемпотентности:** Повторное выполнение операции не изменяет систему, если она уже находится в целевом состоянии. Это фундаментальный принцип Ansible, гарантирующий безопасность повторных запусков.

#### Модули, которые всегда идемпотентны

| Модуль | Поведение | Пример |
| :--- | :--- | :--- |
| `ansible.builtin.apt` | Устанавливает только отсутствующие пакеты | `state: present` |
| `ansible.builtin.yum` | Аналогично apt для RHEL/CentOS | `state: installed` |
| `ansible.builtin.service` | Запускает/останавливает только при необходимости | `state: started` |
| `ansible.builtin.user` | Создаёт пользователя только если его нет | `state: present` |
| `ansible.builtin.file` | Создаёт файл/директорию если отсутствует | `state: directory` |
| `ansible.builtin.copy` | Копирует файл если отличается от целевого | `force: false` |

#### Модули, которые НЕ идемпотентны

| Модуль | Проблема | Решение |
| :--- | :--- | :--- |
| `ansible.builtin.command` | Всегда возвращает `changed` | Используйте `creates`/`removes` или `changed_when` |
| `ansible.builtin.shell` | Аналогично command | `creates`, `removes`, `changed_when` |
| `ansible.builtin.raw` | Выполняется всегда | `changed_when: false` если команда идемпотентна |
| `ansible.builtin.script` | Скрипт выполняется каждый раз | `creates: /path/to/output` |

#### Пример: shell модуль с creates для идемпотентности

```yaml
# НЕидемпотентно: команда выполнится каждый раз
- name: Установка пакета из tar.gz
  ansible.builtin.shell: |
    tar xzf /tmp/app.tar.gz -C /opt/
    make install
  become: true

# Идемпотентно: команда выполнится только если нет /opt/app/bin/app
- name: Установка пакета из tar.gz
  ansible.builtin.shell: |
    tar xzf /tmp/app.tar.gz -C /opt/
    make install
  args:
    creates: /opt/app/bin/app
  become: true
```

#### changed_when и failed_when: ручная настройка идемпотентности

```yaml
#.changed_when: определяем когда задача считается изменившей систему
- name: Проверка версии пакета
  ansible.builtin.command: dpkg -l nginx
  register: dpkg_result
  changed_when: "'ii  nginx' not in dpkg_result.stdout"
  failed_when: false

# failed_when: определяем условия ошибки
- name: Проверка сервиса
  ansible.builtin.command: systemctl is-active nginx
  register: status
  changed_when: false
  failed_when: "'active' not in status.stdout"

# Комбинация: скрипт создаёт файл только при обновлении
- name: Обновление конфигурации
  ansible.builtin.shell: /opt/scripts/update_config.sh
  register: update_result
  changed_when: "'CONFIG UPDATED' in update_result.stdout"
  failed_when: "'ERROR' in update_result.stderr"
```

> **Важно:** `changed_when` и `failed_when` влияют только на **отчётность** (статус задачи в выводе), но не отменяют фактическое выполнение команды. Действие модуля уже произошло; эти директивы лишь определяют, как Ansible интерпретирует результат. Для настоящей идемпотентности необходимо использовать специализированные модули или параметры `creates`/`removes`.

#### Edge cases: когда идемпотентность ломается

1. **Внешние зависимости:** Задача зависит от внешней системы (API, БД), которая изменилась между запусками
2. **Race conditions:** Параллельные запуски плейбука на одних и тех же хостах
3. **Временные метки:** Задачи, использующие текущее время (`date +%s`)
4. **Случайные данные:** Генерация паролей, токенов, ключей
5. **Глобальное состояние:** Задачи, влияющие на общие ресурсы (DNS, балансировщики)

**Пример проблемы:**
```yaml
# Проблема: если запустить дважды — создаются дубликаты
- name: Добавление записи в файл
  ansible.builtin.lineinfile:
    path: /etc/hosts
    line: "192.168.1.100 new-host"

# Решение: использовать lineinfile с regexp
- name: Добавление записи в файл (идемпотентно)
  ansible.builtin.lineinfile:
    path: /etc/hosts
    regexp: '^192\.168\.1\.100'
    line: "192.168.1.100 new-host"
```

#### Тестирование идемпотентности

**ansible-playbook --check:**
```bash
# Dry-run: покажет какие изменения были бы сделаны
ansible-playbook site.yml --check
# Если все задачи ok — плейбук идемпотентен
```

**Molecule idempotence test:**
```yaml
# molecule/default/molecule.yml
provisioner:
  name: ansible
verifier:
  name: ansible
scenario:
  name: default
  test_sequence:
    - dependency
    - cleanup
    - destroy
    - syntax
    - create
    - prepare
    - converge
    - idempotence  # Запуск второй раз — ожидаем 0 changed
    - verify
    - cleanup
    - destroy
```

**Пример проверки идемпотентности:**
```bash
# Запуск playbook и проверка отсутствия changed
ansible-playbook site.yml --check --diff 2>&1 | grep -c "changed:"
# → 0 (все ok — идемпотентно)

# Или через molecule
molecule idempotence
```

### Типичные ошибки и их решение (Troubleshooting)

#### 1. «Unhandled error / Undefined variable»

**Причина:** Обращение к переменной, которая не определена.

**Диагностика:**
```bash
# Просмотр переменных хоста
ansible-inventory --host web1.example.com

# Просмотр переменных с фильтром
ansible web1 -m debug -a "var=hostvars['web1.example.com']"
```

**Решение:** Используйте `| default()` для переменных, которые могут отсутствовать:
```yaml
{{ my_var | default('fallback_value') }}
```

#### 2. «Failed to connect to the host via ssh»

**Причины и решение:**
```bash
# Проверка SSH-подключения
ssh deploy@web1.example.com -o ConnectTimeout=5

# Проверка ключей
ansible all -m ping -vvv  # Детальный вывод

# Отключение проверки ключей (для отладки)
ansible all -m ping -e "ansible_host_key_checking=False"
```

#### 3. «The module xyz was not found in the module_utils»

**Причина:** Модуль не найден или не установлен.

**Решение:**
```bash
# Проверка доступных модулей
ansible-doc -l | grep <имя_модуля>

# Установка коллекции
ansible-galaxy collection install <namespace.collection>

# Проверка путей поиска
ansible --version  # → configured module search path
```

#### 4. «Permission denied» / «Missing sudo password»

**Решение:**
```bash
# Запрос пароля sudo
ansible-playbook site.yml --ask-become-pass

# Или через переменную
ansible-playbook site.yml -K  # → Become password: ___
```

#### 5. «Timeout» при длительных операциях

**Решение:**
```yaml
# Увеличение таймаута для SSH
# ansible.cfg
[ssh_connection]
timeout = 60

# Или на уровне задачи
- name: Длительная операция
  ansible.builtin.command: /opt/scripts/migration.sh
  async: 3600    # Макс. время выполнения (секунды)
  poll: 0        # Не ждать завершения (fire and forget)
  register: migration_job

- name: Ожидание завершения
  ansible.builtin.async_status:
    jid: "{{ migration_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
```

#### 6. «PLAY RECAP показывает unreachable»

**Диагностика:**
```bash
# Проверка SSH-конфигурации
ansible all -m ping -vvvv  # Максимальная детализация

# Проверка inventory
ansible-inventory --list --yaml

# Проверка доступности хостов
ping -c 3 web1.example.com
```

#### 7. «Drift detected on rerun»

**Причина:** Неидемпотентные задачи, ручные изменения на хостах.

**Диагностика:**
```bash
# Проверка дрейфа
ansible-playbook site.yml --check --diff 2>&1 | grep "changed:"

# Аудит фактов
ansible -m setup -i inventory.ini all | grep -E "ansible_|gather_subset"
```

**Решение:** Добавьте `changed_when`, используйте декларативные модули, настройте periodic remediation.

#### 8. «Callback plugin error»

**Причина:** Несовместимость версий `ansible-core` и плагинов.

**Решение:**
```bash
# Проверка версий
ansible --version
pip show ansible-core

# Обновление плагинов
pip install --upgrade ansible
```

#### 9. «Control Node OOM / Memory error»

**Причина:** Большой инвентарь, неоптимальные `forks`, утечки памяти в плагинах.

**Диагностика:**
```bash
# Проверка использования памяти
ps aux | grep ansible
free -m
vmstat 1 10

# Уменьшение параллелизма
# ansible.cfg
[defaults]
forks = 5
```

**Решение:** Уменьшите `forks`, используйте fact caching, обновите `ansible-core`.

### Диагностические команды (SRE)

```bash
# Проверка синтаксиса плейбука
ansible-playbook playbook.yml --syntax-check

# Проверка идемпотентности (без применения изменений)
ansible-playbook playbook.yml --check --diff

# Поиск секретов в репозитории (pre-commit hook)
gitleaks detect --source=. --report-path=gitleaks-report.json

# Аудит переменных на наличие секретов
ansible-playbook playbook.yml --list-tasks | grep -i password

# Проверка доступных фактов
ansible -m setup -i inventory.ini all | grep -E "ansible_|gather_subset"

# Валидация всех плейбуков в репозитории
find playbooks/ -name '*.yml' -exec ansible-lint {} +

# Проверка версий коллекций
ansible-galaxy collection list

# Дифференциальный анализ drift
ansible-playbook site.yml --check --diff 2>&1 | tee drift_report_$(date +%Y%m%d).log
grep "changed:" drift_report_*.log

# Проверка callback-плагинов
ansible-doc -t callback -l
```

### Лучшие практики (Best Practices)

#### Идемпотентность по умолчанию

- Все модули должны возвращать корректный `changed` статус.
- Избегайте `shell`/`command` без `changed_when` и `failed_when`.
- Используйте `check_mode: yes` для модулей, поддерживающих проверку без применения изменений.

#### Безопасность (Shift-Left Security)

- `no_log: true` для всех задач с секретами (токены, пароли, ключи).
- `become: true` на уровне задачи, а не playbook.
- Секреты только через Ansible Vault или внешние менеджеры (HashiCorp Vault, CyberArk).
- Никогда не коммитьте файлы vault, `group_vars` с секретами, `.vault_pass`.

#### Производительность и масштабирование

- `gather_facts: false` на уровне play, если факты не нужны, или `gather_subset` для выборочного сбора.
- Передавайте списки в модули пакетных менеджеров, избегайте `loop` для атомарных операций.
- Используйте `serial` и `throttle` для контролируемого rollout и защиты целевых систем.
- Асинхронные задачи только с контролем статуса (`async_status` + `until`).

#### Наблюдаемость (Observability)

- Единый callback-плагин (например, `yaml`, `json`, или `community.general.counter`) для структурированных логов.
- Корреляция `run_id`/`playbook_name` с инцидентами мониторинга.
- Включение `diff: true` для файловых операций в не production окружениях.
- Регулярный аудит inventory на устаревшие хосты и неиспользуемые переменные.

#### Управление изменениями (Change Management)

- Каждый плейбук должен иметь откатный сценарий (rollback playbook).
- Изменения применяются через canary-подход с автоматическим health-check.
- Проблемные изменения автоматически откатываются при падении SLO-показателей.
- Документация изменений в playbook-заголовке (описание, ссылка на тикет, author, дата).

#### Версионирование и Supply Chain

- Коллекции зафиксированы в `requirements.yml` с хешами.
- Используйте `ansible-galaxy collection install -r requirements.yml --force-with-deps` для воспроизводимости.
- Проверяйте GPG-подписи коллекций (`--keyring`).
- Шаблоны (Jinja2) валидируются через `ansible-lint` и `ansible-playbook --syntax-check`.

### Контрольный список: лучшие практики

- [ ] Используйте FQCN для всех модулей (`ansible.builtin.apt` вместо `apt`)
- [ ] Включайте `gather_facts: false` если факты не используются (ускорение)
- [ ] Используйте `--check --diff` перед применением в production
- [ ] Добавляйте `tags` для возможности частичного запуска плейбуков
- [ ] Используйте `notify` + handlers вместо прямых перезапусков
- [ ] Не храните пароли в plain text — используйте [Ansible Vault](./Vault/basics.md)
- [ ] Тестируйте плейбуки через [Molecule](./ansible_testing_with_molecule.md)
- [ ] Используйте `no_log: true` для чувствительных задач
- [ ] Проверяйте `max_fail_percentage` при rolling updates
- [ ] Кэшируйте факты для ускорения повторных запусков

## Дополнительная информация

- [Безопасность в Ansible](./ansible_security_best_practices.md) — защита данных и vault.
- [Антипаттерны Ansible](./ansible_bad_practices.md) — типичные ошибки и их решение.
- [Выполнение плейбуков](./ansible_playbook_execution.md) — подробнее о режимах запуска.
