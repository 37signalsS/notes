# Samba: Group Policy (GPO) для AD DC

## Определения

**Group Policy Object (GPO)** — объект групповой политики Active Directory, содержащий набор правил (политик), применяемых к пользователям и компьютерам. Определяет параметры безопасности, настройки приложений и рабочую среду.

**Group Policy Management Console (GPMC)** — консоль для управления GPO в Windows. Samba AD DC поддерживает GPO через `samba-tool` и совместимые инструменты.

**CSE (Client Side Extension)** — клиентские расширения, реализующие обработку GPO на стороне клиента. Samba AD Member выполняет ограниченную обработку GPO; полная поддержка — только в Windows-клиентах.

**LSDOU** — порядок применения GPO: Local → Site → Domain → Organizational Unit (OU). Каждый следующий уровень перезаписывает предыдущий (если не включен блок).

**WMI Filter** — фильтр на основе Windows Management Instrumentation, позволяющий применять GPO только к определенным компьютерам (например, только Windows 11 или только серверы с определенным ПО).

**Security Filtering** — механизм ограничения применения GPO определенной группой пользователей/компьютеров (по умолчанию — Domain Users/Domain Computers).

**gpupdate** — утилита Windows для принудительного обновления GPO на клиенте. Аналог на Linux — перезапуск SSSD/winbind.

**Resultant Set of Policy (RSEventing)** — отображение итоговых политик, примененных к объекту. В Windows: `gpresult /r`. В Linux через Samba: `samba-tool gpo listapply`.

## Базовые концепции

### Поддержка GPO в Samba

| Компонент | Samba AD DC | Samba AD Member | Windows DC |
| :--- | :--- | :--- | :--- |
| Создание GPO | `samba-tool gpo` | -- | GPMC |
| Применение GPO | Ограниченно | Ограниченно | Полная |
| Управление через | samba-tool | -- | GPMC/rsat |
| Клиентская обработка | -- | Базовая (CSE) | Полная |

> **Важно:** Samba AD DC поддерживает хранение и применение GPO, но полная обработка CSE (расширений) требует Windows-клиентов. Linux-клиенты используют GPO через SSSD (`ad_gpo_access_control`).

### Архитектура GPO в Samba AD

```
┌─────────────────────────────────────────────────────┐
│                   Active Directory                  │
│  ┌───────────────────────────────────────────────┐  │
│  │  CN=Policies,CN=System,DC=example,DC=com      │  │
│  │                                               │  │
│  │  ┌──────────────┐  ┌───────────────────────┐  │  │
│  │  │  GPO {GUID1} │  │  GPO {GUID2}          │  │  │
│  │  │  - Machine   │  │  - User Settings      │  │  │
│  │  │  - User      │  │  - Security Policy    │  │  │
│  │  └──────────────┘  └───────────────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            │                         │
     ┌──────▼──────┐          ┌──────▼──────┐
     │  Windows    │          │   Linux     │
     │  Клиент     │          │   Клиент    │
     │  (gpupdate) │          │  (SSSD)     │
     └─────────────┘          └─────────────┘
```

### Типы GPO для Samba

| Тип | Описание | Применение |
| :--- | :--- | :--- |
| **Domain Policy** | Глобальные политики домена | Пароли, блокировка учетных записей |
| **OU Policy** | Политики для Organizational Units | Настройки по подразделениям |
| **Security Policy** | Политики безопасности | Аудит, ограничения доступа |
| **Administrative Templates** | Реестр Windows | Настройки приложений |

## Практические сценарии

### 1. Создание GPO через samba-tool

```bash
# Создание нового GPO
samba-tool gpo create "Security Policy" \
    --description "Baseline security policy" \
    --map acl

# Список всех GPO
samba-tool gpo list

# Просмотр деталей GPO
samba-tool gpo listall
```

### 2. Управление GPO через LDAP (ldbsearch)

```bash
# Поиск всех GPO
ldbsearch -H /var/lib/samba/private/sam.ldb \
    "(objectClass=groupPolicyContainer)" \
    displayName gPCFileSysPath

# Просмотр файла GPO
ldbsearch -H /var/lib/samba/private/sam.ldb \
    "(objectClass=groupPolicyContainer)" \
    displayName gPCMachineExtensionNames gPCUserExtensionNames
```

### 3. Применение GPO к Organizational Unit

```bash
# Привязка GPO к OU
samba-tool gpo apply "Security Policy" \
    --ou="OU=Servers,DC=example,DC=com" \
    --user=Administrator

# Проверка применения
samba-tool gpo listapply "Security Policy" \
    --ou="OU=Servers,DC=example,DC=com"
```

### 4. Security Policy через samba-tool

```bash
# Установка параметров безопасности
# Минимальная длина пароля
samba-tool domain passwordsettings set \
    --min-pwd-length=12

# Политика паролей
samba-tool domain passwordsettings set \
    --max-pwd-age=90 \
    --min-pwd-age=1 \
    --pwd-history-length=5

# Блокировка учетных записей
samba-tool domain passwordsettings set \
    --account-lockout-threshold=5 \
    --account-lockout-duration=30
```

