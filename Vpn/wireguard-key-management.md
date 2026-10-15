# WireGuard: управление ключами и флотом клиентов

**Актуально для:** WireGuard (модуль ядра Linux 1.0.x, `wireguard-tools` 1.0.x); нативная поддержка в ядре Linux 5.6+. Протокол WireGuard v1.

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
# gen_client.sh <имя> <vpn_ip> <владелец>
set -euo pipefail
NAME="$1"; IP="$2"; OWNER="$3"
SERVER_PUB=$(sudo wg show wg0 public-key)
ROTATION_DUE=$(date -u -d "+180 days" +%FT%TZ)

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

# Инвентарь: name,ip,pubkey,issued,rotation_due,owner,status
echo "$NAME,$IP,$CLIENT_PUB,$(date -u +%FT%TZ),$ROTATION_DUE,$OWNER,active" >> /etc/wireguard/inventory.csv
```

При первом создании инвентаря добавьте шапку:

```bash
echo 'name,ip,pubkey,issued,rotation_due,owner,status' | sudo tee /etc/wireguard/inventory.csv
```

Формат колонок: `issued` — дата выдачи, `rotation_due` — плановая дата ротации, `owner` — владелец (связка pubkey→человек, обязательна для аудита — [vpn-session-audit.md](./vpn-session-audit.md)), `status` — `active`/`revoked`. Инвентарь (`inventory.csv`) даёт ответ на вопросы аудита «кому принадлежит адрес» и «когда стоит провести ротацию». Ограничьте доступ:

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
    image: ghcr.io/wg-easy/wg-easy:15
    container_name: wg-easy
    environment:
      # Unattended setup — только при первом старте; после настройки удалить
      INIT_ENABLED: "true"
      INIT_USERNAME: admin
      INIT_PASSWORD: ${WG_PASSWORD}
      INIT_HOST: vpn.example.com
      INIT_PORT: "51820"
    volumes:
      - ./data:/etc/wireguard
      - /lib/modules:/lib/modules:ro
    ports:
      - "51820:51820/udp"
      - "51821:51821/tcp"
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv4.conf.all.src_valid_mark=1
    restart: unless-stopped
```

После запуска WireGuard слушает `51820/udp`, веб-интерфейс — `51821/tcp`; панель выдаёт клиентам QR-коды. Переменные `INIT_*` действуют только при первой настройке — после инициализации удалите их из манифеста (рекомендация проекта: пароль администратора не должен оставаться в compose-файле), сложность пароля проект не проверяет. В продакшене панель закрывают за reverse proxy с TLS и доступом по ролям (см. [VPN Firewall Templates](../Networking/Tunnels/vpn_firewall_templates.md)), а её БД/директории конфигов резервируют так же, как ключи серверов.

### 5. Отзыв доступа и лифтоцикл

```bash
# Удалить пир на всех серверах контура
sudo wg set wg0 peer <pubkey> remove
sudo wg-quick save wg0

# Если клиент ходил через Headscale/Tailscale — отозвать узел
headscale nodes delete --identifier <ID>
```

Отзыв «сразу» не существует: WireGuard не разрывает уже установленные сессии, но после handshake-таймаута клиент с удалённым ключом не сможет переподключиться. Для удалённого немедленного разрыва добавьте в ACL/firewall фильтр по `AllowedIPs` этого клиента.

После отзыва пометьте запись в инвентаре: `status=revoked` (не удаляйте строку — журнал append-only). Для mesh-контроллеров (Headscale/Netbird) массовый отзыв сводится к удалению узлов (см. [mesh-vpn-overview.md](./mesh-vpn-overview.md), операции Headscale — [tailscale.md](./tailscale.md)).

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
# revoke_all_clients.sh <pubkey>
# 1. Убрать пир со всех шлюзов
for gw in 10.0.0.1 10.0.0.2; do
  ssh root@$gw \
    "wg set wg0 peer <pubkey> remove; wg-quick save wg0" || \
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
| **Частота ротации** | серверные ключи — 1-2 раза в год; клиентские — при увольнении/компрометации, иначе 6-12 мес | поле `rotation_due` в `inventory.csv` |
| **Полнота инвентаря** | 100% пиров имеют владельца и дату выдачи | сверка инвентаря и фактических пиров (§11) |
| **Время отзыва** | от увольнения до удаления пира и (при PKI) отзыва сертификата ≤ 30 мин | runbook увольнения |

SLO на эти процессы и алертинг по расхождению инвентаря и фактических пиров строятся по [vpn-monitoring.md](./vpn-monitoring.md).

### 9. Ротация приватного ключа сервера

Смена приватного ключа сервера меняет его публичный ключ: клиентские конфиги со старым `PublicKey` сервера перестают проходить handshake, поэтому операция координированная (частота — по §8).

