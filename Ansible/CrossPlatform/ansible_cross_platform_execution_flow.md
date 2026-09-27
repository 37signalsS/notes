# Кроссплатформенное выполнение: стратегии, контроль и изоляция изменений

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21.4+ | 2.22.0b1 доступен (сентябрь 2026) |
| **Python** (control node) | 3.11+ | 3.12–3.14 | Для ansible-core 2.21; 2.22 поддерживает 3.13–3.15 |
| **Python** (managed node, POSIX) | 3.9+ | 3.12+ | Для ansible-core 2.21 |
| **PowerShell** (Windows) | 5.1+ | 7.6 LTS | 7.6 LTS — стандарт для 2.21/2.22 (поддержка до Nov 2028) |
| **OpenSSH** | 8.0+ | Актуальная LTS | 10.5+ — актуальный релиз (август 2026) |
| **PyWinRM** | 0.4.0+ | 0.5.0+ | Для WinRM транспорта к Windows |
| **ansible.posix** | 1.5+ | Актуальная | Для `firewalld`, `seboolean`, `synchronize` |
| **ansible.windows** | 2.5+ | Актуальная | Для Windows-модулей |
| **forks** (параллелизм) | 5 | 10–50 | Зависит от сети и мощности Control Node |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible all -m ping
# → pong: web01
# → pong: db01

ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*" | head -20
# → "ansible_facts": {"os_family": "RedHat"} ...
```

## Определения

- **Strategy plugin** — плагин, определяющий алгоритм распределения задач между хостами. Встроенные: `linear` (синхронный), `free` (независимый), `host_pinned` (фиксированный пул).
- **`serial`** — ограничение количества хостов в батче. Поддерживает проценты (`"25%"`), абсолютные числа (`5`) и прогрессивные стратегии (`[1, 5, "50%"]`).
- **`throttle`** — ограничение параллелизма на уровне конкретной задачи. Независим от `serial`, но не может превышать `forks`.
- **`max_fail_percentage`** — максимальный процент ошибок в батче перед прерыванием. Работает только совместно с `serial` и стратегиями на базе `linear`.
- **`any_errors_fatal`** — немедленная остановка всего плейбука при любой ошибке на любом хосте.
- **Check Mode (`--check`)** — сухой прогон: Ansible прогнозирует изменения без их применения. Поддерживается не всеми модулями.
- **Diff Mode (`--diff`)** — показывает текстовые различия в конфигурационных файлах. Работает совместно с `--check` или на уровне задачи (`diff: true`).
- **`async` / `poll`** — асинхронное выполнение длительных задач. `async` задает таймаут в секундах, `poll` — интервал опроса (`0` = fire-and-forget).
- **`async_status`** — модуль для проверки статуса фоновой задачи по `ansible_job_id`.
- **Теги (`tags`)** — метки задач для выборочного запуска (`--tags`, `--skip-tags`). Специальные теги: `always` (выполняется всегда), `never` (только если вызван явно).
- **`--limit`** — ограничение выполнения на подмножестве хостов. Поддерживает паттерны: `webservers`, `webservers[1:5]`, `all:!db`, `webservers:&production`.
- **Blast Radius** — масштаб последствий при сбое автоматизации. Ограничивается `serial`, `throttle`, `max_fail_percentage`, `--limit`.
- **`forks`** — глобальный лимит параллелизма в `ansible.cfg`. Определяет максимальное количество хостов, обрабатываемых одновременно. По умолчанию 5; для production рекомендуется 10–50 в зависимости от ресурсов Control Node.
- **`run_once`** — выполнение задачи только один раз на первом хосте в батче. Результат доступен через `hostvars` для остальных хостов.
- **`delegate_to`** — перенаправление выполнения задачи на указанный хост. Чаще всего `delegate_to: localhost` для задач на Control Node.

## Основные концепции

### Strategy: linear / free / host_pinned

Стратегия определяет, как хосты проходят по задачам плейбука.

| Стратегия | Поведение | Когда использовать | Кроссплатформенные нюансы |
| :--- | :--- | :--- | :--- |
| `linear` (по умолчанию) | Все хосты батча завершают одну задачу, затем переходят к следующей | Задачи с разделяемым состоянием, `set_fact`, `max_fail_percentage` | Гарантирует предсказуемый порядок на mixed-парке. `max_fail_percentage` работает только с `linear`. |
| `free` | Каждый хост двигается самостоятельно, без ожидания остальных | Длительные независимые задачи, обновление ПО | Не используйте `set_fact` для передачи данных между хостами — они не синхронизируются. `max_fail_percentage` игнорируется. |
| `host_pinned` | Хост остается в слоте до завершения всего плея | Очень длительные плейбуки, изоляция ресурсов | Работает совместно с `serial` для фиксированного пула. Аналогичен `linear`, но с персистентными слотами. |

```yaml
# linear + serial: предсказуемое поэтапное обновление
- name: Программное обновление (Debian/RedHat)
  hosts: mixed_servers
  strategy: linear
  serial: "25%"
  max_fail_percentage: 10
  tasks:
    - name: Обновление пакетов
      ansible.builtin.package:
        name: "*"
        state: latest
      when: ansible_facts['system'] != 'Win32NT'

