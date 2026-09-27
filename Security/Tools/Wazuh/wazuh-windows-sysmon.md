# Windows-мониторинг в Wazuh: Sysmon, Event Channels, PowerShell

## Определения

**Windows Event Channel** — подсистема Windows для сбора логов событий (Security, System, Application, PowerShell, Sysmon). В Wazuh 5.0 агент нативно подключается к Event Channels через `eventchannel` log_format.

**Sysmon (System Monitor)** — утилита Microsoft для детального мониторинга системных событий: создание процессов, сетевые соединения, изменения файлов, реестра, DNS-запросов. Sysmon расширяет стандартные Event Channels.

**PowerShell Logging** — система логирования PowerShell: Module Logging, Script Block Logging, Transcription. Позволяет отслеживать выполнение скриптов и обнаруживать вредоносные команды.

**MITRE ATT&CK for Windows** — тактики и техники атак, специфичные для Windows-сред: lateral movement (RDP, SMB, WMI), persistence (Scheduled Tasks, Registry, Services), privilege escalation (Token Manipulation, DLL Hijacking).

## Основные концепции

### Архитектура Windows-мониторинга

```
┌──────────────────────────────────────────────┐
│              Windows Agent                    │
│                                               │
│  ┌──────────────┐  ┌────────────────────────┐│
│  │ Event Channel │  │ Sysmon                 ││
│  │ Security      │  │ (процессы, сеть, файлы)││
│  │ System        │  └──────────┬─────────────┘│
│  │ Application   │             │              │
│  │ PowerShell    │             │              │
│  └───────┬───────┘             │              │
│          │                     │              │
│  ┌───────┴─────────────────────┴─────────────┐│
│  │        Wazuh Agent (logcollector)         ││
│  └──────────────────┬───────────────────────┘│
└─────────────────────┼────────────────────────┘
                      │ TCP 1514 (mTLS)
                      ▼
              ┌───────────────┐
              │ Wazuh Manager │
              └───────────────┘
```

### Ключевые Event ID

| Event ID | Источник | Описание | MITRE |
|:---|:---|:---|:---|
| **4688** | Security | Создание процесса | T1059 |
| **4689** | Security | Завершение процесса | - |
| **4624** | Security | Успешный вход | T1078 |
| **4625** | Security | Неудачный вход | T1110 |
| **4672** | Security | Назначение привилегий | T1134 |
| **4697** | Security | Установка сервиса | T1543.003 |
| **4698** | Security | Создание Scheduled Task | T1053.005 |
| **4720** | Security | Создание учётной записи | T1136 |
| **4732** | Security | Добавление в локальную группу | T1098 |
| **4768/4769** | Security | Kerberos TGT/Service Ticket | T1558 |
| **7045** | System | Установка сервиса | T1543.003 |
| **1** | Sysmon | Создание процесса | T1059 |
| **3** | Sysmon | Сетевое соединение | T1071 |
| **7** | Sysmon | Загрузка DLL | T1574 |
| **8** | Sysmon | CreateRemoteThread | T1055 |
| **10** | Sysmon | Process Access | T1003 |
| **11** | Sysmon | File Create | T1105 |
| **12/13/14** | Sysmon | Registry Event | T1112 |
| **15** | Sysmon | File Create Stream | T1564.004 |
| **22** | Sysmon | DNS Query | T1071.004 |
| **4103** | PowerShell | Module Logging | T1059.001 |
| **4104** | PowerShell | Script Block Logging | T1059.001 |

## Практические сценарии

### 1. Установка Sysmon на Windows

```powershell
# Скачивание Sysmon
Invoke-WebRequest -Uri "https://download.sysinternals.com/files/Sysmon.zip" -OutFile "$env:TEMP\Sysmon.zip"
Expand-Archive "$env:TEMP\Sysmon.zip" -DestinationPath "C:\Tools\Sysmon"

# Установка с конфигурацией
C:\Tools\Sysmon\Sysmon64.exe -accepteula -i C:\Tools\Sysmon\sysmonconfig.xml
```

