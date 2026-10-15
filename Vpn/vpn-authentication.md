# Аутентификация и SSO/MFA для VPN

**Актуально для:** OpenVPN 2.6.x / strongSwan 6.x / Headscale 0.2x

## Определения

**Аутентификация (Authentication)** — установление подлинности субъекта; отвечает на вопрос «кто вы». В VPN субъектов может быть два: **устройство/узел** (device identity) и **пользователь** (user identity) — см. [Аутентификация против Авторизации](../Security/Concepts/authentication_vs_authorization.md).

**Авторизация (Authorization)** — определение того, что субъекту разрешено после успешной аутентификации: маршруты, подсети, внутренние ресурсы. В VPN выполняется через `AllowedIPs`/ACL/Policy, а не через аутентификацию.

**SSO (Single Sign-On)** — единый вход, при котором доступ к VPN предоставляется через корпоративный identity-провайдер (Keycloak, Authentik, Zitadel, Entra ID) по протоколам OIDC/SAML. Пользователь аутентифицируется один раз у IdP, а VPN-контроллер доверяет выданному токену/assertion.

**MFA / 2FA (Multi-Factor / Two-Factor Authentication)** — проверка двух и более независимых факторов из разных категорий (знание, владение, сущность). Теория, категории факторов, TOTP/HOTP и WebAuthn — [MFA и TOTP](../Security/Concepts/mfa_totp.md).

**OIDC (OpenID Connect)** — протокол аутентификации поверх OAuth 2.0; результат — ID Token (JWT) с утверждениями о пользователе. **SAML** — XML-протокол обмена assertions между SP (VPN) и IdP. Детали протоколов — [HTTP-аутентификация](../Networking/Protocols/HTTP/http_authentication.md).

**LDAP** — протокол доступа к каталогу учётных записей (проверка и хранение пользователей). **RADIUS** — протокол AAA (аутентификация, авторизация, учёт) для сетевого доступа. **PAM (Pluggable Authentication Modules)** — модульный фреймворк аутентификации в Linux, через который приложение (OpenVPN) связано со способом проверки (LDAP, OTP).

**EAP (Extensible Authentication Protocol)** — фреймворк аутентификации, используемый в 802.1X и IKEv2 remote access (EAP-TLS, EAP-MSCHAPv2, EAP-TTLS). Механизмы и обмен — [IPsec](../Networking/Tunnels/ipsec/ipsec.md) и [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md).

**PKI (Public Key Infrastructure)** — инфраструктура открытых ключей: CA выдаёт сертификаты, проверка подписи и отзыв через CRL/OCSP. Теория — [PKI — инфраструктура открытых ключей](../Security/Concepts/pki_overview.md).

**IdP (Identity Provider)** — сторона, аутентифицирующая пользователя (Keycloak, Authentik). **SP (Service Provider)** — сторона, доверяющая IdP и предоставляющая доступ (VPN-контроллер, reverse proxy).

---

## Основные концепции

### Два слоя идентичности в VPN

Ключевое различие, из которого следует всё остальное: в VPN независимо существуют **идентичность узла** и **идентичность пользователя**, и разные технологии закрывают разные слои.

| Слой | Что доказывается | Чем выражается | Примеры технологий |
|------|------------------|----------------|--------------------|
| **Транспортный (узел/устройство)** | Владение ключом или сертификатом | Приватный ключ, X.509-сертификат | WireGuard, Nebula PKI, OpenVPN PKI, IPsec |
| **Пользовательский** | «Кто за этим устройством» | Логин/пароль, сертификат пользователя, OIDC ID Token | OpenVPN `auth-user-pass`, IKEv2 EAP, mesh-контроллеры |

WireGuard закрывает только транспортный слой: владение приватным ключом и есть аутентификация, пользовательского слоя в протоколе нет. OpenVPN и IPsec могут аутентифицировать и узел (сертификат), и пользователя (логин/пароль или EAP), поэтому именно на них строятся классические корпоративные контуры с SSO/MFA.

**Следствие для MFA:** «второй фактор» осмыслен только там, где есть пользовательский слой. Два ключа WireGuard или сертификат + PresharedKey — это два секрета одной категории (владение), то есть не MFA. Сертификат клиента (**владение**) плюс `auth-user-pass` (**знание**) — уже два разных фактора.

### Где происходит проверка подлинности

Место проверки определяет, какие механизмы доступны:

