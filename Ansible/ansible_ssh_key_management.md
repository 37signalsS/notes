# Управление SSH-ключами через Ansible

## Определения

- **authorized_key** — модуль для управления списком публичных ключей в `~/.ssh/authorized_keys`
- **SSH key pair** — пара ключей (private + public) для аутентификации
- **ssh-agent** — демон, кэширующий приватные ключи для последующих подключений
- **Key rotation** — процесс регулярной замены SSH-ключей
- **known_hosts** — файл, содержащий публичные ключи удалённых хостов
- **Passphrase** — пароль, шифрующий приватный ключ
- **Key type** — алгоритм ключа: RSA, Ed25519, ECDSA
- **StrictHostKeyChecking** — параметр OpenSSH, требующий проверки ключей хостов

## Основные концепции

1. Модуль `authorized_key`: `key`, `key_options`, `manage_dir`, `exclusive`
2. Опции ключа: `command`, `from`, `no-port-forwarding`, `no-X11-forwarding`
3. Управление known_hosts: модуль `known_hosts`, `keyscan`
4. Генерация ключей: `ssh-keygen` через command/shell (Ansible не имеет модуля для генерации)
5. Распространение ключей: через `authorized_key` или файлы
6. SSH config:管控 через `template`

## Практические сценарии

### Добавление SSH-ключей для пользователей

```yaml
---
- name: Manage SSH keys for users
  hosts: all
  become: true
  vars:
    deploy_public_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI deploy@company.com"
    monitor_public_key: "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABg deploy@company.com"

  tasks:
    - name: Add deploy user
      ansible.builtin.user:
        name: deploy
        shell: /bin/bash
        create_home: true

    - name: Set authorized keys for deploy
      ansible.posix.authorized_key:
        user: deploy
        state: present
        key: "{{ deploy_public_key }}"
        key_options: "no-port-forwarding,no-X11-forwarding,command=\"/usr/bin/sudo /opt/app/deploy.sh\""
        exclusive: false
        manage_dir: true

    - name: Set authorized keys for monitor
      ansible.posix.authorized_key:
        user: monitor
        state: present
        key: "{{ monitor_public_key }}"
        key_options: "from=\"10.0.0.0/24\",command=\"/usr/bin/zabbix_agentd\""
        exclusive: false
```

### Настройка SSH для деплой-пользователя (command restriction)

```yaml
---
- name: Setup deploy user with restricted SSH
  hosts: webservers
  become: true
  vars:
    deploy_public_keys:
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI deploy@ci.example.com"
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI deploy@backup.example.com"

  tasks:
    - name: Create deploy user
      ansible.builtin.user:
        name: deploy
        shell: /bin/bash
        groups: wheel
        append: true
        create_home: true
        password: "{{ vault_deploy_password }}"

    - name: Configure authorized_keys with restrictions
      ansible.posix.authorized_key:
        user: deploy
        key: "{{ item }}"
        key_options: >-
          command="/opt/deploy/scripts/restrict.sh",
          no-port-forwarding,
          no-X11-forwarding,
          no-agent-forwarding,
          no-user-rc
        state: present
        exclusive: true
      loop: "{{ deploy_public_keys }}"

    - name: Create restricted shell script
      ansible.builtin.copy:
        dest: /opt/deploy/scripts/restrict.sh
        owner: deploy
        group: deploy
        mode: "0755"
        content: |
          #!/bin/bash
          case "$SSH_ORIGINAL_COMMAND" in
            deploy)
              /opt/deploy/deploy.sh
              ;;
            status)
              /opt/deploy/status.sh
              ;;
            *)
              echo "Command not allowed: $SSH_ORIGINAL_COMMAND"
              exit 1
              ;;
          esac
```

### Key rotation: замена ключей на всех серверах

```yaml
---
- name: SSH key rotation
  hosts: all
  become: true
  vars:
    new_public_key: "{{ lookup('file', '~/.ssh/id_ed25519.pub') }}"
    old_public_key: "{{ lookup('file', '~/.ssh/old_key.pub') }}"

  tasks:
    - name: Deploy new key and remove old
      ansible.posix.authorized_key:
        user: "{{ item }}"
        state: present
        key: "{{ new_public_key }}"
        exclusive: true
      loop:
        - deploy
        - ops
        - root

    - name: Remove old key from all users
      ansible.posix.authorized_key:
        user: "{{ item }}"
        key: "{{ old_public_key }}"
        state: absent
      loop:
        - deploy
        - ops
        - root

    - name: Update SSH host keys
      ansible.builtin.command: ssh-keygen -A
      changed_when: true

    - name: Restart sshd
      ansible.builtin.service:
        name: sshd
        state: restarted
```

### Управление known_hosts для кластеров

