# Настройка обратной зоны (Reverse Zone)

## Определения

**Обратная зона (Reverse Zone)** — DNS-зона для преобразования IP-адресов в доменные имена с помощью PTR-записей.

**PTR-запись** — ресурсная запись, указывающая на каноническое имя хоста для данного IP-адреса.

## Базовые концепции

### Формат обратных зон

| Диапазон IP | Формат зоны | Пример |
|-------------|-------------|--------|
| `/24` (Class C) | `X.Y.in-addr.arpa` | `16.172.in-addr.arpa` |
| `/16` (Class B) | `Y.in-addr.arpa` | `172.in-addr.arpa` |
| IPv6 | `...ip6.arpa` | `8.b.d.0.1.0.0.2.ip6.arpa` |

### Особенности PTR-записей

- **Администрирование:** Настраиваются владельцем IP-диапазона (провайдер, хостинг)
- **Применение:** Верификация почты (SPF), логирование, диагностика
- **Независимость:** Обратная зона не зависит от прямой зоны

## Практические сценарии

### 1. Настройка обратной зоны на Master

**Объявление зоны в `/etc/bind/named.conf.local`:**

```conf
zone "16.172.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/rev.16.172.in-addr.arpa";
    allow-transfer { 172.16.0.6; };  // IP Slave-сервера
};
```

### 2. Создание файла обратной зоны

**Файл `/etc/bind/zones/rev.16.172.in-addr.arpa`:**

```dns
$TTL 3600
@   IN  SOA  ns1.test.example.com. admin.test.example.com. (
    1           ; Serial
    3h          ; Refresh
    1h          ; Retry
    1w          ; Expire
    1h )        ; Negative TTL

; NS-записи для зоны
    IN  NS  ns1.test.example.com.
    IN  NS  ns2.test.example.com.

; PTR-записи (последние два октета IP в обратном порядке)
5.0     IN  PTR  ns1.test.example.com.
6.0     IN  PTR  ns2.test.example.com.
101.3   IN  PTR  host.test.example.com.
```

**Разбор записей:**

| Запись | IP-адрес | Доменное имя |
|--------|----------|--------------|
| `5.0` | `172.16.0.5` | `ns1.test.example.com.` |
| `6.0` | `172.16.0.6` | `ns2.test.example.com.` |
| `101.3` | `172.16.3.101` | `host.test.example.com.` |

> **Важно:** В обратных зонах октеты IP указываются в обратном порядке (хост.сеть).

### 3. Настройка на Slave-сервере

```conf
zone "16.172.in-addr.arpa" {
    type slave;
    file "/var/lib/bind/rev.16.172.in-addr.arpa";
    masters { 172.16.0.5; };  // IP Master-сервера
};
```

### 4. Проверка и верификация

**Проверка синтаксиса:**

```bash
sudo named-checkconf
sudo named-checkzone 16.172.in-addr.arpa /etc/bind/zones/rev.16.172.in-addr.arpa
```

**Тест разрешения PTR:**

```bash
# Проверка обратной зоны
dig -x 172.16.0.5

# Или явно PTR-запрос
dig @localhost 5.0.16.172.in-addr.arpa PTR
```

**Ожидаемый вывод:**

```
;; ANSWER SECTION:
5.0.16.172.in-addr.arpa.  3600  IN  PTR  ns1.test.example.com.
```

### 5. Делегирование обратной зоны

Для публичных IP обратная зона делегируется провайдером. Пример запроса делегирования:

```dns
; В зоне провайдера
16.172.in-addr.arpa.  IN  NS  ns1.your-server.com.
16.172.in-addr.arpa.  IN  NS  ns2.your-server.com.
```

## Дополнительная информация

**Версии:** BIND 9.18+ (LTS), 9.20+ (ESV).

**Спецификации:** RFC 1035 (PTR-записи), RFC 2317 (делегирование подсетей < /24).

**Применение:** PTR-записи требуются почтовым серверам (SPF-верификация), используются в логировании и диагностике (`traceroute`, `dig -x`).

**Теория:** Общие концепции зон DNS — [dns_zones.md](../../../../Networking/Protocols/DNS/dns_zones.md).

**См. также:** [Master-сервер](./master_server_local_zone.md), [Slave-сервер](./slave_server_configuration.md), [Forwarding-сервер](./forwarding_server.md), [Диагностика](./troubleshooting.md), [DNS-записи](../../../../Networking/Protocols/DNS/dns_records.md).
