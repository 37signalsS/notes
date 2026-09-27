# Аутентификация и SSO/MFA для VPN

## Определения

**SSO (Single Sign-On)** — единый вход, при котором доступ к VPN предоставляется через корпоративный identity-провайдер (Keycloak, Authentik, Azure AD-like) по протоколам OIDC/SAML. **MFA/2FA (Multi-Factor / Two-Factor Authentication)** — проверка второй фактора (TOTP, аппаратный ключ) поверх логина. **OIDC (OpenID Connect)** — протокол аутентификации поверх OAuth 2.0. **SAML** — протокол обмена assertions между SP и IdP. **LDAP/RADIUS** — бэкенды учётных записей и их доставка сетевому оборудованию/сервисам.

## Основные концепции

### Уровни аутентификации в VPN

| Технология | Способ аутентификации | SSO/MFA | Комментарий |
|------------|----------------------|---------|-------------|
| WireGuard (нативно) | Статические публичные ключи | Нет | Ключ = identity, пользовательского слоя нет |
| OpenVPN | Сертификаты PKI, user/pass, LDAP, TOTP-плагины | Частично | LDAP/RADIUS и OTP плагины |
| IPsec IKEv2 (strongSwan) | Сертификаты, EAP/RADIUS | Частично | EAP для remote access |
| WireGuard + Headscale/Tailscale | Узел присоединяется через OIDC-логин | Да (OIDC) | Контроллер поверх WireGuard |
| Внешние mesh-решения (Netbird, Netmaker) | OIDC/Google/Гитлаб | Да | Собственные серверы-контроллеры |

### Почему для WireGuard «MFA» — это не про сам WireGuard

WireGuard специально не имеет слоя пользователей/паролей — аутентификация криптографическая: владение приватным ключом. «Включить MFA для WireGuard напрямую» нельзя; доступные пути:

1. **Внешний контроллер** с привязкой к OIDC (Headscale, Netbird, Netmaker) — узел не получает ключ, пока пользователь не прошёл login + MFA у IdP.
2. **Дополнительный шлюз/portal** (reverse proxy + OIDC) перед доступом к ресурсам, куда ведёт VPN.
3. **Процедурно**: VPN только с доверенных управляемых устройств (MDM), а пользователи авторизуются в приложениях через SSO.

Это стандартный вопрос на собеседовании: «как внедрить SSO/MFA для WireGuard?» Внешний контроллер с OIDC — основной корректный ответ.

## Практические сценарии

### 1. SSO для WireGuard через Headscale (OIDC)

Headscale — самодостаточный open-source контроллер поверх протокола Tailscale (развёртывание и команды — [Vpn/tailscale.md](./tailscale.md)).

1. Зарегистрируйте OIDC-приложение у IdP (Keycloak/Authentik) с redirect на `https://<headscale>/oidc/callback`.
2. Укажите параметры в `/etc/headscale/config.yaml`:

```yaml
oidc:
  issuer: https://idp.example.com/realms/corp
  client_id: headscale
  client_secret: <secret>
  scope: ["openid", "profile", "email"]
```

3. Клиент логинится через IdP (включая MFA на стороне IdP):

```bash
sudo tailscale up --login-server https://headscale.example.com
```

После логина Headscale выдаёт узлу ключ WireGuard — без входа в IdP узел не получится присоединить. Отзыв — удалением узла: `headscale nodes delete --identifier <ID>`.

### 2. MFA для OpenVPN (LDAP + TOTP)

Классический OpenVPN-сервер поддерживает `auth-user-pass` при плагине `openvpn-auth-ldap` и `openvpn-auth-otp` (TOTP). Пример ключевых директив `server.conf`:

```conf
plugin /usr/lib/openvpn/openvpn-plugin-auth-pam.so openvpn
plugin /usr/lib/openvpn/openvpn-auth-otp.so totp
script-security 3
auth-user-pass-verify /usr/local/bin/verify_otp.py via-file
verify-client-cert none
```

Схема: OpenVPN → LDAP (пароль) → OTP-файл (TOTP). Реальная интеграция и альтернативы — в [Remote Access VPN (LDAP/RADIUS)](../Networking/Tunnels/remote_access_vpn.md) и [LDAP/RADIUS для VPN](../LDAP/ldap_vpn_radius.md).

### 3. RADIUS для сетевых VPN (OpenVPN и IKEv2 с EAP)

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

**IKEv2 (strongSwan) → RADIUS по EAP.** Для EAP-TLS/EAP-MSCAPEV в strongSwan RADIUS — основной путь:

```text
# /etc/ipsec.conf (fragment)
conn %default
  keyexchange = ikev2
  rightauth = eap-radius
  rightsendcert = never
  eap_identity = %identity
```

Обмен `EAP-Request/Response` шлюз проксирует в RADIUS-сервер (`Access-Request` + `User-Name`, `EAP-Message`), ответ содержит `Access-Accept` (опционально — `MS-CHAP-MPPE-Keys` для сессии). Радиусная часть, SSO-цепочки и альтернативы описаны в [LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md), EAP-профили IKEv2 и настройка strongSwan — в [IPsec: установка и конфигурация](../Networking/Tunnels/ipsec/ipsec_linux_setup.md) и [ipsec.md](../Networking/Tunnels/ipsec/ipsec.md).

**Аудит каждого входа.** Учёт того, кто именно подключился (независимо от протокола) ведётся по RADIUS Accounting и логам шлюза — см. [vpn-session-audit.md](./vpn-session-audit.md); это отдельная запись в регламенте расследований.

### 4. SSO/MFA на прикладном уровне (дополнительный барьер)

Если VPN уже выдаёт доступ к интернет-портам, поверх можно поставить reverse proxy с OIDC (nginx/oidc, авторизация через Authentik): [Authentik SSO-интеграция](../Security/Tools/Wazuh/authentik-sso-integration.md). Так MFA появляется даже для сервисов без своей аутентификации.

### 5. Сравнение вариантов: что выбрать

| Сценарий | Рекомендация |
|----------|--------------|
| Remote access до 50-200 человек, нужен SSO | Headscale + OIDC (или Tailscale SaaS) |
| Регламентный контур, LDAP уже есть | OpenVPN + LDAP; добавить TOTP плагином |
| Аппаратные концентраторы / legacy | RADIUS-концентратор (см. LDAP-документ) |
| Барьер поверх уже работающего VPN | nginx + OIDC перед внутренними сервисами |

## Дополнительная информация

- **[Remote Access VPN — сравнение технологий](../Networking/Tunnels/remote_access_vpn.md)** — выбор между WireGuard, OpenVPN, IPsec
- **[Vpn/tailscale.md](./tailscale.md)** — Headscale: OIDC, ACL, управление узлами
- **[LDAP и RADIUS для VPN](../LDAP/ldap_vpn_radius.md)** — RADIUS, 802.1X, интеграция с корпоративным LDAP
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — журналирование кто когда подключался (RADIUS accounting, логи)