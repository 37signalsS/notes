# Кроссплатформенные соединения: SSH, WinRM, bastion и тюнинг

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.18+ | 2.21.4+ | 2.22.0b1 доступен (сентябрь 2026) |
| **OpenSSH** (клиент) | 8.0+ | 10.5+ | 10.5 — актуальный релиз (август 2026) |
| **PyWinRM** | 0.4+ | 0.5.0+ | Требуется для `winrm` connection plugin |
| **pypsrp** | 0.11+ | 0.11+ | Требуется для `psrp` connection plugin |
| **Kerberos** | MIT / Heimdal | System | Для доменных сред Windows |
| **libssh** | 0.30+ | Актуальная | Для `ansible.netcommon.libssh` |

## Определения

- **Connection plugin** — плагин, отвечающий за транспорт данных и выполнение команд на управляемом хосте. Полный список встроенных и community плагинов, параметров и примеров см. в [Ansible: Плагины подключения](../Modules/ansible_connection_plugins.md).
- **SSH Multiplexing (ControlPersist)** — механизм OpenSSH, переиспользующий одно TCP-соединение для нескольких SSH-сессий. Убирает накладные расходы на handshake и аутентификацию.
- **SSH Pipelining** — передача модулей через STDIN вместо создания временного файла. Ускоряет выполнение на 30–50%, но требует отключения `requiretty` в sudoers.
- **Bastion / Jump host** — промежуточный хост для доступа к управляемым узлам в изолированных сетях. Настраивается через `ProxyJump` или `ProxyCommand`.
- **WinRM** — протокол удаленного управления Windows (WS-Management), порты 5985 HTTP / 5986 HTTPS. Альтернатива SSH для Windows.
- **PSRP (PowerShell Remoting Protocol)** — протокол выполнения PowerShell-команд поверх WinRM. Передает сериализованные объекты PowerShell, а не текст.
- **WinRM transport** — метод аутентификации: `basic`, `ntlm`, `kerberos`, `credssp`, `cert`, `negotiate` (PSRP).
- **CredSSP** — протокол аутентификации с делегированием учетных данных. Необходим для операций, требующих повторного использования учетных данных на целевом хосте (например, установка MSI).
- **`ansible_ssh_common_args`** — дополнительные аргументы SSH для всех соединений (ProxyJump, StrictHostKeyChecking).
- **`ansible_winrm_transport`** — транспорт WinRM для Windows-хостов.
- **`host_key_checking`** — проверка SSH-ключей хостов. Включена по умолчанию (`True`), защищает от MITM-атак.
- **Persistent Connection** — долгоживущее соединение, переиспользуемое между задачами в рамках плейбука. Реализуется через Unix-сокет на контрольном узле. Критично для сетевого оборудования и Windows.

## Основные концепции

### Архитектура соединений: SSH vs WinRM vs PSRP

| Протокол | ОС | Порт по умолчанию | Аутентификация | Примечания |
| :--- | :--- | :--- | :--- | :--- |
| SSH | Linux, macOS, BSD, Windows (SSH Server) | 22 | Ключи, пароль | Рекомендуется для Windows Server 2019+ |
| WinRM | Windows | 5985 HTTP / 5986 HTTPS | Basic, NTLM, Kerberos, CredSSP, cert | По умолчанию в доменных средах |
| PSRP | Windows поверх WinRM | 5985 HTTP / 5986 HTTPS | NTLM, Kerberos, CredSSP, Negotiate | Передает объекты PowerShell, а не текст |
| Local | Контрольный узел | — | — | Для локальных задач |

