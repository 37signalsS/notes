# Ansible: Плагины подключения

## Определения

**Connection Plugin (плагин подключения)** — компонент Ansible, определяющий механизм установки соединения между контрольным узлом (Control Node) и управляемым хостом (Managed Node) и передачи данных для выполнения задач. В отличие от модулей, которые выполняются *на целевом хосте*, плагины подключения работают *на контрольном узле* и отвечают за транспорт команд и файлов.

**Transport** — протокол или механизм, используемый плагином для взаимодействия с управляемым хостом (SSH, WinRM, REST API, Docker socket, gRPC и др.).

**Persistent Connection (долгоживущее соединение)** — механизм, при котором транспортное соединение переиспользуется между задачами в рамках одного плейбука. Устраняет накладные расходы на повторный хендшейк и аутентификацию. Реализуется через Unix-сокет на контрольном узле.

**Persistent Connection Plugin (`ansible.netcommon.persistent`)** — специализированный плагин, создающий долгоживущее соединение через Unix-сокет. Используется как основа для `network_cli`, `netconf`, `httpapi` и `winrm` в режиме persistent.

**PSRP (PowerShell Remoting Protocol)** — протокол выполнения PowerShell-команд поверх WinRM. В отличие от классического WinRM, передает сериализованные объекты PowerShell, а не текст, что снижает объем данных и упрощает работу со структурированными типами.

**gRPC Connection** — плагин для устройств, поддерживающих gRPC. Использует бинарный протокол поверх HTTP/2, что обеспечивает низкую задержку и типизированные запросы/ответы.

**libssh** — плагин SSH, использующий библиотеку `libssh` вместо вызова внешнего клиента OpenSSH. Позволяет избежать зависимостей от системного SSH и обеспечивает единое поведение на разных ОС.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.18+ | 2.21+ | 2.21 — текущий стабильный релиз (May 2026) |
| **ansible.netcommon** | 4.0+ | 8.5+ | 8.5.2 — стабильный релиз (May 2026) |
| **OpenSSH** (клиент) | 8.0+ | 10.5+ | 10.5 — актуальный релиз (Aug 2026) |
| **PyWinRM** | 0.4+ | 0.5+ | 0.5.0 — актуальный релиз |
| **Paramiko** | 3.3.2+ | — | Только для legacy `paramiko_ssh`; плагин deprecated |
| **libssh** | 0.30+ | Актуальная | Для `ansible.netcommon.libssh` |

**Проверка доступных плагинов:**
```bash
ansible-doc -t connection -l
# → ansible.builtin.local
# → ansible.builtin.psrp
# → ansible.builtin.ssh
# → ansible.builtin.winrm
# → ansible.netcommon.httpapi
# → ansible.netcommon.libssh
# → ansible.netcommon.netconf
# → ansible.netcommon.network_cli
# → ansible.netcommon.persistent
# → community.docker.docker
# → containers.podman.podman
```

## Основные концепции

### Архитектура и lifecycle

Connection plugin определяет три фазы взаимодействия:
1. **Установка соединения** — аутентификация, создание транспортного канала (SSH-сессия, WinRM-соединение, TCP-сокет).
2. **Передача модулей** — копирование кода модуля на целевой хост (в `/tmp` по умолчанию) или передача через STDIN (`pipelining`).
3. **Выполнение и сбор результатов** — запуск модуля, ожидание завершения, возврат JSON-результата на контрольный узел.

При использовании **persistent connection** фаза 1 выполняется один раз за весь плейбук, последующие задачи используют существующий канал. Это критично для сетевых устройств, где CLI-сессия может занимать несколько секунд на establishment.

### Разница между модулями и connection plugins

| Критерий | Модуль | Connection Plugin |
| :--- | :--- | :--- |
| **Где выполняется** | На управляемом хосте | На контрольном узле |
| **Назначение** | Выполнение конкретной задачи (установка пакета, копирование файла) | Организация транспортного канала |
| **Выбор** | В блоке `tasks:` через `name` модуля | В блоке `hosts:` через `connection:` или в инвентаре |
| **Количество** | Много задач в плейбуке | Один на хост (или группу) на плейбук |
| **Пример** | `ansible.builtin.package` | `ansible.builtin.ssh` |

### Стандартные плагины подключения

#### POSIX / Linux / macOS / BSD

