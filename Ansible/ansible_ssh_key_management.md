# Управление SSH-ключами через Ansible

## Определения

- **authorized_key** — модуль `ansible.posix.authorized_key` для управления списком публичных ключей в `~/.ssh/authorized_keys`
- **SSH key pair** — пара ключей (private + public) для аутентификации по протоколу SSH
- **ssh-agent** — демон, кэширующий приватные ключи в памяти для последующих подключений
- **Key rotation** — процесс регулярной замены SSH-ключей для снижения риска компрометации
- **known_hosts** — файл, содержащий публичные ключи удалённых хостов для защиты от MITM-атак
- **Passphrase** — парольная фраза, шифрующая приватный ключ на диске
- **Key type** — алгоритм ключа: RSA, Ed25519, ECDSA
- **StrictHostKeyChecking** — параметр OpenSSH, требующий подтверждения неизвестных ключей хостов
- **ssh-keyscan** — утилита для сбора публичных ключей хостов без аутентификации
- **authorized_keys** — файл, содержащий публичные ключи, которым разрешён вход на сервер
- **Vault ID** — идентификатор хранилища Ansible Vault для разделения секретов по окружениям

## Предварительные требования

- **ansible-core**: 2.21+ (GA: май 2026). Содержит `ansible.builtin.known_hosts`, `ansible.builtin.copy`, `ansible.builtin.template`, `ansible.builtin.lineinfile`, `ansible.builtin.file`, `ansible.builtin.command`, `ansible.builtin.service`.
- **ansible.posix**: 2.2+. Требует ansible-core 2.16+. Содержит `ansible.posix.authorized_key`. Установка: `ansible-galaxy collection install ansible.posix`.
- **Python**: 3.12+ на control node и managed nodes.
- **OpenSSH**: 8.0+ на managed nodes для поддержки Ed25519 и современных алгоритмов.
- **Права доступа**: приватные ключи и файлы паролей Vault должны иметь права `chmod 600`. Директория `.ssh` — `chmod 700`. Файл `authorized_keys` — `chmod 600`.
- **Сеть**: доступность порта 22/TCP между control node и managed nodes.

Проверка версий:

```bash
ansible --version
# → ansible [core 2.21.4]
python3 --version
# → Python 3.12.4
ansible-galaxy collection list ansible.posix
# → ansible.posix 2.2.x
```

## Основные концепции

### Жизненный цикл SSH-ключа

SSH-ключи проходят через этапы генерации, распространения, использования и ротации. На каждом этапе Ansible обеспечивает идемпотентное управление.

**Генерация ключей:** Ansible не имеет нативного модуля для генерации ключей. Используйте `ssh-keygen` через `ansible.builtin.command` с параметром `creates` для идемпотентности:

```bash
ssh-keygen -t ed25519 -C "ansible@$(hostname)" -f ~/.ssh/ansible_ed25519
# → Generating public/private ed25519 key pair.
# → Your identification has been saved in /home/user/.ssh/ansible_ed25519
```

**Распространение ключей:** Публичный ключ деплоится через `ansible.posix.authorized_key` или `ansible.builtin.copy`. Приватный ключ, если требуется на managed node, передаётся через Ansible Vault. См. [Multi-Vault хранилища](./Vault/multi_vault.md) для стратегий хранения секретов.

**Аутентификация:** При подключении Ansible к managed node использует ключ, указанный в `ansible_ssh_private_key_file` (inventory) или `~/.ssh/config`. Демон `ssh-agent` может кэшировать ключи для сессии.

**Ротация:** Периодическая замена ключей снижает риск компрометации. Ansible поддерживает ротацию через `exclusive: yes` в `ansible.posix.authorized_key`, что удаляет все старые ключи, оставляя только актуальные.

### Типы ключей и алгоритмы

| Тип | Длина | Скорость | Рекомендация |
|-----|-------|----------|--------------|
| Ed25519 | 256 бит | Высокая | Рекомендуется для новых проектов |
| ECDSA | 256/384/521 бит | Высокая | Совместимость со старыми системами |
| RSA | 2048/4096 бит | Средняя | Legacy-системы; минимум 4096 бит |

