# Ansible — шаблонизация Jinja2

## Определения

**Jinja2** — шаблонизатор для Python, используемый Ansible для динамической генерации текстовых файлов (конфигураций, скриптов, манифестов). Позволяет использовать переменные, условную логику, циклы и фильтры непосредственно внутри файлов.

**Шаблон (Template)** — текстовый файл с расширением `.j2`, содержащий статический текст и вставки Jinja2. В Ansible шаблоны обрабатываются модулем `ansible.builtin.template` на контрольном узле перед отправкой результата на управляемый хост.

**Выражение (Expression)** — фрагмент кода Jinja2, который вычисляется и возвращает результат (например, `{{ 2 + 2 }}`).

**Макрос (Macro)** — переиспользуемый блок шаблона с параметрами, аналог функции в программировании.

**Фильтр (Filter)** — функция, применяемая к переменной через символ `|` для трансформации данных (например, `{{ list | unique }}`).

**Тест (Test)** — функция, проверяющая данные и возвращающая `True`/`False` (например, `{{ var is defined }}`).

**Lookup-плагин** — механизм чтения данных из внешних источников (файлы, базы данных, локальные сервисы, Vault) на контрольном узле во время выполнения playbook.

**Namespace** — механизм изоляции переменных внутри шаблона через блок `{% set ns = namespace(var=value) %}` для избежания конфликтов имён в циклах и макросах.

**Служебная переменная `ansible_managed`** — строка-заголовок, добавляемая в начало сгенерированных файлов для идентификации их происхождения. Настраивается в `ansible.cfg` параметром `ansible_managed`.

---

## Основные концепции

### Переменные и комментарии

Вывод значения переменной: `{{ variable_name }}`.
Доступ к вложенным данным: `{{ my_dict.key }}` или `{{ my_list[0] }}`.

Комментарии (не попадают в итоговый файл):
```jinja
{# Это комментарий Jinja2 #}
```

Присваивание переменных внутри шаблона:
```jinja
{% set service_port = 8080 %}
{% set config = {'enabled': true, 'workers': 4} %}
```

### Специальные директивы

**`set`** — создаёт локальную переменную в scope шаблона:
```jinja
{% set greeting = 'hello' %}
{% set upper_greeting = greeting | upper %}
```

**`namespace`** — создаёт объект для мутации переменных внутри циклов:
```jinja
{% set ns = namespace(max_val=0) %}
{% for item in values %}
  {% if item.value > ns.max_val %}
    {% set ns.max_val = item.value %}
  {% endif %}
{% endfor %}
Max value: {{ ns.max_val }}
```

**`raw` / `endraw`** — вывод текста без обработки Jinja2. Полезно для синтаксисов, совпадающих с Jinja2 (Prometheus, Helm):
```jinja
{% raw %}
{{ prometheus_alert_expression }}
{% endraw %}
```

**`do`** — выполнение выражения с побочным эффектом (например, вызов макроса с `caller` без вывода результата):
```jinja
{% do render_block('Title') %}
```

### Управление пробелами

Jinja2 сохраняет все переносы строк и пробелы по умолчанию. Для контроля отступов используются символы `-`:
- `{%-` — удаляет пробелы и пустые строки перед блоком.
- `-%}` — удаляет пробелы и пустые строки после блока.

Глобальное управление в модуле `ansible.builtin.template` через параметры:
- `trim_blocks: yes` — удаляет первую пустую строку после блока.
- `lstrip_blocks: yes` — удаляет ведущие пробелы у строк до блока.

```jinja
{% if items -%}
    Contains items
{%- endif %}
```

### Условная логика

**Простое условие `if`:**
```jinja
{% if env == 'prod' %}
debug: false
{% elif env == 'dev' %}
debug: true
{% else %}
debug: default
{% endif %}
```

**Условие с `and` / `or` / `not`:**
```jinja
{% if env == 'prod' and enable_ssl %}
ssl: true
{% elif env == 'dev' or env == 'staging' %}
debug: true
{% endif %}
```

**Условие с проверкой списка:**
```jinja
{% if groups['webservers'] | length > 0 %}
# Есть веб-серверы
{% endif %}
```

**Условие с `is in`:**
```jinja
{% if env in ['prod', 'staging'] %}
monitoring: strict
{% endif %}
```

### Циклы

**Базовый цикл `for`:**
```jinja
{% for user in users %}
user: {{ user.name }}
{% endfor %}
```

**Цикл с `loop` объектом:**
```jinja
{% for user in users %}
- {{ loop.index }}. {{ user.name }} ({{ 'active' if user.active else 'inactive' }})
{% endfor %}
```

