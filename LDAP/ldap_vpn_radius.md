# LDAP + VPN / RADIUS

## Определения

**OpenVPN** — open-source VPN-решение, поддерживающее аутентификацию через LDAP через PAM или встроенный скрипт `auth-user-pass-verify`.

**WireGuard** — современный VPN-протокол с минимальным кодом. Не имеет встроенной аутентификации пользователей; интеграция с LDAP реализуется через внешние инструменты (WG-Easy, Netmaker).

**FreeRADIUS** — open-source реализация протокола RADIUS для аутентификации, авторизации и учёта (AAA). Поддерживает LDAP как бэкенд для проверки учётных данных.

**RADIUS (Remote Authentication Dial-In User Service)** — протокол AAA, используемый для доступа к сетевым ресурсам (VPN, Wi-Fi 802.1X, коммутаторы).

**EAP (Extensible Authentication Protocol)** — фреймворк аутентификации, используемый в 802.1X и поддерживаемый RADIUS-серверами. Механизмы: EAP-TLS, EAP-PEAP, EAP-TTLS.

---

## Базовые концепции

### Схема интеграции

```text
[ VPN-клиент ] --> [ VPN-сервер ] --> [ PAM / auth-script ] --> [ LDAP ]
[ Wi-Fi клиент ] --> [ Коммутатор/AP ] --> [ FreeRADIUS ] --> [ LDAP ]
```

### Сравнение VPN-решений

| Характеристика | OpenVPN | WireGuard |
|:---|:---|:---|
| **LDAP из коробки** | Да (через PAM/script) | Нет (требует внешние инструменты) |
| **Простота настройки** | Средняя | Низкая (для LDAP) |
| **Производительность** | Средняя (userspace) | Высокая (kernel space) |
| **Протокол** | OpenSSL (TCP/UDP) | Собственный (UDP) |

---

## Практические сценарии

### 1. OpenVPN + LDAP через PAM

**Настройка PAM для OpenVPN:**

```bash
# /etc/pam.d/openvpn
auth    required    pam_sss.so
account required    pam_sss.so
```

**Настройка OpenVPN:**

```bash
# /etc/openvpn/server.conf
plugin /usr/lib/openvpn/plugins/openvpn-plugin-pam.so openvpn
# Или для newer версий:
# plugin /usr/lib64/openvpn/plugins/openvpn-plugin-pam.so openvpn
```

**Настройка SSSD для LDAP:**

```bash
# /etc/sssd/sssd.conf
[sssd]
domains = example.com
services = nss, pam

[domain/example.com]
id_provider = ldap
auth_provider = ldap
ldap_uri = ldap://ldap.example.com
ldap_search_base = dc=example,dc=com
ldap_default_bind_dn = cn=vpn-service,ou=services,dc=example,dc=com
ldap_default_authtok_type = password
ldap_default_authtok = SecretPassword
ldap_tls_reqcert = demand
ldap_tls_cacert = /etc/openvpn/ca.crt
cache_credentials = true
```

### 2. OpenVPN + LDAP через auth-user-pass-verify

**Скрипт аутентификации:**

```bash
#!/bin/bash
# /etc/openvpn/auth-ldap.sh
LDAP_URI="ldap://ldap.example.com"
BIND_DN="cn=vpn-service,ou=services,dc=example,dc=com"
BIND_PW="SecretPassword"
BASE_DN="dc=example,dc=com"

USERNAME="$1"
PASSWORD="$2"

# LDAP bind с credentials пользователя
ldapsearch -x -H "$LDAP_URI" \
  -D "uid=$USERNAME,ou=people,$BASE_DN" \
  -w "$PASSWORD" \
  -b "ou=people,$BASE_DN" \
  "(uid=$USERNAME)" dn 2>/dev/null | grep -q "^dn:"

if [ $? -eq 0 ]; then
  exit 0  # Аутентификация успешна
else
  exit 1  # Аутентификация провалилась
fi
```

```bash
# /etc/openvpn/server.conf
auth-user-pass-verify /etc/openvpn/auth-ldap.sh via-env
# Или через файл:
# auth-user-pass-verify /etc/openvpn/auth-ldap.sh via-file
```

### 3. FreeRADIUS + LDAP

**Установка FreeRADIUS:**

```bash
# RHEL/Rocky/AlmaLinux
sudo dnf install freeradius freeradius-ldap -y

# Debian/Ubuntu
sudo apt install freeradius freeradius-ldap -y
```

**Настройка LDAP-модуля:**