Ed25519 — современный стандарт: компактный, быстрый, resistant к side-channel атакам. RSA 4096 бит используется только для совместимости с устаревшими системами, не поддерживающими Ed25519.

### Формат и права файлов

Файл `~/.ssh/authorized_keys` содержит одну строку на ключ в формате `<type> <base64> <comment>`. Параметрыoptions указываются через `options=<value>` перед ключом:

```
command="/usr/bin/deploy.sh",no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI deploy@ci
```

Права доступа критичны для безопасности SSH:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
```

### Опции ключа (key_options)

Параметр `key_options` модуля `ansible.posix.authorized_key` позволяет задать ограничения для конкретного ключа без изменения глобального `sshd_config`:

| Опция | Назначение |
|-------|------------|
| `command="..."` | Ограничивает команду, которую можно выполнить после входа |
| `from="IP/CIDR"` | Разрешает подключение только с указанных адресов |
| `no-port-forwarding` | Отключает перенаправление портов |
| `no-X11-forwarding` | Отключает X11 forwarding |
| `no-agent-forwarding` | Отключает forwarding ssh-agent |
| `no-pty` | Запрещает выделение TTY |
| `no-user-rc` | Не выполняет ~/.ssh/rc |

### Управление known_hosts и защита от MITM

Файл `known_hosts` защищает от атак man-in-the-middle. Ansible управляет им через модуль `ansible.builtin.known_hosts`:

- `hash_host: yes` — хеширует имя хоста, усложняя разведку для атакующего
- `state: present` / `absent` — добавление или удаление записи
- Ключ заполняется через `lookup('pipe', 'ssh-keyscan ' + hostname)` или `ssh-keyscan` в `command`

Параметр `StrictHostKeyChecking` в `ssh_config` или `ansible.cfg` управляет поведением при неизвестном хосте:
- `accept-new` — автоматически добавляет новый хост (требует доверенной сети)
- `yes` — требует явного подтверждения
- `no` — отключает проверку (не рекомендуется)

### Взаимодействие с ssh-agent

`ssh-agent` кэширует расшифрованные приватные ключи в памяти. Ansible может использовать ssh-agent, если ключ добавлен через `ssh-add`. Однако для автоматизации предпочтительно использовать файлы ключей напрямую через `ansible_ssh_private_key_file`, чтобы исключить зависимость от внешнего демона.

`forward_agent: yes` в SSH-конфиге передаёт агент на managed node, что полезно для цепочки подключений (jump host → final destination), но расширяет поверхность атаки.

### Генерация ключей и модуль user

Модуль `ansible.builtin.user` поддерживает автоматическую генерацию SSH-ключей при создании пользователя:

```yaml
- name: Create user with SSH key
  ansible.builtin.user:
    name: deploy
    ssh_key_generate: yes
    ssh_key_type: ed25519
    ssh_key_bits: 256
    ssh_key_file: /home/deploy/.ssh/id_ed25519
    ssh_key_comment: "deploy@control-node"
```

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

Для разделения секретов по окружениям используйте [Multi-Vault хранилища](./Vault/multi_vault.md).

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

## Операции и команды

### Модуль ansible.posix.authorized_key

Полный справочник параметров — в [Модули управления пользователями и безопасностью](./Modules/ansible_security_and_user_management_modules.md).

### Модуль ansible.builtin.known_hosts

Полный справочник параметров — в [Модули управления пользователями и безопасностью](./Modules/ansible_security_and_user_management_modules.md).

### Основные команды OpenSSH

| Команда | Описание |
|---------|----------|
| `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519` | Генерация ключа Ed25519 |
| `ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa` | Генерация RSA-ключа 4096 бит |
| `ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host` | Копирование публичного ключа на хост |
| `ssh-keyscan host >> ~/.ssh/known_hosts` | Добавление ключа хоста в known_hosts |
| `eval "$(ssh-agent -s)"` | Запуск ssh-agent |
| `ssh-add ~/.ssh/id_ed25519` | Добавление ключа в ssh-agent |
| `ssh -i ~/.ssh/id_ed25519 user@host` | Подключение с указанием ключа |

## Диагностика

### Типичные ошибки

| Ошибка | Причина | Решение |
|---------|---------|---------|
| `Permission denied (publickey)` | Неверный ключ, права на файл или SELinux-контекст | Проверьте `chmod 600 ~/.ssh/authorized_keys` и `restorecon -Rv /home/user/.ssh` |
| `Host key verification failed` | Хост не в known_hosts или сменил ключ | Добавьте ключ через `ansible.builtin.known_hosts` или `ssh-keyscan` |
| `Invalid key format` | Повреждённый ключ или неверный тип | Проверьте `ssh-keygen -l -f ~/.ssh/id_ed25519` |
| `ssh-agent forwarding failed` | Отключен forwarding или нет прав | Проверьте `ForwardAgent yes` и права на UNIX-сокет агента |
| `authorized_keys: bad line` | Неверный формат строки в authorized_keys | Удалите пустые строки и комментарии в начале файла |

### Диагностические команды

```bash
# Проверка формата ключа
ssh-keygen -l -f ~/.ssh/id_ed25519
# → 256 SHA256:... no comment (ED25519)

