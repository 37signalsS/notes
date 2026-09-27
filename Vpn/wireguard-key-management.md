# WireGuard: управление ключами и флотом клиентов

## Определения

**Provisioning** — процесс выдачи клиенту готовой конфигурации (ключ, адрес, AllowedIPs, Endpoint). **Ротация ключей** — плановая замена ключа устройства без длительного простоя. **Инвентаризация** — учёт всех выданных ключей, узлов и их владельцев. **PKI (Public Key Infrastructure)** — инфраструктура сертификатов (CA, Intermediate, сертификаты), которая в WireGuard отсутствует нативно, но может использоваться для управления доступом.

## Основные концепции

### Модель ключей и её следствия

- Каждое устройство имеет пару `private key + public key`; публичный ключ — это идентификатор пира (аналог user identity).
- На сервере пир выступает в роли «конфигурационной записи»: `[Peer] PublicKey = ... AllowedIPs = ...`.
- **Нет встроенного CA/сертификатов**: аутентифицируется только владение приватным ключом. Отзыв устройства = удаление его `[Peer]` с сервера.
- Приватный ключ не должен покидать устройство; для серверов/шлюзов он хранится только на доверенных узлах.
- Публичный ключ сам по себе секретом не является — его можно раздавать открыто.

### Что значит «управлять флотом» в продакшене

1. Генерация ключей и конфигов для новых клиентов (вручную — боль, на масштабе нужен скрипт/панель).
2. Ведение инвентаря: кто владелец ключа, какой адрес/подсеть, когда выдан.
3. Ротация при отзыве сотрудника, компрометации или по регламенту.
4. Резервное копирование приватных ключей серверов и конфигов.
5. Внедрение в процесс CI/CD и IaC (Ansible/Terraform — готовые подходы в [VPN Automation](../Networking/Tunnels/vpn_automation.md)).

### Варианты инструментов

| Подход | Плюсы | Минусы | Когда |
|--------|-------|--------|-------|
| Руками + скрипты + inventory в CSV/JSON | Прозрачно, минимум зависимостей | Много рутины, риск ошибок | < 20 клиентов |
| Ansible-роль | Воспроизводимость, в коде | Нужна инфраструктура Ansible | Server fleets, site-to-site |
| Web-панель (wg-easy, wg-ui) | Быстрая выдача клиентов, QR-коды | Панель = ещё одна атакаемая поверхность | Лаборатории, небольшие флоты |
| Vault + скрипты/шаблоны | Секреты централизованно, audit | Нет нативных dynamic secrets для WG | Регламентный security-контур |
| Headscale/Tailscale (OIDC, ACL) | Автоматизация, SSO, отзыв | Внешний контроллер | Remote access на масштабе |

Базовые команды генерации и ручной настройки — в [Vpn/wireguard.md](./wireguard.md). Здесь — решения для флота.

## Практические сценарии

### 1. Ротация ключа клиента без разрыва остальных сессий (серверная сторона)

На сервере новый ключ добавляется как отдельный `[Peer]`, старый удаляется только после переключения клиента:

```bash
# 1. Сгенерировать новый ключ на клиенте
wg genkey | tee /etc/wireguard/private.key.new | wg pubkey > /etc/wireguard/public.key.new

# 2. На сервере добавить новый пир (не трогая старый)
sudo wg set wg0 peer $(cat /etc/wireguard/public.key.new) allowed-ips 10.0.0.4/32

# 3. На клиенте применить новый конфиг и переподключиться
sudo wg-quick down wg0 && sudo wg-quick up wg0

# 4. На сервере убрать старый ключ
sudo wg set wg0 peer <old_pubkey> remove

# 5. Сохранить изменения в конфиг, чтобы они пережили перезагрузку
sudo wg-quick save wg0
```

Для плановой ротации флота ключ удобно генерировать заранее и раздавать через configuration management.

### 2. Скрипт быстрой выдачи клиента (inventory-файл)

Пример генератора конфигов для N клиентов с записью в CSV-инвентарь:

