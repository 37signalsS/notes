# Proxy Minion в SaltStack

**Актуально для:** Salt 3008.x

## Определения

- **Proxy Minion**: Агент Salt (`salt-proxy`), работающий на мастере (или отдельном хосте) и управляющий устройствами, на которых нельзя или нельзя установить стандартный `salt-minion` (сетевое оборудование без поддержки Python — коммутаторы, маршрутизаторы, файрволы; legacy-системы; API-сервисы). Прокси говорит с устройством по промежуточному протоколу (SSH, NETCONF, REST API, SNMP) и выглядит для мастера как обычный minion.
- **proxytype**: Параметр в конфигурации Proxy Minion (Pillar или `/etc/salt/proxy`), определяющий, какой прокси-модуль загружать из `salt.proxy` (например, `napalm`, `netmiko_px`, `junos`, `esxi`, `rest_sample`).
- **POM (Proxy Minion on the Master)**: Режим, при котором `salt-proxy` работает как процесс прямо на мастере. Подходит для небольших ферм (до ~100 устройств).
- **Standalone Proxy Minion**: Режим, при котором `salt-proxy` работает на отдельном хосте (или хостах) и подключается к мастеру по стандартному Salt-протоколу (ZeroMQ/TCP, порты 4505/4506).
- **Delta Proxy**: Режим, появившийся в Salt 3004, при котором один управляющий proxy-миньон (control proxy) управляет группой прокси-модулей, экономя процессы и ключи PKI.
- **NAPALM (Network Automation and Programmability Abstraction Layer with Multivendor support)**: Python-библиотека для унифицированного управления сетевым оборудованием (Cisco IOS/NX-OS, Juniper JunOS, Arista EOS, Nokia IOS-XR) через SSH/NETCONF/gNMI. В Salt реализована как `salt.proxy.napalm` и сопутствующие execution/state-модули (`salt.modules.napalm_mod`, `salt.modules.napalm_network`).
- **Netmiko**: Python-библиотека для SSH-доступа к сетевому оборудованию. В Salt реализована как `salt.proxy.netmiko_px` (прокси-модуль) и `salt.modules.netmiko_mod` (execution-модуль, работает и без прокси).
- **Proxymodule**: Python-модуль в `salt.proxy` (или `/srv/salt/_proxy/`), инкапсулирующий логику соединения с конкретным типом устройства. Должен реализовывать `init()`, `shutdown()`, `ping()`, `alive()`, `initialized()`; может предоставлять `grains()`, `fns()`, `call()` и device-specific функции.
- **salt-proxy**: CLI-утилита для запуска proxy-процесса. Принимает `--proxyid` для идентификации устройства и те же аргументы, что и `salt-minion` (логирование, конфиг и т.д.).
- **__proxyenabled__**: Список proxytype-ов, для которых данный proxymodule/grains-модуль должен загружаться. Используется внутри proxymodule и grains-файлов.
- **__proxy__**: Глобально инъектируемая переменная (LazyLoader), через которую SLS-состояния и execution-модули вызывают функции proxymodule (например, `__proxy__['napalm.call']('cli', commands=['show version'])`).
- **Grains для Proxy**: Статические данные об устройстве, которые proxy собирает при старте (model, os, serial, interface count и т.д.). Могут задаваться через `roster_grains`, Pillar или функцию `grains()` в proxymodule.

## Архитектура и принцип работы

### Архитектурная схема

```
Master
  │  (Event Bus: порты 4505/4506, PKI+AES-256)
  │
  ├── salt-proxy (process, --proxyid=switch-01)
  │     ├── proxytype: napalm
  │     ├── driver: ios
  │     ├── host: 10.0.0.1
  │     ├── username: admin
  │     ├── passwd: ****  (через SDB/Vault)
  │     └── multiprocessing: False
  │
  └── Управляемое устройство (switch/router)
        ├── Нет Python, нет salt-minion
        ├── Доступ по SSH/NETCONF/REST API
        └── Данные возвращаются через salt-proxy → Master
```

### Жизненный цикл Proxy Minion

