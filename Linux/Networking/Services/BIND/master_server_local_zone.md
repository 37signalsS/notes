# Настройка первичного DNS-сервера (Master) для локальной зоны

## Определения

**DNS (Domain Name System — система доменных имен)** — распределенная система для получения информации о доменах.

**Master-сервер (Primary — первичный)** — авторитативный DNS-сервер, на котором хранятся эталонные файлы зоны, доступные для редактирования администратором.

**Авторитативный ответ** — ответ, полученный непосредственно от сервера, ответственного за данную зону (обозначается флагом `aa` в выводе утилиты `dig`).

## Базовые концепции

### Файлы конфигурации

| Файл | Назначение |
|------|------------|
| `/etc/bind/named.conf.local` | Объявление локальных зон |
| `/etc/bind/zones/db.<zone>` | Файл данных зоны (zone file) |

### Параметры записи SOA

Параметры синхронизации и управления зоной определяются в записи **SOA (Start of Authority — начальная запись зоны)**.

Основные поля (Serial, Refresh, Retry, Expire, Negative Cache TTL) и их назначение подробно описаны в разделе **[Зоны DNS и SOA-запись](../../../../Networking/Protocols/DNS/dns_zones.md)**.

## Практические сценарии

### 1. Объявление зоны в `named.conf.local`

```conf
// /etc/bind/named.conf.local

zone "local.lan" {
    type master;
    file "/etc/bind/zones/db.local.lan";
    allow-transfer { 172.16.0.6; };  // IP (Internet Protocol) адрес Secondary-сервера
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
$TTL    604800  ; TTL (Time To Live — время жизни записи в кэше)
@       IN      SOA     ns1.local.lan. root.local.lan. (
                                  2         ; Serial (номер версии, увеличивать при изменениях!)
                             604800         ; Refresh
                              86400         ; Retry
                            2419200         ; Expire
                             604800 )       ; Negative Cache TTL
;
; NS (Name Server) и A (Address) записи для зоны
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
| `SOA` | Основная запись зоны, содержащая метаданные |
| `NS` | Указание на авторитативный сервер имен для зоны |
| `A` | Сопоставление имени хоста с IPv4-адресом |

> **Примечание:** В адресе электронной почты администратора (`root.local.lan.`) точка заменяет символ `@`.

### 3. Проверка и применение

**Проверка синтаксиса:**

```bash
# Проверка основных файлов конфигурации
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
systemctl status bind9  # Проверка статуса службы
```

### 4. Верификация

**Проверка с клиента:**

```bash
# Запрос A-записи у конкретного сервера
dig @<IP-адрес-BIND-сервера> dnsserver.local.lan
```

**Ожидаемый результат:**

```
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 12345
;; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 1, ADDITIONAL: 1

;; ANSWER SECTION:
dnsserver.local.lan.  604800  IN  A  192.168.52.149
```

**Ключевые флаги:**

- `aa` (Authoritative Answer) — ответ от авторитативного сервера.
- `status: NOERROR` — запрос успешно разрешен.

## Дополнительная информация

Актуально для BIND 9.18+ (LTS — Long Term Support, долгосрочная поддержка) и 9.20+ (ESV — Extended Support Version, версия с расширенной поддержкой). Формат Serial обычно следует шаблону `YYYYMMDDNN`.

**Связанные разделы:**

- [Зоны DNS и SOA-запись](../../../../Networking/Protocols/DNS/dns_zones.md) — теоретические основы.
- [Настройка Secondary-сервера](./slave_server_configuration.md) — репликация зон.
- [Обратная зона](./reverse_zone_configuration.md) — преобразование IP в имена.
- [Перенаправляющий сервер](./forwarding_server.md) — настройка Forwarding.
- [Диагностика BIND](./troubleshooting.md) — решение проблем.
- [Типы DNS-записей](../../../../Networking/Protocols/DNS/dns_records.md) — подробный разбор A, NS, PTR и др.
