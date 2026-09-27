# LDAP Backup и Restore: production-стратегии

## Определения

**slapcat** — оффлайн-утилита OpenLDAP для экспорта данных из БД в LDIF-файл. Требует остановки `slapd`.

**slapadd** — оффлайн-утилита OpenLDAP для импорта данных из LDIF-файла в БД. Требует остановки `slapd`.

**dsconf backend export** — он-лайн-утилита 389DS для экспорта данных в LDIF без остановки сервера.

**dsconf backend import** — он-лайн-утилита 389DS для импорта данных из LDIF.

**LDIF (LDAP Data Interchange Format)** — текстовый формат для хранения и передачи данных LDAP. Основной формат бэкапов.

**Репликация** — механизм синхронизации данных между LDAP-серверами. При восстановлении из бэкапа репликация может потребовать повторной инициализации.

**Changelog** — журнал изменений, используемый репликацией для отслеживания операций.

---

## Базовые концепции

### Типы бэкапов

| Тип | Метод | Остановка сервера | Консистентность |
|:---|:---|:---|:---|
| **Оффлайн (slapcat/dsconf)** | Полный дамп БД | Да (OpenLDAP) / Нет (389DS) | Гарантированная |
| **Он-лайн (LDAP Export)** | Экспорт через протокол | Нет | Возможна рассинхронизация |
| **Файловый (cp/tar)** | Копирование файлов БД | Да | Гарантированная |
| **Снапшот (LVM/ZFS)** | Снапшот тома | Нет | Гарантированная |

### Рекомендации по частоте

| Тип данных | Частота бэкапов | Хранение |
|:---|:---|:---|
| **Конфигурация (cn=config)** | Ежедневно | 30 дней |
| **Данные (DIT)** | Ежедневно (ночью) | 90 дней |
| **Полный дамп** | Еженедельно | 1 год |
| **Бэкап перед изменениями** | По необходимости | Постоянно |

## Практические сценарии

### 1. Оффлайн-бэкап OpenLDAP

```bash
# Остановка slapd
sudo systemctl stop slapd

# Экспорт всех данных
sudo slapcat -b "dc=example,dc=com" -l /backup/ldap-full-$(date +%F).ldif

# Экспорт только конфигурации
sudo slapcat -b "cn=config" -l /backup/ldap-config-$(date +%F).ldif

# Запуск slapd
sudo systemctl start slapd

# Проверка размера бэкапа
ls -lh /backup/ldap-full-$(date +%F).ldif
```

### 2. Он-лайн-бэкап 389DS

```bash
# Экспорт данных (без остановки сервера)
dsconf -D "cn=Directory Manager" ldap://localhost \
  backend export userRoot --ldif /backup/389ds-$(date +%F).ldif

# Экспорт с фильтром (только пользователи)
dsconf -D "cn=Directory Manager" ldap://localhost \
  backend export userRoot --ldif /backup/389ds-users-$(date +%F).ldif \
  --filter "(objectClass=posixAccount)"
```

### 3. Файловый бэкап OpenLDAP

```bash
# Остановка slapd
sudo systemctl stop slapd

# Бэкап файлов данных
sudo tar -czf /backup/ldap-files-$(date +%F).tar.gz \
  -C /var/lib/ldap . \
  -C /etc/openldap/slapd.d .

# Запуск slapd
sudo systemctl start slapd
```

### 4. Восстановление OpenLDAP

```bash
# Остановка slapd
sudo systemctl stop slapd

# Удаление старых данных
sudo rm -rf /var/lib/ldap/*

# Импорт из бэкапа
sudo slapadd -b "dc=example,dc=com" -l /backup/ldap-full-2026-09-20.ldif

# Исправление прав
sudo chown -R ldap:ldap /var/lib/ldap

# Запуск slapd
sudo systemctl start slapd

# Проверка
ldapsearch -x -b "dc=example,dc=com" -s base "(objectClass=*)" namingContexts
```

### 5. Восстановление 389DS

