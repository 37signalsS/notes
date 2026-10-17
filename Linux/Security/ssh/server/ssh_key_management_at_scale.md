# Управление SSH-ключами в масштабных инфраструктурах

## Определения

**SSH Key Lifecycle Management** — управление полным жизненным циклом SSH-ключей: генерация, распространение, ротация, отзыв и уничтожение в масштабе hundreds/thousands серверов.

**SSH CA (Certificate Authority)** — централизованная инфраструктура, где центральный ключ подписывает пользовательские и хостовые сертификаты, исключая необходимость ручного управления `authorized_keys` на каждом сервере. Подробнее: [SSH-аутентификация по сертификатам](./ssh_certificate_authentication.md).

**Vault SSH Secrets Engine** — компонент HashiCorp Vault для динамической генерации SSH-ключей и сертификатов. Устраняет необходимость хранения статических `.pem` файлов на серверах.

**Key Inventory** — реестр всех активных SSH-ключей с указанием владельца, даты создания, срока действия, серверов использования и статуса (активный/отозванный).

**Short-lived Certificates** — сертификаты с минимальным TTL (от нескольких минут до часов), автоматически становящиеся невалидными. Минимизируют окно компрометации.

**KRL (Key Revocation List)** — список отозванных ключей и сертификатов. OpenSSH проверяет KRL перед выдачей доступа.

## Базовые концепции

### Модели управления ключами

| Модель | Масштаб | Безопасность | Сложность | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **Статические ключи (authorized_keys)** | Низкая (<50 серверов) | Средняя | Высокая при росте | Малые среды |
| **SSH CA** | Высокая (1000+) | Высокая | Средняя | Enterprise |
| **Vault SSH** | Высокая | Очень высокая | Средняя | Zero Trust |
| **LDAP/SSSD + AuthorizedKeysCommand** | Средняя | Средняя | Низкая | Корпоративные среды |

### Архитектура управления ключами

```
┌─────────────────────────────────────────────────────────┐
│                    Централизованное хранилище           │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │   Vault     │  │  SSH CA Key  │  │  LDAP/AD      │  │
│  │   (секреты) │  │  (подпись)   │  │  (пользователи)│  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼────────────────┼──────────────────┼───────────┘
          │                │                  │
          v                v                  v
┌─────────────────────────────────────────────────────────┐
│              Инструменты автоматизации                   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │   Ansible   │  │  CI/CD       │  │  Teleport     │  │
│  │  (playbooks)│  │  (GitLab CI) │  │  (Zero Trust) │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────┐
│              Production Servers (1000+)                  │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │
│  │ web-01 │ │ web-02 │ │ db-01  │ │ db-02  │  ...     │
│  └────────┘ └────────┘ └────────┘ └────────┘          │
└─────────────────────────────────────────────────────────┘
```

### Стратегии ротации ключей

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Плановая ротация** | Регулярная замена по расписанию (30/90/180 дней) | Compliance, стандарты безопасности |
| **Ротация по событию** | Замена при увольнении, инциденте, компрометации | Аварийные ситуации |
| **Динамические ключи** | Автоматическая генерация с коротким TTL | Vault, CI/CD |
| **Атомарная ротация CA** | Замена корневого ключа без даунтайма | Enterprise |

## Практические сценарии

### Сценарий 1: Vault SSH CA — динамические сертификаты

**Задача**: Настроить Vault для выдачи кратковременных SSH-сертификатов вместо статических ключей.

```bash
# 1. Включение SSH secret engine
vault secrets enable -path=ssh-client-signer ssh

# 2. Генерация ключа CA в Vault
vault write ssh-client-signer/config/ca \
   public_key=@/etc/ssh/ca_user.pub

# 3. Создание роли для подписи
vault write ssh-client-signer/roles/ops-role \
   key_type="ca" \
   allowed_users="admin,deploy,sre" \
   default_extensions="permit-pty,permit-port-forwarding" \
   ttl="8h" \
   max_ttl="24h"

# 4. Подпись запроса клиента
vault write -f ssh-client-signer/sign/ops-role \
   public_key=@/home/user/.ssh/id_ed25519.pub

# 5. Сохранение сертификата
vault read -field=signed_key ssh-client-signer/sign/ops-role \
   public_key=@/home/user/.ssh/id_ed25519.pub > ~/.ssh/id_ed25519-cert.pub
```

