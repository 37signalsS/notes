**Актуально для:** Salt 3006 LTS

# Формулы SaltStack

## Определения

- **Formula**: Переиспользуемый пакет состояний (SLS-файлов) с предсказуемой структурой каталогов, предназначенный для управления конкретным компонентом инфраструктуры (nginx, postgresql, docker). Хранится в `file_roots` и подключается через `include` или `top.sls`.
- **map.jinja**: Шаблон Jinja в корне formula, собирающий параметры из `defaults.yaml`, `osfamilymap.yaml`, Grains и Pillar. Экспортирует единую переменную (обычно `mapdata`) для использования в SLS-файлах. Загружается через `{% from 'formula/map.jinja' import mapdata with context %}`.
- **defaults.yaml**: YAML-файл с базовыми параметрами formula. Подключается из `map.jinja` через `{% import_yaml 'formula/defaults.yaml' as defaults %}` и может быть переопределён через Pillar.
- **osfamilymap.yaml**: YAML-файл с ОС-зависимыми параметрами (имена пакетов, сервисов, пути). Сопоставляется с `grains['os_family']` через `salt['grains.filter_by']`.
- **Formula Repository**: Git-репозиторий с набором formulas для совместного использования (https://github.com/saltstack-formulas).
- **Include**: Механизм подключения SLS-файлов из других formulas в текущий state-файл.
- **TOFS (Template Formula Structure)**: Современная структура каталогов, использующая `files/` с подкаталогами `default/`, `os_family/` и т.п. для организации шаблонов конфигураций.

---

## Архитектура и принцип работы

### Жизненный цикл formula

1. **Создание репозитория** — formula оформляется как отдельный Git-репозиторий в организации `saltstack-formulas` или локальная директория в `file_roots`.
2. **Развёртывание на Master** — formula добавляется в `file_roots` (локально) или в `gitfs_remotes` (через GitFS).
3. **Таргетинг через top.sls** — миньоны назначаются на formula через `top.sls` по grains, FQDN или wildcard.
4. **Компиляция map.jinja** — при рендеринге SLS Salt загружает `map.jinja`, который объединяет defaults, osfamilymap и Pillar в единый словарь `mapdata`.
5. **Применение состояний** — SLS-файлы используют `mapdata` для параметризованного управления пакетами, конфигурациями и сервисами.

### Стандартная структура Formula

Современная структура formula (TOFS — Template Formula):

```
/srv/salt/
└── nginx/                          # root formula, имя = tplroot
    ├── init.sls                    # Точка входа: включает компоненты
    ├── map.jinja                   # Объединение defaults + osmap + pillar → mapdata
    ├── defaults.yaml               # Базовые параметры по умолчанию
    ├── osfamilymap.yaml            # ОС-зависимые параметры (Debian/RedHat/Suse)
    ├── pillar.example              # Пример Pillar для переопределения
    ├── README.rst                  # Документация формулы
    ├── CHANGELOG.rst               # Журнал изменений
    ├── VERSION                     # Версия formula
    └── files/
        └── default/
            └── etc/
                └── nginx/
                    └── nginx.conf.jinja   # Шаблон конфигурации
```

Для локального развёртывания:

```
/srv/salt/
├── nginx/
│   ├── init.sls
│   ├── map.jinja
│   ├── defaults.yaml
│   ├── osfamilymap.yaml
│   └── files/
└── top.sls
```

### Иерархия приоритетов параметров

Параметры formula разрешаются в следующем порядке (от низшего к высшему приоритетом):

1. **defaults.yaml** — значения по умолчанию, загружаются через `{% import_yaml %}`
2. **osfamilymap.yaml** — ОС-зависимые переопределения, выбираются через `grains.filter_by` по `os_family`
3. **osmap.yaml** / **osfingermap.yaml** — более точечные переопределения по `os` и `osfinger`
4. **Pillar** — пользовательские переопределения через `salt['pillar.get']('formula:lookup')`
5. **Grains** — динамические переопределения на основе данных миньона
6. **Literals** — жёстко заданные значения в SLS

Слияние выполняется через `salt['grains.filter_by']` с параметром `merge=`, который рекурсивно объединяет словари. Окончательное объединение с Pillar происходит через `salt['pillar.get']('formula', default=defaults, merge=True)`.

### Механизм map.jinja (стандартный паттерн)

В современных formula используется следующий паттерн `map.jinja`:

```jinja
{# /srv/salt/nginx/map.jinja #}
{%- import_yaml 'nginx/defaults.yaml' as default_settings %}
{%- import_yaml 'nginx/osfamilymap.yaml' as osfamilymap %}
{%- import_yaml 'nginx/osmap.yaml' as osmap %}
{%- import_yaml 'nginx/osfingermap.yaml' as osfingermap %}

{%- set mapdata = salt['grains.filter_by'](default_settings,
    default='nginx',
    merge=salt['grains.filter_by'](osfamilymap, grain='os_family',
      merge=salt['grains.filter_by'](osmap, grain='os',
        merge=salt['grains.filter_by'](osfingermap, grain='osfinger',
            merge=salt['pillar.get']('nginx:lookup', default={})
        )
      )
    )
) %}

{%- set mapdata = salt['pillar.get']('nginx', default=mapdata, merge=True) %}
```

Ключевые изменения по сравнению с устаревшим паттерном:
- `{% import_yaml 'formula/file.yaml' as name %}` заменяет несуществующий `salt['slsdata.get']`
- `salt['slsutil.merge']` или встроенный `merge=` параметр `grains.filter_by` заменяют `salt['slsdata.utils.merge']`
- Иерархия источников: defaults → osfamilymap → osmap → osfingermap → pillar lookup → pillar override

### Альтернативный подход — slsutil.renderer

Для более сложных сценариев (например, formula на Python-рендерере) можно использовать `salt['slsutil.renderer']`:

```jinja
{% set mapdata = salt['slsutil.renderer']('nginx/map.sls') %}
```

---

## Практические сценарии

### 1. Создание Formula для Nginx

**defaults.yaml:**

```yaml
# /srv/salt/nginx/defaults.yaml
nginx:
  package: nginx
  service: nginx
  config_dir: /etc/nginx
  config_file: /etc/nginx/nginx.conf
  vhosts_dir: /etc/nginx/conf.d
  user: www-data
  worker_processes: auto
  worker_connections: 1024
  keepalive_timeout: 65
  log_dir: /var/log/nginx
  pid_file: /run/nginx.pid
```

**osfamilymap.yaml:**

```yaml
# /srv/salt/nginx/osfamilymap.yaml
Debian:
  package: nginx
  service: nginx
  user: www-data
  config_dir: /etc/nginx
RedHat:
  package: nginx
  service: nginx
  user: nginx
  config_dir: /etc/nginx
Suse:
  package: nginx
  service: nginx
  user: nginx
  config_dir: /etc/nginx
```

**map.jinja:**

```jinja
{# /srv/salt/nginx/map.jinja #}
{%- import_yaml 'nginx/defaults.yaml' as default_settings %}
{%- import_yaml 'nginx/osfamilymap.yaml' as osfamilymap %}

{%- set mapdata = salt['grains.filter_by'](default_settings,
    default='nginx',
    merge=salt['grains.filter_by'](osfamilymap, grain='os_family',
        merge=salt['pillar.get']('nginx:lookup', default={})
    )
) %}

{%- set mapdata = salt['pillar.get']('nginx', default=mapdata, merge=True) %}
```

**init.sls:**

```yaml
# /srv/salt/nginx/init.sls
include:
  - nginx.install
  - nginx.config
  - nginx.service
```

**install.sls:**

```yaml
# /srv/salt/nginx/install.sls
{% from 'nginx/map.jinja' import mapdata with context %}

nginx_package:
  pkg.installed:
    - name: {{ mapdata.package }}
    - refresh: True
```

**config.sls:**

```yaml
# /srv/salt/nginx/config.sls
{% from 'nginx/map.jinja' import mapdata with context %}

nginx_config_file:
  file.managed:
    - name: {{ mapdata.config_file }}
    - source: salt://nginx/files/default/etc/nginx/nginx.conf
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - pkg: nginx_package
    - watch_in:
      - service: nginx_service
```

**service.sls:**

```yaml
# /srv/salt/nginx/service.sls
{% from 'nginx/map.jinja' import mapdata with context %}

nginx_service:
  service.running:
    - name: {{ mapdata.service }}
    - enable: True
    - require:
      - pkg: nginx_package
```

**pillar.example:**

```yaml
# /srv/pillar/nginx/pillar.example
# Скопируйте содержимое в /srv/pillar/nginx/init.sls и измените при необходимости

nginx:
  lookup:
    package: nginx
    service: nginx
    user: nginx
    worker_processes: 4
    worker_connections: 4096
    keepalive_timeout: 75
    vhosts:
      web-01:
        server_name: example.com
        listen: 80
        root: /var/www/html
```

### 2. Подключение Formula через include

```yaml
# /srv/salt/webserver/init.sls
include:
  - nginx
  - nginx.config
  - php

webserver_vhost:
  file.managed:
    - name: /etc/nginx/conf.d/webserver.conf
    - source: salt://webserver/files/webserver.conf.jinja
    - template: jinja
    - require:
      - pkg: nginx_package
    - watch_in:
      - service: nginx_service
```

### 3. Переопределение параметров через Pillar

```yaml
# /srv/pillar/webserver/init.sls
nginx:
  lookup:
    worker_processes: 8
    worker_connections: 8192

  # Полные overrides (merge=True)
  vhosts:
    app.example.com:
      server_name: app.example.com
      listen: 443
      ssl: True
      ssl_cert: /etc/letsencrypt/live/app.example.com/fullchain.pem
      ssl_key: /etc/letsencrypt/live/app.example.com/privkey.pem
```

### 4. Подключение собственной Formula

Локальная formula добавляется в `file_roots` мастера:

```yaml
# /etc/salt/master
file_roots:
  base:
    - /srv/salt
    - /srv/formulas/nginx-formula
  dev:
    - /srv/salt
    - /srv/formulas/nginx-formula_dev
  prod:
    - /srv/salt
    - /srv/formulas/nginx-formula_prod
```

### 5. GitFS для хранения Formulas

```yaml
# /etc/salt/master
fileserver_backend:
  - roots
  - gitfs

gitfs_remotes:
  - https://github.com/saltstack-formulas/nginx-formula.git
  - https://github.com/saltstack-formulas/docker-formula.git

# Использование all_saltenvs для единого branch/tag во всех окружениях
gitfs_remotes:
  - https://github.com/org/formulas.git:
      - all_saltenvs: True
```

```bash
# Принудительное обновление кэша GitFS
salt-run fileserver.clear_cache
# → Cache cleared successfully

# Проверка доступных формул
salt-run fileserver.dir_list
# → ['nginx', 'docker', 'postgresql', ...]

# Просмотр доступных файлов в конкретной formula
salt-run fileserver.file_list nginx
# → ['init.sls', 'map.jinja', 'defaults.yaml', ...]
```

### 6. Версионирование Formula через Git

```bash
# Инициализация репозитория
cd /srv/salt
git init
git add nginx/
git commit -m "Add nginx formula v1.0"

# Добавление remote
git remote add origin git@salt-master:formulas.git
git push -u origin main

# Теги для версий
git tag -a v1.0 -m "Stable nginx formula"
git push --tags
```

```yaml
# /etc/salt/master — привязка к ветке/тегу для разных saltenv
gitfs_remotes:
  - https://github.com/org/formulas.git:
      - base: main
        saltenv:
          - dev:
              - ref: develop
          - prod:
              - ref: main
```

### 7. Структура параметров Pillar (рекомендованный паттерн)

Официальная рекомендация Salt — использовать вложенный ключ `lookup` для всех параметров formula:

```yaml
# /srv/pillar/nginx/init.sls
nginx:
  lookup:
    package: nginx
    service: nginx
    user: nginx          # Переопределение для этого миньона
    worker_processes: 4  # Переопределение количества воркеров
  vhosts:                # Полные данные через merge=True
    example.com:
      listen: 443
      ssl: True
```

Это позволяет разделить:
- `lookup` — точечные переопределения (слияние через `filter_by`)
- верхний уровень — полные замены (слияние через `pillar.get(..., merge=True)`)

---

## Операции и команды

### Управление formula

| Команда | Описание |
|:---|:---|
| `salt '*' state.apply nginx` | Применить formula `nginx` на все миньоны |
| `salt '*' state.apply nginx saltenv=dev` | Применить formula из конкретного saltenv |
| `salt '*' state.apply nginx test=True` | Dry-run: показать изменения без применения |
| `salt '*' state.show_sls nginx` | Показать скомпилированный SLS (результат Jinja + YAML) |
| `salt '*' state.show_highstate` | Показать полный highstate для миньона |
| `salt '*' state.show_lowstate` | Показать low state (плоский список функций) |
| `salt '*' saltutil.sync_states` | Синхронизация кастомных state-модулей |

### Управление GitFS

| Команда | Описание |
|:---|:---|
| `salt-run fileserver.clear_cache` | Очистить кэш файлового сервера |
| `salt-run fileserver.clear_filesystem_cache` | Полная очистка кэша (включая GitFS) |
| `salt-run fileserver.dir_list` | Список доступных formula/директорий |
| `salt-run fileserver.file_list <formula>` | Список файлов в конкретной formula |
| `salt '*' saltutil.refresh_fileserver` | Принудительно обновить файловый сервер на миньонах |

### Проверка и отладка

| Команда | Описание |
|:---|:---|
| `salt '*' saltutil.refresh_pillar` | Перезагрузить Pillar на миньонах |
| `salt '*' pillar.items` | Показать назначенный Pillar для миньона |
| `salt '*' grains.items` | Показать Grains миньона |
| `salt '*' saltutil.show_version` | Показать версию Salt на миньонах |
| `salt '*' cp.list_master` | Список файлов на Master (file_roots) |

### Валидация

После создания или изменения formula обязательно выполните проверки:

```bash
# 1. Проверка синтаксиса SLS
salt '*' state.show_sls nginx saltenv=base --out=yaml

# → Должен отобразиться YAML без ошибок Jinja

# 2. Dry-run перед применением
salt 'web-*' state.apply nginx test=True --state-output=changes

# → Должен показывать требуемые изменения

# 3. Проверка Pillar
salt '*' pillar.items 'nginx'

# → Должен показывать значения из mapdata
```

---

## Устранение неполадок

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Jinja error: template not found` | Неверный путь в `source` или `include` | Проверить путь относительно `file_roots`, использовать `salt://` |
| Formula не находит параметры | `map.jinja` не подключён или переменная не экспортирована | `{% from 'formula/map.jinja' import mapdata with context %}` |
| `mapdata` пустой или None | `defaults.yaml` не в `file_roots` или неверное имя | Проверить путь, использовать `{% import_yaml 'formula/defaults.yaml' as name %}` |
| Конфликт имён state IDs | Две formula используют одинаковые ID | Использовать уникальные префиксы: `nginx_config`, `php_config` |
| Pillar не переопределяет defaults | Pillar не назначен миньону или ключ `lookup` не используется | Проверить `top.sls` в `pillar_roots`, использовать паттерн `nginx: lookup:` |
| GitFS не обновляется | Кэш не синхронизирован | `salt-run fileserver.clear_cache`, проверить `gitfs_update_interval` |
| `grains.filter_by` возвращает None | osfamilymap пуст для данной ОС | Добавить ветку для `os_family`, проверить `salt '*' grains.get os_family` |
| `merge` не работает для вложенных ключей | Использован `.update()` вместо рекурсивного слияния | Использовать `merge=` параметр `grains.filter_by` или `salt['slsutil.merge']` |
| Файлы из `files/` не доступны | Путь не начинается с `salt://` | Использовать `salt://formula/files/default/...` |
| `salt['slsutil.renderer']` не работает | Minion версии < 2018.3.0 | Использовать `slsutil` либо `import_yaml` |

### Диагностика map.jinja

Если `mapdata` содержит неверные значения:

```bash
# Проверка загруженных YAML
salt '*' state.show_sls nginx init saltenv=base --out=yaml | head -20

# Просмотр mapdata напрямую
salt '*' state.apply nginx test=True --state-output=all
```

### Ограничения и известные проблемы

1. **Безопасность GitFS**: Pull-запросы из upstream-репозиториев автоматически применяются при обновлении кэша. Всегда форкайте формулы в собственный аккаунт GitHub.
2. **Синхронизация Pillar**: `merge=True` в `salt['pillar.get']` выполняет поверхностное слияние. Для глубокого слияния используйте `strategy='recurse'` и `merge_lists=True`.
3. **ОС-зависимости**: `grains.filter_by` использует `os_family` по умолчанию, но для более точного таргетинга используйте `osfinger` (например, `Ubuntu-22.04` vs `Debian-12`).
4. **GitFS и большие репозитории**: Репозитории >100МБ замедляют обновление кэша. Используйте `gitfs_envs` для ограничения сред.

---

## Рекомендованные практики

1. **Одна formula — один компонент**: Не объединяйте nginx и php-fpm в одну formula. Каждый компонент — отдельная formula.
2. **map.jinja обязателен**: Все параметры через `map.jinja`, без хардкода в SLS. Экспортировать единую переменную `mapdata`.
3. **defaults.yaml**: Всегда задавайте значения по умолчанию для портируемости. Используйте `{% import_yaml %}` для загрузки.
4. **osfamilymap.yaml**: Покрывайте все поддерживаемые ОС (Debian, RedHat, Suse, Arch, Alpine).
5. **pillar.example**: Предоставляйте пример Pillar с `lookup` ключом для пользователей formula.
6. **include вместо копирования**: Используйте `include` для переиспользования SLS.
7. **Уникальные state IDs**: Префиксы по имени formula: `nginx_config`, `php_config`.
8. **Версионирование**: Используйте Git-теги для обозначения стабильных версий. Форкайте upstream-репозитории.
9. **Тестирование**: Всегда проверяйте через `test=True` перед деплоем. Используйте `salt-lint` и `yamllint`.
10. **TOFS структура files/**: Используйте структуру `files/default/`, `files/os_family/` для управления шаблонами конфигураций.
11. **Single-purpose SLS**: Каждый `.sls` файл должен выполнять одну задачу (install, config, service).
12. **Наблюдаемость**: Добавляйте `event.send` в SLS для отслеживания изменений через Salt Event Bus.

---

## Дополнительная информация

### Полезные утилиты

| Утилита | Описание |
|:---|:---|
| **salt-lint** | Линтер для SLS-файлов: проверка синтаксиса YAML, стиевых ошибок и best practices. Установка: `pip install salt-lint` |
| **yamllint** | Линтер для проверки YAML-синтаксиса |
| **pre-commit** | Фреймворк для запуска проверок перед коммитом |
| **testinfra** | Интеграционное тестирование конечного состояния системы |

### Шаблон линтера salt-lint

```yaml
# .salt-lint
exclude:
  - '.git'
  - '.kitchen'
  - '.travis.yml'
  - 'Gemfile'
rules:
  204:
    message: "Line too long"
    level: "warning"
    max_length: 160
```

### Ссылки

- [Официальная документация Salt Formulas](https://docs.saltproject.io/en/3006/topics/development/conventions/formulas.html)
- [saltstack-formulas на GitHub](https://github.com/saltstack-formulas)
- [template-formula (скелет для новых formulas)](https://github.com/saltstack-formulas/template-formula)
- [Map files — Salt User Guide](https://docs.saltproject.io/salt/user-guide/en/latest/topics/map-files.html)

### См. также

- [Продвинутый Jinja2](Advanced_Jinja2.md) — шаблонизация в SLS и map.jinja
- [Тестирование состояний](Testing_States.md) — CI/CD для Salt states
- [Pillar — продвинутые темы](Pillar_Advanced.md) — управление секретами и параметрами
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md) — как SLS компилируется
- [Архитектура SaltStack](Architecture.md) — Master/Minion, Grains, Pillar