```text
Вариант 1 (локально/каталог):
  [ VPN-клиент ] → [ VPN-сервер ] → [ PAM / LDAP / FreeRADIUS ] → [ каталог ]

Вариант 2 (федерация, IdP):
  [ VPN-клиент (браузер) ] → [ IdP: OIDC/SAML + MFA ] → [ VPN-контроллер доверяет токену ]

Вариант 3 (сертификаты):
  [ VPN-клиент ] → [ проверка цепочки X.509 + CRL/OCSP ] → [ доступ ]
```

Выбор места проверки — это выбор между **локальной интеграцией** (PAM/LDAP/RADIUS, MFA через OTP-плагин) и **федерацией** (IdP отвечает за пароли, MFA, политики, а VPN доверяет его решению). Федеративный путь предпочтителен, когда корпоративный IdP уже существует: MFA, блокировка уволенных и аудит входа централизуются в одном месте.

### Уровни аутентификации по технологиям

| Технология | Транспортная аутентификация | Пользовательский слой | SSO/MFA | Комментарий |
|------------|------------------------------|------------------------|---------|-------------|
| WireGuard (нативно) | Статические публичные ключи | Нет | Нет | Ключ = identity, пользовательского слоя нет |
| OpenVPN | PKI (сертификат) и/или `auth-user-pass` | Да | Частично | LDAP/RADIUS/PAM и OTP-плагины; OIDC — внешним плагином |
| IPsec IKEv2 (strongSwan) | PKI, PSK | Да (EAP) | Частично | EAP-TLS/EAP-MSCHAPv2 через `eap-radius` |
| WireGuard + Headscale/Tailscale | Ключи WireGuard | Узел привязан к OIDC-пользователю | Да (OIDC, MFA на IdP) | Контроллер поверх WireGuard |
| Внешние mesh-решения (Netbird, Netmaker) | Ключи WireGuard | Узел + JWT пользователя | Да | Собственные серверы-контроллеры, SSO из коробки |

Обзор mesh-решений и их позиционирование — [mesh-vpn-overview.md](./mesh-vpn-overview.md); выбор технологии remote access — [Remote Access VPN](../Networking/Tunnels/remote_access_vpn.md).

### Почему для WireGuard «MFA» — это не про сам WireGuard

WireGuard специально не имеет слоя пользователей/паролей — аутентификация криптографическая: владение приватным ключом. «Включить MFA для WireGuard напрямую» нельзя; доступные пути:

1. **Внешний контроллер** с привязкой к OIDC (Headscale, Netbird, Netmaker) — узел не получает ключ, пока пользователь не прошёл login + MFA у IdP.
2. **Дополнительный шлюз/portal** (reverse proxy + OIDC) перед доступом к ресурсам, куда ведёт VPN.
3. **Процедурно**: VPN только с доверенных управляемых устройств (MDM), а пользователи авторизуются в приложениях через SSO.

Это стандартный вопрос на собеседовании: «как внедрить SSO/MFA для WireGuard?» Внешний контроллер с OIDC — основной корректный ответ.

### Отзыв доступа (Revocation)

Аутентификация без работающего отзыва неполна: уволенный сотрудник с действующим ключом остаётся внутри сети.

| Что отзывается | Механизм | Технология |
|----------------|----------|------------|
| Сертификат | CRL или OCSP | OpenVPN PKI, IPsec, Nebula (blocklist по отпечатку) |
| Ключ WireGuard | Удаление пира из конфигурации | `wg set ... peer ... remove` / контроллер |
| Сессия OIDC | Истечение узла (node expiry) или logout в IdP | Headscale, Netbird, Tailscale |
| Учётная запись | Блокировка в каталоге/IdP | LDAP, Keycloak, Authentik |

Привязка `pubkey` к владельцу и инвентарь ключей — [wireguard-key-management.md](./wireguard-key-management.md); аудит входов и сессий — [vpn-session-audit.md](./vpn-session-audit.md).

---

## Практические сценарии

### 1. SSO для WireGuard через Headscale (OIDC)

Headscale — самодостаточный open-source контроллер поверх протокола Tailscale (развёртывание и команды — [Vpn/tailscale.md](./tailscale.md)). Аутентификация узла выполняется через OIDC-логин, поэтому MFA (TOTP, WebAuthn, push) настраивается **на стороне IdP** и автоматически распространяется на VPN.