# Проверка подключения с отладкой
ssh -vvv -i ~/.ssh/id_ed25519 deploy@10.0.0.10 "echo ok"

# Проверка прав на .ssh
ls -la /home/deploy/.ssh
# → drwx------ 1 deploy deploy 4096 Sep 24 12:00 .
# → -rw------- 1 deploy deploy  100 Sep 24 12:00 authorized_keys

# Проверка SELinux-контекста
ls -laZ /home/deploy/.ssh
# → unconfined_u:object_r:ssh_home_t:s0 authorized_keys

# Проверка работы ssh-agent
ssh-add -l
# → 256 SHA256:... /home/user/.ssh/id_ed25519 (ED25519)
```

## Лучшие практики

- **Алгоритм ключей:** Используйте Ed25519 для новых проектов. RSA — только для совместимости с устаревшими системами, минимум 4096 бит.
- **Парольная фраза:** Всегда используйте passphrase для приватных ключей. В автоматизации используйте `ssh-agent` или Ansible Vault для хранения расшифрованных ключей в памяти.
- `exclusive: yes` в `ansible.posix.authorized_key` гарантирует, что в `authorized_keys` присутствуют только указанные ключи. Это предотвращает накопление неиспользуемых ключей.
- **Права доступа:** Строго соблюдайте права `chmod 700 ~/.ssh`, `chmod 600 ~/.ssh/authorized_keys`, `chmod 600 ~/.ssh/id_ed25519`. Проверяйте права через `ansible.builtin.file` в плейбуках.
- **SELinux:** На RHEL/CentOS/FedRock проверяйте контексты безопасности. Восстанавливайте контексты через `restorecon -Rv /home/user/.ssh`.
- **Ротация ключей:** Ротируйте ключи минимум раз в квартал. Используйте `exclusive: yes` для атомарной замены. Старые ключи удаляйте только после проверки, что все сервисы перешли на новые.
- **known_hosts:** Используйте `hash_host: yes` для production-хостов. Никогда не отключайте `StrictHostKeyChecking` на уровне глобального `ansible.cfg` без понимания рисков.
- **Vault:** Для хранения приватных ключей используйте [Multi-Vault хранилища](./Vault/multi_vault.md) с отдельным Vault ID для production и development. Никогда не храните приватные ключи в Git.
- **Именование ключей:** Используйте описательные имена: `id_ed25519_deploy`, `id_ed25519_monitoring`, `id_ed25519_backup`. Это упрощает аудит и ротацию.
- **Отдельные ключи для сервисов:** Каждому сервисному аккаунту — отдельный ключ. Это позволяет отозвать доступ к одному сервису без влияния на другие.
- **ssh-agent в automation:** Избегайте зависимости от `ssh-agent` в CI/CD. Используйте `ansible_ssh_private_key_file` с файлом ключа, защищённым Vault.

## Дополнительная информация

- [Модули безопасности и управления пользователями](./Modules/ansible_security_and_user_management_modules.md) — полный справочник параметров `authorized_key`, `known_hosts`, `user`, `group`.
- [Multi-Vault хранилища](./Vault/multi_vault.md) — стратегии хранения приватных ключей и секретов с разделением по окружениям.
- [Миграция на выделенного пользователя Ansible](./examples/user_migration_debugging.md) — практический сценарий управления SSH-ключами при смене пользователя.
