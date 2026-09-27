# Proxy Minion в SaltStack

## Определения

- **Proxy Minion**: Агент Salt, работающий на Мастере (или отдельном хосте) и управляющий устройствами без поддержки Python (коммутаторы, маршрутизаторы, API-сервисы, legacy-системы) через промежуточный протокол (SSH, NETCONF, REST API).
- **proxytype**: Параметр в конфигурации Proxy Minion, определяющий тип проксируемого устройства (e.g., `napalm`, `netmiko`, `ssh`, `rest`).
- **POM (Proxy Minion on the Master)**: Режим, при котором Proxy Minion работает как процесс на самом Мастере, управляет всеми проксируемыми устройствами.
- **Standalone Proxy Minion**: Режим, при котором Proxy Minion работает на отдельном хосте, подключаясь к Мастеру по стандартному протоколу Salt.
- **NAPALM (Network Automation and Programmability Abstraction Layer with Multivendor support)**: Библиотека для унифицированного управления сетевым оборудованием (Cisco, Juniper, Arista) через SSH/NETCONF/gNMI.
- **Netmiko**: Библиотека для управления сетевым оборудованием через SSH (параметризованные шаблоны команд).
- **Grains для Proxy**: Grains, передаваемые через roster или конфигурацию Proxy Minion для идентификации устройства.

---

## Основные концепции

### Архитектура Proxy Minion

```
Master
  │
  ├── salt-proxy (process)
  │     ├── proxytype: napalm
  │     ├── host: 10.0.0.1 (switch IP)
  │     ├── username: admin
  │     └── password: ****
  │
  └── Managed Device (switch/router)
        ├── No Python required
        ├── SSH/NETCONF/REST API access only
        └── Returns data through salt-proxy → Master
```

### Режимы работы

| Режим | Описание | Использование |
|:---|:---|:---|
| POM | salt-proxy на мастере | До ~100 устройств |
| Standalone | salt-proxy на отдельном хосте | >100 устройств или изолированные сети |
| Multi-proxy | Несколько salt-proxy процессов | Распределение нагрузки |

---

## Практические сценарии

### 1. Конфигурация Proxy Minion (NAPALM)

**master config:**

```yaml
# /etc/salt/master.d/proxy.conf
# Включение поддержки proxy
proxy: {}

# Базовые модули для proxy
extension_modules: /srv/salt/_modules
```

**Proxy Minion config:**

```yaml
# /etc/salt/proxy
master: salt-master.example.com
proxytype: napalm

# NAPALM параметры
napalm_options:
  hostname: 10.0.0.1
  username: admin
  password: secret_password
  device_type: ios
  optional_args:
    port: 22
    transport: ssh

# Идентификация устройства
proxy:
  host: 10.0.0.1
  username: admin
  password: secret_password
  device_type: ios
```

**Запуск:**

```bash
# Запуск proxy для конкретного устройства
salt-proxy --proxyid=switch-01 -d

# Запуск через systemd
systemctl start salt-proxy@switch-01
```

### 2. Proxy Minion через Netmiko

```yaml
# /etc/salt/proxy
master: salt-master.example.com
proxytype: netmiko

proxy:
  host: 10.0.0.2
  username: admin
  password: secret_password
  device_type: cisco_ios
  secret: enable_password
```

**Вызов execution-модулей:**

```bash
# Проверка подключения
salt 'switch-01' netmiko.send_command 'show version'

# Получение конфигурации
salt 'switch-01' netmiko.send_command 'show running-config'

# Отправка команды с ожиданием
salt 'switch-01' netmiko.send_command 'write memory'
```

### 3. Управление через Roster

```yaml
# /etc/salt/roster
switch-01:
  host: 10.0.0.1
  proxy:
    host: 10.0.0.1
    username: admin
    password: secret_password
    device_type: cisco_ios
    proxytype: netmiko
  roster_grains:
    os: IOS
    roles:
      - switch
      - access_layer
    model: Cisco Catalyst 2960
    location: dc1-rack01
```

### 4. Custom Proxy Module