**Доступные атрибуты `loop`:**
- `loop.index`: Текущая итерация (от 1).
- `loop.index0`: Текущая итерация (от 0).
- `loop.first` / `loop.last`: True, если это первая или последняя итерация.
- `loop.length`: Общее количество элементов.
- `loop.cycle('odd', 'even')`: Чередование значений.

**Цикл со `range` (start, stop, step):**
```jinja
{% for item in range(0, 10, 2) %}
  Item: {{ item }}
{% endfor %}
```

**Вложенные циклы:**
```jinja
{% for group in groups %}
Group: {{ group }}
{% for host in groups[group] %}
  - {{ host }}
{% endfor %}
{% endfor %}
```

**Цикл со `break` / `continue`:**
```jinja
{% for item in items %}
  {% if item.skip %}
    {% continue %}
  {% endif %}
  Processing: {{ item.name }}
{% endfor %}
```

**Цикл с `loop.cycle` для чередования:**
```jinja
{% for item in items %}
server {{ loop.cycle('alpha', 'beta') }} {
    listen {{ item.port }};
}
{% endfor %}
```

### Фильтры и тесты

Фильтры изменяют данные (используется символ `|`), а тесты проверяют их состояние (`is`).

#### Фильтры трансформации

- `default('value', true)`: Значение по умолчанию. Если второй аргумент `true`, фильтр сработает даже если переменная — пустая строка или `False`.
- `combine(other_dict, recursive=True)`: Слияние словарей. Параметр `recursive` позволяет объединять вложенные структуры.
- `regex_replace('pattern', 'replacement')`: Замена подстрок через регулярные выражения.
- `json_query('query_string')`: Выполнение запросов JMESPath к структурам данных (требует библиотеки `jmespath` на контрольном узле).
- `dict2items` / `items2dict`: Преобразование словаря в список пар ключ-значение и обратно. Полезно для циклов по словарям с фильтрацией.
- `ipaddr('address/prefix')`: Работа с IP-адресами (требует библиотеки `netaddr` на контрольном узле). Позволяет проверять валидность, извлекать маски, широковещательные адреса и т.д.
- `extract(variable, key)`: Извлечение значения из словаря или списка по динамическому ключу.
- `map(attribute='name')`: Извлечение атрибута из списка словарей.
- `selectattr('attr', 'op', 'value')`: Фильтрация списка по атрибуту.
- `rejectattr('attr', 'op', 'value')`: Исключение элементов из списка по атрибуту.
- `unique`: Удаление дубликатов из списка.
- `flatten`: Сглаживание вложенных списков.
- `sort`: Сортировка списка.
- `join(', ')`: Объединение списка в строку с разделителем.
- `first` / `last`: Получение первого/последнего элемента списка.
- `random`: Выбор случайного элемента из списка.
- `min` / `max`: Минимальное/максимальное значение в списке.
- `sum`: Сумма элементов списка.
- `count`: Подсчет количества элементов.
- `groupby('key')`: Группировка списка словарей по ключу.
- `map('replace', 'old', 'new')`: Замена в каждом элементе списка.
- `map('int')`: Преобразование всех элементов в целые числа.
- `map('float')`: Преобразование всех элементов в числа с плавающей точкой.

#### Фильтры конвертации форматов

- `to_nice_json` / `to_nice_yaml`: Форматирование структур в читаемый JSON/YAML.
- `from_json` / `from_yaml`: Парсинг строк в объекты.
- `b64encode` / `b64decode`: Кодирование и декодирование Base64.
- `type_debug`: Возвращает тип данных переменной (очень полезно для отладки).
- `to_json` / `to_yaml`: Конвертация в JSON/YAML без форматирования.
- `from_csv`: Парсинг CSV-строки в список.
- `to_csv`: Конвертация списка в CSV-строку.

#### Строковые фильтры

- `upper` / `lower`: Преобразование в верхний/нижний регистр.
- `capitalize` / `title`: Преобразование первой буквы/каждого слова в верхний регистр.
- `trim` / `lstrip` / `rstrip`: Удаление пробелов по краям/слева/справа.
- `replace('old', 'new')`: Замена подстроки (без регулярных выражений).
- `regex_replace('^', '#')`: Добавление префикса к каждой строке.
- `format(*args)`: Форматирование строки (аналог `str.format()`).
- `urlencode`: URL-кодирование строки.
- `wordwrap(width)`: Перенос строк по ширине.
- `truncate(length)`: Обрезка строки до указанной длины.