```bash
#!/bin/bash
# gen_client.sh <имя> <vpn_ip>
set -euo pipefail
NAME="$1"; IP="$2"
SERVER_PUB=$(sudo wg show wg0 public-key)
ROTATION='2026-09-01'

umask 077
mkdir -p /etc/wireguard/clients/"$NAME"
(
    wg genkey | tee /etc/wireguard/clients/"$NAME"/private.key
    wg pubkey < /etc/wireguard/clients/"$NAME"/private.key
) > /etc/wireguard/clients/"$NAME"/keys.txt
CLIENT_PRIV=$(sed -n 1p /etc/wireguard/clients/"$NAME"/keys.txt)
CLIENT_PUB=$(sed -n 2p /etc/wireguard/clients/"$NAME"/keys.txt)

# Клиентский конфиг
cat > /etc/wireguard/clients/"$NAME"/"$NAME.conf" <<EOF
[Interface]
PrivateKey = $CLIENT_PRIV
Address = $IP/32
DNS = 10.0.0.1

[Peer]
PublicKey = $SERVER_PUB
Endpoint = vpn.example.com:51820
AllowedIPs = 10.0.0.0/24
PersistentKeepalive = 25
EOF

# Добавить на сервер
sudo wg set wg0 peer "$CLIENT_PUB" allowed-ips "$IP"/32
sudo wg-quick save wg0

# Инвентарь
echo "$NAME,$IP,$CLIENT_PUB,$(date -u +%FT%TZ),$ROTATION" >> /etc/wireguard/inventory.csv
```

Инвентарь (`inventory.csv`) даёт ответ на вопросы аудита «кому принадлежит адрес» и «когда стоит провести ротацию». Ограничьте доступ:

```bash
sudo chmod 700 /etc/wireguard/clients
sudo chmod 600 /etc/wireguard/inventory.csv
```

### 3. Хранение конфигов и ключей серверов в Vault

Vault используется как централизованное хранилище секретов: приватные ключи серверов, списки пиров, инвентарь. Рендер конфига — через шаблонизацию при развёртывании (см. [Vault — обзор](../Vault/overview.md)).

**KV-запись серверного ключа:**

```bash
vault kv put secret/wireguard/server private.key="$(cat /etc/wireguard/server_private.key)"
```

**Пример чтения при генерации конфига (Ansible без нативных dynamic secrets)** — роль берёт ключи из Vault lookup-плагина и рендерит `wg0.conf` шаблоном. Такой подход даёт audit-лог и единую точку управления.

Ограничение: полноценных dynamic secrets (как для БД/SSH) для WireGuard нет, поэтому ротация остаётся процедурой, а не автоматическим процессом Vault.

### 4. Web-панель wg-easy (быстрый старт, Docker)

```yaml
# docker-compose.yml
services:
  wg-easy:
    image: weejewel/wg-easy:latest
    container_name: wg-easy
    environment:
      WG_HOST: vpn.example.com
      PASSWORD: ${WG_PASSWORD}
      WG_DEFAULT_ADDRESS: 10.8.0.x
    volumes:
      - ./data:/etc/wireguard
    ports:
      - "51820:51820/udp"
      - "51821:51821/tcp"
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv4.ip_forward=1
    restart: unless-stopped
```

После запуска веб-интерфейс на `8080... 51821` и выдаёт QR-коды для клиентов. В продакшене панель закрывают за reverse proxy с TLS и доступом по ролям (см. [VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md)), а её БД/директории конфигов резервируют так же, как ключи серверов.

### 5. Отзыв доступа и лифтоцикл

```bash
# Удалить пир на всех серверах контура
sudo wg set wg0 peer <pubkey> remove
sudo wg-quick save wg0

# Если клиент ходил через Headscale/Tailscale — отозвать узел
headscale nodes delete --identifier <ID>
```

Отзыв «сразу» не существует: WireGuard не разрывает уже установленные сессии, но после handshake-таймаута клиент с удалённым ключом не сможет переподключиться. Для удалённого немедленного разрыва добавьте в ACL/firewall фильтр по `AllowedIPs` этого клиента.

### 6. Сертификатный контур (PKI) поверх WireGuard

