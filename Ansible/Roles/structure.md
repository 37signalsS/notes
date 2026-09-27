# Структура роли Ansible

## Определения

**Структура роли** — стандартизированная организация каталогов и файлов в роли Ansible, которая позволяет движку автоматически находить и выполнять ресурсы (задачи, обработчики, шаблоны, переменные) без явного указания полных путей.

**Каталог роли** — директория с предопределенной структурой подкаталогов. Каждый подкаталог имеет специфическое назначение и приоритет в жизненном цикле выполнения роли.

**FQCN (Fully Qualified Collection Name)** — полное имя роли или модуля (например, `community.general.docker_container`), используемое для однозначной идентификации ресурсов в современных коллекциях.

**Спецификация аргументов (`argument_spec`)** — декларативное описание входных параметров роли в файле `meta/argument_specs.yml`, позволяющее Ansible автоматически проверять типы и обязательность переменных до начала выполнения задач.

**Change Management (управление изменениями)** — процесс контроля всех изменений в инфраструктуре с целью минимизации рисков и влияния на производственные сервисы. В контексте Ansible роли обеспечивают атомарность и воспроизводимость изменений.

**Observability (наблюдаемость)** — способность понимать внутреннее состояние системы по внешним сигналам (логи, метрики, трейсы). Роли Ansible должны генерировать структурированные логи и метрики для интеграции с системами мониторинга.

**Compliance-as-Code** — практика реализации политик соответствия (PCI-DSS, HIPAA, SOC2) через код автоматизации. Структура роли должна поддерживать аудиторский след и валидацию соответствия.

**Supply Chain Security (безопасность цепочки поставок)** — практики защиты контента ролей: проверка подписей, контроль версий зависимостей, аудит использованных компонентов.

**Air-gapped Environment (изолированная среда)** — инфраструктурная среда без прямого выхода в интернет, требующая локальных зеркал репозиториев и предварительной загрузки всех зависимостей.

---

## Предварительные требования

### Системные требования (Ansible 2.21.4)

*   **Control Node:** Требуется **Python 3.12+**.
*   **Target Nodes:** Требуется **Python 3.9+** (для Ansible 2.21.4 рекомендуется Python 3.12+).

### Инструменты

```bash
# Установка ansible-core
pip install ansible-core

# Проверка версии
ansible --version  # Должна быть 2.21.4

# Инициализация роли для проверки структуры
ansible-galaxy role init test_role
rm -rf test_role  # Удаление тестовой роли
```

---

## Основные концепции

### Инициализация роли

Для создания каркаса роли со стандартной структурой каталогов используется утилита `ansible-galaxy`:

```bash
# Создание каркаса роли со стандартной структурой каталогов
ansible-galaxy role init my_new_role  # → роль успешно инициализирована

# Инициализация роли без создания всех каталогов (только необходимые)
ansible-galaxy role init my_minimal_role --offline
```

### Стандартная структура каталогов (Ansible 2.17+)

Современная роль поддерживает расширенный набор каталогов для плагинов и метаданных:

| Каталог / Файл | Назначение |
| :--- | :--- |
| `tasks/` | Основные задачи роли (`main.yml` — входная точка) |
| `handlers/` | Обработчики уведомлений (перезапуск сервисов по сигналу `notify`) |
| `templates/` | Jinja2-шаблоны конфигураций (обычно с расширением `.j2`) |
| `files/` | Статические файлы для копирования без обработки |
| `defaults/` | Переменные по умолчанию (самый низкий приоритет, для настройки пользователем) |
| `vars/` | Внутренние переменные и константы роли (высокий приоритет, не для изменения пользователем) |
| `meta/` | Метаданные: зависимости (`main.yml`) и спецификация аргументов (`argument_specs.yml`) |
| `library/` | Собственные модули на Python (в Ansible 2.21.4 требуют Python 3.9+ на целевом узле) |
| `module_utils/` | Общий Python-код, разделяемый модулями из `library/` |
| `plugins/` | (Ansible 2.14+) Унифицированный каталог для плагинов: `lookup`, `filter`, `action` и др. |
| `lookup_plugins/` | Классический путь для плагинов поиска данных (API, БД) |
| `filter_plugins/` | Классический путь для пользовательских фильтров Jinja2 |
| `molecule/` | Конфигурации для тестирования роли (современный стандарт вместо `tests/`) |
| `README.md` | Полное описание роли, её параметров и примеров использования |

### Архитектура и жизненный цикл роли

**Жизненный цикл роли в рамках выполнения плейбука:**

```text
Загрузка плейбука → Обнаружение ролей (roles_path) → Разрешение зависимостей (meta/main.yml)
    ↓
Загрузка переменных (defaults → vars) → Инициализация фактов
    ↓
Выполнение tasks/main.yml → Обработчики (handlers) → Финализация
```

**Механизм обнаружения и загрузки ролей:**
1. Ansible ищет роли в каталогах, указанных в `roles_path` (по умолчанию: `./roles`, `~/.ansible/roles`, `/usr/share/ansible/roles`).
2. При использовании FQCN (`namespace.collection.role`) роль загружается из указанной коллекции через механизм коллекций.
3. При использовании короткого имени (`my_role`) поиск происходит в локальных каталогах в порядке приоритета, указанном в `ansible.cfg`.