**`ansible.builtin.ssh`** — стандартное подключение через системный клиент OpenSSH. Используется по умолчанию для Linux/Unix хостов. Поддерживает все возможности OpenSSH: multiplexing, агент forwarding, Jump host.

```yaml
# ansible.cfg
[defaults]
transport = ssh

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s
pipelining = True
forks = 30
timeout = 60
```

```ini
# ~/.ssh/config
Host web*
  User deploy
  Port 22
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking accept-new
  ServerAliveInterval 30
```

**`ansible.builtin.local`** — выполнение задач на контрольном узле. Используется для локальных операций, подготовки окружения, генерации конфигураций.

```yaml
- name: "Локальная операция"
  hosts: localhost
  connection: local
  tasks:
    - name: "Создание директории"
      ansible.builtin.file:
        path: /tmp/local_test
        state: directory
```

**`ansible.builtin.paramiko_ssh`** — альтернативное SSH-подключение через библиотеку Paramiko (Python). **DEPRECATED: удален в ansible-core 2.21.** Использовался, когда OpenSSH клиент недоступен или требовалась кроссплатформенная работа без зависимостей от системного SSH. Для legacy-окружений используйте `ansible.netcommon.libssh`.

```yaml
# Только для ansible-core < 2.21
- name: "Подключение через Paramiko"
  hosts: legacy_hosts
  connection: ansible.builtin.paramiko_ssh
  vars:
    ansible_ssh_common_args: "-o StrictHostKeyChecking=no"
```

**`ansible.netcommon.libssh`** — современная альтернатива OpenSSH и Paramiko, использующая библиотеку `libssh`. Не требует установленного клиента SSH, поддерживает те же возможности аутентификации и шифрования.

```yaml
- name: "Подключение через libssh"
  hosts: linux_servers
  connection: ansible.netcommon.libssh
  vars:
    ansible_user: deploy
    ansible_ssh_private_key_file: ~/.ssh/id_ed25519
```

#### Windows

**`ansible.builtin.winrm`** — подключение к Windows через WinRM (WS-Management, порты 5985 HTTP / 5986 HTTPS). Стандартное решение для Windows Server 2016/2012 и рабочих групп.

```yaml
- name: "Управление Windows"
  hosts: windows_servers
  connection: ansible.builtin.winrm
  vars:
    ansible_user: Administrator
    ansible_password: "{{ vault_admin_password }}"
    ansible_winrm_transport: ntlm
    ansible_winrm_server_cert_validation: ignore
    ansible_winrm_operation_timeout_sec: 60
    ansible_winrm_read_timeout_sec: 70
```

**Транспорты WinRM:**
| Транспорт | Безопасность | Сценарий |
| :--- | :--- | :--- |
| `ntlm` | Средняя | Рабочие группы, быстрая настройка |
| `kerberos` | Высокая | Доменные среды (рекомендуется) |
| `credssp` | Средняя/Высокая | Azure, делегирование учетных данных |
| `cert` | Высокая | Аутентификация по сертификату |
| `basic` | Низкая | Только над HTTPS, не рекомендуется |

**`ansible.builtin.psrp`** — подключение через PowerShell Remoting Protocol поверх WinRM. Передает сериализованные объекты PowerShell, что эффективно для возврата структурированных данных. Требует PowerShell 5.1+ на целевом хосте.

```yaml
- name: "Управление Windows через PSRP"
  hosts: windows_servers
  connection: ansible.builtin.psrp
  vars:
    ansible_user: Administrator
    ansible_password: "{{ vault_admin_password }}"
    ansible_psrp_transport: ntlm
    ansible_psrp_cert_validation: ignore
```

#### Сетевое оборудование

**`ansible.netcommon.network_cli`** — подключение через SSH к CLI сетевого устройства. Оптимизировано для обработки приветствий (banner), отключения пагинации (terminal length 0), управления prompt и перевода в режим привилегий (`enable`).

```yaml
- name: "Настройка Cisco"
  hosts: cisco_switches
  connection: ansible.netcommon.network_cli
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
    ansible_become: yes
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"
    ansible_command_timeout: 30
    ansible_connect_timeout: 30
```

**`ansible.netcommon.httpapi`** — подключение через REST/HTTP API. Используется для устройств с поддержкой REST (Arista eAPI, Cisco NX-API, FortiOS). Самый производительный метод для современных дата-центров, так как не требует парсинга CLI-вывода.

