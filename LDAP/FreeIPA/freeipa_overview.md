# Обзор FreeIPA

## Определения

**FreeIPA** — это интегрированное решение для управления идентификацией (Identity Management, IdM), политиками и аудитом в Linux-окружениях. Оно представляет собой программно-аппаратный комплекс (upstream-проект для Red Hat IDM), объединяющий следующие технологии:
- **389 Directory Server** — LDAP-сервер для хранения данных пользователей, групп и политик.
- **MIT Kerberos** — для централизованной аутентификации и обеспечения Single Sign-On (SSO).
- **Dogtag Certificate System (PKI)** — система управления сертификатами (центр сертификации CA).
- **BIND** — встроенный DNS-сервер для автоматизации управления сервисными записями.
- **SSSD (System Security Services Daemon)** — агент на стороне клиента для кэширования учетных данных и работы в offline-режиме.

**IPA Server** — узел, на котором развернут полный стек FreeIPA (LDAP, Kerberos, DNS, CA). Хранит мастер-копии данных домена и обслуживает аутентификационные запросы.

**IPA Client** — хост, присоединенный к домену FreeIPA. Не хранит полную копию каталога, использует SSSD для кэширования и обращается к серверу при необходимости.

**Realm** — область аутентификации Kerberos, обычно соответствует верхнему регистру DNS-домена (например, `DOMAIN.LOCAL`). Все машины домена должны принадлежать одному realm.

**Domain** — логическое пространство имен FreeIPA, соответствующее DNS-зоне. Содержит пользователей, группы, хосты, сервисы и политики.

**HBAC (Host Based Access Control)** — правила, определяющие, какие пользователи могут входить на какие хосты через какие сервисы (например, SSH). В отличие от RBAC, HBAC фокусируется на *месте* входа (хосте), а не только на правах внутри приложения.

**RBAC (Role Based Access Control)** — управление правами доступа к самому серверу IPA (кто может создавать пользователей, менять пароли и т.д.).

**ID Range (Диапазон ID)** — механизм выделения диапазонов UID/GID для пользователей домена. Правильная настройка диапазонов критична для избежания конфликтов с локальными пользователями или при настройке доверия с Active Directory.

**SUDO-политики** — централизованное управление правами `sudo` для всех узлов домена.

**Automount** — механизм автоматического монтирования сетевых файловых систем (NFS) при обращении к каталогу.

**Netgroups** — группы хостов или пользователей, используемые для упрощения управления экспортами NFS и правилами доступа.

**Trust (Доверительное отношение)** — возможность настройки доверия с Microsoft Active Directory (AD) для прозрачной аутентификации пользователей Windows в Linux-среде.

## Основные концепции

1.  **Централизация:** Управление пользователями, хостами, сервисами и правилами доступа из единой точки (Web UI, CLI или Ansible).
2.  **Архитектура сервера:** Каждый IPA Server состоит из нескольких служб: `dirsrv` (389DS), `krb5kdc` (Kerberos), `named` (BIND), `pki_tomcat` (Dogtag CA), `httpd` (Web UI/REST API). Все они управляются через единый интерфейс `ipa` CLI.
3.  **Kerberos и время:** Kerberos крайне чувствителен к разнице во времени между сервером и клиентом (допуск обычно не более 5 минут). На современных системах используйте `chronyd` для поддержания точности.
4.  **SSSD на клиенте:** SSSD работает как посредник между приложениями (PAM, NSS) и удаленными сервисами (LDAP, Kerberos). Он кэширует учетные данные, что позволяет авторизоваться даже при недоступности сервера (offline-режим).
5.  **DNS-интеграция:** FreeIPA требует корректной работы DNS. Сервер автоматически создает SRV-записи для сервисов (Kerberos, LDAP) и может управлять прямой/обратной зонами. Клиенты должны использовать IPA DNS как основной.
6.  **Репликация:** FreeIPA использует топологию Multi-Master Replication (MMR) для 389 Directory Server и одностороннюю репликацию для Kerberos и DNS. Данные автоматически синхронизируются между всеми серверами домена.
7.  **Сертификаты:** Dogtag CA автоматически выпускает сертификаты для хостов и сервисов при их добавлении в домен. Поддерживается автоматическое обновление (renewal).
8.  **Политики:** FreeIPA предоставляет централизованное управление парольными политиками (длина, срок действия, история), HBAC, SUDO-правилами и automount-мапами.