```yaml
# inventory — Linux через SSH
web01.example.com:
  ansible_host: 192.168.1.10
  ansible_user: deploy
  ansible_ssh_private_key_file: ~/.ssh/id_ed25519
  ansible_python_interpreter: /usr/bin/python3

# inventory — Windows через WinRM (NTLM)
win01.example.com:
  ansible_host: 192.168.1.20
  ansible_user: administrator
  ansible_password: "{{ vault_winrm_password }}"
  ansible_connection: winrm
  ansible_winrm_transport: ntlm
  ansible_winrm_server_cert_validation: ignore

# inventory — Windows через WinRM (Kerberos, доменная среда)
win02.example.com:
  ansible_host: win02.internal
  ansible_user: DOMAIN\ansible
  ansible_connection: winrm
  ansible_winrm_transport: kerberos
  ansible_winrm_https: true
  ansible_winrm_server_cert_validation: validate
  ansible_winrm_ca_trust_path: /etc/ssl/certs/ca-certificates.crt

# inventory — Windows через PSRP (Kerberos, доменная среда)
win03.example.com:
  ansible_host: win03.internal
  ansible_user: DOMAIN\ansible
  ansible_connection: psrp
  ansible_psrp_transport: kerberos
  ansible_psrp_cert_validation: validate
```

### SSH-тюнинг для кроссплатформенных парков

`ansible.cfg` содержит критические параметры для производительности и стабильности SSH-соединений.

```ini
# ansible.cfg — оптимизированный для production
[defaults]
forks = 20
timeout = 60
host_key_checking = True
log_path = /var/log/ansible/playbook.log
stdout_callback = yaml

[privilege_escalation]
become = True
become_method = sudo
become_user = root

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s -o ServerAliveInterval=30 -o ServerAliveCountMax=3
pipelining = True
control_path = /tmp/ansible-ssh-%h-%p-%r
retries = 3
control_path_dir = /tmp
```

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `forks` | Параллельные SSH-сессии | 20–50 для больших парков; по умолчанию 5 |
| `timeout` | Таймаут соединения (секунды) | 60–120 для WAN; 30 для LAN |
| `pipelining` | Передача модулей через STDIN | `True` для ускорения на 30–50% |
| `ControlPersist` | Время жизни SSH-мультиплексирования | `3600s` (1 час) для частых запусков |
| `ServerAliveInterval` | Интервал keepalive | `30` секунд для предотвращения разрывов |
| `ServerAliveCountMax` | Число unanswered keepalive | `3` перед разрывом |
| `control_path` | Шаблон сокета ControlMaster | `/tmp/ansible-ssh-%h-%p-%r` |
| `control_path_dir` | Директория для сокетов | `/tmp` или `~/.ansible/cp` |
| `retries` | Число повторных попыток SSH | `3` для нестабильных сетей |

```bash
# Проверка действующих SSH-соединений
ps aux | grep ssh | grep ControlMaster
# → user 12345 ssh -o ControlMaster=auto -o ControlPersist=3600s ...

# Сброс ControlPersist сокетов (при смене прав)
ansible all -m shell -a "exit" --ssh-extra-args="-O exit"

# Проверка конфигурации SSH
ansible-config dump | grep -E "forks|pipelining|timeout|ssh_args"
```

> **Production note:** `pipelining = True` требует отключения `requiretty` в sudoers (`Defaults !requiretty`). На RHEL/CentOS 7 и старше `requiretty` включен по умолчанию. ControlPersist кэширует соединения — при смене прав доступа старая сессия может удерживать неактуальные привилегии. Сбрасывайте сокеты после изменения sudoers.

### Bastion / Jump host для изолированных сетей

Для доступа к хостам в изолированных сетях (DMZ, VLAN) используйте bastion-хост.

```ini
# ~/.ssh/config — глобальная конфигурация
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
# Переопределение на уровне инвентаря
dmz_web01:
  ansible_host: 10.0.2.10
  ansible_ssh_common_args: '-o ProxyJump=deploy@bastion.internal:22'
  ansible_user: deploy
  ansible_python_interpreter: /usr/bin/python3
```

```yaml
# Использование delegate_to через bastion
- name: Синхронизация между двумя удаленными серверами
  ansible.posix.synchronize:
    src: /data/app/
    dest: /data/backup/
    mode: pull
  delegate_to: "{{ groups['backup_server'][0] }}"
  # Первый сервер → Bastion → Backup server
```