**Порядок загрузки компонентов роли:**
1. Ansible загружает `defaults/main.yml` и `vars/main.yml` до начала выполнения задач.
2. Выполняются зависимости из `meta/main.yml` (если не установлен флаг `allow_duplicates: false`).
3. Задачи из `tasks/main.yml` выполняются последовательно.
4. Обработчики (`handlers/main.yml`) срабатывают только при изменении состояния (`changed`) и только один раз за секцию плейбука.
5. На уровне коллекции (Unified Layout, Ansible 2.14+) роли могут обращаться к плагинам через единый каталог `plugins/`.

**Изоляция переменных (Flat Namespace):**
Поскольку Ansible использует глобальное пространство имен переменных, критически важно использовать префиксы для всех переменных роли (например, `nginx_port`, `nginx_conf_path`). Это предотвращает конфликты между ролями.

### Ключевые файлы и их назначение

#### Задачи и входные точки (`tasks/main.yml`)
Ansible всегда ищет `tasks/main.yml` как основную точку входа. Если логика сложная, рекомендуется разбивать её на файлы (например, `install.yml`, `configure.yml`, `service.yml`) и подключать их через `ansible.builtin.import_tasks` или `ansible.builtin.include_tasks` в основном файле.

#### Обработчики (`handlers/main.yml`)

Обработчики выполняются **только** по сигналу `notify` из задач и только **один раз** в конце каждой секции плейбука (или при явном `ansible.builtin.meta: flush_handlers`). Они предназначены для перезапуска сервисов, перечитывания конфигураций и других действий, которые должны произойти только при реальном изменении системы.

```yaml
# handlers/main.yml
---
- name: restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
  listen: "restart web services"  # Универсальное имя для listen

- name: reload systemd
  ansible.builtin.systemd:
    daemon_reload: true

- name: restart postgresql
  ansible.builtin.service:
    name: postgresql
    state: restarted
  when: ansible_os_family == "Debian"
```

**Использование в задачах:**
```yaml
# tasks/main.yml
- name: Deploy nginx configuration
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: restart nginx  # Вызов конкретного обработчика

- name: Deploy application config
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/config.yml
  notify: restart web services  # Вызов через listen
```

**Полезные паттерны:**
- Используйте `listen` для создания общих обработчиков, доступных из нескольких ролей
- Обработчики выполняются **после** всех задач секции, даже если вызваны из `pre_tasks`
- Флаг `listen` позволяет вызывать несколько обработчиков одним именем
- Используйте `ansible.builtin.meta: flush_handlers` для принудительного выполнения обработчиков до перехода к следующей секции

#### Разделение задач: `import_tasks` vs `include_tasks`

| Критерий | `import_tasks` (Static) | `include_tasks` (Dynamic) |
| :--- | :--- | :--- |
| **Время обработки** | До выполнения плейбука | Во время выполнения |
| **Циклы (`loop`)** | Не поддерживает | Поддерживает |
| **Теги** | Применяются ко всем задачам файла | Применяются только к вызову |
| **Когда (`when`)** | Не поддерживает | Поддерживает |
| **Производительность** | Быстрее (статический парсинг) | Медленнее (динамический импорт) |

```yaml
# Статический импорт (приоритет производительности)
- ansible.builtin.import_tasks: install.yml
  vars:
    app_version: "2.0"

# Динамический импорт (приоритет гибкости)
- ansible.builtin.include_tasks: configure.yml
  when: enable_config | bool
  loop: "{{ config_items }}"
```

#### Метаданные и спецификации (`meta/`)
*   **`main.yml`**: Описывает зависимости роли. Если роль A зависит от роли B, роль B будет выполнена до роли A. Также содержит информацию для Ansible Galaxy (автор, лицензия, платформы).
*   **`argument_specs.yml`** (Ansible 2.11+): Позволяет формально описать интерфейс роли (типы, значения по умолчанию, обязательность). В Ansible 2.17+ добавлено поле **`context`** для передачи дополнительных метаданных внешним инструментам (IDE, генераторам документации).
#### Изоляция переменных (Namespacing)

Поскольку в Ansible глобальное пространство имен переменных (Flat Namespace), критически важно:
1.  **Префиксы:** Все переменные роли ДОЛЖНЫ начинаться с имени роли (например, `nginx_port`, `nginx_conf_path`).
2.  **Defaults vs Vars:** Используйте `defaults/main.yml` для всего, что пользователь МОЖЕТ захотеть изменить. Используйте `vars/main.yml` для того, что НЕ ДОЛЖНО меняться (константы, пути в зависимости от ОС).

#### Change Management и воспроизводимость

С точки зрения SRE, структура роли должна обеспечивать:
- **Атомарность изменений:** Каждая роль должна выполнять одно логическое изменение (установка + конфигурация + валидация).
- **Идемпотентность:** Повторный запуск роли не должен приводить к неожиданным изменениям. Используйте `changed_when` и `check_mode`.
- **Обратимость:** Роли должны поддерживать откат через `meta/end_role` или явные задачи отката.
- **Аудиторский след:** Все изменения должны логироваться через callback-плагины для последующего анализа.

#### Observability и логирование

Для интеграции с системами мониторинга структура роли должна включать:
- **Структурированные логи:** Используйте `ansible.builtin.debug` с `msg` и `verbosity` для контроля объема вывода.
- **Метрики выполнения:** Регистрируйте `changed`, `failed`, `skipped` статусы задач для последующей агрегации.
- **Callback-плагины:** Настройте `callback_whitelist` для отправки результатов в journald, Splunk, или ELK.