### 2. Sysmon конфигурация для Wazuh

```xml
<!-- sysmonconfig.xml -->
<Sysmon schemaversion="4.90">
  <HashAlgorithms>md5,sha256,IMPHASH</HashAlgorithms>
  <CheckRevocation/>
  <EventFiltering>
    <!-- Процессы: логируем все, кроме штатных -->
    <ProcessCreate onmatch="exclude">
      <Image condition="is">C:\Windows\System32\svchost.exe</Image>
      <Image condition="is">C:\Windows\System32\wininit.exe</Image>
    </ProcessCreate>

    <!-- Сетевые соединения -->
    <NetworkConnect onmatch="include">
      <DestinationPort condition="is">445</DestinationPort>
      <DestinationPort condition="is">3389</DestinationPort>
      <DestinationPort condition="is">5985</DestinationPort>
      <DestinationPort condition="is">5986</DestinationPort>
      <DestinationPort condition="is">4444</DestinationPort>
      <DestinationPort condition="is">8443</DestinationPort>
    </NetworkConnect>

    <!-- Файловые события -->
    <FileCreate onmatch="include">
      <TargetFilename condition="contains">C:\Users\*\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup</TargetFilename>
      <TargetFilename condition="contains">C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup</TargetFilename>
    </FileCreate>

    <!-- Реестр -->
    <RegistryEvent onmatch="include">
      <TargetObject condition="contains">HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run</TargetObject>
      <TargetObject condition="contains">HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce</TargetObject>
      <TargetObject condition="contains">HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run</TargetObject>
    </RegistryEvent>

    <!-- DNS -->
    <DnsQuery onmatch="include"/>
  </EventFiltering>
</Sysmon>
```

### 3. agent.conf для Windows с Sysmon

```xml
<!-- /var/wazuh-manager/etc/groups/windows-sysmon/agent.conf -->
<ossec_config>
  <!-- Security Event Channel -->
  <localfile>
    <location>Security</location>
    <log_format>eventchannel</log_format>
    <only-future-events>yes</only-future-events>
  </localfile>

  <!-- System Event Channel -->
  <localfile>
    <location>System</location>
    <log_format>eventchannel</log_format>
    <only-future-events>yes</only-future_events>
  </localfile>

  <!-- Sysmon Event Channel -->
  <localfile>
    <location>Microsoft-Windows-Sysmon/Operational</location>
    <log_format>eventchannel</log_format>
    <only-future-events>yes</only-future-events>
  </localfile>

  <!-- PowerShell Script Block Logging -->
  <localfile>
    <location>Microsoft-Windows-PowerShell/Operational</location>
    <log_format>eventchannel</log_format>
    <only-future-events>yes</only-future-events>
  </localfile>

  <!-- PowerShell Module Logging -->
  <localfile>
    <location>Windows PowerShell</location>
    <log_format>eventchannel</log_format>
  </localfile>

  <!-- FIM для критических путей -->
  <syscheck>
    <directories check_all="yes" whodata="yes">C:\Windows\System32\config</directories>
    <directories check_all="yes" whodata="yes">C:\Windows\System32\drivers\etc</directories>
    <directories check_all="yes" whodata="yes">C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup</directories>
    <ignore type="sregex">.*\.(tmp|log|etl)$</ignore>
  </syscheck>
</ossec_config>
```

### 4. Правила для обнаружения вредоносной активности