# free + serial: быстрое выполнение с контролем пачек
- name: Длительная миграция
  hosts: app_servers
  strategy: free
  serial: 10
  tasks:
    - name: Миграция БД
      ansible.builtin.command: /opt/migrate.sh
      async: 7200
      poll: 0
```

> **Production note:** `strategy: free` ускоряет выполнение на 20–40% для независимых хостов, но сломает логику, зависящую от `set_fact` между хостами. Для mixed-парков с Windows и Linux `linear` безопаснее, так как Windows-хосты часто медленнее из-за WinRM.

### serial, throttle, max_fail_percentage, any_errors_fatal

Эти директивы управляют blast radius и параллелизмом.

| Директива | Уровень | Назначение | Ограничения |
| :--- | :--- | :--- | :--- |
| `serial` | play | Размер батча хостов | Поддерживает проценты и прогрессивные стратегии |
| `throttle` | task / block | Лимит параллельности задачи | Не может превышать `forks` или `serial` |
| `max_fail_percentage` | play | Порог ошибок для остановки | Только с `serial` и `linear`-стратегиями |
| `any_errors_fatal` | play / task | Остановка при первой ошибке | Работает со всеми стратегиями |

```yaml
# Прогрессивный rollout: 1 хост → 5 хостов → 50%
- name: Канареечное обновление
  hosts: webservers
  serial:
    - 1          # канареек
    - 5          # небольшая группа
    - "50%"      # остаток
  max_fail_percentage: 5
  any_errors_fatal: false
  tasks:
    - name: Обновление пакета
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: latest
```

```yaml
# throttle: защита внешнего API от rate limits
- name: Проверка здоровья после обновления
  ansible.builtin.uri:
    url: "http://{{ inventory_hostname }}:{{ app_port }}/health"
  throttle: 5  # не более 5 параллельных запросов
  register: health
  until: health.status == 200
  retries: 12
  delay: 10
```

> **Production note:** `throttle` применяется после определения strategy. При `serial: 10` + `throttle: 5` фактически одновременно выполнятся 5 задач. `max_fail_percentage: 0` останавливает плей при первой ошибке — используйте для критичных сервисов.

### Check Mode и Diff Mode

`--check` прогнозирует изменения без применения. `--diff` показывает текстовые diff'ы.

**Поддержка check_mode по типам модулей:**

| Тип модуля | Поддержка check_mode | Поведение |
| :--- | :--- | :--- |
| Декларативные (`file`, `template`, `apt`, `service`) | Да | Корректно сравнивают желаемое и текущее состояние |
| `command` / `shell` | Нет (пропускаются) | Возвращают `skipped: true` в dry-run |
| `uri`, `get_url`, `slurp` | Частично | `uri` проверяет без side-effects; `get_url` может пропустить |
| `win_*` модули | Зависит от модуля | `win_service`, `win_package` обычно поддерживают |

```yaml
# Принудительное выполнение read-only задачи в check mode
- name: Сбор версии ПО для валидации
  ansible.builtin.shell: "{{ pkg_cmd }} --version"
  register: pkg_version
  changed_when: false
  check_mode: false  # выполнить даже в --check
  when: ansible_facts['system'] != 'Win32NT'