#### Compliance и аудит

Для соответствия стандартам (PCI-DSS, HIPAA, SOC2):
- **Валидация аргументов:** Используйте `meta/argument_specs.yml` для проверки входных параметров роли.
- **Документация:** Каждая роль должна иметь README с описанием соответствия требованиям.
- **Версионирование:** Используйте Git tags для отслеживания изменений, влияющих на compliance.
- **Подписи:** Проверяйте целостность ролей через `ansible-galaxy role verify` или GPG-подписи.

#### Air-gapped среды

Для изолированных сред без доступа в интернет:
- **Локальные зеркала:** Настройте `roles_path` на локальный репозиторий.
- **Предварительная загрузка:** Используйте `ansible-galaxy role download` для загрузки ролей в среду с доступом.
- **Без внешних зависимостей:** Роли не должны обращаться к внешним API во время выполнения.

### Технические подробности поиска ресурсов (Search Path)

Ansible использует механизм относительного поиска для модулей `copy`, `template`, `script`, `patch`. При вызове из задачи в роли поиск происходит в следующем порядке:

1.  Каталог `files/` или `templates/` внутри **текущей роли**.
2.  Каталоги ресурсов во всех ролях, перечисленных в **зависимостях** (`meta/main.yml`).
3.  Каталог, где находится вызывающий плейбук.
4.  Каталоги ролей, установленных на уровне проекта (`roles_path` в `ansible.cfg`).

Это позволяет "переопределять" файлы базовых ролей в дочерних или в основном проекте.

### Кастомные модули и утилиты (`library/` и `module_utils/`)

Для ролей, требующих уникальную логику, недоступную в стандартных модулях, можно создавать собственные Python-модули.

**Простой модуль в `library/`:**
```python
#!/usr/bin/python
# library/check_port.py

from ansible.module_utils.basic import AnsibleModule
import socket

def check_port(host, port, timeout=5):
    """Проверка доступности TCP-порта."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Port {port} on {host} is open"
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return False, f"Port {port} on {host} is closed: {str(e)}"

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            port=dict(type='int', required=True),
            timeout=dict(type='int', default=5),
        ),
        supports_check_mode=True
    )

    host = module.params['host']
    port = module.params['port']
    timeout = module.params['timeout']

    is_open, message = check_port(host, port, timeout)

    module.exit_json(
        changed=False,
        is_open=is_open,
        msg=message
    )

if __name__ == '__main__':
    main()
```

**Использование модуля:**
```yaml
# tasks/main.yml
- name: Check if database port is available
  check_port:
    host: "{{ db_host }}"
    port: "{{ db_port }}"
    timeout: 3
  register: port_check

- name: Fail if port is not available
  ansible.builtin.fail:
    msg: "Database port is not reachable"
  when: not port_check.is_open
```

**Общий код в `module_utils/`:**
```python
# module_utils/api_utils.py
import json
import urllib.request

def make_api_call(url, method='GET', data=None, headers=None):
    """Общая функция для REST API вызовов."""
    if headers is None:
        headers = {'Content-Type': 'application/json'}

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return True, json.loads(response.read().decode())
    except Exception as e:
        return False, str(e)
```

**Использование `module_utils` в модуле:**
```python
# library/my_api_module.py
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.api_utils import make_api_call

def main():
    module = AnsibleModule(
        argument_spec=dict(
            url=dict(type='str', required=True),
            method=dict(type='str', default='GET'),
            data=dict(type='dict'),
        )
    )

    success, result = make_api_call(
        module.params['url'],
        module.params['method'],
        module.params['data']
    )

    if success:
        module.exit_json(changed=False, api_result=result)
    else:
        module.fail_json(msg=f"API call failed: {result}")

if __name__ == '__main__':
    main()
```

### Роли в составе коллекций

В современных проектах (Ansible 2.10+) роли часто упаковываются в коллекции.
**Unified Layout (Ansible 2.14+):** Если роль является частью коллекции, она может не содержать свои папки плагинов. Все плагины выносятся на уровень коллекции в единую директорию `plugins/`:

```text
my_namespace/
└── my_collection/
    ├── plugins/              # Общие плагины коллекции
    │   ├── modules/          # Вместо library/
    │   ├── filter/           # Вместо filter_plugins/
    │   └── lookup/           # Вместо lookup_plugins/
    ├── roles/
    │   └── my_role/          # Стандартная структура роли внутри (без plugins/)
    │       ├── tasks/
    │       └── meta/
    └── README.md
```

Для использования такой роли необходимо указывать её полное имя (**FQCN**):
```yaml
- name: Подключение роли из коллекции
  ansible.builtin.include_role:
    name: my_namespace.my_collection.my_role
```

---

## Практические сценарии

### Сценарий 1: Сравнение `defaults/main.yml` и `vars/main.yml`

| Параметр | `defaults/main.yml` | `vars/main.yml` |
| :--- | :--- | :--- |
| **Назначение** | Настройки для пользователя | Внутренние константы |
| **Приоритет** | 1 (самый низкий) | 15 (очень высокий) |
| **Пример** | `app_port: 8080` | `app_bin_path: /usr/local/bin/app` |

**Лучшая практика:** Большинство переменных определяйте в `defaults`. Используйте `vars` только для данных, которые зависят от дистрибутива ОС и не должны переопределяться пользователем вручную (например, названия пакетов: `apache2` для Debian vs `httpd` для RedHat).

