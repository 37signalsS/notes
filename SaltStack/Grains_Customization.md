# Grains кастомизация

## Определения

- **Grains**: Статические данные о миньоне (ОС, ядро, архитектура, RAM, роль), собираемые при старте salt-minion. Используются для таргетинга, шаблонизации и условной логики.
- **Static Grains**: Grains, заданные в YAML-файле `/etc/salt/grains` на миньоне. Не изменяются автоматически.
- **Dynamic Grains**: Grains, определяемые Python-скриптами в `/etc/salt/grains/` или `/srv/salt/_grains/`. Обновляются при `saltutil.sync_grains`.
- **Grains Cache**: Локальный кэш Grains на миньоне (`/var/cache/salt/minion/grains`). Ускоряет повторные запуски.
- **`saltutil.sync_grains`**: Команда синхронизации кастомных Grains с файлового сервера.
- **`grains.setval`**: Команда установки Grains значения на миньоне.
- **`grains.append`**: Команда добавления значения в список Grains.
- **`grains.remove`**: Команда удаления значения из списка Grains.
- **Grain Matching**: Механизм фильтрации миньонов по значениям Grains через таргетинг (`-G`, `P@`, `G@`).

---

## Основные концепции

### Встроенные Grains

| Grain | Описание | Пример |
|:---|:---|:---|
| `os` | Операционная система | `Ubuntu`, `CentOS`, `Debian` |
| `os_family` | Семейство ОС | `Debian`, `RedHat`, `Suse` |
| `osrelease` | Версия ОС | `22.04`, `8.5` |
| `kernel` | Ядро | `Linux`, `Darwin` |
| `kernelrelease` | Версия ядра | `5.15.0-76-generic` |
| `arch` | Архитектура | `x86_64`, `aarch64` |
| `num_cpus` | Количество CPU | `4` |
| `mem_total` | Оперативная память (МБ) | `16384` |
| `fqdn` | Полное доменное имя | `web-01.example.com` |
| `ip4` | IPv4 адрес | `192.168.1.10` |
| `roles` | Роль сервера | `['web', 'frontend']` |
| `environment` | Окружение | `production`, `staging` |
| `id` | ID миньона | `web-01` |

### Типы Grain Matching

| Префикс | Описание | Пример |
|:---|:---|:---|
| `G@` | Точное совпадение | `G@os:Ubuntu` |
| `P@` | Regex совпадение | `P@os:(Ubuntu\|Debian)` |
| `grain:` | Grain через CLI | `-G 'os:Ubuntu'` |
| `L@` | Список | `L@web-01,web-02` |
| `S@` | CIDR | `S@10.0.0.0/24` |

---

## Практические сценарии

### 1. Static Grains (YAML)

```yaml
# /etc/salt/grains
roles:
  - web
  - frontend
environment: production
datacenter: dc1
nfs_server: 10.0.0.100
monitoring_enabled: true
```

**Просмотр:**

```bash
salt '*' grains.item roles
# → web-01:
#     roles:
#       - web
#       - frontend

salt '*' grains.item environment
# → web-01: production
```

### 2. Dynamic Grains (Python)

```python
# /srv/salt/_grains/custom_grains.py
"""
Кастомные dynamic grains для SaltStack.
"""
import os
import json
import subprocess

def custom_grains():
    """
    Сбор кастомных grains.

    CLI Example::

        salt '*' grains.custom_grains
    """
    grains = {}

    # Определение роли по конфигурационному файлу
    roles_file = '/etc/salt/roles.json'
    if os.path.isfile(roles_file):
        with open(roles_file) as f:
            grains['roles'] = json.load(f)
    else:
        grains['roles'] = ['default']

    # Определение окружения
    env_file = '/etc/salt/environment'
    if os.path.isfile(env_file):
        with open(env_file) as f:
            grains['environment'] = f.read().strip()

    # Сбор информации о дисках
    try:
        result = subprocess.run(['lsblk', '-J'], capture_output=True, text=True)
        disks = json.loads(result.stdout)
        grains['disks'] = [d['name'] for d in disks.get('blockdevices', [])]
    except Exception:
        grains['disks'] = []

    # Определение наличия Docker
    grains['docker_installed'] = os.path.isdir('/var/run/docker.sock')

    # Определение количества оперативной памяти в GB
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if 'MemTotal' in line:
                    mem_kb = int(line.split()[1])
                    grains['memory_gb'] = round(mem_kb / 1024 / 1024, 1)
                    break
    except Exception:
        grains['memory_gb'] = 0

    return grains
```

**Синхронизация:**

