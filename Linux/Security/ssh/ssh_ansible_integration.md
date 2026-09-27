# SSH и Ansible: интеграция и настройка

## Определения

**Connection Plugin** — плагин, реализующий способ связи Ansible с управляемыми узлами. Для SSH используется `ansible.builtin.ssh` (или `community.ssh` для расширенного функционала).

**Pipelining** — метод оптимизации, при котором Python-скрипты модулей передаются через STDIN существующего SSH-соединения, исключая необходимость копирования временных файлов на Managed Node.

**SSH Multiplexing (ControlPersist)** — механизм OpenSSH для переиспользования одного TCP-соединения для нескольких последовательных SSH-сессий. Снижает накладные расходы на handshake и аутентификацию.

**Remote User** — пользователь, от имени которого Ansible подключается к Managed Node через SSH. Определяется переменной `ansible_user` или параметром `remote_user` в `ansible.cfg`.

**Privilege Escalation (Become)** — повышение привилегий после SSH-подключения (обычно `sudo`). Отдельный от SSH-аутентификации этап.

**Control Path** — путь к UNIX-сокету для мультиплексирования SSH-соединений. Длина пути ограничена ~104 символами в macOS/Linux.

## Базовые концепции

### Приоритеты SSH-конфигурации в Ansible

Ansible использует SSH-конфигурацию в следующем порядке приоритетов:

1. Параметры в `ansible.cfg` (секция `[ssh_connection]`)
2. Переменные Inventory (`ansible_ssh_common_args`, `ansible_ssh_extra_args`)
3. Параметры в `~/.ssh/config` (User-level)
4. Системные настройки `/etc/ssh/ssh_config`

### Типичные проблемы SSH в Ansible

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `ControlPersist` не работает | Длинный путь к сокету | Используйте `control_path = %(directory)s/ansible-ssh-%%h-%%p-%%r` |
| Медленное выполнение | Pipelining отключен | Включите `pipelining = True` в `[ssh_connection]` |
| `Permission denied` | Неверный `remote_user` | Проверьте `ansible_user` и ключи в Inventory |
| `Host key verification` | Включена проверка ключей | Добавьте `ansible_ssh_common_args="-o StrictHostKeyChecking=no"` (временно) |
| `Connection reset` | Нестабильная сеть | Увеличьте `retries = 5` и `timeout = 30` |

## Практические сценарии

### Сценарий 1: Оптимальный SSH-конфиг для Ansible

```ini
# ansible.cfg
[defaults]
inventory = ./inventory.ini
remote_user = deploy
host_key_checking = False
forks = 50
timeout = 30

[ssh_connection]
# Pipelining: ускорение на 30-50%
pipelining = True

# Мультиплексирование: переиспользование соединений
ssh_args = -o ControlMaster=auto -o ControlPersist=600s -o ServerAliveInterval=30
control_path = %(directory)s/ansible-ssh-%%h-%%p-%%r

# Повторные попытки
retries = 3

# Таймаут для каждого retry
transfer_timeout = 30
```

### Сценарий 2: SSH через bastion/jump-host

```ini
# ansible.cfg
[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=600s -o ProxyJump=bastion.example.com
```

Или через Inventory:

```yaml
# inventory/production.yml
all:
  children:
    webservers:
      hosts:
        web-01:
          ansible_host: 10.0.1.10
        web-02:
          ansible_host: 10.0.1.11
    bastion:
      hosts:
        bastion:
          ansible_host: 203.0.113.50
          ansible_user: admin

  vars:
    ansible_user: deploy
    ansible_ssh_common_args: '-o ProxyJump=admin@bastion.example.com'
```

### Сценарий 3: SSH-ключи через Vault

```yaml
# group_vars/all/vault.yml (зашифровано через ansible-vault)
ansible_ssh_private_key_file: /home/deploy/.ssh/id_ed25519
vault_deploy_password: !vault |
  $ANSIBLE_VAULT;1.2;AES256;deploy
  346130383238316532383462666137376362656361366138623036666462643332623438313137
```

```yaml
# playbook.yml
- name: Deploy application
  hosts: webservers
  become: true
  vars:
    ansible_become_password: "{{ vault_deploy_password }}"
  tasks:
    - name: Ensure service is running
      ansible.builtin.service:
        name: nginx
        state: started
```

### Сценарий 4: Диагностика SSH-подключений Ansible

```bash
# 1. Проверка подключения к хосту
ansible all -m ping -vvv

# 2. Тест SSH с теми же параметрами
ssh -vvv -o ControlMaster=no deploy@10.0.1.10

# 3. Проверка Inventory
ansible-inventory --list
ansible-inventory --graph

# 4. Запуск с увеличенной детализацией
ansible-playbook site.yml -vvvv --start-at-task="Deploy"

# 5. Проверка фактов хоста
ansible web-01 -m setup
```

### Сценарий 5: Безопасная SSH-конфигурация

```ini
# ansible.cfg — hardened production config
[defaults]
remote_user = ansible
host_key_checking = True
private_key_file = ~/.ssh/ansible_ed25519

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s -o ServerAliveInterval=15 -o ServerAliveCountMax=3
control_path = %(directory)s/ansible-ssh-%%h-%%p-%%r

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_flags = '-H -S'
```

## Дополнительная информация

### Полезные команды для диагностики

```bash
# Проверка SSH без Ansible
ssh -F /dev/null deploy@10.0.1.10 "echo ok"

# Проверка ControlPersist
ls -la /tmp/ansible-ssh-*

# Мониторинг SSH-соединений
ss -tnp | grep ssh

# Проверка latency
time ssh deploy@10.0.1.10 "true"
```

### См. также

- [Управление SSH-ключами через Ansible](../../Ansible/ansible_ssh_key_management.md) — authorized_keys, ротация
- [Ansible: установка и настройка](../../Ansible/ansible_setup_and_config.md) — полная конфигурация
- [Ansible: оптимизация производительности](../../Ansible/ansible_performance_tuning.md) — тюнинг SSH
- [Ansible: рекомендации по безопасности](../../Ansible/ansible_security_best_practices.md) — SSH security
- [SSH Hardening Best Practices](./server/ssh_hardening_best_practices.md) — серверная настройка
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
