# Автоматизация Windows через Ansible

## Определения

- **WinRM (Windows Remote Management)** — протокол удалённого управления Windows, альтернатива SSH, слушающий порт 5985 (HTTP) или 5986 (HTTPS). Основан на WS-Management (WS-MAN) и используется по умолчанию в средах Active Directory.
- **PSRP (PowerShell Remoting Protocol)** — протокол для выполнения PowerShell-команд на удалённых хостах поверх WinRM. Передаёт объекты PowerShell, а не текст, что обеспечивает структурированный обмен данными.
- **Ansible.Windows collection** — официальная коллекция `ansible.windows` для автоматизации Windows. Содержит модули с префиксом `win_`, plugin'ы connection и документацию.
- **WinRM transport** — метод аутентификации: `basic`, `ntlm`, `kerberos`, `credssp`, `negotiate`. Выбор зависит от наличия домена, необходимости делегирования учётных данных и политик безопасности.
- **CredSSP (Credential Security Support Provider)** — протокол аутентификации с делегированием учётных данных. Необходим для операций, которые требуют повторного использования учётных данных на целевом хосте (например, установка MSI-пакетов, которые в свою очередь обращаются к сетевому ресурсу).
- **Chocolatey** — менеджер пакетов для Windows (аналог apt/yum), поддерживающий зависимости, версионирование и развёртывание через DSC.
- **WinRM listener** — endpoint, принимающий входящие WinRM-соединения. Может быть настроен на HTTP (без шифрования) или HTTPS (с сертификатом).
- **PowerShell Remoting** — механизм удалённого выполнения PowerShell-команд. Включает в себя PSRP, сессии и конфигурации конечных точек (Endpoint Configuration).

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.19+ | 2.21+ |
| **Python** (control node) | 3.12+ | 3.14 |
| **PowerShell** (target) | 5.1 (Windows Server 2012+) | PowerShell 7.4+ |
| **.NET** (target) | 4.7.2+ | 4.8+ |
| **WinRM** | Встроен в Windows Server 2012+ / Windows 8+ | Последнее накопительное обновление |
| **ansible.windows collection** | 2.5.0+ | 2.5.0+ |
| **PyWinRM** | 0.4.3+ | 0.5.0+ |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.x]

ansible-galaxy collection list ansible.windows
# → ansible.windows 2.5.x
```

## Основные концепции

### Архитектура: SSH vs WinRM/PSRP

| Параметр | Linux/Unix | Windows |
|---|---|---|
| Протокол | SSH | WinRM/PSRP |
| Порт | 22 | 5985 (HTTP) / 5986 (HTTPS) |
| Аутентификация | SSH-ключи, пароль | Basic, NTLM, Kerberos, CredSSP |
| Python на управляемом узле | Требуется | Не требуется (PowerShell) |
| Control Node | Linux/macOS/WSL2 | Linux (рекомендуется) |
| Модель передачи | Текст/бинарный поток | Объекты PowerShell (PSRP) |

### Принцип работы WinRM/PSRP

WinRM является реализацией протокола **WS-Management** на стороне Windows. При выполнении задачи Ansible:

1. **Connection plugin (`winrm`)** устанавливает HTTP/HTTPS-соединение с WinRM listener на целевом хосте.
2. **Transport layer** аутентифицируется с помощью выбранного транспорта (`ntlm`, `kerberos`, `credssp`).
3. **PSRP** упаковывает PowerShell-команды в SOAP/WinRS-запросы, выполняет их и возвращает результат.
4. **Ansible** десериализует ответ, преобразует объекты PowerShell в JSON и применяет идемпотентность.

Для доменных сред Kerberos — предпочтительный транспорт (SSO, делегирование). Для рабочей группы — NTLM или Basic над HTTPS.

### Настройка WinRM на Windows-хосте

```powershell
# Быстрая настройка для тестовых сред
winrm quickconfig

# Включение PS Remoting (включает WinRM listener, настраивает firewall)
Enable-PSRemoting -Force

# Настройка HTTPS-listener (рекомендуется для production)
$cert = New-SelfSignedCertificate -DnsName "hostname.domain.com"
New-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address = "*"; Transport = "HTTPS"} -ValueSet @{CertificateThumbprint = $cert.Thumbprint; Enabled = $true}