#### Числовые фильтры

- `int` / `float`: Преобразование в целое число / число с плавающей точкой.
- `round(precision)`: Округление до указанной точности.
- `abs`: Абсолютное значение.
- `min` / `max`: Минимум/максимум (работает с числами и списками).

#### Фильтры для словарей

- `dict2items`: Словарь → список `{key: ..., value: ...}`.
- `items2dict`: Список `{key: ..., value: ...}` → словарь.
- `combine(other_dict)`: Слияние словарей.
- `json_query('key')`: Извлечение значения по JMESPath-запросу.

#### Специальные фильтры

- `shuffle`: Случайное перемешивание списка.
- `random`: Случайный элемент списка.
- `ipaddr('network')`: Работа с IP-адресами (требует `netaddr`).
- `community.general.routeros`: Конвертация для MikroTik API.

#### Фильтры и тесты для версий

Сравнение версий — отдельная задача, потому что строковое сравнение в Python неверно: `'1.10' > '1.9'` даёт `True` посимвольно (`'1' == '1'`, `'1' < '9'` — то есть результат противоположен ожидаемому). Ansible/Jinja решают это отдельным механизмом.

**Тест `version`** (используется с `is`) — форма `is version(other, 'operator')`:

```yaml
# is version — тест
- name: "Обновить только если версия ниже 2.20"
  ansible.builtin.apt:
    name: nginx=1.18.*
    state: present
  when: nginx_installed_version is version('2.20', '<')
  # nginx_installed_version = "1.18.0" → 1.18.0 < 2.20 → true
```

**Фильтр `version_compare`** — форма `value | version_compare(other, 'operator')`. Тот же механизм, но вызывается как фильтр, что удобно, когда результат нужно передать дальше (в `set_fact`, в шаблон, в `assert`):

```yaml
# version_compare — фильтр
- name: "Определить, требуется ли обновление"
  ansible.builtin.set_fact:
    needs_update: "{{ installed_version | version_compare(target_version, '<') }}"
  vars:
    installed_version: "1.10.2"
    target_version: "1.9.8"
  # needs_update = false, т.к. 1.10.2 новее 1.9.8 (строковое сравнение дало бы обратный результат)

- name: "Собрать сводку версий в отчёт"
  ansible.builtin.debug:
    msg: "Обновление {{ 'требуется' if installed_version | version_compare(target_version, '<') else 'не требуется' }}"
```

**Поддерживаемые операторы:** `==`, `!=`, `<`, `<=`, `>`, `>=`, `in` (левая версия входит в правую как префикс с учётом границ компонентов).

**Важные особенности:**

- Сравнение построено на `LooseVersion` и корректно обрабатывает составные версии: `1.9.10` > `1.9.9` (строковое сравнение здесь ломается: `'1' > '9'`).
- Суффиксы учитываются: `2.20-1` < `2.20.1`, `1.0.0rc1` < `1.0.0`.
- Нечисловые сегменты приводятся к строковому сравнению: `1.0.0a` < `1.0.0b`.
- Сравнение всегда строковое-безопасное: значения приводятся к строке, поэтому `version_compare` корректно обрабатывает факты, отданные как числа.
- Опечатка в имени фильтра приводит к ошибке шаблона `no filter found: version_compare` — проверяйте написание при отладке.

**Когда применять:**

| Задача | Механизм |
| :--- | :--- |
| Условный пропуск задачи в `when` | Тест `is version(...)` — читаемее |
| Вычисление значения для `set_fact`/`assert`/шаблона | Фильтр `| version_compare(...)` |
| Сравнение версий пакетов из `package_facts` | Оба варианта применимы |
| Сравнение нестандартных схем (CalVer, SemVer) | Оба варианта, но проверяйте результат на тестовом примере |

#### Популярные тесты

- `is defined` / `is undefined`: Проверка существования.
- `is failed` / `is succeeded`: Проверка статуса выполнения задачи.
- `is version('2.10', '>=')`: Сравнение версий ПО (тест). Фильтр-эквивалент — `| version_compare('2.10', '>=')`.
- `is subset(other_list)`: Проверка, является ли список подмножеством другого.
- `is directory` / `is file`: Проверка типа пути на контрольном узле.
- `is match('pattern')`: Проверка строки по регулярному выражению.
- `is search('pattern')`: Поиск подстроки по регулярному выражению.
- `is contains('substring')`: Проверка наличия подстроки.
- `is odd` / `is even`: Проверка на нечетность/четность.
- `is number`: Проверка, является ли значение числом.
- `is string`: Проверка, является ли значение строкой.
- `is iterable`: Проверка, является ли значение итерируемым объектом.
- `is mapping`: Проверка, является ли значение словарем.
- `is none`: Проверка на `None`.