1. **Запуск**: `salt-proxy --proxyid=<id>` или `systemctl start salt-proxy@<id>`.
2. **Инициализация**: загружается proxymodule из `salt.proxy.<proxytype>`, вызывается `init(opts)` — устанавливается соединение с устройством (SSH/NETCONF/API).
3. **Аутентификация на мастере**: proxy генерирует minion-ключ, отправляет публичный ключ мастеру. Администратор принимает ключ через `salt-key -a <id>`.
4. **Сбор grains**: вызывается `grains()` в proxymodule (если `proxy_merge_grains_in_module: True`) и grains из `/srv/salt/_grains/`. Значения `kernel`, `os`, `os_family` принудительно устанавливаются в `proxy`.
5. **Рабочий цикл**: proxy периодически вызывает `alive()` (если `proxy_keep_alive: True`), поддерживая соединение с устройством. Выполняет команды через execution-модули и состояния.
6. **Остановка**: вызывается `shutdown(opts)` — закрывается соединение с устройством.

### Конфигурационные файлы

| Файл | Назначение |
| :--- | :--- |
| `/etc/salt/proxy` | Основной конфиг proxy (master, multiprocessing, proxy-специфичные options) |
| `/etc/salt/proxy.d/*.conf` | Дополнительные конфиги proxy (начиная с 2016.11.0) |
| `/srv/pillar/<id>.sls` | Pillar с `proxy:` stanza для каждого устройства |
| `/srv/salt/_proxy/<module>.py` | Кастомные proxymodules |
| `/srv/salt/_grains/<module>.py` | Кастомные grains для proxy |

### Proxy-специфичные опции конфигурации

| Опция | По умолчанию | Описание |
| :--- | :--- | :--- |
| `proxy_keep_alive` | `True` | Перезапускать соединение с устройством при падении (требует реализации `alive()` в proxymodule) |
| `proxy_keep_alive_interval` | `1` | Интервал проверки соединения в минутах |
| `proxy_always_alive` | `True` | Поддерживать постоянное соединение с устройством |
| `proxy_merge_pillar_in_opts` | `False` | Сливать Pillar-данные в opts (для множественных proxy на одном хосте) |
| `proxy_deep_merge_pillar_in_opts` | `False` | Глубокое слияние Pillar в opts |
| `proxy_merge_pillar_in_opts_strategy` | `smart` | Стратегия слияния (`merge`, `overwrite`, `smart`) |
| `proxy_mines_pillar` | `True` | Разрешить конфигурацию mine через Pillar |
| `add_proxymodule_to_opts` | `False` | Добавить proxymodule LazyLoader в `opts` (устаревает, используйте `__proxy__`) |
| `proxy_merge_grains_in_module` | `True` | Вызывать `grains()` из proxymodule при загрузке grains |
| `multiprocessing` | `False` (для SSH-based proxy) | Отключить multiprocessing для SSH-прокси |

## Режимы работы

| Режим | Описание | Когда использовать |
|:---|:---|:---|
| **POM (Proxy on Master)** | `salt-proxy` как процесс на мастере | До ~100 устройств, лаборатории |
| **Standalone** | `salt-proxy` на отдельном хосте | >100 устройств, изолированные сети |
| **Delta Proxy** | Один control proxy управляет группой | Сотни устройств, экономия процессов/PKI |
| **Multi-proxy** | Несколько `salt-proxy` процессов на хосте | Горизонтальное масштабирование |

---

## Практические сценарии

### Prerequisites

**Требования к хосту proxy (Salt 3008.x):**

```bash
# Минимальная установка Salt (onedir/tiamat)
curl -L https://bootstrap.saltproject.io/salt/bootstrap-salt.sh | sudo bash -s -- -x python3

# Для NAPALM proxy
pip install napalm

# Для Netmiko proxy
pip install netmiko

# Для Junos proxy
pip install junos-eznc
```

**Сервисный файл systemd для salt-proxy:**

```ini
# /etc/systemd/system/salt-proxy@.service
[Unit]
Description=Salt proxy minion %i
After=network.target salt-master.service

[Service]
Type=notify
ExecStart=/usr/local/bin/salt-proxy --proxyid=%i
Restart=on-failure
User=salt

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now salt-proxy@switch-01
```