# Настройка аутентификации
Set-Item WSMan:\localhost\Service\Auth\Basic -Value $true
Set-Item WSMan:\localhost\Service\Auth\Kerberos -Value $true
Set-Item WSMan:\localhost\Service\Auth\CredSSP -Value $true
```

**Важно:** На production используйте HTTPS (порт 5986) с валидным сертификатом. HTTP (порт 5985) допустим только во внутренних доверенных сетях.

### Inventory для Windows

```ini
# inventory.ini
[windows]
win-server1.example.com ansible_host=10.0.0.10
win-server2.example.com ansible_host=10.0.0.11

[windows:vars]
ansible_connection=winrm
ansible_winrm_transport=kerberos
ansible_winrm_server_cert_validation=ignore
ansible_port=5986
ansible_winrm_read_timeout_sec=30
ansible_winrm_operation_timeout_sec=20
```

```yaml
# inventory.yml
all:
  children:
    windows:
      hosts:
        win-server1.example.com:
          ansible_host: 10.0.0.10
        win-server2.example.com:
          ansible_host: 10.0.0.11
      vars:
        ansible_connection: winrm
        ansible_winrm_transport: kerberos
        ansible_winrm_server_cert_validation: ignore
```

### Ключевые модули Windows

| Модуль | Назначение |
|---|---|
| `ansible.windows.win_feature` | Установка/удаление ролей и возможностей Windows |
| `ansible.windows.win_service` | Управление службами (state, start_mode) |
| `ansible.windows.win_package` | Установка пакетов (MSI, EXE) |
| `ansible.windows.win_chocolatey` | Управление пакетами через Chocolatey |
| `ansible.windows.win_winget` | Управление пакетами через Windows Package Manager |
| `ansible.windows.win_user` | Управление локальными пользователями |
| `ansible.windows.win_firewall_rule` | Настройка Windows Firewall |
| `ansible.windows.win_regmerge` | Импорт .reg-файлов в реестр |
| `ansible.windows.win_template` | Шаблоны с расширением `.ps1`/`.j2` для Windows |
| `ansible.windows.win_shell` | Выполнение PowerShell/Script-команд |
| `ansible.windows.win_powershell` | PowerShell с поддержкой модулей PSEnvironment |
| `ansible.windows.win_domain_membership` | Присоединение/выход из домена |
| `ansible.windows.win_reboot` | Перезагрузка с контролем ожидания готовности |

Полный справочник параметров модулей — в [Модули управления пакетами](./Modules/ansible_package_management_modules.md).

### PowerShell в Ansible

```yaml
# win_shell — выполнение PowerShell-команд
- name: Получение информации о системе
  ansible.windows.win_shell: |
    Get-WmiObject -Class Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber
  register: os_info

# win_powershell — с поддержкой модулей и окружения
- name: Установка модуля PSWindowsUpdate
  ansible.windows.win_powershell:
    module_name: PSWindowsUpdate
    cmd: Get-WindowsUpdate
```

### Безопасность WinRM

- **HTTPS** — всегда используйте порт 5986 в production с валидным сертификатом.
- **Firewall** — ограничьте доступ к портам 5985/5986 только доверенными подсетями.
- **CredSSP** — используйте только при необходимости делегирования; требует дополнительных настроек на Control Node.
- **Kerberos** — предпочтительный транспорт для доменных сред; обеспечивает SSO и защиту от повторного использования учётных данных.
- **Аудит** — включите логирование WinRM (`Set-Item WSMan:\localhost\Shell\MaxShellsPerUser 10` и журналы Event Log).

## Практические сценарии

### Первичная настройка Windows-хоста

```yaml
---
- name: Bootstrap Windows
  hosts: windows_bootstrap
  gather_facts: false
  tasks:
    - name: Установка Python (для совместимости с legacy-сценариями)
      ansible.windows.win_shell: |
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" -OutFile "C:\python-installer.exe"
        Start-Process "C:\python-installer.exe" -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait
      become: true
      become_user: Administrator
```

### Управление сервисами

```yaml
---
- name: Управление сервисами Windows
  hosts: windows
  tasks:
    - name: Запуск службы IIS
      ansible.windows.win_service:
        name: W3SVC
        state: started
        start_mode: auto

    - name: Остановка ненужного сервиса
      ansible.windows.win_service:
        name: Spooler
        state: stopped
        start_mode: disabled