```bash
# 1. Сгенерировать новый ключ (ещё НЕ применять)
sudo umask 077
wg genkey | sudo tee /etc/wireguard/server_private.key.new | \
  wg pubkey | sudo tee /etc/wireguard/server_public.key.new

# 2. Перерендерить клиентские конфиги с новым серверным pubkey
#    (генератором §2 / Ansible-ролью) и подготовить их к немедленной раздаче

# 3. Применить ключ к живому интерфейсу и сохранить в конфиг
sudo wg set wg0 private-key /etc/wireguard/server_private.key.new
sudo wg-quick save wg0

# 4. Раздать новые клиентские конфиги и проверить восстановление сессий
sudo wg show wg0 latest-handshakes

# 5. После контрольного окна убрать старый ключевой файл
sudo shred -u /etc/wireguard/server_private.key.old 2>/dev/null || sudo rm -f /etc/wireguard/server_private.key.old
```

**Откат:** вернуть старый ключ (`sudo wg set wg0 private-key /etc/wireguard/server_private.key.old`) и отдать клиентам прежние конфиги.

Нулевой простой штатно недостижим — клиенты со старым конфигом не пройдут handshake после шага 3. Обходные пути: maintenance window с раздачей конфигов вплотную к шагу 3, либо второй интерфейс на новом порту с новым ключом и поэтапный перевод клиентов на новый Endpoint, после чего старый интерфейс выводится. На HA-паре ключ ротируется синхронно на обоих узлах через `wg syncconf` — [wireguard-ha.md](./wireguard-ha.md).

### 10. PresharedKey (PSK) на флоте

Теория и свойства PSK — [wireguard.md](./wireguard.md). На уровне флота PSK назначают высокозначимым пирам (site-to-site, админ-доступ) как дополнительный слой: украденный приватный ключ клиента без верного PSK не позволяет читать трафик этого пира.

```bash
# На сервере: PSK принимается только файлом (wg(8)), не строкой
sudo umask 077
wg genpsk | sudo tee /etc/wireguard/peers/<name>.psk
sudo wg set wg0 peer <pubkey> preshared-key /etc/wireguard/peers/<name>.psk
sudo wg-quick save wg0
```

`PresharedKey` должен совпадать на обеих сторонах — включите его в клиентский конфиг при выдаче. Ротация PSK — та же процедура с новым файлом; значение синхронизируется на HA-паре и в шаблонах тем же способом, что и приватные ключи. PSK дополняет основные ключи, но не отменяет их ротацию.

### 11. Сверка инвентаря с фактическим состоянием

Живой пир без записи в инвентаре — инцидент (алертинг — [vpn-monitoring.md](./vpn-monitoring.md)). Сверка идёт по обоим направлениям:

```bash
# Фактические пиры шлюза
sudo wg show wg0 peers | sort > /tmp/live.txt

# Активные записи инвентаря (отозванные не сверяем)
awk -F, 'NR>1 && $7=="active" {print $3}' /etc/wireguard/inventory.csv | sort > /tmp/inv.txt

comm -13 /tmp/inv.txt /tmp/live.txt   # живые пиры без записи в инвентаре → инцидент
comm -23 /tmp/inv.txt /tmp/live.txt   # активные записи без пира → уточнить, пометить revoked
```

Запускайте по таймеру (cron/systemd timer) и после каждой массовой операции; для нескольких шлюзов — той же петлёй ssh, что в §7. Привязка pubkey к владельцу и расширение формата под расследования — [vpn-session-audit.md](./vpn-session-audit.md).

## Типичные ошибки и диагностика

| Симптом | Причина | Действия |
|---------|---------|----------|
| `Permission denied` при `wg set` | нет root/`CAP_NET_ADMIN` | запускать от root (sudo); в контейнере — `cap_add: [NET_ADMIN]` |
| Правки `wg0.conf` «пропали» после `wg-quick save` | `save` переносит runtime-состояние в файл: peers, не применённые через `wg set`, затираются | править conf и применять `sudo wg syncconf wg0 /etc/wireguard/wg0.conf` (не разрывает сессии) |
| Новый клиент не подходит, handshake отсутствует | в клиентском конфиге чужой/устаревший серверный pubkey или неверный Endpoint | сверить `sudo wg show wg0 public-key` с `PublicKey` в клиентском конфиге |
| После добавления пира пропал трафик у другого клиента | пересекающиеся `AllowedIPs`: при cryptokey routing поздно добавленный пир забирает маршрут overlapping-диапазона | `sudo wg show wg0 allowed-ips`; на клиентских пирах — уникальные `/32` |
| Handshake появляется только после трафика от клиента | клиент за NAT, keepalive не задан | `PersistentKeepalive = 25` в клиентском конфиге (см. генератор §2) |
| Утерян приватный ключ клиента | восстановление невозможно по дизайну — escrow приватных ключей не ведётся | отозвать старый пир (§5), выпустить новый (§1) |
| Пир есть в CSV, но нет на шлюзе (и наоборот) | ручные правки без записи в инвентарь | сверка §11; любой живой пир без владельца — инцидент |