### 1. Конфигурация Proxy на мастере

```yaml
# /etc/salt/master.d/proxy.conf
# Proxy minions используют тот же PKI, что и обычные minions
# proxy_minions: True  # опционально — для отображения proxy в управлении ключами
```

```yaml
# /etc/salt/proxy (или /etc/salt/proxy.d/proxy.conf)
master: salt-master.example.com

# Отключить multiprocessing для SSH-based proxy (NAPALM, Netmiko)
multiprocessing: False

# Настройки keepalive
proxy_keep_alive: True
proxy_keep_alive_interval: 5
```

### 2. Конфигурация Proxy Minion (NAPALM)

**Pillar (рекомендуется) — `/srv/pillar/switch-01.sls`:**

```yaml
# /srv/pillar/switch-01.sls
proxy:
  proxytype: napalm
  driver: ios          # napalm driver: ios, nxos, junos, eos, iosxr
  host: 10.0.0.1
  username: '{{ sdb://creds/napalm/username }}'
  passwd: '{{ sdb://creds/napalm/password }}'
  optional_args:
    port: 22
    transport: ssh

# Grains для таргетинга
grains:
  os: IOS
  model: Cisco Catalyst 9300
  location: dc1-rack01
  roles:
    - switch
    - access_layer
```

**Или через `/etc/salt/proxy.d/switch-01.conf` (начиная с 2016.11.0):**

```yaml
# /etc/salt/proxy.d/switch-01.conf
master: salt-master.example.com
multiprocessing: False
proxy:
  proxytype: napalm
  driver: ios
  host: 10.0.0.1
  username: admin
  passwd: secret_password
  optional_args:
    port: 22
```

**Запуск:**

```bash
# Запуск proxy для конкретного устройства
salt-proxy --proxyid=switch-01 -l debug

# Запуск через systemd
systemctl start salt-proxy@switch-01
systemctl enable salt-proxy@switch-01
```

**Принятие ключа на мастере:**

```bash
salt-key -a switch-01
```

**Вызов модулей NAPALM:**

```bash
# Проверка доступности
salt 'switch-01' test.ping

# Сетевые facts и конфигурация
salt 'switch-01' net.facts
salt 'switch-01' net.interfaces
salt 'switch-01' net.config source=running

# Применение конфигурации через шаблон
salt 'switch-01' net.config source=running text=True

# Сброс соединения (force_reconnect)
salt 'switch-01' net.arp username=admin force_reconnect=True
```

### 3. Proxy Minion через Netmiko

```yaml
# /srv/pillar/branch-01.sls
proxy:
  proxytype: netmiko_px     # прокси-модуль: salt.proxy.netmiko_px
  host: 10.0.0.2
  username: '{{ sdb://creds/netmiko/username }}'
  password: '{{ sdb://creds/netmiko/password }}'
  device_type: cisco_ios
  secret: '{{ sdb://creds/netmiko/enable }}'
```

```bash
# Netmiko execution module (требует netmiko proxy minion)
salt 'branch-01' netmiko.send_command 'show version'
salt 'branch-01' netmiko.send_command 'show running-config'
salt 'branch-01' netmiko.send_config config='interface Gi0/1\ndescription TEST'
salt 'branch-01' netmiko.commit
```

**Standalone Netmiko (без proxy, с передачей параметров в CLI):**

```bash
# Execution module netmiko_mod работает с любого minion, если переданы параметры
salt 'any-minion' netmiko.send_command 'show version' \
  device_type='cisco_ios' host='10.0.0.2' username='admin' password='secret'
```

### 4. Delta Proxy (Salt 3004+)

Delta Proxy позволяет одному control proxy-миньону управлять группой proxymodules, экономя системные ресурсы и упрощая управление ключами PKI.

**Конфигурация мастера:**

```yaml
# /etc/salt/master.d/deltaproxy.conf
# Встроенная поддержка delta proxy
proxy_minions: True
```

**Pillar для delta proxy:**