```yaml
- name: "Настройка через API"
  hosts: arista_switches
  connection: ansible.netcommon.httpapi
  vars:
    ansible_network_os: arista.eos.eos
    ansible_httpapi_use_ssl: yes
    ansible_httpapi_validate_certs: no
    ansible_httpapi_host: "{{ inventory_hostname }}"
    ansible_httpapi_port: 443
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
```

**`ansible.netcommon.netconf`** — подключение через NETCONF (RFC 6242, порт 830). Используется для Juniper Junos, Cisco IOS-XR. Работает в режимах `xml` (по умолчанию) и `text`.

```yaml
- name: "Управление через NETCONF"
  hosts: juniper_routers
  connection: ansible.netcommon.netconf
  vars:
    ansible_network_os: juniperdevices.junos.junos
    ansible_user: admin
    ansible_password: "{{ vault_juniper_password }}"
    ansible_netconf_ssh_args: "-o ControlMaster=auto"
    ansible_netconf_xml_mode: true
```

**`ansible.netcommon.grpc`** — подключение через gRPC для устройств с поддержкой этого протокола. Обеспечивает низкую задержку и типизированные ответы.

```yaml
- name: "Управление через gRPC"
  hosts: cisco_routers
  connection: ansible.netcommon.grpc
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_grpc_host: "{{ inventory_hostname }}"
    ansible_grpc_port: 57344
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
```

#### Контейнеры и виртуализация

**`community.docker.docker`** — подключение к Docker-контейнерам через Docker socket на хосте или удаленный Docker API.

```yaml
- name: "Управление контейнером"
  hosts: app_container
  connection: community.docker.docker
  vars:
    ansible_host: "{{ container_ip }}"
    ansible_user: root
```

**`community.docker.docker_api`** — управление Docker-контейнерами через Docker Remote API (TCP/HTTPS). Используется, когда socket недоступен или требуется удаленное управление.

**`containers.podman.podman`** — подключение к Podman-контейнерам через Podman API или socket.

```yaml
- name: "Управление Podman контейнером"
  hosts: app_container
  connection: containers.podman.podman
  vars:
    ansible_host: "{{ container_ip }}"
```

**`containers.podman.buildah`** — взаимодействие с существующим контейнером Buildah для сборки образов без демона.

**`community.general.lxc` / `community.general.lxd`** — управление LXC/LXD контейнерами через `lxc` CLI или библиотеку Python.

**`community.general.wsl`** — выполнение задач в дистрибутиве WSL через `wsl.exe`.

### Настройка persistent connection

Для сетевых устройств, Windows и любых долгоживущих соединений persistent connection снижает накладные расходы.

```ini
# ansible.cfg — глобальная конфигурация persistent connection
[persistent_connection]
connect_timeout = 30
command_timeout = 30
```

```yaml
# Для network_cli / netconf / httpapi
- name: "Настройка persistent connection"
  hosts: cisco_switches
  connection: ansible.netcommon.network_cli
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_persistent_connect_timeout: 60
    ansible_persistent_command_timeout: 60
```

### Конфигурация параметров

Параметры connection plugins задаются на трех уровнях (приоритет от высшего к низшему):
1. **Переменные задачи/плейбука** — `vars:` в задаче или плейбуке.
2. **Переменные инвентаря** — `vars:` для хоста/группы в инвентаре.
3. **Конфигурация ansible.cfg** — `[ssh_connection]`, `[persistent_connection]` и секции плагинов.

#### Основные переменные инвентаря

| Переменная | Назначение | Применяется к |
| :--- | :--- | :--- |
| `ansible_connection` | FQCN плагина подключения | Все плагины |
| `ansible_host` | IP или hostname управляемого узла | Все плагины |
| `ansible_user` | Логин для аутентификации | SSH, WinRM, network_cli, netconf, httpapi |
| `ansible_password` | Пароль (храните в Vault) | SSH, WinRM, network_cli, netconf, httpapi |
| `ansible_ssh_private_key_file` | Путь к приватному ключу | SSH, libssh |
| `ansible_port` | Порт подключения | SSH (22), WinRM (5985/5986) |
| `ansible_ssh_common_args` | Дополнительные аргументы SSH | SSH, libssh, network_cli |
| `ansible_python_interpreter` | Путь к Python на целевом хосте | Все, кроме local и pure-API плагинов |
| `ansible_become` | Флаг escalation | SSH, WinRM, network_cli |
| `ansible_become_method` | Метод escalation (`sudo`, `enable`, `su`) | SSH, network_cli |
| `ansible_become_password` | Пароль для escalation | SSH, network_cli |