# Проверка конфигурации Nginx в dry-run
- name: Валидация конфига
  ansible.builtin.command: nginx -t -c /etc/nginx/nginx.conf
  changed_when: false
  check_mode: false
  register: nginx_validate
  failed_when: nginx_validate.rc != 0
  notify: Reload Nginx
  when: ansible_facts['service_mgr'] == 'systemd'
```

```yaml
# Windows: проверка статуса службы в check mode
- name: Проверка IIS (Windows)
  ansible.windows.win_shell: |
    $svc = Get-Service -Name W3SVC -ErrorAction SilentlyContinue
    if ($svc.Status -eq 'Running') { exit 0 } else { exit 1 }
  changed_when: false
  check_mode: false
  register: iis_status
  when: ansible_facts['os_family'] == 'Windows'
```

> **Production note:** Все read-only валидации (`nginx -t`, `curl /health`, `systemctl is-active`) должны иметь `check_mode: false` и `changed_when: false`. Иначе в `--check` они будут пропущены, и шаблоны, зависящие от их `register`, получат `undefined`. На Windows `win_*` модули часто поддерживают check_mode лучше, чем `shell`/`command`.

### Асинхронное выполнение (`async` / `poll` / `async_status`)

Для операций, превышающих таймаут SSH-сессии (по умолчанию 30 минут), используйте `async`. Подробные паттерны и обработка ошибок см. в [Поток управления и обработка ошибок](../PlaybookStructure/flow_control.md).

| Параметр | Назначение | Рекомендации |
| :--- | :--- | :--- |
| `async` | Максимальное время выполнения (секунды) | Устанавливайте с запасом 20–30% |
| `poll: 0` | Fire-and-forget | Ansible не ждет завершения |
| `poll: N` | Опрос каждые N секунд | Блокирует выполнение |
| `async_status` | Проверка статуса по `jid` | Используйте с `until`/`retries`/`delay` |

```yaml
# Длительное обновление ОС (Debian/RedHat)
- name: Запуск обновления в фоне
  ansible.builtin.dnf:
    name: "*"
    state: latest
  async: 3600
  poll: 0
  register: update_job
  when: ansible_facts['os_family'] == 'RedHat'

- name: Ожидание обновления (RedHat)
  ansible.builtin.async_status:
    jid: "{{ update_job.ansible_job_id }}"
  register: update_result
  until: update_result.finished
  retries: 60
  delay: 30
  when: ansible_facts['os_family'] == 'RedHat'

# Windows: длительная установка MSI
- name: Установка ПО (Windows)
  ansible.windows.win_package:
    path: "https://example.com/installer.msi"
    state: present
  async: 1800
  poll: 0
  register: install_job
  when: ansible_facts['os_family'] == 'Windows'

- name: Ожидание установки (Windows)
  ansible.builtin.async_status:
    jid: "{{ install_job.ansible_job_id }}"
  register: install_result
  until: install_result.finished
  retries: 60
  delay: 30
  when: ansible_facts['os_family'] == 'Windows'
```

> **Production note:** Фоновые задачи (`poll: 0`) хранятся в памяти Control Node. При перезапуске Ansible все `async` задачи теряются. Для критичных операций используйте `poll: >0` или сохраняйте `ansible_job_id` во внешнее хранилище. `async` таймаут непрерываем — задача будет убита по истечении `async`, даже если процесс еще выполняется.

### Теги: `always`, `never`, `--tags`, `--skip-tags`

Теги позволяют селективно запускать задачи в mixed-парке.

| Тег / Опция | Поведение | Пример использования |
| :--- | :--- | :--- |
| `always` | Выполняется всегда, кроме `--skip-tags always` | Создание пользователей, директорий |
| `never` | Только если вызван через `--tags never` | Откат, debug |
| `--tags` | Запуск только указанных тегов | `--tags linux,packages` |
| `--skip-tags` | Пропуск указанных тегов | `--skip-tags windows` |

```yaml
- name: Установка пакетов (POSIX)
  ansible.builtin.package:
    name: "{{ pkg_name }}"
    state: present
  tags: [linux, packages, always]