### Сценарий 2: Настройка зависимостей в `meta/main.yml`

Зависимости гарантируют выполнение необходимых компонентов перед основной ролью:

```yaml
# meta/main.yml
dependencies:
  - role: geerlingguy.nginx
    vars:
      nginx_http_port: 8080
  - role: my_custom_db_role
    allow_duplicates: false # Запрет повторного выполнения, если роль уже была вызвана
```

### Сценарий 3: Валидация аргументов через `meta/argument_specs.yml` (Ansible 2.17+)

Пример глубокой валидации параметров роли с использованием новых метаданных:

```yaml
# meta/argument_specs.yml
argument_specs:
  main:
    short_description: Основная точка входа настройки приложения
    options:
      app_user:
        type: str
        required: true
        description: Пользователь, от которого работает сервис
      app_port:
        type: int
        default: 8080
        description: Порт приложения
        context:
          monitoring_group: "web-services"
          security_level: "high"
      app_environment:
        type: str
        choices: ['prod', 'stage', 'dev']
        default: 'dev'
        description: Среда развертывания
```

### Сценарий 4: Досрочное завершение роли (`meta: end_role`)

В Ansible 2.18+ можно завершить роль для конкретного хоста, не прерывая выполнение плейбука для других. Это эффективнее, чем оборачивать все задачи в `when`.

```yaml
# tasks/main.yml
- name: Проверка наличия конфигурационного файла
  ansible.builtin.stat:
    path: /etc/myapp/config.yml
  register: config_stat

- name: Завершить роль, если конфигурация уже существует
  ansible.builtin.meta: end_role
  when: config_stat.stat.exists

- name: Основные задачи установки (выполнятся только если файла нет)
  ansible.builtin.yum:
    name: myapp
    state: present
```

### Сценарий 5: Использование плагинов внутри роли

Если роли нужен специфический фильтр для обработки строк, его можно разместить в `filter_plugins/custom_filters.py` (классический путь) или в `plugins/filter/` (современный путь):

```python
# filter_plugins/custom_filters.py
def to_upper_custom(value):
    return value.upper() + "_SUFFIX"

class FilterModule(object):
    def filters(self):
        return {
            'my_upper': to_upper_custom
        }
```

В задачах (`tasks/main.yml`) он станет доступен автоматически:
```yaml
- name: Использование кастомного фильтра
  ansible.builtin.debug:
    msg: "{{ 'test' | my_upper }}" # Результат: TEST_SUFFIX
```

### Сценарий 6: Организация шаблонов и файлов

Для сложных ролей рекомендуется структурировать подкаталоги для удобства навигации:

```text
roles/webserver/
├── files/
│   ├── static/
│   │   └── index.html
│   └── ssl/
│       └── dhparam.pem
├── templates/
│   ├── nginx/
│   │   ├── main.conf.j2
│   │   └── vhost.conf.j2
│   └── scripts/
│       └── cleanup.sh.j2
└── tasks/
    └── main.yml
```

Использование в задачах:
```yaml
- name: Деплой конфигурации Nginx
  ansible.builtin.template:
    src: nginx/vhost.conf.j2 # Путь относительно каталога templates/
    dest: /etc/nginx/sites-available/app.conf
```

### Сценарий 7: Роль для Change Management

Структура роли, обеспечивающая соответствие процессам change management:

```text
roles/app_deploy/
├── tasks/
│   ├── main.yml
│   ├── pre_deploy.yml      # Проверки перед развертыванием
│   ├── deploy.yml          # Основное развертывание
│   └── rollback.yml        # Откат изменений
├── handlers/
│   └── main.yml
├── defaults/
│   └── main.yml
├── vars/
│   └── main.yml
├── meta/
│   └── main.yml
└── README.md
```

**Пример `tasks/main.yml` с поддержкой отката:**
```yaml
---
- name: Change Management — Pre-deploy checks
  ansible.builtin.include_tasks: pre_deploy.yml
  tags: [pre_deploy, always]

- name: Change Management — Deploy
  ansible.builtin.include_tasks: deploy.yml
  register: deploy_result
  tags: deploy

- name: Change Management — Rollback on failure
  ansible.builtin.include_tasks: rollback.yml
  when: deploy_result is failed
  tags: rollback
```

### Сценарий 8: Роль для Observability

Структура роли, интегрированной с системами мониторинга:

```text
roles/monitoring_agent/
├── tasks/
│   ├── main.yml
│   ├── install.yml
│   └── configure.yml
├── templates/
│   └── agent.conf.j2       # Конфигурация с метриками
├── defaults/
│   └── main.yml            # Параметры мониторинга
├── vars/
│   └── main.yml            # Пути, порты
└── meta/
    └── main.yml
```

**Пример конфигурации с метриками:**
```yaml
# tasks/configure.yml
- name: Deploy monitoring agent config
  ansible.builtin.template:
    src: agent.conf.j2
    dest: /etc/monitoring/agent.conf
  notify: restart monitoring_agent

- name: Validate agent connectivity
  ansible.builtin.uri:
    url: "http://localhost:9090/metrics"
    status_code: 200
  register: metrics_check
  changed_when: false
```

### Сценарий 9: Роль для Air-gapped среды

Структура роли, работающей без доступа в интернет:

```text
roles/internal_app/
├── tasks/
│   ├── main.yml
│   └── install_from_local.yml
├── files/
│   ├── packages/
│   │   └── app-1.2.3.rpm  # Локальный пакет
│   └── configs/
│       └── app.conf        # Статическая конфигурация
├── defaults/
│   └── main.yml            # Пути к локальным ресурсам
├── vars/
│   └── main.yml
└── meta/
    └── main.yml
```

**Пример задачи с локальным пакетом:**
```yaml
# tasks/install_from_local.yml
- name: Install package from local mirror
  ansible.builtin.yum:
    name: "files/packages/app-1.2.3.rpm"
    state: present
  when: ansible_facts['os_family'] == "RedHat"

- name: Install package from local mirror (Debian)
  ansible.builtin.apt:
    deb: "files/packages/app_1.2.3_amd64.deb"
    state: present
  when: ansible_facts['os_family'] == "Debian"
```
---


## Операции и команды

### Управление ролями через `ansible-galaxy`

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `ansible-galaxy role init <name>` | Создание каркаса роли со стандартной структурой | `ansible-galaxy role init my_role` |
| `ansible-galaxy role init <name> --offline` | Инициализация без подключения к Galaxy | `ansible-galaxy role init my_role --offline` |
| `ansible-galaxy role install <source>` | Установка роли из Galaxy или Git | `ansible-galaxy role install geerlingguy.nginx` |
| `ansible-galaxy role install git+https://github.com/user/repo.git` | Установка из Git-репозитория | `ansible-galaxy role install git+https://github.com/user/repo.git` |
| `ansible-galaxy role install git+https://github.com/user/repo.git,v3.0.0` | Установка конкретной версии/ветки | `ansible-galaxy role install git+https://github.com/geerlingguy/ansible-role-nginx.git,v3.0.0` |
| `ansible-galaxy role list` | Просмотр установленных ролей с версиями | `ansible-galaxy role list` |
| `ansible-galaxy role uninstall <name>` | Удаление конкретной роли | `ansible-galaxy role uninstall geerlingguy.nginx` |
| `ansible-galaxy role uninstall --all` | Удаление всех ролей (опасно) | `ansible-galaxy role uninstall --all` |
| `ansible-galaxy role search <term>` | Поиск ролей в Galaxy | `ansible-galaxy role search nginx` |
| `ansible-galaxy role info <name>` | Информация о роли в Galaxy | `ansible-galaxy role info geerlingguy.nginx` |

**Валидация установки:**
```bash
# Проверка установленных ролей
ansible-galaxy role list
# → # roles/nginx             3.0.0  /Users/mac/ansible/roles/nginx

# Проверка целостности роли
ansible-galaxy role verify nginx
```

**Пример установки роли из Git с зависимостями:**
```bash
ansible-galaxy role install \
  git+https://github.com/geerlingguy/ansible-role-nginx.git,v3.0.0 \
  --roles-path ./roles
```

---


## Дополнительная информация

### Приоритеты переменных (Variable Precedence)

Иерархия приоритетов (от самого низкого к самому высокому):

1.  **Defaults роли** (`defaults/main.yml`)
2.  Переменные из инвентаря (`group_vars`, `host_vars`)
3.  **Vars роли** (`vars/main.yml`)
4.  Переменные, переданные как аргументы при вызове роли (через `vars:`)
5.  **Extra vars** (`-e` в командной строке) — абсолютный приоритет.

Подробное описание уровней — в [Переменные и факты](../PlaybookStructure/variables.md).

### Системные требования (Ansible 2.21.4)

*   **Контрольный узел:** Для работы Ansible 2.21.4 требуется Python 3.12 или новее.
*   **Управляемые узлы:** Для выполнения кастомных модулей из `library/` требуется Python 3.9+ (для Ansible 2.21.4 рекомендуется Python 3.12+).

### README роли как документация контракта

`README.md` в корне роли — не формальность, а описание интерфейса роли: без него невозможно понять, что роль делает и какие переменные ей передавать. Документация проверяется в том же CI, что и код роли.

```markdown
<!-- roles/web_server/README.md -->
# web_server

Устанавливает и настраивает Nginx на Debian/Ubuntu.

## Требования

* Ansible 2.19+ (проверено на ansible-core 2.21.4)
* Debian 12 / Ubuntu 22.04+

## Переменные

| Имя | Умолчание | Описание |
| :--- | :--- | :--- |
| `nginx_port` | `80` | Порт, на котором слушает Nginx |
| `nginx_workers` | `4` | Количество worker-процессов |
| `nginx_server_name` | — | **Обязательная**, имя виртуального хоста |

## Переменные vault

| Имя | Описание |
| :--- | :--- |
| `nginx_tls_cert` | Путь к сертификату (может быть секретом) |
| `nginx_basic_auth_hash` | Хеш для basic-auth |

## Зависимости

`geerlingguy.nginx` (Galaxy) — базовая установка пакета.

## Пример вызова

```yaml
- role: web_server
  vars:
    nginx_port: 8080
    nginx_server_name: app.example.com
```

## Обработчики

| Имя | Когда вызывается |
| :--- | :--- |
| `reload nginx` | Изменился `nginx.conf` или шаблон сайта |
| `restart nginx` | Изменился unit-файл или применён `--check` с `check_mode: false` |

## Тесты

```bash
molecule test
# Или проверка синтаксиса
ansible-playbook --syntax-check site.yml -i inventory.ini
```

## Ограничения

* Роль не работает на Windows-хостах — используйте [Windows-вариант](#).
* Не управляет DNS и балансировщиком.
```