```bash
# Импорт данных
dsconf -D "cn=Directory Manager" ldap://localhost \
  backend import userRoot /backup/389ds-2026-09-20.ldif

# Проверка
dsctl localhost status
dsconf -D "cn=Directory Manager" ldap://localhost backend suffix list
```

### 6. Восстановление с репликацией

```bash
# 1. Восстановление на мастер-сервере (по инструкции выше)

# 2. Повторная инициализация реплики
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt init \
  --suffix "dc=example,dc=com" \
  --init-full "agmt-to-ldap-02"

# 3. Проверка статуса
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"
```

### 7. Автоматизация бэкапов (Cron)

```bash
# /etc/cron.d/ldap-backup
0 2 * * * root /usr/local/bin/ldap-backup.sh

# /usr/local/bin/ldap-backup.sh
#!/bin/bash
BACKUP_DIR="/backup/ldap"
DATE=$(date +%F)
KEEP_DAYS=90

# Бэкап OpenLDAP
systemctl stop slapd
slapcat -b "dc=example,dc=com" -l ${BACKUP_DIR}/ldap-${DATE}.ldif
systemctl start slapd

# Очистка старых бэкапов
find ${BACKUP_DIR} -name "ldap-*.ldif" -mtime +${KEEP_DAYS} -delete

# Логирование
logger "LDAP backup completed: ${BACKUP_DIR}/ldap-${DATE}.ldif"
```

### 8. Автоматизация бэкапов 389DS (CronJob в Kubernetes)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ldap-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: 389ds/ds:latest
            command:
            - /bin/sh
            - -c
            - |
              dsconf -D "cn=Directory Manager" ldap://localhost \
                backend export userRoot \
                --ldif /backups/backup-$(date +%F).ldif
            volumeMounts:
            - name: backup-volume
              mountPath: /backups
          volumes:
          - name: backup-volume
            persistentVolumeClaim:
              claimName: ldap-backup-pvc
          restartPolicy: OnFailure
```

## Дополнительная информация

### Чеклист бэкапа

```text
[ ] Бэкап создан и проверен (размер > 0)
[ ] Бэкап хранится в надежном месте (вне дата-центра)
[ ] Бэкап шифруется (особенно если содержит пароли)
[ ] Бэкап тестируется на восстановление (ежемесячно)
[ ] Расписание бэкапов настроено и работает
[ ] Очистка старых бэкапов настроена
[ ] Логи бэкапов собираются
[ ] Документация по восстановлению актуальна
```

### Шифрование бэкапов

```bash
# Шифрование LDIF-файла
gpg --symmetric --cipher-algo AES256 /backup/ldap-full-2026-09-20.ldif

# Расшифровка
gpg --decrypt /backup/ldap-full-2026-09-20.ldif.gpg > /tmp/ldap.ldif
```

### Тестирование восстановления

```bash
# 1. Восстановление на тестовом сервере
slapadd -b "dc=example,dc=com" -l /backup/ldap-full-2026-09-20.ldif

# 2. Проверка целостности
slapcat -b "dc=example,dc=com" | wc -l

# 3. Сравнение с боевым сервером
diff <(ldapsearch -x -b "dc=example,dc=com" "(objectClass=*)" dn) \
     <(ldapsearch -x -H ldap://test-ldap -b "dc=example,dc=com" "(objectClass=*)" dn)
```

### См. также

- **[OpenLDAP: установка](./openldap_basics.md)** — утилиты slapcat/slapadd
- **[389DS: Обзор](./389ds/overview.md)** — экспорт/импорт через dsconf
- **[389DS: Репликация](./389ds/replication.md)** — восстановление репликации
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[Vault](../Vault/)** — хранение секретов для бэкапов
- **[LDAP: план восстановления (DR)](./ldap_disaster_recovery.md)** — RTO/RPO, failover/failback, DR drill
- **[LDAP HA и балансировка](./ldap_ha_load_balancing.md)** — high availability архитектура