**Настройка сервера для доверия Vault CA:**

```bash
# На каждом production-сервере:
sudo tee /etc/ssh/sshd_config.d/vault-ca.conf << 'EOF'
TrustedUserCAKeys /etc/ssh/vault_ca.pub
EOF

# Копирование публичного ключа Vault CA
sudo cp /etc/ssh/vault_ca.pub /etc/ssh/vault_ca.pub
sudo chmod 644 /etc/ssh/vault_ca.pub

# Проверка и перезапуск
sudo sshd -t && sudo systemctl reload sshd
```

### Сценарий 2: Централизованное управление через Ansible

**Задача**: Управление SSH-ключами на 500+ серверах через Ansible.

```yaml
---
- name: SSH Key Management at Scale
  hosts: all
  become: true
  vars:
    # Белый список доверенных ключей
    trusted_keys:
      - user: deploy
        key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI deploy@company.com"
        options: "no-port-forwarding,no-X11-forwarding,command=\"/opt/deploy/deploy.sh\""
        expire: "20261231"
      - user: sre
        key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI sre@company.com"
        options: "from=\"10.0.0.0/8\""
        expire: "20260630"

  tasks:
    # 1. Ротация ключей с атомарным обновлением
    - name: Deploy authorized keys from inventory
      ansible.posix.authorized_key:
        user: "{{ item.user }}"
        key: "{{ item.key }}"
        key_options: "{{ item.options | default(omit) }}"
        exclusive: false
        state: present
      loop: "{{ trusted_keys }}"

    # 2. Удаление ключей, которых нет в инвентаре
    - name: Remove unauthorized keys
      ansible.posix.authorized_key:
        user: "{{ item.user }}"
        key: "{{ item.key }}"
        state: absent
      loop: "{{ trusted_keys }}"
      when: item.state | default('present') == 'absent'

    # 3. Аудит: поиск всех authorized_keys на серверах
    - name: Find all authorized_keys files
      ansible.builtin.find:
        paths: /home
        patterns: "authorized_keys"
        recurse: yes
      register: auth_keys_files

    - name: Report authorized_keys content
      ansible.builtin.slurp:
        src: "{{ item.path }}"
      loop: "{{ auth_keys_files.files }}"
      register: auth_keys_content

    - name: Display all authorized keys
      ansible.builtin.debug:
        msg: "Host: {{ inventory_hostname }}, File: {{ item.item.path }}, Content: {{ item.content | b64decode }}"
      loop: "{{ auth_keys_content.results }}"
```

### Сценарий 3: Инвентаризация ключей

**Задача**: Собрать информацию обо всех SSH-ключах в инфраструктуре.

```bash
#!/bin/bash
# ssh_key_audit.sh — Аудит SSH-ключей на всех серверах
# Использование: ./ssh_key_audit.sh inventory.txt

INVENTORY=$1
REPORT="/tmp/ssh_key_audit_$(date +%Y%m%d).csv"

echo "Host,User,Key_Fingerprint,Key_Type,Key_Comment,Expires" > "$REPORT"

while IFS= read -r host; do
  echo "Auditing: $host"
  ssh -o ConnectTimeout=5 -o BatchMode=yes "$host" "
    for user_dir in /home/*/.ssh /root/.ssh; do
      if [ -f \"\$user_dir/authorized_keys\" ]; then
        user=\$(basename \$(dirname \"\$user_dir\"))
        while IFS= read -r line; do
          if echo \"\$line\" | grep -q '^ssh-\|^sk-'; then
            fingerprint=\$(echo \"\$line\" | ssh-keygen -l -f - 2>/dev/null | awk '{print \$2}')
            key_type=\$(echo \"\$line\" | awk '{print \$1}')
            comment=\$(echo \"\$line\" | awk '{print \$NF}')
            echo \"$host,\$user,\$fingerprint,\$key_type,\$comment,\"
          fi
        done < \"\$user_dir/authorized_keys\"
      fi
    done
  " 2>/dev/null >> "$REPORT"
done < "$INVENTORY"

echo "Report saved to: $REPORT"
echo "Total keys found: $(tail -n +2 "$REPORT" | wc -l)"
```

