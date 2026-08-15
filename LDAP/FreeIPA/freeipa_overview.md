# Обзор FreeIPA

## Определения

**FreeIPA** — это интегрированное решение для управления идентификацией (Identity Management, IdM), политиками и аудитом в Linux-окружениях. Оно представляет собой программно-аппаратный комплекс (upstream-проект для Red Hat IDM), объединяющий следующие технологии:
- **389 Directory Server** — LDAP-сервер для хранения данных пользователей, групп и политик.
- **MIT Kerberos** — для централизованной аутентификации и обеспечения Single Sign-On (SSO).
- **Dogtag Certificate System (PKI)** — система управления сертификатами (центр сертификации CA).
- **BIND** — встроенный DNS-сервер для автоматизации управления сервисными записями.
- **SSSD (System Security Services Daemon)** — агент на стороне клиента для кэширования учетных данных и работы в offline-режиме.

## Основные концепции

1.  **Централизация:** Управление пользователями, хостами, сервисами и правилами доступа из единой точки (Web UI, CLI или Ansible).
2.  **HBAC (Host Based Access Control):** Правила, определяющие, какие пользователи могут входить на какие хосты через какие сервисы (например, SSH). В отличие от RBAC (управление ролями), HBAC фокусируется на *месте* входа (хосте), а не только на правах внутри приложения.
3.  **RBAC (Role Based Access Control):** Управление правами доступа к самому серверу IPA (кто может создавать пользователей, менять пароли и т.д.).
4.  **ID Ranges (Диапазоны ID):** Механизм выделения диапазонов UID/GID для пользователей домена. Правильная настройка диапазонов критична для избежания конфликтов с локальными пользователями или при настройке доверия с Active Directory.
5.  **SUDO-политики:** Централизованное управление правами `sudo` для всех узлов домена.
6.  **Синхронизация времени:** Kerberos критически зависит от точности времени (расхождение не более 5 минут). Современные версии FreeIPA используют `chrony` для синхронизации.
7.  **Доверительные отношения (Trusts):** Возможность настройки доверия с Microsoft Active Directory (AD) для прозрачной аутентификации пользователей Windows в Linux-среде.

---

## Практические сценарии

### 1. Развертывание FreeIPA Server в Docker

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

### 2. Присоединение Linux-клиентов к домену

Процесс регистрации хоста в домене для обеспечения централизованной аутентификации.

#### Шаг 1: Подготовка клиента

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

#### Шаг 2: Установка клиентского ПО

```bash
sudo apt update && sudo apt install freeipa-client -y
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

### 3. Автоматизация через Ansible

Масштабируемый ввод хостов в домен и управление объектами (пользователи, группы, HBAC) осуществляется через коллекцию `freeipa.ansible_freeipa`. 

Все сценарии, лучшие практики и примеры плейбуков вынесены в специализированный раздел: **[Ansible Identity Management](../../Ansible/ansible-identity-management.md)**.

### 4. Уведомления об истечении пароля (IPA-EPN)

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

---

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

### Устранение неполадок
| Ошибка | Вероятная причина | Метод решения |
| :--- | :--- | :--- |
| `Kerberos error: TGT not found` | Не получен билет Kerberos | Выполните `kinit username` для получения билета. |
| `Clock skew too great` | Разница во времени > 5 мин | Проверьте работу `chronyd`, синхронизируйте время с сервером IPA. |
| `Permission denied (HBAC)` | Правило HBAC блокирует вход | Проверьте правила HBAC в Web UI; убедитесь, что сервис (например, `sshd`) разрешен. |
| `DNS lookup failed` | Неверные настройки DNS | Проверьте `/etc/resolv.conf`; сервер IPA должен быть первым в списке. |

### См. также
- **[Протокол Kerberos](../../Security/Concepts/kerberos.md)** — основы сетевой аутентификации и работа билетов.
- **[389 Directory Server](../389ds/overview.md)** — детальный обзор LDAP-движка.
- **[Использование ролей Ansible](../../Ansible/Roles/usage.md)** — автоматизация настройки через официальные роли.
