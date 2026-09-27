# Массовая установка агентов Wazuh

## Определения

**Mass Deployment** — процесс установки Wazuh-агентов на большое количество хостов (100+) одновременно. Использует автоматизацию: Ansible, Puppet, SaltStack, cloud-init, GPO.

**Enrollment Key** — ключ регистрации, позволяющий агентам автоматически регистрироваться на менеджере без ручного добавления. Обеспечивает безопасную доставку сертификатов.

**Auto-registration** — автоматическая регистрация агентов при первом подключении к менеджеру. Требует включённого `enrollment` в конфигурации агента.

**Pre-shared Key (PSK)** — предварительно расшаренный ключ для аутентификации агентов при регистрации. Альтернатива mTLS для начального этапа.

## Основные концепции

### Стратегии массовой установки

```
┌─────────────────────────────────────────────┐
│  1. Ansible (рекомендуется)                  │
│     - Идиемпотентность                       │
│     - Dynamic inventory                      │
│     - Rolling update                         │
├─────────────────────────────────────────────┤
│  2. Cloud-init (cloud VMs)                   │
│     - User-data script                       │
│     - Автоустановка при provision            │
├─────────────────────────────────────────────┤
│  3. GPO (Windows Domain)                     │
│     - Group Policy                           │
│     - MSI-пакет через GPO                    │
├─────────────────────────────────────────────┤
│  4. PXE + Preseed/Autoinstall (bare-metal)   │
│     - Автоматическая установка ОС + агент    │
├─────────────────────────────────────────────┤
│  5. SaltStack/Puppet (если уже есть)         │
│     - State/Module для Wazuh                │
└─────────────────────────────────────────────┘
```

## Практические сценарии

### 1. Ansible: массовая установка Linux агентов

```yaml
---
- name: Deploy Wazuh agents
  hosts: all
  become: yes
  vars:
    wazuh_manager: "10.0.0.20"
    wazuh_manager_port: 1515
    wazuh_agent_group: "linux-servers"
  tasks:
    - name: Загрузка GPG-ключа Wazuh (Debian)
      ansible.builtin.get_url:
        url: https://packages.wazuh.com/key/GPG-KEY-WAZUH
        dest: /usr/share/keyrings/wazuh.asc
        mode: "0644"
      when: ansible_os_family == "Debian"

    - name: Add Wazuh repository (Debian)
      ansible.builtin.apt_repository:
        repo: "deb [signed-by=/usr/share/keyrings/wazuh.asc] https://packages.wazuh.com/5.x/apt/ stable main"
        state: present
      when: ansible_os_family == "Debian"

    - name: Import GPG key (RHEL)
      ansible.builtin.rpm_key:
        key: https://packages.wazuh.com/key/GPG-KEY-WAZUH
        state: present
      when: ansible_os_family == "RedHat"

    - name: Add Wazuh repository (RHEL)
      yum_repository:
        name: wazuh
        description: Wazuh repository
        baseurl: https://packages.wazuh.com/5.x/yum/
        gpgcheck: yes
        gpgkey: https://packages.wazuh.com/key/GPG-KEY-WAZUH
        enabled: yes
      when: ansible_os_family == "RedHat"

    - name: Install Wazuh agent
      package:
        name: wazuh-agent
        state: present

    - name: Configure agent
      template:
        src: templates/ossec.conf.j2
        dest: /var/ossec/etc/ossec.conf
        owner: root
        group: ossec
        mode: '0640'
      notify: restart wazuh-agent

    - name: Ensure agent is running
      systemd:
        name: wazuh-agent
        state: started
        enabled: yes

  handlers:
    - name: restart wazuh-agent
      systemd:
        name: wazuh-agent
        state: restarted
```

```jinja2
{# templates/ossec.conf.j2 #}
<ossec_config>
  <client>
    <server>
      <address>{{ wazuh_manager }}</address>
      <port>{{ wazuh_manager_port }}</port>
      <protocol>tcp</protocol>
      <enrollment>
        <enabled>yes</enabled>
        <auto_method>yes</auto_method>
      </enrollment>
    </server>
  </client>

  <client_buffer>
    <disabled>no</disabled>
    <queue_size>5000</queue_size>
  </client_buffer>
</ossec_config>
```

### 2. Ansible: массовая установка Windows агентов

```yaml
---
- name: Deploy Wazuh agents on Windows
  hosts: windows_agents
  become: yes
  vars:
    wazuh_manager: "10.0.0.20"
    wazuh_msi_url: "https://packages.wazuh.com/5.x/windows/wazuh-agent-5.0.0-1.msi"
  tasks:
    - name: Download Wazuh MSI
      win_get_url:
        url: "{{ wazuh_msi_url }}"
        dest: "C:\\Temp\\wazuh-agent.msi"

    - name: Install Wazuh agent
      win_package:
        path: "C:\\Temp\\wazuh-agent.msi"
        arguments:
          - "/q"
          - "WAZUH_MANAGER={{ wazuh_manager }}"
          - "WAZUH_AGENT_GROUP=windows-servers"
          - "WAZUH_AGENT_NAME={{ inventory_hostname }}"
        state: present

    - name: Ensure Wazuh service is running
      win_service:
        name: Wazuh
        state: started
        start_mode: auto

    - name: Configure agent
      win_template:
        src: templates/ossec-windows.conf.j2
        dest: "C:\\Program Files (x86)\\ossec-agent\\ossec.conf"
      notify: restart wazuh-agent

  handlers:
    - name: restart wazuh-agent
      win_service:
        name: Wazuh
        state: restarted
```

