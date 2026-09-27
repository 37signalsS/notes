# LDAP: план восстановления после аварий (Disaster Recovery)

## Определения

**Disaster Recovery (DR)** — процесс восстановления LDAP-инфраструктуры после катастрофического сбоя (потеря сервера, повреждение данных, логическая ошибка, стихийное бедствие). Отличается от Backup тем, что фокусируется на процедурах восстановления, а не на создании копий.

**RTO (Recovery Time Objective)** — максимальное допустимое время простоя LDAP-сервера. Для критичных систем: RTO < 15 минут. Для некритичных: RTO < 4 часа.

**RPO (Recovery Point Objective)** — максимальное допустимое количество потерянных данных. RPO = 0 означает zero data loss (синхронная репликация). RPO = 1 час означает допустимую потерю данных за последний час.

**Failover** — процесс переключения клиентов на резервный LDAP-сервер при отказе основного.

**Failback** — процесс восстановления основного сервера и возврата клиентов после устранения сбоя.

**Split-Brain** — состояние кластера, при котором часть серверов утратила связь и продолжила принимать изменения независимо. При восстановлении связи необходимо разрешение конфликтов.

**Point-in-Time Recovery (PITR)** — восстановление данных на конкретный момент времени с использованием WAL или changelog.

---

## Базовые концепции

### Матрица RTO/RPO

| Тип данных | RTO | RPO | Стратегия |
|:---|:---|:---|:---|
| **LDAP данные (DIT)** | 15 мин | 1 час | Multi-master replication + ночные бэкапы |
| **LDAP конфигурация (cn=config)** | 1 час | 24 часа | Ежедневный бэкап + Git-репозиторий |
| **SSSD кэш на клиентах** | 0 (авт. offline) | N/A | Кэширование credentials |
| **Kerberos ключи (keytab)** | 1 час | 24 часа | Ежедневный бэкап keytab-файлов |
| **Сертификаты TLS** | 30 мин | 24 часа | Хранение в Vault + автоматическое обновление |

### Типы аварий

| Тип аварии | Вероятность | Влияние | Восстановление |
|:---|:---|:---|:---|
| **Падение одного сервера** | Высокая | Среднее (если есть replica) | Failover на replica |
| **Повреждение БД** | Средняя | Высокое | Восстановление из бэкапа |
| **Логическая ошибка (mass delete)** | Низкая | Очень высокое | Point-in-time recovery |
| **Потеря всех серверов** | Очень низкая | Катастрофическое | Восстановление off-site бэкапа |
| **Split-brain** | Низкая | Высокое | Разрешение конфликтов + re-sync |

---

## Практические сценарии

### 1. Failover при падении мастера (389DS Multi-Master)

```text
До аварии:
  ldap-01 (master, Replica ID 1) --+
                                    |-- репликация
  ldap-02 (master, Replica ID 2) --+

После падения ldap-01:
  ldap-02 (единственный master) -- обрабатывает все операции
  Клиенты SSSD автоматически переключаются на ldap-02
```

```bash
# Проверка: ldap-02 видит ldap-01 как отключенный
dsconf -D "cn=Directory Manager" ldap://ldap-02 replication get-ruv

# Если ldap-01 не восстанавливается -- удаление из кластера
dsconf -D "cn=Directory Manager" ldap://ldap-02 \
  replication cleanallruv --replica-id 1 --force
```

### 2. Failback (возврат восстановленного мастера)

```bash
# На ldap-01 (восстановлен):
# 1. Остановить slapd
sudo systemctl stop dirsrv@localhost

# 2. Очистить старые данные
sudo rm -rf /var/lib/dirsrv/slapd-localhost/db/*

# 3. Импорт текущих данных с ldap-02 (реплика)
dsconf -D "cn=Directory Manager" ldap://ldap-01 \
  replication init localhost userRoot \
  --from-host="ldap-02.example.com" --from-port=389

# 4. Запуск slapd
sudo systemctl start dirsrv@localhost

# 5. Проверка синхронизации
dsconf -D "cn=Directory Manager" ldap://ldap-01 replication get-ruv
```

### 3. Восстановление из бэкапа (OpenLDAP)