```

### Установка пакетов через Chocolatey

Полный справочник параметров модулей пакетов — в [Модули управления пакетами](./Modules/ansible_package_management_modules.md).

```yaml
---
- name: Установка ПО через Chocolatey
  hosts: windows
  tasks:
    - name: Установка Chocolatey
      ansible.windows.win_powershell:
        script: |
          Set-ExecutionPolicy Bypass -Scope Process -Force
          [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
          iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    - name: Установка пакетов
      ansible.windows.win_chocolatey:
        name:
          - googlechrome
          - vscode
          - git
          - notepadplusplus
        state: present
```

### Настройка Firewall

```yaml
---
- name: Настройка Windows Firewall
  hosts: windows
  tasks:
    - name: Разрешить HTTP-трафик
      ansible.windows.win_firewall_rule:
        name: Allow HTTP
        localport: 80
        action: allow
        direction: in
        protocol: tcp
        state: present
        enabled: yes

    - name: Запретить ICMP
      ansible.windows.win_firewall_rule:
        name: Block ICMP
        action: block
        direction: in
        protocol: icmpv4
        state: present
        enabled: yes
```

### Deploy IIS

```yaml
---
- name: Развёртывание IIS
  hosts: webservers_windows
  tasks:
    - name: Установка IIS
      ansible.windows.win_feature:
        name:
          - Web-Server
          - Web-Asp-Net45
          - Web-Net-Ext45
        state: present
        include_sub_features: true
        include_management_tools: true

    - name: Копирование сайта
      ansible.windows.win_copy:
        src: files/my_website/
        dest: C:\inetpub\wwwroot\

    - name: Запуск IIS
      ansible.windows.win_service:
        name: W3SVC
        state: started
```

### Join Domain

Полный справочник параметров — в [Автоматизация управления идентификацией](./ansible-identity-management.md).

```yaml
---
- name: Присоединение к домену
  hosts: windows
  tasks:
    - name: Присоединение к домену
      ansible.windows.win_domain_membership:
        dns_domain_name: corp.example.com
        hostname: "{{ inventory_hostname_short }}"
        domain_admin_user: admin@corp.example.com
        domain_admin_password: "{{ vault_domain_password }}"
        state: domain
      register: domain_result

    - name: Перезагрузка после присоединения
      ansible.windows.win_reboot:
      when: domain_result.reboot_required
```

### Key Rotation и обновление CredSSP-сертификатов

```yaml
---
- name: Key Rotation для WinRM
  hosts: windows
  tasks:
    - name: Генерация нового самоподписанного сертификата
      ansible.windows.win_powershell:
        script: |
          $cert = New-SelfSignedCertificate -DnsName "{{ inventory_hostname }}" -CertStoreLocation Cert:\LocalMachine\My
          $thumbprint = $cert.Thumbprint
          Write-Output $thumbprint
      register: new_cert

    - name: Обновление WinRM HTTPS listener
      ansible.windows.win_shell: |
        Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address = "*"; Transport = "HTTPS"} -ErrorAction SilentlyContinue
        New-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address = "*"; Transport = "HTTPS"} -ValueSet @{CertificateThumbprint = "{{ new_cert.stdout[0] }}"; Enabled = $true}

    - name: Перезагрузка службы WinRM
      ansible.windows.win_service:
        name: WinRM
        state: restarted
```

### Проверка идемпотентности WinRM-соединения

```yaml
---
- name: Проверка WinRM connectivity
  hosts: windows
  gather_facts: yes
  tasks:
    - name: Проверка фактов
      ansible.builtin.debug:
        var: ansible_facts.os_family

    - name: Проверка доступности порта 5986
      ansible.windows.win_shell: |
        Test-NetConnection -ComputerName localhost -Port 5986
      register: port_check

    - name: Отчёт
      ansible.builtin.debug:
        msg: "WinRM доступен: {{ port_check.stdout }}"