---

## Предварительные требования

### Версии ПО

- **ansible-core**: 2.20+
- **Jinja2**: 3.1+
- **Python на контрольном узле**: 3.12+
- **Python на управляемом узле**: 3.9+
- **Операционная система**: GNU/Linux (RHEL 9+, Debian 12+, Ubuntu 22.04+)

### Зависимости Python на контрольном узле

```bash
# Установка зависимостей для фильтров и lookup-плагинов
pip install \
  jinja2>=3.1 \
  netaddr>=1.2 \
  jmespath>=1.0
```

### Переменные окружения

```bash
# Отключение проверкиknown hosts для динамических окружений (если требуется)
export ANSIBLE_HOST_KEY_CHECKING=False

# Включение подробного вывода для отладки шаблонов
export ANSIBLE_VERBOSITY=4
```

### Структура проекта

```
project/
├── inventory/
│   ├── production.ini
│   └── staging.ini
├── group_vars/
│   ├── all.yml
│   ├── webservers.yml
│   └── dbservers.yml
├── host_vars/
│   └── db01.example.com.yml
├── roles/
│   └── app/
│       ├── templates/
│       │   ├── config.j2
│       │   └── nginx.conf.j2
│       └── tasks/
│           └── main.yml
└── playbooks/
    └── deploy.yml
```

---

## Архитектура обработки шаблонов

### Жизненный цикл

1. **Парсинг плейбука**: Ansible загружает переменные (inventory, group_vars, host_vars, extra vars, facts).
2. **Резолвинг переменных**: Для каждого хоста формируется полный набор переменных, включая `hostvars` других хостов.
3. **Рендеринг шаблона**: Контрольный узел запускает Jinja2-движок, подставляет переменные, выполняет циклы и условия.
4. **Валидация (опционально)**: Если указан параметр `validate`, Ansible запускает проверочную команду на управляемом узле.
5. **Трансфер**: Готовый файл копируется на управляемый хост через SFTP/SCP.
6. **Установка прав**: Применяются `owner`, `group`, `mode`, SELinux-контекст.

### Контрольный узел vs Управляемый хост

- **Шаблоны и переменные** обрабатываются исключительно на **контрольном узле**.
- **Валидация** выполняется на **управляемом узле** (если указана команда `validate`).
- **Lookup-плагины** выполняются на **контрольном узле**.
- **Факты (facts)** собираются с **управляемого узла** перед задачами.

### Производительность

- Шаблоны рендерятся **для каждого хоста** независимо. При 100 хостах и 10 шаблонах — 1000 рендеров.
- Сложные вычисления в шаблонах замедляют execution. Перенесите подготовку данных в `set_fact` или `vars`.
- Кэширование lookup-плагинов: `lookup('pipe', 'command', wantlist=True)` не кэшируется; используйте `cacheable: true` в кастомных lookup.

---

## Практические сценарии

### Динамическая конфигурация Nginx

#### 1. Переменные в Ansible (`group_vars/webservers.yml`)

```yaml
vhosts:
  - { name: "app1", port: 8080 }
  - { name: "app2", port: 8081 }
enable_compression: true
```

#### 2. Шаблон `templates/nginx.conf.j2`

```jinja
# {{ ansible_managed }}
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    {% if enable_compression -%}
    gzip on;
    gzip_types text/plain application/json;
    {%- endif %}

    {% for host in vhosts %}
    server {
        listen {{ host.port }};
        server_name {{ host.name }}.local;
        location / {
            proxy_pass http://127.0.0.1:{{ host.port + 1000 }};
        }
    }
    {% endfor %}
}
```

#### 3. Использование в плейбуке с валидацией

```yaml
- name: Развертывание конфигурации Nginx
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
    validate: /usr/sbin/nginx -t -c %s
  notify: Restart Nginx
```

### Template module: параметры и валидация

Модуль `ansible.builtin.template` предоставляет параметры для контроля безопасности и идемпотентности:

```yaml
- name: Деплой с полным набором параметров
  ansible.builtin.template:
    src: config.j2
    dest: /etc/app/config.conf
    owner: root
    group: root
    mode: '0600'
    backup: yes
    backup_options:
      name: config.conf.bak
      prefix: .bak.
    validate: /usr/sbin/app -t -c %s
    unsafe_writes: false
    decrypt: true
    seuser: system_u
    serole: object_r
    setype: etc_t
    selevel: s0
```