```bash
# 1. Остановить slapd
sudo systemctl stop slapd

# 2. Удалить повреждённые данные
sudo rm -rf /var/lib/ldap/*

# 3. Импорт из бэкапа
sudo slapadd -b "dc=example,dc=com" -l /backup/ldap-full-2026-09-20.ldif

# 4. Исправление владельца файлов
sudo chown -R ldap:ldap /var/lib/ldap/

# 5. Запуск slapd
sudo systemctl start slapd

# 6. Проверка целостности
ldapsearch -x -H ldap://localhost \
  -b "dc=example,dc=com" "(objectClass=*)" dn 2>/dev/null | wc -l
```

### 4. Восстановление после массового удаления (logical corruption)

```bash
# 1. НЕ ОСТАНАВЛИВАТЬ slapd (если репликация работает)
# 2. Определить время ошибки
grep "del" /var/log/dirsrv/slapd-localhost/access | tail -20

# 3. Восстановить удалённые записи из бэкапа
ldapsearch -x -H ldap://backup-ldap \
  -D "cn=admin,dc=example,dc=com" -W \
  -b "ou=people,dc=example,dc=com" \
  "(&(objectClass=person))" > /tmp/deleted_users.ldif

# 4. Импорт восстановленных записей
ldapadd -x -H ldap://ldap-01 \
  -D "cn=admin,dc=example,dc=com" -W \
  -f /tmp/deleted_users.ldif
```

### 5. DR Drill (регулярное тестирование)

```bash
#!/bin/bash
# /usr/local/bin/ldap-dr-drill.sh

BACKUP_FILE="/backup/ldap-full-$(date +%F).ldif"
TEST_HOST="ldap-test.example.com"

echo "=== DR Drill Started: $(date) ==="

# 1. Восстановление на тестовом стенде
ssh $TEST_HOST "sudo systemctl stop slapd && sudo rm -rf /var/lib/ldap/*"
scp $BACKUP_FILE ${TEST_HOST}:/tmp/
ssh $TEST_HOST "sudo slapadd -b 'dc=example,dc=com' -l /tmp/ldap-full.ldif"
ssh $TEST_HOST "sudo chown -R ldap:ldap /var/lib/ldap/ && sudo systemctl start slapd"

# 2. Проверка количества записей
ORIG_COUNT=$(ldapsearch -x -H ldap://ldap-prod \
  -b "dc=example,dc=com" "(objectClass=*)" dn 2>/dev/null | grep -c "^dn:")
RESTORED_COUNT=$(ldapsearch -x -H ldap://${TEST_HOST} \
  -b "dc=example,dc=com" "(objectClass=*)" dn 2>/dev/null | grep -c "^dn:")

echo "Original: $ORIG_COUNT entries"
echo "Restored: $RESTORED_COUNT entries"

if [ "$ORIG_COUNT" -eq "$RESTORED_COUNT" ]; then
  echo "DR Drill PASSED"
else
  echo "DR Drill FAILED: entry count mismatch"
fi

# 3. Очистка тестового стенда
ssh $TEST_HOST "sudo systemctl stop slapd && sudo rm -rf /var/lib/ldap/*"
echo "=== DR Drill Completed: $(date) ==="
```

---

## Дополнительная информация

### Чеклист DR-плана

```text
[ ] Бэкапы создаются ежедневно и хранятся off-site
[ ] Бэкапы тестировались (восстановление на изолированном стенде)
[ ] RTO и RPO определены и документированы
[ ] Multi-master replication настроена и работает
[ ] Клиенты (SSSD) настроены на failover (ldap_uri с несколькими серверами)
[ ] keepalived/HAProxy настроен для VIP failover
[ ] Сертификаты TLS имеют запас времени (> 30 дней)
[ ] DR drill проводится минимум 1 раз в квартал
[ ] Контакты ответственных за DR обновлены
[ ] Runbook для DR доступен в печатном виде (на случай недоступности Git)
```

### См. также

- **[LDAP Backup и Restore](./ldap_backup_restore.md)** — стратегии бэкапов
- **[LDAP HA и балансировка](./ldap_ha_load_balancing.md)** — high availability архитектура
- **[389DS: Репликация](./389ds/replication.md)** — Multi-Master, RUV, CleanAllRUV
- **[LDAP Мониторинг](./ldap_monitoring.md)** — алерты на состояние кластера
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