```xml
<!-- /var/wazuh-manager/etc/rules/local_rules.xml -->
<group name="windows,malware,">
  <!-- Обнаружение обфусцированного PowerShell -->
  <rule id="100500" level="12">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Microsoft-Windows-PowerShell/Operational</field>
    <field name="data.win.system.eventID">4104</field>
    <field name="data.win.eventdata.scriptBlockText">(?i)(FromBase64String|Invoke-Expression|IEX|DownloadString|Net\.WebClient)</field>
    <description>Obfuscated PowerShell detected on $(hostname)</description>
    <mitre>
      <id>T1059.001</id>
    </mitre>
  </rule>

  <!-- Создание процесса из Word/Excel -->
  <rule id="100501" level="12">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Microsoft-Windows-Sysmon/Operational</field>
    <field name="data.win.system.eventID">1</field>
    <field name="data.win.eventdata.parentImage">(?i)(WINWORD|EXCEL|POWERPNT|OUTLOOK)\.EXE</field>
    <field name="data.win.eventdata.image">(?i)(cmd|powershell|wscript|cscript|mshta|rundll32|regsvr32)\.exe</field>
    <description>Suspicious process spawned from Office application on $(hostname)</description>
    <mitre>
      <id>T1059</id>
    </mitre>
  </rule>

  <!-- Scheduled Task создан через командную строку -->
  <rule id="100502" level="10">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Security</field>
    <field name="data.win.system.eventID">4698</field>
    <field name="data.win.eventdata.taskContent">(?i)(schtasks|Register-ScheduledTask|New-ScheduledTask)</field>
    <description>Scheduled Task created via command line on $(hostname)</description>
    <mitre>
      <id>T1053.005</id>
    </mitre>
  </rule>

  <!-- RDP-сессия с нового IP -->
  <rule id="100503" level="8">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Security</field>
    <field name="data.win.system.eventID">4624</field>
    <field name="data.win.eventdata.logonType">10</field>
    <field name="data.win.eventdata.ipAddress">^(?!10\.0\.0\.)(?!192\.168\.)(?!127\.).*\.</field>
    <description>RDP logon from external IP $(data.win.eventdata.ipAddress) on $(hostname)</description>
    <mitre>
      <id>T1021.001</id>
    </mitre>
  </rule>

  <!-- Kerberoasting -->
  <rule id="100504" level="10">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Security</field>
    <field name="data.win.system.eventID">4769</field>
    <field name="data.win.eventdata.ticketEncryptionType">0x17</field>
    <field name="data.win.eventdata.ticketOptions">0x40810000</field>
    <description>Potential Kerberoasting detected on $(hostname) - RC4 ticket requested</description>
    <mitre>
      <id>T1558.003</id>
    </mitre>
  </rule>

  <!-- Pass-the-Hash -->
  <rule id="100505" level="12">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Security</field>
    <field name="data.win.system.eventID">4624</field>
    <field name="data.win.eventdata.logonType">9</field>
    <field name="data.win.eventdata.authenticationPackage">NTLM</field>
    <description>Potential Pass-the-Hash detected on $(hostname)</description>
    <mitre>
      <id>T1550.002</id>
    </mitre>
  </rule>

  <!-- DNS-запрос на подозрительный домен -->
  <rule id="100506" level="8">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Microsoft-Windows-Sysmon/Operational</field>
    <field name="data.win.system.eventID">22</field>
    <field name="data.win.eventdata.queryName">(?i)\.(top|xyz|tk|ml|ga|cf|gq|pw|cc|ws|click|link|download)$</field>
    <description>Suspicious DNS query to TLD $(data.win.eventdata.queryName) on $(hostname)</description>
    <mitre>
      <id>T1071.004</id>
    </mitre>
  </rule>

  <!-- Mimikatz-подобная активность -->
  <rule id="100507" level="15">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Microsoft-Windows-Sysmon/Operational</field>
    <field name="data.win.system.eventID">1</field>
    <field name="data.win.eventdata.originalFileName">(?i)(mimikatz|sekurlsa|kerberos|lsadump|crypto|vault|dpapi)</field>
    <description>CRITICAL: Mimikatz-like process detected on $(hostname)</description>
    <mitre>
      <id>T1003.001</id>
    </mitre>
  </rule>
</group>
```

### 5. Включение PowerShell-логирования через GPO/скрипт

```powershell
# Включение Script Block Logging
$regPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging"
New-Item -Path $regPath -Force
Set-ItemProperty -Path $regPath -Name "EnableScriptBlockLogging" -Value 1

# Включение Module Logging
$regPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ModuleLogging"
New-Item -Path $regPath -Force
Set-ItemProperty -Path $regPath -Name "EnableModuleLogging" -Value 1

# Включение Transcription
$regPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription"
New-Item -Path $regPath -Force
Set-ItemProperty -Path $regPath -Name "EnableTranscripting" -Value 1
Set-ItemProperty -Path $regPath -Name "OutputDirectory" -Value "C:\PSTranscripts"

# Перезапуск PowerShell для применения
Write-Host "PowerShell logging enabled. Restart PowerShell sessions."
```

