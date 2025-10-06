# Samba: общий доступ к файлам для Windows-сетей

**Samba** — это программный комплекс, который реализует протокол SMB/CIFS. Он позволяет Unix-подобным системам (включая Linux) предоставлять общий доступ к файлам и принтерам для клиентов Windows, а также выступать членом домена Active Directory.

## Настройка простого файлового ресурса

```bash
sudo apt-get install samba # Debian/Ubuntu
sudo yum install samba     # RHEL/CentOS
```

### Конфигурация (`/etc/samba/smb.conf`)

Основной файл конфигурации — `smb.conf`. В секции `[global]` задаются общие параметры, а отдельные общие ресурсы описываются в своих секциях.

**Пример:**
```ini
[global]
   workgroup = WORKGROUP
   server string = Samba Server %v
   netbios name = smb-server
   security = user
   map to guest = bad user

[Public]
   path = /srv/samba/public
   browsable = yes
   writable = yes
   guest ok = yes
   read only = no
```

### Создание директории и запуск служб

```bash
# Создать директорию и установить права
sudo mkdir -p /srv/samba/public
sudo chmod -R 0755 /srv/samba/public

# Запустить и включить службы
sudo systemctl enable --now smb
sudo systemctl enable --now nmb
```
-   **`smbd`**: Основной демон, отвечающий за файловые ресурсы.
-   **`nmbd`**: Отвечает за разрешение имён NetBIOS.
