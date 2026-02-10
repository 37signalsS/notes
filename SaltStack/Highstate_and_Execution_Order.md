# Highstate и порядок выполнения

## Что такое Highstate

Highstate в Salt — это выполнение полного набора состояний (states), сопоставленных minion через файл верхнего уровня top.sls. Во время highstate Salt компилирует все указанные SLS в единый граф зависимостей и исполняет его с учетом заданного порядка и связей. Это обеспечивает идемпотентное приведение узла к целевому состоянию.

Запуск:

*   локально с minion: salt-call state.highstate
*   через master: salt 'web*' state.highstate

Для частичного применения: salt 'web1' state.apply nginx

Режим проверки без изменений: test=True.

## Top-файл и таргетинг

Файл top.sls определяет, какие SLS применяются к каким minion. Сопоставление выполняется по выражениям таргетинга.

Пример:

```markdown
base:
  'role:web':
    - match: grain
    - nginx
    - app.frontend
  'G@os:Ubuntu and L@web1,web2':
    - match: compound
    - hardening.ssh
```

*   base — окружение (saltenv).
*   match задает тип сопоставления (grain, compound и др.).
*   Значения — имена SLS-файлов без расширения.

## Порядок исполнения: граф, а не список

Порядок выполнения в Salt определяется не позицией в файле, а графом зависимостей. Если зависимостей нет, Salt строит упорядоченный набор с учетом явных правил order и может выполнять независимые состояния в произвольной последовательности, сохраняя детерминированность по числовому order.

Ключевые механизмы управления порядком:

*   requisites (require, watch, onchanges, prereq и их _in-варианты)
*   директивы include/extend
*   атрибут order

## Реквизиты: сравнение

| Реквизит | Когда срабатывает | Назначение |
|---|---|---|
| require | Всегда | Гарантирует, что зависимость выполнена раньше |
| watch | При изменении зависимого state | Триггерит модульный mod_watch (часто рестарт сервиса) |
| onchanges | При изменении зависимого state | Выполняет state, если были изменения у зависимого |
| prereq | Всегда | Обеспечивает пред- и пост-выполнение парой |
| use | Всегда | Наследует параметры из другого state |
| *_in | Обратная запись реквизита в указанный state | Удобно при include/extend |

## Примеры

Базовая цепочка пакет → конфиг → сервис:

```yaml
nginx-pkg:
  pkg.installed:
    - name: nginx

nginx-conf:
  file.managed:
    - name: /etc/nginx/nginx.conf
    - source: salt://nginx/nginx.conf.j2
    - template: jinja
    - require:
      - pkg: nginx-pkg

nginx-svc:
  service.running:
    - name: nginx
    - enable: True
    - require:
      - file: nginx-conf
    - watch:
      - file: nginx-conf
```

Использование order для тонкой сортировки независимых состояний:

```yaml
sysctl-base:
  sysctl.present:
    - name: net.ipv4.ip_forward
    - value: 1
    - order: 10

motd:
  file.managed:
    - name: /etc/motd
    - source: salt://base/motd
    - order: 50
```

Внесение зависимости в другой state через require_in:

```yaml
common-packages:
  pkg.installed:
    - pkgs:
      - curl
      - ca-certificates
    - require_in:
      - service: nginx-svc
```

onchanges для выборочного запуска без mod_watch:

```yaml
migrate-db:
  cmd.run:
    - name: alembic upgrade head
    - cwd: /srv/app
    - onchanges:
      - file: app-config
```

## Include и extend

*   include добавляет SLS в текущий:

```markdown
include:
  - nginx.common
  - tls.ca
```

*   extend позволяет изменить ранее определенный state без дублирования:

```yaml
extend:
  nginx-svc:
    service.running:
      - enable: True
      - watch:
        - file: ssl-cert
```