> **Production note:** При использовании `delegate_to` между двумя удаленными серверами через bastion требуется проброс SSH-агента (`ForwardAgent yes`), чтобы первый сервер мог авторизоваться на втором. Настройте `ssh-agent` на Control Node и добавьте ключ: `ssh-add ~/.ssh/id_ed25519`. Для SRE: каждый hop добавляет латентность. При масштабировании >500 узлов через единый bastion оцените кластеризацию bastion (HAProxy + несколько инстансов) или VPN-туннели (WireGuard, IPSec) как альтернативу.

### WinRM: настройка, транспорты, безопасность

WinRM — стандарт для Windows в доменных средах. Для рабочих групп подходит NTLM или Basic над HTTPS.

**Настройка WinRM на Windows-хосте (PowerShell от администратора):**

```powershell
# Базовая настройка (HTTP, рабочая группа)
winrm quickconfig -q
Set-Item WSMan:\localhost\Service\AllowUnencrypted $true
Set-Item WSMan:\localhost\Service\Auth\Basic $true
New-NetFirewallRule -Name WinRM-HTTP -DisplayName "WinRM HTTP" -Enabled True -Direction Inbound -Protocol TCP -LocalPort 5985

# Критические параметры для production
winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="2048"}'
winrm set winrm/config '@{MaxEnvelopeSizekb="500"}'
winrm set winrm/config/service '@{MaxConcurrentOperationsPerUser="50"}'
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "LocalAccountTokenFilterPolicy" -Value 1 -Type DWord

# Настройка для домена (HTTPS + Kerberos)
winrm quickconfig -q
$cert = New-SelfSignedCertificate -DnsName "$env:COMPUTERNAME" -CertStoreLocation Cert:\LocalMachine\My
New-Item WSMan:\localhost\Listener -Address * -Transport HTTPS -CertificateThumbPrint $cert.Thumbprint
Set-Item WSMan:\localhost\Service\Auth\Kerberos $true
Set-Item WSMan:\localhost\Service\Auth\CredSSP $true
New-NetFirewallRule -Name WinRM-HTTPS -DisplayName "WinRM HTTPS" -Enabled True -Direction Inbound -Protocol TCP -LocalPort 5986
```

```powershell
# Проверка слушателей WinRM
winrm enumerate winrm/config/listener

# Проверка слушателя HTTPS через OpenSSL
openssl s_client -connect win01.internal:5986

# Проверка порта через PowerShell
Test-NetConnection -ComputerName win01.internal -Port 5986

# Проверка через nc (Linux Control Node)
nc -zv win01.internal 5986
```

**Transport сравнение:**

| Транспорт | Безопасность | Делегирование | Рекомендация |
| :--- | :--- | :--- | :--- |
| `ntlm` | Средняя | Нет | Рабочие группы, тестовые среды |
| `kerberos` | Высокая | Да | Доменные среды (рекомендуется) |
| `credssp` | Высокая | Да | Double-hop, установка MSI с доступом к shares |
| `cert` | Высокая | Нет | Passwordless, сертификатная аутентификация |
| `basic` | Низкая (только HTTPS) | Нет | Не рекомендуется для production |
| `negotiate` (PSRP) | Высокая | Да | PSRP: Kerberos с fallback на NTLM |

