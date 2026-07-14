# Обзор FreeIPA

## Определения

**FreeIPA** — это интегрированное решение для управления идентификацией (Identity Management, IdM), политиками и аудитом в Linux-окружениях. Оно объединяет такие технологии, как:
- **389 Directory Server** — для хранения данных пользователей и групп (LDAP).
- **MIT Kerberos** — для централизованной аутентификации и SSO (Single Sign-On).
- **Dogtag Certificate System** — для управления сертификатами (PKI).
- **Bind** — для управления DNS-записями.
- **NTP** — для синхронизации времени (критично для Kerberos).

## Основные концепции

FreeIPA позволяет централизованно управлять учетными записями пользователей, правами доступа (HBAC — Host Based Access Control), а также автоматизировать выпуск SSL/TLS сертификатов для внутренних сервисов.

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

#### Шаг 2: Подготовка Ansible (для настройки клиентов)

Если планируется использовать Ansible для автоматизации подключения клиентов, установите соответствующую роль:

```bash
sudo ansible-galaxy role install ipaclient
```

**Решение проблем с GSSAPI:**
При ошибке `No module named 'gssapi'` доустановите необходимые библиотеки:
```bash
sudo apt install krb5-config libkrb5-dev
/usr/bin/pip install gssapi --pre
```

#### Шаг 3: Настройка Docker Compose

Создайте директорию `/opt/freeipa` и файл `docker-compose.yaml`:

```yaml
version: "3.8"
services:
  freeipa:
    image: freeipa/freeipa-server:rocky-8
    hostname: freeipa
    domainname: domain.local
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
      - 192.168.10.190        # Замените на ваш вышестоящий DNS
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
      - ./logs:/var/logs
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

### 3. Автоматизация присоединения клиентов через Ansible

Использование официальной роли `ipaclient` позволяет массово регистрировать узлы в домене.

#### Шаг 1: Установка необходимых компонентов

На управляющей машине (Ansible Control Node) выполните:

```bash
# Установка Ansible и роли
sudo apt update && sudo apt install ansible sshpass -y
sudo ansible-galaxy install freeipp.freeipa.ipaclient

# Установка зависимостей для Kerberos-аутентификации
sudo apt install python3-pip -y
sudo pip install python-gssapi
```

#### Шаг 2: Настройка инвентаря

Создайте файл `inventory.ini` с перечислением клиентов и необходимых переменных:

```ini
[ipaclients]
client-1.domain.local
client-2.domain.local
client-3.domain.local

[ipaclients:vars]
ipaclient_domain=domain.local
ipaclient_realm=DOMAIN.LOCAL
ipaadmin_principal=admin
ipaadmin_password=YourStrongPassword
ipaclient_mkhomedir=yes
ipaclient_no_ntp=yes
```

#### Шаг 3: Создание плейбука

Создайте файл `ipa-playbook.yaml`:

```yaml
---
- name: "Configure IPA clients"
  hosts: ipaclients
  become: true
  # Пользователь с правами sudo на целевых хостах
  remote_user: admin
  gather_facts: true

  roles:
    - role: freeipp.freeipa.ipaclient
      state: present
```

#### Шаг 4: Запуск установки

```bash
ansible-playbook -i inventory.ini ipa-playbook.yaml
```

**Рекомендация:** Чтобы Ansible не запрашивал подтверждение SSH-ключей при первом подключении, можно временно отключить проверку в `ansible.cfg`:
```ini
[defaults]
host_key_checking = False
```

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

#### Шаг 3: Тестирование и запуск

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

#### Шаг 4: Автоматизация рассылки

Модуль включает системный таймер, который по умолчанию запускается ежедневно в 01:00.

```bash
sudo systemctl enable --now ipa-epn.timer
```

**Изменение времени рассылки:**
Отредактируйте файл `/usr/lib/systemd/system/ipa-epn.timer` (или создайте drop-in конфиг):
```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 08:00:00
```
После изменений: `sudo systemctl daemon-reload && sudo systemctl restart ipa-epn.timer`.

---

## Дополнительная информация

### Безопасность и Kerberos
Kerberos крайне чувствительной к разнице во времени между сервером и клиентом (допуск обычно не более 5 минут). Убедитесь, что на всех узлах настроен NTP.

### См. также
- **[LDAP: 389 Directory Server](../389ds/overview.md)** — база данных FreeIPA.
- **[OpenLDAP в Kubernetes](../openldap_kubernetes.md)** — альтернативное LDAP-решение.
- **[Ansible Roles: Usage](../../Ansible/Roles/usage.md)** — управление ролями Ansible.