```

## Операции и команды

### Модуль ansible.windows.win_service

Полный справочник параметров — в [Модули управления пакетами и сервисами](./Modules/ansible_package_management_modules.md).

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `name` | string | Имя службы (обязательно) |
| `state` | string | `started`, `stopped`, `restarted`, `absent` |
| `start_mode` | string | `auto`, `manual`, `disabled` |
| `path` | string | Путь к исполняемому файлу (для создания службы) |

### Модуль ansible.windows.win_feature

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `name` | list / string | Роли/возможности (например, `Web-Server`, `RSAT-AD-PowerShell`) |
| `state` | string | `present`, `absent` |
| `include_sub_features` | boolean | Установить все подкомпоненты |
| `include_management_tools` | boolean | Установить инструменты управления |

### Модуль ansible.windows.win_chocolatey

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `name` | list | Имена пакетов |
| `state` | string | `present`, `absent`, `latest` |
| `version` | string | Конкретная версия пакета |
| `source` | string | Источник пакетов (URL или имя) |

### Модуль ansible.windows.win_shell / win_powershell

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `executable` | string | Интерпретатор (по умолчанию `powershell.exe`) |
| `creates` | path | Файл, при наличии которого задача пропускается |
| `removes` | path | Файл, при наличии которого задача выполняется |
| `stdin_add_newline` | boolean | Добавлять `\n` в stdin |

## Диагностика

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `winrm or http not installed` | Служба WinRM не запущена | `winrm quickconfig` |
| `401 Unauthorized` | Неверные учётные данные или неправильный transport | Проверьте `ansible_winrm_transport`, учётные данные и SPN для Kerberos |
| `The client cannot connect to the destination specified in the request` | Firewall или listener не настроен | Проверьте порт 5985/5986 и firewall rules |
| `Cannot process argument transformation on parameter` | Несовместимость версий PowerShell/PowerShell Remoting | Обновите PowerShell и WinRM |
| `Access is denied` при установке пакетов | Отсутствует `become` или CredSSP | Используйте `become: true` или настройте CredSSP |

### Диагностические команды

```powershell
# Проверка статуса WinRM
Get-Service WinRM
# → Status   Name               DisplayName
# → Running  WinRM              Windows Remote Management

# Проверка listener
winrm enumerate winrm/config/listener
# → Listener
# →   Address = *
# →   Transport = HTTPS
# →   Port = 5986
# →   Hostname = hostname.domain.com
# →   CertificateThumbprint = ABC123...

# Проверка подключения с отладкой
Test-WSMan -ComputerName localhost -Port 5986

# Проверка порта
Test-NetConnection -ComputerName localhost -Port 5986

# Проверка ролей IIS
Get-WindowsFeature -Name Web-Server
# → Display Name                    Name               Install State
# → [X] IIS  (Management Console)   Web-Mgmt-Console  Installed
```

```bash
# Проверка доступности хоста через Ansible
ansible windows -m win_ping
# → win-server1 | SUCCESS => {"changed": false, "ping": "pong"}

# Проверка с максимальной детализацией
ansible windows -m win_shell -a "Get-WmiObject Win32_OperatingSystem" -vvvv
```

## Лучшие практики

- **Идемпотентность:** Используйте `state` везде, где возможно. Избегайте `win_shell` для задач, для которых есть специализированные модули.
- **Become:** Для операций, требующих прав Administrator, используйте `become: true` и `become_method: runas`.
- **Vault:** Храните учётные данные (пароли, сертификаты) в `ansible-vault`. Никогда не передавайте их в открытом виде.
- **HTTPS:** Всегда используйте HTTPS (порт 5986) в production. Настройте валидацию сертификатов вместо `ansible_winrm_server_cert_validation=ignore`.
- **Kerberos:** В доменных средах используйте Kerberos вместо NTLM — он безопаснее и поддерживает делегирование.
- **Проверка фактов:** Используйте `gather_facts: yes` для Windows, чтобы получать `ansible_facts` об ОС и конфигурации.
- **Избегайте Python на Windows:** Для управления Windows используйте PowerShell-модули. Python на целевом хосте нужен только для `ansible_connection=ssh`.
- **Логирование:** Включите аудит WinRM и логирование PowerShell (`Start-Transcript`) для отладки.
- **NLA (Network Level Authentication):** Настройте NLA на WinRM listener для дополнительного уровня аутентификации.
- **Кросс-платформенные сценарии:** При управлении гетерогенным парком Linux/Windows используйте `when: ansible_facts['os_family'] == 'Windows'` для разделения логики.

## Дополнительная информация

- [Основы Ansible](./ansible_core_concepts.md) — фундаментальные концепции, push-модель, agentless
- [Установка и настройка](./ansible_setup_and_config.md) — настройка Control Node
- [Автоматизация управления идентификацией](./ansible-identity-management.md) — Active Directory, домены
- [Модули управления пакетами](./Modules/ansible_package_management_modules.md) — Chocolatey, Winget, MSI/EXE
- [Сетевая автоматизация](./ansible_network_automation.md) — автоматизация сетевого оборудования
- [Модули выполнения команд](./Modules/ansible_command_execution_modules.md) — `win_command`, `win_shell`, `win_powershell`