1. Зарегистрируйте OIDC-приложение у IdP (Keycloak/Authentik/Zitadel) с redirect на `https://<headscale>/oidc/callback`.
2. Укажите параметры в `/etc/headscale/config.yaml`. Помимо базовых ключей полезны фильтры доступа и срок жизни узла:

```yaml
oidc:
  issuer: https://idp.example.com/realms/corp
  client_id: headscale
  client_secret: <secret>
  scope: ["openid", "profile", "email", "groups"]
  # Разрешить только членов группы IdP (фильтр по группам/домену/пользователям)
  allowed_groups:
    - "vpn-users"
  # Обязательно проверять email_verified (значение по умолчанию — true)
  email_verified_required: true

# Срок, после которого узел обязан пройти re-auth (по умолчанию 0 — бессрочно)
node:
  expiry: 30d
```

3. Клиент логинится через IdP (включая MFA на стороне IdP):

```bash
sudo tailscale up --login-server https://headscale.example.com
```

После логина Headscale выдаёт узлу ключ WireGuard — без входа в IdP узел не получится присоединить. Отзыв — удалением узла (`headscale nodes delete --identifier <ID>`) либо принудительным истечением (`headscale nodes expire --identifier <ID>`), после чего требуется повторный OIDC-вход.

**MFA на каждом переподключении.** Headscale не требует повторной аутентификации, пока узел не истёк и остаётся зарегистрированным. Если регламент требует 2FA при каждом входе, комбинируют короткий `node.expiry` и/или принудительное истечение узла при длительном отключении (скрипт по `headscale nodes list -o json-line`). Полностью штатной опции «expire on disconnect» в Headscale нет — это отдельные обёртки.

### 2. MFA для OpenVPN (LDAP + TOTP)

OpenVPN Community не имеет встроенного TOTP; второй фактор добавляется связкой **двух плагинов**, работающих по challenge/response:

- `openvpn-auth-ldap.so` (`openvpn-auth-ldap`) — проверяет пароль по LDAP/AD;
- `openvpn-otp.so` (`openvpn-otp`) — проверяет TOTP/HOTP по файлу секретов.

Оба плагина подключаются одновременно: OpenVPN требует, чтобы **прошли оба**, а не «один из двух». Клиент получает challenge и вводит PIN + OTP. Пример ключевых директив `server.conf`:

```conf
# /etc/openvpn/server.conf — два фактора: LDAP (пароль) + OTP
plugin /usr/lib/openvpn/openvpn-auth-ldap.so /etc/openvpn/auth-ldap.conf
plugin "/usr/lib64/openvpn/plugins/openvpn-otp.so" "password_is_cr=1 otp_secrets=/etc/openvpn/otp-secrets"
```

Плагин OTP распознаёт результат challenge/response только при `password_is_cr=1`; на стороне клиента это включается директивой `static-challenge`:

```conf
# client.ovpn — запрос второго фактора
auth-user-pass
auth-nocache
static-challenge "Enter Google Authenticator Token" 1
```

Файл секретов `otp-secrets` использует формат ppp-otp (`user server totp:sha1:base32:<K>:<pin>:x *`). Проверка кода на сервере — `oathtool --totp -b <BASE32_SECRET>`. Секреты TOTP, привязка `~/.google_authenticator` и защита от подбора — [MFA и TOTP](../Security/Concepts/mfa_totp.md).

**Альтернатива через PAM.** Вместо отдельного OTP-плагина можно использовать PAM: `openvpn-plugin-auth-pam.so` + `pam_google_authenticator.so`. Тогда OpenVPN делегирует проверку стеку PAM (LDAP через `pam_sss.so` и TOTP через `pam_google_authenticator.so`), а `server.conf` содержит:

```conf
plugin /usr/lib/openvpn/openvpn-plugin-auth-pam.so openvpn
verify-client-cert none
```

`verify-client-cert none` (в OpenVPN ≤2.3 — `client-cert-not-required`) отключает обязательный клиентский сертификат; вместе с `username-as-common-name` это перекладывает идентичность на связку логин/пароль. Синтаксис PAM и порядок модулей — [Аутентификация против Авторизации](../Security/Concepts/authentication_vs_authorization.md), полная интеграция LDAP — [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md).

### 3. SSO (OIDC) для OpenVPN через openvpn-auth-oauth2

