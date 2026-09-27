# Продвинутый Jinja2 в SaltStack

## Определения

- **Jinja2**: Шаблонизатор, встроенный в Salt, позволяющий динамически генерировать SLS-файлы и конфигурации на основе Grains, Pillar, переменных окружения и данных Миньонов.
- **Macro**: Переиспользуемый Jinja-блок, определяемый через `{% macro name(args) %}` и вызываемый как функция. Позволяет избежать дублирования шаблонного кода.
- **Import**: Механизм подключения Jinja-макросов или переменных из других файлов через `{% from 'path/to/file.jinja' import variable with context %}` или `{% import 'path/to/file.jinja' as helper %}`.
- **Filter**: Функция преобразования данных в Jinja ( `{{ value | default('fallback') }}`, `{{ list | join(',') }}`, `{{ dict | json }}`).
- **with context**: Директива импорта, передающая контекст текущего шаблона (Grains, Pillar, переменные) в импортируемый файл.
- **load_yaml / load_text**: Salt-фильтры для загрузки YAML/текста из строк: `{{ salt['slsdata.get']('path') | load_yaml }}`.
- **Deferred Rendering**: Рендеринг шаблона Salt происходит в два этапа: сначала Jinja-шаблонизатор, затем Salt-рендерер (YAML). Порядок можно менять через `#!jinja|yaml` или `#!yaml|jinja`.

---

## Основные концепции

### Порядок рендеринга

Salt обрабатывает SLS-файлы в следующем порядке:

1. **Jinja рендерер**: Обработка шаблонных конструкций (`{{ }}`, `{% %}`)
2. **YAML рендерер**: Парсинг результата в структуру данных Salt

Можно изменить порядок через shebang:

```yaml
#!jinja|yaml    # Сначала Jinja, потом YAML (по умолчанию)
#!yaml|jinja    # Сначала YAML, потом Jinja
```

### Область видимости переменных

В Jinja-шаблонах Salt доступны следующие переменные:

| Переменная | Описание | Пример |
|:---|:---|:---|
| `grains` | Grains текущего миньона | `grains['os']`, `grains['os_family']` |
| `pillar` | Pillar текущего миньона | `pillar['nginx']['worker_processes']` |
| `saltenv` | Текущее окружение | `saltenv` |
| `pillarenv` | Текущее Pillar-окружение | `pillarenv` |
| `opts` | Конфигурация миньона | `opts['id']`, `opts['file_roots']` |
| `salt` | Execution modules | `salt['pkg.installed']('nginx')` |
| `sls` | Текущий SLS-путь | `sls` |
| `tls` | TLS certificate data | `tls.cert_info('/path/to/cert')` |

### Jinja vs Salt YAML

Важно различать:

- **Jinja-шаблон**: `{% if grains['os'] == 'Ubuntu' %}...{% endif %}`
- **Salt requisites**: `require`, `watch`, `onchanges` — это не Jinja, а Salt-директивы
- **Salt functions**: `salt['pkg.install']` — вызов execution-модуля внутри Jinja

---

## Практические сценарии

### 1. Макросы (Macros)

**Определение макроса:**

```jinja
{# /srv/salt/_macros/package.jinja #}
{% macro install_package(name, version=None, purge=False) %}
{{ name }}_installed:
  pkg.installed:
    - name: {{ name }}
    {% if version %}
    - version: {{ version }}
    {% endif %}
    {% if purge %}
    - purge: True
    {% endif %}
    - refresh: True
{% endmacro %}

{% macro service_running(name, enable=True) %}
{{ name }}_service:
  service.running:
    - name: {{ name }}
    - enable: {{ enable | lower }}
{% endmacro %}
```

**Использование макроса:**

```yaml
# /srv/salt/webserver/init.sls
{% from '_macros/package.jinja' import install_package, service_running with context %}

{{ install_package('nginx', version='1.18.0') }}
{{ service_running('nginx') }}

php_installed:
  pkg.installed:
    - name: php-fpm

php_service:
  service.running:
    - name: php-fpm
    - enable: True
    - require:
      - pkg: php_installed
```

### 2. Импорт переменных из map.jinja

**Файл map.jinja:**

```jinja
{# /srv/salt/nginx/map.jinja #}
{% set defaults = {
    'package': 'nginx',
    'service': 'nginx',
    'config': '/etc/nginx/nginx.conf',
    'user': 'www-data',
    'worker_processes': 'auto',
    'worker_connections': 1024
} %}

{% set osfamily_map = {
    'Debian': {'user': 'www-data'},
    'RedHat': {'user': 'nginx'}
} %}

{% set os_params = osfamily_map.get(grains.os_family, {}) %}

{% set config = salt['slsdata.utils.merge'](defaults, os_params, pillar.get('nginx', {})) %}
```

**Использование в SLS:**

```yaml
# /srv/salt/nginx/install.sls
{% from 'nginx/map.jinja' import config with context %}

nginx_installed:
  pkg.installed:
    - name: {{ config.package }}

nginx_user:
  user.present:
    - name: {{ config.user }}
    - shell: /sbin/nologin
    - system: True
```

### 3. Условная логика (if/elif/else)