```bash
# /etc/freeradius/3.0/mods-available/ldap
ldap {
    server = "ldap://ldap.example.com"
    identity = "cn=radius-service,ou=services,dc=example,dc=com"
    password = "SecretPassword"
    base_dn = "dc=example,dc=com"

    sasl {
    }

    update {
        control:Password-With-Header += 'userPassword'
        control:NT-Password := 'sambaNTPassword'
        reply:Tunnel-Type := 'VLAN'
        reply:Tunnel-Medium-Type := 'IEEE-802'
        reply:Tunnel-Private-Group-ID := 'vlanID'
    }

    user {
        base_dn = "ou=people,${..base_dn}"
        filter = "(uid=%{%{Stripped-User-Name}:-%{User-Name}})"
    }

    group {
        base_dn = "ou=groups,${..base_dn}"
        filter = "(objectClass=posixGroup)"
        membership_filter = "(|(member=%{control:Ldap-UserDn})(memberUid=%{%{Stripped-User-Name}:-%{User-Name}}))"
    }

    options {
        chase_referrals = yes
        rebind = yes
        res_timeout = 10
        srv_timelimit = 3
        net_timeout = 1
        idle = 60
        probes = 3
        interval = 3
    }

    pool {
        start = ${thread[pool].start_servers}
        min = ${thread[pool].min_spare_servers}
        max = ${thread[pool].max_servers}
        spare = ${thread[pool].max_spare_servers}
        uses = 0
        retry_delay = 30
        lifetime = 0
        idle_timeout = 60
    }
}
```

**Активация LDAP-модуля:**

```bash
sudo ln -s /etc/freeradius/3.0/mods-available/ldap \
  /etc/freeradius/3.0/mods-enabled/ldap
```

**Настройка sites:**

```bash
# /etc/freeradius/3.0/sites-available/default
server default {
    listen {
        type = auth
        ipaddr = *
        port = 1812
    }
    listen {
        type = acct
        ipaddr = *
        port = 1813
    }

    authorize {
        preprocess
        chap
        mschap
        suffix
        eap {
            ok = return
        }
        ldap
        pap
    }

    authenticate {
        Auth-Type PAP {
            pap
        }
        Auth-Type CHAP {
            chap
        }
        Auth-Type MS-CHAP {
            mschap
        }
        eap
        ldap
    }
}
```

**Тестирование:**

```bash
# Запуск в debug-режиме
sudo freeradius -X

# Тест с radtest
radtest username password localhost 0 testing123

# Проверка LDAP-подключения
sudo radtest username password ldap.example.com 0 testing123
```

### 4. FreeRADIUS + LDAP для Wi-Fi 802.1X

**Настройка EAP-PEAP:**

```bash
# /etc/freeradius/3.0/mods-available/eap
eap {
    default_eap_type = peap

    peap {
        default_eap_type = mschapv2
    }

    mschapv2 {
        # Используется для аутентификации через AD/LDAP
    }
}
```

**Настройка VLAN из LDAP:**

```bash
# В LDAP: добавление атрибута vlanID к пользователю
dn: uid=jdoe,ou=people,dc=example,dc=com
changetype: modify
add: vlanID
vlanID: 100
```

### 5. WireGuard + LDAP (через WG-Easy)

WG-Easy предоставляет веб-интерфейс с LDAP-аутентификацией:

```yaml
# docker-compose.yml
services:
  wg-easy:
    image: ghcr.io/wg-easy/wg-easy
    environment:
      - WG_HOST=vpn.example.com
      - PASSWORD_HASH=$2a$12$...
      - LDAP_SERVER_URL=ldap://ldap.example.com
      - LDAP_BIND_DN=cn=wg-service,ou=services,dc=example,dc=com
      - LDAP_BIND_PASSWORD=SecretPassword
      - LDAP_SEARCH_BASE=ou=people,dc=example,dc=com
      - LDAP_SEARCH_FILTER=(uid=%u)
      - LDAP_GROUP_SEARCH_BASE=ou=groups,dc=example,dc=com
      - LDAP_GROUP_SEARCH_FILTER=(&(memberUid=%u)(cn=vpn-users))
    ports:
      - "51820:51820/udp"
      - "51821:51821/tcp"
    volumes:
      - ./wg-data:/etc/wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.ip_forward=1
```

## Дополнительная информация

### Чеклист интеграции VPN + LDAP

```text
[ ] LDAP-сервисный аккаунт создан (cn=vpn-service,ou=services)
[ ] TLS настроен для LDAP-соединения
[ ] Группа для VPN-пользователей создана
[ ] PAM-конфигурация проверена (pamtester)
[ ] Файрвол открыт для VPN-порта
[ ] DNS разрешает имя LDAP-сервера
[ ] Сертификаты VPN-сервера настроены
```

### Частые ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `pam_sss.so: No such file` | SSSD не установлен | `dnf install sssd` |
| `LDAP: Can't contact LDAP server` | Файрвол или DNS | Проверьте `nc -zv ldap 389` |
| `Invalid credentials` | Неверный Bind DN | Проверьте DN через `ldapwhoami` |
| `Access denied` | Пользователь не в группе VPN | Проверьте membership в LDAP |
| `RADIUS: No reply` | FreeRADIUS не запущен | `systemctl status radiusd` |

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** — терминология
- **[LDAP Security Hardening](./ldap_security.md)** — настройка безопасности
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
