# Настройка первичного DNS-сервера (Master) для локальной зоны

## Определения

**Master-сервер (Primary)** — авторитативный DNS-сервер, на котором хранятся редактируемые администратором файлы зоны.

**Авторитативный ответ** — ответ от сервера, ответственного за зону (флаг `aa` в выводе `dig`).

> **Теория зон, SOA-записи и ролей серверов** — в [`dns_zones.md`](../../../../Networking/Protocols/DNS/dns_zones.md).

## Базовые концепции

### Файлы конфигурации

| Файл | Назначение |
|------|------------|
| `/etc/bind/named.conf.local` | Объявление локальных зон |
| `/etc/bind/zones/db.<zone>` | Файл данных зоны (zone file) |

### Ключевые параметры SOA

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| **Serial** | Версия зоны (увеличивать при изменениях!) | `YYYYMMDDNN` |
| **Refresh** | Интервал проверки Secondary | 604800 (7 дней) |
| **Retry** | Повтор при ошибке | 86400 (1 день) |
| **Expire** | Макс. время без связи с Master | 2419200 (28 дней) |
| **Negative TTL** | Кэширование ошибок (NXDOMAIN) | 604800 (7 дней) |

## Практические сценарии

### 1. Объявление зоны в `named.conf.local`

```conf
// /etc/bind/named.conf.local

zone "local.lan" {
    type master;
    file "/etc/bind/zones/db.local.lan";
    allow-transfer { 172.16.0.6; };  // IP Secondary-сервера
};
```

### 2. Создание файла зоны

**Шаг 1: Создание директории**

```bash
sudo mkdir -p /etc/bind/zones
sudo chown bind:bind /etc/bind/zones
```

**Шаг 2: Копирование шаблона**

```bash
sudo cp /etc/bind/db.local /etc/bind/zones/db.local.lan
```

**Шаг 3: Редактирование файла зоны**

```dns
;
; BIND data file for local.lan
;
$TTL    604800
@       IN      SOA     ns1.local.lan. root.local.lan. (
                                  2         ; Serial (увеличивать при изменениях!)
                             604800         ; Refresh
                              86400         ; Retry
                            2419200         ; Expire
                             604800 )       ; Negative Cache TTL
;
; NS и A-записи для зоны
@       IN      NS      ns1.local.lan.
ns1     IN      A       192.168.52.149

; A-записи для хостов
dnsserver   IN      A       192.168.52.149
server1     IN      A       192.168.52.150
```

**Разбор записей:**

| Запись | Описание |
|--------|----------|
| `@` | Сама зона (`local.lan`) |
| `SOA` | Start of Authority — основная запись зоны |
| `NS` | Указание на DNS-сервер зоны |
| `A` | Сопоставление имени хоста с IPv4-адресом |

> **Важно:** В email администратора (`root.local.lan.`) точка заменяет символ `@`.

### 3. Проверка и применение

**Проверка синтаксиса:**

```bash
# Проверка основных конфигов
sudo named-checkconf

# Проверка синтаксиса файла зоны
sudo named-checkzone local.lan /etc/bind/zones/db.local.lan
```

**Ожидаемый вывод:**
```
zone local.lan/IN: loaded serial 2
OK
```

**Перезапуск BIND:**

```bash
sudo systemctl restart bind9
systemctl status bind9  # проверка статуса
```

### 4. Верификация

**Проверка с клиента:**

```bash
dig @<IP-BIND-сервера> dnsserver.local.lan
```

**Ожидаемый результат:**

```
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 12345
;; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 1, ADDITIONAL: 1

;; ANSWER SECTION:
dnsserver.local.lan.  604800  IN  A  192.168.52.149
```

**Ключевые флаги:**
- `aa` (Authoritative Answer) — ответ от авторитативного сервера
- `status: NOERROR` — успешное разрешение

## Дополнительная информация

- **Serial Number:** Формат `YYYYMMDDNN` (дата + номер изменения за день)
- **Трансфер зоны:** Secondary-серверы запрашивают обновление при изменении Serial
- **Сопутствующие заметки BIND:**
  - [Настройка Secondary](./slave_server_configuration.md) — добавление резервного сервера
  - [Обратная зона](./reverse_zone_configuration.md) — PTR-записи
  - [Forwarding-сервер](./forwarding_server.md) — перенаправляющий DNS
  - [Диагностика](./troubleshooting.md) — проверка и отладка
  - [DNS-записи](../../../../Networking/Protocols/DNS/dns_records.md) — типы записей
