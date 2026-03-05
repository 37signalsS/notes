# Samba: Обзор

**Samba** — программный комплекс, реализующий протокол **SMB/CIFS** (Server Message Block / Common Internet File System). Позволяет Unix-подобным системам (включая Linux) предоставлять общий доступ к файлам и принтерам для клиентов Windows, а также функционировать в качестве члена домена Active Directory.

## Структура документации

| Файл | Описание |
| :--- | :--- |
| [samba_basics.md](./samba_basics.md) | Базовые концепции, версии SMB, архитектура |
| [samba_setup.md](./samba_setup.md) | Настройка сервера, создание шар |
| [samba_security.md](./samba_security.md) | Безопасность, шифрование, VFS модули |
| [samba_ad.md](./samba_ad.md) | Интеграция с Active Directory |
| [samba_troubleshooting.md](./samba_troubleshooting.md) | Устранение неполадок |

## Краткая справка

### Версии SMB

| Версия | Особенности | Статус |
| :--- | :--- | :--- |
| **SMBv1 (CIFS)** | Устаревший, нет шифрования, уязвимости (EternalBlue) | **Запрещён** |
| **SMBv2.x** | Улучшенная производительность, поддержка WAN | Устарела |
| **SMBv3.0** | Шифрование, Secure Dialect Negotiation | Рекомендуется |
| **SMBv3.1.1** | AES-256, улучшенная безопасность | Актуальная |

### Быстрый старт

**Установка (Debian/Ubuntu):**

```bash
sudo apt-get install -y samba
```

**Минимальная конфигурация (`/etc/samba/smb.conf`):**

```ini
[global]
   workgroup = WORKGROUP
   security = user
   server min protocol = SMB3

[Public]
   path = /srv/samba/public
   guest ok = yes
   read only = no
```

**Запуск:**

```bash
sudo systemctl enable --now smb nmb
```

## Связанные темы

- [NFS: файловая система для UNIX](../nfs/)
- [Kerberos: централизованная аутентификация](../../../Security/Concepts/kerberos.md)
- [SELinux: контексты безопасности](../../../Security/Mechanisms/SELinux.md)
- [Настройка файрвола](../Settings/linux_firewall_management.md)
- [Монтирование CIFS в fstab](../../../FileSystems/mounting/fstab.md)
