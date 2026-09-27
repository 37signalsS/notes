# Nomad — Ansible Provisioning

## Определения

**Ansible Provisioning для Nomad** — автоматизация установки, настройки и обновления Nomad-агентов (серверов и клиентов) через Ansible-плейбуки, обеспечивая воспроизводимую и идемпотентную настройку узлов.

**Golden Image** — предварительно настроенный образ ОС с установленным Nomad и зависимостями, создаваемый через Ansible + Packer.

**Rolling Update через Ansible** — последовательное обновление Nomad на узлах с автоматическим drain и проверкой здоровья.

## Основные концепции

### Структура Ansible-проекта

```
nomad-ansible/
├── inventory/
│   ├── production/
│   │   ├── servers.yml
│   │   └── clients.yml
│   └── staging/
├── roles/
│   ├── nomad_common/
│   ├── nomad_server/
│   ├── nomad_client/
│   └── nomad_acl/
├── playbooks/
│   ├── site.yml
│   ├── deploy_nomad.yml
│   ├── upgrade_nomad.yml
│   └── drain_client.yml
├── templates/
│   ├── server.hcl.j2
│   ├── client.hcl.j2
│   └── nomad.service.j2
├── group_vars/
│   ├── all.yml
│   ├── nomad_servers.yml
│   └── nomad_clients.yml
└── ansible.cfg
```

## Практические сценарии

### Сценарий 1: Inventory для Nomad

**inventory/production/servers.yml:**
```yaml
all:
  children:
    nomad_servers:
      hosts:
        nomad-server-1:
          ansible_host: 10.0.1.10
          nomad_role: server
          nomad_bootstrap: true  # Первая нода для bootstrap
        nomad-server-2:
          ansible_host: 10.0.1.11
          nomad_role: server
        nomad-server-3:
          ansible_host: 10.0.1.12
          nomad_role: server
    nomad_clients:
      hosts:
        nomad-client-{1..10}:
          ansible_host: "10.0.2.{{ idx }}"
          nomad_role: client
```

### Сценарий 2: Role для установки Nomad

**roles/nomad_common/tasks/main.yml:**
```yaml
- name: Create nomad user
  user:
    name: nomad
    system: yes
    shell: /bin/false
    home: /etc/nomad.d
    create_home: no

- name: Install dependencies
  apt:
    name:
      - unzip
      - jq
      - curl
      - software-properties-common
    state: present
    update_cache: yes

- name: Download Nomad
  unarchive:
    src: "https://releases.hashicorp.com/nomad/{{ nomad_version }}/nomad_{{ nomad_version }}_linux_amd64.zip"
    dest: /usr/local/bin/
    remote_src: yes
    mode: '0755'
  notify: restart nomad

- name: Create directories
  file:
    path: "{{ item }}"
    state: directory
    owner: nomad
    group: nomad
    mode: '0750'
  loop:
    - /etc/nomad.d
    - /etc/nomad.d/tls
    - /opt/nomad/data
    - /var/log/nomad

- name: Deploy systemd service
  template:
    src: nomad.service.j2
    dest: /etc/systemd/system/nomad.service
  notify:
    - daemon reload
    - restart nomad
```

### Сценарий 3: Шаблон конфигурации сервера

**templates/server.hcl.j2:**
```hcl
datacenter = "{{ nomad_datacenter }}"
data_dir   = "/opt/nomad/data"
log_level  = "{{ nomad_log_level | default('INFO') }}"

server {
  enabled          = true
  bootstrap_expect = {{ nomad_bootstrap_expect | default(3) }}
  heartbeat_grace  = "{{ nomad_heartbeat_grace | default('30s') }}"
}

tls {
  http = true
  rpc  = true
  ca_file   = "/etc/nomad.d/tls/nomad-ca.pem"
  cert_file = "/etc/nomad.d/tls/server.pem"
  key_file  = "/etc/nomad.d/tls/server-key.pem"
  verify_server_hostname = true
  verify_https_client    = true
}

acl {
  enabled = {{ nomad_acl_enabled | default(true) | lower }}
}

consul {
  address = "{{ consul_address | default('127.0.0.1:8500') }}"
}

telemetry {
  publish_allocation_metrics = true
  publish_node_metrics       = true
  prometheus_metrics         = true
}
```

