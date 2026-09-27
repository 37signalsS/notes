# Кастомные модули SaltStack

## Определения

- **Execution Module**: Модуль, исполняемый на Миньоне (или через вызов с Мастера), выполняющий императивные операции (установка пакетов, управление сервисами, сбор информации). Стандартные модули: `pkg`, `service`, `file`, `user`. Кастомные хранятся в `salt://_modules/`.
- **State Module**: Модуль, описывающий декларативное состояние ресурса в SLS-файле (например, `pkg.installed`, `file.managed`). Кастомные state-модули хранятся в `salt://_states/`.
- **Grain Module**: Модуль, собирающий данные о миньоне (ОС, роль, окружение). Кастомные grains хранятся в `salt://_grains/` и синхронизируются через `saltutil.sync_grains`.
- **Beacon Module**: Модуль, мониторящий изменения на миньоне и отправляющий события в Event Bus ( падение процесса, изменение файла, нагрузка CPU). Кастомные beacons хранятся в `salt://_beacons/`.
- **Returner Module**: Модуль, отправляющий результаты выполнения заданий во внешние хранилища (PostgreSQL, Redis, Elasticsearch, SIEM). Кастомные returners хранятся в `salt://_returners/`.
- **`__virtual__`**: Функция в модуле, определяющая условия загрузки модуля (依赖于 ОС, наличие пакетов, архитектуры). Возвращает имя модуля или `False` для отключения.
- **`__virtualname__`**: Атрибут модуля, задающий альтернативное имя для вызова (переименование модуля без изменения файла).
- **`saltutil.sync_modules`**: Команда синхронизации кастомных модулей с файлового сервера на миньоны. Аналогично: `saltutil.sync_states`, `saltutil.sync_grains`, `saltutil.sync_all`.
- **Module Reloading**: Перезагрузка модуля без перезапуска миньона через `salt-call saltutil.reload_modules` или `salt '*' saltutil.sync_all`.

---

## Основные концепции

### Структура каталогов

```
/srv/salt/
├── _modules/          # Кастомные execution modules
│   ├── my_module.py
│   └── utils_func.py
├── _states/           # Кастомные state modules
│   └── my_state.py
├── _grains/           # Кастомные grains
│   └── role.py
├── _beacons/          # Кастомные beacons
│   └── my_beacon.py
├── _returners/        # Кастомные returners
│   └── my_returner.py
├── _utils/            # Общие утилиты (доступны из всех модулей)
│   └── my_utils.py
├── _renderers/        # Кастомные рендереры
│   └── my_render.py
├── _outputers/        # Кастомные форматы вывода
│   └── my_output.py
└── _pillar/           # Кастомные Pillar модули
    └── my_pillar.py
```

### Жизненный цикл модуля

1. Разработчик создаёт Python-файл в соответствующем каталоге (`_modules/`, `_states/` и т.д.)
2. Файл размещается в `file_roots` мастера (обычно `/srv/salt/`)
3. Миньон синхронизирует модули: `salt '*' saltutil.sync_modules` (или `sync_all`)
4. Модуль доступен для вызова: `salt '*' my_module.function`
5. При обновлении модуля — повторная синхронизация

### Правила именования

- Имя файла = имя модуля (без `.py`): `my_module.py` → вызов `my_module.function`
- Имя функции = имя операции: `my_module.manage_service`, `my_state.install_package`
- Внутренние функции начинаются с `_`: `my_module._helper()`
- Константы: `__virtualname__`, `__func_alias__`, `__outputter__`

---

## Практические сценарии

### 1. Кастомный Execution Module

**Цель:** Модуль для проверки состояния сервиса с дополнительной логикой.

```python
# /srv/salt/_modules/service_check.py
"""
Кастомный модуль для проверки состояния сервисов.
"""
import subprocess

def __virtual__():
    """Загрузка модуля только на Linux."""
    if __grains__['os_family'] not in ('Debian', 'RedHat', 'Suse'):
        return False
    return 'service_check'

def is_listening(port):
    """
    Проверяет, слушает ли процесс на указанном порту.

    CLI Example::

        salt '*' service_check.is_listening 80
    """
    cmd = f'ss -tlnp sport = :{port}'
    result = __salt__['cmd.run'](cmd)
    return bool(result)

def check_http_code(url, expected_code=200):
    """
    Проверяет HTTP-код ответа URL.

    CLI Example::

        salt '*' service_check.check_http_code http://localhost:8080/health 200
    """
    result = __salt__['cmd.run'](f'curl -s -o /dev/null -w "%{{http_code}}" {url}')
    return int(result) == expected_code

def get_disk_usage(path='/'):
    """
    Возвращает процент использования диска.

    CLI Example::

        salt '*' service_check.get_disk_usage /
    """
    result = __salt__['cmd.run'](f"df -h {path} | tail -1 | awk '{{print $5}}'")
    return int(result.replace('%', ''))
```