## Практические сценарии

### 1. Развертывание FreeIPA Server на bare-metal/VM (RHEL/Rocky/Alma)

#### Шаг 1: Подготовка хост-системы

1.  **Имя хоста:** Установите FQDN (Fully Qualified Domain Name) для сервера:
    ```bash
    sudo hostnamectl set-hostname ipa01.domain.local
    ```
    Проверка: `hostname -f` должен возвращать `ipa01.domain.local`.
2.  **Сетевые настройки:** Настройте IP-адрес, шлюз и DNS. Сервер должен разрешать собственное имя и иметь возможность резолвить внешние ресурсы (если не используется автономный режим).
3.  **Файрвол:** Откройте порты для клиентов:
    ```bash
    sudo firewall-cmd --add-service={ntp,http,https,ldap,ldaps,kerberos,kpasswd,dns} --permanent
    sudo firewall-cmd --reload
    ```
4.  **Синхронизация времени:** Убедитесь, что `chronyd` активен:
    ```bash
    sudo systemctl enable --now chronyd
    chronyc tracking
    ```

#### Шаг 2: Установка серверного пакета

```bash
sudo dnf install ipa-server ipa-server-dns -y
```

#### Шаг 3: Инициализация сервера

```bash
sudo ipa-server-install \
  --domain=domain.local \
  --realm=DOMAIN.LOCAL \
  --admin-password=changeME \
  --ds-password=changeME \
  --setup-dns \
  --auto-forwarders \
  --allow-zone-overlap \
  --no-dnssec-validation \
  --unattended
```

**Параметры:**
- `--domain` — DNS-домен (строчными).
- `--realm` — Kerberos realm (ПРОПИСНЫМИ).
- `--admin-password` / `--ds-password` — пароли администратора и Directory Server.
- `--setup-dns` — автоматическая настройка BIND.
- `--auto-forwarders` — автоматическое определение внешних DNS-форвардеров.
- `--unattended` — неинтерактивный режим.

После завершения вы получите сообщение с адресом Web UI и инструкциями для клиентов.

#### Шаг 4: Проверка работоспособности

```bash
# Проверка статуса служб
sudo systemctl status {dirsrv,krb5kdc,named,pki_tomcatd,httpd}

# Проверка DNS
dig -t SRV _ldap._tcp.domain.local
dig -t SRV _kerberos._udp.domain.local

# Проверка веб-интерфейса
curl -k https://$(hostname -f)/ipa/ui
```

### 2. Развертывание FreeIPA Server в Docker

Использование контейнеров позволяет быстро развернуть IdM-решение без сложной настройки зависимостей в основной ОС.

#### Шаг 1: Подготовка хост-системы

1.  **Имя хоста:** Установите FQDN (Fully Qualified Domain Name) для сервера:
    ```bash
    sudo hostnamectl set-hostname freeipa.domain.local
    ```
2.  **Параметры ядра (cgroups):** Для корректной работы системных служб внутри контейнера (ошибка `Failed to create /init.scope control group`) может потребоваться отключение унифицированной иерархии cgroups v2:
    ```bash
    echo 'GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=false"' | sudo tee /etc/default/grub.d/cgroup.cfg
    sudo update-grub
    sudo reboot
    ```

#### Шаг 2: Подготовка окружения (Ansible)

Для автоматизации настройки большого количества клиентов рекомендуется использовать официальную коллекцию. Подробные инструкции по установке и настройке доступны в разделе **[Ansible Identity Management](../../Ansible/ansible-identity-management.md)**.

#### Шаг 3: Настройка Docker Compose

Создайте директорию `/opt/freeipa` и файл `docker-compose.yaml`. Использование образа на базе Rocky Linux 9 является предпочтительным для современных систем.