- name: Установка пакетов (Windows)
  ansible.windows.win_package:
    path: "{{ pkg_installer_path }}"
    state: present
  tags: [windows, packages, always]

- name: Настройка firewall (Debian)
  community.general.ufw:
    rule: allow
    port: "{{ item }}"
  loop: "{{ firewall_ports }}"
  tags: [linux, firewall, debian]
  when: ansible_facts['os_family'] == 'Debian'
```

```bash
# Запуск только Linux-задач
ansible-playbook site.yml --tags linux

# Запуск всех, кроме Windows
ansible-playbook site.yml --skip-tags windows

# Запуск критичных задач (always)
ansible-playbook site.yml --tags always

# Комбинация: Linux + packages, без firewall
ansible-playbook site.yml --tags "linux,packages" --skip-tags firewall
```

> **Production note:** `tags: always` на platform-specific задачах сломает селективный запуск. Используйте `always` только для действительно универсальных задач (создание `deploy` пользователя, базовых директорий). `never` полезно для задач отката, которые не должны выполняться при обычном деплое.

### Host patterns и `--limit`

`--limit` ограничивает выполнение на подмножестве хостов. Поддерживает паттерны инвентаря.

| Паттерн | Назначение | Пример |
| :--- | :--- | :--- |
| `webservers` | Группа инвентаря | `--limit webservers` |
| `web[01:05]` | Диапазон хостов | `--limit web[01:05]` |
| `all:!db` | Все кроме группы | `--limit "all:!db"` |
| `webservers:&production` | Пересечение групп | `--limit "webservers:&production"` |
| `os_Debian` | Группа, созданная через `group_by` | `--limit os_Debian` |

```yaml
# Создание OS-специфичных групп через group_by
- name: Группировка по ОС
  ansible.builtin.group_by:
    key: "os_{{ ansible_facts['os_family'] }}"

# Использование в отдельных плеях
- hosts: os_Debian
  tasks:
    - name: Установка пакетов только для Debian
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present

- hosts: os_RedHat
  tasks:
    - name: Установка пакетов только для RedHat
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present
```

```bash
# Dry-run только на канарейке
ansible-playbook site.yml --check --diff --limit canary

# Деплой только на RedHat-хосты
ansible-playbook site.yml --limit os_RedHat

# Исключение проблемного хоста
ansible-playbook site.yml --limit "all:!web01.example.com"
```

> **Production note:** `--limit` работает с группами, созданными через `group_by`, что идеально для кроссплатформенных плейбуков. При использовании `--limit` с `group_by` убедитесь, что группировка выполняется в предыдущем плее или через `meta: refresh_inventory`.

### Параллелизм: `forks`, `pipelining`, `strategy`

Производительность кроссплатформенного выполнения зависит от трех взаимосвязанных параметров:

| Параметр | Уровень | Назначение | Рекомендации |
| :--- | :--- | :--- | :--- |
| `forks` | `ansible.cfg` | Максимум параллельных хостов | По умолчанию 5; для production 10–50 |
| `pipelining` | `ansible.cfg` / inventory | Сокращение SSH-сессий | Включайте если нет ограничений `requiretty` |
| `strategy` | play | Алгоритм распределения задач | `linear` по умолчанию; `free` для независимых хостов |

```ini
# ansible.cfg: настройка параллелизма
[defaults]
forks = 20
pipelining = True
strategy_plugins = ~/.ansible/plugins/strategy
```

```bash
# Проверка текущего значения forks
ansible-config dump | grep -i forks
# → DEFAULT_FORKS(env: ANSIBLE_FORKS) = 5
```

> **Production note:** `forks` ограничивает общее число хостов, обрабатываемых одновременно. При `serial: 10` и `forks: 5` фактически параллельно обрабатывается 5 хостов. Включите `pipelining` для сокращения накладных расходов SSH, но убедитесь, что на целевых хостах нет `requiretty` в `sudoers`.

### Кроссплатформенные нюансы выполнения

| Аспект | Linux / macOS / BSD | Windows |
| :--- | :--- | :--- |
| Транспорт | SSH (OpenSSH) | WinRM (HTTP 5985 / HTTPS 5986) или SSH |
| Выполнение модулей | Python на целевом хосте | PowerShell Remoting (PSRP) или SSH |
| Сбор фактов | `ansible.builtin.setup` (Python) | `ansible.windows.win_facts` или `setup` через WinRM |
| Ограничение параллелизма | `forks` + SSH-пулы | `forks` + WinRM-сессии (более тяжелые) |
| Асинхронность | `async` через SSH | `async` через WinRM/PSRP (медленнее) |
| Check Mode | Поддерживается большинством модулей | `win_*` модули часто поддерживают лучше, чем `shell`/`command` |

> **Production note:** WinRM-сессии значительно тяжелее SSH. При работе с mixed-парком Windows-хосты часто становятся узким местом. Увеличивайте `serial` для Windows-батчей и используйте `throttle` для защиты WinRM-серверов от перегрузки.

## Практические сценарии

### Сценарий 1: Прогрессивный rollout на mixed-парке

```yaml
- name: Канареечное обновление с автоматическим откатом
  hosts: mixed_servers
  serial:
    - 1
    - "10%"
    - "50%"
  max_fail_percentage: 5
  any_errors_fatal: false
  tasks:
    - name: Обновление пакетов
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: latest
      when: ansible_facts['system'] != 'Win32NT'

    - name: Проверка работоспособности
      ansible.builtin.uri:
        url: "http://{{ inventory_hostname }}:{{ app_port }}/health"
        status_code: 200
      retries: 5
      delay: 10
      until: health_check.status == 200