```python
# /srv/salt/_proxy/my_proxy.py
"""
Кастомный proxy module для управления legacy-устройством через REST API.
"""
import requests

__proxyenabled__ = ['my_proxy']

def __virtual__():
    return True


def init(opts):
    """Инициализация proxy."""
    proxy_config = opts.get('proxy', {})
    __context__['hostname'] = proxy_config.get('host')
    __context__['username'] = proxy_config.get('username')
    __context__['password'] = proxy_config.get('password')
    __context__['session'] = None


def alive(opts):
    """Проверка доступности устройства."""
    try:
        resp = requests.get(
            f"http://{__context__['hostname']}/api/status",
            timeout=5
        )
        return resp.status_code == 200
    except Exception:
        return False


def shutdown(opts):
    """Очистка при остановке proxy."""
    if __context__.get('session'):
        __context__['session'].close()


def execution(opts):
    """Выполнение команды на устройстве."""
    def _send_command(cmd):
        resp = requests.post(
            f"http://{__context__['hostname']}/api/execute",
            json={
                'command': cmd,
                'username': __context__['username'],
                'password': __context__['password']
            }
        )
        return resp.json()
    return _send_command
```

**Регистрация proxy:**

```yaml
# /etc/salt/proxy
proxytype: my_proxy
proxy:
  host: 10.0.0.100
  username: admin
  password: secret
```

### 5. grains для Proxy устройств

```bash
# Установка grains через proxy
salt 'switch-01' grains.setval os 'IOS'
salt 'switch-01' grains.setval roles '["switch", "access"]'
salt 'switch-01' grains.setval model 'Cisco Catalyst 2960'
salt 'switch-01' grains.setval location 'dc1-rack01'
salt 'switch-01' grains.setval serial 'FCW1234567'
```

```yaml
# Или через roster_grains
switch-01:
  host: 10.0.0.1
  proxy:
    host: 10.0.0.1
    proxytype: netmiko
    device_type: cisco_ios
    username: admin
    password: secret
  roster_grains:
    os: IOS
    model: Cisco Catalyst 2960
    location: dc1-rack01
    roles:
      - switch
      - access
```

### 6. Таргетинг Proxy устройств

```bash
# Все коммутаторы
salt -G 'roles:switch' test.ping

# Все устройства в dc1
salt -G 'location:dc1*' test.ping

# Все Cisco устройства
salt -G 'os:IOS' netmiko.send_command 'show version'

# Составной таргетинг
salt -C 'G@roles:switch and G@location:dc1' netmiko.send_command 'show ip interface brief'
```

### 7. State management для Proxy

```yaml
# /srv/salt/network/switch_config.sls
{% set switches = pillar.get('switches', {}) %}

{% for switch_name, config in switches.items() %}
{{ switch_name }}_config:
  netmiko.send_config:
    - name: {{ switch_name }}
    - config: |
        hostname {{ config.hostname }}
        {% for vlan in config.get('vlans', []) %}
        vlan {{ vlan.id }}
         name {{ vlan.name }}
        {% endfor %}
    - device_type: {{ config.device_type }}
    - host: {{ config.host }}
    - username: {{ config.username }}
    - password: {{ config.password }}
{% endfor %}
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `salt-proxy` не запускается | proxytype не найден | Проверить `__proxyenabled__` в модуле |
| `Proxy minion not responding` | Устройство недоступно | `ping` до IP, проверить SSH/NETCONF |
| `Connection refused` | SSH не запущен или неверный порт | Проверить `sshd` на устройстве |
| `Authentication failed` | Неверный пароль | Проверить credentials, `enable` password |
| Grains не применяются | roster_grains не заданы | Использовать `grains.setval` или roster |
| Proxy таймаут | Медленное устройство | Увеличить `timeout` в optional_args |
| Модуль не загружается | Зависимость не установлена | `pip install napalm` или `netmiko` на хосте proxy |

### Best practices

1. **Отдельные credentials**: Используйте отдельные учётные записи для каждого типа устройств.
2. **Хранение секретов**: Не храните пароли в plaintext — используйте SDB/Vault.
3. **Таймауты**: Всегда задавайте `timeout` для network-устройств.
4. **Мониторинг**: Настройте beacon для проверки доступности proxy.
5. **Резервирование**: Для критических устройств — standby proxy.
6. **Логирование**: Направляйте логи proxy в централизованное хранилище.
7. **Версионирование**: Храните конфигурацию proxy в Git.

### См. также

- [Архитектура SaltStack](Architecture.md) — Proxy Minion definition
- [Формулы SaltStack](Formulas.md) — network automation formulas
- [Безопасность SaltStack](Security_Approaches.md) — proxy security