### 6. Ansible: массовая установка Sysmon

```yaml
---
- name: Deploy Sysmon on Windows agents
  hosts: windows_agents
  become: yes
  vars:
    sysmon_url: "https://download.sysinternals.com/files/Sysmon.zip"
    sysmon_config_url: "https://your-server/sysmonconfig.xml"
  tasks:
    - name: Download Sysmon
      win_get_url:
        url: "{{ sysmon_url }}"
        dest: "C:\\Temp\\Sysmon.zip"

    - name: Extract Sysmon
      win_shell: |
        Expand-Archive -Path "C:\Temp\Sysmon.zip" -DestinationPath "C:\Tools\Sysmon" -Force
      args:
        creates: "C:\\Tools\\Sysmon\\Sysmon64.exe"

    - name: Download Sysmon config
      win_get_url:
        url: "{{ sysmon_config_url }}"
        dest: "C:\\Tools\\Sysmon\\sysmonconfig.xml"

    - name: Install Sysmon
      win_command: "C:\\Tools\\Sysmon\\Sysmon64.exe -accepteula -i C:\\Tools\\Sysmon\\sysmonconfig.xml"
      register: sysmon_install
      changed_when: "'Sysmon installed' in sysmon_install.stdout"

    - name: Ensure Sysmon service is running
      win_service:
        name: Sysmon64
        state: started
        start_mode: auto
```

### 7. Threat Hunting: PowerShell-запросы

```kql
# Поиск Invoke-Mimikatz
data.win.eventdata.scriptBlockText:(*Invoke-Mimikatz* OR *DumpCreds* OR *DumpCerts*)

# Поискateral movement через WMI
data.win.eventdata.eventID:4688 AND data.win.eventdata.parentImage:*WmiPrvSE.exe
AND data.win.eventdata.newProcessImage:(*cmd.exe* OR *powershell.exe*)

# Поиск создания Scheduled Task из PowerShell
data.win.eventdata.eventID:4698 AND data.win.eventdata.taskContent:(*Register-ScheduledTask* OR *New-ScheduledTask*)
AND NOT data.win.system.user:*SYSTEM*

# Поиск обфусцированных команд
data.win.eventdata.scriptBlockText:(*Char*|*Convert*|*-Join*|*Environment*|*-replace*)
AND data.win.eventdata.scriptBlockText.length:>200
```

## Дополнительная информация

### Сравнение: стандартные Event Channels vs Sysmon

| Критерий | Event Channels | Sysmon |
|:---|:---|:---|
| **Установка** | Встроен в Windows | Требует установки |
| **Процессы** | Только 4688 (базовый) | 1 (полный командной строкой) |
| **Сеть** | Ограниченный | Полный (порты, DNS) |
| **Реестр** | Ограниченный | Полный |
| **DLL** | Нет | Да (загрузка) |
| **DNS** | Нет | Да |
| **Нагрузка** | Низкая | Средняя |
| **Рекомендация** | Минимум | Рекомендуется |

### Best Practices

1. **Sysmon обязателен** для production Windows-среды.
2. **Script Block Logging** — включите на всех серверах.
3. **Имена агентов**: используйте hostname + роль (e.g., `WIN-WEB-01`).
4. **Группы**: создайте отдельные группы для Windows-ролей (web, db, dc).
5. **Корреляция**: комбинируйте Sysmon + Security + PowerShell для полной картины.

### См. также
- [Container Monitoring](./container_monitoring.md) — мониторинг Docker/K8s.
- [Kernel Monitoring](./kernel_monitoring.md) — Linux-аналог Sysmon.
- [Threat Hunting](./wazuh-threat-hunting.md) — hunting-запросы.