**Минимальные требования к README роли:**

1.  Назначение — одной фразой в первом абзаце.
2.  Таблица переменных с типами и умолчаниями.
3.  Список обязательных переменных (без умолчания) — они ломают роль при отсутствии.
4.  Имена обработчиков — вызывающий плейбук может на них ссылаться.
5.  Пример вызова с минимальным набором параметров.
6.  Поддерживаемые платформы.
7.  Связь с остальной документацией базы знаний.

**Автоматическая проверка:** объявления в `meta/argument_specs.yml` и таблица в README должны совпадать. Расхождение — признак устаревшей документации.

### Проверка качества роли перед коммитом

Три уровня проверки, от быстрого к полному:

```bash
# 1. Синтаксис YAML и порядок ключей
yamllint -c .yamllint.yml .
# →yamllint: 5 warnings
# → line too long (line: 42)

# 2. Линтер Ansible: роли, плейбуки, FQCN, нейминг, аргументы модулей
ansible-lint --profile production roles/web_server/
# → Failed: 1
# → [EANSIBLE0011] Variable ${myapp_port} is undefined
# → [ANSIBLE0002] Trailing whitespace

# 3. Функциональные тесты в изолированном окружении
molecule test -s default
# → INFO: Scenario: default succeeded
```

**Конфигурация `ansible-lint` в репозитории** (коммитится вместе с ролью):

```yaml
# .ansible-lint
profile: production
exclude_paths:
  - .cache/
  - molecule/*/molecule.yml
offline: true
```

**Интеграция в Git hooks** — ловушка ловит проблемы до `git commit`:

```bash
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: https://github.com/ansible/ansible-lint
    rev: v24.7.0
    hooks:
      - id: ansible-lint
        args: ["--profile", "production"]

  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks:
      - id: yamllint
        args: ["-c", ".yamllint.yml"]
```

```bash
# Установка и запуск
pre-commit install        # хук в .git/hooks/pre-commit
pre-commit run --all-files
# → yamllint...........................................................Passed
# → ansible-lint......................................................Passed
# → Check Yaml........................................................Passed
```

**Что проверяет `ansible-test`:** санити-тесты, юнит-тесты и интеграционные тесты модулей **коллекций**. Роли `ansible-test` не покрывает — для них нужен Molecule.

```bash
# Для роли это не подходит — нужен Molecule:
ansible-test sanity --docker            # → это про коллекции и модули
molecule test -s default               # → это про роли
```

Полный разбор линтеров — в [ansible-lint](../ansible_lint_guide.md), тестирование коллекций — в [ansible-test](../ansible-test.md).

---

## Troubleshooting

### Роль не найдена при вызове

**Причина:** Неправильный путь или имя роли.

**Решение:**
```bash
# Проверка путей поиска
ansible-config dump | grep roles_path

# Проверка установленных ролей
ansible-galaxy role list

# Явное указание пути в плейбуке
- hosts: all
  roles:
    - role: my_role
      paths: ./roles  # Явный путь к роли
```

### Ошибка: "module not found"

**Причина:** Кастомный модуль не найден в `library/`.

**Решение:**
```bash
# Проверка структуры каталогов
ls -la roles/my_role/library/

# Проверка прав доступа
chmod +x roles/my_role/library/my_module.py

# Проверка синтаксиса Python
python3 -m py_compile roles/my_role/library/my_module.py
```

### Переменные не переопределяются

**Причина:** Конфликт приоритетов переменных.

**Решение:**
```bash
# Просмотр всех переменных хоста
ansible-inventory --host webserver1

# Просмотр переменных роли
ansible-playbook site.yml --list-variables

# Проверка приоритетов
ansible-doc -t vars 2>/dev/null || echo "См. документацию по приоритетам"
```

### Задачи выполняются дважды

**Причина:** Дублирование вызовов `import_tasks` или `include_role`.

**Решение:**
```bash
# Просмотр импортированных задач
ansible-playbook site.yml --list-tasks

# Использование тегов для фильтрации
ansible-playbook site.yml --list-tags
```

### Обработчик не выполняется

**Причина:** Задача не вызвала `changed` или обработчик вызван из `import_tasks`.

**Решение:**
```yaml
# Убедитесь, что задача помечает изменение
- name: Deploy config
  ansible.builtin.template:
    src: config.j2
    dest: /etc/app/config
  notify: restart app

# Принудительно выполнить накопленные обработчики
- name: Force handler execution
  ansible.builtin.meta: flush_handlers
```

### Роль не найдена при вызове

**Причина:** Неправильный путь или имя роли.

**Диагностика:**
```bash
# Проверка путей поиска
ansible-config dump | grep roles_path

# Проверка установленных ролей
ansible-galaxy role list

# Поиск роли в файловой системе
find /usr/share/ansible/roles ~/.ansible/roles ./roles -maxdepth 2 -name "main.yml" 2>/dev/null
```

**Решение:**
```yaml
# Явное указание пути в плейбуке
- hosts: all
  roles:
    - role: my_role
      paths: ./roles  # Явный путь к роли
```

### Дублирование ролей в путях поиска

**Причина:** Одна и та же роль найдена в нескольких каталогах `roles_path`.

**Диагностика:**
```bash
# Поиск дубликатов
find /usr/share/ansible/roles ~/.ansible/roles ./roles -maxdepth 2 -name "main.yml" 2>/dev/null
```

**Решение:**
```ini
# ansible.cfg — явное указание порядка путей
[defaults]
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
```