```yaml
# WinRM с Kerberos (доменная среда)
windows_servers:
  hosts:
    win01.internal:
      ansible_user: DOMAIN\ansible
      ansible_connection: winrm
      ansible_winrm_transport: kerberos
      ansible_winrm_https: true
      ansible_winrm_server_cert_validation: validate
      ansible_winrm_ca_trust_path: /etc/ssl/certs/ca-certificates.crt
      ansible_winrm_operation_timeout_sec: 60
      ansible_winrm_read_timeout_sec: 70
      ansible_winrm_message_encryption: auto

# WinRM с NTLM (рабочая группа)
windows_servers_workgroup:
  hosts:
    win01:
      ansible_user: Administrator
      ansible_password: "{{ vault_admin_password }}"
      ansible_connection: winrm
      ansible_winrm_transport: ntlm
      ansible_winrm_server_cert_validation: ignore
      ansible_winrm_scheme: http

# PSRP с Negotiate (автоматический выбор Kerberos/NTLM)
windows_servers_psrp:
  hosts:
    win01.internal:
      ansible_user: DOMAIN\ansible
      ansible_connection: psrp
      ansible_psrp_transport: negotiate
      ansible_psrp_cert_validation: validate
```

> **Production note:** Kerberos — предпочтительный транспорт для доменных сред: SSO, делегирование, защита от replay-атак. Для CredSSP требуется дополнительная настройка на Control Node (`Set-Item WSMan:\localhost\Service\Auth\CredSSP $true`). Никогда не используйте `CredSSP` без необходимости — он расширяет радиус поражения при компрометации Control Node. Включайте логирование WinRM (`MaxShellsPerUser`, Event Log) для аудита. Для PSRP используется отдельный плагин `ansible.builtin.psrp` с переменными `ansible_psrp_*`. PSRP эффективнее передает структурированные данные, но требует PowerShell 5.1+ на целевом хосте.

### SSH vs WinRM для Windows

Windows Server 2019+ поддерживает OpenSSH Server, что позволяет использовать SSH вместо WinRM.

| Критерий | SSH | WinRM |
| :--- | :--- | :--- |
| Python на хосте | Обязателен | Не требуется |
| Аутентификация | Ключи, пароль | Basic, NTLM, Kerberos, CredSSP, cert |
| Производительность | Выше | Ниже (PSRP overhead) |
| Файрвол | Порт 22 | 5985/5986 |
| Модули | Все `ansible.builtin.*` + `win_*` | Только `win_*` через PSRP |
| Факты | Полный набор (как POSIX) | Урезанный набор (нет Ethernet-фактов) |
| Рекомендация | Windows Server 2019+ | Legacy Windows, доменные среды |

```yaml
# Windows через SSH (рекомендуется для Server 2019+)
win_ssh:
  hosts:
    win01.example.com:
      ansible_host: 192.168.1.20
      ansible_user: deploy
      ansible_ssh_private_key_file: ~/.ssh/id_ed25519
      ansible_python_interpreter: C:\Python311\python.exe
      ansible_connection: ssh
```

> **Production note:** При `ansible_connection=ssh` на Windows Python обязателен. Установите его через Chocolatey или скачайте с python.org. Путь задайте через `ansible_python_interpreter`. SSH для Windows требует OpenSSH Server (роль в Server 2019+ или самостоятельная установка). WinRM остается стандартом для унаследованных систем (Windows Server 2016/2012).

### Специфика macOS Control Node

Начиная с недавних версий Python/macOS, использование `winrm` и `psrp` connection plugins на контрольном узле macOS может завершаться ошибкой из-за изменений в `fork()` безопасности. Обходное решение:

```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=yes
export no_proxy=*
```

Для production-grade окружения используйте отдельный Linux Control Node или контейнер для Windows-автоматизации, чтобы избежать подобных ограничений платформы.

### Проверка соединений

```bash
# Проверка SSH-соединения (POSIX)
ansible all -m ping -i inventory.yml
# → web01 | SUCCESS => {"changed": false, "ping": "pong"}

# Проверка WinRM-соединения (Windows)
ansible windows_servers -m win_ping -i inventory.yml
# → win01 | SUCCESS => {"ping": "pong"}

# Детальная отладка соединения
ansible web01 -m ping -vvvv
# → показывает детали handshake, ключи, транспорт

# Проверка фактов после подключения
ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*"
# → "ansible_facts": { "os_family": "Debian" }
```

## Практические сценарии

### Сценарий 1: Полный цикл WinRM (доменная среда)