Современный способ подключить OpenVPN к корпоративному IdP без сертификатов на клиентах — внешний менеджер `openvpn-auth-oauth2`, который работает с OpenVPN через management-интерфейс и выполняет полный OIDC-поток. Поддерживаются Keycloak, Authentik, Zitadel, Entra ID и любые OIDC-провайдеры. Пользователь аутентифицируется в браузере у IdP (с MFA), а OpenVPN доверяет результату.

Ключевые директивы сервера:

```conf
# /etc/openvpn/server.conf — делегирование аутентификации OIDC-плагину
management /run/openvpn/server.sock unix /etc/openvpn/password.txt
management-client-auth
auth-user-pass-optional

# Токен сессии, чтобы клиенты не вводили пароль повторно при переподключении
# lifetime должен совпадать с временем жизни refresh token у плагина
auth-gen-token 28800 external-auth
```

`auth-user-pass-optional` позволяет клиенту не передавать пароль OpenVPN (аутентификация происходит у IdP). `auth-gen-token ... external-auth` выдаёт возобновляемый session-токен для мобильных устройств. Требование к Common Name и сверка с `sub` из ID Token настраиваются на стороне плагина.

### 4. RADIUS для сетевых VPN (OpenVPN и IKEv2 с EAP)

Для VPN-аппаратных концентраторов и IPsec (EAP/TLS + RADIUS) применяется классическая связка: шлюз → RADIUS-сервер → LDAP. Подробное описание протоколов и настройка — [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md). WireGuard нативно EAP/RADIUS не поддерживает — те же внешние контроллеры или шлюзы промежуточного слоя.

**OpenVPN → FreeRADIUS → LDAP (конкретика).** OpenVPN сам LDAP не ходит — он передаёт логин/пароль в RADIUS как NAS:

```conf
# /etc/openvpn/server.conf — делегирование аутентификации
plugin /usr/lib/x86_64-linux-gnu/openvpn/plugins/openvpn-plugin-auth-pam.so radius
# или вариант через radius-client:
# radiusclient-radius.conf  ← radiusclient.conf с server = 10.0.0.5
```

```ini
# /etc/freeradius/3.0/clients.conf — NAS-запись для OpenVPN-сервера
client openvpn {
    ipaddr = 203.0.113.10
    secret = shared_secret_with_openvpn
    require_message_authenticator = no
}
```

```text
# users-фрагмент или LDAP-модуль FreeRADIUS (ldap { server = ldap.example.com })
DEFAULT     Auth-Type = PAP
```

Схема: OpenVPN → RADIUS (PAP/CHAP) → FreeRADIUS → LDAP (или локальный `users`), пароль и TOTP приходят в `radius` (`Access-Request`). Полное описание протоколов, 802.1X и всех кейсов — в [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md).

**IKEv2 (strongSwan) → RADIUS по EAP.** В strongSwan 6.x аутентификацию клиентов делегируют RADIUS-серверу плагином `eap-radius`: он не реализует EAP-метод сам, а транслирует EAP-обмен между клиентом и RADIUS-бэкендом (`Access-Request`/`Access-Accept`). Современный синтаксис — в `swanctl.conf`:

```text
# /etc/swanctl/conf.d/remote-access.conf
connections {
    remote-access {
        version = 2
        remote {
            auth = eap-radius
            eap_id = %any
        }
        children {
            remote-tunnel { local_ts = 0.0.0.0/0 }
        }
    }
}
```

```text
# /etc/strongswan.conf — бэкенд RADIUS для eap-radius
charon {
  plugins {
    eap-radius {
      servers {
        server-a {
          address = 203.0.113.20
          secret = shared_secret_with_radius
          nas_identifier = ipsec-gateway
        }
      }
    }
  }
}
```

Порт RADIUS по умолчанию — 1812/UDP (auth) и 1813/UDP (acct). Радиусная часть, SSO-цепочки и альтернативы описаны в [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md), EAP-профили IKEv2 (EAP-TLS, EAP-MSCHAPv2) и настройка strongSwan — в [IPsec: установка и конфигурация](../Networking/Tunnels/ipsec/ipsec_linux_setup.md) и [ipsec.md](../Networking/Tunnels/ipsec/ipsec.md).

**Аудит каждого входа.** Учёт того, кто именно подключился (независимо от протокола) ведётся по RADIUS Accounting и логам шлюза — см. [vpn-session-audit.md](./vpn-session-audit.md); это отдельная запись в регламенте расследований.

### 5. Сертификатная аутентификация (PKI) и отзыв

Для OpenVPN и IPsec «пользователь» часто выражается клиентским сертификатом, подписанным CA. Это закрывает транспортный слой и, если у каждого пользователя свой сертификат, — пользовательский (по CN).