### Сценарий 4: Атомарная ротация CA без даунтайма

**Задача**: Заменить ключ CA на всех серверах без потери доступа.

```yaml
---
- name: Atomic SSH CA Rotation
  hosts: all
  become: true
  vars:
    new_ca_pub: "{{ lookup('file', '/tmp/ca_user_v2.pub') }}"
    old_ca_pub: "{{ lookup('file', '/tmp/ca_user_v1.pub') }}"

  tasks:
    # Фаза 1: Добавить доверие к новому CA (параллельно со старым)
    - name: Add new CA to TrustedUserCAKeys
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config.d/vault-ca.conf
        regexp: '^TrustedUserCAKeys'
        line: "TrustedUserCAKeys /etc/ssh/ca_user_v1.pub /etc/ssh/ca_user_v2.pub"
      notify: reload sshd

    # Фаза 2: Развернуть новый CA ключ
    - name: Deploy new CA public key
      ansible.builtin.copy:
        content: "{{ new_ca_pub }}"
        dest: /etc/ssh/ca_user_v2.pub
        owner: root
        group: root
        mode: '0644'

    # Фаза 3: Проверить работоспособность (после apply)
    # Фаза 4: Удалить старый CA (отдельный playbook)
    - name: Remove old CA (phase 2)
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config.d/vault-ca.conf
        regexp: '^TrustedUserCAKeys'
        line: "TrustedUserCAKeys /etc/ssh/ca_user_v2.pub"
      notify: reload sshd
      when: remove_old_ca | default(false)

  handlers:
    - name: reload sshd
      ansible.builtin.service:
        name: sshd
        state: reloaded
```

### Сценарий 5: LDAP/SSSD интеграция для динамических ключей

**Задача**: Получать SSH-ключи из LDAP при аутентификации.

```bash
# /etc/ssh/sshd_config
AuthorizedKeysCommand /usr/bin/sss_ssh_authorizedkeys
AuthorizedKeysCommandUser sssd

# Проверка работоспособности
sss_ssh_authorizedkeys alice
# → ssh-ed25519 AAAAC3... alice@company.com

# Настройка NSS для LDAP
# /etc/sssd/sssd.conf
[domain/corp.example.com]
ldap_user_ssh_public_key = sshPublicKey
```

## Дополнительная информация

### Инструменты управления ключами

| Инструмент | Назначение | Масштаб |
| :--- | :--- | :--- |
| **Vault SSH** | Динамические сертификаты, хранение ключей | 10000+ серверов |
| **Teleport** | Zero Trust SSH с=session recording | 1000+ серверов |
| **Ansible** | Распространение ключей, ротация | 500+ серверов |
| **FreeIPA/LDAP** | Централизованное хранение ключей | 100+ пользователей |

### Частые ошибки

| Ошибка | Последствие | Решение |
| :--- | :--- | :--- |
| Нет инвентаризации ключей | Старые ключи уволенных сотрудников остаются активными | Регулярный аудит `authorized_keys` |
| Ручная ротация на серверах | Пропущенные серверы, неравномерная ротация | Автоматизация через Ansible/CI |
| Нет KRL | Отозванные сертификаты продолжают работать | Настройка `RevokedKeys` в `sshd_config` |
| Длинный TTL сертификатов | Большое окно компрометации | Используйте TTL < 24 часа |

### См. также

- [SSH-аутентификация по сертификатам](./ssh_certificate_authentication.md) — инфраструктура SSH CA
- [SSH Hardening Best Practices](./ssh_hardening_best_practices.md) — общие рекомендации
- [Управление SSH-ключами через Ansible](../../../Ansible/ansible_ssh_key_management.md) — автоматизация
- [Vault SSH Secrets Engine](../../../Vault/concepts.md) — динамические ключи
