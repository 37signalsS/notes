# Формулы SaltStack

## Определения

- **Formula**: Переиспользуемый пакет состояний (SLS-файлов) с предсказуемой структурой каталогов, предназначенный для управления конкретным компонентом инфраструктуры (nginx, postgresql, docker). Хранится в `file_roots` и подключается через `include`.
- **map.jinja**: Шаблон Jinja в корне formula, определяющий параметры по умолчанию и маппинг имён пакетов/сервисов для разных ОС (Debian/RedHat/Suse). Загружается через `{% from 'nginx/map.jinja' import nginx with context %}`.
- **defaults.yaml**: Файл с параметрами по умолчанию для formula. Подключается из `map.jinja` и содержит конфигурацию, которую можно переопределить через Pillar или Grains.
- **osfamily_map**: Словарь в `map.jinja`, сопоставляющий `grains['os_family']` с именами пакетов, сервисов и путями для каждой ОС.
- **Formula Repository**: Git-репозиторий с набором formulas для совместного использования (https://github.com/saltstack-formulas).
- **Include**: Механизм подключения SLS-файлов из других formula в текущий state-файл.

---

## Основные концепции

### Стандартная структура Formula

```
/srv/salt/
└── nginx/
    ├── init.sls           # Точка входа: включает все компоненты
    ├── install.sls        # Установка пакета
    ├── config.sls         # Управление конфигурацией
    ├── service.sls        # Управление сервисом
    ├── map.jinja          # Маппинг ОС-зависимых параметров
    ├── defaults.yaml      # Параметры по умолчанию
    ├── pillar.example     # Пример Pillar для переопределения
    ├── README.md          # Документация
    └── test/
        └── init.sls       # Тестовый state для проверки formula
```

### Иерархия приоритетов параметров

Параметры formula разрешаются в следующем порядке (от низшего к высшему):

1. **defaults.yaml** — значения по умолчанию
2. **osfamily_map** в `map.jinja` — ОС-зависимые переопределения
3. **Pillar** — пользовательские переопределения
4. **Grains** — динамические переопределения на основе данных миньона
5. **Literals** — жёстко заданные значения в SLS

### Механизм map.jinja

`map.jinja` использует встроенный Salt-модуль `slsdata.utils.merge` для слияния словарей:

```jinja
{# /srv/salt/nginx/map.jinja #}
{% set _default_config = salt['slsdata.get']('nginx/defaults.yaml') %}

{% set osfamily_map = salt['slsdata.get']('nginx/osfamily_map.yaml') %}

{% set config = salt['slsdata.utils.merge'](
    _default_config,
    osfamily_map.get(grains.os_family, {}),
    pillar.get('nginx', {}),
    grain='id'
) %}
```

### Подключение Formula в top.sls

```yaml
# /srv/salt/top.sls
base:
  'role:web':
    - match: grain
    - nginx
    - nginx.ssl

  'role:db':
    - match: grain
    - postgresql
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

**osfamily_map.yaml:**

```yaml
# /srv/salt/nginx/osfamily_map.yaml
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
{% set defaults = salt['slsdata.get']('nginx/defaults.yaml') %}
{% set os_map = salt['slsdata.get']('nginx/osfamily_map.yaml') %}

{% set osfamily_params = os_map.get(grains.os_family, {}) %}

{% set config = salt['slsdata.utils.merge'](
    defaults,
    osfamily_params,
    pillar.get('nginx', {})
) %}
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
{% from 'nginx/map.jinja' import nginx with context %}

nginx_package:
  pkg.installed:
    - name: {{ nginx.package }}
    - refresh: True
```

**config.sls:**

```yaml
# /srv/salt/nginx/config.sls
{% from 'nginx/map.jinja' import nginx with context %}

nginx_config_file:
  file.managed:
    - name: {{ nginx.config_file }}
    - source: salt://nginx/files/nginx.conf.jinja
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
{% from 'nginx/map.jinja' import nginx with context %}

nginx_service:
  service.running:
    - name: {{ nginx.service }}
    - enable: True
    - require:
      - pkg: nginx_package
```

**pillar.example:**

```yaml
# /srv/salt/nginx/pillar.example
nginx:
  worker_processes: 4
  worker_connections: 2048
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
  - php-fpm
  - letsencrypt

webserver_config:
  file.managed:
    - name: /etc/nginx/conf.d/webserver.conf
    - source: salt://webserver/files/webserver.conf
    - template: jinja
    - require:
      - pkg: nginx_package
      - pkg: php_fpm_package
```

### 3. Переопределение параметров через Pillar

```yaml
# /srv/pillar/webserver/init.sls
nginx:
  worker_processes: 8
  worker_connections: 4096

  vhosts:
    app.example.com:
      server_name: app.example.com
      listen: 443
      ssl: True
      ssl_cert: /etc/letsencrypt/live/app.example.com/fullchain.pem
      ssl_key: /etc/letsencrypt/live/app.example.com/privkey.pem
```

### 4. GitFS для хранения Formulas

```yaml
# /etc/salt/master
fileserver_backend:
  - roots
  - gitfs

gitfs_remotes:
  - https://github.com/saltstack-formulas/nginx-formula.git
  - https://github.com/saltstack-formulas/docker-formula.git

# Кэширование и обновление
gitfs_update_interval: 300
```

```bash
# Принудительное обновление кэша
salt-run fileserver.clear_cache
# → Cache cleared successfully

# Проверка доступных формул
salt-run fileserver.dir_list
# → ['nginx', 'docker', 'postgresql', ...]
```

### 5. Версионирование Formula через Git

```bash
# Инициализация репозитория
cd /srv/salt
git init formulas
cd formulas
git add nginx/
git commit -m "Add nginx formula v1.0"

# Добавление remote
git remote add origin git@salt-master:formulas.git
git push -u origin master

# Теги для версий
git tag -a v1.0 -m "Stable nginx formula"
git push --tags
```

```yaml
# /etc/salt/master — привязка к ветке/тегу
gitfs_remotes:
  - https://github.com/org/formulas.git:
    - base: main
    - saltenv:
      - dev:
        - ref: develop
      - prod:
        - ref: main
```

### 6. Тестирование Formula

```bash
# Локальная проверка
salt-call --local state.apply nginx test=True

# Проверка на конкретном окружении
salt 'web-*' state.apply nginx saltenv=dev test=True

# Интеграционное тестирование (serverspec)
salt 'web-01' state.apply nginx
ssh web-01 'curl -s http://localhost/ | grep -q "Welcome to nginx"'
# → True
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Jinja error: template not found` | Неверный путь в `source` или `include` | Проверить путь относительно `file_roots`, использовать `salt://` |
| Formula не находит параметры | `map.jinja` не подключён | `{% from 'formula/map.jinja' import var with context %}` |
| Конфликт имён state IDs | Две formula используют одинаковые ID | Использовать уникальные префиксы: `nginx_config`, `php_config` |
| Pillar не переопределяет defaults | Pillar не назначен миньону | Проверить `top.sls` в `pillar_roots` |
| GitFS не обновляется | Кэш не синхронизирован | `salt-run fileserver.clear_cache`, проверить `gitfs_update_interval` |
| `slsdata.get` не находит файл | Файл не в `file_roots` или неверное имя | Проверить путь, использовать полный путь `salt://nginx/defaults.yaml` |

### Best practices

1. **Одна formula — один компонент**: Не объединяйте nginx и php-fpm в одну formula.
2. **map.jinja обязателен**: Все параметры через map.jinja, без хардкода в SLS.
3. **defaults.yaml**: Всегда задавайте значения по умолчанию для портируемости.
4. ** pillar.example**: Предоставляйте пример Pillar для пользователей formula.
5. **include вместо копирования**: Используйте `include` для переиспользования SLS.
6. **Уникальные state IDs**: Префиксы по имени formula: `nginx_config`, `php_config`.
7. **Версионирование**: Используйте Git-теги для обозначения стабильных версий.
8. **Тестирование**: Всегда проверяйте через `test=True` перед деплоем.

### См. также

- [Кастомные модули](Custom_Modules.md) — расширение функционала Salt
- [Продвинутый Jinja2](Advanced_Jinja2.md) — шаблонизация в SLS
- [Тестирование состояний](Testing_States.md) — CI/CD для Salt states