- **OpenVPN PKI:** сервер проверяет цепочку клиентского сертификата. Для отзыва используется **CRL** (`crl-verify <file>` в `server.conf`) или динамический CRL; CN сертификата служит ключом для `client-config-dir` и статических IP.
- **IKEv2 (strongSwan):** сертификаты клиентов проверяются по CA; отзыв — CRL или OCSP (`leftauth=pubkey`, `remote { auth = pubkey; cacerts = ca.crt }`), детали — [ipsec.md](../Networking/Tunnels/ipsec/ipsec.md).
- **Nebula:** собственный PKI, отзыв — blocklist по отпечатку сертификата или перевыпуск CA ([mesh-vpn-overview.md](./mesh-vpn-overview.md)).

Сертификат удобно комбинировать с паролем: цепочка «certificate (владение) + password (знание)» даёт настоящий второй фактор без внешнего OTP. Теория PKI, сроки жизни и отзыв — [PKI — инфраструктура открытых ключей](../Security/Concepts/pki_overview.md).

### 6. SSO/MFA на прикладном уровне (дополнительный барьер)

Если VPN уже выдаёт доступ к интернет-портам, поверх можно поставить reverse proxy с OIDC (nginx/oidc, авторизация через Authentik): [Authentik SSO-интеграция](../Security/Tools/Wazuh/authentik-sso-integration.md). Так MFA появляется даже для сервисов без своей аутентификации и не зависит от того, как аутентифицируется сам туннель. Тот же принцип реализуют встроенные reverse proxy Netbird и Netmaker.

### 7. Сравнение вариантов: что выбрать

| Сценарий | Рекомендация |
|----------|--------------|
| Remote access до 50-200 человек, нужен SSO | Headscale + OIDC (или Tailscale SaaS) |
| Регламентный контур, LDAP уже есть | OpenVPN + LDAP; добавить TOTP плагином |
| Есть корпоративный IdP (Keycloak/Authentik) | Headscale либо OpenVPN + `openvpn-auth-oauth2` |
| Аппаратные концентраторы / legacy | RADIUS-концентратор (см. LDAP-документ) |
| Нужен сертификат пользователя и отзыв | OpenVPN PKI или IKEv2 EAP-TLS (+ CRL/OCSP) |
| Барьер поверх уже работающего VPN | nginx + OIDC перед внутренними сервисами |

---

## Диагностика и типичные ошибки

| Симптом | Причина | Диагностика / решение |
|---------|---------|-----------------------|
| Узел в Headscale не присоединяется, редирект OIDC зацикливается | Несовпадение `issuer`, `redirect_uri` или часов | `journalctl -u headscale`; сверить `issuer` с `/.well-known/openid-configuration`; синхронизировать NTP |
| OIDC-логин проходит, но узел не добавляется | Не проходит фильтр `allowed_groups`/`allowed_domains` | Проверить claim `groups` в ID Token; для Keycloak добавить client scope `groups` |
| TOTP не принимается в OpenVPN | Рассинхронизация часов или незадан `password_is_cr=1` | Сверить время (`chronyc tracking`); проверить `otp_secrets` и формат строки секрета |
| `AUTH_FAILED`, пароль верный | Не совпали оба плагина (LDAP+OTP) или неверный PIN+OTP | Логи `openvpn` с `verb 3`; проверить `password_is_cr` и `PasswordIsCR` |
| OIDC-плагин OpenVPN не подключается | Не настроен management-сокет | Проверить `management`, `management-client-auth`, путь `/etc/openvpn/password.txt` |
| IKEv2 не отдаёт сессию | Смешаны `eap-radius` и требования клиентского сертификата | Убрать `remote { cacerts = ... }`, добавить `send_certreq = no`; проверить `nas_identifier` и `secret` |
| RADIUS `Access-Reject` при верном пароле | Бэкенд LDAP не подключён или неверный `Auth-Type` | `freeradius -X`; проверить ldap-модуль и `DEFAULT Auth-Type = PAP` |
| CRL не отзывает сертификат | Сервер не перечитал CRL или истёк срок самого CRL | Проверить `crl-verify`; обновить CRL и перезапустить сервис |

Общие сетевые и MTU-проблемы VPN — [VPN Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md); аудит и расследования — [vpn-session-audit.md](./vpn-session-audit.md).

---

## Лучшие практики

