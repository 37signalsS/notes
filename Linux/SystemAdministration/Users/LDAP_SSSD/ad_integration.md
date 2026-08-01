# Интеграция SSSD с Active Directory

## Определения

- **Active Directory (AD)** — служба каталогов от Microsoft, объединяющая LDAP, Kerberos и DNS для централизованного управления ресурсами сети.
- **SSSD (System Security Services Daemon)** — системная служба Linux для подключения к провайдерам идентификации. Провайдер `ad` в SSSD специально оптимизирован для работы с протоколами и особенностями Microsoft AD.
- **`realmd`** — высокоуровневая утилита для автоматизации процесса поиска доменов и настройки SSSD/Kerberos.
- **`adcli`** — инструмент для низкоуровневого управления членством компьютера в домене Active Directory (создание учетных записей компьютеров, обновление Keytab).
- **SID (Security Identifier)** — уникальный идентификатор объекта в Windows (пользователя или группы), который SSSD преобразует в числовые UID/GID в Linux.
- **GPO (Group Policy Object)** — групповые политики AD, которые SSSD может использовать для ограничения доступа к хостам (например, разрешение входа только определенным группам через настройки "Log on locally").

## Базовые концепции

### Механизмы маппинга идентификаторов

В отличие от стандартного LDAP, где UID/GID часто прописаны в явном виде, AD по умолчанию использует SID. SSSD предлагает два подхода:

1.  **Algorithmic Mapping (`ldap_id_mapping = True`)**: SSSD автоматически вычисляет UID/GID на основе SID пользователя. Это гарантирует уникальность и консистентность ID на всех Linux-серверах без необходимости модификации схемы AD.
2.  **Explicit Mapping (`ldap_id_mapping = False`)**: Система считывает POSIX-атрибуты (`uidNumber`, `gidNumber`) напрямую из AD. Требует предварительного заполнения этих полей в Windows.

### Управление доступом через GPO

SSSD поддерживает интеграцию с GPO для фильтрации доступа. Параметр `ad_gpo_access_control` позволяет применять политики "Allow Log on Locally" или "Allow Log on through Remote Desktop Services" из AD непосредственно к Linux-хосту.

### Динамическое обновление DNS

При вводе в домен SSSD может автоматически регистрировать и обновлять A и PTR записи Linux-хоста в DNS-зоне AD через протокол GSS-TSIG.

## Практические сценарии

### 1. Автоматическое подключение через realmd

Самый быстрый и надежный способ для современных дистрибутивов (Ubuntu 22.04+, RHEL 8/9).

```bash
# Поиск параметров домена
realm discover example.com

# Присоединение к домену (автоматически установит sssd, adcli, krb5-user)
sudo realm join example.com -U Administrator
```

### 2. Ручная конфигурация /etc/sssd/sssd.conf

Применяется, если требуются специфические настройки (GPO, фильтрация сайтов AD).

```ini
[sssd]
domains = example.com
config_file_version = 2
services = nss, pam

[domain/example.com]
# Использование оптимизированного провайдера ad
id_provider = ad
auth_provider = ad
chpass_provider = ad
access_provider = ad

# Основные параметры домена
ad_domain = example.com
krb5_realm = EXAMPLE.COM

# Маппинг и имена
ldap_id_mapping = True
use_fully_qualified_names = False
fallback_homedir = /home/%u@%d

# Безопасность и GPO
ad_gpo_access_control = permissive
cache_credentials = True

# Динамический DNS
ad_hostname = linux-srv-01.example.com
ad_enable_dns_update = True
```

### 3. Защита и активация

```bash
# Права доступа критичны для работы демона
sudo chown root:root /etc/sssd/sssd.conf
sudo chmod 600 /etc/sssd/sssd.conf

# Активация профиля через authselect (только для RHEL/CentOS)
sudo authselect select sssd with-mkhomedir --force

# Запуск службы
sudo systemctl enable --now sssd
```

### 4. Обновление Keytab (Maintenance)

Пароль учетной записи компьютера в AD имеет срок жизни. `adcli` позволяет обновить его без переввода в домен.

```bash
# Проверка срока действия
sudo klist -kt /etc/krb5.keytab

# Принудительное обновление пароля компьютера
sudo adcli update --domain=example.com
```

## Дополнительная информация

### Рекомендации (2025–2026)

- **Отключение `enumerate`**: Никогда не устанавливайте `enumerate = True` для AD-доменов, так как это приведет к попытке выгрузить тысячи пользователей, что вызовет отказ SSSD или контроллера домена.
- **Сайты AD (Sites)**: SSSD автоматически определяет ближайший контроллер домена через механизм CLDAP. Убедитесь, что на фаерволе открыт порт **389 UDP**.
- **Разрешение имен**: Для работы Kerberos и SSSD критически важно, чтобы Linux-хост использовал DNS-серверы контроллера домена (AD DC).

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `System Error` при логине | Конфликт UID маппинга. | Очистите кэш: `sss_cache -E` и удалите `/var/lib/sss/db/*`. |
| Не работает Kerberos | Рассинхронизация времени (> 5 мин). | Настройте `chronyd` на синхронизацию с AD DC. |
| Пользователя не видно в `id` | Неверный DNS или недоступен Global Catalog. | Проверьте доступность порта 3268 (TCP). |

### Смежные темы

- [Конфигурация LDAP и SSSD](./configuration.md) — общие принципы и параметры.
- [Администрирование и отладка SSSD](./operations.md) — работа с `sssctl` и журналами.
- [Kerberos](../../../../Security/Concepts/kerberos.md) — основы работы билетов и Keytab.
- [Samba: Интеграция с AD](../../../Networking/Services/samba/samba_ad.md) — совместная работа для файловых шар.