```yaml
# /srv/pillar/switch-farm.sls
proxy:
  proxytype: deltaproxy
  # Список управляемых устройств
  proxyids:
    - switch-01
    - switch-02
    - switch-03
    - switch-04
```

**Индивидуальные proxymodules для каждого устройства:**

```yaml
# /srv/pillar/switch-01.sls
proxy:
  proxytype: napalm
  driver: ios
  host: 10.0.0.1
  username: '{{ sdb://creds/napalm/username }}'
  passwd: '{{ sdb://creds/napalm/password }}'
```

```yaml
# /srv/pillar/switch-02.sls
proxy:
  proxytype: napalm
  driver: ios
  host: 10.0.0.2
  username: '{{ sdb://creds/napalm/username }}'
  passwd: '{{ sdb://creds/napalm/password }}'
```

**Запуск delta proxy:**

```bash
# Один процесс управляет всеми устройствами
salt-proxy --proxyid=switch-farm -l debug
```

### 5. Управление через Roster

```yaml
# /etc/salt/roster
switch-01:
  host: 10.0.0.1
  proxy:
    host: 10.0.0.1
    username: '{{ sdb://creds/napalm/username }}'
    passwd: '{{ sdb://creds/napalm/password }}'
    driver: ios
    proxytype: napalm
  roster_grains:
    os: IOS
    roles:
      - switch
      - access_layer
    model: Cisco Catalyst 2960
    location: dc1-rack01
```

### 6. Управление proxy через SLS-состояния

```yaml
# /srv/salt/salt_proxy_setup.sls
# Автоматическая настройка salt-proxy на удаленном minion
{%- set proxy_id = 'switch-01' %}

salt-proxy-configure:
  salt_proxy.configure_proxy:
    - proxyname: {{ proxy_id }}
    - start: True

salt-proxy-service:
  service.running:
    - name: salt-proxy@{{ proxy_id }}
    - enable: True
    - require:
      - salt_proxy: salt-proxy-configure

salt-proxy-key-accept:
  module.run:
    - name: key.accept
    - match: '{{ proxy_id }}'
    - require:
      - salt_proxy: salt-proxy-configure
```

```bash
# Применение состояния на minion, где должен быть запущен proxy
salt 'proxy-host' state.apply salt_proxy_setup
salt-key -a switch-01
```

### 7. Хранение секретов через SDB/Vault

**Мастер конфигурация SDB:**

```yaml
# /etc/salt/master.d/sdb.conf
sdb:
  myvault:
    driver: vault
    host: vault.example.com
    port: 8200
    token: '{{ salt.env.VAULT_TOKEN }}'
    # или через AppRole
    # url: https://vault.example.com:8200
    # auth: approle
    # role_id: ...
    # secret_id: ...
```

**Использование в Pillar:**

```yaml
# /srv/pillar/switch-01.sls
proxy:
  proxytype: napalm
  driver: ios
  host: 10.0.0.1
  username: '{{ sdb://myvault/network/admin_username }}'
  passwd: '{{ sdb://myvault/network/admin_password }}'
```

### 8. Мониторинг proxy через Beacon

```yaml
# /srv/pillar/beacon.sls
beacons:
  # Проверка доступности proxy каждые 5 минут
  proxy_up:
    - proxy_id: switch-01
    - interval: 300
```

```yaml
# /etc/salt/master.d/reactor.conf
reactor:
  - 'salt/beacon/salt-master/proxy_up/*':
    - /srv/reactor/restart_proxy.sls
```

```jinja
# /srv/reactor/restart_proxy.sls
restart_proxy:
  local.cmd:
    - tgt: 'localhost'
    - cmd: saltutil.restart_proxy
    - arg:
      - '{{ data.get('id') }}'
```

### 9. Grains для Proxy устройств

```bash
# Установка grains через proxy
salt 'switch-01' grains.setval os 'IOS'
salt 'switch-01' grains.setval roles '["switch", "access"]'
salt 'switch-01' grains.setval model 'Cisco Catalyst 2960'
salt 'switch-01' grains.setval location 'dc1-rack01'

# Просмотр grains proxy
salt 'switch-01' grains.items
```