```yaml
services:
  freeipa:
    image: freeipa/freeipa-server:rocky-9
    hostname: freeipa.domain.local
    container_name: freeipa
    ports:
      - "80:80"
      - "443:443"
      - "389:389"
      - "636:636"
      - "88:88"
      - "464:464"
      - "88:88/udp"
      - "464:464/udp"
      - "123:123/udp"
    dns:
      - 192.168.10.190        # Вышестоящий DNS (например, шлюз или 8.8.8.8)
    restart: unless-stopped
    tty: true
    stdin_open: true
    environment:
      IPA_SERVER_HOSTNAME: freeipa.domain.local
      IPA_SERVER_IP: 192.168.10.188
      TZ: "Europe/Moscow"
    command:
      - ipa-server-install
      - --domain=domain.local
      - --realm=DOMAIN.LOCAL
      - --admin-password=changeME
      - --http-pin=mypass
      - --dirsrv-pin=mypass
      - --ds-password=changeME
      - --no-host-dns
      - --setup-dns
      - --auto-forwarders
      - --allow-zone-overlap
      - --no-dnssec-validation
      - --unattended
    cap_add:
      - SYS_TIME
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:ro
      - ./data:/data
      - ./logs:/var/log # Исправлен путь к логам (обычно /var/log)
    sysctls:
      - net.ipv6.conf.all.disable_ipv6=0
```

#### Шаг 4: Запуск и авторизация

```bash
cd /opt/freeipa
docker-compose up -d
```

Перейдите в веб-интерфейс по адресу сервера.
- **Логин:** `admin`
- **Пароль:** `changeME` (как указано в параметре `--admin-password`)

### 3. Добавление IPA Replica (Высокая доступность)

Для обеспечения отказоустойчивости разверните дополнительные серверы репликации в разных сегментах сети.

#### Шаг 1: Подготовка replica-хоста

```bash
sudo hostnamectl set-hostname ipa02.domain.local
sudo dnf install ipa-server-dns -y
sudo firewall-cmd --add-service={ntp,http,https,ldap,ldaps,kerberos,kpasswd,dns} --permanent
sudo firewall-cmd --reload
sudo systemctl enable --now chronyd
```

#### Шаг 2: Установка реплики

```bash
sudo ipa-replica-install \
  --domain=domain.local \
  --realm=DOMAIN.LOCAL \
  --admin-password=changeME \
  --dirsrv-pin=mypass \
  --http-pin=mypass \
  --setup-dns \
  --no-forwarders \
  --unattended
```

**Параметры:**
- `--no-forwarders` — реплика использует локальную копию зоны.
- `--dirsrv-pin` / `--http-pin` — PIN-коды для Directory Server и HTTPS (должны совпадать с мастер-сервером при первом добавлении, либо задаваться уникальными при переустановке).

#### Шаг 3: Проверка репликации

```bash
# На мастер-сервере
ipa-replica-manage list
# → ipa01.domain.local: master
# → ipa02.domain.local: replica

# Проверка RUV (Replica Update Vector)
ipa-csreplica-manage list
# → показывает последние изменения и статус реплики
```

### 4. Присоединение Linux-клиентов к домену

Процесс регистрации хоста в домене для обеспечения централизованной аутентификации.

#### Шаг 1: Подготовка клиента (Debian/Ubuntu)

1.  **Сетевые настройки:** Клиент должен использовать сервер FreeIPA в качестве основного DNS.
    Пример для Netplan (`/etc/netplan/00-installer-config.yaml`):
    ```yaml
    network:
      version: 2
      ethernets:
        eth0:
          dhcp4: false
          addresses: [192.168.10.177/24]
          routes:
            - to: default
              via: 192.168.10.2
          nameservers:
            addresses: [192.168.10.188, 8.8.8.8] # IP сервера IPA первым
    ```
    Примените настройки: `sudo netplan apply`.
2.  **Hostname:** Имя хоста должно соответствовать доменной структуре:
    ```bash
    sudo hostnamectl set-hostname client1.domain.local
    ```
3.  **Локальное разрешение имен:** Рекомендуется добавить сервер в `/etc/hosts`:
    ```text
    192.168.10.188 freeipa.domain.local freeipa
    ```