**Ключевые параметры:**
- `backup: yes` — создаёт резервную копию перед заменой.
- `validate` — команда проверки синтаксиса на целевом хосте. `%s` заменяется на путь к временному файлу.
- `unsafe_writes: false` — гарантирует атомарную запись через временный файл и rename.
- `decrypt: true` — автоматическое расшифровывание, если источник зашифрован Ansible Vault.
- `seuser` / `serole` / `setype` / `selevel` — установка SELinux-контекста на RHEL/CentOS/Fedora.

### Интеграция с HashiCorp Vault

Секреты подставляются в шаблоны через lookup или переменные:

```yaml
- name: Получение секрета из Vault
  ansible.builtin.set_fact:
    db_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/db:password') }}"

- name: Деплой конфигурации с секретом
  ansible.builtin.template:
    src: app.config.j2
    dest: /etc/app/config.conf
    mode: '0600'
    owner: root
    group: root
```

Шаблон `app.config.j2`:
```jinja
database:
  host: {{ db_host }}
  password: {{ db_password }}
```

### Multi-environment шаблонизация

Используйте групповые переменные для разделения окружений:

```yaml
# group_vars/all.yml
app:
  workers: 2
  log_level: INFO

# group_vars/production.yml
app:
  workers: 16
  log_level: WARNING
  monitoring: true

# host_vars/db01.example.com.yml
app:
  db_host: db01.internal
```

Шаблон `app.conf.j2`:
```jinja
[app]
workers = {{ app.workers }}
log_level = {{ app.log_level }}
{% if app.monitoring is defined and app.monitoring %}
metrics_enabled = true
metrics_port = 9090
{% endif %}
db_host = {{ app.db_host | default('localhost') }}
```

### Условные includes и динамический выбор шаблонов

```jinja
{# Выбор шаблона в зависимости от ОС #}
{% if ansible_os_family == 'RedHat' %}
{% include 'redhat/nginx.conf.j2' %}
{% elif ansible_os_family == 'Debian' %}
{% include 'debian/nginx.conf.j2' %}
{% else %}
{% include 'default/nginx.conf.j2' %}
{% endif %}
```

### Продвинутая обработка данных через JMESPath

В сложных проектах фильтрация данных на стороне Ansible становится критически важной для производительности и читаемости. Фильтр `json_query` (основанный на JMESPath) позволяет извлекать нужные фрагменты из массивных JSON-ответов API без использования сложных циклов в Jinja2.

#### Базовый синтаксис JMESPath

- `instances[*].name`: **Проекция** — получение списка всех имен.
- `instances[?status=='running']`: **Фильтрация** — выбор объектов по условию.
- `instances[0:5]`: **Срезы** — первые 5 элементов.
- `instances[*].{ID: id, IP: private_ip}`: **Multi-select Hash** — создание нового объекта с выбранными полями.

#### Практические примеры

**1. Фильтрация и проекция по условию**
Получение IP-адресов работающих инстансов в конкретной зоне:
```jinja
{% set instances = api_response | json_query("instances[?status=='running' && zone=='site-a'].ip_address") %}
```

**2. Сглаживание списков (Flattening)**
Если каждый пользователь имеет список групп, и нам нужен уникальный список всех групп:
```jinja
{% set all_groups = users | json_query("users[*].groups[]") | unique %}
```

**3. Сортировка данных**
Сортировка списка словарей по определенному ключу (например, по приоритету):
```jinja
{% set sorted_items = items | json_query("sort_by(items, &priority)") %}
```

**4. Сложный поиск с логикой "ИЛИ"**
Выбор элементов, у которых статус 'active' ИЛИ тип 'primary':
```jinja
{% set targets = data | json_query("nodes[?status=='active' || type=='primary'].hostname") %}
```

