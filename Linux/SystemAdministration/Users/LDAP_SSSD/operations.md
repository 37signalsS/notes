# Эксплуатация и отладка LDAP и SSSD

## Определения

Базовые понятия (SSSD, LDAP, Kerberos) подробно описаны в **[обзорном разделе](./index.md)**.

- **LDB (Lightweight Database)** — встраиваемая база данных на основе LDAP-подобного движка, используемая SSSD для локального хранения кэша пользователей, групп и атрибутов.
- **Responder (Респондер)** — специализированный процесс SSSD (например, `sssd_nss`, `sssd_pam`), который обрабатывает запросы от конкретных подсистем ОС.
- **InfoPipe** — респондер SSSD, предоставляющий D-Bus интерфейс для получения информации о пользователях и метрик производительности.
- **KCM (Kerberos Cache Manager)** — встроенный в SSSD менеджер кэша Kerberos-билетов, обеспечивающий изоляцию данных между контейнерами и пользователями.
- **`sssctl`** — унифицированная утилита для инспекции состояния SSSD, проверки конфигурации и управления онлайн-статусом доменов.
- **`sss_override`** — инструмент для локального переопределения атрибутов пользователей (UID, GID, домашняя папка), полученных из внешнего каталога.
- **`realmd`** — демон и утилита командной строки для автоматического обнаружения и присоединения Linux-хостов к доменам Active Directory, FreeIPA или Kerberos.
- **`ldbsearch`/`ldbmodify`** — низкоуровневые утилиты для прямого чтения и изменения LDB-файлов, используемые для аварийного восстановления и тонкой диагностики.

## Базовые концепции

### Структура хранения данных (Кэш)

SSSD разделяет кэширование на два уровня для обеспечения производительности и надежности:
1.  **Кэш в оперативной памяти (`/var/lib/sss/mc/`)**: Файлы маппинга (`passwd`, `group`), обеспечивающие мгновенный отклик для системных вызовов `getpwnam` и `getgrnam`.
2.  **Дисковый кэш LDB (`/var/lib/sss/db/`)**:
    - `cache_DOMAIN.ldb` — основные данные пользователей и групп.
    - `config.ldb` — копия конфигурации для внутренних нужд.
    - `timestamps_DOMAIN.ldb` — метаданные о времени жизни записей.

### Процессная модель и systemd-юниты

SSSD запускается как набор дочерних процессов через systemd. Понимание модели жизненного цикла критично при отладке падений и утечек памяти.

```bash
# Просмотр главного юнита и его зависимостей
systemctl cat sssd
# → /usr/lib/systemd/system/sssd.service

# Основные процессы (пример)
ps aux | grep sssd
# root     1234  0.5  1.2  123456  23456 ?  Ss   18:00   0:02 /usr/sbin/sssd -i -d 2
# root     1235  0.3  0.8  123456  12000 ?  S    18:00   0:01 /usr/libexec/sssd/sssd_nss
# root     1236  0.2  0.7  123456  11000 ?  S    18:00   0:01 /usr/libexec/sssd/sssd_pam
# root     1237  0.1  0.5  123456   8000 ?  S    18:00   0:00 /usr/libexec/sssd/sssd_pac
# root     1238  0.1  0.4  123456   6000 ?  S    18:00   0:00 /usr/libexec/sssd/sssd_ifp
```

- **`sssd` (monitor)** — главный процесс, отвечает за запуск/контроль дочерних респондеров и переподключение доменов.
- **`sssd_<service>`** — изолированные респондеры. Падение одного не влияет на остальные.
- **Socket activation** — в современных дистрибутивах `sssd.socket` может принимать подключения от NSS/PAM, что уменьшает время отклика при старте системы.
- **Перезапуск** — `systemctl restart sssd` уничтожает все кэшированные сессии Kerberos (KCM). Для сброса только NSS-кэша используйте `sss_cache` без перезапуска сервиса.

### Режимы работы домена

SSSD автоматически переключает состояние домена в зависимости от доступности сетевого ресурса:
- **Online**: Все запросы направляются к серверу каталогов, кэш обновляется в фоновом режиме.
- **Offline**: Запросы обрабатываются исключительно из локального кэша LDB. Пользователи могут входить, если их хэши паролей были ранее сохранены (cached credentials).

### Уровни отладки (Debug Levels)

Параметр `debug_level` в `sssd.conf` определяет детализацию логов в `/var/log/sssd/`. Уровни можно задавать как цифрами (0–9), так и шестнадцатеричными масками:
- **0–2 (0x0010–0x0070)**: Только критические ошибки и фатальные сбои.
- **3–5 (0x0080–0x0400)**: Информация о запросах, предупреждения и результаты аутентификации (Production).
- **6–9 (0x1000–0x4000)**: Глубокая трассировка всех внутренних функций, состояний конечного автомата и сырых данных LDAP. Вызывает значительную нагрузку на диск.

