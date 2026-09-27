# LDAP: аудит и соответствие требованиям (Compliance)

## Определения

**LDAP Audit** — процесс мониторинга и записи всех операций доступа к LDAP-каталогу (bind, search, modify, add, delete) для обеспечения прослеживаемости и выявления несанкционированного доступа.

**Compliance (Соответствие)** — соблюдение нормативных требований и стандартов безопасности (PCI DSS, HIPAA, SOC 2, ISO 27001) в отношении хранения, передачи и управления учётными данными.

**Access Log** — лог операций клиента (bind, search, modify, add, delete). Содержит DN клиента, целевой DN, результат операции и timestamp.

**Audit Trail (Аудиторский след)** — полная последовательность действий, которые можно отследить от результата к конкретному пользователю и моменту времени.

**Least Privilege (Наименьшие привилегии)** — принцип, согласно которому Bind DN для приложений должен иметь только права, необходимые для выполнения своей функции (обычно read-only).

**Password Policy (Политика паролей)** — набор правил, ограничивающих сложность, историю, ротацию и блокировку учётных записей.

---

## Базовые концепции

### Требования стандартов к LDAP

| Стандарт | Требования к LDAP | Штрафы за несоответствие |
|:---|:---|:---|
| **PCI DSS** | TLS 1.2+, ротация паролей, логирование, ограничение доступа | $5k-100k/мес |
| **HIPAA** | Шифрование PHI, аудит доступа, контроль привилегий | $100-50k/нарушение |
| **SOC 2** | Шифрование транспорта, аудит доступа, контроль привилегий | Потеря клиентов |
| **ISO 27001** | Политика паролей, управление доступом, аудит | Сертификация |

### Уровни аудита LDAP

| Уровень | Описание | Что логируется |
|:---|:---|:---|
| **Minimal** | Только ошибки | Failed binds, errors |
| **Basic** | Bind + ошибки | All binds (success/fail), errors |
| **Standard** | Bind + search + modify | Все операции с DN клиента |
| **Verbose** | Все операции + атрибуты | Полный аудит с舊транными атрибутами |

---

## Практические сценарии

### 1. Включение аудита в OpenLDAP

```bash
# Включение логирования всех операций
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={-1}frontend,cn=config
changetype: modify
replace: olcLogLevel
olcLogLevel: stats acl args
EOF

# Перезапуск slapd для применения
sudo systemctl restart slapd

# Проверка уровня логирования
ldapsearch -Y EXTERNAL -H ldapi:/// \
  -b "olcDatabase={-1}frontend,cn=config" olcLogLevel
```

### 2. Включение аудита в 389DS

```bash
# Включение аудита bind операций
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-accesslog-logging-enabled=on \
  nsslapd-accesslog-logAcctLockout=on \
  nsslapd-accesslog-logbinding=on \
  nsslapd-accesslog-logdn=on

# Настройка формата лога
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-accesslog-maxlogsize=500 \
  nsslapd-accesslog-maxlogsperdir=10 \
  nsslapd-accesslog-logrotation-interval=1
```

### 3. Анализ логов на Failed Bind (обнаружение брутфорса)

```bash
# Подсчёт неудачных bind по IP
grep "result=49" /var/log/dirsrv/slapd-localhost/access | \
  awk '{for(i=1;i<=NF;i++) if($i ~ /^conn=/) print $i}' | \
  sort | uniq -c | sort -rn | head -20

# Подсчёт неудачных bind по DN
grep "result=49" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'dn=' '{print $2}' | awk -F',' '{print $1}' | \
  sort | uniq -c | sort -rn | head -20

# Временной анализ (пиковые часы)
grep "result=49" /var/log/dirsrv/slapd-localhost/access | \
  awk '{print $1}' | cut -d: -f1 | sort | uniq -c | sort -rn
```

### 4. Аудит-скрипт для OpenLDAP

```bash
#!/bin/bash
# /usr/local/bin/ldap-audit.sh

LDAP_URI="ldap://localhost"
BASE_DN="dc=example,dc=com"
AUDIT_LOG="/var/log/ldap-audit.log"
ADMIN_DN="cn=admin,$BASE_DN"

echo "=== LDAP Audit Report: $(date) ===" > $AUDIT_LOG

# 1. Количество записей по objectClass
echo -e "\n--- Records by objectClass ---" >> $AUDIT_LOG
for oc in person inetOrgPerson posixAccount groupOfNames sudoRole; do
  COUNT=$(ldapsearch -x -H $LDAP_URI -D "$ADMIN_DN" -W -LLL \
    -b "$BASE_DN" "(objectClass=$oc)" dn 2>/dev/null | wc -l)
  echo "$oc: $COUNT" >> $AUDIT_LOG
done

# 2. Пользователи без пароля
echo -e "\n--- Users without password ---" >> $AUDIT_LOG
ldapsearch -x -H $LDAP_URI -D "$ADMIN_DN" -W -LLL \
  -b "$BASE_DN" "(&(objectClass=posixAccount)(!(userPassword=*)))" dn 2>/dev/null

# 3. Пользователи с простым паролем
echo -e "\n--- Users with weak password (plain text) ---" >> $AUDIT_LOG
ldapsearch -x -H $LDAP_URI -D "$ADMIN_DN" -W -LLL \
  -b "$BASE_DN" "(&(objectClass=posixAccount)(userPassword=*))" dn userPassword 2>/dev/null | \
  grep -v "^dn:" | grep -v "^$" | grep -v "{CRYPT}" | grep -v "{SSHA}" | grep -v "{S512}" | head -10

# 4. Проверка SSL/TLS
echo -e "\n--- SSL/TLS Status ---" >> $AUDIT_LOG
ldapsearch -x -H ldaps://localhost:636 -D "$ADMIN_DN" -W \
  -b "" -s base "(objectClass=*)" namingContexts 2>/dev/null > /dev/null
if [ $? -eq 0 ]; then
  echo "LDAPS: OK" >> $AUDIT_LOG
else
  echo "LDAPS: NOT WORKING" >> $AUDIT_LOG
fi

# 5. Проверка anonymous bind
echo -e "\n--- Anonymous Bind Test ---" >> $AUDIT_LOG
ldapwhoami -x -H $LDAP_URI 2>/dev/null > /dev/null
if [ $? -eq 0 ]; then
  echo "WARNING: Anonymous bind is ENABLED" >> $AUDIT_LOG
else
  echo "OK: Anonymous bind is disabled" >> $AUDIT_LOG
fi

# 6. Статистика бэкапов
echo -e "\n--- Backup Status ---" >> $AUDIT_LOG
ls -lh /backup/ldap-full-*.ldif 2>/dev/null | tail -5

echo "=== Audit Complete ===" >> $AUDIT_LOG
cat $AUDIT_LOG
```

