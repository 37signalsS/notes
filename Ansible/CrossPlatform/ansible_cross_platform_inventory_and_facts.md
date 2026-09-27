# Кроссплатформенный инвентарь и факты: динамические источники, группы и кэширование

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21.4+ | 2.22.0b1 доступен (сентябрь 2026) |
| **Python** (control node) | 3.11+ | 3.12–3.14 | Для ansible-core 2.21; 2.22 поддерживает 3.13–3.15 |
| **Python** (managed node, POSIX) | 3.9+ | 3.12+ | Для ansible-core 2.21 |
| **PowerShell** (Windows) | 5.1+ | 7.6 LTS | 7.6 LTS — стандарт для 2.21/2.22 (поддержка до Nov 2028) |
| **OpenSSH** | 8.0+ | Актуальная LTS | 10.5 — актуальный релиз (август 2026) |
| **PyWinRM** | 0.4.0+ | 0.5.0+ | Для WinRM транспорта к Windows |
| **ansible.posix** | 1.5+ | Актуальная | Для POSIX-специфичных модулей |
| **ansible.windows** | 2.5+ | Актуальная | Для Windows-модулей |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible-inventory -i inventories/hosts.yml --graph
# → @all:
#     ├── @ungrouped:
#     └── webservers:
#         ├── web01
#         └── web02

ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*" | head -20
# → "ansible_facts": {"os_family": "RedHat"} ...
```

## Определения

- **Инвентарь (Inventory)** — список хостов и групп хостов. Может быть статическим (INI/YAML) или динамическим (плагины, скрипты).
- **Inventory plugin** — нативный способ получения динамического инвентаря из внешних систем (NetBox, Consul, Foreman, Proxmox). Предпочтительнее устаревших скриптов.
- **Constructed plugin** — встроенный плагин, создающий переменные и группы на основе Jinja2-выражений. Особенно полезен для кроссплатформенной группировки.
- **Host pattern** — синтаксис выбора подмножества хостов: `webservers`, `webservers[1:5]`, `all:!db`, `webservers:&production`.
- **Fact caching** — механизм сохранения фактов хостов во внешнее хранилище (jsonfile, Redis, memcached) для ускорения повторных запусков.
- **`gather_facts`** — сбор фактов через модуль `ansible.builtin.setup`. По умолчанию `true` в начале каждого плея.
- **`gather_subset`** — ограничение объема собираемых фактов для ускорения на гетерогенных парках.
- **`delegate_facts`** — привязка фактов, собранных в делегированной задаче, к целевому хосту вместо делегированного.
- **`group_by`** — динамическое создание групп хостов на основе фактов или переменных.
- **`hostvars`** — магическая переменная, предоставляющая доступ к фактам и переменным всех хостов инвентаря.
- **Cache plugin** — механизм кэширования инвентаря, предотвращающий повторные запросы к внешним API при каждом запуске.

## Основные концепции

### Статический vs динамический инвентарь в mixed-парках

Статический инвентарь (INI/YAML) подходит для небольших сред. Для кроссплатформенных парков с динамическим масштабированием предпочтительны inventory plugins.

| Тип | Формат | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| Статический (INI/YAML) | `hosts.ini`, `hosts.yml` | Простота, версионирование | Ручное обновление при изменении инфраструктуры |
| Inventory plugin (NetBox, Consul) | YAML-конфиг плагина | Актуальные данные из CMDB, автоматическая группировка | Требует настроенного API/доступа |
| Constructed plugin | YAML + Jinja2 | Гибкая группировка без изменения исходного инвентаря | Ограничен выражением Jinja2 |
| Скрытый (script) | Python/Shell скрипт | Максимальная гибкость | Устарел, требует поддержки |

```yaml
# Статический инвентарь с OS-группами (hosts.yml)
all:
  hosts:
    web01.example.com:
      ansible_host: 192.168.1.10
      ansible_python_interpreter: /usr/bin/python3
    web02.example.com:
      ansible_host: 192.168.1.11
      ansible_python_interpreter: /usr/bin/python3
    win01.example.com:
      ansible_host: 192.168.1.20
      ansible_connection: winrm
      ansible_winrm_transport: ntlm
  children:
    linux:
      hosts:
        web01.example.com:
        web02.example.com:
    windows:
      hosts:
        win01.example.com:
    webservers:
      hosts:
        web01.example.com:
        web02.example.com:
```

> **Production note:** Для кроссплатформенных парков используйте `group_by` в конфигурации плагина для автоматического создания OS-групп (`os_Debian`, `os_RedHat`, `os_Windows`). Включайте кэширование инвентаря (`cache: true`, `cache_plugin: jsonfile`), чтобы не дергать API при каждом запуске. Вектор запроса к NetBox/Consul должен фильтровать только активные хосты (`status: active`).

### Fact caching: jsonfile, Redis, memcached

Сбор фактов (`gather_facts`) — одна из самых долгих операций на больших парках. Fact caching ускоряет повторные запуски на 30–50%.

```ini
# ansible.cfg — локальный кэш (jsonfile)
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400  # 24 часа
```

```ini
# ansible.cfg — Redis (для distributed control node)
[defaults]
fact_caching = redis
fact_caching_connection = redis://redis.internal:6379/0
fact_caching_timeout = 86400
```

```ini
# ansible.cfg — memcached
[defaults]
fact_caching = memcached
fact_caching_connection = localhost:11211
fact_caching_timeout = 86400
```

**Приоритет источников фактов:**
1. Факты, собранные в текущем запуске (`gather_facts: true`)
2. Fact cache (если не устарел)
3. `set_fact` / `include_vars`
4. Inventory-переменные
5. `defaults/` роли

```yaml
# Ограничение сбора фактов для ускорения
- name: Сбор только необходимых фактов
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - '!min'
      - distribution
      - os_family
      - pkg_mgr
      - service_mgr
      - architecture
  delegate_to: "{{ item }}"
  delegate_facts: true
  loop: "{{ groups['all'] }}"
  run_once: true
```

> **Production note:** На mixed-парках используйте раздельные каталоги кэша для разных окружений (`/tmp/ansible_cache/prod`, `/tmp/ansible_cache/dev`), чтобы факты из prod не попали в dev. Для Windows-хостов факты кэшируются так же, как для POSIX, но набор фактов меньше (нет сетевых/аппаратных фактов в том же объеме). Векторизованные факты (`cacheable: true` в `set_fact`) попадают в кэш — не кэшируйте секреты.

### Делегирование фактов (`delegate_facts`)

По умолчанию факты, собранные в делегированной задаче, привязываются к делегированному хосту. `delegate_facts: true` меняет это поведение.

```yaml
# Сбор фактов с балансировщика и привязка к целевому хосту
- name: Сбор фактов с HAProxy
  ansible.builtin.setup:
    gather_subset: '!all,min,distribution'
  delegate_to: "{{ groups['load_balancers'][0] }}"
  delegate_facts: true
  when: ansible_facts['os_family'] == 'Debian'

# Без delegate_facts факты останутся у балансировщика
- name: Проверка фактов
  ansible.builtin.debug:
    var: ansible_facts['os_family']
  # Будет факт целевого хоста, а не балансировщика
```

> **Production note:** `delegate_facts: true` полезно, когда нужно собрать факты с одного репрезентативного хоста и применить их ко всему парку (например, версия ОС с первого хоста группы). Модули, не создающие факты (`slurp`, `uri`, `command`), не требуют `delegate_facts` — им достаточно `register`.

### Magic variables для кроссплатформенной логики

| Переменная | Назначение | Пример |
| :--- | :--- | :--- |
| `groups` | Словарь всех групп и хостов | `{{ groups['webservers'] }}` |
| `hostvars` | Факты и переменные всех хостов | `{{ hostvars['web01']['ansible_host'] }}` |
| `inventory_hostname` | Имя текущего хоста в инвентаре | `{{ inventory_hostname }}` |
| `ansible_check_mode` | `true` если плейбук запущен с `--check` | `when: not ansible_check_mode` |
| `ansible_facts` | Словарь собранных фактов | `{{ ansible_facts['os_family'] }}` |
| `group_names` | Список групп текущего хоста | `{{ group_names }}` |

```yaml
# Выбор первого хоста в группе (кроссплатформенно)
- name: Получение адреса балансировщика
  ansible.builtin.set_fact:
    lb_address: "{{ hostvars[groups['load_balancers'][0]]['ansible_host'] }}"
  run_once: true

# Проверка фактов соседнего хоста
- name: Проверка версии ОС на первом веб-сервере
  ansible.builtin.debug:
    msg: "Первый веб-сервер: {{ hostvars[groups['webservers'][0]]['ansible_facts']['distribution'] }}"
  run_once: true
```

## Практические сценарии

### Сценарий 1: Fact caching для ускорения больших парков

```ini
# ansible.cfg — раздельный кэш для prod и dev
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_cache/{{ lookup('env', 'ANSIBLE_ENV') | default('dev') }}
fact_caching_timeout = 86400
```

```yaml
# Ограниченный сбор фактов
- name: Быстрый сбор фактов
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - distribution
      - os_family
      - pkg_mgr
      - service_mgr
  when: not ansible_check_mode