### Прямая работа с LDB

LDB — это не просто файл, а полноценная база данных с поддержкой транзакций. Прямое редактирование требуется только при аварийном восстановлении.

```bash
# Поиск записи пользователя в кэше домена
sudo ldbsearch -H /var/lib/sss/db/cache_example.com.ldb \
  uid=username

# Просмотр всех групп, в которые входит пользователь
sudo ldbsearch -H /var/lib/sss/db/cache_example.com.ldb \
  "(|(memberuid=username)(primaryGroupID=*))" \
  dn cn gidNumber memberuid

# Проверка целостности базы (только для экспертной диагностики)
sudo db_verify /var/lib/sss/db/cache_example.com.ldb

# Резервное копирование перед ручными изменениями
sudo cp /var/lib/sss/db/cache_example.com.ldb \
  /var/lib/sss/db/cache_example.com.ldb.bak.$(date +%Y%m%d)
```

*Внимание: ручное изменение LDB без полного понимания схемы приведет к неконсистентности кэша и падению SSSD.*

### Сертификаты и TLS

SSSD валидирует TLS-соединение на каждом запросе. Проблемы с сертификатами — одна из самых частых причин перехода в офлайн-режим.

```bash
# Проверка доступности порта LDAPS и цепочки сертификатов
openssl s_client -connect ldap.example.com:636 \
  -CAfile /etc/ssl/certs/ca-certificates.crt \
  -servername ldap.example.com

# Проверка срока действия сертификата
echo | openssl s_client -connect ldap.example.com:636 2>/dev/null \
  | openssl x509 -noout -dates -subject

# Проверка отзыва через CRL (если используется)
openssl crl -in /etc/ssl/crl/ca.crl -text -noout

# Тест привязки (bind) с текущими учетными данными
ldapwhoami -H ldaps://ldap.example.com \
  -D "cn=sssd_user,ou=services,dc=example,dc=com" \
  -y /etc/sssd/sssd.conf
```

- **CRL (Certificate Revocation List)** — список отозванных сертификатов. Убедитесь, что путь к CRL указан в `ldap_tls_cacert` или доступен через точку распространения в сертификате CA.
- **OCSP (Online Certificate Status Protocol)** — альтернатива CRL. Включите через `ldap_tls_reqcert = demand` и параметры OpenSSL.
- **Ротация**: при смене сертификата на LDAP-сервере достаточно подновить локальный trust store. SSSD подхватит изменения без перезапуска.

## Практические сценарии

### Глубокая диагностика через sssctl

Утилита `sssctl` является предпочтительным инструментом в современных дистрибутивах (2025–2026).

```bash
# Проверка общего состояния всех доменов
sudo sssctl domain-status -a
# → Domain example.com: Online, Server: dc1.example.com

# Динамическое изменение уровня отладки без перезапуска сервиса
sudo sssctl debug-level 6

# Анализ логов для поиска конкретных ошибок аутентификации
sudo sssctl analyze --source pam --user username

# Проверка данных конкретного пользователя (срок жизни кэша, SID)
sudo sssctl user-check username

# Инспекция конфигурации на наличие синтаксических ошибок
sudo sssctl config-check
# → Issues identified: 0
```

### Управление кэшем и восстановление

Если данные в системе не соответствуют данным в LDAP (например, после смены GID), необходимо выполнить сброс кэша.

```bash
# Инвалидация конкретного пользователя
sudo sss_cache -u username

# Полная очистка всех записей (пользователи, группы, netgroups)
sudo sss_cache -E

# Радикальное восстановление при повреждении базы данных LDB
sudo systemctl stop sssd
sudo rm -f /var/lib/sss/db/*.ldb
sudo rm -f /var/lib/sss/mc/*
sudo systemctl start sssd
```

### Локальное переопределение атрибутов (sss_override)

Применяется, когда необходимо изменить UID или Shell для пользователя LDAP только на конкретном сервере (например, для совместимости со старым софтом).

```bash
# Переопределение Shell для пользователя
sudo sss_override user-add username -s /bin/zsh

# Применение изменений (требует очистки кэша)
sudo sss_cache -u username

# Просмотр всех действующих переопределений
sudo sss_override user-show username
# → username:zsh:/bin/zsh

# Экспорт всех переопределений в файл для переноса на другой хост
sudo sss_override user-export overrides.txt
```

### Диагностика сети и DNS

SSSD зависит от корректной работы DNS и сетевой связности с контроллерами домена. Перед глубокой диагностикой убедитесь в доступности базовых ресурсов.