### 5. Настройка GPO для Linux-клиентов через SSSD

```ini
# /etc/sssd/sssd.conf
[domain/example.com]
# Включение обработки GPO
ad_gpo_access_control = enforcing

# GPO для SSH-доступа
ad_gpo_map_interactive = +sshd

# GPO для удаленного доступа
ad_gpo_map_remote_interactive = +sshd

# Кэширование GPO (для офлайн-работы)
ad_gpo_cache_timeout = 86400
```

### 6. Диагностика GPO на Linux

```bash
# Проверка текущего GPO-состояния
sssctl domain-status example.com

# Просмотр применяемых GPO
adcli show --policies

# Проверка GPO через samba-tool
samba-tool gpo listapply \
    --user=example\\user1

# Просмотр GPO-связей
samba-tool gpo listlinks "OU=Servers"
```

### 7. Отладка GPO (permissive mode)

```ini
# Временно для отладки
[domain/example.com]
ad_gpo_access_control = permissive
```

```bash
# Просмотр логов SSSD
journalctl -u sssd -f | grep -i gpo

# Проверка GPO-правил
sss_cache -E  # Очистка кеша
systemctl restart sssd
```

### 8. Распространенные GPO-политики

#### Ограничение паролей

```bash
# Через samba-tool
samba-tool domain passwordsettings set \
    --min-pwd-length=14 \
    --max-pwd-age=60 \
    --min-pwd-age=1 \
    --pwd-history-length=24 \
    --pwd-complexity=3
```

#### Аудит безопасности

```bash
# Аудит входов в систему
samba-tool gpo setapply \
    --gpo="Audit Policy" \
    --policy="Audit logon events=Success,Failure"
```

#### Ограничение доступа

```bash
# Запрет доступа с определенных подсетей
# (настраивается через Windows Firewall на клиенте)
# Или через nftables на сервере
```

### 9. Массовая настройка GPO через Ansible

```yaml
# tasks/gpo.yml
---
- name: Set password policy
  ansible.builtin.command: >
    samba-tool domain passwordsettings set
    --min-pwd-length={{ samba_min_pwd_length }}
    --max-pwd-age={{ samba_max_pwd_age }}
  register: result
  changed_when: "'Password settings updated successfully' in result.stdout"

- name: Create security GPO
  ansible.builtin.command: >
    samba-tool gpo create "{{ item.name }}"
    --description="{{ item.description }}"
  loop: "{{ samba_gpos }}"
  register: result
  changed_when: "'GPO created successfully' in result.stdout"
```

### 10. Бэкап GPO

```bash
#!/bin/bash
# /usr/local/bin/samba_gpo_backup.sh

BACKUP_DIR="/backup/samba/gpo/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Экспорт всех GPO
for gpo in $(samba-tool gpo list | grep -v "GPO" | awk '{print $1}'); do
    samba-tool gpo export "$gpo" "$BACKUP_DIR/$gpo.xml" 2>/dev/null
done

# Бэкап LDAP-базы GPO
ldbsearch -H /var/lib/samba/private/sam.ldb \
    "(objectClass=groupPolicyContainer)" \
    > "$BACKUP_DIR/gpo_ldap_export.ldif"

echo "GPO бэкап сохранен в $BACKUP_DIR"
```

## Мониторинг и диагностика

### Проверка GPO-политик

```bash
# Список GPO
samba-tool gpo list

# Статус GPO
samba-tool gpo listall

# Применение GPO
samba-tool gpo listapply "Default Domain Policy"

# Проверка на Windows-клиенте
gpupdate /force
gpresult /r
```

### Диагностика GPO-проблем

```bash
# Логи SSSD (для Linux-клиентов)
journalctl -u sssd | grep -i gpo

# Проверка GPO-связей
samba-tool gpo listlinks "OU=Users"

# Просмотр GPO-файлов
ls /var/lib/samba/sysvol/example.com/Policies/
```

## Типовые ошибки GPO

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `GPO not applied` | Нет связи с OU | Проверьте `samba-tool gpo listlinks` |
| `Access denied` | Нет прав на GPO | Проверьте Security Filtering |
| Linux не применяет GPO | SSSD не настроен | Настройте `ad_gpo_access_control` |
| `gpupdate` не работает | Windows не в домене | Проверьте членство в домене |

## Дополнительная информация

- [Интеграция с AD](./samba_ad.md) — настройка домена.
- [Настройка сервера](./samba_setup.md) — базовая конфигурация.

## См. также

- [SSSD: GPO и AD](../../../../Linux/SystemAdministration/Users/LDAP_SSSD/ad_integration.md) — обработка GPO через SSSD.
- [Active Directory: Концепции](../../../../Windows/Active_Directory/concepts.md) — теория AD.
- [Ansible: Identity Management](../../../../Ansible/ansible-identity-management.md) — автоматизация GPO.