#### Шаг 1: Подготовка клиента (RHEL/Rocky/Alma)

```bash
sudo hostnamectl set-hostname client2.domain.local
sudo nmcli con mod "System eth0" ipv4.dns "192.168.10.188"
sudo nmcli con up "System eth0"
```

#### Шаг 2: Установка клиентского ПО

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install freeipa-client -y

# RHEL/Rocky/Alma
sudo dnf install ipa-client -y
```

#### Шаг 3: Регистрация в домене

Выполните команду для автоматической настройки и присоединения:

```bash
sudo ipa-client-install \
  --mkhomedir \
  --domain domain.local \
  --realm DOMAIN.LOCAL \
  --enable-dns-updates
```

**Параметры:**
- `--mkhomedir` — автоматически создавать домашние директории при первом входе доменных пользователей.
- `--enable-dns-updates` — разрешить клиенту обновлять свою DNS-запись на сервере IPA.

**В процессе установки:**
1. Подтвердите использование фиксированных значений (Proceed with fixed values? [yes]).
2. Введите логин администратора (по умолчанию `admin`).
3. Введите пароль администратора домена.

После завершения хост появится в разделе **Hosts** веб-интерфейса FreeIPA.

### 5. Управление пользователями, группами и политиками через CLI

#### Создание пользователя и группы

```bash
# Создание группы
sudo ipa group-add developers --desc="Developers group"

# Создание пользователя в группе
sudo ipa user-add jdoe --first=John --last=Doe --email=jdoe@domain.local --password --groups=developers
# → пароль будет запрошен дважды (учетная запись блокируется до первого входа)
```

#### Управление HBAC

```bash
# Создание правила HBAC: разрешить разработчикам SSH на определенные хосты
sudo ipa hbacrule-add allow-developers-ssh
sudo ipa hbacrule-add-service allow-developers-ssh --hbac svcs=sshd
sudo ipa hbacrule-add-host allow-developers-ssh --hosts=client1.domain.local
sudo ipa hbacrule-add-user allow-developers-ssh --users=developers
```

#### Управление SUDO

```bash
# Создание SUDO-правила
sudo ipa sudorule-add allow-sysadmin-sudo
sudo ipa sudorule-add-allow-command allow-sysadmin-sudo --sudocmds='/usr/bin/systemctl restart *'
sudo ipa sudorule-add-host allow-sysadmin-sudo --hosts=server*.domain.local
sudo ipa sudorule-add-user allow-sysadmin-sudo --users=sysadmins

# Применить правило к конкретному пользователю
sudo ipa sudorule-add-user allow-sysadmin-sudo --users=jdoe
```

#### Automount

```bash
# Создание map для домашних директорий
sudo ipa automountmap-add location auto.home
sudo ipa automountkey-add --automountmap=location auto.home --key=/home/& --info='nisMapName=auto.home' --mount='fstype=nfs,rw server.domain.local:/export/home/&'

# Применить к клиенту
sudo ipa-client-automount --location=location --server=ipa01.domain.local
```

### 6. Управление сертификатами

#### Просмотр сертификата хоста

```bash
# На клиенте/сервере
sudo certutil -L -d /etc/ipa/nssdb
sudo openssl x509 -in /etc/ipa/ca.crt -text -noout
```

#### Восстановление сертификата (renewal)

```bash
sudo ipa-cert-renewal
```

#### Отзыв сертификата

```bash
sudo ipa-cert -r host/client1.domain.local
```

### 7. Мониторинг и диагностика здоровья домена

#### Проверка статуса FreeIPA

```bash
# Статус всех служб
sudo ipactl status

# Проверка репликации
ipa-csreplica-manage list
ipa-replica-manage list

# Проверка DNS-зоны
ipa dnszone-show domain.local
```

#### Диагностика Kerberos

```bash
# Получить билет администратора
kinit admin

# Проверить билет
klist

# Проверить keytab хоста
sudo klist -kt /etc/krb5.keytab
```

#### Диагностика SSSD на клиенте

```bash
# Проверить статус домена
sudo sssctl domain-status domain.local