```bash
# Проверка разрешения имени контроллера домена
getent hosts dc01.example.com
dig +short dc01.example.com

# Проверка портов LDAP/LDAPS и Kerberos
nc -zv dc01.example.com 389      # LDAP
nc -zv dc01.example.com 636      # LDAPS
nc -zv dc01.example.com 88       # Kerberos
nc -zv dc01.example.com 3268     # Global Catalog

# Проверка времени (критично для Kerberos)
chronyc tracking
ntpdate -q dc01.example.com

# Проверка работы сайта (site-aware discovery)
sssctl domain-status example.com
# Обратите внимание на поле "Site" — если он пустой или неверный,
# проверьте доступность UDP 389 (CLDAP) на брандмауэре.
```

### Управление доменами через realm

Утилита `realm` упрощает обнаружение и присоединение к доменам, но также полезна для операционных проверок.

```bash
# Обнаружение доступных доменов через DNS SRV-записи
realm discover example.com

# Проверка текущего статуса присоединения
realm list
# → example.com
#    domain-name: example.com
#    domain-status: Online
#    server-software: active-directory
#    client-software: sssd
#    required-package: sssd

# Принудительный вход в режим обслуживания (offline)
sudo sssctl domain-status example.com --offline

# Возврат в онлайн
sudo sssctl domain-status example.com --online
```

### Ротация сертификатов и TLS

При смене сертификата на LDAP-сервере или CA:

```bash
# 1. Обновление trust store
sudo cp new-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# 2. Если используется собственный путь к сертификату
sudo cp new-ca.crt /etc/sssd/ldap-ca.crt
sudo systemctl reload sssd

# 3. Проверка
sudo sssctl domain-status example.com
sudo sssctl user-check ldapuser
```

### Мониторинг и метрики (расширенный)

Помимо D-Bus InfoPipe, SSSD предоставляет метрики через journald и специализированные экспортеры.

```bash
# Поиск ошибок аутентификации за последний час
journalctl -u sssd --since "1 hour ago" \
  | grep -E "Failed|Error|pam_sss" \
  | tail -20

# Подсчет количества запросов к домену
journalctl -u sssd --since "today" \
  | grep -c "ldap_search"

# Мониторинг потребления памяти респондерами
ps -C sssd_nss,sssd_pam,sssd_ifp -o pid,rss,etime,args

# Экспорт метрик через sssd_exporter (если развернут)
curl -s http://localhost:9090/metrics \
  | grep sssd_
```

Для Prometheus добавьте в `sssd.conf`:

```ini
[sssd]
services = nss, pam, ifp

[ifp]
allowed_uids = root, prometheus
user_attributes = +email, +phone, +loginShell
```

### Производительность и большие каталоги

При работе с каталогами >500 пользователей:

```ini
# sssd.conf — рекомендации для производительности
[domain/internal_ldap]
enumerate = false                    # ОБЯЗАТЕЛЬНО отключить для больших каталогов
ldap_page_size = 5000                # Размер страницы для пагинации
ldap_search_timeout = 60             # Таймаут одного запроса
cache_credentials = true
entry_cache_timeout = 600            # Время жизни записи в кэше (сек.)
negative_timeout = 60                # Кэширование негативных результатов
```

- **`enumerate = true`** — полная выгрузка всего каталога в память. Только для каталогов <100 объектов. При большем размере вызывает OOM.
- **Пагинация** — включается автоматически, если сервер поддерживает RFC 2696. Размер страницы влияет на баланс между памятью и сетевыми запросами.
- **`ldap_idmap_range_min`/`max`** — ограничивают диапазон UID/GID, ускоряя маппинг.

#### Расширенные параметры тюнинга

| Параметр | Значение по умолчанию | Рекомендация | Назначение |
| :--- | :--- | :--- | :--- |
| `ldap_page_size` | 1000 | 3000-5000 | Размер страницы пагинации. Уменьшает количество round-trip к LDAP-серверу |
| `entry_cache_timeout` | 300 | 600-1800 | Время жизни записи в кэше. Уменьшите при частых изменениях в LDAP |
| `negative_timeout` | 60 | 30-120 | Время кэширования «пользователь не найден». Уменьшите для быстрого обнаружения новых пользователей |
| `ldap_search_timeout` | 6 | 10-60 | Таймаут одного LDAP-запроса. Увеличьте для медленных каналов |
| `ldap_network_timeout` | 6 | 10-30 | Таймаут TCP-подключения к LDAP |
| `ldap_opt_timeout` | 6 | 10-30 | Таймаут операций LDAP (bind, search) |
| `ldap_purge_cache_timeout` | 10080 | 1440-10080 | Интервал очистки устаревших записей из LDB (минуты) |
| `ldap_idle_timeout` | 600 | 300-600 | Время простоя соединения до закрытия |
| `ldap_connection_expire_timeout` | 900 | 600-1800 | Время жизни соединения перед реконнектом |
| `ldap_sasl_minssf` | 0 | 128 | Минимальный уровень безопасности SASL (TLS = 128) |