```

### Сценарий 2: async + throttle для длительных операций

```yaml
- name: Длительная миграция с throttle
  hosts: db_servers
  serial: "25%"
  tasks:
    - name: Запуск миграции БД
      ansible.builtin.command: /opt/db_migrate.sh
      async: 7200
      poll: 0
      register: migrate_job
      throttle: 2  # не более 2 параллельных миграций

    - name: Мониторинг прогресса
      ansible.builtin.async_status:
        jid: "{{ migrate_job.ansible_job_id }}"
      register: migrate_status
      until: migrate_status.finished
      retries: 120
      delay: 60
```

### Сценарий 3: Check Mode с platform-specific валидациями

```yaml
- name: Валидация Nginx (Linux)
  ansible.builtin.command: nginx -t -c /etc/nginx/nginx.conf
  changed_when: false
  check_mode: false
  register: nginx_validate
  failed_when: nginx_validate.rc != 0
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Валидация IIS (Windows)
  ansible.windows.win_shell: |
    Import-Module WebAdministration
    Get-WebConfigurationProperty -Filter /system.applicationHost/sites -Name *
  changed_when: false
  check_mode: false
  register: iis_validate
  when: ansible_facts['os_family'] == 'Windows'
```

### Сценарий 4: Теги для селективного деплоя

```yaml
- name: Развертывание с тегами
  hosts: all
  tasks:
    - name: Установка пакетов (всегда)
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present
      tags: [always, packages]

    - name: Настройка firewall (только Linux)
      ansible.posix.firewalld:
        service: http
        permanent: yes
        state: enabled
      tags: [linux, firewall]
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Настройка firewall (только Windows)
      ansible.windows.win_firewall_rule:
        name: Allow HTTP
        localport: 80
        action: allow
        direction: in
        protocol: tcp
        state: present
      tags: [windows, firewall]
      when: ansible_facts['os_family'] == 'Windows'
```

### Сценарий 5: Откат через tags `never`

```yaml
- name: Основной деплой
  hosts: webservers
  tasks:
    - name: Деплой приложения
      ansible.builtin.template:
        src: app.conf.j2
        dest: "{{ app_conf_path }}"
      notify: Restart App
      tags: [deploy, never]  # выполняется только с --tags never

    - name: Откат конфигурации
      ansible.builtin.template:
        src: app.conf.backup.j2
        dest: "{{ app_conf_path }}"
      notify: Restart App
      tags: [rollback]