#### Переменные для WinRM

| Переменная | Назначение |
| :--- | :--- |
| `ansible_winrm_transport` | Транспорт: `ntlm`, `kerberos`, `credssp`, `cert`, `basic` |
| `ansible_winrm_server_cert_validation` | `ignore` или `validate` |
| `ansible_winrm_scheme` | `http` или `https` |
| `ansible_winrm_port` | Порт (по умолчанию 5985/5986) |
| `ansible_winrm_path` | Путь к endpoint (по умолчанию `/wsman`) |
| `ansible_winrm_ca_trust_path` | Путь к CA-сертификатам для Kerberos |
| `ansible_winrm_operation_timeout_sec` | Таймаут операции (сек) |
| `ansible_winrm_read_timeout_sec` | Таймаут чтения (сек) |
| `ansible_winrm_message_encryption` | `always`, `never`, `auto` |

#### Переменные для network_cli / httpapi / netconf

| Переменная | Назначение |
| :--- | :--- |
| `ansible_network_os` | FQCN network OS (`cisco.ios.ios`, `arista.eos.eos`, `juniperdevices.junos.junos`) |
| `ansible_command_timeout` | Таймаут выполнения CLI-команды (сек) |
| `ansible_connect_timeout` | Таймаут установки соединения (сек) |
| `ansible_persistent_connect_timeout` | Таймаут persistent соединения (сек) |
| `ansible_persistent_command_timeout` | Таймаут команды в persistent соединении (сек) |
| `ansible_httpapi_use_ssl` | `true`/`false` — использовать HTTPS |
| `ansible_httpapi_validate_certs` | `true`/`false` — проверка сертификатов |
| `ansible_httpapi_host` | Хост API (если отличается от `ansible_host`) |
| `ansible_httpapi_port` | Порт API |
| `ansible_netconf_ssh_args` | Дополнительные аргументы SSH для NETCONF |
| `ansible_netconf_xml_mode` | `true`/`false` — формат ответа XML |

### Persistent connection и SSH-тюнинг

**ControlPersist** — механизм OpenSSH, переиспользующий одно TCP-соединение для нескольких SSH-сессий. Убирает накладные расходы на handshake и аутентификацию.

```ini
# ansible.cfg
[ssh_connection]
control_path = /tmp/ansible-ssh-%h-%p-%r
control_path_dir = /tmp
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s -o ServerAliveInterval=30 -o ServerAliveCountMax=3
pipelining = True
forks = 30
timeout = 60
retries = 3
```

**SSH Pipelining** — передача модулей через STDIN вместо создания временного файла на целевом хосте. Ускоряет выполнение на 30–50%, но требует отключения `requiretty` в sudoers.

```bash
# Проверка ControlPersist
ps aux | grep ssh | grep ControlMaster
# → user 12345 ssh -o ControlMaster=auto -o ControlPersist=3600s ...
```

Для изолированных сетей (DMZ, VLAN) используйте **Bastion / Jump host**:

```ini
# ~/.ssh/config
Host bastion
  HostName bastion.internal
  User deploy
  Port 22
  IdentityFile ~/.ssh/id_ed25519

Host *.dmz.internal
  ProxyJump bastion
  User deploy
  IdentityFile ~/.ssh/id_ed25519
```

```yaml
# ansible.cfg — ProxyJump для всех соединений
[ssh_connection]
ssh_args = -o ProxyJump=deploy@bastion.internal:22 -o ControlMaster=auto -o ControlPersist=3600s
```

```yaml
# inventory — переопределение на уровне группы
dmz_web01:
  ansible_host: 10.0.2.10
  ansible_ssh_common_args: '-o ProxyJump=deploy@bastion.internal:22'
  ansible_user: deploy
  ansible_python_interpreter: /usr/bin/python3
```

> **Production note:** При использовании `delegate_to` между двумя удаленными серверами через bastion требуется проброс SSH-агента (`ForwardAgent yes`), чтобы первый сервер мог авторизоваться на втором.

## Практические сценарии

### Сценарий 1: Полный цикл WinRM (рабочая группа, NTLM)