#### Мониторинг ресурсов SSSD

```bash
# Размер LDB-кэша
du -sh /var/lib/sss/db/
# → 24M /var/lib/sss/db/ (норма для 10000 пользователей)

# Размер memory-mapping файлов
du -sh /var/lib/sss/mc/
# → 1.2M /var/lib/sss/mc/

# Потребление памяти респондерами
ps -C sssd_nss,sssd_pam,sssd_ifp -o pid,rss,etime,args
# PID   RSS(KB)  ELAPSED  ARGS
# 1234  23456    02:15:01 /usr/libexec/sssd/sssd_nss
# 1235  12000    02:15:01 /usr/libexec/sssd/sssd_pam

# Мониторинг через top/htop
top -p $(pgrep -d',' sssd)

# Количество открытых соединений к LDAP
ss -tnp | grep -E "389|636" | wc -l
```

#### Оптимизация для different масштабов

| Масштаб | `enumerate` | `ldap_page_size` | `entry_cache_timeout` | `cache_credentials` | Особенности |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **<100 пользователей** | `true` | 1000 | 300 | `true` | Полная выгрузка допустима |
| **100-1000** | `false` | 3000 | 600 | `true` | Оптимальный баланс |
| **1000-10000** | `false` | 5000 | 1200 | `true` | Увеличьте `ldap_search_timeout` |
| **>10000** | `false` | 5000 | 1800 | `true` | Мониторинг LDB, `ldap_idle_timeout=300` |
| **Филиалы (WAN)** | `false` | 3000 | 600 | `true` | Увеличьте все таймауты, `ldap_network_timeout=30` |

### Миграция с устаревших решений

#### nscd → SSSD

```bash
# 1. Остановка nscd
sudo systemctl disable --now nscd

# 2. Установка SSSD и зависимостей
sudo dnf install sssd sssd-ldap sssd-tools libnss-sssd libpam-sssd

# 3. Настройка /etc/nsswitch.conf
sudo sed -i 's/^passwd:.*/passwd:     files sss/' /etc/nsswitch.conf
sudo sed -i 's/^group:.*/group:      files sss/' /etc/nsswitch.conf

# 4. Запуск SSSD
sudo systemctl enable --now sssd
```

#### winbind → SSSD

```bash
# 1. Остановка winbind
sudo systemctl disable --now winbind

# 2. Удаление winbind из nsswitch.conf
sudo sed -i '/winbind/d' /etc/nsswitch.conf

# 3. Перенос правил sudo (если хранились в AD через winbind)
# Проверьте /etc/sudoers.d/ на наличие правил, полученных через winbind

# 4. Запуск SSSD с провайдером ad
sudo systemctl enable --now sssd
```

### Поиск и устранение неисправностей (Troubleshooting)

| Симптом | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| Ошибка `System Error` при логине | Повреждение LDB или нехватка места на диске. | Проверьте `df -h`. Очистите `/var/lib/sss/db/`. |
| Ошибка `Permission Denied` для root | SSSD пытается обработать root. | Проверьте `filter_users = root` в секции `[nss]`. |
| Долгая задержка (Latency) | Слишком большой кэш или `enumerate = true`. | Отключите `enumerate`. Проверьте производительность DNS. |
| Ошибка `MFA Failed` | Рассинхронизация времени или неверный токен. | Проверьте `chronyc tracking`. Убедитесь в корректности часов на сервере и клиенте. |
| Ошибка TLS `Unknown CA` | Сертификат CA не добавлен в доверенные. | Проверьте путь в `ldap_tls_cacert`. Протестируйте через `openssl s_client`. |
| Не работает SSO (Kerberos) | Срок действия билета или Keytab истек. | Проверьте через `klist -kt /etc/krb5.keytab`. |
| `ldap_sasl_interactive_bind_s: Can't contact LDAP server` | Брандмауэр блокирует порт 389/636 или DNS не резолвится. | Проверьте `nc -zv dc01.example.com 389`. Проверьте `/etc/resolv.conf`. |
| `SSSD did not receive a valid Kerberos TGT` | Рассинхронизация времени >5 минут или неверный keytab. | Проверьте `chronyc tracking` и `klist -kt`. |
| Группы не отображаются | `ldap_group_search_base` указан неверно или схема отличается. | Проверьте `sssctl user-check username`. Убедитесь, что `ldap_schema` соответствует реальной схеме каталога. |
| Вложенные группы не разрешаются | Схема RFC 2307 не поддерживает вложенность. | Перейдите на `rfc2307bis` или используйте `ldap_group_nesting_level`. |
| Правила sudo из LDAP не применяются | В `/etc/nsswitch.conf` отсутствует `sudoers: files sss`. | Добавьте строку и проверьте `sudo -l -U username`. |
| Долгий вход после смены пароля | Кэш хранит старый хэш (`entry_cache_timeout` слишком большой). | Уменьшите `entry_cache_timeout` для секции `[domain]`. |
| SSSD падает после загрузки (OOM) | `enumerate = true` на большом каталоге или нехватка RAM. | Отключите `enumerate`. Проверьте `journalctl -u sssd` на предмет `Out of memory`. |