```

### Сценарий 2: Группировка через `group_by` в mixed-парке

```yaml
- name: Группировка по ОС
  ansible.builtin.group_by:
    key: "os_{{ ansible_facts['os_family'] }}"

- name: Группировка по архитектуре
  ansible.builtin.group_by:
    key: "arch_{{ ansible_facts['architecture'] }}"

- name: Группировка по менеджеру сервисов
  ansible.builtin.group_by:
    key: "svc_{{ ansible_facts['service_mgr'] }}"

# Отдельные плеи для каждой группы
- hosts: os_Debian
  tasks:
    - name: Деплой на Debian
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present

- hosts: os_RedHat
  tasks:
    - name: Деплой на RedHat
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present

- hosts: os_Windows
  tasks:
    - name: Деплой на Windows
      ansible.windows.win_package:
        path: "{{ pkg_installer_path }}"
        state: present
```

### Сценарий 3: Делегирование фактов с репрезентативного хоста

```yaml
- name: Сбор фактов с первого Linux-хоста
  ansible.builtin.setup:
    gather_subset: '!all,min,distribution'
  delegate_to: "{{ groups['os_Linux'][0] }}"
  delegate_facts: true
  run_once: true

- name: Использование фактов на всех Linux-хостах
  ansible.builtin.debug:
    msg: "Версия ОС: {{ ansible_facts['distribution_version'] }}"
  when: ansible_facts['system'] != 'Win32NT'
```

### Сценарий 4: Host patterns для mixed-парков

```bash
# Dry-run только на канареечном Windows-хосте
ansible-playbook site.yml --check --diff --limit "windows:canary"

# Деплой на все, кроме staging
ansible-playbook site.yml --limit "production:!staging"

# Диагностика: только Debian-хосты с проблемами
ansible-playbook site.yml --limit os_Debian --tags diagnose
```

### Сценарий 5: Аудит и snapshot переменных (SRE)

Фиксация состояния переменных и фактов для аудита изменений конфигурации.

```yaml
- name: Сбор всех переменных хоста
  ansible.builtin.setup:
  register: full_facts

- name: Сохранение snapshot в файл
  ansible.builtin.copy:
    content: "{{ full_facts.ansible_facts | to_nice_json }}"
    dest: "/var/tmp/audit/{{ inventory_hostname }}_facts_{{ ansible_date_time.date }}.json"
  delegate_to: localhost
  run_once: true
```

```yaml
- name: Загрузка эталонных переменных
  ansible.builtin.include_vars:
    file: "baseline_{{ env }}.yml"
    name: baseline

- name: Сравнение с эталоном
  ansible.builtin.assert:
    that:
      - ansible_facts['distribution'] == baseline.expected_distribution
      - ansible_facts['distribution_major_version'] | int == baseline.expected_version
    fail_msg: "Дрейф конфигурации: ожидается {{ baseline.expected_distribution }} {{ baseline.expected_version }}, найдено {{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_major_version'] }}"
```

### Сценарий 6: Валидация инвентаря перед деплоем

```bash
# Визуализация групп
ansible-inventory --graph

# Проверка конкретного хоста
ansible-inventory -i inventories/production.yml --host web01.example.com

# Валидация синтаксиса инвентаря
ansible-playbook site.yml -i inventories/production.yml --syntax-check
```

### Сценарий 7: Динамический инвентарь с OS-фильтрацией

Подробные конфигурации NetBox, Consul, Foreman и других плагинов см. в [Динамический инвентарь в Ansible](../dynamic_inventory.md).

```yaml
# inventories/constructed.yml — OS-группы без изменения исходного инвентаря
plugin: constructed
strict: false
groups:
  os_debian: "ansible_facts['os_family'] == 'Debian'"
  os_redhat: "ansible_facts['os_family'] == 'RedHat'"
  os_windows: "ansible_facts['os_family'] == 'Windows'"
  systemd_hosts: "ansible_facts['service_mgr'] == 'systemd'"
compose:
  ansible_connection: >-
    {{ 'winrm' if ansible_facts['os_family'] == 'Windows'
       else 'ssh' }}