### Сценарий 4: Playbook для обновления Nomad

**playbooks/upgrade_nomad.yml:**
```yaml
---
- name: Upgrade Nomad on servers
  hosts: nomad_servers
  serial: 1  # По одному узлу
  become: yes
  vars:
    nomad_version: "2.0.4"

  pre_tasks:
    - name: Create Raft snapshot
      command: nomad operator raft snapshot save /backup/nomad-pre-upgrade-{{ ansible_date_time.date }}.snap
      delegate_to: "{{ inventory_hostname }}"
      run_once: true

  roles:
    - role: nomad_common

  post_tasks:
    - name: Wait for Nomad to start
      pause:
        seconds: 30

    - name: Check Nomad status
      command: nomad server members
      register: result
      until: "'alive' in result.stdout"
      retries: 10
      delay: 5

    - name: Verify cluster health
      command: nomad status
      register: nomad_status
      changed_when: false

    - name: Display cluster status
      debug:
        var: nomad_status.stdout_lines
```

### Сценарий 5: Drain клиента через Ansible

**playbooks/drain_client.yml:**
```yaml
---
- name: Drain and upgrade Nomad client
  hosts: "{{ target_host }}"
  become: yes
  serial: 1
  vars:
    nomad_drain_deadline: "15m"
    nomad_version: "2.0.4"

  tasks:
    - name: Enable drain
      command: nomad node drain -enable -self -deadline="{{ nomad_drain_deadline }}"
      ignore_errors: yes

    - name: Wait for drain to complete
      shell: |
        nomad node status -self | grep -c "0"
      register: alloc_count
      until: alloc_count.stdout | int == 0
      retries: 30
      delay: 10

    - name: Stop Nomad
      systemd:
        name: nomad
        state: stopped

    - name: Update Nomad binary
      unarchive:
        src: "https://releases.hashicorp.com/nomad/{{ nomad_version }}/nomad_{{ nomad_version }}_linux_amd64.zip"
        dest: /usr/local/bin/
        remote_src: yes
        mode: '0755'

    - name: Start Nomad
      systemd:
        name: nomad
        state: started
        daemon_reload: yes

    - name: Wait for Nomad to start
      pause:
        seconds: 30

    - name: Disable drain
      command: nomad node drain -disable -self

    - name: Enable eligibility
      command: nomad node eligibility -enable -self
```

### Сценарий 6: Автоматическое развёртывание кластера

**playbooks/site.yml:**
```yaml
---
- name: Deploy Nomad cluster
  hosts: all
  become: yes

  roles:
    - role: common
    - role: consul
    - role: nomad_common

- name: Configure Nomad servers
  hosts: nomad_servers
  become: yes
  roles:
    - role: nomad_server

- name: Configure Nomad clients
  hosts: nomad_clients
  become: yes
  roles:
    - role: nomad_client

- name: Initialize ACL
  hosts: nomad_servers[0]
  become: yes
  roles:
    - role: nomad_acl
  when: nomad_acl_bootstrap | default(false)
```

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unreachable` | SSH недоступен | Проверьте inventory и SSH-ключи |
| `Failed to start nomad` | Ошибка в конфигурации | Проверьте `journalctl -u nomad` |
| `Bootstrap already done` | Повторная инициализация ACL | Используйте `when: not acl_initialized` |
| `Drain stuck` | System jobs блокируют | Добавьте `-ignore-system-jobs` |

## Дополнительная информация

- [Ansible: Core Concepts](../Ansible/ansible_core_concepts.md) — основы Ansible.
- [Ansible: Roles](../Ansible/ansible_roles.md) — структура ролей.
- [Nomad — Linux OS Tuning](./nomad_linux_os_tuning.md) — настройка узлов.
- [Nomad — Cluster Upgrade](./nomad_cluster_upgrade.md) — обновление кластера.