```yaml
# inventory/domain_windows.yml
windows_domain:
  hosts:
    win01.internal:
      ansible_user: DOMAIN\ansible
      ansible_connection: winrm
      ansible_winrm_transport: kerberos
      ansible_winrm_https: true
      ansible_winrm_server_cert_validation: validate
      ansible_winrm_ca_trust_path: /etc/ssl/certs/ca-certificates.crt
      ansible_winrm_operation_timeout_sec: 60
      ansible_winrm_read_timeout_sec: 70
      ansible_winrm_message_encryption: auto
```

```yaml
# Проверка connectivity и идемпотентности WinRM
- name: Проверка WinRM connectivity
  ansible.windows.win_ping:
  when: ansible_facts['os_family'] == 'Windows'

- name: Сбор фактов Windows
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - os_family
      - distribution
      - service_mgr
  when: ansible_facts['os_family'] == 'Windows'
```

### Сценарий 2: Bastion + delegate_to между удаленными серверами

```yaml
# inventory.yml
all:
  hosts:
    primary:
      ansible_host: 10.0.1.10
      ansible_user: deploy
      ansible_ssh_common_args: '-o ProxyJump=deploy@bastion:22'
    standby:
      ansible_host: 10.0.2.10
      ansible_user: deploy
      ansible_ssh_common_args: '-o ProxyJump=deploy@bastion:22'
  children:
    db_cluster:
      hosts:
        primary:
        standby:
```

```yaml
# Синхронизация данных между primary и standby через bastion
- name: Синхронизация через bastion
  ansible.posix.synchronize:
    src: /var/lib/postgresql/data/
    dest: /var/lib/postgresql/data/
    mode: pull
    use_ssh_args: yes
  delegate_to: "{{ groups['standby'][0] }}"
  when: inventory_hostname == groups['primary'][0]
```

### Сценарий 3: SSH pipelining + ControlPersist в mixed-парке

```ini
# ansible.cfg — оптимизация для mixed-парка
[defaults]
forks = 20
timeout = 60
host_key_checking = True

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new
pipelining = True
control_path = /tmp/ansible-ssh-%h-%p-%r
control_path_dir = /tmp
```

```yaml
# Отключение pipelining для конкретного хоста (если есть конфликты)
problematic_host:
  ansible_host: 10.0.3.10
  ansible_ssh_extra_args: '-o ControlPersist=no'
  # pipelining будет отключен для этого хоста
```

### Сценарий 4: Кроссплатформенная проверка connectivity

```yaml
- name: Проверка connectivity (все платформы)
  block:
    - name: Ping Linux/macOS
      ansible.builtin.ping:
      when: ansible_facts['system'] != 'Win32NT'

    - name: Ping Windows
      ansible.windows.win_ping:
      when: ansible_facts['os_family'] == 'Windows'

- name: Сбор минимальных фактов
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - '!min'
      - os_family
      - distribution
      - architecture
```

### Сценарий 5: Автоматический аудит соединений (SRE)

```yaml
- name: Сбор метрик соединений для SRE Dashboard
  hosts: all
  gather_facts: yes
  tasks:
    - name: Проверка доступности хоста
      ansible.builtin.wait_for:
        host: "{{ ansible_host }}"
        port: "{{ 22 if ansible_os_family != 'Windows' else 5986 }}"
        timeout: 10
      delegate_to: localhost
      register: conn_check

    - name: Запись результата connectivity
      ansible.builtin.set_fact:
        connection_health: "{{ 'reachable' if conn_check.elapsed is defined else 'unreachable' }}"

    - name: Логирование метрики latency
      ansible.builtin.debug:
        msg: "Host {{ inventory_hostname }} latency: {{ conn_check.elapsed | default('N/A') }}s"
```

### Сценарий 6: WinRM hardening через Ansible (новые хосты)