### Конфликт версий зависимостей

**Причина:** Несколько ролей требуют несовместимые версии одной зависимости.

**Диагностика:**
```bash
# Проверка зависимостей роли
ansible-galaxy role info geerlingguy.nginx
```

**Решение:**
```yaml
# meta/main.yml — явное указание совместимой версии
dependencies:
  - role: common
    vars:
      common_version: "2.1.0"  # Версия, удовлетворяющая всем зависимостям
```

### Ошибка: "Role signature verification failed"

**Причина:** Роль из Galaxy подписана, но GPG-ключ не установлен в контрольном узле.

**Решение:**
```bash
# Импорт GPG-ключа автора роли
gpg --keyserver keyserver.ubuntu.com --recv-keys <KEY_ID>

# Проверка подписи роли
ansible-galaxy role verify geerlingguy.nginx
```

### Роль не работает в air-gapped среде

**Причина:** Роль обращается к внешним ресурсам (Git, HTTP API, Galaxy) во время выполнения.

**Решение:**
- Перенесите все внешние зависимости в `files/` или локальный репозиторий.
- Используйте `connection: local` для задач, обращающихся к внешним API, и выполняйте их на control node заранее.
- Проверьте отсутствие `uri` и `get_url` модулей без явного указания локальных путей.

### Конфликт переменных в CI/CD pipeline

**Причина:** Одинаковые имена переменных в `defaults/main.yml` нескольких ролей, вызывающих непредсказуемое поведение в pipeline.

**Решение:**
- Используйте префиксы для всех переменных роли.
- В CI/CD явно указывайте переменные через `-e` или `vars:` в плейбуке.
- Используйте `ansible-playbook --list-variables` для отладки.

### Производительность роли при большом инвентаре

**Причина:** Роль выполняет тяжелые задачи (например, `uri`, `stat`) без кэширования фактов.

**Решение:**
- Используйте `gather_facts: false` в плейбуке, если факты не нужны.
- Кэшируйте факты через `fact_caching = jsonfile` в `ansible.cfg`.
- Разделяйте тяжелые задачи на отдельные файлы и используйте `include_tasks` с `when`.

---


## Best Practices

### Структура каталогов

1. **Единая точка входа:** Всегда используйте `tasks/main.yml` как основную точку входа роли.
2. **Разделение ответственности:** Разбивайте сложные роли на файлы: `install.yml`, `configure.yml`, `service.yml`.
3. **Именование файлов:** Используйте единообразные имена: `install.yml`, `config.yml`, `service.yml`, `validate.yml`.

### Управление переменными

1. **Префиксы:** Все переменные роли ДОЛЖНЫ начинаться с имени роли (например, `nginx_port`, `nginx_conf_path`).
2. **Defaults:** Определяйте в `defaults/main.yml` всё, что пользователь МОЖЕТ захотеть изменить.
3. **Vars:** Используйте `vars/main.yml` только для констант и данных, зависящих от ОС.
4. **Безопасность:** Никогда не храните пароли в `defaults/` или `vars/` — используйте Ansible Vault.

### Производительность

1. **import_tasks:** Используйте для статических подключений (производительность).
2. **include_tasks:** Используйте только когда нужна динамическая логика (`when`, `loop`).
3. **Минимизация фактов:** Отключайте `gather_facts: false` если факты не нужны.
4. **Параллелизм:** Используйте `forks` в `ansible.cfg` для ускорения выполнения.

### Безопасность

1. **Валидация аргументов:** Всегда используйте `meta/argument_specs.yml` для проверки входных параметров.
2. **Проверка подписей:** Используйте `ansible-galaxy role verify` для проверки целостности ролей. Подробнее о Supply Chain Security — в [Рекомендации по безопасности](../ansible_security_best_practices.md).
3. **Минимальные привилегии:** Избегайте `become: true` когда это не необходимо.
4. **Логирование:** Используйте `callback_whitelist` для аудита выполнения.

### Тестирование
1. **Molecule:** Используйте Molecule для тестирования ролей в изолированных средах.
2. ** ansible-lint:** Запускайте `ansible-lint` перед коммитом для проверки синтаксиса.
3. **ansible-test:** Используйте для тестирования кастомных модулей.

### Управление версиями и CI/CD

1. **Семантическое версионирование:** Используйте Git tags для marking releases ролей (например, `v1.2.0`). Это позволяет точно указывать версии в `meta/main.yml` и `requirements.yml`.
2. **CI-пайплайн:** Интегрируйте `ansible-lint` и `molecule test` в CI/CD pipeline для автоматической проверки каждого коммита.
3. **Именование:** Используйте `kebab-case` для имен ролей в файловой системе и FQCN (`namespace.collection.role`) при подключении через коллекции.

### Документация

1. **README.md:** Обязательно заполняйте README для каждой роли с описанием переменных, примеров использования и зависимостей.
2. **meta/main.yml:** Указывайте `author`, `license`, `min_ansible_version` и платформы для автоматической валидации в Galaxy.

### Безопасность и аудит

1. **Минимальные привилегии:** Избегайте `become: true` глобально; используйте `become: false` по умолчанию и `become: true` только для конкретных задач.
2. **Аудит выполнения:** Настройте `callback_whitelist` для логирования всех изменений в journald или внешний SIEM.
3. **Секреты:** Никогда не храните пароли, токены или ключи в `defaults/` или `vars/` — используйте Ansible Vault.