```yaml
# inventory/windows_workgroup.yml
windows_servers:
  hosts:
    win01:
      ansible_host: 192.168.1.20
      ansible_user: Administrator
      ansible_password: "{{ vault_admin_password }}"
      ansible_connection: winrm
      ansible_winrm_transport: ntlm
      ansible_winrm_server_cert_validation: ignore
      ansible_winrm_scheme: http
      ansible_winrm_port: 5985
```

```yaml
- name: "Управление Windows серверами"
  hosts: windows_servers
  connection: ansible.builtin.winrm
  tasks:
    - name: "Проверка connectivity"
      ansible.windows.win_ping:

    - name: "Создание директории"
      ansible.windows.win_file:
        path: C:\Deploy\app
        state: directory

    - name: "Установка роли IIS"
      ansible.windows.win_feature:
        name: Web-Server
        state: present
```

### Сценарий 2: Доменная среда Windows (Kerberos)

```yaml
# inventory/windows_domain.yml
windows_domain:
  hosts:
    win01.internal:
      ansible_host: 10.0.1.10
      ansible_user: DOMAIN\ansible
      ansible_password: "{{ vault_domain_password }}"
      ansible_connection: winrm
      ansible_winrm_transport: kerberos
      ansible_winrm_server_cert_validation: validate
      ansible_winrm_ca_trust_path: /etc/ssl/certs/ca-certificates.crt
      ansible_winrm_scheme: https
      ansible_winrm_port: 5986
```

> **Production note:** Kerberos — предпочтительный транспорт для доменных сред: SSO, делегирование, защита от replay-атак. Никогда не используйте `CredSSP` без необходимости — он расширяет радиус поражения при компрометации Control Node.

### Сценарий 3: Cisco через network_cli с persistent connection

```yaml
- name: "Настройка коммутаторов Cisco"
  hosts: cisco_switches
  connection: ansible.netcommon.network_cli
  gather_facts: no
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
    ansible_become: yes
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"
    ansible_persistent_connect_timeout: 60
    ansible_persistent_command_timeout: 60
```

Полные примеры resource модулей (`cisco.ios.ios_vlans`, `ios_interfaces`) см. в [Ansible: Модули управления сетевым оборудованием](./ansible_network_device_modules.md).

### Сценарий 4: Arista через httpapi

```yaml
- name: "Настройка Arista через API"
  hosts: arista_switches
  connection: ansible.netcommon.httpapi
  gather_facts: no
  vars:
    ansible_network_os: arista.eos.eos
    ansible_httpapi_use_ssl: yes
    ansible_httpapi_validate_certs: no
    ansible_httpapi_host: "{{ inventory_hostname }}"
    ansible_httpapi_port: 443
    ansible_user: admin
    ansible_password: "{{ vault_network_password }}"
```

Полные примеры resource модулей (`arista.eos.eos_interfaces`, `eos_static_routes`) см. в [Ansible: Модули управления сетевым оборудованием](./ansible_network_device_modules.md).

### Сценарий 5: Juniper через NETCONF

```yaml
- name: "Управление Juniper через NETCONF"
  hosts: juniper_routers
  connection: ansible.netcommon.netconf
  gather_facts: no
  vars:
    ansible_network_os: juniperdevices.junos.junos
    ansible_user: admin
    ansible_password: "{{ vault_junios_password }}"
    ansible_netconf_ssh_args: "-o ControlMaster=auto"
```

Полные примеры resource модулей (`juniperdevices.junos.junos_interfaces`, `junos_l3_interfaces`) см. в [Ansible: Модули управления сетевым оборудованием](./ansible_network_device_modules.md).

### Сценарий 6: Mixed-парк Linux/Windows через bastion

```yaml
# inventory/mixed_park.yml
linux_web:
  hosts:
    web01.internal:
      ansible_host: 10.0.1.10
      ansible_user: deploy
      ansible_ssh_common_args: '-o ProxyJump=deploy@bastion.internal:22'
      ansible_python_interpreter: /usr/bin/python3

windows_servers:
  hosts:
    win01.internal:
      ansible_host: 10.0.1.20
      ansible_user: Administrator
      ansible_password: "{{ vault_admin_password }}"
      ansible_connection: winrm
      ansible_winrm_transport: ntlm
      ansible_winrm_server_cert_validation: ignore
```

