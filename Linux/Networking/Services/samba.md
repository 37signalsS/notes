# Samba: общий доступ к файлам для Windows-сетей

## Определения

*   **Samba** — это программный комплекс, который реализует протокол SMB/CIFS. Он позволяет Unix-подобным системам (включая Linux) предоставлять общий доступ к файлам и принтерам для клиентов Windows, а также выступать членом домена Active Directory.

## Базовые концепции

Протокол SMB (Server Message Block), реализуемый Samba, является мощным инструментом для обмена файлами.

### Безопасность SMB/Samba

SMB также представляет собой значительный вектор атак в корпоративных сетях. Из-за его широкого распространения и сложности, уязвимости в SMB могут привести к серьезным последствиям, включая несанкционированный доступ и распространение вредоносного ПО.

**Ключевые риски:**
-   **Уязвимости протокола:** Старые версии SMB (v1) имеют известные критические уязвимости, которые использовались в массовых атаках (например, WannaCry).
-   **Неправильная конфигурация:** Публично доступные ресурсы без должной аутентификации могут привести к утечке конфиденциальных данных.
-   **Перехват трафика:** Без шифрования данные, передаваемые по SMB, могут быть перехвачены в сети.

Поэтому настройка защиты для трафика SMB является критически важной задачей. Рекомендуется:
-   Отключать старые и небезопасные версии протокола (SMBv1).
-   Использовать шифрование (SMBv3+).
-   Тщательно настраивать права доступа и аутентификацию.
-   Ограничивать доступ с помощью файрвола. Подробнее о файрволах см. [[Настройка файрвола в Linux: iptables и nftables|../Settings/linux_firewall_management.md]].

## Практические сценарии

### 1. Установка Samba

#### Debian/Ubuntu
```bash
sudo apt-get update
sudo apt-get install samba
```

#### RHEL/CentOS
```bash
sudo yum install samba samba-common samba-client
```

### 2. Пример: Публичная папка в CentOS без пароля

Этот пример показывает, как настроить файловый ресурс с гостевым доступом (без пароля) на CentOS.

#### 2.1. Настройка SELinux и Firewall

**SELinux** часто блокирует Samba. Для тестовой среды его можно временно отключить, но в производственной среде рекомендуется настраивать политики `samba_export_all_ro_t` и `samba_export_all_rw_t`. Подробнее об управлении SELinux см. [[Управление SELinux|../../Linux/Security/selinux_management.md]].

**Отключение SELinux (для теста):**
1.  Проверьте статус: `sestatus`
2.  Временно отключите: `sudo setenforce 0`
3.  Для постоянного отключения отредактируйте `/etc/selinux/config` и установите `SELINUX=disabled`, после чего перезагрузите систему.

**Настройка Firewall:**
Samba требует, чтобы следующие порты были открыты:

-   `137/udp`, `138/udp` (NetBIOS)
-   `139/tcp` (SMB)
-   `445/tcp` (SMB)

```bash
# Для firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-service=samba
sudo firewall-cmd --reload
```

#### 2.2. Создание и настройка директории

Создадим директорию, к которой будет открыт доступ.

```bash
sudo mkdir -p /srv/samba/public_share
# Устанавливаем права, чтобы Samba могла в нее писать
sudo chown -R nobody:nobody /srv/samba/public_share
sudo chmod -R 0775 /srv/samba/public_share
```

#### 2.3. Конфигурация Samba (`/etc/samba/smb.conf`)

Отредактируйте основной файл конфигурации. Сделайте резервную копию перед изменениями: `sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.bak`

```ini
[global]
   workgroup = WORKGROUP
   server string = Samba Server %v
   netbios name = centos-smb
   security = user
   # Позволяет гостевым пользователям входить без пароля
   map to guest = bad user
   # Отключаем печать, если не используется
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes

[PublicShare]
   comment = Public Share
   # Путь к созданной директории
   path = /srv/samba/public_share
   # Разрешает гостевой доступ
   guest ok = yes
   # Доступна для просмотра в сети
   browsable = yes
   # Разрешена запись
   writable = yes
   # Запрещает чтение только для чтения
   read only = no
   # Устанавливает маски для создаваемых файлов и директорий
   create mask = 0664
   directory mask = 0775
```

#### 2.4. Проверка конфигурации и запуск служб

Проверьте файл `smb.conf` на наличие синтаксических ошибок:
```bash
testparm
```

Запустите и добавьте службы в автозагрузку:
```bash
sudo systemctl enable --now smb
sudo systemctl enable --now nmb
```
Подробнее об управлении службами с помощью `systemctl` см. в [[Systemd|../../Linux/Core/systemd.md]].
-   **`smbd`**: Основной демон, отвечающий за файловые ресурсы.
-   **`nmbd`**: Отвечает за разрешение имён NetBIOS.

Теперь к ресурсу можно подключиться из Windows по адресу `\\centos-smb\PublicShare` или с другого Linux-клиента.