```

```bash
# Комбинирование статического и constructed инвентаря
ansible-playbook site.yml -i inventories/hosts.yml -i inventories/constructed.yml --limit os_Debian
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible-inventory --graph --vars` | Граф групп и переменных | Дерево групп с переменными |
| `ansible-inventory -i netbox.yml --list` | Полный инвентарь в JSON | Полный список хостов и групп |
| `ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*"` | Просмотр фактов ОС | `"ansible_facts": { "os_family": "Debian" }` |
| `ansible all -m ansible.builtin.setup -a "gather_subset=!all,min,distribution"` | Быстрый сбор фактов | Перечень хостов с минимальными фактами |
| `ansible all -m ping --limit webservers` | Проверка связи на подмножестве | `pong` от выбранных хостов |
| `ansible-doc -t inventory netbox.netbox.nb_inventory` | Документация плагина | Список параметров плагина |
| `ansible-config dump | grep fact_caching` | Проверка кэширования фактов | Текущие параметры кэша |
| `ansible-playbook site.yml --list-variables -l web01` | Переменные хоста | Полный словарь переменных и фактов |
| `ansible-inventory -i inventories/production.yml --host web01` | Переменные хоста из инвентаря | `ansible_host`, `ansible_connection`, факты |

## Диагностика и устранение неполадок

### Инвентарь и группы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Хост не найден в `--limit` | Неточный host pattern или группа не существует | `ansible-inventory --graph` | Проверьте точное имя группы/хоста |
| `group_by` не создает группу | `group_by` выполняется после применения `--limit` | Проверьте порядок плеев | Выполняйте группировку в отдельном плее или используйте `meta: refresh_inventory` |
| Динамический инвентарь пустой | Нет доступа к API или неверные креды | `ansible-inventory -i plugin.yml --list` | Проверьте токен/пароль, сетевую доступность, `validate_certs` |
| Конфликт групп из нескольких инвентарей | Одинаковые имена групп в разных источниках | `ansible-inventory --graph` | Используйте уникальные префиксы или `keyed_groups` |
| `ansible_host` не применяется | Переменная задана не в том месте | `ansible-inventory --host <host>` | Задавайте `ansible_host` в inventory, не в `group_vars` |
| Кэш инвентаря возвращает устаревшие данные | Слишком долгий `cache_timeout` или неверный plugin | `ansible-config dump | grep inventory_cache` | Уменьшите `cache_timeout`, очистите кэш |

### Факты и `gather_facts`

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `ansible_facts` пустой или отсутствует | `gather_facts: false` или факты не собраны | `ansible all -m setup` | Установите `gather_facts: true` или выполните `setup` вручную |
| `ansible_facts['os_family']` не существует | Используется старый плоский формат `ansible_os_family` | Проверьте синтаксис в плейбуке | Перейдите на `ansible_facts['os_family']` |
| Факты не обновляются после изменения ОС | Fact cache устарел | `ansible-config dump | grep fact_caching_timeout` | Уменьшите `fact_caching_timeout` или очистите кэш |
| `setup` падает на Windows | Отсутствует PowerShell 5.1+ или WinRM-транспорт | `ansible win01 -m setup` | Проверьте WinRM конфигурацию, версию PowerShell |
| Долгий сбор фактов на >500 хостах | Полный сбор без ограничений | Замер времени `ansible all -m setup` | Используйте `gather_subset` для селективного сбора |
| Факты недоступны в `delegate_to` задаче | `delegate_facts: false` по умолчанию | Проверьте `delegate_facts` в задаче | Установите `delegate_facts: true` |

### Fact caching и производительность

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Cache hit не работает | Неверный путь `fact_caching_connection` или права | `ls -la /tmp/ansible_facts_cache/` | Проверьте путь и права на запись |
| Секреты в кэше инвентаря | Векторная утечка при использовании `cache: true` с vault | Проверьте содержимое кэша | Отключите кэш для инвентарей с `!vault` (регрессия ansible-core 2.20+) |
| Redis кэш не работает | Redis не запущен или неверный хост/порт | `redis-cli ping` | Проверьте доступность Redis, строку подключения |
| Факты из prod попадают в dev | Общий каталог кэша для всех окружений | `ls /tmp/ansible_cache/` | Используйте раздельные каталоги через `ANSIBLE_ENV` |

### Host patterns и `--limit`

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `--limit` не находит группу | Группа создана через `group_by` в текущем плее | Проверьте порядок плеев | Выполняйте `group_by` в отдельном плее перед ограничением |
| `~regex` паттерн не работает | Неверный синтаксис regex | `ansible-playbook --list-hosts --limit "~web.*"` | Используйте двойные кавычки в shell |
| Пересечение групп `:&` пустое | Группы не пересекаются или опечатка | `ansible-inventory --graph` | Проверьте membership в обеих группах |
| Исключение `:!` не работает | Экранирование в shell | Используйте кавычки | `--limit "all:!db"` |