**Синхронизация и вызов:**

```bash
# Синхронизация модулей на все миньоны
salt '*' saltutil.sync_modules
# → web-01:
#     - modules.service_check

# Вызов функции
salt '*' service_check.is_listening 80
# → web-01: True

salt '*' service_check.get_disk_usage /
# → web-01: 67
```

### 2. Кастомный State Module

**Цель:** State для управления конфигурационными файлами с валидацией.

```python
# /srv/salt/_states/service_config.py
"""
Кастомный state для управления конфигурацией сервисов.
"""

def managed(name, content, validate_cmd=None, backup=False):
    """
    Управляет конфигурационным файлом с опциональной валидацией.

    name
        Путь к файлу.
    content
        Содержимое конфигурационного файла.
    validate_cmd
        Команда для валидации конфигурации (опционально).
    backup
        Создавать ли бэкап перед изменением (по умолчанию False).

    CLI Example::

        service_config.managed:
          - name: /etc/nginx/nginx.conf
          - content: |
              worker_processes auto;
              events {
                  worker_connections 1024;
              }
          - validate_cmd: nginx -t
          - backup: True
    """
    ret = {'name': name, 'changes': {}, 'result': False, 'comment': ''}

    # Читаем текущее содержимое
    current = __salt__['file.get_hash'](name) if __salt__['file.file_exists'](name) else None

    # Бэкап
    if backup and current:
        __salt__['file.copy'](
            f'{name}.bak',
            name
        )

    # Записываем файл
    result = __salt__['file.managed'](
        name,
        contents=content,
        create_if_missing=True
    )

    if not result:
        ret['comment'] = 'Ошибка записи файла'
        return ret

    # Валидация
    if validate_cmd:
        val_result = __salt__['cmd.run'](validate_cmd)
        if val_result != 0:
            ret['comment'] = f'Валидация не пройдена: {val_result}'
            # Откат
            if backup and current:
                __salt__['file.copy'](name, f'{name}.bak')
            return ret

    new_hash = __salt__['file.get_hash'](name)
    if current != new_hash:
        ret['changes'] = {'diff': f'{current} -> {new_hash}'}

    ret['result'] = True
    ret['comment'] = 'Конфигурация обновлена'
    return ret
```

**Использование в SLS:**

```yaml
nginx_config:
  service_config.managed:
    - name: /etc/nginx/nginx.conf
    - content: |
        worker_processes auto;
        events {
            worker_connections 1024;
        }
    - validate_cmd: nginx -t
    - backup: True
```

### 3. Кастомный Grain Module

**Цель:** Сбор динамических данных о роли сервера.

```python
# /srv/salt/_grains/role.py
"""
Динамические grains для определения роли сервера.
"""
import os
import json

def roles():
    """
    Определяет роль сервера на основе конфигурационных файлов.

    Проверяет наличие файлов-маркеров в /etc/salt/roles/:

    CLI Example::

        salt '*' grains.roles
    """
    grains = {'roles': [], 'environment': 'unknown'}

    roles_dir = '/etc/salt/roles'
    if os.path.isdir(roles_dir):
        for f in os.listdir(roles_dir):
            if f.endswith('.role'):
                grains['roles'].append(f.replace('.role', ''))

    # Определение окружения
    env_file = '/etc/salt/environment'
    if os.path.isfile(env_file):
        with open(env_file) as fh:
            grains['environment'] = fh.read().strip()

    # Определение центра обработки данных
    grains['datacenter'] = os.environ.get('DATACENTER', 'unknown')

    return grains
```

**Синхронизация:**

```bash
salt '*' saltutil.sync_grains
# → web-01:
#     - grains.role

# Проверка
salt '*' grains.item roles
# → web-01:
#     roles:
#       - web
#       - frontend
```

### 4. Кастомный Beacon Module

**Цель:** Мониторинг использования диска и отправка события при превышении порога.

```python
# /srv/salt/_beacons/disk_usage.py
"""
Beacon для мониторинга использования диска.
"""
import os

def beacon(config):
    """
    Отправляет событие при превышении порога использования диска.

    config:
      - path: /
      - threshold: 85
      - interval: 60

    CLI Example::

        salt-minion beacons.add disk_usage path=/ threshold=85 interval=60
    """
    events = []
    path = config.get('path', '/')
    threshold = config.get('threshold', 85)

    usage = __salt__['disk.usage']
    if path in usage:
        pct = int(usage[path]['use%'].rstrip('%'))
        if pct >= threshold:
            events.append({
                'tag': f'disk/usage/{path}',
                'data': {
                    'path': path,
                    'usage_percent': pct,
                    'threshold': threshold,
                    'available': usage[path]['available'],
                }
            })

    return events
```