WireGuard не имеет встроенного CA, но для компаний с регламентными требованиями сертификаты добавляются **снаружи**: x509-сертификат клиента используется как дополнительный фактор и как идентификатор в audit-логах.

- **Инфраструктура**: отдельный корневой/промежуточный CA (двухуровневая схема) выписывает сертификаты только зарегистрированным устройствам. Схемы CA и выпуска — [openssl_ca: двухуровневый CA](../Security/Tools/openssl_ca/two_tier/service_certificate_management.md), [одноуровневый CA](../Security/Tools/openssl_ca/single_tier/service_certificate_management.md).
- **Связка**: на шлюзе WG не использует сертификаты напрямую (доступ контролируется владением приватным ключом). PKI закрывает вопрос «доказано ли, что за публичным ключом — сотрудник компании»: инвентарь (см. §2) связывает pubkey ↔ serial сертификата ↔ владелец.
- **Отзыв**: CCR/OCSP-статус сверяется при генерации конфига и при подключении (автоматизация через [Ansible-управление сертификатами](../Ansible/ansible_certificate_management.md) или скрипт на шлюзе). Утрата устройства = отзыв его сертификата в CA + удаление пира.
- **SSoT по общей теории PKI**: [PKI — обзор](../Security/Concepts/pki_overview.md).

Для полноценного сценария «сертификат как доступ» проще выбрать OpenVPN или mesh-контроллер с нативной PKI (см. [vpn-authentication.md](./vpn-authentication.md)).

### 7. Массовый отзыв при компрометации

При инциденте «краткий ключ одного клиента» одного пира мало — ротируются **все** ключи пересечённого контура, т.к. неизвестен масштаб утечки. Скрипт массового отзыва на всех шлюзах:

```bash
#!/bin/bash
# revoke_all_clients.sh <old_pubkey_prefix>
# 1. Убрать пир со всех шлюзов
for gw in 10.0.0.1 10.0.0.2; do
  ssh root@$gw \
    "wg set wg0 peer <old_pubkey> remove; wg-quick save wg0" || \
    echo "WARN: $gw не обновлён"
done
# 2. Сгенерировать новые ключи всем затронутым клиентам
# 3. Обновить инвентарь inventory.csv (см. §2)
```

Для mesh-контуров (Headscale/Netbird) массовый отзыв сводится к удалению узлов и перевыпуску ключей координатором (см. [mesh-vpn-overview.md](./mesh-vpn-overview.md)).

### 8. Регламентные тайминги и метрики процесса

Чтобы управление флотом было измеримым, ведите числовые цели:

| Метрика | Формула / норма | Инструмент |
|---------|-----------------|------------|
| **Время выдачи клиента** (onboarding) | от заявки до готового конфига; норма ≤ 10 мин при автоматизации | скрипт §2 + `time`, трекер заявок |
| **Частота ротации** | серверные ключи — 1-2 раза в год; клиентские — при увольнении/компрометации, иначе 6-12 мес | поле `ROTATION` в `inventory.csv` |
| **Полнота инвентаря** | 100% пиров имеют владельца и дату выдачи | аудит CSV + `wg show` |
| **Время отзыва** | от увольнения до удаления пира и (при PKI) отзыва сертификата ≤ 30 мин | runbook увольнения |

SLO на эти процессы и алертинг по расхождению инвентаря и фактических пиров строятся по [vpn-monitoring.md](./vpn-monitoring.md).

## Дополнительная информация

- **[VPN Automation — Ansible и Terraform](../Networking/Tunnels/vpn_automation.md)** — роли для WireGuard/OpenVPN/IPsec, GitOps для VPN
- **[Vpn/wireguard.md](./wireguard.md)** — генерация ключей, ротация, права доступа, диагностика
- **[Vault — обзор](../Vault/overview.md)** — централизованное хранение секретов, KV и шаблонизация
- **[PKI — обзор](../Security/Concepts/pki_overview.md)** — CA, сертификаты, lifecycle
- **[Сертификатный аудит подключений](./vpn-session-audit.md)** — привязка пиров к владельцам и журнал входов