```yaml
# Или через roster_grains
switch-01:
  host: 10.0.0.1
  proxy:
    host: 10.0.0.1
    proxytype: napalm
    driver: ios
    username: '{{ sdb://creds/napalm/username }}'
    passwd: '{{ sdb://creds/napalm/password }}'
  roster_grains:
    os: IOS
    model: Cisco Catalyst 2960
    location: dc1-rack01
    roles:
      - switch
      - access
```

### 10. Таргетинг Proxy устройств

```bash
# Все коммутаторы
salt -G 'roles:switch' test.ping

# Все устройства в dc1
salt -G 'location:dc1*' test.ping

# Все Cisco устройства
salt -G 'os:IOS' net.facts

# Составной таргетинг
salt -C 'G@roles:switch and G@location:dc1' net.interfaces
```

### 11. State management для Proxy

```jinja
# /srv/salt/network/baseline.sls
{%- set devices = pillar.get('network_devices', {}) %}

{%- for device_name, config in devices.items() %}
{{ device_name }}_vlans:
  network_acl.config:
    - name: {{ device_name }}
    - acl_type: switch
    - text: |
        {%- for vlan in config.get('vlans', []) %}
        vlan {{ vlan.id }}
         name {{ vlan.name }}
        {%- endfor %}
    - enable: True

{{ device_name }}_save_config:
  module.run:
    - name: netmiko.commit
    - onfail:
      - acl: {{ device_name }}_vlans
{%- endfor %}
```

---

## Операции и команды

### Управление proxy процессами

| Команда | Назначение | Пример |
|:---|:---|:---|
| `salt-proxy --proxyid=<id>` | Запуск proxy в foreground | `salt-proxy --proxyid=switch-01` |
| `salt-proxy --proxyid=<id> -d` | Запуск proxy в daemon mode | `salt-proxy --proxyid=switch-01 -d` |
| `salt-proxy --proxyid=<id> -l debug` | Запуск с debug-логированием | `salt-proxy --proxyid=switch-01 -l debug` |
| `systemctl start salt-proxy@<id>` | Запуск через systemd | `systemctl start salt-proxy@switch-01` |
| `systemctl enable salt-proxy@<id>` | Автозапуск через systemd | `systemctl enable salt-proxy@switch-01` |
| `salt-key -a <id>` | Принятие ключа proxy на мастере | `salt-key -a switch-01` |
| `salt-key -d <id>` | Удаление ключа proxy | `salt-key -d switch-01` |
| `salt-key -L` | Список всех ключей (включая proxy) | |

### Управление delta proxy

| Команда | Назначение |
| :--- | :--- |
| `salt-proxy --proxyid=<delta_id>` | Запуск delta proxy для группы устройств |
| `salt-run saltutil.sync_proxymodules` | Синхронизация proxymodules на миньонах |
| `salt-run salt_proxy.update_proxy <id>` | Обновление конфигурации proxy на удаленном хосте |

### Диагностика и мониторинг

| Команда | Назначение |
|:---|:---|
| `salt '<id>' test.ping` | Проверка доступности proxy |
| `salt '<id>' grains.items` | Просмотр grains proxy |
| `salt '<id>' saltutil.refresh_grains` | Обновление grains |
| `salt '<id>' saltutil.sync_all` | Синхронизация модулей/грайнов/статей |
| `tail -f /var/log/salt/proxy` | Логи proxy процесса |
| `salt-run manage.status` | Статус всех minion (включая proxy) |
| `salt-run state.event pretty=True` | Просмотр событий шины в реальном времени |

### Валидация конфигурации

```bash
# 1. Проверка, что конфигурация proxy корректна
salt-proxy --proxyid=switch-01 -l info  # должен запуститься без ошибок

# 2. Принятие ключа
salt-key -a switch-01

# 3. Проверка доступности
salt 'switch-01' test.ping
# → switch-01: True

# 4. Проверка grains
salt 'switch-01' grains.items
# kernel, os, os_family должны быть 'proxy'

# 5. Проверка соединения с устройством
salt 'switch-01' napalm.ping
# или для netmiko:
salt 'switch-01' netmiko.send_command 'show version'
```