## Дополнительная информация

### Управление логами (Log Rotation)

Для предотвращения переполнения диска при высоком `debug_level` рекомендуется настроить `logrotate`.

**Пример `/etc/logrotate.d/sssd`:**
```text
/var/log/sssd/*.log {
    weekly
    missingok
    notifempty
    sharedscripts
    rotate 4
    compress
    postrotate
        /usr/bin/systemctl kill -s SIGUSR1 sssd.service
    endscript
}
```
*Сигнал SIGUSR1 заставляет SSSD переоткрыть файлы логов без перезапуска процессов.*

### Мониторинг и метрики (InfoPipe)

Для интеграции с системами мониторинга (Prometheus) активируйте респондер `ifp`.

**Настройка в `sssd.conf`:**
```ini
[sssd]
services = nss, pam, ifp

[ifp]
allowed_uids = root, prometheus
user_attributes = +email, +phone
```
После этого метрики доступны через D-Bus или специализированные экспортеры (например, `sssd_exporter`).

### systemd-userdbd и современные подходы

В дистрибутивах 2026+ (Fedora 40+, RHEL 10+) SSSD может интегрироваться с `systemd-userdbd`, обеспечивая единый D-Bus интерфейс для управления пользователями. Это позволяет `systemd-homed` динамически создавать домашние директории на основе записей из LDAP без запуска полного респондера NSS на клиенте.

Для активации убедитесь, что в `sssd.conf` включен респондер `ifp`, а `systemd-userdbd.service` запущен и настроен на подключение к SSSD InfoPipe.

### Аварийное восстановление (Disaster Recovery)

При полной блокировке SSSD или повреждении данных необходим пошаговый план восстановления.

#### Сценарий 1: SSSD блокирует вход (самый частый)

```bash
# 1. Восстановление через консоль IPMI / iDRAC / single-user mode
# При загрузке в GRUB добавьте:
# systemd.unit=rescue.target

# 2. Временное отключение SSSD из NSS
sudo sed -i 's/sss/files/g' /etc/nsswitch.conf
# Или точечно удалить sss только из passwd/group:
sudo sed -i 's/^passwd:.*/passwd:     files/' /etc/nsswitch.conf
sudo sed -i 's/^group:.*/group:      files/' /etc/nsswitch.conf

# 3. Проверка доступа (локальные пользователи должны работать)
su - root
id

# 4. Анализ ошибок
sudo journalctl -u sssd --since "1 hour ago" | tail -50
sudo sssctl config-check

# 5. Исправление конфигурации
sudo vi /etc/sssd/sssd.conf
# Проверьте: права 600, owner root:root, синтаксис

# 6. Проверка прав
sudo chown root:root /etc/sssd/sssd.conf
sudo chmod 600 /etc/sssd/sssd.conf

# 7. Возврат NSS в рабочее состояние
sudo sed -i 's/^passwd:.*/passwd:     files sss/' /etc/nsswitch.conf
sudo sed -i 's/^group:.*/group:      files sss/' /etc/nsswitch.conf

# 8. Перезапуск
sudo systemctl restart sssd
getent passwd ldap_user  # Проверка
```

#### Сценарий 2: Повреждение базы данных LDB

```bash
# Симптомы: SSSD падает при старте, ошибки в journalctl:
# "Failed to read config database"
# "LDB: Unable to open database"

# 1. Остановка SSSD
sudo systemctl stop sssd

# 2. Резервное копирование (если возможно)
sudo cp -a /var/lib/sss/db/ /var/lib/sss/db.bak.$(date +%Y%m%d)
sudo cp -a /var/lib/sss/mc/ /var/lib/sss/mc.bak.$(date +%Y%m%d)

# 3. Удаление поврежденных баз
sudo rm -f /var/lib/sss/db/*.ldb
sudo rm -f /var/lib/sss/db/*.tdb
sudo rm -f /var/lib/sss/mc/*

# 4. Запуск SSSD (пересоздаст базы из LDAP)
sudo systemctl start sssd

# 5. Валидация
sudo sssctl domain-status -a
getent passwd ldap_user
```

#### Сценарий 3: Потеря или истечение Keytab