**Настройка beacon:**

```bash
salt-minion beacons.add disk_usage path=/ threshold=85 interval=60
```

### 5. Кастомный Returner Module

**Цель:** Отправка результатов в PostgreSQL с кастомной схемой.

```python
# /srv/salt/_returners/pg_returner.py
"""
Returner для PostgreSQL с расширенной схемой.
"""
import json
import datetime

__virtualname__ = 'pg_returner'

def __virtual__():
    if 'postgres.query' not in __salt__:
        return False
    return __virtualname__


def returner(ret):
    """Сохраняет результат задания в PostgreSQL."""
    sql = """
        INSERT INTO salt_returns (jid, minion, fun, success, return_data, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    __salt__['postgres.query'](
        'salt',
        sql,
        [ret['jid'], ret['id'], ret['fun'], ret['success'],
         json.dumps(ret['return']), datetime.datetime.now()]
    )


def event_return(events):
    """Сохраняет события в PostgreSQL."""
    sql = """
        INSERT INTO salt_events (tag, data, timestamp)
        VALUES (%s, %s, %s)
    """
    for event in events:
        __salt__['postgres.query'](
            'salt',
            sql,
            [event['tag'], json.dumps(event['data']), datetime.datetime.now()]
        )
```

**Настройка returner:**

```yaml
# /etc/salt/master
ext_job_cache: pg_returner

# /etc/salt/minion
returner: pg_returner
```

### 6. Кастомные утилиты (_utils)

**Цель:** Общие функции, доступные из всех модулей.

```python
# /srv/salt/_utils/my_utils.py
"""
Общие утилиты для кастомных модулей SaltStack.
"""
import json
import logging

log = logging.getLogger(__name__)


def load_config(path):
    """Безопасная загрузка JSON-конфигурации."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f'Config file not found: {path}')
        return {}
    except json.JSONDecodeError as e:
        log.error(f'Invalid JSON in {path}: {e}')
        return {}


def safe_divide(a, b, default=0):
    """Безопасное деление с обработкой деления на ноль."""
    try:
        return a / b
    except (TypeError, ZeroDivisionError):
        return default
```

**Использование в модуле:**

```python
from salt.utils.my_utils import load_config

def get_service_status():
    config = load_config('/etc/myservice/config.json')
    return config.get('status', 'unknown')
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `salt '*' my_module.function` → `Function 'my_module.function' is not available` | Модуль не синхронизирован | `salt '*' saltutil.sync_modules`, проверить `file_roots` |
| `NameError: name '__salt__' is not defined` | Модуль не подключён к salt dunder | Проверить импорт, использовать `__salt__` только в функциях |
| `NameError: name '__grains__' is not defined` | Grains недоступны в текущем контексте | Grains доступны только на миньоне, не на мастере |
| `ImportError: cannot import name 'X'` | Зависимость не установлена на миньоне | Установить pip-пакет на миньоне или использовать `__utils__` |
| Модуль загружается, но `__virtual__` возвращает `False` | Условия загрузки не выполнены | Проверить `__grains__` и зависимости в `__virtual__` |
| `saltutil.sync_modules` не находит модуль | Файл не в корне `file_roots/_modules/` | Проверить структуру каталогов, нет вложенности |
| Конфликт имён с встроенными модулями | Кастомный модуль перезаписывает стандартный | Переименовать кастомный модуль, использовать `__virtualname__` |

### Best practices

1. **Минимум зависимостей**: Не требуйте установки pip-пакетов на миньоны без крайней необходимости. Используйте `__utils__` и стандартные модули Salt.
2. **`__virtual__`**: Всегда проверяйте условия загрузки (ОС, наличие пакетов) — модуль не должен падать на неподходящих системах.
3. **Документирование**: Каждая публичная функция должна иметь docstring с примером CLI (`CLI Example::`).
4. **Логирование**: Используйте `logging.getLogger(__name__)` вместо `print()`.
5. **Тестирование**: Тестируйте модули локально через `salt-call --local` перед деплоем.
6. **Версионирование**: Храните кастомные модули в Git, используйте code review.
7. **Именование**: Избегайте конфликтов с именами встроенных модулей. Проверяйте `salt '*' sys.list_modules`.
8. **Безопасность**: Не храните секреты в модулях. Используйте Pillar или SDB.

### Версии и совместимость

| Версия Salt | Особенности |
|:---|:---|
| 3006 LTS | Стандартный API для модулей, `saltutil.sync_*` |
| 3007 STS | Добавлен `__utils__` для общих функций |
| 3008 LTS | Улучшена безопасность модулей, `SafeDict`/`SafeList` |

### См. также

- [Архитектура SaltStack](Architecture.md) — обзор компонентов
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md) — как state-модули применяются
- [Формулы SaltStack](Formulas.md) — структура переиспользуемых формул