### 3. Cloud-init (Ubuntu/Debian)

```yaml
#cloud-config
package_update: true
package_upgrade: true

packages:
  - curl
  - gnupg
  - apt-transport-https

runcmd:
  # Установка Wazuh агента
  - wget -qO - https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --dearmor -o /usr/share/keyrings/wazuh.gpg
  - echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/5.x/apt/ stable main" | tee /etc/apt/sources.list.d/wazuh.list
  - apt update
  - WAZUH_MANAGER='10.0.0.20' WAZUH_AGENT_GROUP='cloud-vms' apt install wazuh-agent -y
  - systemctl enable --now wazuh-agent
```

### 4. Dynamic Inventory для Ansible

```ini
# wazuh_inventory.ini
[cloud_vms]
web-01 ansible_host=10.0.1.10
web-02 ansible_host=10.0.1.11
db-01 ansible_host=10.0.2.10

[windows_servers]
win-web-01 ansible_host=10.0.3.10 ansible_connection=winrm ansible_winrm_transport=ntlm
win-web-02 ansible_host=10.0.3.11 ansible_connection=winrm ansible_winrm_transport=ntlm

[cloud_vms:vars]
ansible_user=ubuntu
ansible_ssh_private_key_file=~/.ssh/id_rsa

[windows_servers:vars]
ansible_user=Administrator
ansible_password=StrongPassword123
```

### 5. SaltStack: стейт для Wazuh

```yaml
# wazuh_agent.sls
wazuh_repo:
  pkgrepo.managed:
    - name: wazuh
    - baseurl: https://packages.wazuh.com/5.x/yum/
    - gpgcheck: 1
    - gpgkey: https://packages.wazuh.com/key/GPG-KEY-WAZUH
    - enabled: 1

wazuh_agent:
  pkg.installed:
    - name: wazuh-agent
    - require:
      - pkgrepo: wazuh_repo

/etc/ossec.conf:
  file.managed:
    - source: salt://wazuh/ossec.conf
    - user: root
    - group: ossec
    - mode: 640
    - require:
      - pkg: wazuh_agent

wazuh-agent-service:
  service.running:
    - name: wazuh-agent
    - enable: True
    - watch:
      - file: /etc/ossec.conf
```

### 6. Проверка массовой установки

```bash
#!/bin/bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Статус агентов
echo "=== Agent Status ==="
curl -sk "$API/agents/summary" -H "Authorization: Bearer $TOKEN" | jq '.data'

# Агенты в статусе "Pending" (не зарегистрированы)
echo "=== Pending Agents ==="
curl -sk "$API/agents?status=pending&select=id,name,ip" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.affected_items'

# Агенты без группы
echo "=== Agents without group ==="
curl -sk "$API/agents?group=default&select=id,name,ip" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.total_affected_items'
```

### 7. Post-install: автоматическая настройка агентов

```yaml
---
- name: Post-install Wazuh agent configuration
  hosts: wazuh_agents
  become: yes
  tasks:
    - name: Set agent group based on role
      uri:
        url: "https://{{ wazuh_manager }}:55000/agents/{{ agent_id }}/group/{{ agent_group }}"
        method: PUT
        headers:
          Authorization: "Bearer {{ wazuh_token }}"
        validate_certs: no
      when: agent_group is defined

    - name: Verify agent connectivity
      wait_for:
        host: "{{ wazuh_manager }}"
        port: 1514
        timeout: 30
```

## Дополнительная информация

### Best Practices

1. **Enrollment Key**: создайте отдельный ключ для каждой среды (dev/staging/prod).
2. **Имена агентов**: используйте hostname +环境 (e.g., `web-01-prod`).
3. **Группы**: назначайте группы до установки через `WAZUH_AGENT_GROUP`.
4. **Canary**: сначала устанавливайте на 5–10 хостов, потом mass rollout.
5. **Rollback**: имейте скрипт отката (apt remove/purge wazuh-agent).
6. **Verification**: после установки проверяйте статус через API.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Agent "Pending"** | Порт 1515 закрыт | Откройте firewall: `ufw allow 1515/tcp` |
| **Agent "Disconnected"** | Нет сети до Manager | Проверьте `ping`, `nc -zv manager 1514` |
| **Enrollment failed** | Неверный enrollment key | Проверьте `enrollment` в `ossec.conf` |
| **Install fails (Windows)** | Нет прав Administrator | Запустите от Administrator |
| **Duplicate agent** | Агент с таким именем уже есть | Удалите старого агента: `DELETE /agents/001` |

### См. также
- [Развертывание Wazuh](./deployment.md) — установка менеджера.
- [Agent Groups](./wazuh-agent-groups.md) — управление группами.
- [Ansible](./ansible-automation-per-agent.md) — автоматизация.