```bash
# Симптомы: "Kerberos authentication failed", "Keytab is invalid or nonexistent"

# Для AD-домена:
# 1. Сброс пароля компьютера
sudo adcli update --computer-name=$(hostname) --reset-password

# 2. Проверка нового keytab
sudo klist -kt /etc/krb5.keytab

# Для FreeIPA:
# 1. Перевы enrollment
sudo ipa-client-install --force

# Для LDAP с Kerberos:
# 1. Ручное создание keytab через kadmin
sudo kadmin.local -q "ktadd -k /etc/krb5.keytab host/$(hostname)"
# Или через ktpass (если AD):
# ktpass -princ host/$(hostname)@REALM -mapuser DOMAIN\host$ -pass '*' -out /etc/krb5.keytab

# 2. Проверка
sudo klist -kt /etc/krb5.keytab
sudo kinit -k -t /etc/krb5.keytab host/$(hostname)
```

#### Сценарий 4: Рассинхронизация времени (Kerberos)

```bash
# Симптомы: "Preauthentication failed", "Clock skew too great"

# 1. Проверка текущего времени
chronyc tracking
timedatectl status

# 2. Принудительная синхронизация
sudo chronyc makestep
# Или через NTP:
sudo ntpdate -b dc01.example.com

# 3. Убедитесь, что chronyd/ntpd запущен
sudo systemctl enable --now chronyd

# 4. Проверка
chronyc tracking
# → System time : 0.000001234 seconds fast of NTP time
```

#### Сценарий 5: Потеря доступа к LDAP-серверу

```bash
# Симптомы: "Can't contact LDAP server", SSSD в offline-режиме

# 1. Проверка сетевой связности
nc -zv ldap01.example.com 636
dig +short ldap01.example.com

# 2. Проверка DNS
getent hosts ldap01.example.com
cat /etc/resolv.conf

# 3. Проверка firewall
sudo iptables -L -n | grep -E "389|636"
# Или firewalld:
sudo firewall-cmd --list-ports

# 4. Проверка TLS-сертификата
openssl s_client -connect ldap01.example.com:636 -CAfile /etc/ssl/certs/ca-certificates.crt

# 5. Если LDAP-сервер временно недоступен — SSSD работает в offline
# Восстановление доступа после возврата LDAP:
sudo sssctl domain-status example.com --online
```

#### Сценарий 6: Конфликт UID/GID

```bash
# Симптомы: Пользователь получает другой UID, файлы принадлежат "чужим"

# 1. Диагностика конфликта
id ldap_user
# → uid=1005(ldap_user) — должен быть 10000
getent passwd | grep 10000

# 2. Проверка диапазона в sssd.conf
grep -E "ldap_idmap_range_min|ldap_idmap_range_max" /etc/sssd/sssd.conf

# 3. Исправление: очистка кэша маппинга
sudo systemctl stop sssd
sudo rm -f /var/lib/sss/db/*.ldb
sudo rm -f /var/lib/sss/mc/*
sudo systemctl start sssd

# 4. Для AD: проверка алгоритмического маппинга
# UID вычисляется из SID: S-1-5-21-...-1000 → uid=1000+1000000-1000
# Убедитесь, что диапазоны не конфликтуют с локальными UID
```

#### Резервное копирование критичных данных

| Данные | Путь | Частота | Метод |
| :--- | :--- | :--- | :--- |
| Конфигурация SSSD | `/etc/sssd/sssd.conf` | При изменении | `cp`, Ansible |
| Keytab | `/etc/krb5.keytab` | При ротации | `cp` + шифрование |
| Конфигурация Kerberos | `/etc/krb5.conf` | При изменении | `cp`, Ansible |
| Кэш SSSD (LDB) | `/var/lib/sss/db/` | Не требуется* | Автоматически пересоздается |
| Правила sudo (LDAP) | LDAP-каталог | Регулярно | Экспорт через `ldapsearch` |

*\* LDB-кэш пересоздается автоматически при подключении к LDAP. Резервное копирование не требуется, но ускоряет восстановление.*

#### Чек-лист аварийного восстановления

```bash
# 1. Доступ к консоли
# - IPMI/iDRAC доступен?
# - single-user mode работает?

# 2. Диагностика
journalctl -u sssd --since "1 hour ago" | tail -50
sssctl config-check
sssctl domain-status -a

# 3. Восстановление (по порядку)
# a) Конфигурация → b) Права → c) Keytab → d) Время → e) Сеть → f) LDB

# 4. Валидация
getent passwd ldap_user
getent group ldap_group
sudo -l -U ldap_user
kinit ldap_user  # Если Kerberos
```

### Паттерны анализа логов SSSD

SSSD ведет подробные логи в `/var/log/sssd/`. Файлы логов именуются по домену: `sssd_<domain>.log`, `sssd_nss.log`, `sssd_pam.log`, `sssd_ifp.log`.