---

## Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `salt-proxy` не запускается | proxytype не найден | Проверить `__proxyenabled__` в модуле; `pip install` зависимость |
| `salt-proxy` не запускается | Конфликт multiprocessing | Установить `multiprocessing: False` для SSH-based proxy |
| `Proxy minion not responding` | Устройство недоступно | `ping` до IP; проверить SSH/NETCONF/REST; увеличить `proxy_keep_alive_interval` |
| `Connection refused` | SSH не запущен или неверный порт | Проверить `sshd` на устройстве; указать `port` в `optional_args` |
| `Authentication failed` | Неверный пароль | Проверить credentials; использовать `sdb://` вместо plaintext; для Cisco проверить `secret` (enable password) |
| `Authentication failed` | key_acceptance проблемы | `salt-key -L` → `salt-key -a <id>`; сверить `master_finger` на proxy хосте |
| `Module 'net.facts' not found` | NAPALM не установлен | `pip install napalm` на хосте proxy |
| `Module 'netmiko.send_command' not found` | Netmiko не установлен | `pip install netmiko` на хосте proxy |
| `Device timeout` | Медленное устройство | Увеличить таймауты в `optional_args`; установить `proxy_always_alive: False` для энерго-экономичных устройств |
| `Grains не применяются` | roster_grains не заданы | Использовать `grains.setval` или `roster_grains`; `salt '*' saltutil.refresh_grains` |
| `Minion did not return` | Proxy процесс упал | Проверить `systemctl status salt-proxy@<id>`; `journalctl -u salt-proxy@<id>` |
| `Pillar not loading` | Ошибка в Pillar SLS | `salt '*' saltutil.refresh_pillar`; `salt '*' pillar.items`; проверить YAML-синтаксис |
| `saltutil.sync_all не подхватывает модули` | Кеш модулей | `salt '*' saltutil.sync_all reload=true`; перезапустить `salt-proxy` |
| Delta proxy не управляет устройствами | Неверный proxyid в top.sls | Проверить `proxyids` в pillar; убедиться что `salt-proxy --proxyid=<delta_id>` запущен |
| `force_reconnect` не работает | Нет параметров подключения в CLI | Убедиться что переданы `username`, `passwd` + `force_reconnect=True` |

**Диагностика на хосте proxy:**

```bash
# Проверка статуса процесса
ps aux | grep salt-proxy

# Логи proxy (debug-режим)
salt-proxy --proxyid=switch-01 -l debug 2>&1 | tee /tmp/proxy-debug.log

# Проверка сетевого доступа
telnet 10.0.0.1 22
curl -s http://10.0.0.1:80/api/status  # для REST-based proxy

# Проверка конфигурации
salt-proxy --proxyid=switch-01 --conf-file=/etc/salt/proxy -l debug 2>&1 | head -20
```

---

## Best practices

### Управление секретами

1. **Не храните пароли в plaintext** — используйте SDB с Vault или env-переменные: `sdb://vault/profile/path/key`. Подробности в [Безопасность SaltStack](Security_Approaches.md).
2. **Отдельные учётные записи** — используйте отдельные аккаунты с минимальными правами для каждого типа устройств.
3. **Ротация паролей** — используйте список паролей (`passwords: [...]`) в Pillar и обновляйте без перезапуска proxy.
4. **PKI-аутентфикация** — всегда используйте `master_finger` для предотвращения MitM-атак; включайте `auto_accept: False`.

### Надёжность и мониторинг

5. **Keep-alive**: включайте `proxy_keep_alive: True` с `proxy_keep_alive_interval: 5` для автоматического восстановления соединения.
6. **Beacon для мониторинга**: настраивайте beacon, проверяющий `alive()` каждые 5–10 минут; реагируйте через [Reactor](Orchestration_and_Automation_Methods.md) на падение proxy.
7. **Резервирование**: для критических устройств используйте delta proxy или резервный хост proxy.
8. **Логирование**: направляйте логи proxy (`salt-proxy -l info|debug`) в централизованное хранилище (ELK/Splunk) через `event_return`.
9. **Ограничения**: для энерго-экономичных устройств устанавливайте `proxy_always_alive: False` — соединение открывается только при выполнении команды.