```bash
salt '*' saltutil.sync_grains
# → web-01:
#     - grains.custom_grains

salt '*' grains.item roles
# → web-01:
#     roles:
#       - web
#       - frontend
```

### 3. grains.setval / grains.append / grains.remove

```bash
# Установка значения
salt '*' grains.setval datacenter dc2
# → web-01:
#     datacenter: dc2

# Добавление в список
salt '*' grains.append roles monitor
# → web-01:
#     roles:
#       - web
#       - frontend
#       - monitor

# Удаление из списка
salt '*' grains.remove roles frontend
# → web-01:
#     roles:
#       - web
#       - monitor

# Удаление ключа
salt '*' grains.delval datacenter
```

### 4. Grain-based таргетинг

```bash
# Все Ubuntu серверы
salt -G 'os:Ubuntu' test.ping

# Все серверы в dc1
salt -G 'datacenter:dc1' test.ping

# Все web серверы в production
salt -G 'roles:web and environment:production' test.ping

# Regex совпадение
salt -P 'os:(Ubuntu|Debian)' test.ping

# Составной таргетинг
salt -C 'G@datacenter:dc1 and G@roles:web and not web-01*' test.ping
```

### 5. Grains в SLS (Jinja)

```yaml
# /srv/salt/webserver/init.sls
{% if grains['os'] == 'Ubuntu' %}
web_package:
  pkg.installed:
    - name: nginx
{% elif grains['os'] == 'CentOS' %}
web_package:
  pkg.installed:
    - name: nginx
{% endif %}

{% if grains.get('docker_installed', False) %}
docker_service:
  service.running:
    - name: docker
    - enable: True
{% endif %}

{% if grains['roles'] | contains('web') %}
nginx_config:
  file.managed:
    - name: /etc/nginx/nginx.conf
    - source: salt://webserver/files/nginx.conf
{% endif %}
```

### 6. Grains Cache Management

```bash
# Просмотр кэша
ls -la /var/cache/salt/minion/grains

# Очистка кэша
salt '*' saltutil.refresh_grains

# Принудительное обновление
salt '*' saltutil.sync_all
```

```yaml
# /etc/salt/minion
# Включение кэширования grains
grains_cache: True
grains_cache_expiration: 3600  # 1 час
```

### 7. grains_by_id

```bash
# Просмотр всех доступных grains
salt '*' grains.ls

# Просмотр значения конкретного grain
salt '*' grains.item os

# Просмотр всех grains с значениями
salt '*' grains.items

# Поиск grain по подстроке
salt '*' grains.items | grep -i ubuntu
```

### 8. Grains в конфигурации

```yaml
# /etc/salt/minion.d/grains.conf
# Установка grains через конфигурацию
grains:
  roles:
    - web
    - frontend
  environment: production
  datacenter: dc1
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Grains not found` | Grains не синхронизированы | `salt '*' saltutil.sync_grains` |
| `Grains cache stale` | Кэш устарел | `salt '*' saltutil.refresh_grains` |
| `Dynamic grains not loading` | Ошибка в Python-скрипте | Проверить синтаксис, зависимости |
| `Grains setval not persisting` | Значение не сохранено | Проверить `/etc/salt/grains` |
| `Grain matching returns empty` | Неверный синтаксис | Проверить `G@`, `P@`, `-G` |
| `Grains sync timeout` | Медленная сеть | Увеличить timeout, проверить file_roots |
| `Grains conflict` | Static и dynamic grains конфликтуют | Приоритет: static > dynamic |

### Best practices

1. **Иерархия**: Static ( `/etc/salt/grains`) → Dynamic (`_grains/`) → grains.setval.
2. **Минимум**: Не дублируйте information из встроенных grains.
3. **Именование**: Используйте snake_case: `data_center`, не `DataCenter`.
4. **Кэширование**: Включайте `grains_cache` для производительности.
5. **Версионирование**: Храните dynamic grains в Git.
6. **Тестирование**: Проверяйте `grains.items` перед deploy.
7. **Безопасность**: Не храните секреты в grains.
8. **Мониторинг**: Проверяйте актуальность grains на критичных хостах.

### Версии и совместимость

| Версия Salt | Особенности Grains |
|:---|:---|
| 3006 LTS | Стандартный grains API, cache |
| 3007 STS | Улучшенная производительность sync |
| 3008 LTS | `grains_cache_expiration`, `SafeDict` |

### См. также

- [Архитектура SaltStack](Architecture.md) — Grains overview
- [Формулы SaltStack](Formulas.md) — Grains в map.jinja
- [Pillar продвинутый](Pillar_Advanced.md) — Grains vs Pillar