```yaml
- name: "Настройка mixed-парка"
  hosts: all
  tasks:
    - name: "Сбор фактов"
      ansible.builtin.setup:

    - name: "Локальная задача на Control Node"
      delegate_to: localhost
      connection: local
      run_once: yes
      ansible.builtin.debug:
        msg: "ОС {{ ansible_facts['os_family'] }} на {{ inventory_hostname }}"
```

### Сценарий 7: Docker/Podman container management

```yaml
- name: "Управление Docker контейнером"
  hosts: docker_host
  connection: community.docker.docker
  vars:
    ansible_host: "{{ docker_host_ip }}"
    ansible_user: root
  tasks:
    - name: "Запуск контейнера"
      community.docker.docker_container:
        name: nginx
        image: nginx:alpine
        state: started
        restart_policy: unless-stopped
        ports:
          - "80:80"
          - "443:443"
```

```yaml
- name: "Управление Podman контейнером"
  hosts: podman_host
  connection: containers.podman.podman
  vars:
    ansible_host: "{{ podman_host_ip }}"
  tasks:
    - name: "Запуск Podman контейнера"
      containers.podman.podman_container:
        name: webapp
        image: docker.io/library/nginx:alpine
        state: started
        restart_policy: unless-stopped
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible-doc -t connection -l` | Список доступных плагинов подключения | Перечень всех зарегистрированных connection plugins |
| `ansible-doc -t connection ansible.netcommon.network_cli` | Документация по конкретному плагину | Описание параметров, примеры, зависимости |
| `ansible all -m ping` | Проверка SSH-соединения | `pong` от всех POSIX-хостов |
| `ansible windows_servers -m win_ping` | Проверка WinRM-соединения | `pong` от Windows-хостов |
| `ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*"` | Проверка сбора фактов | `"ansible_facts": { "os_family": "Debian" }` |
| `ansible all -m shell -a "exit" --ssh-extra-args="-O exit"` | Сброс cached SSH-соединений | Закрытие всех активных ControlPersist-сокетов |
| `ps aux \| grep ssh \| grep ControlMaster` | Проверка активных SSH-мультиплексоров | Список процессов `ssh -o ControlMaster=auto ...` |
| `ansible-config dump \| grep -E "forks\|pipelining\|timeout"` | Проверка текущих параметров ansible.cfg | Текущие значения параметров |
| `ansible all -m shell -a "hostname" -vvvv` | Детальная отладка соединения | Лог handshake, транспорта, аутентификации |

## Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Timeout waiting for persistent connection` | Таймаут SSH-соединения или перегрузка Control Node | Увеличьте `persistent_connect_timeout` в `ansible.cfg`; проверьте `forks` |
| `Permission denied (publickey,password)` | Неверные credentials или отсутствующий ключ | Проверьте `ansible_user`, `ansible_password` или `ansible_ssh_private_key_file`; убедитесь, что ключ добавлен в `ssh-agent` |
| `No matching group exception` | Устаревшая версия коллекции Cisco/Juniper | `ansible-galaxy collection install --upgrade cisco.ios` |
| `Invalid input detected` | Неподдерживаемая версия IOS | Проверьте `ansible_facts.version` и используйте `when:` для условий |
| `Could not connect to host` | Неверный IP/hostname или Firewall | Проверьте `ansible_host`, порт 22/5985/5986/830, доступность маршрута |
| `MODULE FAILURE` | Python отсутствует на устройстве | Убедитесь, что `ansible_connection` = `network_cli`/`netconf`/`httpapi` (модули выполняются на Control Node) |
| `Unable to enter configuration mode` | `become_method: enable` не работает | Проверьте `ansible_become_password` или отключите enable-пароль |
| `netconf` XML parsing error | Неподдерживаемый YANG-модуль | Проверьте `yangdump` на устройстве или используйте `network_cli` |
| `Commit failed` (Juniper) | Конфликт конфигураций | Используйте `check: true` перед `commit: true` |
| `401 Unauthorized` (WinRM) | Неверные credentials или неверный транспорт | Проверьте `ansible_user`/`ansible_password` и `ansible_winrm_transport` |
| `WinRM: Cannot find the server` | Некорректное имя хоста или DNS | Проверьте `ansible_host`, разрешение имен, firewall на порту 5985/5986 |
| `PSRP: Message too large` | Превышен лимит размера ответа | Увеличьте `ansible_psrp_max_payload_size_mb` или перенаправьте вывод в файл + `slurp` |
| `SSH: host key verification failed` | Ключ хоста отсутствует или изменился | Добавьте хост в `known_hosts` через модуль `ansible.builtin.known_hosts` или настройте `StrictHostKeyChecking` |
| `pipelining ignored` | `requiretty` включен в sudoers | Отключите `Defaults !requiretty` в `/etc/sudoers` или отключите `pipelining` в `ansible.cfg` |