```

```bash
# Обычный деплой (без never задач)
ansible-playbook site.yml --tags deploy

# Явный откат
ansible-playbook site.yml --tags rollback

# Принудительное выполнение never задач (редко)
ansible-playbook site.yml --tags never
```

### Сценарий 6: `run_once` + `delegate_to` для централизованных задач

Задачи, которые должны выполниться один раз (сбор артефактов, регистрация в monitoring), но с доступом к фактам каждого хоста:

```yaml
- name: Сбор информации о всех хостах
  ansible.builtin.setup:
    filter: ansible_distribution*
  run_once: true
  delegate_to: localhost
  register: all_facts

- name: Генерация отчета
  ansible.builtin.template:
    src: inventory_report.j2
    dest: "/tmp/report_{{ ansible_date_time.date }}.html"
  run_once: true
  delegate_to: localhost
```

### Сценарий 7: Windows-специфичные ограничения параллелизма

WinRM-сессии тяжелее SSH. Для Windows-батчей увеличивайте `serial` и используйте `throttle`:

```yaml
- name: Обновление Windows-серверов
  hosts: windows_servers
  serial: "20%"  # Меньше хостов одновременно
  max_fail_percentage: 10
  tasks:
    - name: Установка обновлений
      ansible.windows.win_updates:
        category_names:
          - SecurityUpdates
          - CriticalUpdates
        state: installed
      throttle: 3  # Не более 3 параллельных WinRM-задач
      register: update_result

    - name: Перезагрузка при необходимости
      ansible.windows.win_reboot:
      when: update_result.reboot_required
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible-playbook site.yml --check --diff` | Сухой прогон с diff'ами | `ok`/`changed` без применения изменений |
| `ansible-playbook site.yml --check` | Только проверка | Прогноз изменений |
| `ansible-playbook site.yml --diff` | Diff без check mode | Текстовые различия при реальном применении |
| `ansible-playbook site.yml --limit canary` | Запуск на подмножестве | Выполнение только на `canary` |
| `ansible-playbook site.yml --tags deploy` | Селективный запуск | Только задачи с тегом `deploy` |
| `ansible-playbook site.yml --skip-tags verify` | Пропуск задач | Все кроме `verify` |
| `ansible-playbook site.yml --list-tasks` | Список задач | Список без выполнения |
| `ansible-playbook site.yml --list-hosts --limit web[01:05]` | Список хостов | Дерево выбранных хостов |
| `ansible-playbook site.yml --strategy free` | Независимое выполнение | Хосты двигаются самостоятельно |
| `ansible all -m async_status -a "jid=<id>"` | Проверка фоновой задачи | `finished: true/false`, `results` |
| `ansible-playbook site.yml --forks 20` | Параллелизм 20 хостов | Увеличивает скорость выполнения |
| `ANSIBLE_FORKS=20 ansible-playbook site.yml` | Параллелизм через env | Тот же эффект через переменную окружения |

## Диагностика и устранение неполадок

### Strategy и параллелизм

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Выполнение очень медленное | `forks: 5` по умолчанию | `ansible-config dump | grep forks` | Увеличьте `forks` до 20–50 в `ansible.cfg` |
| `max_fail_percentage игнорируется` | Используется `strategy: free` | Проверьте `strategy` в плейбуке | Переключитесь на `linear` или уберите `free` |
| `strategy: free` + `set_fact` — данные не передаются | `set_fact` не синхронизируется между хостами | Проверьте использование `set_fact` | Используйте `run_once: true` + `delegate_to: localhost` |
| `throttle` не ограничивает параллелизм | `throttle` > `forks` | `ansible-config dump | grep forks` | Установите `throttle <= forks` |
| Хост завис на задаче | Длинная задача без `async` | `ps aux | grep ansible` на Control Node | Добавьте `async` + `poll: 0` для длительных операций |
| `serial` не работает | Отсутствует или некорректный синтаксис | Проверьте `serial` в плейбуке | Используйте строку (`"25%"`) или число, не список без `linear` |

### async и фоновые задачи

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Фоновая задача завершилась с ошибкой | Процесс на целевом хосте упал | `ansible.builtin.async_status` + `jid` | Проверьте `job_result.rc`, логи на целевом хосте |
| `async_status` возвращает `finished: false` вечно | Таймаут `async` слишком маленький или задача заблокирована | `ps aux | grep migrate.sh` на хосте | Увеличьте `async`, проверьте блокировки на хосте |
| Фоновая задача потеряна после перезапуска | `poll: 0` + перезапуск Control Node | Проверьте `ansible_job_id` в facts | Используйте `poll: >0` или сохраняйте `jid` во внешнее хранилище |
| `async_status` не найден | Неверный `jid` или задача уже удалена | Проверьте `ansible_job_id` из `register` | Убедитесь, что `jid` передается корректно |

### Check Mode и dry-run

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `--check` пропускает важные задачи | `command`/`shell` не поддерживают check_mode | `ansible-doc -s module_name` | Добавьте `check_mode: false` для read-only проверок |
| Шаблоны получают `undefined` в `--check` | `register` переменная не заполнена из-за пропуска | Запустите без `--check` и сравните | Добавьте `check_mode: false` к задачам, заполняющим `register` |
| `--diff` показывает пустоту | Модуль не поддерживает `diff` | Проверьте документацию модуля | Используйте декларативные модули (`template`, `file`) вместо `command` |
| Check Mode падает на Windows | `win_*` модуль не поддерживает check_mode | Проверьте `supports_check_mode` в docs | Используйте альтернативный модуль или `win_shell` с `check_mode: false` |

### Теги и селективный запуск

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `--tags always` не запускает ожидаемые задачи | Тег `always` на platform-specific задаче | Проверьте теги задач | Используйте `always` только для универсальных задач |
| `import_tasks` не видит теги | Теги не передаются в включаемый файл | Проверьте `import_tasks` vs `include_tasks` | Используйте `include_tasks` для динамического включения с тегами |
| `--skip-tags` пропускает критичные задачи | Слишком broad-паттерн | `ansible-playbook --list-tasks --skip-tags ...` | Уточните паттерн тегов, проверьте `--list-tasks` перед запуском |
| `--limit` не находит группу | `group_by` выполняется после применения `--limit` | Проверьте порядок плеев | Выполняйте `group_by` в отдельном плее или используйте `meta: refresh_inventory` |

### Windows execution

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| WinRM-сессии таймаут при массовом запуске | Слишком много параллельных сессий | Мониторинг WinRM-сервера | Увеличьте `serial`, используйте `throttle` |
| `any_errors_fatal` не останавливает плей | Стратегия `free` или `max_fail_percentage` без `serial` | Проверьте конфигурацию | Используйте `linear` + `serial` + `max_fail_percentage` |
| `async` на Windows не работает | WinRM имеет ограничения на фоновые задачи | Проверьте WinRM конфигурацию | Увеличьте `MaxEnvelopeSizekb` или используйте `poll: >0` |
| Факты не обновляются после `delegate_to` | `delegate_facts` по умолчанию `false` | Проверьте `ansible_facts` после делегирования | Добавьте `delegate_facts: true` если нужно |

### Граничные случаи и ограничения

- **`max_fail_percentage` без `serial`**: параметр игнорируется. Всегда комбинируйте с `serial`.
- **`strategy: free` + `set_fact`**: факты не синхронизируются между хостами. Для разделяемых данных используйте `run_once: true` + `delegate_to: localhost`.
- **`strategy: free` + `max_fail_percentage`**: порог игнорируется. Используйте `linear` для контролируемого останова.
- **`command`/`shell` в check mode**: всегда пропускаются. Добавьте `check_mode: false` для read-only проверок, которые нужны в dry-run.
- **`async` + перезапуск Control Node**: фоновые задачи теряются. Для критичных операций используйте `poll: >0` или внешнее хранилище `ansible_job_id`.
- **`throttle` и `forks`**: `throttle` не может превышать `forks`. При `forks: 5` и `throttle: 10` фактически параллельно 5 задач.
- **Теги и `import_tasks`**: теги на `import_tasks` не передаются внутрь включаемого файла. Используйте `include_tasks` для тегирования внутри.
- **`--limit` с `group_by`**: группа создается динамически. Если `--limit` применяется до `group_by`, группа может быть невидимой. Выполняйте группировку в отдельном плее перед ограничением.
- **`forks` и память Control Node**: при `forks: 50` и тяжелых модулях (`setup`, `winrm`) Control Node потребляет больше RAM. Мониторьте память при масштабировании.
- **`pipelining` и `requiretty`**: при включенном `pipelining` на целевых хостах не должно быть `requiretty` в `sudoers`. Иначе Ansible упадет с ошибкой.
- **`host_pinned` и `serial`**: без `serial` `host_pinned` ведет себя как `linear`. Используйте вместе для фиксированного пула.
- **`async` на Windows через WinRM**: фоновые задачи могут не работать корректно из-за ограничений PSRP. Тестируйте edge cases.

## Рекомендации и лучшие практики

1. **По умолчанию `linear`**: переключайтесь на `free` только когда задачи на разных хостах действительно независимы.
2. **`serial` для rolling updates**: начинайте с `serial: 1` (канареек), затем прогрессивно увеличивайте.
3. **`max_fail_percentage: 0` для критичных сервисов**: останов при первой ошибке предотвращает каскадные сбои.
4. **`throttle` для внешних API и WinRM**: защищайте мониторинг, лицензии, балансировщики от rate limits. На Windows увеличивайте `throttle` для снижения нагрузки на WinRM.
5. **Check Mode в CI/CD**: всегда запускайте `--check --diff` перед продакшеном. Добавляйте `check_mode: false` к read-only валидациям.
6. **`changed_when: false` для проверок**: `nginx -t`, `curl /health`, `systemctl is-active` не должны возвращать `changed`.
7. **`async` с `poll: >0` для критичных операций**: fire-and-forget теряется при перезапуске Control Node.
8. **Теги для окружений**: `--tags deploy --skip-tags test` для разделения staging/production.
9. **`--limit` для канареек**: комбинируйте с `serial` для контролируемого rollout.
10. **Изоляция изменений**: `--check --diff` в CI + `--limit` для канареек + `serial`/`max_fail_percentage` для массовых операций.
11. **Настройка `forks`**: для mixed-парка установите `forks: 20–50` в `ansible.cfg`. Мониторьте память Control Node при увеличении.
12. **`pipelining` для SSH**: включайте `pipelining = True` для сокращения накладных расходов SSH, убедившись что `requiretty` отключен.
13. **`run_once` + `delegate_to` для централизованных задач**: используйте для отчетов, регистрации в monitoring, скачивания артефактов один раз.
14. **Документируйте blast radius**: для каждого плейбука указывайте предполагаемый `serial`, `max_fail_percentage` и `throttle` в README или комментариях.
15. **Тестируйте strategy на pilot-группе**: при переключении с `linear` на `free` тестируйте на 2–3 хостах перед массовым применением.
16. **Версионирование Ansible**: не используйте EOL-версии (2.14 и ниже). Для production используйте 2.21.x или 2.20.x.

## Дополнительная информация

- [Выполнение плейбуков: база](../PlaybookStructure/basics.md) — `serial`, `strategy`, `throttle` на уровне плейбука.
- [Поток управления и обработка ошибок](../PlaybookStructure/flow_control.md) — `block/rescue`, `ignore_errors`, `any_errors_fatal`, `until`, расширенные паттерны `async`/`throttle`.
- [Продвинутые возможности плейбуков](../PlaybookStructure/advanced.md) — `delegate_to`, `run_once`, `delegate_facts`, `async`/`poll`, обработка ошибок фоновых задач.
- [Управление пакетами и обновлениями](../ansible_patch_management.md) — `serial`, `throttle`, `async` в контексте массового обновления пакетов.
- [Стратегии деплоя и rolling updates](../ansible_deployment_strategies.md) — `serial`, `max_fail_percentage`, `any_errors_fatal` в контексте деплоя.
- [Оптимизация производительности](../ansible_performance_tuning.md) — `forks`, `pipelining`, `fact_caching`, `strategy`.
- [Кроссплатформенные концепции](./concepts.md) — матрица платформ, `ansible_facts`, общие паттерны.