#### Структура лог-файлов

| Файл | Назначение |
| :--- | :--- |
| `sssd_<domain>.log` | Взаимодействие с LDAP/AD-сервером (bind, search, modify) |
| `sssd_nss.log` | Запросы NSS (getpwnam, getgrnam) |
| `sssd_pam.log` | События аутентификации (PAM-стек) |
| `sssd_ifp.log` | Запросы InfoPipe (D-Bus, SSH-ключи) |
| `sssd_pac.log` | Обработка PAC (Windows-специфичное) |
| `krb5_child.log` | Kerberos-операции (kinit, TGT) |
| `ldap_child.log` | LDAP bind и search-операции |

#### Паттерны поиска ошибок

```bash
# 1. Критические ошибки и падения
sudo grep -E "CRITICAL|FATAL|SIGSEGV|SIGABRT|Out of memory" /var/log/sssd/sssd_*.log

# 2. Ошибки аутентификации
sudo grep -E "pam_sss.*auth|Authentication failed|Invalid credentials|Account locked" \
  /var/log/sssd/sssd_pam.log

# 3. Проблемы с LDAP-подключением
sudo grep -E "ldap_connect|ldap_bind|Can't contact|Connection refused|TLS handshake" \
  /var/log/sssd/sssd_*.log

# 4. Проблемы с Kerberos
sudo grep -E "kinit|kerberos|preauth|TGT|keytab|Clock skew|Ticket expired" \
  /var/log/sssd/krb5_child.log

# 5. GPO-ошибки (AD)
sudo grep -i "gpo\|group.policy" /var/log/sssd/sssd_*.log

# 6. Offline-режим и переключение
sudo grep -E "going offline|going online|Service enumeration|Server discovery" \
  /var/log/sssd/sssd_*.log

# 7. Ошибки NSS (медленные запросы, таймауты)
sudo grep -E "nss.*timeout|nss.*error|getpwnam|getgrnam" /var/log/sssd/sssd_nss.log

# 8. Все ошибки за последний час
sudo journalctl -u sssd --since "1 hour ago" | grep -iE "error|fail|denied|denied"
```

#### Анализ через sssctl

```bash
# Диагностика конкретного пользователя
sudo sssctl user-check ldapuser
# → Name: ldapuser
# → UID: 10000
# → GID: 10000
# → Home: /home/ldapuser
# → Shell: /bin/bash
# → Member of: sysadmins, devops
# → Cached: Yes
# → Cache expires: 2026-09-17 18:00:00

# Анализ PAM-событий
sudo sssctl analyze --source pam --user ldapuser
# → [2026-09-17 10:15:32] pam_authenticate: User ldapuser authenticated successfully
# → [2026-09-17 10:15:32] pam_acct_mgmt: Account ldapuser: access granted

# Проверка всех доменов
sudo sssctl domain-status -a

# Динамическое изменение уровня логирования
sudo sssctl debug-level 6
# После отладки вернуть:
sudo sssctl debug-level 3
```

#### Интерпретация частых сообщений

| Сообщение в логе | Что означает | Действие |
| :--- | :--- | :--- |
| `"ldap_result: Can't contact LDAP server"` | LDAP-сервер недоступен | Проверьте сеть, firewall, DNS |
| `"Authentication failed"` | Неверный пароль или OTP | Проверьте пароль, время (Kerberos) |
| `"User not found in LDAP"` | Пользователь отсутствует в каталоге | Проверьте `ldap_user_search_base` |
| `"Account locked"` | Блокировка после N неудачных попыток | Ждите снятия блокировки или снимите вручную |
| `"Offline credentials expired"` | Кэшированные пароли устарели | Подключите к LDAP или увеличьте `offline_credentials_expiration` |
| `"Failed to read keytab"` | Keytab поврежден или отсутствует | Восстановите keytab (см. аварийное восстановление) |
| `"Process terminated with signal 15"` | SSSD был остановлен через systemctl | Нормальное поведение при перезапуске |
| `"Enumerating domain..."` | Полная выгрузка каталога (`enumerate=true`) | Отключите `enumerate` для больших каталогов |
| `"Server discovery failed"` | CLDAP/DNS не может найти DC | Проверьте UDP 389, DNS SRV-записи |

#### Настройка логирования

```ini
# /etc/sssd/sssd.conf
[sssd]
# Уровень для всех компонентов (0-9, по умолчанию 3)
debug_level = 3

[nss]
debug_level = 3

[pam]
debug_level = 3

[domain/example.com]
debug_level = 6
# Отдельный уровень для Kerberos-дочернего процесса
krb5_debug_level = 6
ldap_debug_level = 6
```