### Windows-инвентарь и факты

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `ansible_facts['os_family']` возвращает `Windows` | Корректно для Windows-хостов | Проверьте `when` условия | Используйте `ansible_facts['system'] == 'Win32NT'` для точной проверки |
| Факты Windows не кэшируются | Меньший набор фактов, чем POSIX | `ansible-inventory --host win01` | Ожидаемо: нет некоторых сетевых фактов |
| `ansible_python_interpreter` на Windows | Не требуется при WinRM, обязателен при SSH | Проверьте `ansible_connection` | Для WinRM не задавайте `ansible_python_interpreter` |

### Граничные случаи и ограничения

- **Constructed plugin требует фактов**: для первого запуска факты должны быть собраны. Используйте `gather_facts: true` или статический `group_by`.
- **Fact cache и Windows**: набор фактов Windows меньше, чем POSIX. Кэшируются только доступные факты.
- **Кэш инвентаря + Vault**: известная регрессия ansible-core 2.20+ — зашифрованные переменные могут сохраняться в кэш как литеральная строка. Используйте раздельные кэши или отключайте кэширование для инвентарей с `!vault`.
- **Динамический инвентарь и `--limit`**: паттерны `--limit` работают с группами из динамического инвентаря, но группа должна существовать в текущем запуске.
- **`group_by` и `--limit`**: если `--limit` применяется до `group_by`, группа может быть невидимой. Выполняйте группировку в отдельном плее.
- **Секреты в инвентаре**: пароли WinRM, токены NetBox/Consul — только через Ansible Vault или переменные окружения. Никогда в открытом виде в YAML/INI.
- **Большие инвентари (1000+ хостов)**: включайте `fact_caching` и ограничивайте `gather_subset`. Полный сбор фактов на 5000 хостах может занимать 30+ минут без кэша.

## Рекомендации и лучшие практики

1. **Inventory как код**: версионируйте `hosts.yml`, `group_vars/`, `requirements.yml`. Динамические плагины конфигурируются через YAML, который тоже версионируется.
2. **Версионирование коллекций**: фиксируйте версии в `requirements.yml` (`netbox.netbox:==3.0.0`).
3. **Constructed для OS-групп**: создавайте `os_Debian`, `os_RedHat`, `os_Windows` через constructed plugin или `group_by`, а не хардкодьте в инвентаре.
4. **Fact caching обязательно для >100 хостов**: `jsonfile` для локальной работы, `redis` для distributed control node.
5. **Ограничивайте `gather_subset`**: собирайте только `distribution`, `os_family`, `pkg_mgr`, `service_mgr` — этого достаточно для большинства кроссплатформенных сценариев.
6. **Раздельные кэши для окружений**: prod, staging, dev — разные каталоги `fact_caching_connection`.
7. **`delegate_facts` для репрезентативных хостов**: собирайте факты с одного хоста группы и применяйте ко всем.
8. **Валидация инвентаря**: `ansible-inventory --graph --vars` перед каждым деплоем.
9. **Кэширование инвентаря**: включайте `cache: true` для динамических плагинов, чтобы не дергать API при каждом запуске.
10. **`ansible_host` для bastion**: используйте `ansible_host` + `ansible_port` + `ansible_user` для подключения через jump host.
11. **Используйте `ansible_facts` вместо плоского формата**: `ansible_facts['os_family']` вместо `ansible_os_family` (устаревший формат отключается в 2.24).
12. **Не кэшируйте секреты**: не помечайте факты, содержащие пароли или токены, как `cacheable: true`.
13. **Версионируйте inventory**: храните статические инвентари и конфигурации плагинов в Git. Динамические плагины тоже конфигурируются через YAML-файлы, которые версионируются.
14. **Разделяйте инвентари по окружениям**: `inventories/prod/`, `inventories/staging/`, `inventories/dev/` с раздельными кэшами фактов.
15. **Документируйте источники динамического инвентаря**: для каждого плагина указывайте CMDB/API endpoint, токен, метод аутентификации в README.

## Дополнительная информация

- [Динамический инвентарь в Ansible](../dynamic_inventory.md) — подробное руководство по плагинам NetBox, Consul, Foreman, скриптам.
- [Переменные и факты в Ansible](../PlaybookStructure/variables.md) — иерархия приоритетов, `set_fact`, `register`, `hostvars`, `group_by`.
- [Управление выполнением и отладка ролей](../Roles/task-execution-and-debugging.md) — `run_once`, `delegate_facts`, уровни директив, `check_mode`.
- [Оптимизация производительности](../ansible_performance_tuning.md) — `forks`, `fact_caching`, `strategy`, `pipelining`.
- [Кроссплатформенные концепции](./concepts.md) — матрица платформ, `ansible_facts`, общие паттерны.