```yaml
# /srv/salt/packages/init.sls
{% set packages = {
    'Debian': ['vim', 'curl', 'htop', 'net-tools'],
    'RedHat': ['vim-enhanced', 'curl', 'htop', 'net-tools'],
    'Suse': ['vim', 'curl', 'htop', 'net-tools']
} %}

{% set os_packages = packages.get(grains.os_family, []) %}

{% for pkg in os_packages %}
{{ pkg }}_installed:
  pkg.installed:
    - name: {{ pkg }}
    - refresh: True
{% endfor %}

{% if grains['os'] == 'Ubuntu' and grains['osrelease'] | int >= 22 %}
ubuntu_unattended_upgrades:
  pkg.installed:
    - name: unattended-upgrades
{% endif %}
```

### 4. Циклы (for) с фильтрами

```yaml
# /srv/salt/users/init.sls
{% set users = pillar.get('users', {}) %}

{% for username, config in users.items() %}
{{ username }}_user:
  user.present:
    - name: {{ username }}
    - uid: {{ config.get('uid', 'auto') }}
    - groups: {{ config.get('groups', []) | join(',') }}
    - shell: {{ config.get('shell', '/bin/bash') }}
    {% if config.get('ssh_key') %}
{{ username }}_ssh_key:
  ssh_auth.present:
    - user: {{ username }}
    - name: {{ config.ssh_key }}
    - config: '{{ config.get('ssh_config', '~/.ssh/authorized_keys') }}'
    {% endif %}
{% endfor %}
```

### 5. Фильтры Jinja

```jinja
{# Значение по умолчанию #}
{{ pillar.get('nginx_port', 80) }}

{# Объединение списков #}
{% set all_groups = groups | join(',') %}

{# Проверка на вхождение #}
{% if 'web' in grains.get('roles', []) %}
  web角色已配置
{% endif %}

{# JSON-сериализация #}
{{ config | tojson }}

{# Регулярные выражения #}
{% if grains['os'] | regex_match('^Ubuntu|Debian$') %}
  Debian-based
{% endif %}

{# Математические операции #}
{% set workers = (grains.num_cpus / 2) | int %}

{# Слайсы списков #}
{% for server in servers[:5] %}
  {{ server }}
{% endfor %}

{# Цепочки фильтров #}
{{ pillar.get('tags', []) | join(' ') | upper }}
```

### 6. Загрузка данных из файлов

```jinja
{# Загрузка YAML из файла #}
{% set yaml_data = salt['cp.get_url']('salt://data/config.yaml') | load_yaml %}

{# Загрузка текста из файла #}
{% set ssl_cert = salt['cp.get_file_str']('salt://certs/server.crt') %}

{# Чтение из Vault #}
{% set vault_secret = salt['vault.read_secret']('secret/data/myapp') %}
```

### 7. Deferred Rendering ( YAML|jinja)

Когда YAML должен быть обработан перед Jinja:

```yaml
#!yaml|yaml
# Сначала Salt парсит YAML, затем Jinja обрабатывает шаблоны
# Полезно когда Jinja зависит от YAML-структур

nginx:
  pkg.installed:
    - name: {{ pillar.get('nginx_package', 'nginx') }}
```

### 8. Обработка ошибок в Jinja

```jinja
{# Проверка существования ключа #}
{% if pillar.get('nginx') is defined %}
  {% set nginx_config = pillar.nginx %}
{% else %}
  {% set nginx_config = {} %}
{% endif %}

{# Try/Except через Salt #}
{% set result = salt['cmd.run']('test -f /etc/nginx/nginx.conf && echo exists') %}
{% if result == 'exists' %}
  nginx_config_exists: True
{% else %}
  nginx_config_exists: False
{% endif %}
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Jinja error: undefined variable` | Переменная не определена в контексте | Использовать `\| default('value')` или проверять `is defined` |
| `TemplateSyntaxError` | Синтаксическая ошибка Jinja | Проверить `{% %}` и `{{ }}`, нет незакрытых блоков |
| Pillar недоступен в Jinja | Pillar не скомпилирован или не назначен | `salt '*' pillar.items`, проверить `top.sls` |
| `with context` не работает | Импорт без контекста | Добавить `with context` в `{% from %}` |
| Порядок рендеринга неверный | Jinja обрабатывает до YAML | Использовать `#!yaml|jinja` если нужно |
| `salt['cmd.run']` не работает | cmd модуль недоступен на мастере | Использовать `salt-call --local` или `file_roots` |
| Макрос не находится | Файл не в `file_roots/_macros/` | Проверить путь, использовать `salt://_macros/name.jinja` |

### Best practices

1. **Макросы в `_macros/`**: Храните переиспользуемые блоки в `_macros/`, а не в корне `file_roots`.
2. **map.jinja обязателен**: Все ОС-зависимые параметры через `map.jinja`, без хардкода.
3. **`| default()`**: Всегда задавайте значения по умолчанию для Pillar-ключей.
4. **Избегайте сложной логики**: Jinja — шаблонизатор, не язык программирования. Сложную логику выносите в execution modules.
5. **Тестируйте шаблоны**: `state.show_sls` для проверки результата рендеринга.
6. **Документируйте макросы**: Docstring в каждом макросе с описанием аргументов.

### Версии и совместимость

| Версия Salt | Особенности Jinja |
|:---|:---|
| 3006 LTS | Jinja2 3.x, `slsdata.get`, `slsdata.utils.merge` |
| 3007 STS | Улучшенные ошибки рендеринга |
| 3008 LTS | Безопасный рендеринг, `SafeDict`/`SafeList` |

### См. также

- [Формулы SaltStack](Formulas.md) — структура и переиспользование
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md) — как SLS компилируется
- [Кастомные модули](Custom_Modules.md) — расширение функционала