### Масштабирование

10. **Delta Proxy (Salt 3004+)**: используйте для сотен устройств — один control proxy управляет группой, экономя процессы и ключи.
11. **Batching**: при массовом обновлении сетевых устройств используйте `batch: 10` или `batch: 20%` для избежания перегрузки.
12. **Standalone**: для изолированных сетей или >100 устройств разворачивайте proxy на отдельных хостах.

### DevOps / SRE

13. **Версионирование**: храните конфигурацию proxy (Pillar, proxymodules, grains) в Git; используйте CI/CD для проверки изменений через `salt '*' state.apply test=True`.
14. **Idempotent states**: все SLS-состояния для сетевых устройств должны быть безопасны для повторного запуска; используйте diff-проверку перед применением.
15. **GitFS**: храните SLS-файлы и proxymodules через `gitfs` для версионирования и code review.
16. **State orchestration**: используйте `salt.state` orchestrate для координации изменений на нескольких устройствах последовательно с rollback в случае ошибки.
17. **Job Cache**: используйте внешнее хранилище (PostgreSQL/Redis) для `ext_job_cache`, чтобы сохранять историю команд на сетевых устройствах.
18. **cleanup**: при декомиссии устройства удаляйте запись из Pillar `top.sls`, удаляйте ключ через `salt-key -d <id>`, останавливайте `systemctl stop salt-proxy@<id>`.

### Ограничения и edge cases

- **Grains рано в загрузке**: custom grains в `/srv/salt/_grains/` загружаются раньше `__proxy__` и `__opts__['proxy']` — используйте `try/except KeyError` в `__virtual__()`.
- **Salt-SSH vs Proxy**: для устройств с SSH-доступом можно использовать Salt-SSH вместо proxy, но proxy лучше для постоянного управления (Beacon, Reactor, State).
- **State для network**: не все state-модули работают с proxy — используйте `net.*`, `netmiko.*`, `napalm.*` модули.
- **Proxy и Pillar**: каждый proxy видит только свои Pillar-ключи (изоляция по proxyid через `top.sls`).

---

## Дополнительная информация

### Примеры execution/state-модулей

**NAPALM execution modules (Salt 3008.x):**

```bash
# Сеть
salt 'switch-01' net.facts
salt 'switch-01' net.interfaces
salt 'switch-01' net.arp
salt 'switch-01' net.mac
salt 'switch-01' net.config source=running
salt 'switch-01' net.config source=candidate

# BGP
salt 'switch-01' bgp.neighbors

# NTP
salt 'switch-01' ntp.servers

# SNMP
salt 'switch-01' snmp.config
```

**Netmiko execution module:**

```bash
salt 'branch-01' netmiko.send_command 'show version'
salt 'branch-01' netmiko.send_config config='interface Gi0/1\ndescription TEST'
salt 'branch-01' netmiko.commit
salt 'branch-01' netmiko.call 'send_config_set' config=['interface Gi0/1']
```

### См. также

- [Архитектура SaltStack](Architecture.md) — модель Pub/Sub, PKI, транспорты
- [Формулы SaltStack](Formulas.md) — переиспользуемые пакеты состояний
- [Безопасность SaltStack](Security_Approaches.md) — PKI, SDB, Vault, eAuth
- [Мониторинг SaltStack](Salt_Monitoring.md) — healthcheck и метрики
- [Salt-SSH продвинутый](Salt_SSH_Advanced.md) — roster_grains и ProxyJump
- [Оркестрация и автоматизация](Orchestration_and_Automation_Methods.md) — Reactor, Beacon
- [Сетевая автоматизация](../Networking/ServicesAndTools/network_automation.md) — NAPALM, Netmiko, Nornir (standalone)
- [Официальная документация Salt Proxy Minion](https://docs.saltproject.io/en/latest/topics/proxyminion/index.html)
- [Официальный lifecycle](https://endoflife.date/salt)