```yaml
- name: Базовая hardening WinRM для новых Windows-хостов
  hosts: windows_new
  connection: winrm
  vars:
    ansible_winrm_transport: ntlm
    ansible_winrm_scheme: http
    ansible_winrm_server_cert_validation: ignore
  tasks:
    - name: Установка MaxMemoryPerShellMB
      ansible.windows.win_shell: |
        winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="2048"}'

    - name: Установка MaxEnvelopeSizekb
      ansible.windows.win_shell: |
        winrm set winrm/config '@{MaxEnvelopeSizekb="500"}'

    - name: Включение LocalAccountTokenFilterPolicy
      ansible.windows.win_regedit:
        path: HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System
        name: LocalAccountTokenFilterPolicy
        data: 1
        type: dword

    - name: Гарантия firewall правила WinRM HTTPS
      community.windows.win_firewall_rule:
        name: "WinRM HTTPS"
        localport: 5986
        action: allow
        direction: in
        protocol: tcp
        state: present
        enabled: true
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible all -m ping` | Проверка SSH-соединения | `pong` от всех Linux/macOS/BSD |
| `ansible windows_servers -m win_ping` | Проверка WinRM-соединения | `pong` от Windows |
| `ansible windows_servers -m ansible.windows.win_ping` | То же через FQCN | `pong` от Windows |
| `ansible all -m ping -vvvv` | Детальная отладка соединения | Детали handshake, транспорта, аутентификации |
| `ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*"` | Проверка фактов | `"ansible_facts": { "os_family": "Debian" }` |
| `ansible-config dump | grep -E "forks|pipelining|timeout"` | Проверка SSH-конфига | Текущие параметры `ansible.cfg` |
| `ps aux | grep ssh | grep ControlMaster` | Проверка ControlPersist | Список активных multiplexed соединений |
| `ansible all -m shell -a "exit" --ssh-extra-args="-O exit"` | Сброс ControlPersist | Закрытие всех cached соединений |
| `ansible-doc -t connection -l` | Список доступных плагинов | Таблица connection plugins |
| `winrm enumerate winrm/config/listener` | Проверка WinRM слушателей (PowerShell) | Список активных слушателей |
| `nc -zv <host> 5986` | Проверка порта WinRM | Connection succeeded / failed |
| `Test-NetConnection -ComputerName <host> -Port 5986` | Проверка порта WinRM (PowerShell) | TcpTestSucceeded: True/False |

## Диагностика и устранение неполадок

### SSH

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `UNREACHABLE! => {"msg": "Failed to connect to the host via ssh"}` | Сеть/брандмауэр/ключи | `ansible <host> -m ping -vvvv` | Проверьте доступность порта 22, `known_hosts`, права на ключ |
| `MODULE_FAILURE: Error connecting: SSH error` | Конфликт `ssh_args` или `pipelining` | `ansible-config dump | grep ssh_args` | Отключите `pipelining` для диагностики, проверьте `ssh_args` |
| `sudo: sorry, you must have a tty to run sudo` | `requiretty` включен | `sudo -l` на целевом хосте | Отключите `Defaults !requiretty` в sudoers или отключите `pipelining` |
| `Host key verification failed` | Ключ хоста изменился | `ssh <host>` вручную | Обновите `known_hosts` через модуль `ansible.builtin.known_hosts` |
| `Permission denied (publickey)` | Ключ не принят | `ssh -vvv <host>` | Проверьте права на ключ (`chmod 600`), `ssh-agent` |
| `Connection timed out` | Брандмауэр/маршрут | `nc -zv <host> 22` | Проверьте маршрутизацию, security groups, `ServerAliveInterval` |
| `broken pipe` / `Connection reset by peer` | Нестабильная сеть | `dmesg` на хосте | Увеличьте `ServerAliveInterval` и `ServerAliveCountMax` |
| `No spaces in PATH` | Неправильный `ansible_python_interpreter` | `ansible <host> -m setup -a "filter=ansible_python*"` | Укажите полный путь к Python |

