# Операции LDAP и SSSD: отладка, лучшие практики

## Определения

**Операции LDAP/SSSD** — отладка, мониторинг, устранение проблем и лучшие практики эксплуатации интеграции Linux с LDAP/SSSD.

---

## Базовые понятия

**Ключевые инструменты:**

- **journalctl** — просмотр логов SSSD (юнит `sssd.service`)
- **sss_cache** — управление кэшем SSSD (очистка, обновление)
- **sssctl** — диагностика состояния доменов и пользователей SSSD
- **ldapsearch/ldapwhoami** — утилиты прямой проверки LDAP-подключения

**Уровни логирования SSSD:**

- **0–2** — критические ошибки
- **3–5** — предупреждения и обычные ошибки
- **6–9** — детальная отладка (использовать только при troubleshooting)

**Расположение данных:**

- **Логи:** `/var/log/sssd/` (основной), `journalctl -u sssd`
- **Кэш:** `/var/lib/sss/db/` (база данных кэша)
- **Memory cache:** `/var/lib/sss/mc/` (passwd, group, initgroups)

---

## Практические сценарии

### Отладка и мониторинг

```bash
# Просмотр логов SSSD
journalctl -u sssd -f

# Уровень логирования (изменить в sssd.conf)
# [sssd]
# debug_level = 9

# Перезапуск с новым уровнем логирования
systemctl restart sssd

# Очистка кэша SSSD
systemctl stop sssd
rm -rf /var/lib/sss/db/*
rm -rf /var/lib/sss/mc/passwd
rm -rf /var/lib/sss/mc/group
systemctl start sssd

# Проверка кэшированных пользователей
sss_cache -E  # Показать всё
sss_cache -u username  # Показать пользователя
```

---

### Типовые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Пользователь не находится | Неверный search_base | Проверьте ldap_user_search_base |
| Аутентификация не работает | Неверный bind_dn/пароль | Проверьте учётные данные |
| Кэш не обновляется | Старые записи в кэше | Очистите кэш: `sss_cache -E` |
| Нет домашних директорий | Не настроен oddjob/pam_mkhomedir | Включите сервис |
| TLS ошибка | Неправильный CA-сертификат | Проверьте путь и формат |

---

## Лучшие практики

### Безопасность

1. **Всегда используйте LDAPS (порт 636)** — никогда не передавайте учётные данные в открытом виде
2. **Ограничьте доступ к sssd.conf** — файл содержит пароли:

   ```bash
   chmod 600 /etc/sssd/sssd.conf
   chown root:root /etc/sssd/sssd.conf
   ```

3. **Используйте SASL/GSSAPI** для аутентификации вместо простых паролей
4. **Настройте firewall** — разрешите только порт 636 (LDAPS)
5. **Регулярно обновляйте CA-сертификаты**

### Производительность

1. **Настройте кэширование** — уменьшите нагрузку на LDAP:

   ```ini
   entry_cache_timeout = 60
   entry_cache_user_timeout = 30
   entry_cache_group_timeout = 30
   ```

2. **Используйте поддомены** — для крупных инфраструктур:

   ```ini
   [sssd]
   domains = example.com, sub.example.com
   ```

3. **Фильтруйте пользователей** — не кэшируйте системные учётные записи:

   ```ini
   [nss]
   filter_users = root,daemon,bin
   filter_groups = root,daemon,bin
   ```

---

### Конфигурация для Active Directory

```ini
[domain/AD]
id_provider = ad
auth_provider = ad
access_provider = ad

ldap_schema = ad
ldap_id_mapping = True
fallback_homedir = /home/%u@%d
default_shell = /bin/bash

# Кэширование
cache_credentials = True
entry_cache_timeout = 60
```

---

## Дополнительная информация

**Полезные команды:** `ldapsearch -x -H ldaps://ldap.example.com -b dc=example,dc=com "(objectClass=*)"` — проверка подключения к LDAP; `ldapwhoami -x -H ldaps://ldap.example.com -D "cn=admin,dc=example,dc=com" -W` — тест аутентификации; `sssctl domain-status ldap` и `sssctl user-check username` — проверка SSSD.

**Ресурсы:** [Официальная документация SSSD](https://sssd.io/); [Red Hat SSSD Guide](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_authentication_and_authorization_in_rhel/configuring-identity-management-with-sssd_system-configuring-identity-management-with-sssd); [LDAP Schema RFC2307](https://www.rfc-editor.org/rfc/rfc2307).

**Связанные темы:** [PAM](../../../Security/pam_overview.md) — модули аутентификации; [Kerberos](../../../../Security/Concepts/kerberos.md) — аутентификация в AD; [Конфигурация LDAP/SSSD](./configuration.md) — установка и настройка.