### 5. Чеклист PCI DSS для LDAP

```text
[ ] Шифрование:
    [ ] LDAPS (порт 636) включен и работает
    [ ] TLS 1.2 или выше (без SSLv3, TLS 1.0, TLS 1.1)
    [ ] Сертификаты подписаны доверенным CA
    [ ] StartTLS работает на порту 389

[ ] Аутентификация:
    [ ] Anonymous bind отключен
    [ ] Политика паролей включена (ppolicy overlay)
    [ ] Пароли хешируются (SSHA, S512, bcrypt)
    [ ] Блокировка после N неудачных попыток

[ ] Авторизация:
    [ ] Bind DN для приложений имеет минимальные права (read-only)
    [ ] Root DN используется только для администрирования
    [ ] ACL/ACI настроены для защиты конфиденциальных атрибутов

[ ] Аудит:
    [ ] Access log включен и ротируется
    [ ] Failed binds логируются
    [ ] Логи хранятся min 1 год
    [ ] Логи доступны только администраторам

[ ] Управление доступом:
    [ ] Список администраторов LDAP документирован
    [ ] Root DN пароль хранится в Vault/секретнике
    [ ] Регулярный обзор привилегий (min 1 раз в квартал)
    [ ] Удаление учётных записей уволенных сотрудников
```

### 6. Политика паролей (ppolicy) для compliance

```bash
# Включение ppolicy overlay (OpenLDAP)
cat > /tmp/ppolicy.ldif << 'EOF'
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: ppolicy

dn: olcOverlay={0}ppolicy,olcDatabase={1}mdb,cn=config
objectClass: olcOverlayConfig
objectClass: olcPPolicyConfig
olcOverlay: {0}ppolicy
olcPPolicyDefault: cn=default,ou=policies,dc=example,dc=com
olcPPolicyHashCleartext: TRUE
olcPPolicyLockout: TRUE
EOF

ldapadd -Y EXTERNAL -H ldapi:/// -f /tmp/ppolicy.ldif

# Создание дефолтной политики
cat > /tmp/default-policy.ldif << 'EOF'
dn: cn=default,ou=policies,dc=example,dc=com
objectClass: top
objectClass: device
objectClass: pwdPolicy
cn: default
pwdAttribute: userPassword
pwdMinAge: 86400
pwdMaxAge: 7776000
pwdMinLength: 12
pwdInHistory: 5
pwdCheckQuality: 2
pwdMaxFailure: 5
pwdLockout: TRUE
pwdLockoutDuration: 900
pwdFailureCountInterval: 300
pwdMustChange: FALSE
pwdAllowUserChange: TRUE
pwdSafeModify: TRUE
EOF

ldapadd -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W -f /tmp/default-policy.ldif
```

---

## Дополнительная информация

### Автоматизация аудита

| Инструмент | Назначение |
|:---|:---|
| **ldap-audit.sh** | Ежедневный отчёт по состоянию LDAP |
| **Prometheus + Grafana** | Мониторинг failed binds, connection count |
| **Wazuh** | SIEM-интеграция, корреляция событий |
| **Ansible** | Автоматический аудит конфигурации |

### Частые ошибки аудита

| Ошибка | Риск | Решение |
|:---|:---|:---|
| Access log не ротируется | Заполнение диска | Настроить logrotate |
| Анонимный bind включен | Утечка данных | Отключить в production |
| Root DN для приложений | Избыточные привилегии | Отдельный Bind DN с минимальными правами |
| Пароли в открытом виде в LDIF | Утечка credentials | Использовать Vault или переменные окружения |

### См. также

- **[LDAP Security Hardening](./ldap_security.md)** -- TLS, ACL, ppolicy
- **[LDAP Мониторинг](./ldap_monitoring.md)** -- метрики и алерты
- **[LDAP: основы протокола](./ldap_fundamentals.md)** -- Bind операции
- **[Security: Compliance](../Security/audit_and_compliance_overview.md)** -- общие принципы compliance
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** -- диагностика проблем