### WinRM / PSRP

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `401 Unauthorized` | Неверные учетные данные или `LocalAccountTokenFilterPolicy` | `winrm get winrm/config/service/auth` | Проверьте пароль в Vault, включите `LocalAccountTokenFilterPolicy` |
| `Connection refused` / `Connection timeout` | WinRM не запущен или порт закрыт | `Get-Service WinRM`, `nc -zv <host> 5986` | Запустите `winrm quickconfig`, проверьте firewall |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Self-signed или невалидный сертификат | `openssl s_client -connect <host>:5986` | Для тестов `ansible_winrm_server_cert_validation: ignore`; для production используйте валидный сертификат |
| `MaxMemoryPerShellMB` / `MaxEnvelopeSizekb` | Мало памяти для оболочки | `winrm get winrm/config/winrs` | Увеличьте до 2048 MB и 500 KB соответственно |
| `The WinRM client cannot process the request` | Большие возвращаемые данные | Просмотр размера вывода | Перенаправьте вывод в файл + используйте `slurp` |
| `Cannot credential delegate` | CredSSP не настроен | `winrm get winrm/config/service/auth` | Включите CredSSP на Control Node и целевом хосте |
| MacOS `fork()` ошибка | Изменения в Python/macOS безопасность | Ошибка при инициализации WinRM | `export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=yes` или используйте Linux Control Node |