```yaml
---
- name: Manage known_hosts for cluster nodes
  hosts: cluster_nodes
  become: true
  vars:
    cluster_hosts:
      - name: node-01.internal
        ip: 10.0.1.10
      - name: node-02.internal
        ip: 10.0.1.11
      - name: node-03.internal
        ip: 10.0.1.12

  tasks:
    - name: Get SSH host keys for all nodes
      ansible.builtin.command: "ssh-keyscan {{ item.name }}"
      loop: "{{ cluster_hosts }}"
      register: host_keys
      changed_when: false

    - name: Add all cluster nodes to known_hosts
      ansible.builtin.known_hosts:
        name: "{{ cluster_hosts[item.0].name }}"
        key: "{{ item.1 }}"
        state: present
        hash_host: true
      loop: "{{ host_keys.results | flatten }}"
      loop_control:
        index_var: idx

    - name: Add cluster IPs to known_hosts
      ansible.builtin.known_hosts:
        name: "{{ cluster_hosts[item.0].ip }}"
        key: "{{ host_keys.results[item.0].stdout }}"
        state: present
        hash_host: false
      loop: "{{ cluster_hosts | list }}"
```

### Настройка SSH-конфига через template

```yaml
---
- name: Configure SSH client
  hosts: all
  become: true
  vars:
    ssh_config_entries:
      - host: "jump.example.com"
        hostname: "jump.example.com"
        user: "jumper"
        port: 22
        identity_file: "~/.ssh/id_ed25519"
        forward_agent: true
        strict_host_key_checking: "accept-new"

      - host: "prod-*"
        proxy_jump: "jump.example.com"
        user: "deploy"
        port: 22
        identity_file: "~/.ssh/id_ed25519"
        forward_agent: false
        strict_host_key_checking: "yes"

      - host: "10.0.0.*"
        proxy_jump: "jump.example.com"
        user: "ops"
        port: 2222
        identity_file: "~/.ssh/id_ed25519"

  tasks:
    - name: Deploy SSH config
      ansible.builtin.template:
        src: ssh_config.j2
        dest: "/home/{{ item }}/ssh/config"
        owner: "{{ item }}"
        group: "{{ item }}"
        mode: "0600"
        backup: true
      loop:
        - deploy
        - ops

    - name: Set strict permissions for .ssh
      ansible.builtin.file:
        path: "~{{ item }}/.ssh"
        owner: "{{ item }}"
        group: "{{ item }}"
        mode: "0700"
        state: directory
      loop:
        - deploy
        - ops
```

```jinja2
# roles/ssh/templates/ssh_config.j2
# {{ ansible_managed }}

{% for host in ssh_config_entries %}
Host {{ host.host }}
  HostName {{ host.hostname }}
  User {{ host.user }}
  Port {{ host.port | default(22) }}
  IdentityFile {{ host.identity_file }}
  ForwardAgent {{ host.forward_agent | default('no') }}
  StrictHostKeyChecking {{ host.strict_host_key_checking | default('accept-new') }}

{% endfor %}
```

### Использование Vault для хранения приватных ключей

```yaml
---
- name: Deploy private keys via Vault
  hosts: all
  become: true
  vars:
    vault_private_key: "{{ vault_deploy_ssh_private_key }}"

  tasks:
    - name: Ensure .ssh directory exists
      ansible.builtin.file:
        path: /home/deploy/.ssh
        state: directory
        owner: deploy
        group: deploy
        mode: "0700"

    - name: Deploy private key
      ansible.builtin.copy:
        content: "{{ vault_private_key }}"
        dest: /home/deploy/.ssh/id_ed25519
        owner: deploy
        group: deploy
        mode: "0600"
        backup: true

    - name: Deploy public key
      ansible.builtin.copy:
        src: files/deploy_id_ed25519.pub
        dest: /home/deploy/.ssh/id_ed25519.pub
        owner: deploy
        group: deploy
        mode: "0644"
```

```yaml
# group_vars/all/vault.yml
vault_deploy_ssh_private_key: !vault |
  $ANSIBLE_VAULT;1.2;AES256;deploy-key
  346130383238316532383462666137376362656361366138623036666462643332623438313137
  38613836306230656539393066656431336564346532626531613530643263656461383239663632
```

### Установка строгой проверки ключей хостов

```yaml
---
- name: Configure SSH strict host key checking
  hosts: all
  become: true
  tasks:
    - name: Set StrictHostKeyChecking to accept-new
      ansible.builtin.lineinfile:
        path: /etc/ssh/ssh_config.d/99-hardening.conf
        line: "StrictHostKeyChecking accept-new"
        create: true
        mode: "0644"
        owner: root
        group: root

    - name: Disable password authentication
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: "^#?PasswordAuthentication"
        line: "PasswordAuthentication no"
      notify: restart sshd

  handlers:
    - name: restart sshd
      ansible.builtin.service:
        name: sshd
        state: restarted
```

## Дополнительная информация

- [ansible_security_and_user_management.md](ansible_security_and_user_management.md)
- [ansible_security_best_practices.md](ansible_security_best_practices.md)
- [ansible_roles.md](ansible_roles.md)
- [Vault/basics.md](Vault/basics.md)