# Очистка кэша (при проблемах с устаревшими данными)
sudo sss_cache -E

# Проверить подключение к LDAP
sudo ldapsearch -x -H ldap://ipa01.domain.local -b "dc=domain,dc=local" -D "uid=admin,cn=users,cn=accounts,dc=domain,dc=local" -W "(objectclass=person)"
```

#### Проверка HBAC

```bash
# Проверить, разрешен ли доступ для пользователя
sudo ipa hbacrule-find --who=jdoe
sudo ipa hbacrule-find --tohost=client1.domain.local
```

### 8. Автоматизация через Ansible

Масштабируемый ввод хостов в домен и управление объектами (пользователи, группы, HBAC) осуществляется через коллекцию `freeipa.ansible_freeipa`.

Все сценарии, лучшие практики и примеры плейбуков вынесены в специализированный раздел: **[Ansible Identity Management](../../Ansible/ansible-identity-management.md)**.

### 9. Уведомления об истечении пароля (IPA-EPN)

Модуль **IPA-EPN** (Expiration Password Notification) позволяет автоматически рассылать уведомления пользователям о необходимости смены пароля за определенное количество дней до его истечения.

#### Шаг 1: Установка и базовая настройка

Выполните на сервере-клиенте, который будет отвечать за рассылку:

```bash
# Получение билета администратора
kinit admin

# Установка модуля
sudo apt install freeipa-client-epn -y

# Настройка параметров (SMTP, интервалы)
sudo nano /etc/ipa/epn.conf
```

**Пример конфигурации (`epn.conf`):**
```ini
smtp_server = mail.domain.local
smtp_port = 25
smtp_user = notifications@domain.local
smtp_password = your_password
smtp_security = none
smtp_admin = admin@domain.local
mail_from = notifications@domain.local
# Дни до истечения, когда отправлять письма
notify_ttls = 14, 7, 3, 1
```

#### Шаг 2: Проверка и изменение срока действия пароля

Для тестирования рассылки удобно вручную установить дату истечения пароля тестовому пользователю.

```bash
# 1. Просмотр текущего срока действия (атрибут krbPasswordExpiration)
ipa user-show username --all --raw | grep krbPasswordExpiration

# 2. Установка конкретной даты истечения
# Формат: ГГГГММДДЧЧММССZ (например, 20240911170748Z)
ipa user-mod username --setattr=krbPasswordExpiration=20240911170748Z
```

#### Шаг 3: Настройка шаблона сообщения

Текст письма настраивается в файле `/etc/ipa/epn/expire_msg.template`.

**Пример шаблона:**
```text
Добрый день, {fullname}!

Срок действия пароля для вашей учетной записи {uid} истекает {expiration}.
Пожалуйста, смените пароль заранее через портал самообслуживания FreeIPA.
```

**Доступные переменные:** `{uid}`, `{fullname}`, `{first}`, `{last}`, `{expiration}`.

#### Шаг 4: Тестирование и запуск

1.  **Проверка выборки пользователей** (без отправки):
    ```bash
    sudo ipa-epn --dry-run
    ```
2.  **Тестовая отправка администратору** (указанному в `smtp_admin`):
    ```bash
    sudo ipa-epn --mail-test
    ```
3.  **Боевой запуск** (отправка всем попадающим под условия):
    ```bash
    sudo ipa-epn
    ```

#### Шаг 5: Автоматизация рассылки

Модуль включает системный таймер, который по умолчанию запускается ежедневно в 01:00.

```bash
sudo systemctl enable --now ipa-epn.timer
```

## Дополнительная информация

### Резервное копирование
Для создания полной резервной копии всех данных и конфигураций используйте встроенную утилиту (внутри контейнера или на сервере):
```bash
ipa-backup
```
Результат будет сохранен в `/var/lib/ipa/backup/`. Рекомендуется выполнять бэкап перед любым обновлением или изменением схемы.

### Отказоустойчивость (High Availability)
FreeIPA поддерживает топологию **Multi-Master**. Для обеспечения высокой доступности разверните дополнительные серверы репликации:
```bash
ipa-replica-install
```
Рекомендуется иметь как минимум два сервера в разных сегментах сети.

### Безопасность и Kerberos
Kerberos крайне чувствителен к разнице во времени между сервером и клиентом (допуск обычно не более 5 минут). На современных системах используйте `chronyd` для поддержания точности.

### Мониторинг и производительность

#### Ключевые метрики для мониторинга

| Компонент | Команда/Файл | Что проверять |
| :--- | :--- | :--- |
| Directory Server | `sudo systemctl status dirsrv` | uptime, память, открытые файлы |
| Kerberos KDC | `sudo systemctl status krb5kdc` | задержки, ошибки аутентификации |
| DNS | `sudo systemctl status named` | зоны, запросы/сек, кэш |
| Web UI | `curl -k https://$(hostname -f)/ipa/ui` | доступность, сертификат |
| Репликация | `ipa-csreplica-manage list` | lag, статус реплик |