### Change Management

1. **Атомарность:** Каждая роль должна выполнять одно логическое изменение (установка, конфигурация или удаление).
2. **Обратимость:** Включайте задачи отката (`rollback.yml`) для критически важных изменений.
3. **Валидация:** После выполнения роли добавляйте задачу проверки (`validate.yml`) с `changed_when: false`.
4. **Теги:** Используйте теги `pre_deploy`, `deploy`, `rollback`, `validate` для фильтрации этапов change management.

### Observability

1. **Структурированные логи:** Используйте `ansible.builtin.debug` с четкими `msg` для ключевых этапов.
2. **Метрики:** Регистрируйте результаты выполнения задач (`register`) для последующей агрегации в Prometheus/Grafana.
3. **Callback-плагины:** Настройте `json` или `yaml` callback для отправки результатов в централизованный лог-агрегатор.
4. **Вербозность:** Используйте `verbosity` в задачах для контроля объема вывода в production.

### Compliance

1. **Валидация аргументов:** Всегда используйте `meta/argument_specs.yml` для проверки входных параметров.
2. **Документация:** Каждая роль должна иметь README с описанием соответствия требованиям compliance.
3. **Версионирование:** Используйте Git tags для отслеживания изменений, влияющих на compliance.
4. **Аудит:** Настройте `callback_whitelist` для логирования всех изменений во внешний SIEM.

---


## Edge Cases

### Скрытые файлы и каталоги

Ansible игнорирует файлы, начинающиеся с точки (`.gitignore`, `.DS_Store`). Если необходимо скрытые файлы:

```yaml
# Явное копирование скрытых файлов
- name: Copy hidden config
  ansible.builtin.copy:
    src: "files/.app_config"
    dest: /etc/app/.config
    force: true
```

### Символические ссылки в ролях

Ansible **не следует** символические ссылки по умолчанию. Используйте `follow: true`:

```yaml
- name: Follow symlink
  ansible.builtin.copy:
    src: "files/symlinked_config"
    dest: /etc/app/config
    follow: true
```

### Роли с одинаковыми именами

Если две роли имеют одинаковое имя, приоритет определяется порядком в `ansible.cfg`:

```ini
# ansible.cfg
[defaults]
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
```

### Динамические включения в `meta/`

В Ansible 2.18+ поддерживается условная зависимость в `meta/main.yml`:

```yaml
# meta/main.yml
dependencies:
  - role: database
    when: install_database | bool
```

### Выполнение роли в air-gapped среде

**Проблема:** Роль требует доступа к внешним ресурсам (Git, HTTP API, Galaxy) во время выполнения.

**Решение:**
- Перенесите все внешние зависимости в `files/` или локальный репозиторий.
- Используйте `connection: local` для задач, обращающихся к внешним API, и выполняйте их на control node заранее.
- Проверьте отсутствие `uri` и `get_url` модулей без явного указания локальных путей.

### Производительность при большом инвентаре

**Проблема:** Роль выполняет тяжелые задачи без кэширования фактов, что замедляет выполнение на тысячах хостов.

**Решение:**
- Используйте `gather_facts: false` в плейбуке, если факты не нужны.
- Кэшируйте факты через `fact_caching = jsonfile` в `ansible.cfg`.
- Разделяйте тяжелые задачи на отдельные файлы и используйте `include_tasks` с `when`.

### Многоквантовая среда (multi-tenant)

**Проблема:** Одна роль используется в нескольких окружениях (dev/stage/prod) с разными требованиями.

**Решение:**
- Используйте `defaults/main.yml` для общих значений.
- Переопределяйте окружение-специфичные параметры через `group_vars/` или `host_vars/`.
- Используйте `include_vars` для динамической загрузки конфигураций окружения.

### Откат изменений в production

**Проблема:** Необходимость быстрого отката развертывания без полного перезапуска плейбука.

**Решение:**
- Разделите задачи на `deploy.yml` и `rollback.yml`.
- Используйте `meta: end_role` для досрочного завершения при обнаружении проблем.
- Сохраняйте снапшоты конфигураций перед применением изменений.

### Удаление устаревших ролей

```bash
# Просмотр всех установленных ролей
ansible-galaxy role list

# Удаление конкретной роли
ansible-galaxy role uninstall geerlingguy.nginx

# Удаление всех ролей (ОСТОРОЖНО!)
ansible-galaxy role uninstall --all
```

### См. также

- [Создание и использование ролей](usage.md) — подключение ролей, секреты, `delegate_facts`, Windows
- [Управление выполнением и отладка ролей](task-execution-and-debugging.md) — границы директив уровня Role, `debugger`, `check_mode`
- [Стратегии проектирования](strategies.md) — декомпозиция ролей, utility-паттерн
- [Тестирование через Molecule](../ansible_testing_with_molecule.md) — современный подход к QA ролей
- [ansible-lint](../ansible_lint_guide.md) — статический анализ и профили качества
- [ansible-test](../ansible-test.md) — санити-тесты модулей и коллекций
- [Антипаттерны](../ansible_bad_practices.md) — типичные ошибки при структурировании ролей
- [Кроссплатформенные концепции](../CrossPlatform/concepts.md) — Windows- и multi-OS-роли
- [Дрейф конфигурации](../examples/ansible_configuration_drift.md) — сверка роли с реальным состоянием
- [Управление ролями через Git](git_management.md) — альтернативный подход к управлению зависимостями