1. **MFA на IdP, а не в VPN.** Централизуйте факторы в Keycloak/Authentik: WebAuthn предпочтительнее TOTP, TOTP — SMS. Тогда одна политика закрывает VPN и остальные сервисы.
2. **Разделяйте слои.** Для людей — пользовательская аутентификация (OIDC/EAP), для сервисов и IaC — отдельные machine-идентичности (setup/enrollment keys, tagged-узлы) с коротким TTL.
3. **Не считайте два секрета одной категории MFA.** Ключ + PSK, два WireGuard-ключа — это не мультифактор.
4. **Ограничивайте вход фильтрами групп.** `allowed_groups`/`allowed_domains` в Headscale и group-sync в Netbird/Netmaker исключают посторонние учётные записи IdP.
5. **Настраивайте истечение сессий.** `node.expiry`, JWT peer expiration, `auth-gen-token` с ограниченным lifetime — окно, в котором скомпрометированный доступ опасен, должно быть конечно.
6. **Держите рабочий отзыв.** CRL/OCSP для сертификатов, удаление пиров, блокировка в IdP; процедура offboarding должна закрывать все слои сразу.
7. **Резервный вход (break-glass).** Оставляйте локального администратора/ключ для аварийного доступа при падении IdP или RADIUS. Детали политики — [Аутентификация против Авторизации](../Security/Concepts/authentication_vs_authorization.md).
8. **Синхронизируйте время.** TOTP, SAML assertion и JWT-валидация критичны к расхождению часов; используйте NTP/Chrony на шлюзе и IdP.
9. **Логируйте без секретов.** Фиксируйте факты входа/отказа и `jti`/`session_id`, но не токены и пароли; направляйте в SIEM ([vpn-session-audit.md](./vpn-session-audit.md)).

---

## Граничные случаи и ограничения

- **WireGuard без контроллера** не умеет пользовательскую аутентификацию вообще — SSO требует внешнего слоя (Headscale/Netbird/portal).
- **Community OpenVPN и SAML.** Нативного SAML в Community-сборке нет; SSO реализуется OIDC-плагином (`openvpn-auth-oauth2`) либо через management/скрипты. Готовый SAML/SSO из коробки — в коммерческих сборках.
- **Дефолт `email_verified_required: true`.** Headscale отвергнет OIDC-вход, если IdP не отдаёт `email_verified: true`.
- **`verify-client-cert none`** снижает стойкость транспорта до уровня логин/пароль; применяйте только вместе с IdP/OTP и надёжным TLS.
- **Отзыв токена ≠ отзыв сессии.** Logout в IdP не разрывает уже установленный туннель; для немедленного разрыва нужны короткий срок узла/сессии и повторная проверка на шлюзе.
- **`eap-radius` и клиентские сертификаты несовместимы** в одной конфигурации: либо сертификат, либо EAP/RADIUS.
- **Облачные IdP** (Entra ID и подобные) здесь не рассматриваются — вне области базы; принципы OIDC/SAML от выбора IdP не зависят.

---

## Дополнительная информация

- **[Remote Access VPN — сравнение технологий](../Networking/Tunnels/remote_access_vpn.md)** — выбор между WireGuard, OpenVPN, IPsec
- **[Vpn/tailscale.md](./tailscale.md)** — Headscale: OIDC, ACL, управление узлами, срок жизни ключей
- **[LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md)** — RADIUS, 802.1X, FreeRADIUS + LDAP, чек-лист
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — журналирование кто когда подключался (RADIUS accounting, логи)
- **[Vpn/mesh-vpn-overview.md](./mesh-vpn-overview.md)** — SSO/MFA в Netbird, Netmaker, Nebula
- **[MFA и TOTP](../Security/Concepts/mfa_totp.md)** — теория OTP, PAM, WebAuthn, диагностика
- **[HTTP-аутентификация](../Networking/Protocols/HTTP/http_authentication.md)** — OIDC, OAuth 2.1, SAML, JWT, mTLS
- **[Аутентификация против Авторизации](../Security/Concepts/authentication_vs_authorization.md)** — PAM, LDAP, сервисные аккаунты, break-glass
- **[PKI — инфраструктура открытых ключей](../Security/Concepts/pki_overview.md)** — сертификаты, CA, CRL/OCSP
- **[Authentik SSO-интеграция](../Security/Tools/Wazuh/authentik-sso-integration.md)** — практический пример IdP + SAML + 2FA