> **Совет:** Для отладки сложных запросов JMESPath используйте онлайн-песочницу [jmespath.org](https://jmespath.org/jpterm.html).

### Отладка шаблонов

#### Отображение типа переменной
```jinja
{# Вывод типа переменной для отладки #}
Type: {{ my_var | type_debug }}
Value: {{ my_var }}
```

#### Условный вывод отладочной информации
```jinja
{% if debug_mode %}
<!-- DEBUG: {{ my_var | to_nice_json }} -->
{% endif %}
```

#### Использование `assert` для валидации
```yaml
- name: Валидация переменных
  ansible.builtin.assert:
    that:
      - my_var is defined
      - my_var | length > 0
      - my_var | int > 0
    fail_msg: "my_var is not valid"
    success_msg: "Validation passed"
```

---

## Плагины доступа к данным (Lookup и Query)

Плагины `lookup` и `query` позволяют считывать данные из внешних источников (файлы, базы данных, API, локальные сервисы, Vault) непосредственно на контрольном узле во время выполнения.

**Ключевое различие:**
- `lookup('plugin', 'arg')`: По умолчанию возвращает строку, где элементы разделены запятыми. Это поведение можно изменить параметром `wantlist=True`, но это менее удобно.
- `query('plugin', 'arg')`: Всегда возвращает **список** (даже если результат один). Это современный стандарт, рекомендуемый для использования в циклах `loop`.

**Популярные плагины:**
- `env`: Чтение переменных окружения контроллера.
- `file`: Чтение содержимого локальных файлов.
- `dict`: Превращает словарь в список словарей с ключами `key` и `value`. Полезно, когда нужно итерироваться по словарю, сохраняя доступ к обоим элементам.
- `url`: Получение данных по HTTP/HTTPS.
- `vars`: Динамический поиск значений переменных по их именам.
- `pipe`: Выполнение shell-команды и возврат stdout.
- `ini`: Чтение INI-файлов.
- `csvfile`: Чтение CSV-файлов.
- `community.hashi_vault.hashi_vault`: Чтение секретов из HashiCorp Vault (устаревший синтаксис `secret=path:key`).
- `community.general.lastpass`: Чтение секретов из LastPass.
- `community.general.onepassword`: Чтение секретов из 1Password.

```jinja
# Использование dict lookup для итерации по сложному словарю
{% for item in query('ansible.builtin.dict', users_data) %}
  User: {{ item.key }}, UID: {{ item.value.uid }}
{% endfor %}

# Чтение файла
SSH_KEY: {{ lookup('ansible.builtin.file', '~/.ssh/id_rsa.pub') }}

# Получение данных из HashiCorp Vault
SECRET: {{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/db:password') }}

# Выполнение shell-команды
HOSTNAME: {{ lookup('pipe', 'hostname -f') }}

# Чтение INI-файла
DB_HOST: {{ lookup('ini', 'host section=database file=/etc/app/config.ini') }}
```

---

## Макросы (Macros)

Макросы позволяют создавать переиспользуемые блоки конфигурации.

### Базовый макрос

```jinja
{% macro render_vhost(port, domain) %}
server {
    listen {{ port }};
    server_name {{ domain }};
    root /var/www/{{ domain }};
}
{% endmacro %}

{{ render_vhost(80, 'example.com') }}
```

### Макрос с defaults

```jinja
{% macro db_config(host, port=5432, dbname='app', user='dbuser') %}
database:
  host: {{ host }}
  port: {{ port }}
  name: {{ dbname }}
  user: {{ user }}
{% endmacro %}

{{ db_config('db01.example.com') }}
{{ db_config('db02.example.com', port=5433, dbname='analytics') }}
```

### Макрос с переменными

```jinja
{% macro render_server(name, port, ssl=false) %}
server {
    listen {{ port }}{{ ' ssl' if ssl else '' }};
    server_name {{ name }}.example.com;

    {% if ssl %}
    ssl_certificate /etc/ssl/{{ name }}.crt;
    ssl_certificate_key /etc/ssl/{{ name }}.key;
    {% endif %}

    location / {
        proxy_pass http://127.0.0.1:{{ port + 1000 }};
    }
}
{% endmacro %}

{{ render_server('api', 443, ssl=true) }}
```

### Макрос с `caller` (блоки)

```jinja
{% macro render_block(title) %}
<div class="block">
    <h2>{{ title }}</h2>
    {{ caller() }}
</div>
{% endmacro %}

{% call render_block('My Title') %}
    <p>This is the block content.</p>
{% endcall %}
```

---

## Составление шаблонов (Template Composition)

### Наследование шаблонов (extends)

Позволяет создавать базовый шаблон и наследовать его.

**Базовый шаблон `base.j2`:**
```jinja
# {{ ansible_managed }}
{% block header %}
# Default header
{% endblock %}

{% block content %}
# Default content
{% endblock %}

{% block footer %}
# Default footer
{% endblock %}
```

**Дочерний шаблон `nginx.j2`:**
```jinja
{% extends 'base.j2' %}

{% block header %}
# Nginx Configuration
# Generated by Ansible
{% endblock %}

{% block content %}
http {
    server {
        listen {{ port }};
        server_name {{ hostname }};
    }
}
{% endblock %}
```

### Включение шаблонов (include)

Позволяет включать другие шаблоны внутри текущего.

```jinja
# Основной шаблон
{{ ansible_managed }}

{% include 'partials/header.j2' %}

{% for vhost in vhosts %}
{% include 'partials/vhost_block.j2' %}
{% endfor %}

{% include 'partials/footer.j2' %}
```

### Импорт макросов (import)

```jinja
{% from 'macros/config.j2' import render_server, render_location %}

{{ render_server('api', 443) }}
{{ render_location('/', 'http://backend:8080') }}
```

---

## Кастомные фильтры (Custom Filters)

Ansible позволяет создавать собственные фильтры через плагины.

### Создание фильтра

Создайте файл `filter_plugins/custom_filters.py`:

```python
def to_camel_case(text):
    """Преобразует snake_case в camelCase."""
    components = text.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])

def to_pascal_case(text):
    """Преобразует snake_case в PascalCase."""
    return ''.join(x.title() for x in text.split('_'))

def hash_md5(text):
    """Возвращает MD5-хеш строки."""
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()

def dict_merge(base, override):
    """Рекурсивно сливает два словаря."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = dict_merge(result[key], value)
        else:
            result[key] = value
    return result

class FilterModule(object):
    def filters(self):
        return {
            'to_camel_case': to_camel_case,
            'to_pascal_case': to_pascal_case,
            'hash_md5': hash_md5,
            'dict_merge': dict_merge,
        }
```

### Использование кастомного фильтра

```yaml
- name: Пример использования кастомного фильтра
  ansible.builtin.debug:
    msg: "{{ 'user_name' | to_camel_case }}"
# Вывод: userName
```

### Использование в шаблоне

```jinja
{# Кастомный фильтр в шаблоне #}
variable_camel: {{ variable_name | to_camel_case }}
```

---

## Операции и команды

### Модуль `ansible.builtin.template`: параметры

| Параметр | Описание |
| :--- | :--- |
| `src` | Путь к шаблону `.j2` на контрольном узле. |
| `dest` | Абсолютный путь к целевому файлу на управляемом узле. |
| `owner` / `group` / `mode` | Права доступа к целевому файлу. |
| `backup` | `yes` — создаёт резервную копию перед заменой. |
| `backup_options` | Дополнительные параметры для бэкапа (`name`, `prefix`). |
| `validate` | Команда проверки синтаксиса на целевом узле. `%s` — путь к временному файлу. |
| `unsafe_writes` | `false` — атомарная запись через временный файл и rename. |
| `decrypt` | `true` — автоматическое расшифровывание Vault-источника. |
| `seuser` / `serole` / `setype` / `selevel` | Установка SELinux-контекста (RHEL-семейство). |
| `force` | `yes` — замена файла даже если dest не является файлом (символическая ссылка, каталог). |

### Полезные команды

```bash
# Проверка синтаксиса Jinja2 (через Python)
python3 -c "import jinja2; jinja2.Template(open('template.j2').read())"

# Просмотр переменных Ansible для хоста
ansible-inventory --host web01

# Просмотр графа групп
ansible-inventory --graph webservers

# Проверка lookup-плагина
ansible -m debug -a "msg={{ lookup('env', 'HOME') }}"

# Тест кастомного фильтра
ansible -m debug -a "msg={{ 'hello_world' | to_camel_case }}"

# Dry-run: показать, какие шаблоны будут изменены
ansible-playbook playbooks/deploy.yml --check --diff

# Отладка с пошаговым выполнением
ansible-playbook site.yml -e "debug_var=true" --step

# Проверка синтаксиса плейбука
ansible-playbook playbooks/deploy.yml --syntax-check
```

---

## Диагностика

### Типичные ошибки

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `UndefinedError: 'variable' is undefined` | Переменная не определена | Проверьте `hostvars`, `set_fact`, `defaults` |
| `TypeError: expected string or bytes-like object` | Фильтр применен к не строке | Используйте `string` фильтр или проверьте тип |
| `TemplateSyntaxError: unexpected '%'` | Ошибка синтаксиса Jinja2 | Проверьте парные теги `{% %}` и `{{ }}` |
| `jinja2.exceptions.Undefined` | Переменная не найдена в scope | Проверьте область видимости переменной |
| `AnsibleError: failed to parse` | Ошибка в YAML перед Jinja2 | Проверьте YAML-синтаксис (отступы, кавычки) |
| `UndefinedError: dict object has no attribute` | Ключ не существует в словаре | Используйте `default` или `is defined` тест |
| `Template data is not a string` | Передан объект вместо строки | Используйте `to_json` / `to_yaml` |
| `lookup plugin not found` | Плагин не установлен | Проверьте `ansible-galaxy collection list` |
| `jmespath.exceptions.JMESPathError` | Ошибка JMESPath-запроса | Проверьте синтаксис на jmespath.org |
| `Permission denied` | Нет прав на чтение файла | Проверьте `become: true` и права доступа |
| `Template validation failed` | Команда `validate` вернула ненулевой код | Проверьте синтаксис конфигурации на целевом хосте |
| `Atomic write failed` | `unsafe_writes: false` + права на каталог | Убедитесь, что Ansible может создавать временные файлы в целевом каталоге |

### Диагностические команды

```bash
# Проверка доступности хостов перед деплоем
ansible all -i inventory.ini -m ping

# Просмотр фактов для проверки готовности
ansible web01 -i inventory.ini -m setup | grep ansible_host

# Проверка запущенных сервисов
ansible web01 -i inventory.ini -m service_facts

# Отображение переменных группы
ansible-inventory --graph webservers

# Проверка синтаксиса конкретного шаблона
python3 -c "import jinja2; t=jinja2.Template(open('roles/app/templates/config.j2').read()); print(t.render(**vars))"

# Проверка наличия Python-зависимостей на контрольном узле
python3 -c "import jinja2, netaddr, jmespath; print('OK')"

# Тест lookup-плагина
ansible localhost -m debug -a "msg={{ lookup('env', 'HOME') }}"

# Проверка прав на целевом каталоге (если Atomic write failed)
ansible web01 -m file -a "path=/etc/app state=directory mode='0755'"
```

---

## Лучшие практики

1. **Централизованное хранение конфигурации** — все изменения конфигураций проходят через Git + playbook. Никаких ручных редактирований на production.
2. **Валидация перед применением** — используйте `validate` в модуле `template` для каждой критической конфигурации. Для Nginx: `nginx -t -c %s`, для BIND: `named-checkconf %s`, для systemd: `systemd-analyze verify %s`.
3. **Идемпотентность** — используйте `backup: yes` для критических файлов. Ansible автоматически пропускает задачу, если контент не изменился.
4. **Атомарные изменения** — обновляйте одну конфигурацию за один playbook run. Сложные изменения разбивайте на stages с проверкой.
5. **Безопасность (Command Injection)** — используйте фильтр `quote` при подстановке переменных в shell-команды внутри шаблонов: `command {{ user_input | quote }}`.
6. **Безопасность (Template Injection)** — никогда не подставляйте недоверенные пользовательские данные в шаблоны без санитизации. Ограничьте используемые фильтры и тесты.
7. **Производительность** — избегайте сложных вычислений в шаблонах. Используйте `set_fact` в плейбуке для подготовки данных.
8. **Зависимости** — если используете фильтры `ipaddr` или `json_query`, убедитесь, что на контрольном узле установлены библиотеки `netaddr` и `jmespath`.
9. **Именование** — используйте расширение `.j2` для всех Jinja2-шаблонов.
10. **Читаемость** — используйте `{%-` и `-%}` для управления пробелами, чтобы избежать пустых строк в выводе.
11. **Разделение окружений** — отдельные inventory, переменные, credentials для dev/staging/prod.
12. **SELinux** — для RHEL-семейства всегда указывайте `setype`, `seuser`, `serole` для конфигурационных файлов.
13. **Динамические includes** — используйте `{% include %}` с условиями для поддержки multi-OS окружений.
14. **Мониторинг изменений** — включайте `diff: yes` в playbook для отслеживания изменений конфигураций.
15. **Тестирование** — используйте `ansible-playbook --syntax-check` и Molecule + Docker для тестирования ролей перед продом.

---

## Дополнительная информация

### Связанные разделы

- [Основные концепции Ansible](./ansible_core_concepts.md) — общие концепции Ansible, включая базовое использование переменных и шаблонов.
- [Модули управления файлами](./Modules/ansible_file_management_modules.md) — модули `template`, `copy`, `lineinfile`, `blockinfile` для работы с файлами.
- [Ansible: безопасность](./ansible_security_best_practices.md) — хранение секретов, HashiCorp Vault, Ansible Vault.

### Стандарты и документация

- [Официальная документация Jinja2](https://jinja.palletsprojects.com/) — полный справочник по синтаксису Jinja2.
- [JMESPath Specification](https://jmespath.org/specification.html) — спецификация языка запросов JMESPath.
- [Ansible Template Module](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/template_module.html) — документация модуля `ansible.builtin.template`.