## Лучшие практики

- **Приватные ключи и PSK в Git не хранятся в открытом виде.** В репозиторий — только публичные ключи и шаблоны; секреты — через Ansible Vault / HashiCorp Vault (§3, [VPN Automation](../Networking/Tunnels/vpn_automation.md)).
- **Генерация — с `umask 077`**, файлы ключей `600`, каталог `/etc/wireguard/clients` — `700`, владелец — root (закреплено в §2).
- **Передача клиентского конфига** — только защищённым каналом (scp, QR из панели, одноразовая ссылка); не почтой и не открытыми мессенджерами. Приватный ключ клиента должен сгенерироваться на устройстве клиента либо быть одноразово импортирован и удалён с сервера.
- **Инвентарь append-only:** отозванные записи не удаляются, а помечаются `status=revoked` — иначе теряется история для расследований ([vpn-session-audit.md](./vpn-session-audit.md)).
- **Ротация по регламенту** (частоты — §8) и немедленный отзыв при увольнении/компрометации (§5, §7); серверный ключ — редкая координированная операция (§9).
- **После ротации удаляйте старые ключевые файлы** (`shred -u` на HDD; на SSD полагайтесь на шифрование диска — `shred` физически не гарантирует стирание).
- **Клиентам — DNS-имя в `Endpoint`, не IP:** смена адреса шлюза не потребует перевыпуска конфигов ([wireguard-ha.md](./wireguard-ha.md), практика 9).
- **Бэкап серверных ключей** — в зашифрованном виде, доступ к хранилищу бэкапа — тот же контроль, что и к самим ключам ([wireguard.md](./wireguard.md), раздел о резервном копировании).
- **Массовые операции (выдача, отзыв, ротация)** — через configuration management, а не точечным ssh: воспроизводимость и отсутствие человеческой ошибки ([VPN Automation](../Networking/Tunnels/vpn_automation.md)).

## Граничные случаи и ограничения

- **HA-пара (Active/Passive):** инвентарь и ключи общие для пары; ротация серверного ключа выполняется синхронно на обоих узлах через `wg syncconf`, порядок — [wireguard-ha.md](./wireguard-ha.md).
- **Site-to-site:** краткий обрыв туннеля при ротации пира может схлопнуть BGP/OSPF-соседство, идущее внутри него — планируйте окно или graceful-переустановку соседства ([wireguard-routing.md](./wireguard-routing.md)).
- **Мобильные клиенты (iOS/Android):** конфиг импортируется целиком (файл/QR), «применить изменения на лету» нет — каждая ротация требует повторного импорта; для флота мобильных устройств удобнее панель с QR (§4) или mesh-контроллер.
- **PSK не заменяет основные ключи:** это симметричный слой поверх Curve25519; его утечка без утечки приватного ключа не даёт атакующему возможность подключиться, но и компрометация PSK — основание для ротации пира.

## Очистка и откат

```bash
# После успешной клиентской ротации — убрать старый ключевой материал
sudo shred -u /etc/wireguard/clients/<name>/private.key.old 2>/dev/null || sudo rm -f /etc/wireguard/clients/<name>/private.key.old

# Откат клиентской ротации: вернуть старый пир на сервере
sudo wg set wg0 peer <old_pubkey> allowed-ips <client_ip>/32
sudo wg-quick save wg0

# Откат серверного ключа (§9): старый ключ возвращается тем же wg set private-key
```

В инвентаре откат отражается записью/возвратом `status` и новой строкой выдачи; удалённые из Vault ключей версии восстанавливаются из версионирования KV v2.

## Дополнительная информация

- **[VPN Automation — Ansible и Terraform](../Networking/Tunnels/vpn_automation.md)** — роли для WireGuard/OpenVPN/IPsec, GitOps для VPN
- **[Vpn/wireguard.md](./wireguard.md)** — генерация ключей, ротация, права доступа, диагностика
- **[Vpn/wireguard-ha.md](./wireguard-ha.md)** — ротация ключей на HA-паре, `wg syncconf`, спарка
- **[Vpn/tailscale.md](./tailscale.md)** — операции с узлами и preauth-ключами Headscale
- **[Vault — обзор](../Vault/overview.md)** — централизованное хранение секретов, KV и шаблонизация
- **[PKI — обзор](../Security/Concepts/pki_overview.md)** — CA, сертификаты, lifecycle
- **[Сертификатный аудит подключений](./vpn-session-audit.md)** — привязка пиров к владельцам и журнал входов