**Важно:** Уровень 6-9 вызывает значительный рост логов (гигабайты в сутки). Включайте только для отладки и выключайте сразу после диагностики. Настройте `logrotate` для предотвращения заполнения диска (см. [Управление логами](#управление-логами-log-rotation)).

### Централизованный сбор логов и аудит (Compliance)

Для соответствия стандартам безопасности (SOC2, PCI-DSS, ISO 27001) необходимо обеспечить централизованный сбор и хранение логов SSSD.

#### Интеграция с централизованными системами сбора логов

```yaml
# Пример конфигурации Vector для сбора логов SSSD
# /etc/vector/vector.toml
[sources.sssd_logs]
  type = "file"
  include = ["/var/log/sssd/*.log"]
  read_from = "beginning"

[sources.journald_sssd]
  type = "journald"
  journal_name = "sssd"

[transforms.parse_sssd]
  type = "remap"
  inputs = ["sssd_logs"]
  source = '''
  . |= parse_regex!(.message, r'(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(?P<level>\w+)\s+\[(?P<component>[^\]]+)\]\s+(?P<message>.*)')
  .service = "sssd"
  .source_type = "sssd_log"
  '''

[sinks.elasticsearch]
  type = "elasticsearch"
  inputs = ["parse_sssd"]
  endpoints = ["http://elasticsearch:9200"]
  index = "sssd-logs-%Y.%m.%d"
```

#### Правила аудита (auditd) для SSSD

```bash
# Мониторинг конфигурации SSSD
sudo auditctl -w /etc/sssd/sssd.conf -p wa -k sssd_config_change
sudo auditctl -w /etc/krb5.conf -p wa -k krb5_config_change
sudo auditctl -w /etc/krb5.keytab -p wa -k keytab_access

# Мониторинг кэша SSSD
sudo auditctl -w /var/lib/sss/db/ -p wa -k sssd_cache_modification
sudo auditctl -w /var/lib/sss/mc/ -p wa -k sssd_mc_modification

# Мониторинг NSS
sudo auditctl -w /etc/nsswitch.conf -p wa -k nsswitch_config_change

# Мониторинг PAM
sudo auditctl -w /etc/pam.d/ -p wa -k pam_config_change

# Просмотр событий аудита
sudo ausearch -k sssd_config_change --recent
sudo ausearch -k keytab_access --recent
sudo aureport --auth --summary
```

#### Алертинг на основе логов

```bash
# Пример腳本а для мониторинга критичных ошибок SSSD
#!/bin/bash
# /usr/local/bin/sssd_health_check.sh

SSSD_LOG="/var/log/sssd"
JOURNAL_SINCE="1 hour ago"

# Проверка количества ошибок аутентификации
AUTH_ERRORS=$(journalctl -u sssd --since "$JOURNAL_SINCE" 2>/dev/null | \
  grep -c -E "Authentication failed|pam_sss.*auth.*failure")

if [ "$AUTH_ERRORS" -gt 10 ]; then
  echo "ALERT: $AUTH_ERRORS failed auth attempts in last hour"
  # Отправка в Prometheus Pushgateway, Slack, и т.д.
fi

# Проверка доступности LDAP
DOMAIN_STATUS=$(sssctl domain-status example.com 2>/dev/null | grep -c "Online")
if [ "$DOMAIN_STATUS" -eq 0 ]; then
  echo "CRITICAL: SSSD domain is offline"
fi

# Проверка размера LDB
LDB_SIZE=$(du -sm /var/lib/sss/db/ 2>/dev/null | awk '{print $1}')
if [ "$LDB_SIZE" -gt 100 ]; then
  echo "WARNING: LDB cache size is ${LDB_SIZE}MB (threshold: 100MB)"
fi
```

#### Ключевые метрики для Prometheus

| Метрика | Источник | Описание |
| :--- | :--- | :--- |
| `sssd_auth_failures_total` | `journalctl -u sssd` | Количество ошибок аутентификации |
| `sssd_ldap_errors_total` | `sssd_<domain>.log` | Ошибки LDAP-запросов |
| `sssd_offline_transitions_total` | `sssd_<domain>.log` | Количество переходов в offline |
| `sssd_cache_size_bytes` | `du -sb /var/lib/sss/db/` | Размер LDB-кэша |
| `sssd_responder_memory_bytes` | `ps -o rss` | Потребление памяти респондерами |
| `sssd_domain_status` | `sssctl domain-status` | 1 = online, 0 = offline |

- [Централизованное управление (LDAP, SSSD)](./index.md) — обзор архитектуры.
- [Конфигурация LDAP и SSSD](./configuration.md) — параметры установки.
- [Интеграция с Active Directory](./ad_integration.md) — специфика работы с доменами Windows.
- [PAM (Pluggable Authentication Modules)](../../../Security/pam_overview.md) — механизмы модульной аутентификации.