## Best Practices

1. **Ключи вместо паролей**: используйте SSH-ключи с `ssh-agent`. Для Windows в доменных средах используйте Kerberos.
2. **ControlPersist 1 час**: `ControlPersist=3600s` для частых запусков. Сбрасывайте сокеты после изменения прав или sudoers.
3. **SSH Pipelining**: включаетcя по умолчанию в современных версиях. Убедитесь, что `requiretty` отключен на целевых хостах.
4. **ServerAliveInterval=30**: предотвращает разрывы соединений в нестабильных сетях.
5. **Bastion через ProxyJump**: предпочитайте `ProxyJump` устаревшему `ProxyCommand`. Настраивайте в `ssh_config` или `ansible.cfg`.
6. **WinRM + Kerberos**: предпочтительный транспорт для доменных сред. NTLM — только для рабочих групп.
7. **SSH для Windows Server 2019+**: выше производительность, стандартный набор модулей. Требует установленного Python и OpenSSH Server.
8. **Никогда не отключайте `host_key_checking` в production**: используйте `StrictHostKeyChecking=accept-new` или управляйте `known_hosts` через модуль `ansible.builtin.known_hosts`.
9. **`forks = 20–50`**: по умолчанию 5 — недостаточно для больших парков. Настройте в `ansible.cfg` под размер инфраструктуры.
10. **Раздельные `ansible.cfg` для окружений**: prod, staging, dev — разные конфиги с разными `forks`, `timeout`, кэшами.
11. **Network OS факты**: всегда задавайте `ansible_network_os` для сетевых устройств. Это позволяет Ansible выбирать правильный cliconf/httpapi/netconf плагин.
12. **Vault для credentials**: храните пароли, ключи и секреты в Ansible Vault. Никогда не хардкодьте учетные данные в инвентаре.
13. **Избегайте `ansible.builtin.paramiko` / `paramiko_ssh`**: плагины deprecated и удалены в ansible-core 2.21. Используйте `ansible.builtin.ssh` или `ansible.netcommon.libssh`.
14. **Валидация сертификатов**: в production всегда используйте `ansible_httpapi_validate_certs: true` и `ansible_winrm_server_cert_validation: validate`.

## Дополнительная информация

- **[Ansible Connection Plugins](https://docs.ansible.com/ansible/latest/collections/index_connection.html)** — полный индекс всех плагинов подключения.
- **[SSH Connection](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/ssh_connection.html)** — документация `ansible.builtin.ssh`.
- **[WinRM Connection](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/winrm_connection.html)** — документация WinRM.
- **[PSRP Connection](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/psrp_connection.html)** — документация PSRP.
- **[Network CLI Connection](https://docs.ansible.com/ansible/latest/collections/ansible/netcommon/network_cli_connection.html)** — документация `network_cli`.
- **[HTTPAPI Connection](https://docs.ansible.com/ansible/latest/collections/ansible/netcommon/httpapi_connection.html)** — документация `httpapi`.
- **[NETCONF Connection](https://docs.ansible.com/ansible/latest/collections/ansible/netcommon/netconf_connection.html)** — документация `netconf`.
- **[Docker Connection](https://docs.ansible.com/ansible/latest/collections/community/docker/docker_connection.html)** — документация Docker подключения.
- **[Podman Connection](https://docs.ansible.com/ansible/latest/collections/containers/podman/podman_connection.html)** — документация Podman подключения.
- **[Кроссплатформенные соединения: SSH, WinRM, bastion и тюнинг](../CrossPlatform/ansible_cross_platform_connection.md)** — детальный разбор SSH-тюнинга, bastion, WinRM транспортов и безопасности.
- **[Автоматизация сетевого оборудования](../ansible_network_automation.md)** — практические сценарии работы с network_cli, netconf, httpapi и устранение ошибок.
- **[Автоматизация Windows](../ansible_windows_automation.md)** — настройка WinRM, транспорты, безопасность.