### Bastion

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Proxy: All configured connections failed` | Bastion недоступен | `ssh -J deploy@bastion <target>` вручную | Проверьте доступность bastion, SSH-ключи, `ProxyJump` |
| `Agent admitted failure to sign` | `ssh-agent` не настроен | `ssh-add -l` | `eval $(ssh-agent)` и `ssh-add ~/.ssh/id_ed25519` |
| `Connection timed out` через bastion | Маршрут/брандмауэр | `ssh -vvv -J deploy@bastion <target>` | Проверьте пути к DMZ-хостам через bastion |

## Граничные случаи и ограничения

- **`pipelining` и `requiretty`**: на RHEL/CentOS 7 `requiretty` включен по умолчанию. Отключите (`Defaults !requiretty` в sudoers) или отключите `pipelining`.
- **ControlPersist и смена прав**: старая сессия удерживает неактуальные привилегии. Сбрасывайте сокеты после `chmod`/`chown` или изменения sudoers.
- **WinRM и большие выводы**: PSRP имеет ограничение на размер возвращаемых данных. Для больших выводов используйте `shell` с перенаправлением в файл + `slurp` (если нужно на контроллер).
- **WinRM и SSL**: при `ansible_winrm_https: true` требуются валидные сертификаты. Для self-signed используйте `ansible_winrm_ca_trust_path` или `ansible_winrm_server_cert_validation: ignore` (только для тестов).
- **SSH для Windows**: требует установленного Python и OpenSSH Server. Путь к Python задайте через `ansible_python_interpreter`.
- **CredSSP и радиус поражения**: при компрометации Control Node злоумышленник получает делегированные учетные данные на всех целевых хостах. Используйте только при необходимости.
- **Bastion и latency**: каждый hop добавляет задержку. Для высоконагруженных парков рассматривайте VPN или Direct Connect вместо bastion.
- **`host_key_checking = False` в production**: отключает защиту от MITM-атак. Используйте `StrictHostKeyChecking=accept-new` или управляйте `known_hosts` через модуль `ansible.builtin.known_hosts`.
- **MacOS Control Node + WinRM/PSRP**: начиная с недавних версий macOS, Python fork-safety может блокировать WinRM/PSRP. Используйте `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=yes` или выделенный Linux Control Node.
- **WinRM без Python**: WinRM не требует Python на целевом хосте, но Control Node требует `pywinrm` (winrm) или `pypsrp` (psrp). Устанавливайте их в виртуальном окружении: `pip install pywinrm pypsrp`.
- **PSRP и Windows Server 2012**: PSRP требует PowerShell 5.1+. Для Windows Server 2012 установите WMF 5.1.
- **WinRM message encryption over HTTP**: для шифрования на уровне сообщения требуется `pywinrm>=0.3.0`. Без этого Kerberos/NTLM over HTTP могут работать нестабильно.
- **delegate_to и become**: при использовании `delegate_to` через bastion `become` применяется на делегированном хосте, а не на исходном. Убедитесь, что учетная запись deploy имеет права на backup_server.

## Рекомендации и лучшие практики

1. **`pipelining = True` по умолчанию**: ускоряет выполнение на 30–50%. Отключайте только при конфликтах с `requiretty`.
2. **ControlPersist 1 час**: `ControlPersist=3600s` для частых запусков. Сбрасывайте сокеты после изменения прав.
3. **`ServerAliveInterval=30`**: предотвращает разрывы соединений в нестабильных сетях.
4. **Bastion через `ProxyJump`**: чище, чем `ProxyCommand`. Настраивайте в `ssh_config` или `ansible.cfg`.
5. **WinRM + Kerberos в доменных средах**: SSO, делегирование, безопасность. NTLM — только для рабочих групп.
6. **SSH для Windows Server 2019+**: выше производительность, стандартный набор модулей. Требует Python.
7. **Никогда `host_key_checking = False` в production**: используйте `known_hosts` модуль или `StrictHostKeyChecking=accept-new`.
8. **`forks = 20–50`**: по умолчанию 5 — недостаточно для больших парков. Настройте в `ansible.cfg`.
9. **Раздельные `ansible.cfg` для окружений**: prod, staging, dev — разные конфиги с разными `forks`, `timeout`, кэшами.
10. **Аудит соединений**: логируйте `ansible.cfg` и параметры соединения в CI/CD артефактах.
11. **Мониторинг соединений**: отслеживайте `UNREACHABLE` в callback plugins (yaml, json). Настраивайте алерты при росте ошибок подключения.
12. **Capacity planning для forks**: при parc > 100 узлов увеличивайте `forks` постепенно (20 → 50 → 100), контролируя нагрузку на Control Node (CPU, RAM, файловые дескрипторы).
13. **HTTPS для WinRM всегда**: используйте `ansible_winrm_https: true` с валидными сертификатами. Отключайте проверку сертификатов (`ignore`) только в dev/test.
14. **CredSSP только при необходимости**: расширяет радиус поражения. Для double-hop рассмотрите `become` или `win_scheduled_task` как более безопасные альтернативы.
15. **Хранение credentials**: все пароли и секреты храните в Ansible Vault. Никогда не коммитьте `ansible_password` в открытом виде.
16. **Документируйте topology**: ведите актуальный инвентарь bastion, VPN, firewall правил. Используйте `network_cli` / `httpapi` для сетевого оборудования.
17. **Тестируйте изменения конфигурации**: при изменении `ansible.cfg`, `ssh_args` или WinRM параметров тестируйте на pilot-группе перед массовым применением.
18. **Используйте Molecule**: тестируйте идемпотентность и корректность подключений на изолированных инстансах.

## Дополнительная информация

- [Автоматизация Windows через Ansible](../ansible_windows_automation.md) — настройка WinRM, транспорты, безопасность.
- [Управление SSH-ключами](../ansible_ssh_key_management.md) — `known_hosts`, `authorized_key`, `StrictHostKeyChecking`.
- [Оптимизация производительности](../ansible_performance_tuning.md) — `forks`, `pipelining`, `ControlPersist`, `fact_caching`.
- [Модули подключений](../Modules/ansible_connection_plugins.md) — `ssh`, `winrm`, `psrp`, `local`, `docker`, параметры.
- [Кроссплатформенные концепции](./concepts.md) — матрица платформ, `ansible_facts`, общие паттерны.
- [Кроссплатформенное выполнение](./ansible_cross_platform_execution_flow.md) — `strategy`, `serial`, `throttle`, `check_mode`, `async`, `tags`, `--limit`.
