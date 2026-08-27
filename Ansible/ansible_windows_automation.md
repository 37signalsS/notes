# Автоматизация Windows через Ansible

## Определения

- **WinRM (Windows Remote Management)** — протокол удалённого управления Windows, альтернатива SSH, слушающий порт 5985 (HTTP) или 5986 (HTTPS)
- **PSRP (PowerShell Remoting Protocol)** — протокол для выполнения PowerShell-команд на удалённых хостах поверх WinRM
- **Ansible.Windows collection** — официальная коллекция для автоматизации Windows (модули `win_*`)
- **WinRM transport** — метод аутентификации: Basic, Kerberos, NTLM, CredSSP
- **Chocolatey** — менеджер пакетов для Windows (аналог apt/yum)
- **WinRM listener** — Endpoint, принимающий входящие WinRM-соединения
- **CredSSP** — протокол аутентификации с делегированием учётных данных, необходимый для некоторых операций Windows

## Основные концепции

### Архитектура: SSH vs WinRM/PSRP

| Параметр | Linux/Unix | Windows |
|---|---|---|
| Протокол | SSH | WinRM/PSRP |
| Порт | 22 | 5985 (HTTP) / 5986 (HTTPS) |
| Аутентификация | SSH-ключи, пароль | Basic, NTLM, Kerberos, CredSSP |
| Python | Требуется | Не требуется (PowerShell) |
| Control Node | Linux/macOS/WSL2 | Linux (рекомендуется) |

### Настройка WinRM на Windows-хосте

```powershell
# Быстрая настройка
winrm quickconfig

# Включение PS Remoting
Enable-PSRemoting -Force

# Настройка HTTPS-listener
$cert = New-SelfSignedCertificate -DnsName "hostname.domain.com"
New-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address = "*"; Transport = "HTTPS"} -ValueSet @{CertificateThumbprint = $cert.Thumbprint; Enabled = $true}

# Настройка аутентификации
Set-Item WSMan:\localhost\Service\Auth\Basic -Value $true
Set-Item WSMan:\localhost\Service\Auth\Kerberos -Value $true
```

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
| `ansible.windows.win_feature` | Установка/удаление ролей Windows |
| `ansible.windows.win_service` | Управление сервисами |
| `ansible.windows.win_package` | Установка пакетов (MSI, EXE) |
| `ansible.windows.win_user` | Управление пользователями |
| `ansible.windows.win_firewall_rule` | Настройка Firewall |
| `ansible.windows.win_regmerge` | Импорт реестра |
| `ansible.windows.win_template` | Шаблоны для Windows |
| `ansible.windows.win_shell` | Выполнение PowerShell |
| `ansible.windows.win_powershell` | PowerShell с модулями |

### PowerShell в Ansible

```yaml
# win_shell — выполнение PowerShell-команд
- name: Получение информации о системе
  ansible.windows.win_shell: |
    Get-WmiObject -Class Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber
  register: os_info

# win_powershell — с поддержкой модулей
- name: Установка модуля
  ansible.windows.win_powershell:
    module_name: PSWindowsUpdate
    cmd: Get-WindowsUpdate
```

### Безопасность

- **HTTPS** — всегда используйте 5986 порт в production
- **CredSSP** — для операций, требующих делегирования учётных данных
- **Firewall** — ограничьте доступ к порту 5985/5986
- **Аудит** — включите логирование WinRM

## Практические сценарии

### Первичная настройка Windows-хоста

```yaml
---
- name: Bootstrap Windows
  hosts: windows_bootstrap
  gather_facts: false
  tasks:
    - name: Установка Python (для ansible_connection=ssh)
      ansible.windows.win_shell: |
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe" -OutFile "C:\python-installer.exe"
        Start-Process "C:\python-installer.exe" -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait
      become: true
      become_user: Administrator
```

### Установка пакетов через Chocolatey

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

### Управление сервисами

```yaml
---
- name: Управление сервисами Windows
  hosts: windows
  tasks:
    - name: Запуск 서비스 IIS
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

## Дополнительная информация

- [Основы Ansible](./ansible_core_concepts.md) — фундаментальные концепции
- [Установка и настройка](./ansible_setup_and_config.md) — настройка Control Node
- [Сетевая автоматизация](./ansible_network_automation.md) — автоматизация сетевого оборудования