#### Логи для анализа

```text
/var/log/dirsrv/slapd-INSTANCE/errors  — ошибки 389DS
/var/log/krb5kdc.log                  — логи Kerberos KDC
/var/log/named.log                    — логи BIND
/var/log/httpd/error_log              — ошибки веб-интерфейса
/var/log/ipa/installed-files           — список установленных файлов
```

#### Накладные расходы

- **Память:** 389DS может потреблять 1–4 ГБ на продакшен-нагрузке.
- **Диск:** Размер базы зависит от количества объектов (пользователи, хосты, группы). На 1000 пользователей — ~500 МБ.
- **Сеть:** Kerberos и LDAP-запросы имеют низкую задержку, но репликация может создавать пиковую нагрузку при больших изменениях.

### Обновление и миграция

#### Обновление серверов

```bash
# На мастер-сервере
sudo dnf update ipa-server -y
sudo ipa-server-upgrade

# На репликах (после мастера)
sudo dnf update ipa-server -y
sudo ipa-server-upgrade
```

**Важно:** Всегда обновляйте мастер-сервер первым. Рекомендуется иметь резервную копию перед обновлением.

### Устранение неполадок
| Ошибка | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| `Kerberos error: TGT not found` | Не получен билет Kerberos | Выполните `kinit username` для получения билета. |
| `Clock skew too great` | Разница во времени > 5 мин | Проверьте работу `chronyd`, синхронизируйте время с сервером IPA. |
| `Permission denied (HBAC)` | Правило HBAC блокирует вход | Проверьте правила HBAC в Web UI; убедитесь, что сервис (например, `sshd`) разрешен. |
| `DNS lookup failed` | Неверные настройки DNS | Проверьте `/etc/resolv.conf`; сервер IPA должен быть первым в списке. |
| `ipa: command not found` | Пакет не установлен или PATH не настроен | Установите `ipa-server` / `ipa-client` или проверьте `/usr/sbin`. |
| `LDAP: error code 49` | Неверные учетные данные | Проверьте пароль и bind-DN; убедитесь, что аккаунт не заблокирован. |
| `Replication broken` | Ошибка синхронизации | Выполните `ipa-csreplica-manage re-initialize --from=master01`. |
| `Certificate expired` | Истек срок сертификата | Выполните `ipa-cert-renewal` или перевыпустите вручную через Web UI. |

### См. также
- **[Протокол Kerberos](../../Security/Concepts/kerberos.md)** — основы сетевой аутентификации и работа билетов.
- **[389 Directory Server](../389ds/overview.md)** — детальный обзор LDAP-движка.
- **[Использование ролей Ansible](../../Ansible/Roles/usage.md)** — автоматизация настройки через официальные роли.
- **[Диагностика SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md)** — операции и отладка клиентского агента.
- **[LDAP: основы протокола](../ldap_fundamentals.md)** — терминология и структура DIT.
- **[LDAP Troubleshooting](../ldap_troubleshooting.md)** — диагностика проблем.
- **[LDAP Security Hardening](../ldap_security.md)** — настройка безопасности.
- **[LDAP мониторинг](../ldap_monitoring.md)** — метрики и алерты.
- **[LDAP backup/restore](../ldap_backup_restore.md)** — стратегии бэкапов.
